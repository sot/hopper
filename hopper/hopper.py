"""
"""
from __future__ import print_function, division, absolute_import

import pyyaks.logger
import parse_cm
from Quaternion import Quat
import Chandra.Maneuver
from Chandra.Time import DateTime

logger = pyyaks.logger.get_logger(name=__file__, level=pyyaks.logger.INFO,
                                  format="%(message)s")

CMD_ACTION_CLASSES = []


def as_date(time):
    return DateTime(time).date


class StateValue(object):
    def __init__(self, name, init_func=None, log=True):
        self.name = name
        self.value = None
        self.values = []
        self.log = log
        self.init_func = init_func

    def __get__(self, instance, cls):
        return self.value

    def __set__(self, instance, value):
        date = SC.curr_cmd['date'] if SC.curr_cmd else '2000:001:00:00:00.000'

        if self.log:
            logger.info('{} {}={}'.format(date, self.name, value))
        if self.init_func:
            value = self.init_func(value)
        self.value = value
        self.values.append({'value': value, 'date': date})


class SpacecraftState(object):
    cmds = []
    i_curr_cmd = None
    curr_cmd = None
    obsid = StateValue('obsid')
    pitch = StateValue('pitch')
    pcad_mode = StateValue('pcad_mode')
    maneuver = StateValue('maneuver')
    q_att = StateValue('q_att', init_func=Quat)
    targ_q_att = StateValue('targ_q_att', init_func=Quat)

    def __getattr__(self, attr):
        if attr.endswith('s') and attr[:-1] in self.__class__.__dict__:
            values = self.__class__.__dict__[attr[:-1]].values
            return values
        else:
            return super(SpacecraftState, self).__getattribute__(attr)

    def iter_cmds(self):
        self.cmds_to_add = []

        for i, cmd in enumerate(self.cmds):
            self.i_curr_cmd = i
            self.curr_cmd = cmd
            yield cmd

        self.i_curr_cmd = None
        self.curr_cmd = None

        for cmd in self.cmds_to_add:
            self.add_cmd(cmd)

    def add_cmd(self, cmd):
        """
        Add command in correct order to the commands list.

        TO DO: use scs and step for further sorting??
        """
        cmd_date = cmd['date']

        if self.curr_cmd is None:
            i_cmd0 = 0
        else:
            # If currently iterating through commands then only add command if
            # it is *after* current command (otherwise iteration gets messed up).
            # In this case add commands after iteration is done.
            if cmd_date < self.curr_cmd['date']:
                self.cmds_to_add.append(cmd)
                return
            i_cmd0 = self.i_curr_cmd + 1

        cmds = self.cmds
        for i_cmd in xrange(i_cmd0, len(self.cmds)):
            if cmd_date < cmds[i_cmd]['date']:
                self.cmds.insert(i_cmd, cmd)
                break
        else:
            self.cmds.append(cmd)


SC = SpacecraftState()


class CmdActionMeta(type):
    """
    Simple metaclass to register CmdAction classes
    """
    def __init__(cls, name, bases, dct):
        super(CmdActionMeta, cls).__init__(name, bases, dct)
        if 'cmd_trigger' in dct:
            CMD_ACTION_CLASSES.append(cls)


class CmdAction(object):
    __metaclass__ = CmdActionMeta

    @classmethod
    def action(cls):
        raise NotImplemented()

    @classmethod
    def trigger(cls, cmd):
        ok = all(cmd.get(key) == val
                 for key, val in cls.cmd_trigger.iteritems())
        return ok


class StateValueCmd(CmdAction):
    """
    Set a state value from a single key in the cmd dict.

    Required class attributes:

      - cmd_trigger
      - state_name
      - cmd_key (can also be a tuple of keys)
    """
    @classmethod
    def action(cls, cmd):
        if isinstance(cls.cmd_key, tuple):
            value = tuple(cmd[key] for key in cls.cmd_key)
        else:
            value = cmd[cls.cmd_key]
        setattr(SC, cls.state_name, value)


class FixedStateValueCmd(CmdAction):
    """
    Base class for setting a single state value to something fixed.
    These class attributes are required:

      cmd_trigger = {}
      state_name = None
      state_value = None
    """
    @classmethod
    def action(cls, cmd):
        setattr(SC, cls.state_name, cls.state_value)


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


class QAttCmd(StateValueCmd):
    """
    Pseudo-command to update current attitude quaternion
    """
    cmd_trigger = {'tlmsid': 'update_q_att'}
    state_name = 'q_att'
    cmd_key = 'q1', 'q2', 'q3', 'q4'


class ObsidCmd(StateValueCmd):
    cmd_trigger = {'type': 'MP_OBSID', 'tlmsid': 'COAOSQID'}
    state_name = 'obsid'
    cmd_key = 'id'


class PitchCmd(StateValueCmd):
    """
    Pseudo-command to update current Sun pitch angle.
    """
    cmd_trigger = {'tlmsid': 'update_pitch'}
    state_name = 'pitch'
    cmd_key = 'pitch'


class ManeuverCmd(CmdAction):
    """
    Add a dict that records aggregate information about a maneuver.

    This is an example of a delayed action since this command is injected
    at maneuver start but evaluated maneuver end and so the obsid will be
    correct.
    """

    cmd_trigger = {'tlmsid': 'add_maneuver'}

    @classmethod
    def action(cls, cmd):
        maneuver = cmd['maneuver']
        maneuver['final']['obsid'] = SC.obsid
        SC.maneuver = cmd['maneuver']

class StartManeuverCmd(CmdAction):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AOMANUVR'}

    @classmethod
    def action(cls, cmd):
        atts = Chandra.Maneuver.attitudes(SC.q_att, SC.targ_q_att,
                                          step=300, tstart=cmd['date'])
        for time, q1, q2, q3, q4, pitch in atts:
            date = DateTime(time).date
            SC.add_cmd({'date': date,
                        'tlmsid': 'update_q_att',
                        'q1': q1, 'q2': q2, 'q3': q3, 'q4': q4})
            SC.add_cmd({'date': date,
                        'tlmsid': 'update_pitch',
                        'pitch': pitch})

        att0 = atts[0]
        att1 = atts[-1]
        maneuver = {'initial': {'date': as_date(att0['time']),
                                'q_att': (att0['q1'], att0['q2'], att0['q3'], att0['q4']),
                                'obsid': SC.obsid},
                    'final': {'date': as_date(att1['time']),
                              'q_att': (att1['q1'], att1['q2'], att1['q3'], att1['q4'])},
                    'dur': att1['time'] - att0['time']}

        SC.add_cmd({'date': maneuver['final']['date'],
                    'tlmsid': 'add_maneuver',
                    'maneuver': maneuver})


class NMMMode(FixedStateValueCmd):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AONMMODE'}
    state_name = 'pcad_mode'
    state_value = 'NMAN'


class NPNTMode(FixedStateValueCmd):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AONPMODE'}
    state_name = 'pcad_mode'
    state_value = 'NPNT'


def set_initial_state():
    """
    Set the initial state of SC.  For initial testing just use
    stub values.
    """
    SC.q_att = 0, 0, 0
    SC.targ_q_att = 0, 0, 0
    SC.obsid = 0

set_initial_state()

SC.cmds = parse_cm.read_backstop_as_list('test.backstop')
SC.created_cmds = SC.cmds[:0]

# Initial step of adding commands based on actual backstop commands
for cmd in SC.iter_cmds():
    for cmd_action in CMD_ACTION_CLASSES:
        if cmd_action.trigger(cmd):
            cmd_action.action(cmd)
