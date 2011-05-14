# editable_git_model.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt
#
# -*- coding: utf-8 -*-

from time import mktime

from git.objects.util import altz_to_utctz_str
from random import random
#from random import uniform

from gfbi_core.util import Timezone
from gfbi_core.git_model import GitModel
from gfbi_core.git_filter_branch_process import TIME_FIELDS
from gfbi_core.git_rebase_process import git_rebase_process
from gfbi_core.non_continuous_timelapse import non_continuous_timelapse


class EditableGitModel(GitModel):
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
        # Contains modifications, indexed by [operation_id][Commit][field]
        self.orig_model = GitModel(directory=directory)
        self._modifications = {}
        self._merge = False
        self._git_process = None

        GitModel.__init__(self, directory=directory)

    def populate(self):
        """
            Populates the model, by constructing a list of the commits of the
            current branch of the given repository.
        """
        self.orig_model.populate()
        GitModel.populate(self)

    def set_current_branch(self, branch, force=False):
        """
            Sets the model's current branch.

            :param branch:
                The desired branch to modelize.
        """
        if self._changed_branch_once and not force:
            raise Exception("You shouldn't change the branch twice.")

        self.orig_model.set_current_branch(branch, force=force)
        self._modifications = {}

        GitModel.set_current_branch(self, branch, force=force)

    def get_modifications(self):
        """
            Returns the modified values dictionnary.
        """
        return self._modifications

    def get_orig_model(self):
        """
            Returns an unmodified GitModel.
        """
        return self.orig_model

    def data(self, index):
        """
            This method uses the index row to select the commit and the index
            column to select the field to return.

            :param index:
                The index of the wanted information.

            :return:
                Depending on the index column, one of the commit fields.
        """
        if self.is_modified(index):
            return self.modified_data(index)
        else:
            return self.orig_data(index)

    def modified_data(self, index):
        commit = self._commits[index.row()]
        column = index.column()
        field = self._columns[column]

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
        return self.orig_model.data(index)

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