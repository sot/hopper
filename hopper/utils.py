from itertools import izip

from Chandra.Time import DateTime


def as_date(time):
    return DateTime(time).date


def un_camel_case(cc_name):
    chars = []
    for c0, c1 in izip(cc_name[:-1], cc_name[1:]):
        # Lower case followed by Upper case then insert "_"
        chars.append(c0.lower())
        if c0.lower() == c0 and c1.lower() != c1:
            chars.append('_')
    chars.append(c1.lower())

    return ''.join(chars)


