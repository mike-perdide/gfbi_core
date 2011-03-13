# git_model.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt
#
# -*- coding: utf-8 -*-

from time import mktime
from datetime import datetime

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
from subprocess import Popen, PIPE
from random import random
#from random import uniform

from gfbi_core.util import Timezone, Index
from gfbi_core.git_filter_branch_process import git_filter_branch_process, \
                                        TEXT_FIELDS, ACTOR_FIELDS, TIME_FIELDS
from gfbi_core.git_rebase_process import git_rebase_process
from gfbi_core.non_continuous_timelapse import non_continuous_timelapse

NAMES = {'actor':'Actor', 'author':'Author',
             'authored_date':'Authored Date', 'committed_date':'Committed Date',
             'committer':'Committer', 'count':'Count', 'diff':'Diff',
             'diffs':'Diffs', 'find_all':'Find All', 'hexsha':'Id',
             'lazy_properties':'Lazy Properties',
             'list_from_string':'List From String', 'message':'Message',
             'parents':'Parents', 'repo':'Repo', 'stats':'Stats',
             'summary':'Summary', 'tree':'Tree'}
NOT_EDITABLE_FIELDS = ['hexsha']


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

        # Contains modifications, indexed by [Commit][field_name]
        self._modifications = {}

        # Contains the modified list of commits (original + inserted - deleted)
        self._enlarged = []

        self._show_modifications = True

        self._columns = []
        self._merge = False
        self._git_process = None

        self._changed_branch_once = False

        self.populate()

    def populate(self, filter_count=0, filter_score=None):
        """
            Populates the model, by constructing a list of the commits of the
            current branch of the given repository.

            :param filter_count:
                The number of display filters configured.
            :param filter_score:
                The filter method used to determine whether a field matches the
                configured criteria. The return value is 0 if the field doesn't
                match. The return value is 1 or more if the fields matches one
                or more.
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

        if filter_score:
            iterator = 0
            filtered_commits = {}

            for commit in self._repo.iter_commits():
                for field_index in range(len(self._columns)):
                    index = Index(row=iterator, column=field_index)
                    if commit not in filtered_commits:
                        filtered_commits[commit] = 0
                    filtered_commits[commit] += filter_score(index)
                iterator += 1

            self._commits = []
            for commit in self._repo.iter_commits():
                if filtered_commits[commit] >= filter_count:
                    self._commits.append(commit)

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
        self._changed_branch_once
        self._modifications = {}
        self._enlarged = []

    def get_commits(self):
        """
            Returns the commit list.
        """
        return self._commits

    def get_modifications(self):
        """
            Returns the modified values dictionnary.
        """
        return self._modifications

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
        commit = self._commits[index.row()]
        column = index.column()
        field = self._columns[column]

        if self._show_modifications and self.is_modified(index):
            modification = self._modifications[commit]
            if field in TIME_FIELDS:
                if field == 'authored_date':
                    _timestamp = modification[field]
                    _offset = altz_to_utctz_str(commit.author_tz_offset)
                    _tz = Timezone(_offset)
                elif field == 'committed_date':
                    _timestamp = modification[field]
                    _offset = altz_to_utctz_str(commit.committer_tz_offset)
                    _tz = Timezone(_offset)
                value = (_timestamp, _tz)
            else:
                value = modification[field]
        else:
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
                actor = eval("commit." + field)
                value = (actor.name, actor.email)
            elif field == "message":
                value = commit.message.rstrip()
            else:
                value = eval("commit." + field)
        return value

    def set_merge(self, merge_state):
        """
            Set the merge option, meaning that the committed and authored
            notions are merged. For instance, if the committed date is changed
            in the set_data() method, the authored date will be set with the
            same value.

            :param merge_state:
                Boolean, sets the merge option.
        """
        self._merge = merge_state

    def set_columns(self, column_list):
        """
            Set the fields that will be returned as columns.

            :param list:
                A list of commit field names.
        """
        self._columns = []
        for item in column_list:
            if item in NAMES:
                self._columns.append(item)

    def set_data(self, index, value):
        """
            Set the given value to the commit and the field determined by the
            index.

            :param index:
                The index of the commit and the field that should be modified.
            :param value:
                The value that will be assigned.
        """
        commit = self._commits[index.row()]
        column = index.column()
        field_name = self._columns[column]

        if field_name in TIME_FIELDS:
            reference, tz = self.data(index)
        else:
            reference = self.data(index)

        if reference != value:
            self.set_field_data(commit, field_name, value)

            if self._merge:
                if field_name == "committed_date":
                    self.set_field_data(commit, "authored_date", value)
                elif field_name == "authored_date":
                    self.set_field_data(commit, "committed_date", value)
                elif field_name == "author":
                    self.set_field_data(commit, "committer", value)
                elif field_name == "committer":
                    self.set_field_data(commit, "author", value)

            self.dirty = True

    def set_field_data(self, commit, field, value):
        """
            This method is used in set_data() to assign the given value to the
            given field of the given commit.

            :param commit:
                The commit that will be modified.
            :param field:
                The field that will be modified.
            :param value:
                The value that will be assigned.
        """
        if commit not in self._modifications:
            self._modifications[commit] = {}
        self._modifications[commit][field] = value

    def insert_commit(self, commit, parent):
        """
            The parent commit is the previous commit in the history.
        """
        insert_index = self._commits.index(parent)
        self._commits.insert(insert_index, commit)
        self._modifications[commit] = {}

    def is_modified(self, index):
        """
            Returns True if the commit field determined by the index has been
            modified (if there is a corresponding entry in the _modifications
            dict).

            :param index:
                Index of the field of the commit.

            :return:
                True if the field of the commit is modified else False.
        """
        commit = self._commits[index.row()]
        column = index.column()
        field_name = self._columns[column]

        mods = self._modifications
        if commit in mods and field_name in mods[commit]:
            return True
        return False

    def original_data(self, index):
        """
            Returns the original data, even if the commit field pointed by the
            index has been modified.

            :param index:
                Index of the field of the commit.

            :return:
                The original value of the field of the commit.
        """
        commit = self._commits[index.row()]
        column = index.column()

        value = eval("commit."+self._columns[column])
        return value

    def toggle_modifications(self):
        """
            Toggle the show/hide modifications option. If unset, data() will act
            like original_data(). If not, it will return the modified value of
            the field of the commit, if it has been modified.
        """
        if self._show_modifications:
            self._show_modifications = False
        else:
            self._show_modifications = True

    def show_modifications(self):
        """
            Returns the current toggleModifications option state.
        """
        return self._show_modifications

    def write(self, log=False, script=False):
        """
            Start the git filter-branch command and therefore write the
            modifications stored in _modifications.

            :param log:
                Boolean, set to True to log the git command.
            :param script:
                Boolean, set to True to generate a git filter-branch script that
                can be used by on every checkout of the repository.
        """
        # Write only if there is modified commits
        oldest_commit_parent = self.oldest_modified_commit_parent()
        self._git_process = git_rebase_process(self,
                                   directory=self._directory,
                                   commits=self._commits,
                                   modifications=self._modifications,
                                   oldest_commit_parent=oldest_commit_parent,
                                   log=log, script=script,
                                   branch=self._current_branch)
                           # git_filter_branch_process(self,
                           #        directory=self._directory,
                           #        commits=self._commits,
                           #        modifications=self._modifications,
                           #        oldest_commit_parent=oldest_commit_parent,
                           #        log=log, script=script)

        self._git_process.start()

    def is_finished_writing(self):
        """
            Returns False if the git command process isn't finished else True.
        """
        if self._git_process is not None:
            return self._git_process.is_finished()
        return True

    def progress(self):
        """
            Returns the git command process progress.
        """
        if self._git_process is not None:
            return self._git_process.progress()
        return 0

    def oldest_modified_commit_parent(self):
        """
            Returns a string with the oldest modified commit's parent hexsha or
            None if the oldest modified commit is the first one.

            :return:
                The hexsha of the last modified commit's parent.
        """
        if self._commits:
            parent = None
            for commit in reversed(self._commits):
                if commit in self._modifications:
                    break
                parent = commit

            if parent:
                return parent
            else:
                return None

        else:
            return False

    def erase_modifications(self):
        """
            Erase all modifications: set _modified to {}.
        """
        self._modifications = {}

    def reorder_commits(self, dates, times, weekdays):
        """
            This method reorders the commits given specified timelapses and
            weekdays.
        """
        timelapse = non_continuous_timelapse(dates, times, weekdays)

        ## Random method
        #delta = truc_truc.get_total_seconds() / (how_many_commits + 1)
        #max_error = delta / 2
        #
        #time_cursor = 0
        #for commit in xrange(how_many_commits):
        #    time_cursor += delta
        #    # The next lines sets the commit_time to time_cursor, plus or less
        #    # an error
        #    new_commit_time = time_cursor + int((random() * 2 - 1) * max_error)

        # Uniform method
        total_seconds = timelapse.get_total_seconds()
        distribution = [int(random() * total_seconds)
                        for commit in xrange(len(self._commits))]
        distribution.sort()

        index = 0
        for commit in self._commits:
            this_distribution = distribution[index]
            new_commit_time = timelapse.datetime_from_seconds(this_distribution)
            self.set_field_data(commit, "authored_date",
                                int(mktime(new_commit_time.timetuple())))
            self.set_field_data(commit, "committed_date",
                                int(mktime(new_commit_time.timetuple())))

            index += 1
