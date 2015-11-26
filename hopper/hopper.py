"""
"""
from __future__ import print_function, division, absolute_import

from collections import defaultdict

import pyyaks.logger
import parse_cm
from Quaternion import Quat

logger = pyyaks.logger.get_logger(name=__file__, level=pyyaks.logger.INFO,
                                  format="%(message)s")

from .cmd_action import CMD_ACTION_CLASSES


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
        date = instance.curr_cmd['date'] if instance.curr_cmd else '2000:001:00:00:00.000'

        if self.log:
            logger.debug('{} {}={}'.format(date, self.name, value))
        if self.init_func:
            value = self.init_func(value)
        self.value = value
        self.values.append({'value': value, 'date': date})


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

    def initialize(self, cmds, obsreqs=None, characteristics=None, initial_state=None):
        for attr in self.__class__.__dict__.values():
            if isinstance(attr, StateValue):
                attr.values = []
        self.cmds = cmds
        self.obsreqs = {obsreq['obsid']: obsreq for obsreq in obsreqs} if obsreqs else None
        self.characteristics = characteristics
        self.i_curr_cmd = None
        self.curr_cmd = None
        self.checks = defaultdict(list)

        if initial_state is None:
            initial_state = {'q_att': (0, 0, 0),
                             'targ_q_att': (0, 0, 0),
                             'simpos': 0,
                             'simfa_pos': 0}
        for key, val in initial_state.items():
            setattr(self, key, val)

    def run(self):
        cmd_actions = []

        # Run through load commands and do checks
        for cmd in self.iter_cmds():
            for cmd_action_class in CMD_ACTION_CLASSES:
                if cmd_action_class.trigger(cmd):
                    cmd_action = cmd_action_class(self)
                    cmd_action.action(cmd)
                    cmd_actions.append(cmd_action)

        self.checks = dict(self.checks)

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

        logger.debug('Adding command {}'.format(cmd))

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



def run_cmds(backstop_file, or_list_file=None, ofls_characteristics_file=None,
             initial_state=None):
    SC = SpacecraftState()
    cmds = parse_cm.read_backstop_as_list(backstop_file)
    obsreqs = parse_cm.read_or_list(or_list_file) if or_list_file else None
    if ofls_characteristics_file:
        odb_si_align = parse_cm.read_characteristics(ofls_characteristics_file,
                                                     item='ODB_SI_ALIGN')
        characteristics = {'odb_si_align': odb_si_align}
    else:
        characteristics = None

    SC.initialize(cmds, obsreqs, characteristics, initial_state)
    SC.run()

    return SC
