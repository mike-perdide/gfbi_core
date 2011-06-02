# git_filter_branch_process.py
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


class git_rebase_process(Thread):
    """
        Thread meant to execute and follow the progress of the git command
        process.
    """

    def __init__(self, parent, log=True, force_committed_date=False,
                 dont_populate=False):
        """
            Initialization of the GitFilterBranchProcess thread.

            :param parent:
                GitModel object, parent of this thread.
            :param log:
                If set to True, the git filter-branch command will be logged.
            :param force_committed_date:
                As the git way updates the committed author/date when
                cherry-picking, and since we offer to modify these values, we
                offer the user the choice to force the committed author/date
                or to let git update it.
        """
        Thread.__init__(self)

        oldest_hexsha, oldest_row = parent.oldest_modified_commit_parent()
        self._oldest_hexsha = oldest_hexsha
        self._oldest_parent_row = oldest_row

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
        self._progress = None
        self._finished = False
        self._success = False

        if self._model.is_fake_model():
            self._fallback_branch_name = Repo(self._directory).branches[0].name
        else:
            self._fallback_branch_name = self._branch.name

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
            if "commit" in field and not self._force_committed_date :
                # We're letting git update the committer's name and email
                continue

            index = Index(row=row, column=columns.index(field))
            value = self._model.data(index)
            commit_settings = add_assign(commit_settings, field, value)

        for field in TIME_FIELDS:
            if "commit" in field and not self._force_committed_date :
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
        # Backslash overflow !
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
        except Exception, err:
            raise
        finally:
            self.cleanup_repo()
        self._finished = True

    def cleanup_repo(self):
        # Do some verifications before these cleanup steps.
        a_repo = Repo(self._directory)
        if a_repo.is_dirty():
            self.run_command('git reset HEAD --hard')

        if a_repo.active_branch.name == 'gitbuster_rebase':
            self.run_command('git checkout %s' % self._fallback_branch_name)
            self.run_command('git branch -D gitbuster_rebase')

    def pick_and_commit(self):
        """
            This is the method that actually does the rebasing.
        """
        self.run_command('git checkout %s -b gitbuster_rebase' %
                         self._oldest_hexsha)
        oldest_index = self._oldest_parent_row

        self._progress = 0
        for row in xrange(oldest_index - 1, -1, -1):
            if self._model.is_deleted(Index(row=row, column=0)):
                # If the commit has been deleted, skip it
                continue

            hexsha = self._model.data(Index(row=row, column=0))
            FIELDS, MESSAGE = self.prepare_arguments(row)

            output, errors = self.run_command('git cherry-pick -n %s' % hexsha)
            if [line for line in errors if "error: could not apply" in line]:
                # We have a merge conflict.
                self._model.set_conflicting_commit(row)
                commit = self._model.get_conflicting_commit()
                if commit in self._solutions:
                    apply_solutions(self._solutions[commit])
                else:
                    # Find out what were the hexsha of the conflicting commit
                    # and of it's parent, in order to find the diff.
                    self.process_unmerged_state()
                    self.cleanup_repo()
                    return False

            self.run_command(FIELDS + ' git commit -m "%s"' % MESSAGE)
            self._progress += 1. / self._to_rewrite_count

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

    def process_unmerged_state(self):
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

        parents_column = model_columns.index('parents')
        parents_index = Index(conflicting_row, parents_column)
        parents = model.data(parents_index)

        self._u_files = get_unmerged_files(from_hexsha=parents[0].hexsha,
                                           to_hexsha=hexsha)
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


def get_unmerged_files(from_hexsha=None, to_hexsha=None):
    """
        Collect several information about the current unmerged state.

        :param from_hexsha, to_hexsha:
            These parameters are used to provide the diff that should have been
            applied by the conflicting commit.
    """
    u_files = {}

    # Fetch diffs
    provide_unmerged_status(u_files)
    provide_diffs(u_files, from_hexsha, to_hexsha)
    provide_unmerged_contents(u_files)
    provide_orig_contents(u_files)

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


def provide_diffs(u_files, from_hexsha=None, to_hexsha=None):
    """
        Process the output of git diff rather than calling git diff on
        every file in the path.
    """
    if not (from_hexsha and to_hexsha) and \
       not os.path.exists(REBASE_PATCH_FILE):
        raise GfbiException("Not enough information to calculate diffs: "
                            "neither both hexsha nor %s" % REBASE_PATCH_FILE)

    if (from_hexsha and to_hexsha):
        command = "git diff %s %s" % (from_hexsha, to_hexsha)
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


def provide_orig_contents(u_files):
    """
        This method fetches the content of the files before the merge.

        Possible optimization: use git.repo.tree.
    """
    command = "git reset --hard"
    run_command(command)

    for u_file, file_info in u_files.items():
        git_status = file_info["git_status"]
        orig_content = ""
        if git_status not in ('UA', 'DU', 'DD'):
            handle = codecs.open(u_file, encoding='utf-8', mode='r')
            orig_content = handle.read()
            handle.close()
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
