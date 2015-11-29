"""
Definitions for command-action classes that interpret commands
and perform subsequent actions which could include spawning new
commands or doing checks.
"""

import re

from astropy.coordinates import SkyCoord
import astropy.units as u

import chandra_aca
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

    def set_SC(cls, SC):
        cls.SC = SC

    @classmethod
    def trigger(cls, cmd):
        ok = all(cmd.get(key) == val
                 for key, val in cls.cmd_trigger.iteritems())
        return ok

    def action(self, cmd=None):
        raise NotImplemented()


class Cmd(CmdActionCheck):
    abstract = True
    type = 'cmd'


class Action(CmdActionCheck):
    abstract = True
    type = 'action'


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


class StateValueCmd(Cmd):
    """
    Set a state value from a single key in the cmd dict.

    Required class attributes:

      - cmd_trigger
      - state_name
      - cmd_key (can also be a tuple of keys)
    """
    abstract = True

    def action(self, cmd):
        if isinstance(self.cmd_key, tuple):
            value = tuple(cmd[key] for key in self.cmd_key)
        else:
            value = cmd[self.cmd_key]
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


class ObsidCmd(StateValueCmd):
    cmd_trigger = {'type': 'MP_OBSID', 'tlmsid': 'COAOSQID'}
    state_name = 'obsid'
    cmd_key = 'id'


class ManeuverCmd(Cmd):
    cmd_trigger = {'tlmsid': 'AOMANUVR'}

    def action(self, cmd):
        SC = self.SC
        atts = Chandra.Maneuver.attitudes(SC.q_att, SC.targ_q_att,
                                          step=300, tstart=cmd['date'])
        for time, q1, q2, q3, q4, pitch in atts:
            date = DateTime(time).date
            SC.add_cmd({'date': date,
                        'action': 'update_q_att',
                        'q1': q1, 'q2': q2, 'q3': q3, 'q4': q4})
            SC.add_cmd({'date': date,
                        'action': 'update_pitch',
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
                    'action': 'add_maneuver',
                    'maneuver': maneuver})

        # If NMM to NPM auto-transition is enabled (AONM2NPE) then schedule NPM
        # at 1 second after maneuver end
        if SC.auto_npm_transition:
            SC.add_cmd({'date': as_date(att1['time'] + 1),
                        'tlmsid': 'nmm_npm_transition'})


class NmmModeCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AONMMODE'}
    state_name = 'pcad_mode'
    state_value = 'NMAN'


class NpntModeCmd(Cmd):
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
            SC.add_check('attitude_consistent_with_obsreq', date=cmd['date'])

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
    def action(self, cmd):
        maneuver = cmd['maneuver']
        maneuver['final']['obsid'] = self.SC.obsid
        self.SC.maneuver = cmd['maneuver']


class AttitudeConsistentWithObsreqCheck(Check):
    """
    For science observations check that the expected target attitude
    (derived from the current TARG_Q_ATT and OR Y,Z offset) matches
    the OR target attitude.
    """
    description = 'Science target attitude matches OR list for obsid'

    def action(self, cmd=None):
        SC = self.SC
        obsid = SC.obsid

        if SC.characteristics is None:
            self.add_message('warning', 'no Characteristics provided')

        elif SC.obsreqs is None:
            self.add_message('warning', 'no OR list provided')

        elif obsid not in SC.obsreqs:
            self.add_message('error', 'obsid {} not in OR list'.format(obsid))

        elif 'target_ra' not in SC.obsreqs[obsid]:
            self.add_message('error', 'obsid {} does not have RA/Dec in OR'.format(obsid))

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
            if sep > 1. * u.arcsec:
                message = ('science target attitude RA={:.5f} Dec={:.5f} different '
                           'from OR list for obsid {} by {:.1f}'
                           .format(q_targ.ra, q_targ.dec, obsid, sep.to('arcsec')))
                self.add_message('error', message)
