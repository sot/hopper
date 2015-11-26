"""
Definitions for command-action classes that interpret commands
and perform subsequent actions which could include spawning new
commands or doing checks.
"""

from astropy.coordinates import SkyCoord
import astropy.units as u

import chandra_aca
import Chandra.Maneuver
from Chandra.Time import DateTime


def as_date(time):
    return DateTime(time).date

CMD_ACTION_CLASSES = []


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

    def __init__(self, SC):
        self.SC = SC  # global spacecraft state

    @classmethod
    def trigger(cls, cmd):
        ok = all(cmd.get(key) == val
                 for key, val in cls.cmd_trigger.iteritems())
        return ok

    def action(self):
        raise NotImplemented()


class StateValueCmd(CmdAction):
    """
    Set a state value from a single key in the cmd dict.

    Required class attributes:

      - cmd_trigger
      - state_name
      - cmd_key (can also be a tuple of keys)
    """
    def action(self, cmd):
        if isinstance(self.cmd_key, tuple):
            value = tuple(cmd[key] for key in self.cmd_key)
        else:
            value = cmd[self.cmd_key]
        setattr(self.SC, self.state_name, value)


class FixedStateValueCmd(CmdAction):
    """
    Base class for setting a single state value to something fixed.
    These class attributes are required:

      cmd_trigger = {}
      state_name = None
      state_value = None
    """
    def action(self, cmd):
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
    the OR target attitude.
    """
    name = 'pcad.attitude_consistent_with_obsreq'
    cmd_trigger = {'tlmsid': 'check_obsreq_target_from_pcad'}

    def action(self, cmd):
        SC = self.SC
        obsid = SC.obsid
        check = {'name': self.name,
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
            # to science target attitude
            y_off, z_off = obsreq['target_offset_y'], obsreq['target_offset_z']
            targ = SkyCoord(obsreq['target_ra'], obsreq['target_dec'], unit='deg')
            pcad = SC.targ_q_att
            detector = SC.detector
            si_align = SC.characteristics['odb_si_align'][detector]

            q_targ = chandra_aca.calc_targ_from_aca(pcad, y_off, z_off, si_align)
            cmd_targ = SkyCoord(q_targ.ra, q_targ.dec, unit='deg')

            sep = targ.separation(cmd_targ)
            if sep < 1. * u.arcsec:
                ok = True
                message = 'science target attitude matches OR list for obsid {}'.format(obsid)
            else:
                ok = False
                message = ('science target attitude RA={:.5f} Dec={:.5f} different '
                           'from OR list for obsid {} by {:.1f}'
                           .format(q_targ.ra, q_targ.dec, obsid, sep.to('arcsec')))
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

    def action(self, cmd):
        maneuver = cmd['maneuver']
        maneuver['final']['obsid'] = self.SC.obsid
        self.SC.maneuver = cmd['maneuver']


class StartManeuverCmd(CmdAction):
    cmd_trigger = {'type': 'COMMAND_SW',
                   'tlmsid': 'AOMANUVR'}

    def action(self, cmd):
        SC = self.SC
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

    def action(self, cmd):
        SC = self.SC
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
