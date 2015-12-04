"""
Definitions for command-action classes that interpret commands
and perform subsequent actions which could include spawning new
commands or doing checks.
"""

import re
from itertools import izip

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

