# util.py
# Copyright (C) 2011 Julien Miotte <miotte.julien@gmail.com>
#
# This module is part of gfbi_core and is released under the GPLv3
# License: http://www.gnu.org/licenses/gpl-3.0.txt

from datetime import timedelta, tzinfo

class Index:
    """
        This mimics the qModelIndex, so that we can use it in the
        GitModel.data() method when populating the model.
    """

    def __init__(self, row=0, column=0):
        """
            Initialization of the Index object.

            :param row:
                Row number, integer.

            :param column:
                Column number, integer.
        """
        self._row = row
        self._column = column

    def row(self):
        """
            Returns the row number.
        """
        return self._row

    def column(self):
        """
            Returns the column number.
        """
        return self._column


class Timezone(tzinfo):
    """
        Timezone class used to preserve the timezone information when handling
        the commits information.
    """

    def __init__(self, tz_string):
        """
            Initialize the Timezone object with it's string representation.

            :param tz_string:
                Representation of the offset to UTC of the timezone. (i.e. +0100
                for CET or -0400 for ECT)
        """
        self.tz_string = tz_string

    def utcoffset(self, dt):
        """
            Returns the offset to UTC using the string representation of the
            timezone.

            :return:
                Timedelta object representing the offset to UTC.
        """
        sign = 1 if self.tz_string[0] == '+' else -1
        hour = sign * int(self.tz_string[1:-2])
        minutes = sign * int(self.tz_string[2:])
        return timedelta(hours=hour, minutes=minutes)

    def tzname(self, dt):
        """
            Returns the offset to UTC string representation.

            :return:
                Offset to UTC string representation.
        """
        return self.tz_string

    def dst(self, dt):
        """
            Returns a timedelta object representing a whole number of minutes
            with magnitude less than one day.

            :return:
                timedelta(0)
        """
        return timedelta(0)


class DummyCommit:

    def __init__(self):
        self.author_tzinfo = None
        self.committer_tzinfo = None
        self.binsha = 0


class HistoryAction:

    def revert(self, model):
        pass


class InsertAction(HistoryAction):

    def __init__(self, insert_position, commit, modifications):
        self._insert_position = insert_position
        self._commit = commit
        self._modifications = modifications

    def undo(self, model):
        model.remove_rows(self._insert_position, 1, ignore_history=True,
                          really_remove=True)

    def redo(self, model):
        model.insert_commit(self._insert_position, self._commit,
                            self._modifications)


class SetAction(HistoryAction):

    def __init__(self, set_index, old_value, new_value):
        self._set_index = set_index
        self._old_value = old_value
        self._new_value = new_value

    def undo(self, model):
        model.set_data(self._set_index, self._old_value, ignore_history=True)

    def redo(self, model):
        model.set_data(self._set_index, self._new_value, ignore_history=True)


class RemoveAction(HistoryAction):

    def __init__(self, remove_position, commit, modifications):
        self._remove_position = remove_position
        self._commit = commit
        self._modifications = modifications

    def undo(self, model):
        model.undelete_commit(self._commit, self._modifications)

    def redo(self, model):
        model.remove_rows(self._remove_position, 1, ignore_history=True)


class SetBranchNameAction(HistoryAction):

    def __init__(self, old_name, new_name):
        self._old_name = old_name
        self._new_name = new_name

    def undo(self, model):
        model.set_new_branch_name(self._old_name, ignore_history=True)

    def redo(self, model):
        model.set_new_branch_name(self._new_name, ignore_history=True)


class DummyBranch:

    def __init__(self, name):
        self.name = name
        self.path = name


class GfbiException(Exception):
    pass
