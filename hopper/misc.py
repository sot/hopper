# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Commands, Actions, and checks for miscellaneous subsystems including CCDM, EPS
"""

from .base_cmd import StateValueCmd

class ObsidCmd(StateValueCmd):
    cmd_trigger = {'type': 'MP_OBSID', 'tlmsid': 'COAOSQID'}
    state_name = 'obsid'
    cmd_key = 'id'

