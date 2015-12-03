"""
Definitions for command-action classes that interpret commands
and perform subsequent actions which could include spawning new
commands or doing checks.
"""

import re

import Chandra.Maneuver
from Chandra.Time import DateTime

from .utils import as_date, un_camel_case

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
        if isinstance(self.cmd_key, tuple):
            value = tuple(self.cmd[key] for key in self.cmd_key)
        else:
            value = self.cmd[self.cmd_key]
        setattr(self.SC, self.state_name, value)


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


class SimTransCmd(StateValueCmd):
    cmd_trigger = {'type': 'SIMTRANS'}
    state_name = 'simpos'
    cmd_key = 'pos'


class SimFocusCmd(StateValueCmd):
    cmd_trigger = {'type': 'SIMFOCUS'}
    state_name = 'simfa_pos'
    cmd_key = 'pos'


class TargQAttCmd(StateValueCmd):
    """
    2009:033:01:18:19.704 |  8221758 0 | MP_TARGQUAT
    | TLMSID= AOUPTARQ, CMDS= 8,
    Q1= -7.34527862e-01, Q2=  1.58017489e-01,
    Q3=  3.72958462e-01, Q4=  5.44427478e-01, SCS= 130, STEP= 1542
    """
    cmd_trigger = {'type': 'MP_TARGQUAT',
                   'tlmsid': 'AOUPTARQ'}
    state_name = 'targ_q_att'
    cmd_key = 'q1', 'q2', 'q3', 'q4'


class ObsidCmd(StateValueCmd):
    cmd_trigger = {'type': 'MP_OBSID', 'tlmsid': 'COAOSQID'}
    state_name = 'obsid'
    cmd_key = 'id'


class ManeuverCmd(Cmd):
    cmd_trigger = {'tlmsid': 'AOMANUVR'}

    def run(self):
        SC = self.SC
        atts = Chandra.Maneuver.attitudes(SC.q_att, SC.targ_q_att,
                                          step=300, tstart=self.cmd['date'])
        for time, q1, q2, q3, q4, pitch in atts:
            date = DateTime(time).date
            SC.add_action('set_qatt', date, q1=q1, q2=q2, q3=q3, q4=q4)
            SC.add_action('set_pitch', date, pitch=pitch)

        att0 = atts[0]
        att1 = atts[-1]
        maneuver = {'initial': {'date': as_date(att0['time']),
                                'obsid': SC.obsid,
                                'q1': att0['q1'], 'q2': att0['q2'], 'q3': att0['q3'], 'q4':att0['q4']},
                    'final': {'date': as_date(att1['time']),
                              # final obsid filled in at the end of the maneuver
                              'q1': att1['q1'], 'q2': att1['q2'], 'q3': att1['q3'], 'q4':att1['q4']},
                    'dur': att1['time'] - att0['time']}

        SC.add_action('add_maneuver', date=maneuver['final']['date'], maneuver=maneuver)

        # If NMM to NPM auto-transition is enabled (AONM2NPE) then schedule NPM
        # at 10 seconds after maneuver end
        if SC.auto_npm_transition:
            SC.add_action('auto_nmm_npm', as_date(att1['time'] + 10))


class NmmModeCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AONMMODE'}
    state_name = 'pcad_mode'
    state_value = 'NMAN'


class NpntModeCmd(Cmd):
    """
    Explicit AONPMODE command.  Most frequently NPM is entered by
    auto-transition from NMM (via AutoNmmNpmAction).
    """
    cmd_trigger = {'tlmsid': 'AONPMODE'}
    state_name = 'pcad_mode'
    state_value = 'NPNT'

class AutoNmmNpmAction(Action):
    """
    Get to NPNT by way of an automatic transition after a maneuver.  This
    is accompanied by acquisition of a (new) star catalog which must be checked.
    """
    def run(self):
        SC = self.SC
        SC.pcad_mode = 'NPNT'

        # For ORs check that the PCAD attitude corresponds to the OR target
        # coordinates after appropriate align / offset transforms.
        if SC.is_obs_req():
            SC.add_check('attitude_consistent_with_obsreq', date=self.cmd['date'])

        # TODO: add commands to kick off ACA sequence with star acquisition
        # and checking.


class DisableNPMAutoTransitionCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AONM2NPD'}
    state_name = 'auto_npm_transition'
    state_value = False


class EnableNPMAutoTransitionCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AONM2NPE'}
    state_name = 'auto_npm_transition'
    state_value = True


class SetQAttAction(Action, StateValueCmd):
    """
    Action to update current attitude quaternion
    """
    state_name = 'q_att'
    cmd_key = 'q1', 'q2', 'q3', 'q4'


class SetPitchAction(Action, StateValueCmd):
    """
    Action to update current Sun pitch angle.
    """
    state_name = 'pitch'
    cmd_key = 'pitch'


class AddManeuverAction(Action):
    """
    Add a dict that records aggregate information about a maneuver.

    This is an example of a delayed action since this command is injected
    at maneuver start but evaluated maneuver end and so the obsid will be
    correct.
    """
    def run(self):
        maneuver = self.cmd['maneuver']
        maneuver['final']['obsid'] = self.SC.obsid
        self.SC.maneuver = maneuver
