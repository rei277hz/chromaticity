"""Certify the one-sided limit of the strongest Rec.709 first boundary at white."""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from color_tools.color_core.modcam16 import HK
from tools.build.appearance_certificate import PI
from .rec709_fixed_jhk_boundary import FACES, outside_faces, prove_interior, witness_chromas
from .rec709_fixed_jhk_decode import Decoder, REFERENCE_NITS


HEIGHT = 100.
WHITE_PREFIX = 2.
LOCAL_HUE = (math.radians(137), math.radians(140))
TERMINAL_CHROMA = (45., 52.)


def increasing_root(evaluate, lo, hi, tolerance):
    """Retain a strict sign bracket, even when a probe encloses zero."""
    if not (evaluate(lo).hi < 0 and evaluate(hi).lo > 0):
        raise ValueError(f'Root not bracketed on [{lo}, {hi}]')
    while hi - lo > tolerance:
        width = hi - lo
        for fraction in (0.5, 0.25, 0.75):
            probe = lo + fraction * width
            value = evaluate(probe)
            if value.hi < 0:
                lo = probe
                break
            if value.lo > 0:
                hi = probe
                break
        else:
            raise ValueError(f'Root enclosure stalled on [{lo}, {hi}]')
    return lo, hi


def certify_tangent(decoder):
    low, high = LOCAL_HUE
    partition = np.linspace(low, high, 129)
    _, slope_h = decoder.white_slopes(partition[:-1], partition[1:])
    if not np.all(slope_h.lo[..., 1] > 0):
        raise ValueError('Green white slope was not proved strictly increasing')
    hue = increasing_root(lambda h: decoder.white_slopes(h, h)[0][1], low, high, 1e-11)

    chromas = np.linspace(0, WHITE_PREFIX, 129)
    dc, _ = decoder.slopes(chromas[:-1], chromas[1:], *hue)
    dcc = decoder.chroma_second(chromas[:-1], chromas[1:], *hue)
    rgb = decoder.bounds(chromas[:-1], chromas[1:], *hue)
    if not (np.all(dc.hi[..., (0, 2)] < 0) and np.all(dcc.hi[..., 1] < 0) and np.all(rgb.lo > 0)):
        raise ValueError('The tangent was not proved strictly inward from white')
    return hue


def certify_contact(decoder, hue):
    chroma = increasing_root(lambda c: -decoder.bounds(c, c, *hue)[2], *TERMINAL_CHROMA, 1e-7)
    rgb = decoder.bounds(*chroma, *hue)
    dc, _ = decoder.slopes(*chroma, *hue)
    if not (dc.hi[2] < 0 and np.all(rgb.lo[:2] > 0) and np.all(rgb.hi[:2] < 1) and rgb.hi[2] < 1):
        raise ValueError('The terminal bracket was not proved to cross only the blue face')
    interior_boxes = prove_interior(decoder, (WHITE_PREFIX, chroma[0]), hue)
    if interior_boxes is None:
        raise ValueError('The segment between the white and blue neighborhoods was not proved interior')

    partition = np.linspace(*LOCAL_HUE, 129)
    _, dh = decoder.slopes(*chroma, partition[:-1], partition[1:])
    if not np.all(dh.lo[..., 2] > 0):
        raise ValueError('Blue was not proved strictly increasing with hue at the terminal chroma')
    return chroma, rgb, interior_boxes


def exclude_other_hues(decoder, chroma):
    edges = (np.linspace(0, LOCAL_HUE[0], 129), np.linspace(LOCAL_HUE[1], float((2 * PI).hi), 129))
    low = np.concatenate([arc[:-1] for arc in edges])
    high = np.concatenate([arc[1:] for arc in edges])
    witnesses = []
    for _ in range(40):
        initial, _ = decoder.white_slopes(low, high)
        outward = initial.lo > 0
        excluded = np.any(outward, axis=-1)
        for index in np.flatnonzero(excluded):
            witnesses.append({
                'hue_radians': [float(low[index]), float(high[index])],
                'outward_white_face': FACES[3 + int(np.argmax(outward[index]))],
            })
        low, high = low[~excluded], high[~excluded]
        if not low.size:
            return witnesses

        middle = (low + high) / 2
        probes = np.fromiter(witness_chromas(decoder, middle, chroma), dtype=float, count=middle.size)
        exterior = outside_faces(decoder.bounds(probes, probes, low, high))
        excluded = np.any(exterior, axis=-1)
        for index in np.flatnonzero(excluded):
            witnesses.append({
                'hue_radians': [float(low[index]), float(high[index])],
                'exterior_chroma': float(probes[index]),
                'exterior_face': FACES[int(np.argmax(exterior[index]))],
            })
        low, middle, high = low[~excluded], middle[~excluded], high[~excluded]
        if not low.size:
            return witnesses
        if np.any((middle == low) | (middle == high)) or low.size > 8192:
            break
        low, high = np.concatenate((low, middle)), np.concatenate((middle, high))
    raise ValueError(f'Unresolved competing hue intervals near {math.degrees(low.min()):.9f} degrees')


