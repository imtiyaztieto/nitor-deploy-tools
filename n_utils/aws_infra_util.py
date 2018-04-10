#!/usr/bin/env python

# Copyright 2016-2017 Nitor Creations Oy
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function
from builtins import str
from builtins import range
from past.builtins import basestring
import collections
import json
import glob
import os
import re
import subprocess
import sys
import yaml
from yaml import ScalarNode, SequenceNode, MappingNode
from copy import deepcopy
from .cf_utils import stack_params_and_outputs, region, resolve_account, expand_vars

stacks = dict()
PARAM_REF_RE = re.compile(r'\(\(([^)]+)\)\)')
CFG_PREFIX = "AWS::CloudFormation::Init_config_files_"
include_dirs = []
if "CF_TEMPLATE_INCLUDE" in os.environ:
    for next_dir in os.environ["CF_TEMPLATE_INCLUDE"].split(":"):
        if not next_dir.endswith(os.path.sep):
            next_dir = next_dir + os.path.sep
        include_dirs.append(next_dir)

include_dirs.append(os.path.join(os.path.dirname(__file__), "includes") +\
                    os.path.sep)

############################################################################
# _THE_ yaml & json deserialize/serialize functions
def descalar(target):
    if isinstance(target, ScalarNode) or isinstance(target, SequenceNode) or \
       isinstance(target, MappingNode):
        if target.tag in INTRISINC_FUNCS:
            return INTRISINC_FUNCS[target.tag](None, '', target)
        else:
            return descalar(target.value)
    elif isinstance(target, list):
        ret = []
        for nxt in target:
            ret.append(descalar(nxt))
        return ret
    else:
        return target


def base64_ctor(loader, tag_suffix, node):
    return {'Fn::Base64': descalar(node.value)}

def findinmap_ctor(loader, tag_suffix, node):
    return {'Fn::FindInMap': descalar(node.value)}

def getatt_ctor(loader, tag_suffix, node):
    return {'Fn::GetAtt': descalar(node.value)}

def getazs_ctor(loader, tag_suffix, node):
    return {'Fn::GetAZs': descalar(node.value)}

def importvalue_ctor(loader, tag_suffix, node):
    return {'Fn::ImportValue': descalar(node.value)}

def join_ctor(loader, tag_suffix, node):
    return {'Fn::Join': descalar(node.value)}

def select_ctor(loader, tag_suffix, node):
    return {'Fn::Select': descalar(node.value)}

def split_ctor(loader, tag_suffix, node):
    return {'Fn::Split': descalar(node.value)}

def sub_ctor(loader, tag_suffix, node):
    return {'Fn::Sub': descalar(node.value)}

def ref_ctor(loader, tag_suffix, node):
    return {'Ref': descalar(node.value)}

def and_ctor(loader, tag_suffix, node):
    return {'Fn::And': descalar(node.value)}

def equals_ctor(loader, tag_suffix, node):
    return {'Fn::Equals': descalar(node.value)}

def if_ctor(loader, tag_suffix, node):
    return {'Fn::If': descalar(node.value)}

def not_ctor(loader, tag_suffix, node):
    return {'Fn::Not': descalar(node.value)}

def or_ctor(loader, tag_suffix, node):
    return {'Fn::Or': descalar(node.value)}

def importfile_ctor(loader, tag_suffix, node):
    return {'Fn::ImportFile': descalar(node.value)}

def importyaml_ctor(loader, tag_suffix, node):
    return {'Fn::ImportYaml': descalar(node.value)}

def merge_ctor(loader, tag_suffix, node):
    return {'Fn::Merge': descalar(node.value)}

INTRISINC_FUNCS = {
  '!Base64': base64_ctor,
  '!FindInMap': findinmap_ctor,
  '!GetAtt': getatt_ctor,
  '!GetAZs': getazs_ctor,
  '!ImportValue': importvalue_ctor,
  '!Join': join_ctor ,
  '!Select': select_ctor,
  '!Split': split_ctor,
  '!Sub': sub_ctor,
  '!Ref': ref_ctor,
  '!And': and_ctor,
  '!Equals': equals_ctor,
  '!If': if_ctor,
  '!Not': not_ctor,
  '!Or': or_ctor,
  '!ImportFile': importfile_ctor,
  '!ImportYaml': importyaml_ctor,
  '!Merge': merge_ctor
}

