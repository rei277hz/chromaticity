"""Find and certify the strongest first Rec.709 boundary contact at J_HK=99.9."""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np

from color_tools.color_core.modcam16 import HK
from .rec709_fixed_jhk_decode import Decoder, HEIGHT, REFERENCE_NITS


CONTACT_TOLERANCE = 1e-6
GLOBAL_TOLERANCE = 1e-4
FACES = ('R=0', 'G=0', 'B=0', 'R=1', 'G=1', 'B=1')


@dataclass(frozen=True)
class Contact:
    hue: float
    inside: float
    outside: float
    prefix_boxes: int


def violations(rgb):
    return np.concatenate((-rgb, rgb - 1), axis=-1)


def outside_faces(bounds):
    return np.concatenate((bounds.hi < 0, bounds.lo > 1), axis=-1)


def prove_interior(decoder, chroma_range, hue_range):
    """Count chroma boxes covering a region by strict cube interior bounds."""
    low, high = (np.array([endpoint]) for endpoint in chroma_range)
    count = 0
    for _ in range(48):
        rgb = decoder.bounds(low, high, *hue_range)
        interior = np.all((rgb.lo > 0) & (rgb.hi < 1), axis=-1)
        count += int(np.count_nonzero(interior))
        if np.all(interior):
            return count
        if np.any(outside_faces(rgb)):
            return None
        low, high = low[~interior], high[~interior]
        middle = (low + high) / 2
        if np.any((middle == low) | (middle == high)) or low.size > 8192:
            return None
        low, high = np.concatenate((low, middle)), np.concatenate((middle, high))
    return None


def estimated_contacts(decoder, hues):
    """Seed the search with float probes. The interval checks decide acceptance."""
    chroma = np.linspace(0, decoder.chroma_limit, 513)
    outside = np.any(violations(decoder.rgb(chroma, hues[:, None])) > 0, axis=-1)
    if np.any(outside[:, 0]) or np.any(~outside[:, -1]):
        raise ValueError('Expected the gray point inside and the zero-J_A endpoint outside')
    first = np.argmax(outside, axis=-1)
    low, high = chroma[first - 1], chroma[first]
    for _ in range(32):
        mid = (low + high) / 2
        exterior = np.any(violations(decoder.rgb(mid, hues)) > 0, axis=-1)
        low, high = np.where(exterior, low, mid), np.where(exterior, mid, high)
    return (low + high) / 2


def improve_contact(decoder, hues, best=None):
    estimates = np.concatenate([
        estimated_contacts(decoder, hues[start:start + 256])
        for start in range(0, len(hues), 256)
    ])
    for index in np.argsort(-estimates, kind='stable'):
        hue = float(hues[index])
        low = max(0., float(estimates[index] - CONTACT_TOLERANCE / 4))
        high = min(decoder.chroma_limit, float(estimates[index] + CONTACT_TOLERANCE / 4))
        if best is not None and low <= best.inside:
            break
        if np.any(outside_faces(decoder.bounds(high, high, hue, hue))):
            count = prove_interior(decoder, (0., low), (hue, hue))
            if count is not None:
                return Contact(hue, low, high, count)
    return best


def witness_chromas(decoder, hues, upper):
    """Pick probes with large exterior margins for each hue midpoint."""
    # Use smaller spacing near gray, where a light RGB face can be crossed early.
    chroma = upper * np.linspace(0, 1, 513)**2
    for start in range(0, len(hues), 256):
        batch = hues[start:start + 256, None]
        margins = np.max(violations(decoder.rgb(chroma, batch)), axis=-1)
        yield from chroma[np.argmax(margins, axis=-1)]


def certify_hues(decoder):
    """Cover the hue circle with chroma witnesses no later than the upper bound."""
    # The next float above tau encloses the exact end of the hue circle.
    angles = np.linspace(0., math.nextafter(math.tau, math.inf), 257)
    best = improve_contact(decoder, angles[:-1])
    if best is None:
        raise ValueError('No positive first-contact bracket was certified')
    low, high = angles[:-1], angles[1:]
    witnesses = []
    for _ in range(40):
        mid = (low + high) / 2
        best = improve_contact(decoder, mid, best)
        upper = min(decoder.chroma_limit, math.nextafter(best.inside + GLOBAL_TOLERANCE, -math.inf))
        chroma = np.fromiter(witness_chromas(decoder, mid, upper), dtype=float, count=len(mid))
        exterior = outside_faces(decoder.bounds(chroma, chroma, low, high))
        certified = np.any(exterior, axis=-1)
        for index in np.flatnonzero(certified):
            witnesses.append((float(low[index]), float(high[index]), float(chroma[index]),
                              FACES[int(np.argmax(exterior[index]))]))
        if np.all(certified):
            return best, upper, sorted(witnesses)
        low, mid, high = low[~certified], mid[~certified], high[~certified]
        if np.any((mid == low) | (mid == high)) or low.size > 8192:
            break
        low, high = np.concatenate((low, mid)), np.concatenate((mid, high))
    raise ValueError(f'Global chroma bound unresolved for {low.size} hue intervals near {low.min():.9g} radians')


