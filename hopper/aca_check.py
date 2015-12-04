import re
from collections import defaultdict

import numpy as np
from astropy.table import Table

from .cmd_action import Cmd


class StarcatTable(Table):
    @property
    def mons(self):
        ok = self['type'] == 'MON'
        return self[ok]

    @property
    def guis(self):
        ok = (self['type'] == 'GUI') | (self['type'] == 'BOT')
        return self[ok]

    @property
    def acqs(self):
        ok = (self['type'] == 'ACQ') | (self['type'] == 'BOT')
        return self[ok]


class StarCatalogCmd(Cmd):
    """
    Parse Star catalog command AOSTRCAT

    2012:310:03:03:03.056 | 3173084 0 | MP_STARCAT | TLMSID= AOSTRCAT, CMDS= 49,
    IMNUM1= 0, YANG1= 6.09510552e-04, ZANG1= 8.97075878e-03, MAXMAG1=
    1.02187500e+01, MINMAG1= 5.79687500e+00, DIMDTS1= 20, RESTRK1= 1, IMGSZ1= 2,
    TYPE1= 2, ...

    Starcheck Perl code

    foreach my $i (1..16) {
        $c->{"SIZE$i"} = $sizes[$c->{"IMGSZ$i"}];
        $c->{"MAG$i"} = ($c->{"MINMAG$i"} + $c->{"MAXMAG$i"})/2;
        $c->{"TYPE$i"} = ($c->{"TYPE$i"} or $c->{"MINMAG$i"} != 0 or $c->{"MAXMAG$i"} != 0)? 
            $types[$c->{"TYPE$i"}] : 'NUL';
        push @{$self->{mon}},$i if ($c->{"TYPE$i"} eq 'MON');
        push @{$self->{fid}},$i if ($c->{"TYPE$i"} eq 'FID');
        push @{$self->{acq}},$i if ($c->{"TYPE$i"} eq 'ACQ' or $c->{"TYPE$i"} eq 'BOT');
        push @{$self->{gui}},$i if ($c->{"TYPE$i"} eq 'GUI' or $c->{"TYPE$i"} eq 'BOT');
        $c->{"YANG$i"} *= $r2a;
        $c->{"ZANG$i"} *= $r2a;
        $c->{"HALFW$i"} = ($c->{"TYPE$i"} ne 'NUL')? 
            ( 40 - 35*$c->{"RESTRK$i"} ) * $c->{"DIMDTS$i"} + 20 : 0;
        $c->{"HALFW$i"} = $monhalfw[$c->{"IMGSZ$i"}] if ($c->{"TYPE$i"} eq 'MON');
        $c->{"YMAX$i"} = $c->{"YANG$i"} + $c->{"HALFW$i"};
        $c->{"YMIN$i"} = $c->{"YANG$i"} - $c->{"HALFW$i"};
        $c->{"ZMAX$i"} = $c->{"ZANG$i"} + $c->{"HALFW$i"};
        $c->{"ZMIN$i"} = $c->{"ZANG$i"} - $c->{"HALFW$i"};
    """
    cmd_trigger = {'tlmsid': 'AOSTRCAT'}
    subsystems = ['aca']

    def run(self):
        # Mappings from commanded (integer) value to canonical ACA checking
        # representations.
        sizes = ('4x4', '6x6', '8x8');
        mon_halfw = (10, 15, 20)
        types = ('ACQ', 'GUI', 'BOT', 'FID', 'MON')

        # Take command parameters like "yang14" and convert to a structure
        # like pars[14]['yang']
        re_par_idx = re.compile(r'([a-z]+) (\d+) $', re.VERBOSE)
        pars = defaultdict(dict)
        for key, val in self.cmd.items():
            match = re_par_idx.match(key)
            if match:
                par, idx = match.groups()
                pars[int(idx)][par] = val

        # Convert raw command parameter values to useful values in a list of
        # rows.  E.g.  pars[14]['YANG'] in radians goes to rows[13]['yang'] in
        # arcsec.
        rows = []
        for idx in range(1, 17):
            par = pars[idx]
            if par['minmag'] == par['maxmag'] == 0:
                # These special values indicate no star catalog entry so skip.
                continue

            row = dict(idx=idx,
                       size=sizes[par['imgsz']],
                       type=types[par['type']],
                       yang=np.degrees(par['yang']) * 3600,
                       zang=np.degrees(par['zang']) * 3600)
            row['halfw'] = (mon_halfw[par['size']] if (row['type'] == 'MON')
                            else (40 - 35 * par['restrk']) * par['dimdts'] + 20.0)
            rows.append(row)

        names = ('idx', 'type', 'size', 'yang', 'zang', 'halfw')
        starcat = StarcatTable(rows, names=names)
        starcat['yang'].format = ".1f"
        starcat['zang'].format = ".1f"
        starcat['halfw'].format = ".0f"
        self.SC.starcat = starcat
