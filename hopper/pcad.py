# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Commands, Actions, and checks for PCAD
"""

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.table import Table
import astropy.units as u

import chandra_aca
from Quaternion import Quat
import Chandra.Maneuver
from cxotime import CxoTime

from .base_cmd import (Cmd, StateValueCmd, FixedStateValueCmd, Action, Check,
                       CmdSequenceCheck)

class TargQAttCmd(StateValueCmd):
    """
    2009:033:01:18:19.704 |  8221758 0 | MP_TARGQUAT
    | TLMSID= AOUPTARQ, CMDS= 8,
    Q1= -7.34527862e-01, Q2=  1.58017489e-01,
    Q3=  3.72958462e-01, Q4=  5.44427478e-01, SCS= 130, STEP= 1542
    """
    cmd_trigger = {'type': 'MP_TARGQUAT',
                   'tlmsid': 'AOUPTARQ'}
    state_name = 'targ_q1', 'targ_q2', 'targ_q3', 'targ_q4'
    cmd_key = 'q1', 'q2', 'q3', 'q4'


class DitherEnableCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AOENDITH'}
    state_name = 'dither_enabled'
    state_value = True


class DitherDisableCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AODSDITH'}
    state_name = 'dither_enabled'
    state_value = False


class DitherParmsCmd(Cmd):
    """
    2015:278:02:08:30.051 |  4459839 0 | MP_DITHER        | TLMSID= AODITPAR, CMDS= 9,
    ANGP=  0.00000000e+00, ANGY=  0.00000000e+00,
    COEFP=  3.87799955e-05, COEFY=  3.87799955e-05,
    RATEP=  8.88546929e-03, RATEY=  6.28318917e-03,
    SCS= 128, STEP= 90
    """
    cmd_trigger = {'tlmsid': 'AODITPAR'}

    def run(self):
        SC = self.SC
        cmd = self.cmd
        SC.dither_phase_pitch = np.degrees(cmd['angp'])
        SC.dither_phase_yaw = np.degrees(cmd['angy'])
        SC.dither_ampl_pitch = np.degrees(cmd['coefp']) * 3600
        SC.dither_ampl_yaw = np.degrees(cmd['coefy']) * 3600
        SC.dither_period_pitch = 2 * np.pi / cmd['ratep']
        SC.dither_period_yaw = 2 * np.pi / cmd['ratey']

class ManeuverCmd(Cmd):
    cmd_trigger = {'tlmsid': 'AOMANUVR'}

    def run(self):
        SC = self.SC
        atts = Chandra.Maneuver.attitudes([SC.q1, SC.q2, SC.q3, SC.q4],
                                          [SC.targ_q1, SC.targ_q2, SC.targ_q3, SC.targ_q4],
                                          step=300, tstart=self.cmd['date'])
        for time, q1, q2, q3, q4, pitch in atts:
            SC.add_action('set_qatt', date=time, q1=q1, q2=q2, q3=q3, q4=q4)
            SC.add_action('set_pitch', date=time, pitch=pitch)

        att0 = atts[0]
        att1 = atts[-1]
        time0 = CxoTime(att0['time'])
        time1 = CxoTime(att1['time'])
        maneuver = {'initial': {'date': time0.date,
                                'obsid': SC.obsid,
                                'q1': att0['q1'], 'q2': att0['q2'], 'q3': att0['q3'], 'q4':att0['q4']},
                    'final': {'date': time1.date,
                              # final obsid filled in at the end of the maneuver
                              'q1': att1['q1'], 'q2': att1['q2'], 'q3': att1['q3'], 'q4':att1['q4']},
                    'dur': round((time1 - time0).sec, 3)}

        # Add the summary dict of maneuver info as a spacecraft state
        SC.maneuver = maneuver

        # Set the maneuver obsid at the end of the maneuver
        SC.add_action('set_maneuver_obsid', date=maneuver['final']['date'])

        # If NMM to NPM auto-transition is enabled (AONM2NPE) then schedule NPM
        # at maneuver end.  In reality it happens a bit later, but for checking
        # commands we take the most conservative approach and assume everything
        # happens immediately.
        if SC.auto_npm_transition:
            SC.add_action('auto_npm_with_star_checking', time1)


class NmmModeCmd(FixedStateValueCmd):
    cmd_trigger = {'tlmsid': 'AONMMODE'}
    state_name = 'pcad_mode'
    state_value = 'NMAN'


class NpntModeCmd(FixedStateValueCmd):
    """
    Explicit AONPMODE command.  Most frequently NPM is entered by
    auto-transition from NMM (via AutoNmmNpmAction).
    """
    cmd_trigger = {'tlmsid': 'AONPMODE'}
    state_name = 'pcad_mode'
    state_value = 'NPNT'

#######################################################################
# ACTIONS
#######################################################################


class AutoNpmWithStarCheckingAction(Action):
    """
    Get to NPNT by way of an automatic transition after a maneuver.  This
    is accompanied by acquisition of a (new) star catalog which must be checked.
    """
    def run(self):
        SC = self.SC
        SC.pcad_mode = 'NPNT'

        npm_time = CxoTime(self.cmd['date'])

        # For ORs check that the PCAD attitude corresponds to the OR target
        # coordinates after appropriate align / offset transforms.
        if SC.is_obs_req():
            SC.add_check('attitude_consistent_with_obsreq', date=self.cmd['date'])

        # Get the field stars that the ACA is viewing
        SC.add_action('aca.set_stars', npm_time)

        # Check star catalog
        SC.add_action('aca.identify_starcat', npm_time)
        SC.add_action('aca.acquisition_stars', npm_time)
        SC.add_action('aca.guide_stars', npm_time)
        SC.add_action('aca.mon_stars', npm_time)
        SC.add_action('aca.fid_lights', npm_time)

        # Check dither parameters at a time when they will be at the final values
        SC.add_check('standard_dither', npm_time + 8 * u.min)

        # Add checks for dither disable / enable sequence if dither is large
        SC.add_check('large_dither_cmd_sequence', npm_time + 8 * u.min)


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
    state_name = 'q1', 'q2', 'q3', 'q4'
    cmd_key = 'q1', 'q2', 'q3', 'q4'


class SetPitchAction(Action, StateValueCmd):
    """
    Action to update current Sun pitch angle.
    """
    state_name = 'pitch'
    cmd_key = 'pitch'


class SetManeuverObsid(Action):
    """
    Set the obsid for the current maneuver to the current obsid.

    This is an example of a delayed action since this command is injected
    at maneuver start but evaluated maneuver end and so the obsid will be
    correct.
    """
    def run(self):
        self.SC.maneuver['final']['obsid'] = self.SC.obsid


class AttitudeConsistentWithObsreqCheck(Check):
    """
    For science observations check that the expected target attitude
    (derived from the current TARG_Q_ATT and OR Y,Z offset) matches
    the OR target attitude.
    """
    description = 'Science target attitude matches OR list for obsid'

    def run(self):
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
            pcad = Quat([SC.targ_q1, SC.targ_q2, SC.targ_q3, SC.targ_q4])
            detector = SC.detector
            si_align = SC.characteristics['odb_si_align'][detector]

            q_targ = chandra_aca.calc_targ_from_aca(pcad, y_off, z_off, si_align)
            cmd_targ = SkyCoord(q_targ.ra, q_targ.dec, unit='deg')

            sep = targ.separation(cmd_targ)
            if sep > 1. * u.arcsec:
                message = ('science target attitude RA={:.5f} Dec={:.5f} different '
                           'from OR list by {:.1f}'
                           .format(q_targ.ra, q_targ.dec, sep.to('arcsec')))
                self.add_message('error', message)


class StandardDitherCheck(Check):
    description = 'Dither parameters match one of the standard sets'

    def run(self):
        SC = self.SC
        standards = Table(dict(dither_period_pitch=[1087.0, 1000.0],
                               dither_period_yaw=[768.6, 707.1],
                               dither_ampl_pitch=[20, 8],
                               dither_ampl_yaw=[20, 8]))

        for standard in standards:
            if all(np.allclose(getattr(SC, name), standard[name], rtol=0.001)
                   for name in standards.colnames):
                break
        else:
            self.add_message('warning', 'non-standard dither amplitude or period')


class LargeDitherCmdSequenceCheck(CmdSequenceCheck):
    """Check dither amplitude.  If greater than 30" ("large") in either axis then
    check that dither is disabled one minute before NPM start and enabled 5
    minutes after NPM stars.  In this case the ``matches`` attribute will
    contain the matching commands.  If not greater than 30" then the
    ``not_applicable`` attribute will be True.

    This action is scheduled at 8 minutes after NPM starts so that any initial
    dither commanding is completed.  Base time is set to be the end of the
    previous maneuver, aka NPM start.

    """
    cmd_sequence = [({'tlmsid': 'AODSDITH'}, -1 * u.min,  10 * u.s),
                    ({'tlmsid': 'AOENDITH'}, 5 * u.min,  10 * u.s)]

    def run(self):
        if self.SC.dither_ampl_pitch < 30 and self.SC.dither_ampl_yaw < 30:
            self.not_applicable = True
            return
        super(LargeDitherCmdSequenceCheck, self).run()

    @property
    def base_time(self):
        """
        Base time for this check is the end of the last maneuver (aka start of
        NPM).  The ATS actually schedules things relative to 10 seconds BEFORE
        the end of the maneuver.
        """
        return CxoTime(self.SC.maneuver['final']['date']) - 10 * u.s
