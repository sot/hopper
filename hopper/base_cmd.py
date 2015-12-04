"""
Definitions for command-action classes that interpret commands
and perform subsequent actions which could include spawning new
commands or doing checks.
"""

import re
from itertools import izip
import numpy as np

from cxotime import CxoTime

from .utils import un_camel_case

CMD_ACTION_CLASSES = set()
CHECK_CLASSES = {}

class CmdActionMeta(type):
    """Metaclass to register CmdAction classes and auto-generate ``name`` and
    ``cmd_trigger`` class attributes for ``Cmd`` and ``Action`` subclasses.

    For example, consider the classes below::

      class PcadAction(Action):
      class (PcadAction):

    This code will result in::

      name = 'pcad.attitude_consistent_with_obsreq'
      cmd_trigger = {'action': 'pcad.attitude_consistent_with_obsreq'}

    The class name can optionally end in Check or Action (and this gets
    stripped out from the ``name``), but the class base for checks or actions
    must be ``Check`` or ``Action``, respectively.

    """
    def __init__(cls, name, bases, dct):
        super(CmdActionMeta, cls).__init__(name, bases, dct)

        if 'abstract' in dct:
            return

        name = re.sub(r'(Check|Action|Cmd)$', '', name)
        cls.name = '.'.join(cls.subsystems + [un_camel_case(name)])

        # Auto-generate command trigger for actions
        if cls.type == 'action':
            cls.cmd_trigger = {'action': cls.name}

        # Checks are captured by name in a dict instead of a list.  This is
        # because checks are processed separately after the main run of commands
        # and therefore they can simply be looked up instead of requiring a
        # linear search.
        if cls.type == 'check':
            CHECK_CLASSES[cls.name] = cls

        else:
            CMD_ACTION_CLASSES.add(cls)


class CmdActionCheck(object):
    __metaclass__ = CmdActionMeta
    abstract = True
    subsystems = []

    def __init__(self, cmd):
        self.cmd = cmd

    def set_SC(cls, SC):
        cls.SC = SC

    @classmethod
    def trigger(cls, cmd):
        ok = all(cmd.get(key) == val
                 for key, val in cls.cmd_trigger.iteritems())
        return ok

    def run(self):
        raise NotImplemented()


class Cmd(CmdActionCheck):
    abstract = True
    type = 'cmd'


class Action(CmdActionCheck):
    abstract = True
    type = 'action'


class StateValueCmd(Cmd):
    """
    Set a state value from a single key in the cmd dict.

    Required class attributes:

      - cmd_trigger
      - state_name
      - cmd_key (can also be a tuple of keys)
    """
    abstract = True

    def run(self):
        state_names = (self.state_name if isinstance(self.state_name, (tuple, list))
                       else (self.state_name,))

        if isinstance(self.cmd_key, (tuple, list)):
            values = tuple(self.cmd[key] for key in self.cmd_key)
        else:
            values = (self.cmd[self.cmd_key],)

        if len(values) != len(state_names):
            raise ValueError('length of values {} != length of state_names {}'
                             .format(len(values), len(state_names)))

        for state_name, value in izip(state_names, values):
            setattr(self.SC, state_name, value)


class FixedStateValueCmd(Cmd):
    """
    Base class for setting a single state value to something fixed.
    These class attributes are required:

      cmd_trigger = {}
      state_name = None
      state_value = None
    """
    abstract = True

    def run(self):
        setattr(self.SC, self.state_name, self.state_value)


class Check(CmdActionCheck):
    abstract = True
    type = 'check'

    # True if criteria for running test not met but this is OK.  For example
    # the large dither check is not_applicable if dither < 30 arcsec.  Not_applicable
    # checks can be removed or ignored.
    not_applicable = False

    def __init__(self, date):
        self.obsid = self.SC.obsid
        self.date = date
        self.messages = []

    def add_message(self, category, text):
        self.messages.append({'category': category, 'text': text})

    @property
    def warnings(self):
        return [msg['text'] for msg in self.messages if msg['category'] == 'warning']

    @property
    def errors(self):
        return [msg['text'] for msg in self.messages if msg['category'] == 'error']

    @property
    def infos(self):
        return [msg['text'] for msg in self.messages if msg['category'] == 'info']

    @property
    def success(self):
        return len(self.errors) == 0

    def __repr__(self):
        out = ('<{} at {} warnings={} errors={}>'
               .format(self.name, self.date, len(self.warnings), len(self.errors)))
        return out


class CmdSequenceCheck(Check):
    """
    Check that commands occur within ``tolerance`` of the specified
    delta time offsets from the base time.

    Required class attribute::

      cmds: list of tuples (cmd_match, time_offset, tolerance)

    The tuple consists of::

      cmd_match: dict of command params and values (e.g. tlmsid)
      time_offset: time offset from ``date``
      tolerance: tolerance on time_offset (quantity or TimeDelta)

    Example::

      cmd_sequence = [({'tlmsid': 'AODSDITH'}, -1 * u.min,  10 * u.s),
                      ({'tlmsid': 'AOENDITH'}, 5 * u.min,  10 * u.s)]
    """
    abstract = True


    def run(self):
        self.matches = []
        for cmd_match, time_offset, tolerance in self.cmd_sequence:
            matches = self.match_cmd(cmd_match, time_offset, tolerance)
            self.matches.extend(matches)

    def match_cmd(self, cmd_match, time_offset, tolerance):
        SC = self.SC
        time = self.base_time + time_offset
        min_date = (time - tolerance).date
        max_date = (time + tolerance).date
        i_min = np.searchsorted(SC.cmd_dates, min_date, side='left')
        i_max = np.searchsorted(SC.cmd_dates, max_date, side='right') + 1

        matches = []
        for cmd in SC.cmds[i_min:i_max]:
            if all(cmd.get(key) == val for key, val in cmd_match.items()):
                matches.append(cmd)

        n_match = len(matches)
        if n_match != 1:
            cmd_match_str = ' '.join('{}={}'.format(key, val)
                                     for key, val in cmd_match.items())
            if n_match == 0:
                n_match = 'no'
            message = ('{} matches for command {} within {} of {}'
                       .format(n_match, cmd_match_str.upper(),
                               tolerance, time))
            category = 'error' if (len(matches) == 0) else 'warning'
            self.add_message(category, message)

        return matches

    @property
    def base_time(self):
        return CxoTime(self.date)
