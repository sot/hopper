# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
"""


from collections import OrderedDict
from copy import copy

import numpy as np

import pyyaks.logger
import parse_cm
from Quaternion import Quat

from .utils import as_date, get_backstop_cmds

logger = pyyaks.logger.get_logger(name='hopper', level=pyyaks.logger.INFO,
                                  format="%(message)s")

from .base_cmd import CMD_ACTION_CLASSES, CHECK_CLASSES, CmdActionCheck

STATE0 = {'q1': 0.0, 'q2': 0.0, 'q3':0.0, 'q4': 1.0,
          'targ_q1': 0.0, 'targ_q2': 0.0, 'targ_q3':0.0, 'targ_q4': 1.0,
          'simpos': 0,
          'simfa_pos': 0,
          'date': '1999:001:00:00:00.000',
          'dither_enabled': True,
          'dither_phase_pitch': 0.0,
          'dither_phase_yaw': 0.0,
          'dither_ampl_pitch': 8.0,
          'dither_ampl_yaw': 8.0,
          'dither_period_pitch': 1000.0,
          'dither_period_yaw': 707.1
}

class StateValue(object):
    def __init__(self):
        self.clear()

    def clear(self):
        self.values = []
        self.dates = np.ndarray(shape=(0,), dtype='S21')

    def __get__(self, SC, cls):
        """
        Get the value at the last sample which occurs before or at SC.date.
        For instance::

          idx   = [0, 1, 2, 3, 4]
                   |  |  |  |  |
          dates = [0, 1, 2, 2, 3]  # idx = 3 for date=2
          dates = [0, 1, 2, 2, 3]  # idx = -1 for date=-0.1 (no value)
          dates = [0, 1, 2, 2, 3]  # idx = 1 for date=1.0
          dates = [0, 1, 2, 2, 3]  # idx = 1 for date=1.1
        """
        # No samples defined yet, return None
        if len(self.dates) == 0:
            return None

        # Return last sample before or at the current SC date
        date = SC.date
        idx = np.searchsorted(self.dates, date, side='right') - 1
        return self.values[idx] if (idx >= 0) else None

    def __set__(self, SC, value):
        date = SC.date

        logger.debug('%s %s=%s', date, self.name, value)

        self.value = value
        self.values.append(value)
        self.dates.resize(len(self.values))
        self.dates[-1] = date

        SC.set_state_value(date, self.name, value)


class SpacecraftMeta(type):
    def __init__(cls, name, bases, dct):
        super(SpacecraftMeta, cls).__init__(name, bases, dct)

        for name, val in dct.items():
            if isinstance(val, StateValue):
                val.name = name


class Spacecraft(object, metaclass=SpacecraftMeta):
    simpos = StateValue()
    simfa_pos = StateValue()
    obsid = StateValue()
    pitch = StateValue()
    pcad_mode = StateValue()
    auto_npm_transition = StateValue()
    maneuver = StateValue()
    q1 = StateValue()
    q2 = StateValue()
    q3 = StateValue()
    q4 = StateValue()
    targ_q1 = StateValue()
    targ_q2 = StateValue()
    targ_q3 = StateValue()
    targ_q4 = StateValue()
    starcat = StateValue()
    stars = StateValue()
    dither_enabled = StateValue()
    dither_phase_pitch = StateValue()
    dither_phase_yaw = StateValue()
    dither_ampl_pitch = StateValue()
    dither_ampl_yaw = StateValue()
    dither_period_pitch = StateValue()
    dither_period_yaw = StateValue()

    def __init__(self, cmds, obsreqs=None, characteristics=None, initial_state=None, starcheck=False):
        # Make this (singleton) instance of Spacecraft available to
        # all the CmdActionBase child classes.  This is functionally equivalent to
        # making all the cmd_action instances "children" of self and passing
        # self as the parent.
        CmdActionCheck.SC = self

        class_dict = self.__class__.__dict__

        for attr in class_dict.values():
            if isinstance(attr, StateValue):
                attr.clear()

        if isinstance(cmds, str):
            cmds = get_backstop_cmds(cmds)
        self.cmds = cmds
        self.obsreqs = obsreqs if obsreqs else None
        self.characteristics = characteristics
        # If starcheck is True, and hopper was called from starcheck, run in a reduced mode that
        # skips the star catalog checks (they are already being done independently in starcheck)
        self.starcheck = starcheck
        self.checks = []

        # Make the initial spacecraft "state" dict from user-supplied values, with
        # defaults provided by STATE0
        state0 = copy(STATE0)
        state0.update(initial_state or {})

        self.date = state0.pop('date')
        self.states = [{attr: getattr(self, attr) for attr, val in class_dict.items()
                        if isinstance(val, StateValue)}]
        self.states[0]['date'] = self.date

        for key, val in state0.items():
            if key in class_dict and isinstance(class_dict[key], StateValue):
                setattr(self, key, val)
            else:
                raise AttributeError('key {} is not a StateValue class attribute'
                                     .format(key))

    def run(self):
        """
        Interpret the sequence of commands ``self.cmds``, triggering an action
        for relevant commands.
        """
        self.cmd_actions = []

        # Run through load commands and do checks
        for self.i_cmd, cmd in enumerate(self.cmds):
            self.date = cmd['date']

            for cmd_action_class in CMD_ACTION_CLASSES:
                if cmd_action_class.trigger(cmd):
                    cmd_action = cmd_action_class(cmd)
                    cmd_action.run()
                    self.cmd_actions.append(cmd_action)

        # Once all commands are assembled then make a numpy array of command dates.
        # This is useful for finding commands by date later.
        self.cmd_dates = np.array([cmd['date'] for cmd in self.cmds])

        # Sort the checks by date and then execute each one
        self.checks = sorted(self.checks, key=lambda x: x.date)
        for check in self.checks:
            self.date = check.date
            check.run()

    def __getattr__(self, attr):
        cls_dict = self.__class__.__dict__
        for ending in ('s', '_dates'):
            attr1 = attr[:-len(ending)]
            if (attr.endswith(ending)
                    and attr1 in cls_dict
                    and isinstance(cls_dict[attr1], StateValue)):
                return cls_dict[attr1].values if (ending == 's') else cls_dict[attr1].dates

        return super(Spacecraft, self).__getattribute__(attr)

    def add_cmd(self, **cmd):
        """
        Add command in correct order to the commands list.

        TO DO: use scs and step for further sorting??
        """
        cmd_date = cmd['date']

        logger.debug('Adding command %s', cmd)

        # Prevent adding command before current command since the command
        # interpreter is a one-pass process.
        if cmd_date < self.date:
            raise ValueError('cannot insert command {} prior to current command {}'
                             .format(cmd, self.curr_cmd))

        # Insert command at first place where new command date is strictly
        # less than existing command date.  This implementation is linear, and
        # could be improved, though in practice commands are often inserted
        # close to the original.
        cmds = self.cmds
        for i_cmd in range(self.i_cmd + 1, len(cmds)):
            if cmd_date < cmds[i_cmd]['date']:
                cmds.insert(i_cmd, cmd)
                break
        else:
            cmds.append(cmd)

    def add_action(self, action, date, **kwargs):
        """
        Thin wrapper around add_cmd, but specific to adding an action.

        :param action: name of the action
        :param date: execution date for the action
        """
        # Quick test that date is (most likely) in the Year DOY format.
        # Creating a full CxoTime object is relatively expensive so don't
        # do that here and instead rely on other time formats having a
        # different default length.
        self.add_cmd(action=action, date=as_date(date), **kwargs)

    def add_check(self, name, date, **kwargs):
        """
        Add check ``name`` at ``date``
        """
        self.checks.append(CHECK_CLASSES[name](as_date(date), **kwargs))

    def is_obs_req(self):
        """
        Is this an observation request (OR) obsid?  Can this test be better?
        """
        return self.obsid < 38000

    def set_state_value(self, date, name, value):
        """
        Update the current self.states list to reflect the new setting of state
        ``name=value`` at ``date``.

        :param date: date of state transition
        :param name: name of state parameter
        :param value: value of state parameter
        """
        # During first initialization of SC state values there is no state so
        # just ignore these calls.
        if not hasattr(self, 'states'):
            return

        date = as_date(date)
        states = self.states

        # Create a new state if date has changed.  Note use of shallow copy.
        if states[-1]['date'] != date:
            states.append(copy(states[-1]))
            states[-1]['date'] = date

        states[-1][name] = value

    @property
    def q_att(self):
        return Quat([self.q1, self.q2, self.q3, self.q4])

    @property
    def detector(self):
        for si, lims in (('HRC-S', (-400000.0, -85000.0)),
                         ('HRC-I', (-85000.0, 0.0)),
                         ('ACIS-S', (0.0, 83000.0)),
                         ('ACIS-I', (83000.0, 400000.0))):
            lim0, lim1 = lims
            if lims[0] < self.simpos <= lims[1]:
                return si
        else:
            raise ValueError('illegal value of sim_tsc: {}'.format(self.simpos))

    def get_checks_by_obsid(self):
        """
        Return checks organized by obsid
        """
        checks = OrderedDict()
        for obsid in self.obsids:
            checks[obsid] = []

        for check in self.checks:
            checks[check.obsid].append(check)

        return checks


def set_log_level(level):
    """
    Set the global logging level

    :level: log level string like "verbose" or "critical"
    """
    levels = 'VERBOSE DEBUG INFO WARNING CRITICAL ERROR'.split()
    levels_map = {key.lower(): getattr(pyyaks.logger, key) for key in levels}
    level = levels_map[level]

    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)


def run_cmds(cmds, or_list=None, ofls_characteristics_file=None,
             initial_state=None, starcheck=False):
    if or_list is None:
        obsreqs = None
    elif isinstance(or_list, dict):
        obsreqs = or_list
    else:
        obsreqs, _ = parse_cm.read_or_list_full(or_list)
    if ofls_characteristics_file:
        odb_si_align = parse_cm.read_characteristics(ofls_characteristics_file,
                                                     item='ODB_SI_ALIGN')
        characteristics = {'odb_si_align': odb_si_align}
    else:
        characteristics = None

    sc = Spacecraft(cmds, obsreqs, characteristics, initial_state, starcheck)
    sc.run()

    return sc
