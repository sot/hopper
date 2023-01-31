# Licensed under a 3-clause BSD style license - see LICENSE.rst


import os
import glob


import pytest
import numpy as np
import astropy.units as u

import parse_cm
import hopper
import hopper.base_cmd

root = os.path.dirname(__file__)

# The ode directory seems to have gone missing from this SOT MP directory use in the test
# so setting the exists() to look for that missing piece should skip the now-broken tests
HAS_OCT0515 = os.path.exists(os.path.join(root, 'OCT0515', 'mps', 'ode'))

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
    # hopper.pcad now uses the default ODB_SI_ALIGN if not supplied,
    # so we get this warning from the edited 13781 either way
    assert lines == ['13871 error: science target attitude RA=160.63125 Dec=5.04381 '
                         'different from OR list by 3.6 arcsec']
    assert not ok

    manvrs = parse_cm.read_maneuver_summary(os.path.join(root, 'NOV0512', 'manvr_summary'),
                                            structured=True)

    # Make sure maneuvers are consistent with OFLS maneuver summary file
    assert len(manvrs) == len(sc.maneuvers)
    for manvr, sc_manvr in zip(manvrs, sc.maneuvers):
        for initfinal in ('initial', 'final'):
            for q in ('q1', 'q2', 'q3', 'q4'):
                assert np.allclose(manvr[initfinal][q], sc_manvr[initfinal][q], atol=1e-7)


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


def test_cmd_sequence_check():
    backstop = """
    2015:001:00:00:00.000 | 0 0 | FAKE | TLMSID=FAKE1
    2015:001:00:00:10.000 | 0 0 | FAKE | TLMSID=FAKE2
    2015:001:00:00:20.000 | 0 0 | FAKE | TLMSID=FAKE3
    2015:001:00:00:21.000 | 0 0 | FAKE | TLMSID=FAKE3
    """
    class FakeCmdSequenceCheck(hopper.base_cmd.CmdSequenceCheck):
        cmd_sequence = [({'tlmsid': 'FAKE1'}, -4 * u.s,  1.1 * u.s),
                        ({'tlmsid': 'FAKE1'}, 4 * u.s,  1.1 * u.s),
                        ({'tlmsid': 'FAKE3'}, 15 * u.s,  1.1 * u.s)]

    sc = hopper.Spacecraft(backstop)
    sc.add_check('fake_cmd_sequence', '2015:001:00:00:05.000')
    sc.run()

    check = sc.checks[0]
    assert check.warnings == ['2 matches for command TLMSID=FAKE3 within '
                              '1.1 s of 2015:001:00:00:20.000']
    assert check.errors == ['no matches for command TLMSID=FAKE1 within '
                            '1.1 s of 2015:001:00:00:09.000']


