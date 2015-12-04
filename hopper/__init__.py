from .spacecraft import run_cmds, logger, set_log_level, Spacecraft

# This registers various cmd, action and check classes
from . import aca, pcad, mech, misc
