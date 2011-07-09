from os.path import join
#import GitPython
#import dulwich
import pygit2
from gfbi_core.util import Timezone

#class Repo:
#    """
#       GitPython compatible Repo class.
#    """
#
#    def __init__(self, directory):
#        self._repo = git.Repo(directory)
#
#        self.active_branch = self._repo.active_branch
#
#    def iter_commits(self, rev=None):
#        return self._repo.iter_commits(rev=rev)
#
#    def branches(self):
#        return self._repo.branches

class Repo:
    """
        Wrapper class to provide a common API for different bindings. Here, we
        provide a wrapper for pygit2 Repository objects.
    """

    def __init__(self, directory):
        """
            Repo initialization.

            :param directory:
                The directory of the git repository.
        """
        self._repo = pygit2.Repository(join(directory, ".git"))
        self._directory = directory

    @property
    def active_branch(self):
        """
            Returns the current checked out branch or raises an exception if
            the git repository is in detached HEAD state.
        """
        refs = []
        with open(join(self._directory, '.git/HEAD')) as handle:
            refs = [line.strip()
                    for line in handle.readlines()
                    if line[:5] == 'ref: ']

        if not refs:
            raise GfbiException("Repository is in detached HEAD state.")

        # here refs should be like : ["ref: refs/heads/master"]
        active_branch = refs[0].split(" ")[1]

        return self._get_branch_from_ref(active_branch)

    def _get_branch_from_ref(self, ref):
        """
            Returns a BranchFromPygit2 object corresponding to the given
            reference. The reference must be like "refs/heads/master".
        """
        assert ref[:11] == "refs/heads/", "Reference isn't correct: %s" % ref

        reference = self._repo.lookup_reference(ref)
        commit = CommitFromPygit2(self._repo[reference.sha])
        return BranchFromPygit2(reference, commit)

    def all_commits(self, rev=None):
        """
            Returns a list of all the commits in the history of the given
            revision.

            :param rev:
                The revision from which we list the history. The revision can
                be in the following formats:
                    * "722be9178d5d6334938fd85f5f31be8048cd5538"
                    * "refs/heads/master"
                    * "refs/tags/v0.1"
                    * CommitFromPygit2()
        """
        assert rev is not None

        if rev in self._repo.listall_references():
            rev = self._repo.lookup_reference(rev).sha

        if isinstance(rev, CommitFromPygit2):
            rev = rev.hexsha

        return [CommitFromPygit2(commit)
                for commit in self._repo.walk(rev,
                                              pygit2.GIT_SORT_TOPOLOGICAL)]

    @property
    def branches(self):
        """
            Returns the branches in the form of a list of BranchFromPygit2
            objects.
        """
        return [self._get_branch_from_ref(ref)
                for ref in self._repo.listall_references()
                if ref[:11] == "refs/heads/"]

    def is_dirty(self):
        """
            Not implemented yet.
        """
        return False

class CommitFromPygit2:
    """
        Wrapper class to provide a common API for different bindings. Here, we
        provide a wrapper for pygit2 Commit objects.
    """

    def __init__(self, commit_object):
        """
            Initializes the CommitFromPygit2 object with a pygit2.Commit
            object.

            :param commit_object:
                The pygit2.Commit we are wrapping.
        """
        assert isinstance(commit_object, pygit2.Commit), commit_object
        self._commit_object = commit_object

    def __eq__(self, other):
        if not hasattr(other, "hexsha"):
            return False
        return self.hexsha == other.hexsha

    def __neq__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.hexsha)

    @property
    def committer_name(self):
        return self._commit_object.committer[0]

    @property
    def committer_email(self):
        return self._commit_object.committer[1]

    @property
    def committed_date(self):
        return self._commit_object.committer[2]

    @property
    def committer_tz(self):
        return Timezone(mnts_offset=self._commit_object.committer[3])

    @property
    def author_name(self):
        return self._commit_object.author[0]

    @property
    def author_email(self):
        return self._commit_object.author[1]

    @property
    def authored_date(self):
        return self._commit_object.author[2]

    @property
    def author_tz(self):
        return Timezone(mnts_offset=self._commit_object.author[3])

    @property
    def parents(self):
        return [CommitFromPygit2(commit)
                for commit in self._commit_object.parents]

    @property
    def summary(self):
        return self._commit_object.message_short

    @property
    def message(self):
        return self._commit_object.message

    @property
    def hexsha(self):
        return self._commit_object.sha


class BranchFromPygit2:
    """
        Wrapper class to provide a common API for different bindings. Here, we
        provide a wrapper for branches when we're using pygit2. We're wrapping
        pygit2.Reference and CommitFromPygit2.
    """

    def __init__(self, reference, commit):
        """
            Initialization of the BranchFromPygit2 object.

            :param reference:
                The pygit2.Reference object related to the branch.
            :param commit:
                The CommitFromPygit2 object pointed by the branch reference.
        """
        assert isinstance(reference, pygit2.Reference), reference
        assert isinstance(commit, CommitFromPygit2), commit

        self._reference = reference
        self._commit = commit

    @property
    def name(self):
        """
            Returns the name of the reference, in the format of
            "refs/heads/master".
        """
        return self._reference.name

    @property
    def commit(self):
        """
            Returns the CommitFromPygit2 object pointed by the branch
            reference.
        """
        return self._commit

    def tracking_branch(self):
        return None