SOURCED_PARAMS = None

def run_command(command):
    proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    output = proc.communicate()
    if proc.returncode:
        raise Exception("Failed to run " + str(command))
    return output[0]

def _process_line(line, params, used_params):
    key_val = line.split("=", 1)
    if len(key_val) == 2:
        key = re.sub("[^a-zA-Z0-9_]", "", key_val[0].strip())
        if key in os.environ:
            value = os.environ[key]
        else:
            value = key_val[1].strip()
        if value.startswith("\"") and value.endswith("\""):
            value = value[1:-1]
        value = expand_vars(value, used_params, None, [])
        params[key] = value
        used_params[key] = value

def import_parameter_file(filename, params):
    used_params = deepcopy(os.environ)
    used_params.update(params)
    with open(filename, "r") as propfile:
        prevline = ""
        for line in propfile.readlines():
            if line.startswith("#"):
                prevline = ""
                continue
            if line.endswith("\\"):
                prevline = prevline + line[:-1]
            else:
                line = prevline + line
                prevline = ""
                _process_line(line, params, used_params)
        if prevline:
            _process_line(prevline, params, used_params)

def _add_subcomponent_file(component, branch, type, name, files):
    if name:
        os.environ["ORIG_" + type.upper() + "_NAME"] = name
        files.append(component + os.sep + type + "-" + name + os.sep + "infra.properties")
        files.append(component + os.sep + type + "-" + name + os.sep + "infra-" + branch + ".properties")

def load_parameters(component=None, stack=None, serverless=None, docker=None, image=None, branch=None):
    ret = {}
    if not branch:
        if "GIT_BRANCH" in os.environ:
            branch = os.environ["GIT_BRANCH"]
        else:
            branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch.strip().split("/")[-1:][0]
    os.environ["GIT_BRANCH"] = branch
    files = ["infra.properties", "infra-" + branch + ".properties" ]
    if component:
        files.append(component + os.sep + "infra.properties")
        files.append(component + os.sep + "infra-" + branch + ".properties")
        _add_subcomponent_file(component, branch, "stack", stack, files)
        _add_subcomponent_file(component, branch, "serverless", serverless, files)
        _add_subcomponent_file(component, branch, "docker", docker, files)
        _add_subcomponent_file(component, branch, "image", image, files)
        if type(image) == str:
            files.append(component + os.sep + "image" + os.sep + "infra.properties")
            files.append(component + os.sep + "image" + os.sep + "infra-" + branch + ".properties")
    for file in files:
        if os.path.exists(file):
            import_parameter_file(file, ret)
    if "REGION" not in ret:
        ret["REGION"] = region()
    if "ACCOUNT_ID" not in ret:
        account = resolve_account()
        if account:
            ret["ACCOUNT_ID"] = account
    if "GIT_BRANCH" not in ret:
        ret["GIT_BRANCH"] = os.environ["GIT_BRANCH"]
    if "paramEnvId" not in ret:
        ret["paramEnvId"] = os.environ["GIT_BRANCH"]
    if "ORIG_STACK_NAME" in os.environ:
        ret["ORIG_STACK_NAME"] = os.environ["ORIG_STACK_NAME"]
    if "ORIG_DOCKER_NAME" in os.environ:
        ret["ORIG_DOCKER_NAME"] = os.environ["ORIG_DOCKER_NAME"]
        if "DOCKER_NAME" not in ret:
            ret["DOCKER_NAME"] = component + "/" + ret["paramEnvId"] + "-" + ret["ORIG_DOCKER_NAME"]
    if "ORIG_SERVERLESS_NAME" in os.environ:
        ret["ORIG_SERVERLESS_NAME"] = os.environ["ORIG_SERVERLESS_NAME"]
    if "ORIG_IMAGE_NAME" in os.environ:
        ret["ORIG_IMAGE_NAME"] = os.environ["ORIG_IMAGE_NAME"]
    if "JENKINS_JOB_PREFIX" not in ret:
        ret["JENKINS_JOB_PREFIX"] = "aws" + ret["paramEnvId"]
    return ret


