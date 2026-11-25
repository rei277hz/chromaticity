"""Export a square texture from the certified Rec.709 limiting color."""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from color_tools.color_core import modcam16
from .rec709_fixed_jhk_decode import Decoder, REFERENCE_NITS
from .rec709_ramp_gamut import map_chroma
from .rec709_ramp_images import write_images, write_preview


SIZE = 1024
WHITE_HEIGHT = 100.
RGB_ROUNDOFF = 2e-12


def verify_appearance(rgb, heights, chroma, hue, decoder):
    """Forward-encode the float texture and measure errors in its ramp coordinates."""
    rgb_to_cones = np.linalg.inv(decoder.linear_rgb_matrix)
    height_error = chroma_error = hue_error = 0.
    for start in range(0, SIZE, 64):
        rows = slice(start, start + 64)
        block = rgb[rows].astype(float)
        gray = block[..., 1, None]
        cones = gray + (block - gray) @ rgb_to_cones.T
        q = modcam16.encode_cones(cones, reference=REFERENCE_NITS).q
        actual_chroma = np.hypot(q[..., 1], q[..., 2])
        actual_hue = np.arctan2(q[..., 2], q[..., 1])
        angular_error = np.arctan2(np.sin(actual_hue - hue), np.cos(actual_hue - hue))
        hue_error = max(hue_error, float(np.max(abs(angular_error[chroma[rows] > 0]), initial=0)))
        height_error = max(height_error, float(np.max(abs(q[..., 0] - heights[rows, None]))))
        chroma_error = max(chroma_error, float(np.max(abs(actual_chroma - chroma[rows]))))

    if not (height_error <= 1e-5 and chroma_error <= 2e-5 and hue_error <= 2e-4):
        raise ValueError(f'Ramp appearance verification failed: {height_error=}, {chroma_error=}, {hue_error=}')
    return {'j_hk': height_error, 'chroma': chroma_error, 'hue_radians': hue_error}


def chroma_for_saturation(height, saturation):
    """Solve J_HK^2 = J_A^2 + 66 C with saturation C / J_A."""
    offset = (modcam16.HK / 2) * saturation
    denominator = np.hypot(height, offset) + offset
    numerator = saturation * height**2
    return np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)


def generate(limit, output_dir, saturation_preview=False):
    solution, certificate = limit['solution'], limit['certificate']
    if (limit['color_space'] != 'Linear Rec.709' or limit['reference_white_nits'] != REFERENCE_NITS
            or solution['j_hk_limit'] != WHITE_HEIGHT or solution['contact_face'] != 'B=0'):
        raise ValueError('Unexpected Rec.709 limiting-color calibration')

    hue_low, hue_high = certificate['tangent_hue_radians']
    chroma_low, chroma_high = certificate['first_contact_chroma_interval']
    anchor_chroma = solution['chroma_estimate']
    anchor = np.asarray(solution['linear_rgb_estimate'], dtype=float)
    if not (0 < hue_low < hue_high < math.tau and 0 < chroma_low <= anchor_chroma <= chroma_high
            and anchor.shape == (3,) and np.all((0 <= anchor) & (anchor <= 1)) and anchor[2] == 0):
        raise ValueError('Unexpected dimensions or bounds in the limiting-color report')

    # The lower hue endpoint has a certified inward white slope. The top-left
    # texel uses the reported anchor itself, which lies within the same hue bracket.
    hue = hue_low
    decoder = Decoder(height=WHITE_HEIGHT)
    heights = np.linspace(WHITE_HEIGHT, 0, SIZE)
    orientation = {'first_row': 'top', 'j_hk_top_to_bottom': [WHITE_HEIGHT, 0]}
    if saturation_preview:
        anchor_saturation = solution['saturation_estimate']
        saturation = np.linspace(anchor_saturation, 0, SIZE)
        requested = chroma_for_saturation(heights[:, None], saturation)
        if not math.isclose(requested[0, 0], anchor_chroma, rel_tol=1e-12, abs_tol=0):
            raise ValueError('The saturation axis does not start at the certified anchor')
        requested[0, 0] = anchor_chroma
        actual_ja = np.sqrt(heights[:-1, None]**2 - modcam16.HK * requested[:-1])
        if not np.allclose(requested[:-1] / actual_ja, saturation, rtol=1e-10, atol=0):
            raise ValueError('Requested saturation does not match the horizontal axis')
        orientation['requested_saturation_c_over_j_a_left_to_right'] = [anchor_saturation, 0]
    else:
        requested = np.broadcast_to(np.linspace(anchor_chroma, 0, SIZE), (SIZE, SIZE))
        orientation['requested_chroma_left_to_right'] = [anchor_chroma, 0]
    chroma = map_chroma(heights, requested, hue)
    if abs(chroma[0, 0] - anchor_chroma) > chroma_high - chroma_low:
        raise ValueError('The top-left gamut limit disagrees with the certified anchor')
    chroma[0, 0] = anchor_chroma

    rgb = decoder.rgb_at_height(heights[:, None], chroma, hue)
    rgb[0, 0] = anchor
    if not np.isfinite(rgb).all() or rgb.min() < -RGB_ROUNDOFF or rgb.max() > 1 + RGB_ROUNDOFF:
        raise ValueError('Gamut-mapped ramp contains RGB outside the cube')
    rgb = np.clip(rgb, 0, 1).astype(np.float32)
    if not (np.array_equal(rgb[0, 0], anchor.astype(np.float32))
            and np.all(rgb[0, -1] == 1) and np.all(rgb[-1] == 0)):
        raise ValueError('Ramp corners do not match the requested orientation')

    mapped = chroma < requested
    mapped_count = int(np.count_nonzero(mapped))
    if not (np.all(chroma >= 0) and np.all(chroma <= requested)
            and not mapped[:, -1].any() and not mapped[0].any()
            and np.array_equal(mapped[-1], requested[-1] > 0)
            and np.all(rgb[..., 2][mapped] <= RGB_ROUNDOFF)):
        raise ValueError('Ramp chroma mapping disagrees with the certified geometry')
    errors = verify_appearance(rgb, heights, chroma, hue, decoder)
    if saturation_preview:
        write_preview(output_dir / 'preview.png', rgb)
    else:
        write_images(output_dir, rgb)
    report = {
        'schema': 1,
        'size': [SIZE, SIZE],
        'reference_white_nits': REFERENCE_NITS,
        'preview_color_space': 'sRGB',
        'orientation': orientation,
        'hue_degrees': solution['hue_degrees_estimate'],
        'raster_hue_radians': hue,
        'mapped_texels': mapped_count,
        'mapped_texels_percent': 100 * mapped_count / (SIZE * SIZE),
        'linear_rgb_corners': {'top_left': rgb[0, 0].tolist(), 'top_right': rgb[0, -1].tolist(),
                               'bottom_left': rgb[-1, 0].tolist(), 'bottom_right': rgb[-1, -1].tolist()},
        'float_texture_appearance_max_absolute_error': errors,
    }
    if not saturation_preview:
        report['texture_color_space'] = 'Linear Rec.709'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saturation-preview', action='store_true')
    parser.add_argument('--limit-report', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    limit = json.loads(args.limit_report.read_text(encoding='utf-8'))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = generate(limit, args.output_dir, saturation_preview=args.saturation_preview)
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
