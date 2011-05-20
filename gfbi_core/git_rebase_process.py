# git_filter_branch_process.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt
#
# -*- coding: utf-8 -*-

from datetime import datetime
from subprocess import Popen, PIPE
from threading import Thread
from tempfile import mkstemp
import os

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


def run_command(command):
#    print "running %s" % command
    process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    process.wait()
    errors = process.stderr.read()
    if "error: could not apply" in errors:
        return False
    return True


def run_get_output(command):
    process = Popen(command, shell=True, stdout=PIPE)
    process.wait()
    return process.stdout.readlines()


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
        self._script = script
        self._model = parent
        self._directory = parent._directory
        self._branch = parent._current_branch

        self._to_rewrite_count = self._model.get_to_rewrite_count()

        self._u_files = {}
        self._output = []
        self._errors = []
        self._progress = None
        self._finished = False

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
            _dt = datetime.fromtimestamp(_timestamp).replace(tzinfo=_tz)
            value = _dt.strftime("%a %b %d %H:%M:%S %Y %Z")
            commit_settings = add_assign(commit_settings, field, value)

        field = "message"
        index = Index(row=row, column=columns.index(field))
        message = self._model.data(index)

        message = message.replace('\\', '\\\\')
        message = message.replace('$', '\\\$')
        # Backslash overflow !
        message = message.replace('"', '\\\\\\"')
        message = message.replace("'", "'\"\\\\\\'\"'")
        message = message.replace('(', '\(')
        message = message.replace(')', '\)')

        return commit_settings, message

    def run(self):
        """
            Main method of the script. Launches the git command and
            logs/generate scripts if the options are set.
        """
        os.chdir(self._directory)
        run_command('git checkout %s -b tmp_rebase' %
                    self._oldest_parent.hexsha)
        oldest_index = self._oldest_parent_row

        self._progress = 0
        for row in xrange(oldest_index - 1, -1, -1):
            hexsha = self._model.data(Index(row=row, column=0))
            FIELDS, MESSAGE = self.prepare_arguments(row)

            if not run_command('git cherry-pick -n %s' % hexsha):
                # We have a merge conflict.
                self._model.set_conflicting_commit(row)
                self.get_unmerged_files()
                run_command('git reset HEAD --hard')
                run_command('git checkout %s' % self._branch)
                run_command('git branch -D tmp_rebase')
                self._finished = True
                return False
            run_command(FIELDS + ' git commit -m "%s"' % MESSAGE)

            self._progress += 1 / self._to_rewrite_count

        run_command('git branch -M %s' % self._branch)
        self._finished = True
        self._model.populate()

        return True

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
        self._u_files = {}

        # Fetch diffs
        diffs = self.process_diffs()

        command = "git st"
        output = run_get_output(command)

        for line in output:
            for status, short_status in STATUSES:
                if status in line:
                    self.process_unmerged_line(line, status,
                                               short_status, diffs)
                    break

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
            diff_output = run_get_output(command)
        else:
            return diffs

        u_file = None
        diff = ""
        for line in diff_output:
            if line[:10] == 'diff --git':
                if u_file:
                    diffs[u_file] = diff
                u_file = line.split('diff --git a/')[1].split(' ')[0]

            diff += line

        diffs[u_file] = diff

        return diffs

    def process_unmerged_line(self, line, status, short_status, diffs):
        """
            Process the given line wich should contain a path and the reason
            why the merge conflicted.
        """
        u_file = line.split(status)[1].strip()
        handle, tmp_file = mkstemp()
        diff = diffs[u_file]

        # Make a backup of the unmerged file.
        command = "cp %s %s" % (u_file, tmp_file)
        run_command(command)

        model = self._model
        model_columns = model.get_columns()

        conflicting_commit = model.get_conflicting_commit()
        conflicting_row = model.get_conflicting_row()

        if short_status[0] == 'D' or short_status[1] == 'A':
            # Meaning the file is not present in the tree before the
            # conflicting commit.
            orig_content = ""
        else:
            # We're going to fetch the tree object of the commit that was
            # applied before the merge conflict. That commit is located at
            # conflicting _row + 1.
            tree_column = model_columns.index('tree')
            tree_index = Index(conflicting_row + 1, tree_column)
            tree = model.data(tree_index)
            orig_content = tree[u_file].data_stream.read()

        if not self._u_files.has_key(short_status):
            self._u_files[short_status] = []

        self._u_files[short_status].append([u_file, orig_content,
                                            tmp_file, diff])
