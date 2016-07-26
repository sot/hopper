"""
"""
from __future__ import print_function, division, absolute_import

from collections import defaultdict
import os

from astropy.coordinates import SkyCoord
import astropy.units as u

import chandra_aca
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


class SimTransCmd(StateValueCmd):
    cmd_trigger = {'type': 'SIMTRANS'}
    state_name = 'simpos'
    cmd_key = 'pos'


class SimFocusCmd(StateValueCmd):
    cmd_trigger = {'type': 'SIMFOCUS'}
    state_name = 'simfa_pos'
    cmd_key = 'pos'


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


class CheckObsreqTargetFromPcad(CmdAction):
    """
    For science observations check that the expected target attitude
    (derived from the current TARG_Q_ATT and OR Y,Z offset) matches
    the OR target attitude to within 1 arcsec.
    """
    cmd_trigger = {'tlmsid': 'check_obsreq_target_from_pcad'}

    @classmethod
    def action(cls, cmd):
        obsid = SC.obsid
        check = {'name': cls.__name__,
                 'date': cmd['date']}

        # TODO refactor to set variables ok, skip, message throughout then `check` at end

        if SC.characteristics is None:
            check.update({'ok': True,
                          'skip': True,
                          'message': 'no Characteristics provided'})

        elif SC.obsreqs is None:
            check.update({'ok': True,
                          'skip': True,
                          'message': 'no OR list provided'})

        elif obsid not in SC.obsreqs:
            check.update({'ok': False,
                          'skip': True,
                          'message': 'obsid {} not in OR list'.format(obsid)})

        elif 'target_ra' not in SC.obsreqs[obsid]:
            check.update({'ok': False,
                          'skip': True,
                          'message': 'obsid {} does not have RA/Dec in OR'.format(obsid)})

        else:
            obsreq = SC.obsreqs[obsid]

            # Gather inputs for doing conversion from spacecraft target attitude
            # to science target attitude.  Add in the dynamical offset attributes
            # which are available for loads planned with Matlab tools 2016_210
            # and later.  These pseudo-attributes must be injected by calling code.
            y_off = obsreq['target_offset_y'] + obsreq.get('aca_offset_y', 0)
            z_off = obsreq['target_offset_z'] + obsreq.get('aca_offset_z', 0)
            targ = SkyCoord(obsreq['target_ra'], obsreq['target_dec'], unit='deg')
            pcad = SC.targ_q_att
            detector = SC.detector

            try:
                si_align = SC.characteristics['si_align'][detector]
            except KeyError:
                # Products are planned using the Matlab tools SI align which matches the
                # baseline mission align matrix from pre-November 2015.
                from chandra_aca.transform import ODB_SI_ALIGN
                si_align = ODB_SI_ALIGN

            q_targ = chandra_aca.calc_targ_from_aca(pcad, y_off, z_off, si_align)
            cmd_targ = SkyCoord(q_targ.ra, q_targ.dec, unit='deg')

            sep = targ.separation(cmd_targ)
            if sep < 1. * u.arcsec:
                ok = True
                message = ('science target attitude matches OR list'
                           ' (separation={:.1f})'
                           .format(sep.to('arcsec')))
            else:
                ok = False
                message = ('science target attitude RA={:.5f} Dec={:.5f} different '
                           'from OR list (separation={:.1f})'
                           .format(q_targ.ra, q_targ.dec, sep.to('arcsec')))
            check.update({'ok': ok, 'message': message})

        SC.checks[obsid].append(check)


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

        # If NMM to NPM auto-transition is enabled (AONM2NPE) then schedule NPM
        # at 1 second after maneuver end
        if SC.auto_npm_transition:
            SC.add_cmd({'date': as_date(att1['time'] + 1),
                        'tlmsid': 'nmm_npm_transition'})


class NMMMode(FixedStateValueCmd):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AONMMODE'}
    state_name = 'pcad_mode'
    state_value = 'NMAN'


class NPNTMode(CmdAction):
    cmd_trigger = None  # custom trigger

    @classmethod
    def trigger(cls, cmd):
        ok = cmd.get('tlmsid') in ('AONPMODE', 'nmm_npm_transition')
        return ok

    @classmethod
    def action(cls, cmd):
        SC.pcad_mode = 'NPNT'

        # Only do subsequent checks for auto transition to NPM following
        # a maneuver.  Other NPM transitions (following NPM dumps, mech moves)
        # don't generate checks.
        if cmd['tlmsid'] != 'nmm_npm_transition':
            return

        # For ORs check that the PCAD attitude corresponds to the OR target
        # coordinates after appropriate align / offset transforms.
        if SC.is_obs_req():
            SC.add_cmd({'date': cmd['date'],
                        'tlmsid': 'check_obsreq_target_from_pcad'})

        # TODO: add commands to kick off ACA sequence with star acquisition
        # and checking.

class DisableNPMAutoTransition(FixedStateValueCmd):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AONM2NPD'}
    state_name = 'auto_npm_transition'
    state_value = False


class EnableNPMAutoTransition(FixedStateValueCmd):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AONM2NPE'}
    state_name = 'auto_npm_transition'
    state_value = True


def run_cmds(backstop_file, or_list=None, characteristics=None,
             initial_state=None):
    """
    Run ``cmds`` from ``initial_state``.

    :param or_list: OR list filename or OR-list object from read_or_list() or None
    :param characteristics: characteristics filename or dict of characteristics or None
    :param initial_state: initial state (dict)

    :returns: Spacecraft object
    """
    cmds = parse_cm.read_backstop_as_list(backstop_file)

    if isinstance(or_list, basestring):
        or_list = parse_cm.read_or_list(or_list)

    if characteristics is None:
        characteristics = {}

    elif isinstance(characteristics, basestring):
        # This must be an OFLS characteristics file
        odb_si_align = parse_cm.read_characteristics(characteristics, item='ODB_SI_ALIGN')
        characteristics = {'si_align': odb_si_align}

    SC.initialize(cmds, or_list, characteristics, initial_state)

    # Run through load commands and do checks
    for cmd in SC.iter_cmds():
        for cmd_action in CMD_ACTION_CLASSES:
            if cmd_action.trigger(cmd):
                cmd_action.action(cmd)

    SC.checks = dict(SC.checks)
    return SC