def yaml_load(stream):
    for name in INTRISINC_FUNCS:
        yaml.add_multi_constructor(name, INTRISINC_FUNCS[name], Loader=yaml.SafeLoader)
    class OrderedLoader(yaml.SafeLoader):
        pass
    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return collections.OrderedDict(loader.construct_pairs(node))
    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)

    return yaml.load(stream, OrderedLoader)

def yaml_save(data):
    class OrderedDumper(yaml.SafeDumper):
        pass
    def _dict_representer(dumper, data):
        return dumper.represent_mapping(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            list(data.items()))
    OrderedDumper.add_representer(collections.OrderedDict, _dict_representer)
    return yaml.dump(data, None, OrderedDumper)

def json_load(stream):
    return json.loads(stream, object_pairs_hook=collections.OrderedDict)

def json_save(data):
    return json.dumps(data, indent=2)

def json_save_small(data):
    return json.dumps(data, indent=None)

############################################################################
# import_scripts
gotImportErrors = False

# the CF_ prefix is expected already to have been stripped
def decode_parameter_name(name):
    return re.sub('__', '::', name)

def import_script(filename):
    # the "var " prefix is to support javascript as well
    var_decl_re = re.compile(
        r'^(\s*var\s+)?CF_([^\s=]+)[\s="\']*([^#"\'\`]*)(?:["\'\s\`]*)(#optional)?')
    embed_decl_re = re.compile(
        r'^(.*?=\s*)?(.*?)(?:(?:\`?#|//)CF([^#\`]*))[\"\`\s]*(#optional)?')
    arr = []
    with open(filename) as fd:
        for line in fd:
            result = var_decl_re.match(line)
            if result:
                js_prefix = result.group(1)
                encoded_varname = result.group(2)
                var_name = decode_parameter_name(encoded_varname)
                ref = collections.OrderedDict()
                ref['Ref'] = var_name
                ref['__source'] = filename
                if str(result.group(4)) == "#optional":
                    ref['__optional'] = "true"
                    ref['__default'] = str(result.group(3)).strip(" \"'")
                arr.append(line[0:result.end(2)] + "='")
                arr.append(ref)
                if js_prefix:
                    arr.append("';\n")
                else:
                    arr.append("'\n")
            else:
                result = embed_decl_re.match(line)
                if result:
                    prefix = result.group(1)
                    if not prefix:
                        prefix = result.group(2)
                        default_val = ""
                    else:
                        default_val = str(result.group(2)).strip(" \"'")
                    arr.append(prefix + "'")
                    for entry in yaml_load("[" + result.group(3) + "]"):
                        apply_source(entry, filename, str(result.group(4)),
                                     default_val)
                        arr.append(entry)
                    if filename.endswith(".ps1"):
                        arr.append("'\r\n")
                    else:
                        arr.append("'\n")
                else:
                    arr.append(line)
    return arr

def find_include(basefile):
    if os.path.isfile(basefile):
        return basefile
    for search_dir in include_dirs:
        if os.path.isfile(search_dir + basefile):
            return search_dir + basefile
    return None

def find_all_includes(pattern):
    ret = []
    dirs = list(include_dirs)
    dirs.insert(0, "./")
    for search_dir in dirs:
        for next_match in glob.glob( search_dir + pattern):
            ret.append(next_match)
    return ret

def resolve_file(filename, basefile, templateParams):
    resolved = filename % templateParams
    if filename[0] == "/":
        return existing(resolved)
    if re.match(r"^(\.\./\.\./|\.\./|\./)?aws-utils/.*", resolved):
        return existing(find_include(re.sub(r"^(\.\./\.\./|\.\./|\./)?aws-utils/", "", resolved)))
    if re.match(r"^\(\(\s?includes\s?\)\)/.*", filename):
        return existing(find_include(re.sub(r"^\(\(\s?includes\s?\)\)/", "", resolved)))
    base = os.path.dirname(basefile)
    if len(base) == 0:
        base = "."
    return existing(base + "/" + resolved)