def test_large_dither():
    backstop = """
2015:062:08:28:18.991 |  3957337 0 | MP_OBSID         | TLMSID= COAOSQID, CMDS= 3, ID= 15718, SCS= 131, STEP= 749
2015:062:20:18:10.685 |  4123548 0 | COMMAND_SW       | TLMSID= AONMMODE, HEX= 8030402, MSID= AONMMODE, SCS= 129, STEP= 4
2015:062:20:18:10.942 |  4123549 0 | COMMAND_SW       | TLMSID= AONM2NPE, HEX= 8030601, MSID= AONM2NPE, SCS= 129, STEP= 6
2015:062:20:18:15.042 |  4123565 0 | MP_TARGQUAT      | TLMSID= AOUPTARQ, CMDS= 8, Q1= -2.65325073e-02, Q2= -8.73197509e-01, Q3= -2.16761314e-01, Q4=  4.35702502e-01, SCS= 129, STEP= 8
2015:062:20:18:16.685 |  4123572 0 | MP_STARCAT       | TLMSID= AOSTRCAT, CMDS= 49, IMNUM1= 0, YANG1= -3.74826751e-03, ZANG1= -8.44541515e-03, MAXMAG1=  8.00000000e+00, MINMAG1=  5.79687500e+00, DIMDTS1= 1, RESTRK1= 1, IMGSZ1= 2, TYPE1= 3, IMNUM2= 1, YANG2=  1.03768397e-02, ZANG2=  8.08314461e-04, MAXMAG2=  8.00000000e+00, MINMAG2=  5.79687500e+00, DIMDTS2= 1, RESTRK2= 1, IMGSZ2= 2, TYPE2= 3, IMNUM3= 2, YANG3= -8.85384038e-03, ZANG3=  7.76983377e-04, MAXMAG3=  8.00000000e+00, MINMAG3=  5.79687500e+00, DIMDTS3= 1, RESTRK3= 1, IMGSZ3= 2, TYPE3= 3, IMNUM4= 3, YANG4= -9.07930904e-03, ZANG4= -1.11081634e-02, MAXMAG4=  1.16093750e+01, MINMAG4=  5.79687500e+00, DIMDTS4= 19, RESTRK4= 1, IMGSZ4= 1, TYPE4= 2, IMNUM5= 4, YANG5=  1.45644975e-03, ZANG5=  2.51155582e-03, MAXMAG5=  1.13906250e+01, MINMAG5=  5.79687500e+00, DIMDTS5= 20, RESTRK5= 1, IMGSZ5= 1, TYPE5= 2, IMNUM6= 5, YANG6=  4.69027820e-03, ZANG6= -1.69850557e-03, MAXMAG6=  1.10937500e+01, MINMAG6=  5.79687500e+00, DIMDTS6= 20, RESTRK6= 1, IMGSZ6= 1, TYPE6= 2, IMNUM7= 6, YANG7=  4.09613903e-03, ZANG7= -1.05378407e-02, MAXMAG7=  1.11406250e+01, MINMAG7=  5.79687500e+00, DIMDTS7= 20, RESTRK7= 1, IMGSZ7= 1, TYPE7= 2, IMNUM8= 7, YANG8=  2.11031190e-03, ZANG8=  1.14731549e-02, MAXMAG8=  1.14687500e+01, MINMAG8=  5.79687500e+00, DIMDTS8= 1, RESTRK8= 1, IMGSZ8= 1, TYPE8= 1, IMNUM9= 7, YANG9=  6.98053802e-03, ZANG9= -1.01179011e-02, MAXMAG9=  1.15781250e+01, MINMAG9=  5.79687500e+00, DIMDTS9= 20, RESTRK9= 1, IMGSZ9= 1, TYPE9= 0, IMNUM10= 0, YANG10=  9.85608916e-03, ZANG10= -1.32544145e-03, MAXMAG10=  1.18281250e+01, MINMAG10=  5.79687500e+00, DIMDTS10= 20, RESTRK10= 1, IMGSZ10= 1, TYPE10= 0, IMNUM11= 1, YANG11=  8.51563994e-03, ZANG11= -1.28850470e-03, MAXMAG11=  1.17656250e+01, MINMAG11=  5.79687500e+00, DIMDTS11= 20, RESTRK11= 1, IMGSZ11= 1, TYPE11= 0, IMNUM12= 2, YANG12=  5.27607341e-04, ZANG12=  4.67076445e-03, MAXMAG12=  1.19687500e+01, MINMAG12=  5.79687500e+00, DIMDTS12= 20, RESTRK12= 1, IMGSZ12= 1, TYPE12= 0, IMNUM13= 0, YANG13=  4.63366240e-07, ZANG13=  4.63366240e-07, MAXMAG13=  0.00000000e+00, MINMAG13=  0.00000000e+00, DIMDTS13= 0, RESTRK13= 0, IMGSZ13= 0, TYPE13= 0, IMNUM14= 0, YANG14=  4.63366240e-07, ZANG14=  4.63366240e-07, MAXMAG14=  0.00000000e+00, MINMAG14=  0.00000000e+00, DIMDTS14= 0, RESTRK14= 0, IMGSZ14= 0, TYPE14= 0, IMNUM15= 0, YANG15=  4.63366240e-07, ZANG15=  4.63366240e-07, MAXMAG15=  0.00000000e+00, MINMAG15=  0.00000000e+00, DIMDTS15= 0, RESTRK15= 0, IMGSZ15= 0, TYPE15= 0, IMNUM16= 0, YANG16=  4.63366240e-07, ZANG16=  4.63366240e-07, MAXMAG16=  0.00000000e+00, MINMAG16=  0.00000000e+00, DIMDTS16= 0, RESTRK16= 0, IMGSZ16= 0, TYPE16= 0, , SCS= 129, STEP= 17
2015:062:20:18:20.936 |  4123588 0 | COMMAND_SW       | TLMSID= AOMANUVR, HEX= 8034101, MSID= AOMANUVR, SCS= 129, STEP= 68
2015:063:00:29:49.707 |  4182471 0 | COMMAND_SW       | TLMSID= AONMMODE, HEX= 8030402, MSID= AONMMODE, SCS= 129, STEP= 105
2015:063:00:29:49.964 |  4182472 0 | COMMAND_SW       | TLMSID= AONM2NPE, HEX= 8030601, MSID= AONM2NPE, SCS= 129, STEP= 107
2015:063:00:29:54.064 |  4182488 0 | MP_TARGQUAT      | TLMSID= AOUPTARQ, CMDS= 8, Q1= -1.16706859e-01, Q2= -9.37626262e-01, Q3= -4.78807715e-02, Q4=  3.23950510e-01, SCS= 129, STEP= 109
2015:063:00:29:55.707 |  4182495 0 | MP_STARCAT       | TLMSID= AOSTRCAT, CMDS= 49, IMNUM1= 0, YANG1= -3.74826751e-03, ZANG1= -8.99925418e-03, MAXMAG1=  8.00000000e+00, MINMAG1=  5.79687500e+00, DIMDTS1= 1, RESTRK1= 1, IMGSZ1= 2, TYPE1= 3, IMNUM2= 1, YANG2=  1.03768397e-02, ZANG2=  2.54475434e-04, MAXMAG2=  8.00000000e+00, MINMAG2=  5.79687500e+00, DIMDTS2= 1, RESTRK2= 1, IMGSZ2= 2, TYPE2= 3, IMNUM3= 2, YANG3= -8.85384038e-03, ZANG3=  2.23144350e-04, MAXMAG3=  8.00000000e+00, MINMAG3=  5.79687500e+00, DIMDTS3= 1, RESTRK3= 1, IMGSZ3= 2, TYPE3= 3, IMNUM4= 3, YANG4=  1.45811630e-03, ZANG4= -1.13126336e-02, MAXMAG4=  8.92187500e+00, MINMAG4=  5.79687500e+00, DIMDTS4= 20, RESTRK4= 1, IMGSZ4= 1, TYPE4= 2, IMNUM5= 4, YANG5= -2.90790360e-03, ZANG5= -1.06009686e-03, MAXMAG5=  1.02031250e+01, MINMAG5=  5.79687500e+00, DIMDTS5= 20, RESTRK5= 1, IMGSZ5= 1, TYPE5= 2, IMNUM6= 5, YANG6=  4.90111155e-03, ZANG6=  7.60882625e-03, MAXMAG6=  1.15625000e+01, MINMAG6=  5.79687500e+00, DIMDTS6= 20, RESTRK6= 1, IMGSZ6= 1, TYPE6= 2, IMNUM7= 6, YANG7= -3.81859580e-03, ZANG7= -3.13928093e-03, MAXMAG7=  8.04687500e+00, MINMAG7=  5.79687500e+00, DIMDTS7= 20, RESTRK7= 1, IMGSZ7= 1, TYPE7= 2, IMNUM8= 7, YANG8=  5.29001180e-04, ZANG8= -3.85448323e-04, MAXMAG8=  7.84375000e+00, MINMAG8=  5.79687500e+00, DIMDTS8= 20, RESTRK8= 1, IMGSZ8= 1, TYPE8= 2, IMNUM9= 0, YANG9=  8.24962873e-03, ZANG9= -3.36793118e-03, MAXMAG9=  1.15000000e+01, MINMAG9=  5.79687500e+00, DIMDTS9= 20, RESTRK9= 1, IMGSZ9= 1, TYPE9= 0, IMNUM10= 1, YANG10=  5.26932754e-03, ZANG10= -1.07102526e-02, MAXMAG10=  1.15156250e+01, MINMAG10=  5.79687500e+00, DIMDTS10= 20, RESTRK10= 1, IMGSZ10= 1, TYPE10= 0, IMNUM11= 2, YANG11=  1.20303248e-04, ZANG11= -5.58219646e-03, MAXMAG11=  1.14218750e+01, MINMAG11=  5.79687500e+00, DIMDTS11= 20, RESTRK11= 1, IMGSZ11= 1, TYPE11= 0, IMNUM12= 0, YANG12=  4.63366240e-07, ZANG12=  4.63366240e-07, MAXMAG12=  0.00000000e+00, MINMAG12=  0.00000000e+00, DIMDTS12= 0, RESTRK12= 0, IMGSZ12= 0, TYPE12= 0, IMNUM13= 0, YANG13=  4.63366240e-07, ZANG13=  4.63366240e-07, MAXMAG13=  0.00000000e+00, MINMAG13=  0.00000000e+00, DIMDTS13= 0, RESTRK13= 0, IMGSZ13= 0, TYPE13= 0, IMNUM14= 0, YANG14=  4.63366240e-07, ZANG14=  4.63366240e-07, MAXMAG14=  0.00000000e+00, MINMAG14=  0.00000000e+00, DIMDTS14= 0, RESTRK14= 0, IMGSZ14= 0, TYPE14= 0, IMNUM15= 0, YANG15=  4.63366240e-07, ZANG15=  4.63366240e-07, MAXMAG15=  0.00000000e+00, MINMAG15=  0.00000000e+00, DIMDTS15= 0, RESTRK15= 0, IMGSZ15= 0, TYPE15= 0, IMNUM16= 0, YANG16=  4.63366240e-07, ZANG16=  4.63366240e-07, MAXMAG16=  0.00000000e+00, MINMAG16=  0.00000000e+00, DIMDTS16= 0, RESTRK16= 0, IMGSZ16= 0, TYPE16= 0, , SCS= 129, STEP= 118
2015:063:00:29:59.958 |  4182511 0 | COMMAND_SW       | TLMSID= AOMANUVR, HEX= 8034101, MSID= AOMANUVR, SCS= 129, STEP= 169
2015:063:00:45:12.746 |  4186073 0 | COMMAND_SW       | TLMSID= AODSDITH, HEX= 8034300, MSID= AODSDITH, SCS= 129, STEP= 194
2015:063:00:51:11.746 |  4187474 0 | MP_DITHER        | TLMSID= AODITPAR, CMDS= 9, ANGP=  3.49065885e-02, ANGY=  0.00000000e+00, COEFP=  3.10279953e-04, COEFY=  3.87799955e-05, RATEP=  2.37369956e-03, RATEY=  6.28318917e-03, , SCS= 129, STEP= 200
2015:063:00:51:12.746 |  4187478 0 | COMMAND_SW       | TLMSID= AOENDITH, HEX= 8034301, MSID= AOENDITH, SCS= 129, STEP= 210
2015:063:00:52:42.746 |  4187830 0 | COMMAND_SW       | TLMSID= AOFUNCEN, HEX= 8030320, MSID= AOFUNCEN, AOPCADSE=32 , SCS= 129, STEP= 212
"""
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
