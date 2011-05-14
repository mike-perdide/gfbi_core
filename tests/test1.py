from subprocess import Popen, PIPE
from gfbi_core.git_model import GitModel
from gfbi_core.editable_git_model import EditableGitModel
from gfbi_core.util import Index, Timezone
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
    run_command('echo init > init_file')
    run_command('git add init_file')
    command = commit(
        "Initial commit",
        author_name="Wallace Henry",
        author_email="wh@jp.com",
        author_date="Sun Mar 11 12:00:00 2012 +0100",
        committer_name="Wallace Henry",
        committer_email="wh@jp.com",
        committer_date="Sun Mar 11 12:00:00 2012 +0100"
    )
    run_command('git branch wallace_branch')

def populate_repository():
    for value in xrange(20, 25):
        command = 'echo "%d" > %d' % (value, value)
        run_command(command)

        run_command('git add %d' % value)

        commit(
            str(value),
            author_name="Wallace Henry",
            author_email="wh@jp.com",
            author_date="Sun Mar 11 12:10:%d 2012 +0100" % value,
            committer_name="Wallace Henry",
            committer_email="wh@jp.com",
            committer_date="Sun Mar 11 12:10:%d 2012 +0100" % value
        )

    run_command('git checkout wallace_branch')

    for value in xrange(20, 25):
        command = 'echo "branch_%d" > branch_%d' % (value, value)
        run_command(command)

        run_command('git add branch_%d' % value)

        commit(
            "branch_" + str(value),
            author_name="Wallace Henry",
            author_email="wh@jp.com",
            author_date="Sun Mar 11 12:20:%d 2012 +0100" % value,
            committer_name="Wallace Henry",
            committer_email="wh@jp.com",
            committer_date="Sun Mar 11 12:20:%d 2012 +0100" % value
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
    for col in xrange(len(AVAILABLE_CHOICES)):
        value =  model.data(Index(row, col))
        if col == 0:
            value = value[:7]
        elif col in (1, 2):
            tmstp, tz = value
            _dt = datetime.fromtimestamp(float(tmstp)).replace(tzinfo=tz)
            date_format = "%d/%m/%Y %H:%M:%S"
            value = _dt.strftime(date_format)
            value = tmstp
        line += "[" + str(value) + "] "
    return line

def test_field_has_changed(test_row, test_column, test_value):
    our_model = EditableGitModel(REPOSITORY_NAME)

#    print "====================================== Before the write"
#    for row in xrange(our_model.row_count()):
#        print pretty_print_from_row(our_model, row)
#    print "======================================================="

    index = Index(test_row, test_column)
    our_model.set_data(index, test_value)

    write_and_wait(our_model)

    new_model = GitModel(REPOSITORY_NAME)
    new_model_value = new_model.data(index)
#    print "======================================= After the write"
#    for row in xrange(our_model.row_count()):
#        print pretty_print_from_row(new_model, row)
#    print "======================================================="

    if test_column in (1, 2):
        assert new_model_value[0] == test_value[0] and \
                new_model_value[1].tzname("") == test_value[1].tzname(""), \
                "The %s field wasn't changed correctly" % \
                AVAILABLE_CHOICES[test_column]
    else:
        assert new_model_value == test_value, \
                "The %s field wasn't changed correctly" % \
                    AVAILABLE_CHOICES[test_column]

    for row in xrange(our_model.row_count()):
        for column in xrange(1, our_model.column_count()):
            if (row == test_row and column == test_column):
                continue

            index = Index(row, column)

            our_value = our_model.data(index)
            new_value = new_model.data(index)
            if column in (1, 2):
                our_value, tz = our_value
            #    print our_value, tz.tzname(None)
                new_value, tz = new_value
            #    print new_value, tz.tzname(None)

            assert our_value == new_value, \
                    "Something else has change: (%d, %d)\ncolumn:%s\n" % \
                    (row, column, AVAILABLE_CHOICES[column]) + \
                    "%s\n%s\n%s\n" % \
                    (AVAILABLE_CHOICES,
                     pretty_print_from_row(our_model, row),
                     pretty_print_from_row(new_model, row)) + \
                    "%s // %s" % (our_value, new_value)

create_repository()
populate_repository()


test_field_has_changed(2, 1, (1331465000, Timezone('+0100')) )
print "Test name"
test_field_has_changed(4, 3, "JeanJean")
print "Test message"
test_field_has_changed(3, 5, "Boing boing boing")