def existing(filename):
    if filename and os.path.exists(filename):
        return filename
    else:
        return None

PARAM_NOT_AVAILABLE = "N/A"

def _add_params(target, source, source_prop, use_value):
    if source_prop in source:
        for k, val in list(source[source_prop].items()):
            target[k] = val['Default'] if use_value and 'Default' in val else PARAM_NOT_AVAILABLE

def _get_params(data, template):
    params = dict()

    # first load defaults for all parameters in "Parameters"
    _add_params(params, data, 'Parameters', True)
    if "resources" in data:
        _add_params(params, data['resources'], 'Parameters', True)
        params['ServerlessDeploymentBucket'] = PARAM_NOT_AVAILABLE

    params['STACK_NAME'] = PARAM_NOT_AVAILABLE

    if not 'REGION' in os.environ:
        os.environ['REGION'] = region()
    params['REGION'] = os.environ['REGION']

    if not 'ACCOUNT_ID' in os.environ:
        os.environ['ACCOUNT_ID'] = resolve_account()
    params['ACCOUNT_ID'] = os.environ['ACCOUNT_ID']


    global SOURCED_PARAMS
    if not SOURCED_PARAMS:
        SOURCED_PARAMS = {}
        # then override them with values from infra
        template_dir = os.path.dirname(os.path.abspath(template))
        image_dir = os.path.dirname(template_dir)

        image_name = os.path.basename(image_dir)
        stack_name = os.path.basename(template_dir)
        stack_name = re.sub('^stack-', '', stack_name)
        SOURCED_PARAMS = load_parameters(component=image_name, stack=stack_name)
        SOURCED_PARAMS.update(os.environ)

    params.update(SOURCED_PARAMS)

    # source_infra_properties.sh always resolves a region, account id and stack
    # name
    params["AWS::Region"] = params['REGION']
    params["AWS::AccountId"] = params['ACCOUNT_ID']
    params["AWS::StackName"] = params['STACK_NAME']

    # finally load AWS-provided and "Resources"
    params["AWS::NotificationARNs"] = PARAM_NOT_AVAILABLE
    params["AWS::NoValue"] = PARAM_NOT_AVAILABLE
    params["AWS::StackId"] = PARAM_NOT_AVAILABLE
    _add_params(params, data, 'Resources', False)
    if "resources" in data:
        _add_params(params, data['resources'], 'Resources', False)
    return params

# replaces "((param))" references in `data` with values from `params` argument.
# Param references with no association in `params` are left as-is.
def apply_params(data, params):
    if isinstance(data, collections.OrderedDict) or isinstance(data, dict):
        for k, val in list(data.items()):
            key2 = apply_params(k, params)
            val2 = apply_params(val, params)
            if k != key2:
                del data[k]
            data[key2] = val2
    elif isinstance(data, list):
        for i in range(0, len(data)):
            data[i] = apply_params(data[i], params)
    elif isinstance(data, str) or isinstance(data, str):
        prev_end = None
        res = ''
        for match in PARAM_REF_RE.finditer(data):
            k = match.group(1)
            if k in params:
                span = match.span()
                # support non-string values only when value contains nothing but
                # the reference
                if span[0] == 0 and span[1] == len(data):
                    return params[k]
                res += data[prev_end:span[0]]
                res += params[k]
                prev_end = span[1]
        data = res + data[prev_end:]
    return data

# Applies recursively source to script inline expression
def apply_source(data, filename, optional, default):
    if isinstance(data, collections.OrderedDict):
        if 'Ref' in data:
            data['__source'] = filename
            if optional == "#optional":
                data['__optional'] = "true"
                data['__default'] = default
        for k, val in list(data.items()):
            apply_source(k, filename, optional, default)
            apply_source(val, filename, optional, default)

