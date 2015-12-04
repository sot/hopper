from __future__ import print_function

import os
import glob
from itertools import izip
import pytest
import numpy as np

import parse_cm
import hopper

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
                     'q4':1.37317495e-01,
                     'simpos': 75624,
                     'simfa_pos': -468,
                     'date': '2012-11-10 00:00:00'}
    ok, lines, sc = run_hopper(backstop_file, or_list_file,
                               ofls_characteristics_file, initial_state)
    return ok, lines, sc

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
                     'q2':6.38847453e-02,
                     'q3':-5.54412345e-01,
                     'q4':5.17902594e-01,
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
    backstop = """
2015:287:00:00:00.000 |  7637432 0 | MP_DITHER        | TLMSID= AODITPAR, CMDS= 9, ANGP=  0.00000000e+00, ANGY=  0.00000000e+00, COEFP=  1.93899978e-05, COEFY=  3.87799955e-05, RATEP=  8.88178870e-03, RATEY=  6.28318917e-03, , SCS= 128, STEP= 622
2015:288:00:00:00.000 |  7637436 0 | COMMAND_SW       | TLMSID= AOENDITH, HEX= 8034301, MSID= AOENDITH, SCS= 128, STEP= 632
2015:289:00:00:00.000 |  7637436 0 | COMMAND_SW       | TLMSID= AODSDITH, HEX= 8034301, MSID= AODSDITH, SCS= 128, STEP= 632"""

    sc = hopper.run_cmds(backstop)
    sc.date = '2015:288:00:00:01.000'
    assert sc.dither_enabled is True

    allclose = lambda a, b: np.allclose(a, b, rtol=0, atol=0.01)
    assert allclose(sc.dither_phase_pitch, 0.0)
    assert allclose(sc.dither_phase_yaw, 0.0)
    assert allclose(sc.dither_ampl_pitch, 4.0)  # arcsec
    assert allclose(sc.dither_ampl_yaw, 8.0)
    assert allclose(sc.dither_period_pitch, 707.423)  # seconds
    assert allclose(sc.dither_period_yaw, 1000.0)

    sc.date = '2015:289:00:00:01.000'
    assert sc.dither_enabled is False

    return sc
