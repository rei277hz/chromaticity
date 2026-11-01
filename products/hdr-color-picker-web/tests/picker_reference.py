"""Independent NumPy appearance equations and RGB colorimetry for OCIO tests.

No Rust, WASM, generated tables, or shader imports. The ACES transforms themselves
are exclusively evaluated by PyOpenColorIO with the official checked-in config.
"""
import numpy as np

WHITE = np.array([0.3127 / 0.329, 1, (1 - 0.3127 - 0.329) / 0.329])
CAT16 = np.array([[.401288, .650173, -.051461], [-.250268, 1.204414, .045854], [-.002079, .048952, .953127]])
ADAPTATION = 1 / (CAT16 @ WHITE)
LA = 20.3
k = 1 / (5 * LA + 1)
FL = .2 * k**4 * 5 * LA + .1 * (1 - k**4)**2 * (5 * LA)**(1 / 3)
Z = 1.48 + np.sqrt(.1)


def hyperbolic(v):
    p = (FL * v / 100)**.42
    return 400 * p / (27.13 + p)


LOW = hyperbolic(.26)
HIGH = hyperbolic(150)
SLOPE = 1.68 * 27.13 * FL * (FL * 150 / 100)**(-.58) / (27.13 + (FL * 150 / 100)**.42)**2
AW = 3.05 * hyperbolic(100)


def response(v):
    if v < .26:
        return LOW * v / .26 + .1
    if v > 150:
        return HIGH + SLOPE * (v - 150) + .1
    return hyperbolic(v) + .1


def inverse_response(v):
    v -= .1
    if v < LOW:
        return .26 * v / LOW
    if v > HIGH:
        return 150 + (v - HIGH) / SLOPE
    return 100 / FL * (27.13 * v / (400 - v))**(1 / .42)


def neutral_jhk(nits):
    a = 3.05 * response(nits / 203 * 100) - .305
    return 100 * (max(0, a) / AW)**(.525 * Z)


PEAK = neutral_jhk(1000)
FITTED_RADIUS_K = 5.977038579617132
FITTED_RADIUS_D = 3.557365336640551
# The browser ruler marks the 203-nit appearance white. In this fixed
# appearance context that white has J_HK=100.
REFERENCE_J = neutral_jhk(203) / PEAK


def rgb_matrix(primaries):
    columns = np.array([[x / y, 1, (1 - x - y) / y] for x, y in primaries]).T
    return columns @ np.diag(np.linalg.solve(columns, WHITE))


P3 = rgb_matrix([(.68, .32), (.265, .69), (.15, .06)])
REC709 = rgb_matrix([(.64, .33), (.30, .60), (.15, .06)])
REC2020 = rgb_matrix([(.708, .292), (.170, .797), (.131, .046)])


def code_xyz(code):
    j, x, y = code
    x, y = 2*x - 1, 2*y - 1
    radius = np.hypot(x, y)
    saturation = FITTED_RADIUS_K * np.expm1(FITTED_RADIUS_D * radius)
    h = np.arctan2(-x, y)
    u = .007 / .525 * saturation
    jhk = j * PEAK
    denominator = np.hypot(jhk, 33*u) + 33*u
    ja = jhk**2 / denominator if denominator > 0 else 0
    c = u * ja
    e = (1 - .0582*np.cos(h) - .0258*np.cos(2*h) - .1347*np.cos(3*h)
         + .0289*np.cos(4*h) - .1475*np.sin(h) - .0308*np.sin(2*h)
         + .0385*np.sin(3*h) + .0096*np.sin(4*h))
    opponent_radius = (c * AW / 35) / (43 * .8 * e)
    achromatic = AW * (ja / 100)**(1 / (.525 * Z))
    compressed = np.linalg.solve(
        [[2, 1, .05], [1, -12/11, 1/11], [1/9, 1/9, -2/9]],
        [achromatic + .305, opponent_radius * np.cos(h), opponent_radius * np.sin(h)],
    )
    sharpened = np.array([inverse_response(v) for v in compressed]) / ADAPTATION
    return np.linalg.solve(CAT16, sharpened) / 100
