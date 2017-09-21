# Licensed under a 3-clause BSD style license - see LICENSE.rst
from itertools import izip
import os

import parse_cm
from cxotime import CxoTime


def as_date(time, quick=True):
    """
    Return in Year DOY format (aka 'date')

    :param time: time-like input
    :param quick: assume a 21-character string is already in YDAY format
    """
    if quick and isinstance(time, basestring) and len(time) == 21:
        return time
    else:
        return CxoTime(time).yday


def un_camel_case(cc_name):
    """
    Change ``CamelCaseNName`` to ``camel_case_nname``.  Note behavior
    for adjacent upper case letters.

    :param cc_name: input camel-cased name
    """
    chars = []
    for c0, c1 in izip(cc_name[:-1], cc_name[1:]):
        # Lower case followed by Upper case then insert "_"
        chars.append(c0.lower())
        if c0.lower() == c0 and c1.lower() != c1:
            chars.append('_')
    chars.append(c1.lower())

    return ''.join(chars)


def get_backstop_cmds(content):
    """
    Thin wrapper around parse_cm.read_backstop_as_list which allows for
    passing the backstop content as a single string.  This assumes it
    will have at least one newline.

    :param content: backstop content or file name (str)
    """
    if os.linesep in content:
        lines = (line.strip() for line in content.splitlines())
        content = [line for line in lines if line]

    return parse_cm.read_backstop_as_list(content)
