# git_filter_rebase.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

from threading import Thread
import os
import time
import codecs
from git import Repo

from gfbi_core.util import Index, run_command, apply_solutions, \
                           get_unmerged_files, GfbiException
from gfbi_core import ENV_FIELDS, ACTOR_FIELDS, TIME_FIELDS


def add_assign(commit_settings, field, value):
    commit_settings += ENV_FIELDS[field] + "='%s'" % value + " "
    return commit_settings


class git_filter_rebase(Thread):
    """
        Thread meant to execute and follow the progress of the git command
        process.
    """

    def __init__(self, parent, log=True, force_committed_date=False,
                 dont_populate=False):
        """
            Initialization of the GitFilterRebase thread.

            :param parent:
                GitModel object, parent of this thread.
            :param log:
                If set to True, the git commands will be logged.
            :param force_committed_date:
                As the git way updates the committed author/date when
                cherry-picking, and since we offer to modify these values, we
                offer the user the choice to force the committed author/date
                or to let git update it.
            :param dont_populate:
                If set to True, this process won't repopulate the model after
                the rewrite.
        """
        Thread.__init__(self)

        self._start_commits = parent.get_start_write_from()

        self._log = log
        if log:
            self._logfile = ".gitbuster_" + time.strftime("%d-%m-%Y.%H-%M")

        self._force_committed_date = force_committed_date
        self._dont_populate = dont_populate
        self._model = parent
        self._directory = parent._directory
        self._branch = parent._current_branch

        self._to_rewrite_count = self._model.get_to_rewrite_count()
        self._solutions = self._model.get_conflict_solutions()

        self._u_files = {}
        self._output = []
        self._errors = []
        self._updated_refs = {}
        self._should_be_updated = []
        self._last_updated_sha = None
        self._progress = None
        self._finished = False
        self._success = False

        if self._model.is_fake_model():
            self._fallback_branch_name = Repo(self._directory).branches[0].name
        else:
            self._fallback_branch_name = self._branch.name

        if not self.model_is_applicable():
            raise GfbiException("Can't apply, the repository changed.")

    def model_is_applicable(self):
        """
            Here we are going to check if the tip commit of the given model is
            the same as the real one. This is important because applying a
            dated model (if the repository has new commits since we launched
            gfbi_core) will cause data losses.
        """
        if self._model.is_fake_model():
            # No need to check fake models
            return True

        a_repo = Repo(self._directory)
        current_tip = a_repo.branches[self._branch.name].commit
        current_tip.hexsha

        row = 0
        while self._model.is_inserted_commit(Index(row, 0)):
            row += 1
        index = Index(row, 0)
        model_tip_hexsha = self._model.data(index)
        return current_tip.hexsha == model_tip_hexsha

    def all_should_be_updated(self, updated_parents):
        """
            Returns all the commits that should be updated, if the given commit
            would be modified.
        """
        should_be_updated = set()
        for updated_parent in updated_parents:
            for commit in self._model.c_data(updated_parent, "children"):
                should_be_updated.add(commit)
                should_be_updated.update(self.all_should_be_updated((commit,)))
        return should_be_updated

    def log(self, message):
        if self._log:
            handle = codecs.open(self._logfile, encoding='utf-8', mode='a')
            log_stamp = unicode(time.strftime("[%d-%m-%Y %H:%M:%S] "))
            handle.write(log_stamp + message.rstrip() + "\n")
            handle.close()

    def run_command(self, command):
        self.log("Running: %s" % command.strip() + "\n")
        output, errors = run_command(command)

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
            if "commit" in field and not self._force_committed_date:
                # We're letting git update the committer's name and email
                continue

            index = Index(row=row, column=columns.index(field))
            value = self._model.data(index)
            commit_settings = add_assign(commit_settings, field, value)

        for field in TIME_FIELDS:
            if "commit" in field and not self._force_committed_date:
                # We're letting git update the committed date.
                continue

            index = Index(row=row, column=columns.index(field))
            _timestamp, _tz = self._model.data(index)
            value = str(_timestamp) + " " + _tz.tzname(None)
            commit_settings = add_assign(commit_settings, field, value)

        field = "message"
        index = Index(row=row, column=columns.index(field))
        message = self._model.data(index)

        return commit_settings, message

    def run(self):
        """
            Main method of the script. Launches the git command and
            logs if the option is set.
        """
        os.chdir(self._directory)
        try:
            self.pick_and_commit()
        except Exception, e:
            self._errors.append(str(e))
        finally:
            self.cleanup_repo()
        self._finished = True

    def cleanup_repo(self):
        # Do some verifications before these cleanup steps.
        a_repo = Repo(self._directory)
        if a_repo.is_dirty():
            self.run_command('git reset HEAD --hard')

        try:
            branches = [branch.name for branch in a_repo.branches]

            if 'gitbuster_rebase' in branches:
                self.run_command('git checkout %s' % self._fallback_branch_name)
                self.run_command('git branch -D gitbuster_rebase')
        except TypeError:
            self.run_command('git checkout %s' % self._fallback_branch_name)

    def ref_update(self, commit):
        """
            Update the commit, probably since one of it's parents has changed.
        """
        model = self._model

        parents = model.c_data(commit, "parents")

        if model.is_deleted(commit):
            # If the commit has been deleted, skip it
            if self._last_updated_sha:
                # We don't need to set the last updated sha
                return True

            # The last updated sha hasn't be set, meaning that this may be
            # the top commit.
            if parents[0] in self._updated_refs:
                self._last_updated_sha = self._updated_refs[parents[0]]
            else:
                hexsha = model.c_data(parents[0], "hexsha")
                self._last_updated_sha = hexsha

            return True

        if len(parents) != 1:
            # This is a merge
            for parent in parents:
                if parent in self._should_be_updated and \
                   parent not in self._updated_refs:
                    # Meaning one of the parent branches of the merge hasn't
                    # been rewritten yet => skip for now
                    return True

        # The following will be useful to query the model
        commit_row = model.row_of(commit)

        # Here the parent should be the one defined in the mode (we should call
        # data()). Otherwise, we won't be able to insert or delete commits.
        _parent = parents[0]
        if _parent in self._updated_refs:
            _parent_sha = self._updated_refs[_parent]
        else:
            _parent_sha = self._model.c_data(_parent, "hexsha")

        self.run_command("git checkout -f %s" % _parent_sha)

        to_pick_hexsha = model.c_data(commit, "hexsha")
        if len(parents) == 1:
            # This is not a merge
            pick_command = "git cherry-pick -n %s" % to_pick_hexsha
        else:
            # This is a merge
            pick_command = "git cherry-pick -n -m 1 %s" % to_pick_hexsha

        output, errors = self.run_command(pick_command)
        if [line for line in errors if "error: could not apply" in line]:
            # We have a merge conflict.
            model.set_conflicting_commit(commit_row)
            commit = model.get_conflicting_commit()
            if commit in self._solutions:
                apply_solutions(self._solutions[commit])
            else:
                # Find out what were the hexsha of the conflicting commit
                # and of it's parent, in order to find the diff.
                self.process_unmerged_state(_parent_sha)
                self.cleanup_repo()
                return False

        output, errors = self.run_command("git write-tree")
        new_tree = output[0].strip()

        parent_string = ""
        for parent in parents:
            if parent in self._updated_refs:
                _parent = self._updated_refs[parent]
            else:
                _parent = self._model.c_data(parent, "hexsha")

            parent_string += "-p %s " % _parent

        FIELDS, MESSAGE = self.prepare_arguments(commit_row)
        with open("tmp_message", "w") as handle:
            handle.write(MESSAGE)

        output, errors = self.run_command(FIELDS +
                                        "git commit-tree %s %s < tmp_message" %
                                        (new_tree, parent_string))
        new_sha = output[0].strip()
        self._last_updated_sha = new_sha
        self._updated_refs[commit] = new_sha

        self._progress += 1. / self._to_rewrite_count
        for _commit in self._model.c_data(commit, "children"):
            if not self.ref_update(_commit):
                return False

        return True

    def pick_and_commit(self):
        """
            This is the method that actually does the rebasing.
        """
        self._should_be_updated = self.all_should_be_updated(self._start_commits)

        self._progress = 0
        for commit in self._start_commits:
            if not self.ref_update(commit):
                # There is a conflict
                return False

        # Update other references (as branches, tags)
        if self._last_updated_sha is None:
            self._errors.append("Error: No commit was updated.")
            return False

        command = "git update-ref refs/heads/gitbuster_rebase %s"
        self.run_command(command % self._last_updated_sha)
        output, errors = self.run_command("git checkout gitbuster_rebase")

        if "error: pathspec 'gitbuster_rebase' did not match" in errors[0]:
            # Something, somewhere, went very wrong.
            self._errors.append("Something went wrong in the git filter/rebase "
                         "process, not applying your changes to avoid data "
                         "loss, please check the logs.")
            return False

        if self._model.is_name_modified():
            # The model may be fake
            new_branch_name = self._model.get_new_branch_name()
            self.run_command('git branch -M %s' % new_branch_name)
            if not self._model.is_fake_model():
                self.run_command('git branch -D %s' % self._branch.name)

            branches = Repo(self._directory).branches
            new_branch = [branch for branch in branches
                          if branch.name == new_branch_name][0]
            self._model.set_current_branch(new_branch, force=True)

            # Setting the _branch to the new branch
            # This is useful if we create a fake branch, and change it's name
            # after the creation.
            self._branch = new_branch
        else:
            self.run_command('git branch -M %s' % self._branch.name)

        if not self._dont_populate:
            self._model.populate()
        self._success = True

    def process_unmerged_state(self, orig_hexsha):
        """
            Process the current unmerged state and inform the model about
            unmerged files.
        """
        model = self._model
        conflicting_commit = model.get_conflicting_commit()
        hexsha = model.c_data(conflicting_commit, "hexsha")

        self._u_files = get_unmerged_files(hexsha, orig_hexsha, self._directory)
        self._model.set_unmerged_files(self._u_files)

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

    def is_success(self):
        """
            Returns True if the process went through without failing.
        """
        return self._success
