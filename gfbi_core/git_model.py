# git_model.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt
#
# -*- coding: utf-8 -*-

import sys
try:
    from git import Repo
except:
    print """Couldn't import git. You might want to install GitPython from:
    http://pypi.python.org/pypi/GitPython/"""
    sys.exit(1)
try:
    from git import __version__
    str_maj, str_min, str_rev = __version__.split(".")
    _maj, _min, _rev = int(str_maj), int(str_min), int(str_rev)
    if  _maj < 0 or (_maj == 0 and _min < 3) or \
        (_maj == 0 and _min == 3 and _rev < 1):
        raise Exception()
except:
    print "This project needs GitPython (>=0.3.1)."
    sys.exit(1)

from git.objects.util import altz_to_utctz_str

from gfbi_core.util import Timezone
from gfbi_core import ACTOR_FIELDS, TIME_FIELDS


class GitModel:
    """
        This class represents the list of commits of the current branch of a
        given repository. This class is meant to be Qt-free so that it can be
        used in other ways than gitbuster.
    """

    def __init__(self, directory="."):
        """
            Initializes the model with the repository root directory.

            :param directory:
                Root directory of the git repository.
        """
        self._directory = directory
        self._repo = Repo(directory)
        self._current_branch = self._repo.active_branch

        self._columns = ['hexsha',
                     'authored_date', 'committed_date',
                     'author_name', 'author_email',
                     'committer_name', 'committer_email',
                     'message']

        self._changed_branch_once = False
        self._commits = []
        self._unpushed = []

        self.populate()

    def populate(self):
        """
            Populates the model, by constructing a list of the commits of the
            current branch of the given repository.
        """
        self._commits = []
        self._unpushed = []

        branch_rev = self._current_branch.commit
        if self._current_branch.tracking_branch():
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
        return not commit in self._unpushed

    def get_branches(self):
        """
            Returns the repository avalaible branches.
        """
        return self._repo.branches

    def get_current_branch(self):
        """
            Returns the model's current branch.
        """
        return self._current_branch

    def set_current_branch(self, branch, force=False):
        """
            Sets the model's current branch.

            :param branch:
                The desired branch to modelize.
        """
        if self._changed_branch_once and not force:
            raise Exception("You shouldn't change the branch twice.")

        self._current_branch = branch
        self._changed_branch_once = True

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
