from subprocess import Popen, PIPE
from gfbi_core.git_model import GitModel, Index
from git.objects.util import altz_to_utctz_str
from datetime import datetime
import os
import time

REPOSITORY_NAME = "/tmp/tests_git"

AVAILABLE_CHOICES = ['hexsha',
                     'authored_date', 'committed_date',
                     'author', 'committer',
                     'message']

def run_command(command):
#    print "Running: %s" % command
    process = Popen(command, shell=True, stdout=PIPE)
    process.wait()

def create_repository():
    run_command('rm -rf ' + REPOSITORY_NAME)
    run_command('mkdir ' + REPOSITORY_NAME)
    os.chdir(REPOSITORY_NAME)
    run_command('git init')

def populate_repository():
    for value in xrange(10, 59):
        command = 'echo "%d" > %d' % (value, value)
        run_command(command)

        run_command('git add %d' % value)

        command = commit(
            str(value),
            author_name="Wallace Henry",
            author_email="wh@jp.com",
            author_date="Sun Mar 11 12:36:%d 2012 +0100" % value,
            committer_name="Wallace Henry",
            committer_email="wh@jp.com",
            committer_date="Sun Mar 11 12:36:%d 2012 +0100" % value
        )

def commit(message,
           author_name=None, author_email=None, author_date=None,
           committer_name=None, committer_email=None, committer_date=None):
    command = ''

    if author_name:
        command += 'GIT_AUTHOR_NAME="%s" ' % author_name
    if author_email:
        command += 'GIT_AUTHOR_EMAIL="%s" ' % author_email
    if author_date:
        command += 'GIT_AUTHOR_DATE="%s" ' % author_date
    if committer_name:
        command += 'GIT_COMMITTER_NAME="%s" ' % committer_name
    if committer_email:
        command += 'GIT_COMMITTER_EMAIL="%s" ' % committer_email
    if committer_date:
        command += 'GIT_COMMITTER_DATE="%s" ' % committer_date

    command += 'git commit -m "%s"' % message

    run_command(command)

def write_and_wait(model):
    model.write()

    total_wait = 0
    time.sleep(1)
    while not model.is_finished_writing():
        if total_wait > 15:
            raise Exception("We waited too long for the writing process")
        time.sleep(1)
        total_wait += 1

def pretty_print_from_row(model, row):
    line = ""
    for i in xrange(len(AVAILABLE_CHOICES)):
        value =  model.data(Index(row, i))
        if isinstance(value, tuple):
            value, tz = value
        line += "[" + str(value) + "]   "
    print line

def test_field_has_changed(test_row, test_column, test_value):
    our_model = GitModel(REPOSITORY_NAME)
    our_model.set_columns(AVAILABLE_CHOICES)

    index = Index(test_row, test_column)
    our_model.set_data(index, test_value)

    write_and_wait(our_model)

    new_model = GitModel(REPOSITORY_NAME)
    new_model.set_columns(AVAILABLE_CHOICES)
    new_model_value = new_model.data(index)
    if test_column in (1, 2):
        # We should deal with the date in a cleaner manner. Will do for now.
        new_model_value, tz = new_model_value
        new_model_value -= 60*60
    assert new_model_value == test_value, \
            "The %s field wasn't changed" % AVAILABLE_CHOICES[test_column]

    for row in xrange(our_model.row_count()):
        for column in xrange(1, our_model.column_count()):
            if row == test_row and column == test_column:
                continue

            index = Index(row, column)

            our_value = our_model.data(index)
            new_value = new_model.data(index)
            if column in (1, 2):
                our_value, tz = our_value
                new_value, tz = new_value

            assert our_value == new_value, \
                    "Something else has change: (%d, %d)" % (row, column)

create_repository()
populate_repository()

test_field_has_changed(2, 1, 1315484564)
test_field_has_changed(4, 3, ("JeanJean", "jeanjean@john.com"))
test_field_has_changed(7, 5, "Boing boing boing")
