# git_filter_branch_process.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

from datetime import datetime
from subprocess import Popen, PIPE
from threading import Thread
import os
import fcntl

from git.objects.util import altz_to_utctz_str

from gfbi_core.util import Timezone
from gfbi_core import ENV_FIELDS, TEXT_FIELDS, ACTOR_FIELDS, TIME_FIELDS


def add_assign(env_filter, field, value):
    env_filter += "export " + ENV_FIELDS[field] + ";\n"
    env_filter += ENV_FIELDS[field] + "='%s'" % value + ";\n"
    return env_filter

class git_filter_branch_process(Thread):
    """
        Thread meant to execute and follow the progress of the git command
        process.
    """

    def __init__(self, parent, commits=list(), modifications=dict(),
                 directory=".", oldest_commit_parent=None, log=True,
                 script=True):
        """
            Initialization of the GitFilterBranchProcess thread.

            :param parent:
                GitModel object, parent of this thread.
            :param args:
                List of arguments that will be passed on to git filter-branch.
            :param oldest_commit_parent:
                The oldest modified commit's parent.
            :param log:
                If set to True, the git filter-branch command will be logged.
            :param script:
                If set to True, the git filter-branch command will be written in
                a script that can be distributed to other developpers of the
                project.
        """
        Thread.__init__(self)

        if oldest_commit_parent is None:
            self._oldest_commit = "HEAD"
        else:
            self._oldest_commit = str(oldest_commit_parent.hexsha) + ".."

        self._log = log
        self._script = script
        self._parent = parent
        self._commits = commits
        self._modifications = modifications
        self._directory = directory

        self._output = []
        self._errors = []
        self._progress = None
        self._finished = False

    def prepare_arguments(self):
        env_filter = ""
        commit_filter = ""

        for commit in self._modifications:
            hexsha = commit.hexsha
            env_header = "if [ \"\$GIT_COMMIT\" = '%s' ]; then " % hexsha
            commit_header = str(env_header)

            env_content = ""
            commit_content = ""

            for field in self._modifications[commit]:
                if field in ACTOR_FIELDS:
                    name, email = self._modifications[commit][field]
                    if field == "author":
                        env_content = add_assign(env_content,
                                                 "author_name", name)
                        env_content = add_assign(env_content,
                                                 "author_email", email)
                    elif field == "committer":
                        env_content = add_assign(env_content,
                                                 "committer_name", name)
                        env_content = add_assign(env_content,
                                                 "committer_email", email)
                elif field == "message":
            # Behold, thee who wanders in this portion of the source code.  What
            # you see here may look like the ramblings of a deranged man. You
            # may partially be right, but ear me out before lighting the pyre.
            # The command given to the commit-filter argument is to be
            # interpreted in a bash environment. Therefore, if we want to use
            # newlines, we need to use ' quotes. BUT, and that's where I find it
            # gets hairy, if we already have single quotes in the commit
            # message, we need to escape it. Since escaping single quotes in
            # single quotes string doesn't work, we need to: close the single
            # quote string, open double quotes string, escape the single quote,
            # close the double quotes string, and then open a new single quote
            # string for the rest of the commit message. Now light the pyre.
                    value = self._modifications[commit][field]
                    message = value.replace('\\', '\\\\')
                    message = message.replace('$', '\\\$')
                    # Backslash overflow !
                    message = message.replace('"', '\\\\\\"')
                    message = message.replace("'", "'\"\\\\\\'\"'")
                    message = message.replace('(', '\(')
                    message = message.replace(')', '\)')
                    commit_content += "echo '%s' > ../message;" % message
                elif field in TIME_FIELDS:
                    _timestamp = self._modifications[commit][field]
                    _utc_offset = altz_to_utctz_str(commit.author_tz_offset)
                    _tz = Timezone(_utc_offset)
                    _dt = datetime.fromtimestamp(_timestamp).replace(tzinfo=_tz)
                    value = _dt.strftime("%a %b %d %H:%M:%S %Y %Z")
                    env_content = add_assign(env_content, field, value)

            if env_content:
                env_filter += env_header + env_content +"fi\n"

            if commit_content:
                commit_filter += commit_header + commit_content + "fi;"

        self._args = ""
        if env_filter:
            self._args += '--env-filter "%s" ' % env_filter
        if commit_filter:
            commit_filter += 'git commit-tree \\"\$@\\"\n'
            self._args += '--commit-filter "%s" ' % commit_filter

        if self._args:
            os.chdir(self._directory)

            command = 'rm -fr "$(git rev-parse --git-dir)/refs/original/"'
            process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
            process.wait()

            command = 'rm -fr .git-rewrite"'
            process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
            process.wait()

            return True

        return False

    def run(self):
        """
            Main method of the script. Launches the git command and
            logs/generate scripts if the options are set.
        """
        if not self.prepare_arguments():
            self._finished = True
            return

        clean_pipe = "|tr '\r' '\n'"
        command = "git filter-branch "
        command += self._args + self._oldest_commit

        process = Popen(command + clean_pipe, shell=True,
                        stdout=PIPE, stderr=PIPE)

        # Setting the stdout file descriptor to non blocking.
        fcntl.fcntl(
                process.stdout.fileno(),
                fcntl.F_SETFL,
                fcntl.fcntl(process.stdout.fileno(),
                            fcntl.F_GETFL) | os.O_NONBLOCK,
            )

        while True:
            try:
                line = process.stdout.readline()
            except IOError, error:
                continue

            if not line:
                break

            clean_line = line.replace('\r', '\n')
            self._output.append(clean_line)
            if "Rewrite" in clean_line:
                progress = float(line.split('(')[1].split('/')[0])
                total = float(line.split('/')[1].split(')')[0])
                self._progress = progress/total

        process.wait()
        self._finished = True

        self._errors = process.stderr.readlines()
        if self._log:
            log_file = "./gitbuster.log"
            handle = open(log_file, "a")
            handle.write("=======================\n")
            handle.write("Operation date :" +
                         datetime.now().strftime("%a %b %d %H:%M:%S %Y") +
                        "\n")
            handle.write("===== Command: ========\n")
            handle.write(command + "\n")
            handle.write("===== git output: =====\n")
            for line in self._output:
                handle.write(line.rstrip() + "\n")
            handle.write("===== git errors: =====\n")
            for line in self._errors:
                handle.write(line + "\n")
            handle.close()

        if self._script:
            # Generate migration script
            handle = open("migration.sh", "w")
            handle.write("#/bin/sh\n# Generated by gitbuster on " +
                         datetime.now().strftime("%a %b %d %H:%M:%S %Y") +
                         "\n")
            handle.write(command + "\n")
            handle.close()

        if self._errors:
            for line in self._errors:
                print line
        else:
            self._parent.erase_modifications()

    def progress(self):
        """
            Returns the progress percentage
        """
        return self._progress

    def output(self):
        """
            Returns the output as a list of lines
        """
        return list(self._output)

    def errors(self):
        """
            Returns the errors as a list of lines
        """
        return list(self._errors)

    def is_finished(self):
        """
            Returns self._finished
        """
        return self._finished
