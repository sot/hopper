"""
"""
from __future__ import print_function, division, absolute_import

from copy import copy

import pyyaks.logger
import parse_cm
from Quaternion import Quat

logger = pyyaks.logger.get_logger(name=__file__, level=pyyaks.logger.INFO,
                                  format="%(message)s")

from .cmd_action import CMD_ACTION_CLASSES, CHECK_CLASSES, CmdActionCheck

STATE0 = {'q_att': (0, 0, 0),
          'targ_q_att': (0, 0, 0),
          'simpos': 0,
          'simfa_pos': 0,
          'date': '1999:001:00:00:00.000'}

class StateValue(object):
    def __init__(self, name, init_func=None, log=True):
        self.name = name
        self.value = None
        self.values = []
        self.log = log
        self.init_func = init_func

    def __get__(self, SC, cls):
        return self.value

    def __set__(self, SC, value):
        date = SC.date

        if self.log:
            logger.debug('{} {}={}'.format(date, self.name, value))

        if self.init_func:
            value = self.init_func(value)
        self.value = value
        self.values.append({'value': value, 'date': date})

        if hasattr(SC, 'states'):
            if SC.state['date'] != date:
                SC.states.append(copy(SC.state))
                SC.state['date'] = date
            SC.state[self.name] = value


class SpacecraftState(object):
    simpos = StateValue('simpos')
    simfa_pos = StateValue('simfa_pos')
    obsid = StateValue('obsid')
    pitch = StateValue('pitch')
    pcad_mode = StateValue('pcad_mode')
    auto_npm_transition = StateValue('auto_npm_transition')
    maneuver = StateValue('maneuver')
    q_att = StateValue('q_att', init_func=Quat)
    targ_q_att = StateValue('targ_q_att', init_func=Quat)

    def __init__(self, cmds, obsreqs=None, characteristics=None, initial_state=None):
        for attr in self.__class__.__dict__.values():
            if isinstance(attr, StateValue):
                attr.values = []
        self.cmds = cmds
        self.obsreqs = {obsreq['obsid']: obsreq for obsreq in obsreqs} if obsreqs else None
        self.characteristics = characteristics
        self.i_curr_cmd = None
        self.curr_cmd = None
        self.checks = []

        # Make the initial spacecraft "state" dict from user-supplied values, with
        # defaults provided by STATE0
        state0 = copy(STATE0)
        state0.update(initial_state or {})

        self.date = state0['date']
        self.states = [{attr: getattr(self, attr) for attr, val in self.__dict__.items()
                        if isinstance(val, StateValue)}]
        self.states[0]['date'] = self.date

        for key, val in state0.items():
            setattr(self, key, val)


    def run(self):
        # Make this (singleton) instance of SpacecraftState available to
        # all the CmdActionBase child classes.  This is functionally equivalent to
        # making all the cmd_action instances "children" of self and passing
        # self as the parent.
        CmdActionCheck.SC = self

        cmd_actions = []

        # Run through load commands and do checks
        for cmd in self.iter_cmds():
            self.date = cmd['date']
            for cmd_action_class in CMD_ACTION_CLASSES:
                if cmd_action_class.trigger(cmd):
                    cmd_action = cmd_action_class()
                    cmd_action.action(cmd)
                    cmd_actions.append(cmd_action)

        for check in self.checks:
            self.date = check.date
            check.action()


    def __getattr__(self, attr):
        if (attr.endswith('s')
                and attr[:-1] in self.__class__.__dict__
                and isinstance(self.__class__.__dict__[attr[:-1]], StateValue)):
            values = self.__class__.__dict__[attr[:-1]].values
            return values
        else:
            return super(SpacecraftState, self).__getattribute__(attr)

    def iter_cmds(self):
        for i, cmd in enumerate(self.cmds):
            self.i_curr_cmd = i
            self.curr_cmd = cmd
            yield cmd

        self.i_curr_cmd = None
        self.curr_cmd = None

    def add_check(self, name, date):
        """
        Add check ``name`` at ``date``
        """
        self.checks.append(CHECK_CLASSES[name](date))

    def add_cmd(self, cmd):
        """
        Add command in correct order to the commands list.

        TO DO: use scs and step for further sorting??
        """
        cmd_date = cmd['date']

        logger.debug('Adding command {}'.format(cmd))

        if self.curr_cmd is None:
            i_cmd0 = 0
        else:
            # If currently iterating through commands then only add command if
            # it is *after* current command (otherwise iteration gets messed up).
            # In this case add commands after iteration is done.
            if cmd_date < self.date:
                raise ValueError('cannot insert command {} prior to current command {}'
                                 .format(cmd, self.curr_cmd))
            i_cmd0 = self.i_curr_cmd + 1

        cmds = self.cmds
        for i_cmd in xrange(i_cmd0, len(cmds)):
            if cmd_date < cmds[i_cmd]['date']:
                cmds.insert(i_cmd, cmd)
                break
        else:
            cmds.append(cmd)

    def is_obs_req(self):
        """
        Is this an observation request (OR) obsid?  Can this test be better?
        """
        return self.obsid < 40000

    def set_initial_state(self):
        """
        Set the initial state of SC.  For initial testing just use
        stub values.
        """

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

    @property
    def state(self):
        return self.states[-1]


def run_cmds(backstop_file, or_list_file=None, ofls_characteristics_file=None,
             initial_state=None):
    cmds = parse_cm.read_backstop_as_list(backstop_file)
    obsreqs = parse_cm.read_or_list(or_list_file) if or_list_file else None
    if ofls_characteristics_file:
        odb_si_align = parse_cm.read_characteristics(ofls_characteristics_file,
                                                     item='ODB_SI_ALIGN')
        characteristics = {'odb_si_align': odb_si_align}
    else:
        characteristics = None

    SC = SpacecraftState(cmds, obsreqs, characteristics, initial_state)
    SC.run()

    return SC
