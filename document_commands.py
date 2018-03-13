#!/usr/bin/env python

from n_utils import COMMAND_MAPPINGS, PATH_COMMANDS, NDT_AND_CONSOLE
from subprocess import Popen, PIPE

CONSOLE_PREFERRED = sorted([cmd.split("=")[0] for cmd in NDT_AND_CONSOLE])
def do_call(command):
    proc = Popen(command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    output, err = proc.communicate()
    return (output + err).strip().replace("'", "\\'")

for command in sorted(COMMAND_MAPPINGS.keys()):
    if command in CONSOLE_PREFERRED:
        continue
    print "### `ndt " + command + "`"
    print ""
    print "```bash"
    print do_call(["ndt", command, "-h"])
    print "```\n"

for command in CONSOLE_PREFERRED:
    print "### `[ndt ]" + command + "`"
    print ""
    print "```bash"
    print do_call([command, "-h"])
    print "```\n"

for script in sorted(PATH_COMMANDS):
    name = script.split("/")[-1]
    print "### `" + name + "`"
    print ""
    print "```bash"
    print do_call([name, "-h"])
    print "```\n"
