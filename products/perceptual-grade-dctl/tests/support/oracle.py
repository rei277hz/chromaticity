"""Float32 DCTL subprocess adapter. No independent numerical reference math."""
from importlib.resources import files
import subprocess
import numpy as np
from .dctl import controls

RESOURCES = files('tests.support')
SOURCE = (RESOURCES / 'Perceptual-Grade.dctl').read_text()
UI = controls(SOURCE)
DEFAULTS = {item['name']: item['default'] for item in UI}


def run(mode, values, settings=None):
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[None, :]
    if not len(values):
        return np.empty((0, 5))
    fields = dict(DEFAULTS, **(settings or {}))
    for item in UI:
        if item['type'] in ('DCTLUI_SLIDER_INT', 'DCTLUI_COMBO_BOX'):
            fields[item['name']] = int(round(fields[item['name']]))
    prefix = ' '.join(format(fields[item['name']], '.17g') for item in UI)
    payload = ''.join(prefix + ' ' + ' '.join(format(v, '.17g') for v in row) + '\n' for row in values)
    output = subprocess.run([str(RESOURCES / 'oracle'), mode], input=payload, text=True, capture_output=True, check=True)
    result = np.fromstring(output.stdout, dtype=np.float32, sep=' ').reshape(-1, 5).astype(float)
    if len(result) != len(values):
        raise AssertionError('DCTL oracle returned an incorrect row count')
    return result


def settings(lp, tp, cp, space):
    result = dict(srcWhite=8, globalExposure=lp.exposure,
                  srcX=lp.source_x, srcY=lp.source_y, le=-lp.cr_balance, be=-lp.yb_balance,
                  ls=lp.cr_spread, bs=lp.yb_spread, la=lp.cr_heading, ba=lp.yb_heading,
                  inputBlack=tp.input_black, inputShadows=tp.input_shadows, inputMidtones=tp.input_midtones,
                  inputWhite=tp.input_white, inputHighlights=tp.input_highlights, remapFit=tp.fit,
                  peakNits=(500, 1000, 2000, 4000).index(tp.peak_nits),
                  globalChromaGain=cp.global_gain, globalHighChromaHue=cp.global_high_hue,
                  globalLowChromaHue=cp.global_low_hue, adaptanceStrength=cp.adaptance_strength,
                  lightnessFit=cp.j_fit, chromaFit=cp.c_fit, hueFit=cp.hue_fit, adaptanceFit=cp.adaptance_fit)
    families = {'j_low': 'LowToJ', 'j_high': 'HighToJ',
                'j_a': 'aToJ', 'j_b': 'bToJ',
                'c_low': 'LowToC', 'c_high': 'HighToC',
                'c_a': 'aToC', 'c_b': 'bToC',
                'hue': 'Hue', 'concentration_a': 'ConcentrationA', 'concentration_b': 'ConcentrationB',
                'adaptance_a': 'AdaptanceA', 'adaptance_b': 'AdaptanceB'}
    for family, suffix in families.items():
        for index, tone in enumerate('SMWH'):
            result['tone' + tone + suffix] = getattr(cp, family + '_' + str(index))
    return result


def grade(rgb, lp, tp, cp, space='Linear Rec.709', mode='grade'):
    # RGB/XYZ coordinates are adapters, not the grading oracle. Linear-matrix
    # tests compare in XYZ directly; appearance expectations always execute DCTL.
    from color_tools.perceptual_grade_core.model import linear
    rgb = np.asarray(rgb, dtype=float)
    shape = rgb.shape
    xyz = rgb.reshape(-1, 3) @ np.asarray(linear.rgb_to_xyz(space)).T
    result = run(mode, xyz, settings(lp, tp, cp, space))[:, :3]
    return (result @ np.asarray(linear.xyz_to_rgb(space)).T).reshape(shape)


def error(actual, expected, floor=1e-3):
    actual, expected = np.asarray(actual), np.asarray(expected)
    return np.max(np.abs(actual - expected), axis=-1) / np.maximum(floor, np.max(np.abs(expected), axis=-1))
