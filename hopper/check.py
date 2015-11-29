import re

from .utils import un_camel_case


class CmdBaseMeta(type):
    """Metaclass to register CmdAction classes and auto-generate ``name`` and
    ``cmd_trigger`` class attributes for ``Check`` and ``Action`` subclasses.

    For example, consider the classes below::

      class PcadCheck(Check):
      class AttitudeConsistentWithObsreq(PcadCheck):

    This code will result in::

      name = 'pcad.attitude_consistent_with_obsreq'
      cmd_trigger = {'check': 'pcad.attitude_consistent_with_obsreq'}

    The class name can optionally end in Check or Action (and this gets
    stripped out from the ``name``), but the class base for checks or actions
    must be ``Check`` or ``Action``, respectively.

    """
    def __init__(cls, name, bases, dct):
        parents = []
        for mro_class in cls.mro():
            mro_name = re.sub(r'(Check|Action)$', '', mro_class.__name__)
            if mro_name == '':  # Final Check or Action class
                cls.name = '.'.join(reversed(parents))
                cls.cmd_trigger = {mro_class.__name__.lower(): cls.name}
                break
            parents.append(un_camel_case(mro_name))

        if hasattr(cls, 'cmd_trigger'):
            CHECK_CLASSES.append(cls)

        super(CmdBaseMeta, cls).__init__(name, bases, dct)


class Check(object):
    __metaclass__ = CmdBaseMeta

    def set_SC(cls, SC):
        cls.SC = SC

