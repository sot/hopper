from __future__ import print_function

import os

import hopper


def make_pcad_attitude_check_report(backstop_file, or_list_file=None,
                                    ofls_characteristics_file=None, initial_state=None):
    """
    Minimal example of making a report for checking PCAD attitudes
    """

    # Run the commands and populate attributes in `sc`, the spacecraft state.
    # In particular sc.checks is a dict of checks by obsid.
    # Any state value (e.g. obsid or q_att) has a corresponding plural that
    # gives the history of updates as a dict with a `value` and `date` key.
    sc = hopper.run_cmds(backstop_file, or_list_file, ofls_characteristics_file, initial_state)

    all_ok = True

    # Iterate through obsids in order
    lines = []
    obsids = [obj['value'] for obj in sc.obsids]
    for obsid in obsids:
        if obsid not in sc.checks:
            continue

        checks = sc.checks[obsid]
        for check in checks:
            if check['name'] == 'CheckObsreqTargetFromPcad':
                ok = check['ok']
                all_ok &= ok
                if check.get('skip'):
                    message = 'SKIPPED: {}'.format(check['message'])
                else:
                    message = 'OK' if ok else check['message']
                line = '{:5d}: {}'.format(obsid, message)
                lines.append(line)
    return all_ok, lines


def example_with_nov0512():
    """
    Minimal example of running checks from Python
    """
    root = os.path.dirname(__file__)
    or_list_file = os.path.join(root, 'NOV0512', 'or_list')
    backstop_file = os.path.join(root, 'NOV0512', 'backstop')
    ofls_characteristics_file = os.path.join(root, 'NOV0512', 'CHARACTERIS_12MAR15')

    initial_state = {'q_att': (-3.41366779e-02, 6.48062295e-01, 7.48327371e-01, 1.37317495e-01),
                     'simpos': 75624,
                     'simfa_pos': -468}

    # NOV0512 with added CHARACTERISTICS.
    ok, lines = make_pcad_attitude_check_report(backstop_file, or_list_file,
                                                ofls_characteristics_file, initial_state)
    print('With characteristics')
    print('OK=', ok)
    print('\n'.join(lines))
    print()

    # NOV0512 the way it really is.  This is how old loads with no characteristics will
    # process when run through the checker.  But for now there is no really need to call
    # this function from perl starcheck in that case, the starcheck output should be
    # entirely UNCHANGED.
    ok, lines = make_pcad_attitude_check_report(backstop_file, or_list_file,
                                                None, initial_state)
    print('No characteristics')
    print('OK=', ok)
    print('\n'.join(lines))
