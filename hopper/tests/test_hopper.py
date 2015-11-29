from __future__ import print_function

import os
import glob
import pytest

import hopper
import hopper.cmd_action

root = os.path.dirname(__file__)

HAS_OCT0515 = os.path.exists(os.path.join(root, 'OCT0515'))


def run_hopper(backstop_file, or_list_file=None,
               ofls_characteristics_file=None, initial_state=None):
    # Run the commands and populate attributes in `sc`, the spacecraft state.
    # In particular sc.checks is a dict of checks by obsid.
    # Any state value (e.g. obsid or q_att) has a corresponding plural that
    # gives the history of updates as a dict with a `value` and `date` key.
    sc = hopper.run_cmds(backstop_file, or_list_file, ofls_characteristics_file, initial_state)

    all_ok = True

    # Iterate through obsids in order
    lines = []
    obsids = sc.obsids['values']
    for obsid in obsids:
        lines.append('obsid = {}'.format(obsid))

    return all_ok, lines, sc


def test_nov0512():
    """
    Minimal example of running checks from Python
    """
    or_list_file = os.path.join(root, 'NOV0512', 'or_list')
    backstop_file = os.path.join(root, 'NOV0512', 'backstop')
    ofls_characteristics_file = os.path.join(root, 'NOV0512', 'CHARACTERIS_12MAR15')

    initial_state = {'q_att': (-3.41366779e-02, 6.48062295e-01, 7.48327371e-01, 1.37317495e-01),
                     'simpos': 75624,
                     'simfa_pos': -468,
                     'date': '2012-11-10 00:00:00'}

    # NOV0512 with added CHARACTERISTICS.
    ok, lines, sc = run_hopper(backstop_file, or_list_file,
                               ofls_characteristics_file, initial_state)
    assert ('13871: science target attitude RA=160.63125 Dec=5.04381 '
            'different from OR list for obsid 13871 by 3.6 arcsec' in lines)
    assert not ok

    # NOV0512 the way it really is.  This is how old loads with no characteristics will
    # process when run through the checker.
    ok, lines, sc = run_hopper(backstop_file, or_list_file, None, initial_state)
    assert ok


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

    initial_state = {'q_att': (-6.48322909e-01, 6.38847453e-02, -5.54412345e-01, 5.17902594e-01),
                     'simpos': 75624,
                     'simfa_pos': -468,
                     'date': '2015-10-13 00:00:00'}

    ok, lines, sc = run_hopper(glob.glob(backstop_file)[0],
                               glob.glob(or_list_file)[0],
                               glob.glob(ofls_characteristics_file)[0],
                               initial_state)
    assert ok