# returns new data
def import_scripts_pass1(data, basefile, path, templateParams):
    if isinstance(data, collections.OrderedDict):
        templateParams.update(_get_params(data, basefile))
    global gotImportErrors
    if isinstance(data, collections.OrderedDict):
        if 'Fn::ImportFile' in data:
            val = data['Fn::ImportFile']
            script_import = resolve_file(val, basefile, templateParams)
            if script_import:
                data.clear()
                contents = import_script(script_import)
                data['Fn::Join'] = ["", contents]
            else:
                print("ERROR: " + val + ": Can't import file \"" + val + \
                      "\" - file not found on include paths or relative to " + \
                      basefile)
                gotImportErrors = True
        elif 'Fn::ImportYaml' in data:
            val = data['Fn::ImportYaml']
            del data['Fn::ImportYaml']
            yaml_file = resolve_file(val, basefile, templateParams)
            if yaml_file:
                contents = yaml_load(open(yaml_file))
                contents = apply_params(contents, data)
                data.clear()
                if isinstance(contents, collections.OrderedDict):
                    for k, val in list(contents.items()):
                        data[k] = import_scripts_pass1(val, yaml_file, path + \
                                                       k + "_", templateParams)
                elif isinstance(contents, list):
                    data = contents
                    for i in range(0, len(data)):
                        data[i] = import_scripts_pass1(data[i], yaml_file,
                                                       path + str(i) + "_", templateParams)
                else:
                    print("ERROR: " + path + ": Can't import yaml file \"" + \
                          yaml_file + "\" that isn't an associative array or" +\
                          " a list in file " + basefile)
                    gotImportErrors = True
            else:
                if not ('optional' in data and data['optional']):
                    print("ERROR: " + val + ": Can't import file \"" + val + \
                          "\" - file not found on include paths or relative to " + \
                          basefile)
                    gotImportErrors = True
                else:
                    for k in data:
                        del data[k]
            if "optional" in data:
                del data["optional"]
        elif 'Fn::Merge' in data:
            merge_list = data['Fn::Merge']
            if not isinstance(merge_list, list):
                print("ERROR: " + path + ": Fn::Merge must associate to a list in file " + basefile)
                gotImportErrors = True
                return data
            data = import_scripts_pass1(merge_list[0], basefile, path + "0_", templateParams)
            for i in range(1, len(merge_list)):
                merge = import_scripts_pass1(merge_list[i], basefile, path + str(i) + "_", templateParams)
                if isinstance(data, collections.OrderedDict):
                    if not isinstance(merge, collections.OrderedDict):
                        print("ERROR: " + path + ": First Fn::Merge entry " +\
                              "was an object, but entry " + str(i) + " was " + \
                              "not an object: " + str(merge) + " in file " +\
                              basefile)
                        gotImportErrors = True
                    else:
                        for k, val in list(merge.items()):
                            data[k] = val
                elif isinstance(data, list):
                    if not isinstance(merge, list):
                        print("ERROR: " + path + ": First Fn::Merge entry " +\
                              "was a list, but entry " + str(i) + " was not" +\
                              " a list: " + str(merge))
                        gotImportErrors = True
                    else:
                        for k in range(0, len(merge)):
                            data.append(merge[k])
                else:
                    print("ERROR: " + path + ": Unsupported " + str(type(data)))
                    gotImportErrors = True
                    break
        elif 'Ref' in data:
            data['__source'] = basefile
        else:
            for k, val in list(data.items()):
                data[k] = import_scripts_pass1(val, basefile, path + k + "_", templateParams)
    elif isinstance(data, list):
        for i in range(0, len(data)):
            data[i] = import_scripts_pass1(data[i], basefile, path + str(i) + "_", templateParams)
    return data

