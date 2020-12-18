from __future__ import print_function

import os
import glob
from itertools import izip

import pytest
import numpy as np
import astropy.units as u

import parse_cm
import hopper
import hopper.base_cmd

root = os.path.dirname(__file__)

HAS_OCT0515 = os.path.exists(os.path.join(root, 'OCT0515'))


def run_hopper(backstop_file, or_list_file=None,
               ofls_characteristics_file=None, initial_state=None):
    # Run the commands and populate attributes in `sc`, the spacecraft state.
    # In particular sc.checks is a dict of checks by obsid.
    # Any state value (e.g. obsid or q1) has a corresponding plural that
    # gives the history of updates as a dict with a `value` and `date` key.
    sc = hopper.run_cmds(backstop_file, or_list_file, ofls_characteristics_file, initial_state)

    all_ok = True

    # Iterate through obsids in order
    lines = []
    for obsid, checks in sc.get_checks_by_obsid().items():
        for check in checks:
            all_ok &= check.success
            for msg in check.messages:
                lines.append('{} {}: {}'.format(obsid, msg['category'], msg['text']))

    return all_ok, lines, sc


def run_nov0512(with_characteristics=True):
    """
    Minimal example of running checks from Python
    """
    or_list_file = os.path.join(root, 'NOV0512', 'or_list')
    backstop_file = os.path.join(root, 'NOV0512', 'backstop')
    ofls_characteristics_file = (os.path.join(root, 'NOV0512', 'CHARACTERIS_12MAR15')
                                 if with_characteristics else None)
    initial_state = {'q1': -3.41366779e-02,
                     'q2': 6.48062295e-01,
                     'q3': 7.48327371e-01,
                     'q4': 1.37317495e-01,
                     'simpos': 75624,
                     'simfa_pos': -468,
                     'date': '2012-11-10 00:00:00'}
    ok, lines, sc = run_hopper(backstop_file, or_list_file,
                               ofls_characteristics_file, initial_state)
    return ok, lines, sc


def read_data_file(filename):
    if not os.path.isabs(filename):
        filename = os.path.join(root, 'data', filename)
    with open(filename, 'r') as fh:
        out = fh.read()
    return out


def test_nov0512_with_characteristics():
    """NOV0512 with added CHARACTERISTICS."""
    ok, lines, sc = run_nov0512(with_characteristics=True)
    assert lines == ['13871 error: science target attitude RA=160.63125 Dec=5.04381 '
                     'different from OR list by 3.6 arcsec']
    assert not ok


def test_nov0512_as_planned():
    """NOV0512 the way it really is.  This is how old loads with no characteristics will
    process when run through the checker."""
    ok, lines, sc = run_nov0512(with_characteristics=False)
    assert ok

    manvrs = parse_cm.read_maneuver_summary(os.path.join(root, 'NOV0512', 'manvr_summary'),
                                            structured=True)

    # Make sure maneuvers are consistent with OFLS maneuver summary file
    assert len(manvrs) == len(sc.maneuvers)
    for manvr, sc_manvr in izip(manvrs, sc.maneuvers):
        for initfinal in ('initial', 'final'):
            for q in ('q1', 'q2', 'q3', 'q4'):
                assert np.allclose(manvr[initfinal][q], sc_manvr[initfinal][q], atol=1e-7)

    return sc


@pytest.mark.skipif('not HAS_OCT0515')
def test_oct0515():
    """
    More recent loads (not in version control)
    """
    root = os.path.dirname(__file__)
    or_list_file = os.path.join(root, 'OCT0515', '*.or')
    backstop_file = os.path.join(root, 'OCT0515', '*.backstop')
    ofls_characteristics_file = os.path.join(root, 'OCT0515', 'mps', 'ode', 'characteristics',
                                             'CHARACTERIS*')

    initial_state = {'q1': -6.48322909e-01,
                     'q2': 6.38847453e-02,
                     'q3': -5.54412345e-01,
                     'q4': 5.17902594e-01,
                     'simpos': 75624,
                     'simfa_pos': -468,
                     'date': '2015-10-13 00:00:00'}

    ok, lines, sc = run_hopper(glob.glob(backstop_file)[0],
                               glob.glob(or_list_file)[0],
                               glob.glob(ofls_characteristics_file)[0],
                               initial_state)
    assert ok
    return sc


def test_dither_commanding():
    backstop = read_data_file('dither_commanding.backstop')

    sc = hopper.run_cmds(backstop)
    sc.date = '2015:288:00:00:01.000'
    assert sc.dither_enabled is True

    def allclose(a, b):
        return np.allclose(a, b, rtol=0, atol=0.01)

    assert allclose(sc.dither_phase_pitch, 0.0)
    assert allclose(sc.dither_phase_yaw, 0.0)
    assert allclose(sc.dither_ampl_pitch, 4.0)  # arcsec
    assert allclose(sc.dither_ampl_yaw, 8.0)
    assert allclose(sc.dither_period_pitch, 707.423)  # seconds
    assert allclose(sc.dither_period_yaw, 1000.0)

    sc.date = '2015:289:00:00:01.000'
    assert sc.dither_enabled is False

    return sc


def test_cmd_sequence_check():
    backstop = """
    2015:001:00:00:00.000 | 0 0 | FAKE | TLMSID=FAKE1
    2015:001:00:00:10.000 | 0 0 | FAKE | TLMSID=FAKE2
    2015:001:00:00:20.000 | 0 0 | FAKE | TLMSID=FAKE3
    2015:001:00:00:21.000 | 0 0 | FAKE | TLMSID=FAKE3
    """

    class FakeCmdSequenceCheck(hopper.base_cmd.CmdSequenceCheck):
        cmd_sequence = [({'tlmsid': 'FAKE1'}, -4 * u.s, 1.1 * u.s),
                        ({'tlmsid': 'FAKE1'}, 4 * u.s, 1.1 * u.s),
                        ({'tlmsid': 'FAKE3'}, 15 * u.s, 1.1 * u.s)]

    sc = hopper.Spacecraft(backstop)
    sc.add_action('fake_cmd_sequence', '2015:001:00:00:05.000')
    sc.run()

    check = sc.cmd_actions[-1]
    assert check.warnings == ['2 matches for command TLMSID=FAKE3 within '
                              '1.1 s of 2015:001:00:00:20.000']
    assert check.errors == ['no matches for command TLMSID=FAKE1 within '
                            '1.1 s of 2015:001:00:00:09.000']
    return sc


def test_large_dither():
    backstop = read_data_file('large_dither.backstop')
    sc = hopper.Spacecraft(backstop)
    sc.run()

    # Cmd sequence checks
    checks = [check for check in sc.checks if check.name == 'large_dither_cmd_sequence']
    assert len(checks) == 2
    assert checks[0].not_applicable is True
    assert checks[1].not_applicable is False
    assert checks[1].base_time.date == '2015:063:00:46:12.997'
    assert checks[1].warnings == checks[1].errors == []
    assert checks[1].matches[0]['date'] == '2015:063:00:45:12.746'
    assert checks[1].matches[1]['date'] == '2015:063:00:51:12.746'

    checks = [check for check in sc.checks if check.name == 'standard_dither']
    assert len(checks) == 2
    assert checks[0].warnings == checks[0].errors == []
    assert checks[1].warnings == ['non-standard dither amplitude or period']
    assert checks[1].errors == []

    return sc
