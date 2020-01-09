# Licensed under a 3-clause BSD style license - see LICENSE.rst
import ska_helpers

from .spacecraft import run_cmds, logger, set_log_level, Spacecraft

# This registers various cmd, action and check classes
from . import aca, pcad, mech, misc

__version__ = ska_helpers.get_version(__package__)

def test(*args, **kwargs):
     '''
     Run py.test unit tests.
     '''
     import testr
     return testr.test(*args, **kwargs)
