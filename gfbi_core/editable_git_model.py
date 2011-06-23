# editable_git_model.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

from time import mktime

from random import random
#from random import uniform

from gfbi_core import NAMES
from gfbi_core.util import DummyCommit, InsertAction, SetAction, RemoveAction, \
                           SetBranchNameAction, DummyBranch, GfbiException, \
                           Index
from gfbi_core.git_model import GitModel
from gfbi_core import TIME_FIELDS
from gfbi_core.git_filter_rebase import git_filter_rebase
from gfbi_core.non_continuous_timelapse import non_continuous_timelapse
from gfbi_core.validation import validate_branch_name


class EditableGitModel(GitModel):
    """
        This class represents the list of commits of the current branch of a
        given repository. This class is meant to be Qt-free so that it can be
        used in other ways than gitbuster.
    """

    def __init__(self, directory=".", fake_branch_name="", from_commits=False):
        """
            Initializes the model with the repository root directory.

            :param directory:
                Root directory of the git repository.
        """
        if fake_branch_name:
            # This is an empy gitModel that will be filled with data from
            # another model
            self.orig_model = None
        else:
            self.orig_model = GitModel(directory=directory)

        self.init_attributes()

        GitModel.__init__(self, directory=directory,
                          fake_branch_name=fake_branch_name,
                          from_commits=from_commits)

    def init_attributes(self):
        """
            These attributes should be resetted when populating the model.
        """
        self._modifications = {}
        self._deleted_commits = []
        self._merge = False
        self._history = []
        self._last_history_event = -1
        self._conflicting_commit = None
        self._unmerged_files = None
        self._solutions = {}
        self._new_branch_name = ""
        self._git_process = None
        self._start_write_cache = {}
        self._children_cache = {}

    def populate(self):
        """
            Populates the model, by constructing a list of the commits of the
            current branch of the given repository.
        """
        self.init_attributes()

        if not self.is_fake_model():
            self.orig_model.populate()

        GitModel.populate(self)

    def set_current_branch(self, branch, force=False):
        """
            Sets the model's current branch.

            :param branch:
                The desired branch to modelize.
        """
        if self._changed_branch_once and not force:
            raise GfbiException("You shouldn't change the branch twice.")

        if self.is_fake_model():
            # This is the moment after we wrote the model, the model is getting
            # real (not fake).
            self.orig_model = GitModel(directory=self._directory)

        self.orig_model.set_current_branch(branch, force=force)
        self._modifications = {}

        GitModel.set_current_branch(self, branch, force=force)

    def get_modifications(self):
        """
            Returns the modified values dictionnary.
        """
        return self._modifications

    def get_modified_count(self):
        """
            Returns the number of modified or deleted commits.
        """
        modified_or_deleted = set(
            [commit for commit in self._commits
             if self.commit_is_modified(commit) and
                not self.is_deleted(commit)])
        return len(modified_or_deleted)

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

    def c_data(self, commit, field):
        """
            This is a convenient method to access data using the commit and
            the column.
        """
        row = self.row_of(commit)
        col = self.get_column(field)
        return self.data(Index(row, col))

    def modified_data(self, index):
        commit = self._commits[index.row()]
        column = index.column()
        field = self._columns[column]

        value = ""
        if commit in self._modifications:
            modification = self._modifications[commit]
            value = modification[field]

            if value and field in ("children", "parents"):
                value = list(value)

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

    def set_data(self, index, value, ignore_history=False):
        """
            Set the given value to the commit and the field determined by the
            index.

            :param index:
                The index of the commit and the field that should be modified.
            :param value:
                The value that will be assigned.
        """
        if not 0 <= index.row() < len(self._commits):
            raise GfbiException("Invalid index")

        commit = self._commits[index.row()]
        column = index.column()
        field_name = self._columns[column]

        reference = None

        if field_name in TIME_FIELDS:
            if self.data(index) is not None:
                reference, tz = self.data(index)
        else:
            reference = self.data(index)

        # This is useless in the development version of GitPython
        # See https://github.com/gitpython-developers/GitPython/commit/096897123ab5d8b500024e63ca81b658f3cb93da
        git_python_precheck = (hasattr(reference, 'binsha') !=
                               hasattr(value, 'binsha'))

        if git_python_precheck or reference != value:
            self.set_field_data(commit, field_name, value)

            if not ignore_history:
                action = SetAction(index, reference, value)
                self._history[self._last_history_event].append(action)

            if self._merge:
                if field_name == "committed_date":
                    self.set_field_data(commit, "authored_date", value)
                elif field_name == "authored_date":
                    self.set_field_data(commit, "committed_date", value)
                elif field_name == "author_name":
                    self.set_field_data(commit, "committer_name", value)
                elif field_name == "committer_name":
                    self.set_field_data(commit, "author_name", value)
                elif field_name == "author_email":
                    self.set_field_data(commit, "committer_email", value)
                elif field_name == "committer_email":
                    self.set_field_data(commit, "author_email", value)

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

    def start_history_event(self):
        """
            Start a new history event. If the current event isn't the last one,
            drop every event after the current event.
        """
        while self._last_history_event < len(self._history) - 1:
            self._history.pop()

        self._last_history_event += 1
        self._history.append([])

    def undo_history(self):
        """
            Reverts the history one event back.
        """
        if self._last_history_event >= 0:
            for action in reversed(self._history[self._last_history_event]):
                action.undo(self)
            if self._last_history_event > -1:
                self._last_history_event -= 1

    def redo_history(self):
        """
            Replays the history one event forward.
        """
        if self._last_history_event < len(self._history) - 1:
            self._last_history_event += 1
            for action in self._history[self._last_history_event]:
                action.redo(self)

    def undelete_commit(self, commit, modifications):
        """
            Remove a commit from the _deleted_commits list.
        """
        self._deleted_commits.remove(commit)

        if modifications:
            self._modifications[commit] = modifications

    def insert_commit(self, row, commit, modifications):
        """
            The parent commit is the previous commit in the history.
        """
        self._commits.insert(row, commit)

        if modifications:
            self._modifications[commit] = modifications

    def insert_rows(self, position, rows):
        """
            Inserts blank rows in the model.

            :param position:
                Position from where to insert.
            :param rows:
                Number of rows to insert.
        """
        for i in xrange(rows):
            commit = DummyCommit()
            self._commits.insert(position, commit)

            self._modifications[commit] = {}
            for field in NAMES:
                self._modifications[commit][field] = None

            action = InsertAction(position, commit, self._modifications[commit])
            self._history[self._last_history_event].append(action)

    def remove_rows(self, position, rows, ignore_history=False,
                    really_remove=False):
        """
            Removes rows from the model.

            :param position:
                Position from where to delete.
            :param rows:
                Number of rows to delete.
        """
        for i in xrange(rows):
            if really_remove:
                commit = self._commits.pop(position)
                self._modifications.pop(commit)
            else:
                commit = self._commits[position + i]
                if not self.is_deleted(commit):
                    self._deleted_commits.append(commit)

                    if not ignore_history:
                        modifications = None
                        if self._modifications.has_key(commit):
                            modifications = self._modifications[commit]
                        action = RemoveAction(position, commit, modifications)
                        self._history[self._last_history_event].append(action)

    def is_deleted(self, indexorcommit):
        """
            If indexorcommit:
                * is an index, if the commit at index.row() is a deleted commit,
                return True.
                * is a commit, if the commit is a deleted commit, return True.
        """
        if hasattr(indexorcommit, 'row'):
            if not 0 <= indexorcommit.row() < len(self._commits):
                raise GfbiException("Invalid index")
            commit = self._commits[indexorcommit.row()]
        else:
            commit = indexorcommit
        return commit in self._deleted_commits

    def is_inserted_commit(self, index):
        """
            If the commit at index.row() is a DummyCommit, return True.
        """
        commit = self._commits[index.row()]
        return isinstance(commit, DummyCommit)

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

        if isinstance(commit, DummyCommit):
            return True

        if commit in mods and field_name in mods[commit]:
            return mods[commit][field_name] != self.orig_data(index)
        return False

    def commit_is_modified(self, commit):
        """
            Returns True is one of the commit fields has been modified.
        """
        row = self.row_of(commit)

        children_col = self.get_column("children")
        ignore_columns = set((children_col,))
        for col in set(xrange(self.column_count())) - ignore_columns:
            index = Index(row, col)
            if self.is_modified(index) and not self.is_deleted(index):
                return True
        return False

    def write(self, log=True, force_committed_date=False, dont_populate=False):
        """
            Start the git filter-branch command and therefore write the
            modifications stored in _modifications.

            :param log:
                Boolean, set to True to log the git command.
            :param force_committed_date:
                As the git way updates the committed author/date when
                cherry-picking, and since we offer to modify these values, we
                offer the user the choice to force the committed author/date
                or to let git update it.
        """
        self._git_process = git_filter_rebase(self, log=log,
                                    force_committed_date=force_committed_date,
                                    dont_populate=dont_populate)
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

    def is_write_success(self):
        """
            Returns True if the write process went through without failing.
        """
        if self._git_process is not None:
            return self._git_process.is_success()
        else:
            return False

    def get_start_write_from(self):
        """
            Returns the parents of the commits that are modified.
        """
        modified_commits = tuple(self._modifications.keys())
        if modified_commits in self._start_write_cache.keys():
            return self._start_write_cache[modified_commits]

        parents = set()
        for commit in self._modifications:
            if self.commit_is_modified(commit):
                parents.add(commit)

        smaller_parent_set = set(parents)
        for parent in parents:
            # Check that parent isn't in any of the other parents history tree
            if parent not in smaller_parent_set:
                continue

            for _parent in parents - set([parent]):
                # Go down the history tree of _parent
                this_parent_parents = self.c_data(_parent, "parents")
                if _parent in smaller_parent_set and \
                   parent in self.all_parents(_parent):
                    # Parent is present in the _parent history tree
                    # That means _parent must be removed from
                    # smaller_parent_set.
                    smaller_parent_set.remove(_parent)

        if parents == set([]) and self.is_fake_model():
            # Special case: no commit has really been modified, and this is a
            # fake model. We just need to update the top commit.
            smaller_parent_set = ([self._commits[0],])

        self._start_write_cache[modified_commits] = smaller_parent_set

        return smaller_parent_set

    def all_parents(self, commit):
        """
            Returns all the parents of a commit.
        """
        parents = set()

        parents_to_look = set([commit,])
        while parents_to_look:
            commit = parents_to_look.pop()
            for parent in self.c_data(commit, "parents"):
                yield parent
                parents_to_look.add(parent)

    def all_children(self, commits):
        """
            Returns a set with all the children of the given commits.
        """
        children = set()

        modified_commits = tuple(self._modifications.keys())
        if modified_commits in self._children_cache.keys():
            return self._children_cache[modified_commits]

        children_to_look = set(commits)
        while children_to_look:
            commit = children_to_look.pop()
            for child in self.c_data(commit, "children"):
                if not child in children:
                    children_to_look.add(child)

                children.add(child)

        self._children_cache[modified_commits] = children

        return children

    def get_to_rewrite_count(self):
        """
            Returns the number of commits to will be rewritten. That means the
            number of commit between HEAD and the oldest modified commit.
        """
        start_from_commits = self.get_start_write_from()
        all_children = self.all_children(start_from_commits)

        return len(all_children) + len(start_from_commits)

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
        #    new_commit_time = time_cursor + int((random() * 2 - 1) *max_error)

        # Uniform method
        total_seconds = timelapse.get_total_seconds()
        distribution = [int(random() * total_seconds)
                        for commit in xrange(len(self._commits))]
        distribution.sort()

        index = 0
        for commit in self._commits:
            this_distribution = distribution[index]
            new_commit_time = timelapse.datetime_from_seconds(
                                                            this_distribution)
            self.set_field_data(commit, "authored_date",
                                int(mktime(new_commit_time.timetuple())))
            self.set_field_data(commit, "committed_date",
                                int(mktime(new_commit_time.timetuple())))

            index += 1

    def set_conflicting_commit(self, row):
        """
            Sets the conflicting commit accordingly to the given row.
        """
        self._conflicting_commit = self._commits[row]

    def get_conflicting_commit(self):
        """
            Gets the conflicting commit.
        """
        return self._conflicting_commit

    def get_conflicting_row(self):
        """
            Returns the conflicting commit row.
        """
        return self._commits.index(self._conflicting_commit)

    def is_conflicting_commit(self, row):
        """
            Returns true is the given row points to the conflicting commit.
        """
        if self._conflicting_commit is None:
            return False

        return self._conflicting_commit == self._commits[row]

    def set_unmerged_files(self, u_files):
        """
            Sets the unmerged files as a dictionnary of :
                dict[filepath] = {"unmerged_content"    : unmerged_content,
                                  "diff"                : diff,
                                  "orig_content"        : orig_content,
                                  "git_status"          : git_status}

                where git_status is one of:
                    DD : both deleted
                    AU : added by us
                    UD : deleted by them
                    UA : added by them
                    DU : deleted by us
                    AA : both added
                    UU : both modified

                orig_content is the content of the file at filepath before the
                merge conflict

                unmerged_content is the content of the file at filepath at the
                moment of the merge conflict

                and diff is the diff that should be applied by the conflicting
                commit.
        """
        self._unmerged_files = u_files

    def get_unmerged_files(self):
        """
            Returns the unmerged files after cherry-picking the conflicting
            commit (self._conflicting_commit).
        """
        return self._unmerged_files

    def set_conflict_solutions(self, solutions):
        """
            Sets the solutions for the current conflicting commit.

            :param solutions:
                This is a dictionnary like:
                    solutions[filepath] = (action, custom_content)

                where filepath is the path of the unmerged file

                action is the action that should be taken after the conflict.
                Here is an explanation of what should happen for every action:
                    delete      : git rm filepath
                    add         : git add filepath
                    add_custom  : echo $custom_content > filepath
                                  git add filepath
        """
        self._solutions[self._conflicting_commit] = solutions

    def get_conflict_solutions(self):
        """
            Returns the solutions for every possible conflict of the model.
        """
        return self._solutions

    def is_valid_branch_name(self, name):
        """
            This allows us to check if the name is valid before setting it.
        """
        try:
            validate_branch_name(name)
        except Exception, err:
            return False, err
        else:
            return True, None

    def set_new_branch_name(self, name, ignore_history=False):
        """
            Set the new name of the branch.
        """
        name = name.strip()

        if not ignore_history:
            action = SetBranchNameAction(self._new_branch_name, name)
            self._history[self._last_history_event].append(action)

        if name == self._old_branch_name:
            self._new_branch_name = ""
        elif ignore_history and name == "":
            self._new_branch_name = ""
        else:
            validate_branch_name(name)
            self._new_branch_name = name

        return self._new_branch_name

    def get_new_branch_name(self):
        """
            Returns the new name of the branch.
        """
        return self._new_branch_name

    def is_name_modified(self):
        """
            Returns True if there is a new branch name to be written.
        """
        return self._new_branch_name != ""
