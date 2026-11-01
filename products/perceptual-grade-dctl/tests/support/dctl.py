"""Perceptual Grade DCTL section markers and model declaration."""
from dctl_testing.parser import controls, section


def body(source):
    return section(source, '/* PG_NUMERICAL_BEGIN */', '/* PG_NUMERICAL_END */')


def model_call(source):
    return source.split('PGModel m=', 1)[1].split(';', 1)[0]
