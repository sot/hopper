"""
Checks for command load checking
"""

from astropy.coordinates import SkyCoord
import astropy.units as u

import chandra_aca
from Quaternion import Quat

from .cmd_action import CmdActionCheck

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

    def __repr__(self):
        out = ('<{} at {} warnings={} errors={}>'
               .format(self.name, self.date, len(self.warnings), len(self.errors)))
        return out


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