# returns new data
def import_scripts_pass2(data, templateFile, path, templateParams, resolveRefs):
    global gotImportErrors
    if isinstance(data, collections.OrderedDict):
        if 'Ref' in data:
            var_name = data['Ref']
            if '__source' in data:
                filename = data['__source']
                del data['__source']
            else:
                filename = "unknown"
            if not var_name in templateParams:
                if '__optional' in data:
                    data = data['__default']
                else:
                    print("ERROR: " + path + ": Referenced parameter \"" + \
                          var_name + "\" in file " + filename + \
                          " not declared in template parameters in " + \
                          templateFile)
                    gotImportErrors = True
            else:
                if resolveRefs:
                    data = templateParams[var_name]
                    if data == PARAM_NOT_AVAILABLE:
                        print("ERROR: " + path + ": Referenced parameter \"" +\
                              var_name + "\" in file " + filename +\
                              " is resolved later by AWS; cannot resolve its" +\
                              " value now")
                        gotImportErrors = True
            if '__optional' in data:
                del data['__optional']
            if '__default' in data:
                del data['__default']
        elif 'StackRef' in data:
            stack_var = import_scripts_pass2(data['StackRef'], templateFile,
                                             path + "StackRef_", templateParams,
                                             True)
            data.clear()
            region = stack_var['region']
            stack_name = stack_var['stackName']
            stack_param = stack_var['paramName']
            stack_key = region + "." + stack_name
            if stack_key in stacks:
                stack_params = stacks[stack_key]
            else:
                stack_params = stack_params_and_outputs(region, stack_name)
                stacks[stack_key] = stack_params
            if not stack_param in stack_params:
                sys.exit("Did not find value for: " + stack_param +\
                         " in stack " + stack_name)
            data = stack_params[stack_param]
        else:
            for k, val in list(data.items()):
                data[k] = import_scripts_pass2(val, templateFile, path + k +\
                                               "_", templateParams, resolveRefs)
    elif isinstance(data, list):
        for i in range(0, len(data)):
            data[i] = import_scripts_pass2(data[i], templateFile, path + \
                                           str(i) + "_", templateParams,
                                           resolveRefs)
    return data

def import_scripts(data, basefile):
    global gotImportErrors
    gotImportErrors = False

    data = import_scripts_pass1(data, basefile, "", _get_params(data, basefile))
    data = import_scripts_pass2(data, basefile, "", _get_params(data, basefile), False)
    if gotImportErrors:
        sys.exit(1)
    return data

############################################################################
# extract_scripts
def bash_encode_parameter_name(name):
    return "CF_" + re.sub('::', '__', name)

def encode_script_filename(prefix, path):
    if path.find("UserData_Fn::Base64") != -1:
        return prefix + "-userdata.sh"
    idx = path.find(CFG_PREFIX)
    if idx != -1:
        soff = idx + len(CFG_PREFIX)
        eoff = path.find("_content_", soff)
        cfg_path = path[soff:eoff]
        return prefix + "-" + cfg_path[cfg_path.rfind("/") + 1:]
    return prefix + "-" + path

def extract_script(prefix, path, join_args):
    # print prefix, path
    # "before" and "after" code blocks, placed before and after var declarations
    code = ["", ""]
    var_decls = collections.OrderedDict()
    code_idx = 0
    for element in join_args:
        if isinstance(element, collections.OrderedDict):
            if not 'Ref' in element:
                print("Dict with no ref")
                json_save(element)
            else:
                var_name = element['Ref']
                if not len(var_name) > 0:
                    raise Exception("Failed to convert reference inside " +\
                                    "script: " + str(element))
                bash_varname = bash_encode_parameter_name(var_name)
                var_decl = ""
                #var_decl += "#" + var_name + "\n"
                var_decl += bash_varname + "=\"\";\n"
                var_decls[var_name] = var_decl
                code[code_idx] += "${" + bash_varname + "}"
        else:
            code[code_idx] += element
        code_idx = 1 # switch to "after" block

    filename = encode_script_filename(prefix, path)
    sys.stderr.write(prefix + ": Exported path '" + path + \
                     "' contents to file '" + filename + "'\n")
    with open(filename, "w") as script_file: #opens file with name of "test.txt"
        script_file.write(code[0])
        script_file.write("\n")
        for var_name, var_decl in list(var_decls.items()):
            script_file.write(var_decl)
        script_file.write("\n")
        script_file.write(code[1])
    return filename

