"""Derive the largest Rec.709 J_HK with a fully in-gamut reduction rectangle."""

import argparse
import json
import math
from pathlib import Path

from color_tools.color_core import linear, modcam16


COLOR_SPACE = 'Linear Rec.709'
REFERENCE_NITS = 203


def derive():
    rgb_to_cat16 = linear.mm(linear.CAT16, linear.rgb_to_xyz(COLOR_SPACE))
    white_cat16 = linear.mv(linear.CAT16, linear.xyz(linear.D65))
    rgb_to_cones = tuple(
        tuple(value / white for value in row)
        for row, white in zip(rgb_to_cat16, white_cat16)
    )
    minimum = min(value for row in rgb_to_cones for value in row)
    if not minimum > 0 or not modcam16.HK > 0:
        raise ValueError('The reduction bound requires positive cone coefficients and H-K gain')

    # The bound forces zero chroma, whose maximum is the D65 neutral endpoint.
    rgb = (1, 1, 1)
    white = modcam16.encode_cones(rgb, reference=REFERENCE_NITS)
    j_hk = 100  # A / A_W is exactly one at white.
    if white.q[1:].any() or not math.isclose(white.q[0], j_hk, rel_tol=0, abs_tol=1e-12):
        raise ValueError('Neutral white disagrees with the modCAM16 normalization')

    return {
        'schema': 1,
        'color_space': COLOR_SPACE,
        'white_point': 'D65',
        'reference_white_nits': REFERENCE_NITS,
        'solution': {
            'linear_rgb': rgb,
            'linear_rgb_nits': tuple(value * REFERENCE_NITS for value in rgb),
            'j_hk': j_hk,
            'chroma': 0,
            'hue_degrees': None,
        },
        'containment': {
            'j_hk_range': (0, j_hk),
            'chroma_range': (0, 0),
            'rgb_to_normalized_cat16_cones': rgb_to_cones,
            'minimum_cone_coefficient': minimum,
            'hk_coefficient': modcam16.HK,
        },
    }


def summary(report):
    solution = report['solution']
    containment = report['containment']
    return '\n'.join([
        '# Rec.709 fixed-hue reduction limit',
        '',
        f"The unique maximum is D65 white at linear RGB `{solution['linear_rgb']}`, "
        f"or `{solution['linear_rgb_nits']}` nits per channel. "
        f"`J_HK = {solution['j_hk']}` and `C = 0`. Hue is undefined.",
        '',
        'The D65-normalized Rec.709-to-CAT16 matrix has strictly positive entries '
        f"(minimum {containment['minimum_cone_coefficient']:.12g}). Nonnegative RGB gives "
        'nonnegative cone responses and nonnegative `J_A`. Consequently every color in the cube '
        f"satisfies `J_HK >= sqrt({containment['hk_coefficient']:g} * C)`. Every rectangle with "
        'positive starting chroma includes points with `J_HK = 0` and `C > 0`, '
        'which violate the bound at every hue.',
        '',
        'At `C = 0`, the two opponent components vanish and the three compressed cone responses '
        'are equal. Cone compression is strictly increasing. The D65-normalized cone transform '
        'is invertible and preserves the neutral axis, so these colors are exactly `(x, x, x)` '
        'with `0 <= x <= 1`. Along this segment `J_HK = J_A` increases strictly from 0 at black '
        f"to {solution['j_hk']} at white, where `A = A_W`.",
        '',
        'Reproduce with `buck2 build --remote-only //libraries/perceptual-grade-core:rec709_reduction_limit`.',
        '',
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    report = derive()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (args.output_dir / 'summary.md').write_text(summary(report), encoding='utf-8')


if __name__ == '__main__':
    main()
