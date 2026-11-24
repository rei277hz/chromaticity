"""Fixed-hue Rec.709 gamut mapping for the white-limit ramp."""

import numpy as np

from color_tools.color_core.modcam16 import GAMMA, HK
from tools.build.appearance_certificate import I
from tools.build.spindle_certificate import power

from .rec709_fixed_jhk_decode import Decoder


def certify_blue_boundary(decoder, hue):
    """Establish one blue-face crossing at every positive ramp height."""
    direction = decoder.direction_bounds(hue)
    left, middle, right = (direction[index] for index in range(3))
    red, green, blue = decoder.linear_rgb_matrix_bounds
    beta = decoder.normalized_white_response_bounds
    neutral_rate = (I(HK) / 10000) / (2 * GAMMA)

    if not (right.hi < 0 and (left - right).lo > 0 and (middle - left).lo > 0
            and (neutral_rate - middle).lo > 0 and beta.lo > 0 and beta.hi < 1):
        raise ValueError('The ramp hue must have ordered, decreasing cone responses')
    if not (red[0].lo > 0 and red[2].hi < 0 and green[0].hi < 0 and green[2].hi < 0
            and blue[0].lo > 0 and blue[2].lo > 0 and (blue[0] + blue[1]).hi < 0):
        raise ValueError('The Rec.709 inverse matrix does not support the blue-face certificate')

    # The normalized response t_M is the largest and lies at or below white.
    # For i=L,S, (cone_i / cone_M)^(21/50) =
    # 1 - C * (d_M - d_i) / (t_M * (1 - beta * t_i)). The denominator
    # strictly decreases: the worst ratio of response rates occurs at white.
    max_rate_ratio = (neutral_rate - right) / (neutral_rate - middle)
    if not (1 - beta * (1 + max_rate_ratio)).lo > 0:
        raise ValueError('The relative cone amplitudes were not proved decreasing')

    # Blue / cone_M consequently decreases and has one zero before t_S=0.
    # While blue is nonnegative, the minimum S/M cone ratio gives a lower
    # L/M cone ratio because L lies between S and M in response space.
    theta = (middle - left) / (middle - right)
    min_cone_ratio = -(blue[0] + blue[1]) / blue[2]
    min_response_ratio = power(min_cone_ratio, 21, 50)
    left_fraction = 1 - theta * (1 - min_response_ratio)
    min_left_ratio = power(left_fraction * (1 - beta) / (1 - beta * left_fraction), 50, 21)
    if not ((1 + red[0] * (min_left_ratio - 1)).lo > 0
            and (red[0] * theta + red[2]).lo > 0):
        raise ValueError('Red was not proved within the cube up to the blue-face crossing')

    # Cone decompression is convex, so the difference M-L uses at least
    # theta of the difference M-S. The red test above then bounds red by
    # cone_M, as the positive L,S weights do for blue. Green is positive.
    # Its chroma derivative is largest relative to the M-cone derivative at
    # white, where both cone derivative ratios are one and both response rate
    # ratios are maximal. A nonpositive white slope bounds green by gray.
    white_slope, _ = decoder.white_slopes(hue, hue)
    if not white_slope.hi[1] <= 0:
        raise ValueError('The ramp hue must be on the inward side of the white tangent')


def map_chroma(heights, requested, hue):
    """Cap chroma requests shared by all rows or supplied separately per row."""
    heights = np.asarray(heights, dtype=float)
    requested = np.asarray(requested, dtype=float)
    if (heights.ndim != 1 or not np.all(np.isfinite(heights) & (heights >= 0) & (heights <= 100))
            or requested.ndim not in (1, 2) or (requested.ndim == 2 and len(requested) != len(heights))
            or not np.all(np.isfinite(requested) & (requested >= 0))
            or not np.isfinite(hue)):
        raise ValueError('Expected heights in [0, 100], nonnegative chroma by column or row, and a finite hue')

    decoder = Decoder(height=100)
    certify_blue_boundary(decoder, hue)
    lowest_direction = decoder.direction(hue)[2]
    height_squared = heights**2
    inside = np.zeros_like(heights)
    outside = height_squared / HK
    for _ in range(55):
        chroma = (inside + outside) / 2
        energy = np.maximum(0, height_squared - HK * chroma) / 10000
        lowest_response = energy ** (1 / (2 * GAMMA)) + chroma * lowest_direction
        blue = decoder.rgb_at_height(heights, chroma, hue)[..., 2]
        keep = (lowest_response > 0) & (blue >= 0)
        inside = np.where(keep, chroma, inside)
        outside = np.where(keep, outside, chroma)

    # Reserve a few ulps on the legal side for float RGB evaluation.
    inside *= 1 - 32 * np.finfo(float).eps
    return np.minimum(requested, inside[:, None])
