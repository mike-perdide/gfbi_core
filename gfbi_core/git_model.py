# git_model.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

import sys
from git import Repo
from git.objects.util import altz_to_utctz_str

from gfbi_core.util import Timezone, DummyCommit, DummyBranch, GfbiException
from gfbi_core import ACTOR_FIELDS, TIME_FIELDS


class GitModel:
    """
        This class represents the list of commits of the current branch of a
        given repository. This class is meant to be Qt-free so that it can be
        used in other ways than gitbuster.
    """

    def __init__(self, directory=".", fake_branch_name="", remote_ref=None):
        """
            Initializes the model with the repository root directory.

            :param directory:
                Root directory of the git repository.
        """
        self._directory = directory

        self._remote_ref = False
        self._current_branch = None

        if fake_branch_name:
            # This is an empy gitModel that will be filled with data from
            # another model
            self._repo = None
            self._current_branch = DummyBranch(fake_branch_name)
        elif remote_ref:
            # This is a model on a remote repository
            self._repo = Repo(directory)
            self._remote_ref = remote_ref
            self._current_branch = False
        else:
            self._repo = Repo(directory)
            self._current_branch = self._repo.active_branch

        self._columns = ['hexsha',
                         'authored_date', 'committed_date',
                         'author_name', 'author_email',
                         'committer_name', 'committer_email',
                         'message', 'parents', 'tree']

        self._changed_branch_once = False
        self._commits = []
        self._unpushed = []

        self._old_branch_name = ""

        if not fake_branch_name:
            self.populate()

    def is_fake_model(self):
        return isinstance(self._current_branch, DummyBranch)

    def is_remote_model(self):
        """
            Returns True if the model is build with a remote.
        """
        return self._remote_info

    def populate(self):
        """
            Populates the model, by constructing a list of the commits of the
            current branch of the given repository.
        """
        if self.is_fake_model():
            raise Exception("You shouldn't try to populate a fake model.")

        self._commits = []
        self._unpushed = []

        if self._remote_ref:
            branch_rev = self._remote_ref.commit
        else:
            branch_rev = self._current_branch.commit

        if self._current_branch and self._current_branch.tracking_branch():
            remote_commits_head = self._current_branch.tracking_branch().commit
        else:
            remote_commits_head = None

        pushed = False
        for commit in self._repo.iter_commits(rev=branch_rev):
            self._commits.append(commit)

            if remote_commits_head is not None and \
               commit.hexsha == remote_commits_head.hexsha:
                pushed = True
            if not pushed:
                self._unpushed.append(commit)

    def is_commit_pushed(self, commit):
        """
            Returns True if the commit has been pushed to the remote branch.

            :param commit:
        """
        if isinstance(commit, DummyCommit):
            return False
        else:
            return not commit in self._unpushed

    def get_branches(self):
        """
            Returns the repository avalaible branches.
        """
        if self._repo:
            return self._repo.branches
        else:
            raise Exception("There is no branches here")

    def get_current_branch(self):
        """
            Returns the model's current branch (maybe a DummyBranch).
        """
        return self._current_branch

    def get_remote_ref(self):
        """
            Returns the model's remote reference.
        """
        return self._remote_ref

    def set_current_branch(self, branch, force=False):
        """
            Sets the model's current branch.
            As populate() is costly, we don't do it automaticaly here.

            :param branch:
                The desired branch to modelize.
            :param force:
                By default, users shouldn't change the branch of a model twice.
                They should create a new model.
        """
        if self._changed_branch_once and not force:
            raise GfbiException("You shouldn't change the branch twice.")

        if self.is_fake_model():
            # This is the moment after we wrote the model, the model is getting
            # real (not fake).
            self._repo = Repo(self._directory)

        self._current_branch = branch
        self._changed_branch_once = True
        self._old_branch_name = branch.name

    def get_commits(self):
        """
            Returns the commit list.
        """
        return self._commits

    def get_columns(self):
        """
            Returns the selected fields names.
        """
        return self._columns

    def row_count(self):
        """
            Returns the count of commits.
        """
        return len(self._commits)

    def column_count(self):
        """
            Returns the count of selected fields names.
        """
        return len(self._columns)

    def data(self, index):
        """
            This method uses the index row to select the commit and the index
            column to select the field to return.

            :param index:
                The index of the wanted information.

            :return:
                Depending on the index column, one of the commit fields.
        """
        return self.orig_data(index)

    def orig_data(self, index):
        commit = self._commits[index.row()]
        column = index.column()
        field = self._columns[column]

        if field in TIME_FIELDS:
            if field == 'authored_date':
                _timestamp = commit.authored_date
                _utc_offset = altz_to_utctz_str(commit.author_tz_offset)
                _tz = Timezone(_utc_offset)
            elif field == 'committed_date':
                _timestamp = commit.committed_date
                _utc_offset = altz_to_utctz_str(commit.committer_tz_offset)
                _tz = Timezone(_utc_offset)
            value = (_timestamp, _tz)
        elif field in ACTOR_FIELDS:
            actor = eval("commit." + field.split('_')[0])
            if '_email' in field:
                value = actor.email
            else:
                value = actor.name
        elif field == "message":
            value = commit.message.rstrip()
        else:
            value = eval("commit." + field)

        return value

    def row_of(self, commit):
        return self._commits.index(commit)

    def get_old_branch_name(self):
        """
            Returns the old name of the branch.
        """
        return self._old_branch_name

    def is_first_commit(self, index):
        """
            Returns true if the index points to the first commit.
            First commit is the last of _commits.
        """
        return index.row() == len(self._commits) - 1
