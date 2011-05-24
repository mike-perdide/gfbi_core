from os import waitpid
from subprocess import Popen

def validate_branch_name(candidate):
    """
    Checks whether the name change is legitimate


    >>> validate_branch_name("master master")
    Traceback (most recent call last):
    ...
    ValueError: Invalid name: has spaces in it
    >>> validate_branch_name("")
    Traceback (most recent call last):
    ...
    ValueError: Invalid name: got empty string
    >>> validate_branch_name("azertyop")
    >>> validate_branch_name("azertyop/qsdfghjklm/wxcvb")
    >>> validate_branch_name("azertyop/azertop//")
    Traceback (most recent call last):
    ...
    ValueError: Invalid name, \
see http://www.kernel.org/pub/software/scm/git/\
docs/git-check-ref-format.html
    >>> validate_branch_name("azertyop/.qsfglm")
    Traceback (most recent call last):
    ...
    ValueError: Invalid name, \
see http://www.kernel.org/pub/software/scm/git/\
docs/git-check-ref-format.html
    """
    if not candidate:
        raise ValueError("Invalid name: got empty string")
    if any (item in candidate for item in " \t\n"):
        raise ValueError("Invalid name: has spaces in it")
    command = u'git check-ref-format refs/tags/%s' % candidate
    process = Popen(command.split())
    status = waitpid(process.pid, 0)[1]
    if status != 0:
        raise ValueError("Invalid name, see http://www.kernel.org/"
            "pub/software/scm/git/docs/git-check-ref-format.html")
