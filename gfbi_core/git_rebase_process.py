# git_filter_branch_process.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt
#
# -*- coding: utf-8 -*-

from subprocess import Popen, PIPE
from threading import Thread
import os
import time
import codecs

from gfbi_core.util import Index
from gfbi_core import ENV_FIELDS, ACTOR_FIELDS, TIME_FIELDS


STATUSES = (
    ("both deleted:", "DD"),
    ("added by us:", "AU"),
    ("deleted by them:", "UD"),
    ("added by them:", "UA"),
    ("deleted by us:", "DU"),
    ("both added:", "AA"),
    ("both modified:", "UU")
)


def add_assign(commit_settings, field, value):
    commit_settings += ENV_FIELDS[field] + "='%s'" % value + " "
    return commit_settings


class git_rebase_process(Thread):
    """
        Thread meant to execute and follow the progress of the git command
        process.
    """

    def __init__(self, parent, log=True, script=True):
        """
            Initialization of the GitFilterBranchProcess thread.

            :param parent:
                GitModel object, parent of this thread.
            :param log:
                If set to True, the git filter-branch command will be logged.
            :param script:
                If set to True, the git filter-branch command will be written
                in a script that can be distributed to other developpers of the
                project.
        """
        Thread.__init__(self)

        oldest_parent, oldest_row = parent.oldest_modified_commit_parent()
        self._oldest_parent = oldest_parent
        self._oldest_parent_row = oldest_row

        self._log = log
        if log:
            self._logfile = ".gitbuster_" + time.strftime("%d-%m-%Y.%H-%M")

        self._script = script
        self._model = parent
        self._directory = parent._directory
        self._branch = parent._current_branch

        self._to_rewrite_count = self._model.get_to_rewrite_count()
        self._solutions = self._model.get_conflict_solutions()

        self._u_files = {}
        self._output = []
        self._errors = []
        self._progress = None
        self._finished = False

    def log(self, message):
        if self._log:
            handle = codecs.open(self._logfile, encoding='utf-8', mode='a')
            log_stamp = unicode(time.strftime("[%d-%m-%Y %H:%M:%S] "))
            handle.write(log_stamp + message)
            handle.close()

    def run_command(self, command):
        process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
        process.wait()
        self.log("Running: %s" % command.strip() + "\n")
        errors = process.stderr.readlines()
        output = process.stdout.readlines()

        for line in errors:
            u_line = line.decode('utf-8')
            self.log(u"STDERR: " + u_line + "\n")

        for line in output:
            u_line = line.decode('utf-8')
            self.log(u"STDOUT: " + u_line + "\n")

        return output, errors

    def prepare_arguments(self, row):
        commit_settings = ""
        message = ""
        columns = self._model.get_columns()

        for field in ACTOR_FIELDS:
            index = Index(row=row, column=columns.index(field))
            value = self._model.data(index)
            commit_settings = add_assign(commit_settings, field, value)

        for field in TIME_FIELDS:
            index = Index(row=row, column=columns.index(field))
            _timestamp, _tz = self._model.data(index)
            value = str(_timestamp) + " " + _tz.tzname(None)
            commit_settings = add_assign(commit_settings, field, value)

        field = "message"
        index = Index(row=row, column=columns.index(field))
        message = self._model.data(index)

        message = message.replace('\\', '\\\\')
        message = message.replace('$', '\\\$')
        # Backslash overflow !
        message = message.replace('"', '\\\\\\"')
        message = message.replace("'", "'\"\\\\\\'\"'")

        return commit_settings, message

    def run(self):
        """
            Main method of the script. Launches the git command and
            logs/generate scripts if the options are set.
        """
        os.chdir(self._directory)
        try:
           self.pick_and_commit()
        except Exception, err:
            self.run_command('git reset HEAD --hard')
            self.run_command('git checkout %s' % self._branch)
            self.run_command('git branch -D tmp_rebase')
            raise
        finally:
            self._finished = True

    def pick_and_commit(self):
        """
            This is the method that actually does the rebasing.
        """
        self.run_command('git checkout %s -b tmp_rebase' %
                         self._oldest_parent.hexsha)
        oldest_index = self._oldest_parent_row

        self._progress = 0
        for row in xrange(oldest_index - 1, -1, -1):
            hexsha = self._model.data(Index(row=row, column=0))
            FIELDS, MESSAGE = self.prepare_arguments(row)

            output, errors = self.run_command('git cherry-pick -n %s' % hexsha)
            if [line for line in errors if "error: could not apply" in line]:
                # We have a merge conflict.
                self._model.set_conflicting_commit(row)
                commit = self._model.get_conflicting_commit()
                if commit in self._solutions:
                    self.apply_solutions(self._solutions[commit])
                else:
                    self.get_unmerged_files()
                    self.run_command('git checkout %s' % self._branch)
                    self.run_command('git branch -D tmp_rebase')
                    return False
            self.run_command(FIELDS + ' git commit -m "%s"' % MESSAGE)

            self._progress += 1. / self._to_rewrite_count

        self.run_command('git branch -M %s' % self._branch)
        self._model.populate()

    def apply_solutions(self, solutions):
        """
            This apply the given solutions to the repository.

            :param solutions:
                See EditableGitModel.set_conflict_solutions.
        """
        for filepath, action in solutions.items():
            if action[0] == "delete":
                command = 'git rm %s'
            elif action[0] == "add":
                command = 'git add %s'
            elif action[0] == "add_custom":
                custom_content = action[1]
                handle = codecs.open(filepath, encoding='utf-8', mode='w')
                handle.write(custom_content)
                handle.close()
                command = 'git add %s'

            self.run_command(command % filepath)

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

    def get_unmerged_files(self):
        """
            Makes copies of unmerged files and informs the model about theses
            files.
        """
        self.u_files = {}

        # Fetch diffs
        diffs = self.process_diffs()

        command = "git status"
        output, errors = self.run_command(command)

        for line in output:
            for status, short_status in STATUSES:
                if status in line:
                    self.process_status_line(line, status,
                                             short_status, diffs)
                    break

        command = "git reset --hard"
        self.run_command(command)

        for file, file_info in self._u_files.items():
            git_status = file_info["git_status"]
            if git_status not in ('UA', 'DU', 'DD'):
                handle = codecs.open(file, encoding='utf-8', mode='r')
                orig_content = handle.read()
                handle.close()
                file_info["orig_content"] = orig_content

        self._model.set_unmerged_files(self._u_files)

    def process_diffs(self):
        """
            Process the output of git diff rather than calling git diff on
            every file in the path.
        """
        diffs = {}

        model = self._model
        model_columns = model.get_columns()
        conflicting_row = model.get_conflicting_row()

        hexsha_column = model_columns.index('hexsha')
        hexsha_index = Index(conflicting_row, hexsha_column)
        hexsha = model.data(hexsha_index)

        parents_column = model_columns.index('parents')
        parents_index = Index(conflicting_row, parents_column)
        parents = model.data(parents_index)

        if len(parents) == 1:
            parent = parents[0]
            command = "git diff %s %s" % (parent.hexsha, hexsha)
            diff_output, errors = self.run_command(command)
        else:
            return diffs

        u_file = None
        diff = ""
        for line in diff_output:
            if line[:10] == 'diff --git':
                if u_file:
                    diffs[u_file] = diff
                    diff = ""
                u_file = line.split('diff --git a/')[1].split(' ')[0]

            diff += line

        diffs[u_file] = diff

        return diffs

    def process_status_line(self, line, status, short_status, diffs):
        """
            Process the given line wich should contain a path and the reason
            why the merge conflicted.
        """
        u_file = line.split(status)[1].strip()

        if u_file in diffs:
            diff = diffs[u_file]
        else:
            diff = ""

        # Make a backup of the unmerged file.
        unmerged_content = u""
        if not short_status == "DD":
            handle = codecs.open(u_file, encoding='utf-8', mode='r')
            unmerged_content = handle.read()
            handle.close()

        self._u_files[u_file] = {"unmerged_content" : unmerged_content,
                                 "diff"             : diff,
                                 "orig_content"     : "",
                                 "git_status"       : short_status}