def derive():
    decoder = Decoder(height=HEIGHT)
    hue = certify_tangent(decoder)
    chroma, rgb_bounds, interior_boxes = certify_contact(decoder, hue)
    witnesses = sorted(exclude_other_hues(decoder, chroma[0]), key=lambda w: w['hue_radians'])
    intervals = sorted([LOCAL_HUE, *(tuple(w['hue_radians']) for w in witnesses)])
    if (intervals[0][0] != 0 or intervals[-1][1] < float((2 * PI).hi)
            or any(a[1] != b[0] for a, b in zip(intervals, intervals[1:]))):
        raise ValueError('The certificate does not cover the hue circle')

    h, c = sum(hue) / 2, sum(chroma) / 2
    rgb = decoder.rgb(c, h)
    rgb[2] = 0
    ja = math.sqrt(HEIGHT**2 - HK * c)
    return {
        'schema': 1,
        'color_space': 'Linear Rec.709',
        'white_point': 'D65',
        'reference_white_nits': REFERENCE_NITS,
        'solution': {
            'j_hk_limit': HEIGHT,
            'hue_degrees_estimate': math.degrees(h),
            'chroma_estimate': c,
            'j_a_estimate': ja,
            'saturation_estimate': c / ja,
            'contact_face': 'B=0',
            'linear_rgb_estimate': rgb.tolist(),
            'linear_rgb_nits_estimate': (REFERENCE_NITS * rgb).tolist(),
        },
        'certificate': {
            'local_hue_radians': LOCAL_HUE,
            'tangent_hue_radians': hue,
            'white_prefix_chroma': WHITE_PREFIX,
            'interior_prefix_boxes': interior_boxes,
            'first_contact_chroma_interval': chroma,
            'first_contact_linear_rgb_bounds': [[*rgb_bounds.lo[:2], 0], [*rgb_bounds.hi[:2], 0]],
            'exterior_witnesses': witnesses,
        },
    }


def summary(report):
    solution, certificate = report['solution'], report['certificate']
    rgb = ', '.join(f'{channel:.10g}' for channel in solution['linear_rgb_estimate'])
    nits = ', '.join(f'{channel:.10g}' for channel in solution['linear_rgb_nits_estimate'])
    lo, hi = certificate['first_contact_chroma_interval']
    return '\n'.join([
        '# Rec.709 boundary limit as J_HK approaches 100 from below',
        '',
        f"The limiting hue is **{solution['hue_degrees_estimate']:.9f} degrees** and chroma is "
        f"**{solution['chroma_estimate']:.9f}**. Saturation `C / J_A` is {solution['saturation_estimate']:.9f}.",
        f'Linear RGB is approximately `({rgb})`, or `({nits})` nits per channel. The contact is on `B=0`.',
        f'The certified chroma interval is `[{lo:.12f}, {hi:.12f}]`.',
        '',
        'At white, the selected hue has zero initial green slope and strictly negative green curvature. '
        'Red and blue initially decrease. Directed interval bounds certify the interior segment and its '
        'first positive-chroma contact at blue zero.',
        'Nearby higher hues have positive initial green slope. Nearby lower hues have negative blue at '
        'the selected contact chroma. The remaining hues have outward slopes at white or certified exterior '
        'points before the contact. These signs establish the unique longest prefix at `J_HK = 100`.',
        '',
        'For heights approaching 100 from below, compactness of the hue circle and continuity of raw RGB '
        'make every limit of feasible prefixes feasible at 100, bounding their lengths above. At the '
        'selected hue, each RGB channel has positive height derivative at white because the neutral '
        'response increases and the inverse cone matrix preserves gray. That derivative stays positive '
        'near white, so reducing height moves the initial segment inward. Any shortened prefix away '
        'from white stays interior by compactness and continuity. This proves convergence of the optimal '
        'chroma, and uniqueness at 100 gives convergence of the optimizing hues and colors.',
        '',
        'Every height strictly between black and white has a positive first-contact chroma, so there is '
        'no first qualifying height strictly below 100.',
        '',
        'Reproduce with `buck2 build --remote-only //libraries/perceptual-grade-core:rec709_fixed_jhk_limit`.',
        '',
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    report = derive()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (args.output_dir / 'summary.md').write_text(summary(report), encoding='utf-8')


if __name__ == '__main__':
    main()
