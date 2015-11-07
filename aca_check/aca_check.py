"""
"""
from __future__ import print_function, division, absolute_import

import pyyaks.logger
import parse_cm
from Quaternion import Quat

logger = pyyaks.logger.get_logger(name=__file__, level=pyyaks.logger.INFO,
                                  format="%(message)s")

CMD_ACTION_CLASSES = []


class StateValue(object):
    def __init__(self, name, log=True):
        self.name = name
        self.value = None
        self.values = []
        self.log = log

    def __get__(self, instance, cls):
        return self.value

    def __set__(self, instance, value):
        if self.log:
            logger.info('{} {}={}'.format(instance.date, self.name, value))
        self.value = value
        self.values.append({'value': value, 'date': instance.date})


class SpacecraftState(object):
    date = StateValue('date', log=False)
    obsid = StateValue('obsid')
    q_att = StateValue('q_att')
    targ_q_att = StateValue('targ_q_att')

    def __getattr__(self, attr):
        if attr.endswith('s') and attr[:-1] in self.__class__.__dict__:
            values = self.__class__.__dict__[attr[:-1]].values
            return values
        else:
            return super(SpacecraftState, self).__getattribute__(attr)

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


class DateCmd(CmdAction):
    """
    Set spacecraft date.  This must be the first cmd action defined.
    """
    cmd_trigger = True

    @classmethod
    def trigger(cls, cmd):
        return True

    @classmethod
    def action(cls, cmd):
        SC.date = cmd['date']


class ObsidCmd(CmdAction):
    cmd_trigger = {'type': 'MP_OBSID'}

    @classmethod
    def action(cls, cmd):
        SC.obsid = cmd['id']


class TargQAttCmd(CmdAction):
    """
    2009:033:01:18:19.704 |  8221758 0 | MP_TARGQUAT
    | TLMSID= AOUPTARQ, CMDS= 8,
    Q1= -7.34527862e-01, Q2=  1.58017489e-01,
    Q3=  3.72958462e-01, Q4=  5.44427478e-01, SCS= 130, STEP= 1542
    """
    cmd_trigger = {'tlmsid': 'AOUPTARQ'}

    @classmethod
    def action(cls, cmd):
        SC.targ_q_att = Quat([cmd['q1'], cmd['q2'], cmd['q3'], cmd['q4']])


cmds = parse_cm.read_backstop_as_list('test.backstop')

for cmd in cmds:
    for cmd_action in CMD_ACTION_CLASSES:
        if cmd_action.trigger(cmd):
            cmd_action.action(cmd)
