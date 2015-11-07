"""
"""
from __future__ import print_function, division, absolute_import

import pyyaks.logger
import parse_cm
from Quaternion import Quat

logger = pyyaks.logger.get_logger(name=__file__, level=pyyaks.logger.INFO,
                                  format="%(message)s")

COMMAND_ACTION_CLASSES = []


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


class CommandActionMeta(type):
    """
    Simple metaclass to register CommandAction classes
    """
    def __init__(cls, name, bases, dct):
        super(CommandActionMeta, cls).__init__(name, bases, dct)
        if 'command_trigger' in dct:
            COMMAND_ACTION_CLASSES.append(cls)


class CommandAction(object):
    __metaclass__ = CommandActionMeta

    @classmethod
    def action(cls):
        raise NotImplemented()

    @classmethod
    def trigger(cls, command):
        ok = all(command.get(key) == val
                 for key, val in cls.command_trigger.iteritems())
        return ok


class DateCmd(CommandAction):
    """
    Set spacecraft date.  This must be the first command action defined.
    """
    command_trigger = True

    @classmethod
    def trigger(cls, command):
        return True

    @classmethod
    def action(cls, command):
        SC.date = command['date']


class ObsidCmd(CommandAction):
    command_trigger = {'type': 'MP_OBSID'}

    @classmethod
    def action(cls, command):
        SC.obsid = command['id']


class TargQAttCmd(CommandAction):
    """
    2009:033:01:18:19.704 |  8221758 0 | MP_TARGQUAT
    | TLMSID= AOUPTARQ, CMDS= 8,
    Q1= -7.34527862e-01, Q2=  1.58017489e-01,
    Q3=  3.72958462e-01, Q4=  5.44427478e-01, SCS= 130, STEP= 1542
    """
    command_trigger = {'tlmsid': 'AOUPTARQ'}

    @classmethod
    def action(cls, command):
        SC.targ_q_att = Quat([command['q1'], command['q2'], command['q3'], command['q4']])


commands = parse_cm.read_backstop_as_list('test.backstop')

for command in commands:
    for command_action in COMMAND_ACTION_CLASSES:
        if command_action.trigger(command):
            command_action.action(command)
