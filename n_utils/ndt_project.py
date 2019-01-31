from __future__ import print_function
from builtins import object
import sys
import inspect
from operator import attrgetter
from os import sep, path, mkdir
import re
try:
    from os import scandir, walk
except ImportError:
    from scandir import scandir, walk

from n_utils.git_utils import Git
from n_utils.aws_infra_util import load_parameters

class Component(object):
    subcomponent_classes = []
    def __init__(self, name, project):
        self.name = name
        self.subcomponents = []
        self.project = project
        if not self.subcomponent_classes:
            self.subcomponent_classes = [name_and_obj for name_and_obj in inspect.getmembers(sys.modules["n_utils.ndt_project"]) if name_and_obj[0].startswith("SC") and inspect.isclass(name_and_obj[1])]
    
    def get_subcomponents(self):
        if not self.subcomponents:
            self.subcomponents = sorted(self._find_subcomponents(), key=attrgetter("name"))
        return self.subcomponents
    
    def _find_subcomponents(self):
        ret = []
        for subdir in [de.name for de in scandir(self.project.root + sep + self.name) if self._is_subcomponent(de.name)]:
            for _, obj in self.subcomponent_classes:
                if obj(self, "").match_dirname(subdir):
                    if subdir == "image":
                        sc_name = ""
                    else:
                        sc_name = subdir.split("-")[-1:][0]
                    ret.append(obj(self, sc_name))
        return ret

    def _is_subcomponent(self, dir):
        for name, obj in self.subcomponent_classes:
            if obj(self, "").match_dirname(dir):
                return True
        return False

class SubComponent(object):
    def __init__(self, component, name):
        self.component = component
        self.name = name
        self.type = self.__class__.__name__[2:].lower()

    def get_dir(self):
        return self.component.name + sep + self.type + "-" + self.name

    def match_dirname(self, dir):
        return dir.startswith(self.type + "-")

    def list_row(self, branch):
        return ":".join([self.component.name, branch, self.type, self.name])

    def job_properties_filename(self, branch, root):
        name_arr = [self.type, re.sub(r'[^\w-]', '_', branch), self.component.name, self.name]
        return root + sep + "job-properties" + sep + "-".join(name_arr) + ".properties"

class SCImage(SubComponent):
    def get_dir(self):
        if self.name:
            return self.component.name + sep + "image-" + self.name
        else:
            return self.component.name + sep + "image"

    def match_dirname(self, dir):
        return dir == "image" or dir.startswith("image-")

    def list_row(self, branch):
        if not self.name:
            name = "-"
        else:
            name = self.name
        return ":".join([self.component.name, branch, self.type, name])

    def job_properties_filename(self, branch, root):
        name_arr = [self.type, re.sub(r'[^\w-]', '_', branch), self.component.name]
        if self.name:
            name_arr.append(self.name)
        return root + sep + "job-properties" + sep + "-".join(name_arr) + ".properties"

class SCStack(SubComponent):
    pass

class SCServerless(SubComponent):
    pass

class SCCDK(SubComponent):
    pass

class SCTerraform(SubComponent):
    pass



class Project(object):
    def __init__(self, root="."):
        self.componets = []
        self.root = root if root else guess_project_root
        self.all_subcomponents = []

    def get_components(self):
        if not self.componets:
            self.componets = sorted(self._find_components(), key=attrgetter("name"))
        return self.componets

    def _find_components(self):
        return [Component(de.name, self) for de in scandir(self.root) if de.is_dir() and self._is_component(de.name)]

    def get_all_subcomponents(self):
        if not self.all_subcomponents:
            for component in self.get_components():
                self.all_subcomponents.extend(component.get_subcomponents())
        return self.all_subcomponents

    def _is_component(self, dir):
        return len([de for de in scandir(dir) if de.is_file() and (de.name == "infra.properties" or (de.name.startswith("infra-") and de.name.endswith(".properties")))]) > 0

def guess_project_root():
    
    for guess in [".", Git().get_git_root(), "..", "../..", "../../..", "../../../.."]:
        if len(Project(root=guess).get_all_subcomponents()) > 0:
            if guess == ".":
                return guess
            else:
                return path.abspath(guess)

def list_jobs(export_job_properties=False):
    ret = []
    with Git() as git:
        current_project = Project(root=guess_project_root())
        for branch in git.get_branches():
            if branch == git.get_current_branch():
                project = current_project
            else:
                root = git.export_branch(branch)
                project = Project(root=root)
            for subcomponent in project.get_all_subcomponents():
                ret.append(subcomponent.list_row(branch))
            if export_job_properties:
                #$TYPE-$GIT_BRANCH-$COMPONENT-$NAME.properties
                try:
                    mkdir(current_project.root + sep + "job-properties")
                except OSError as err:
                    if err.errno == 17:
                        pass
                    else:
                        raise err
                for subcomponent in project.get_all_subcomponents():
                    filename = subcomponent.job_properties_filename(branch, current_project.root)
                    prop_args = {
                        "component": subcomponent.component.name,
                        subcomponent.type: subcomponent.name,
                        "branch": branch,
                        "git": git
                    }
                    parameters = load_parameters(**prop_args)
                    with open(filename, 'w+') as prop_file:
                        for key, value in list(parameters.items()):
                            prop_file.write(key + "=" + value + "\n")
    return ret