def derive():
    decoder = Decoder()
    contact, upper, witnesses = certify_hues(decoder)
    gap = math.nextafter(upper - contact.inside, math.inf)
    if not (0 < contact.inside < contact.outside <= upper
            and contact.outside - contact.inside <= CONTACT_TOLERANCE
            and gap <= GLOBAL_TOLERANCE):
        raise ValueError('Invalid chroma bounds')
    if (witnesses[0][0] != 0 or witnesses[-1][1] <= math.tau
            or any(left[1] != right[0] for left, right in zip(witnesses, witnesses[1:]))):
        raise ValueError('The certified hue intervals do not cover the full circle')

    bounds = decoder.bounds(contact.inside, contact.outside, contact.hue, contact.hue)
    touched = np.concatenate((bounds.lo <= 0, bounds.hi >= 1))
    face_indices = np.flatnonzero(touched)
    faces = [FACES[index] for index in face_indices]
    chroma = (contact.inside + contact.outside) / 2
    rgb = decoder.rgb(chroma, contact.hue)
    if len(face_indices) == 1:
        # The certificate fixes this channel exactly at the first contact.
        face_index = int(face_indices[0])
        rgb[face_index % 3] = face_index // 3
    ja = math.sqrt(HEIGHT**2 - HK * chroma)
    return {
        'schema': 1,
        'color_space': 'Linear Rec.709',
        'white_point': 'D65',
        'reference_white_nits': REFERENCE_NITS,
        'solution': {
            'j_hk': HEIGHT,
            'j_a_estimate': ja,
            'hue_degrees': math.degrees(contact.hue),
            'chroma_estimate': chroma,
            'saturation_estimate': chroma / ja,
            'contact_face': faces[0] if len(faces) == 1 else None,
            'possible_contact_faces': faces,
            'linear_rgb_estimate': rgb.tolist(),
            'linear_rgb_nits_estimate': (REFERENCE_NITS * rgb).tolist(),
        },
        'certificate': {
            'hue_radians': contact.hue,
            'first_contact_chroma_interval': [contact.inside, contact.outside],
            'first_contact_linear_rgb_bounds': [bounds.lo.tolist(), bounds.hi.tolist()],
            'interior_prefix_boxes': contact.prefix_boxes,
            'global_chroma_upper_bound': upper,
            'global_chroma_gap_bound': gap,
            'exterior_witnesses': [
                {'hue_interval_radians': [low, high], 'chroma': c, 'face': face}
                for low, high, c, face in witnesses
            ],
        },
    }


def summary(report):
    solution, certificate = report['solution'], report['certificate']
    low, high = certificate['first_contact_chroma_interval']
    rgb = ', '.join(f'{channel:.9g}' for channel in solution['linear_rgb_estimate'])
    nits = ', '.join(f'{channel:.9g}' for channel in solution['linear_rgb_nits_estimate'])
    face = solution['contact_face']
    face_description = (f'The contact is on `{face}`.' if face else
                        f"Possible contact faces are `{', '.join(solution['possible_contact_faces'])}`.")
    return '\n'.join([
        '# Rec.709 first boundary at J_HK = 99.9',
        '',
        f"Hue **{solution['hue_degrees']:.9f} degrees**, chroma **{solution['chroma_estimate']:.9f}**, "
        f"saturation `C / J_A = {solution['saturation_estimate']:.9f}`.",
        f'Linear RGB is approximately `({rgb})`, or `({nits})` nits per channel.',
        f'The first contact is in the chroma bracket `[{low:.12f}, {high:.12f}]`. {face_description}',
        '',
        'Directed interval bounds certify the radial segment from gray through the inner bracket endpoint.',
        'The outer endpoint is outside the cube, so the first contact lies between the endpoints.',
        f"Exterior witnesses cover the hue circle and bound every first-contact chroma above by "
        f"{certificate['global_chroma_upper_bound']:.12f}. The global chroma gap is at most "
        f"{certificate['global_chroma_gap_bound']:.9g}.",
        '',
        'Reproduce with `buck2 build --remote-only //libraries/perceptual-grade-core:rec709_fixed_jhk_boundary`.',
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