# data argument is mutated
def extract_scripts(data, prefix, path=""):
    if not isinstance(data, collections.OrderedDict):
        return
    for k, val in list(data.items()):
        extract_scripts(val, prefix, path + k + "_")
        if k == "Fn::Join":
            if not val[0] == "":
                continue
            if isinstance(val[1][0], basestring) and (val[1][0].find("#!") != 0):
                continue
            script_file = extract_script(prefix, path, val[1])
            del data[k]
            data['Fn::ImportFile'] = script_file

############################################################################
# simple apis
def yaml_to_dict(yaml_file_to_convert):
    data = yaml_load(open(yaml_file_to_convert))
    data = import_scripts(data, yaml_file_to_convert)
    _patch_launchconf(data)
    return data

def yaml_to_json(yaml_file_to_convert):
    data = yaml_to_dict(yaml_file_to_convert)
    return json_save(data)

def yaml_to_yaml(yaml_file_to_convert):
    data = yaml_to_dict(yaml_file_to_convert)
    return yaml_save(data)

def json_to_yaml(json_file_to_convert):
    data = json_load(open(json_file_to_convert).read())
    extract_scripts(data, json_file_to_convert)
    return yaml_save(data)


############################################################################
# misc json
def locate_launchconf_metadata(data):
    if "Resources" in data:
        resources = data["Resources"]
        for val in list(resources.values()):
            if "Type" in val and val["Type"] == "AWS::AutoScaling::LaunchConfiguration" and \
                "Metadata" in val:
                return val["Metadata"]
    return None

def locate_launchconf_userdata(data):
    resources = data["Resources"]
    for val in list(resources.values()):
        if "Type" in val and val["Type"] == "AWS::AutoScaling::LaunchConfiguration":
            if "Properties" in val and "UserData" in val["Properties"] and \
               "Fn::Base64" in val["Properties"]["UserData"] and \
               "Fn::Join" in val["Properties"]["UserData"]["Fn::Base64"] and \
               len(val["Properties"]["UserData"]["Fn::Base64"]["Fn::Join"]) >= 2:
                return val["Properties"]["UserData"]["Fn::Base64"]["Fn::Join"][1]
            else:
                if "Properties" in val and "UserData" in val["Properties"] and \
                   "Fn::Base64" in val["Properties"]["UserData"] and \
                   "Fn::Sub" in val["Properties"]["UserData"]["Fn::Base64"]:
                    return val["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"]
    return None

def reset_launchconf_userdata(data, lc_userdata):
    resources = data["Resources"]
    for val in list(resources.values()):
        if "Type" in val and val["Type"] == "AWS::AutoScaling::LaunchConfiguration":
            val["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"] = lc_userdata

def get_refs(data, reflist=None):
    if not reflist:
        reflist = []
    if isinstance(data, collections.OrderedDict):
        if "Ref" in data:
            reflist.append(data["Ref"])
        for val in list(data.values()):
            get_refs(val, reflist)
    elif isinstance(data, list):
        for ref in data:
            get_refs(ref, reflist)
    return reflist

def _patch_launchconf(data):
    lc_meta = locate_launchconf_metadata(data)
    if lc_meta is not None:
        lc_userdata = locate_launchconf_userdata(data)
        if lc_userdata:
            if isinstance(lc_userdata, list):
                lc_userdata.append("\nexit 0\n# metadata hash: " + str(hash(json_save(lc_meta))) + "\n")
            else:
                lc_userdata += "\nexit 0\n# metadata hash: " + str(hash(json_save(lc_meta))) + "\n"
                reset_launchconf_userdata(data, lc_userdata)
        lc_meta_refs = set(get_refs(lc_meta))
        if len(lc_meta_refs) > 0:
            first = 1
            for ref in lc_meta_refs:
                lc_userdata.append("# metadata params: " if first else ", ")
                lc_userdata.append({"Ref" : ref})
                first = 0
            lc_userdata.append("\n")
