# git_filter_rebase.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

from subprocess import Popen, PIPE
from threading import Thread
import os
import time
import codecs
from git import Repo

from gfbi_core.util import Index, GfbiException
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
REBASE_PATCH_FILE = ".git/rebase-merge/patch"


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

        self._start_commit = parent.get_start_write_from()
        self._start_commit_row = parent.get_commits().index(self._start_commit)

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

    def children_commits_to_rewrite(self, updated_parent):
        """
            Returns the commits of the branch which parents contains
            <updated_parent>.
        """
        to_rewrite = []
        # Here we should use data, instead of get_commits, because if forbids
        # us to insert or delete commits.
        for commit in self._model.get_commits():
            if updated_parent in self._model.c_data(commit, "parents"):
                to_rewrite.append(commit)
        return to_rewrite

    def all_should_be_updated(self, updated_parent):
        """
            Returns all the commits that should be updated, if the given commit
            would be modified.
        """
        should_be_updated = set()
        for commit in self.children_commits_to_rewrite(updated_parent):
            should_be_updated.add(commit)
            should_be_updated.update(self.all_should_be_updated(commit))
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

        message = message.replace('\\', '\\\\')
        message = message.replace('$', '\\\$')
        message = message.replace('"', '\\\"')

        return commit_settings, message

    def run(self):
        """
            Main method of the script. Launches the git command and
            logs if the option is set.
        """
        os.chdir(self._directory)
        try:
            self.pick_and_commit()
        except Exception:
            raise
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

        if model.is_deleted(commit):
            # If the commit has been deleted, skip it
            return True

        parents = model.c_data(commit, "parents")

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
            _parent_sha = _parent.hexsha

        self.run_command("git checkout -f %s" % _parent_sha)

        if len(parents) == 1:
            # This is not a merge
            pick_command = "git cherry-pick -n %s" % \
                                            model.c_data(commit, "hexsha")
        else:
            # This is a merge
            pick_command = "git cherry-pick -n -m 1 %s" % \
                                            model.c_data(commit, "hexsha")

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
                _parent = parent

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
        for _commit in self.children_commits_to_rewrite(commit):
            if not self.ref_update(_commit):
                return False

        return True

    def pick_and_commit(self):
        """
            This is the method that actually does the rebasing.
        """
        self.run_command('git checkout %s -b gitbuster_rebase' %
                         self._model.c_data(self._start_commit, "hexsha"))

        self._should_be_updated = self.all_should_be_updated(self._start_commit)

        self._progress = 0
        for commit in self.children_commits_to_rewrite(self._start_commit):
            if not self.ref_update(commit):
                # There is a conflict
                return False

        # Update other references (as branches, tags)
        command = "git update-ref refs/heads/gitbuster_rebase %s"
        self.run_command(command % self._last_updated_sha)
        self.run_command("git checkout gitbuster_rebase")

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
        model_columns = model.get_columns()
        conflicting_row = model.get_conflicting_row()

        hexsha_column = model_columns.index('hexsha')
        hexsha_index = Index(conflicting_row, hexsha_column)
        hexsha = model.data(hexsha_index)

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


def run_command(command):
    process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    process.wait()
    errors = process.stderr.readlines()
    output = process.stdout.readlines()

    return output, errors


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
    command = "git status"
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
    if conflicting_hexsha:
        command = "git diff %s~ %s" % (conflicting_hexsha, conflicting_hexsha)
        diff_output, errors = run_command(command)
    else:
        diff_output = open(REBASE_PATCH_FILE).readlines()

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
            diff += line

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
