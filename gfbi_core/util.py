# util.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

from datetime import timedelta, tzinfo
from subprocess import Popen, PIPE
from git import Repo
import codecs


STATUSES = (
    ("both deleted:", "DD"),
    ("added by us:", "AU"),
    ("deleted by them:", "UD"),
    ("added by them:", "UA"),
    ("deleted by us:", "DU"),
    ("both added:", "AA"),
    ("both modified:", "UU")
)
REBASE_PATCH_FILE = ".git/rebase-merge/patch"


class Index:
    """
        This mimics the qModelIndex, so that we can use it in the
        GitModel.data() method when populating the model.
    """

    def __init__(self, row=0, column=0):
        """
            Initialization of the Index object.

            :param row:
                Row number, integer.

            :param column:
                Column number, integer.
        """
        self._row = row
        self._column = column

    def row(self):
        """
            Returns the row number.
        """
        return self._row

    def column(self):
        """
            Returns the column number.
        """
        return self._column


class Timezone(tzinfo):
    """
        Timezone class used to preserve the timezone information when handling
        the commits information.
    """

    def __init__(self, tz_string):
        """
            Initialize the Timezone object with it's string representation.

            :param tz_string:
                Representation of the offset to UTC of the timezone. (i.e.
                +0100 for CET or -0400 for ECT)
        """
        self.tz_string = tz_string

    def utcoffset(self, dt):
        """
            Returns the offset to UTC using the string representation of the
            timezone.

            :return:
                Timedelta object representing the offset to UTC.
        """
        sign = 1 if self.tz_string[0] == '+' else -1
        hour = sign * int(self.tz_string[1:-2])
        minutes = sign * int(self.tz_string[2:])
        return timedelta(hours=hour, minutes=minutes)

    def tzname(self, dt):
        """
            Returns the offset to UTC string representation.

            :return:
                Offset to UTC string representation.
        """
        return self.tz_string

    def dst(self, dt):
        """
            Returns a timedelta object representing a whole number of minutes
            with magnitude less than one day.

            :return:
                timedelta(0)
        """
        return timedelta(0)


class DummyCommit:

    def __init__(self):
        self.author_tzinfo = None
        self.committer_tzinfo = None
        self.binsha = 0


class HistoryAction:

    def revert(self, model):
        pass


class InsertAction(HistoryAction):

    def __init__(self, insert_position, commit, modifications):
        self._insert_position = insert_position
        self._commit = commit
        self._modifications = modifications

    def undo(self, model):
        model.remove_rows(self._insert_position, 1, ignore_history=True,
                          really_remove=True)

    def redo(self, model):
        model.insert_commit(self._insert_position, self._commit,
                            self._modifications)


class SetAction(HistoryAction):

    def __init__(self, set_index, old_value, new_value):
        self._set_index = set_index
        self._old_value = old_value
        self._new_value = new_value

    def undo(self, model):
        model.set_data(self._set_index, self._old_value, ignore_history=True)

    def redo(self, model):
        model.set_data(self._set_index, self._new_value, ignore_history=True)


class RemoveAction(HistoryAction):

    def __init__(self, remove_position, commit, modifications):
        self._remove_position = remove_position
        self._commit = commit
        self._modifications = modifications

    def undo(self, model):
        model.undelete_commit(self._commit, self._modifications)

    def redo(self, model):
        model.remove_rows(self._remove_position, 1, ignore_history=True)


class SetBranchNameAction(HistoryAction):

    def __init__(self, old_name, new_name):
        self._old_name = old_name
        self._new_name = new_name

    def undo(self, model):
        model.set_new_branch_name(self._old_name, ignore_history=True)

    def redo(self, model):
        model.set_new_branch_name(self._new_name, ignore_history=True)


class DummyBranch:

    def __init__(self, name):
        self.name = name
        self.path = name


class GfbiException(Exception):
    pass


def run_command(command):
    process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    output, errors = process.communicate()

    return output.split('\n'), errors.split('\n')


def get_unmerged_files(conflicting_hexsha, orig_hexsha, directory):
    """
        Collect several information about the current unmerged state.

        :param from_hexsha, to_hexsha:
            These parameters are used to provide the diff that should have been
            applied by the conflicting commit.
    """
    u_files = {}

    # Fetch diffs
    provide_unmerged_status(u_files)
    provide_diffs(u_files, conflicting_hexsha)
    provide_unmerged_contents(u_files)
    provide_orig_contents(u_files, orig_hexsha, directory)

    return u_files


def provide_unmerged_status(u_files):
    """
        Reads the output of 'git status' to find the unmerged statuses.
    """
    command = "git --no-pager status"
    output, errors = run_command(command)
    for line in output:
        for status, short_status in STATUSES:
            if status in line:
                u_file = line.split(status)[1].strip()
                git_status = short_status
                u_files.setdefault(u_file, {})["git_status"] = git_status
                break


def provide_diffs(u_files, conflicting_hexsha):
    """
        Process the output of git diff rather than calling git diff on
        every file in the path.
    """
    command = "git --no-pager diff %s~ %s" % \
            (conflicting_hexsha, conflicting_hexsha)
    diff_output, errors = run_command(command)

    u_file = None
    diff = ""
    for line in diff_output:
        if line[:10] == 'diff --git':
            if u_file and diff:
                u_files.setdefault(u_file, {})["diff"] = diff
                diff = ""
            u_file = line.split('diff --git a/')[1].split(' ')[0]

            if u_file not in u_files:
                # This isn't an unmerged file, don't log the diff
                u_file = None

        if u_file:
            diff += line + "\n"

    # Write the last diff
    if u_file:
        u_files.setdefault(u_file, {})["diff"] = diff


def provide_unmerged_contents(u_files):
    """
        Fetches the unmerged contents of the files.
    """
    # Make a backup of the unmerged file.
    for u_file, file_info in u_files.items():
        short_status = file_info["git_status"]
        unmerged_content = ""
        if not short_status == "DD":
            handle = codecs.open(u_file, encoding='utf-8', mode='r')
            unmerged_content = handle.read()
            handle.close()
        u_files.setdefault(u_file, {})["unmerged_content"] = unmerged_content


def provide_orig_contents(u_files, orig_hexsha, directory):
    """
        This method fetches the content of the files before the merge.

        Possible optimization: use git.repo.tree.
    """
    repo = Repo(directory)
    commit = repo.commit(rev=orig_hexsha)
    tree = commit.tree

    # Use Commit.tree[file].data_stream.read()
    for u_file, file_info in u_files.items():
        git_status = file_info["git_status"]
        orig_content = ""
        if git_status not in ('UA', 'DU', 'DD'):
            blob = tree[u_file]
            orig_content = blob.data_stream.read()
        u_files.setdefault(u_file, {})["orig_content"] = orig_content


def apply_solutions(solutions):
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

        run_command(command % filepath)
