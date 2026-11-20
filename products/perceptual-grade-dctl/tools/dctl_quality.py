"""Measure the four installed DCTLs against independent, signed XYZ stages."""
import argparse
import json
from pathlib import Path

import numpy as np
from color_tools.perceptual_grade_reference.model import rgb_matrix

from tests.support import dctl_reference as reference, oracle
from tests.support.dctl import STAGES


def samples(size):
    if size < 2:
        raise ValueError("Use at least two samples per axis")
    # Linear Rec.709 colors at different exposures, followed by signed XYZ probes.
    axis = np.linspace(0., 1., size)
    rgb = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)
    xyz = rgb @ rgb_matrix("Linear Rec.709").T
    rows = [xyz * gain for gain in (.01, 1., 10.)]
    rows.append(np.array([[-.2, -.1, -.35], [-.1, .2, .05], [5., 3., 4.]]))
    rows.append(reference.WHITE * np.array([[-4.], [2048.]]))
    return np.unique(np.vstack(rows).astype(np.float32), axis=0)


def cases():
    return {
        "linear": dict(srcWhite=3, globalExposure=.2, ls=5., ba=7.),
        "tone": dict(inputShadows=4., inputMidtones=43., remapFit=2),
        "jc": dict(toneHaToJ=1.2, toneSbToC=-.1, toneMHighToJ=-3.,
                   toneWLowToC=.08, globalChromaGain=.1),
        "warp": dict(toneMAdaptanceA=2., webhue00=-6, webchroma14=.2, webscale25=-.15),
    }


def metrics(actual, expected, inputs):
    error = np.max(abs(actual - expected), axis=-1)
    ratio = error / reference.tolerance(expected)
    worst = int(np.argmax(ratio))
    return dict(failed_pixels=int(np.count_nonzero(~(ratio <= 1.))),
                maximum_tolerance_fraction=float(ratio[worst]),
                output_minimum=float(np.min(actual)), output_maximum=float(np.max(actual)),
                worst=dict(input=inputs[worst].tolist(), expected=expected[worst].tolist(),
                           actual=actual[worst].tolist()))


def run(output, size):
    pixels = samples(size)
    settings = cases()
    results = {}
    actual_chain = expected_chain = pixels
    for stage in STAGES:
        result = oracle.run(stage, pixels, settings[stage])
        expected = reference.apply(stage, pixels, settings[stage])
        results[stage] = metrics(result, expected, pixels)
        actual_chain = oracle.run(stage, actual_chain, settings[stage])
        expected_chain = reference.apply(stage, expected_chain, settings[stage])
    results["chain"] = metrics(actual_chain, expected_chain, pixels)
    report = dict(samples=len(pixels), space="Linear XYZ D65, 203-nit reference white",
                  controls=settings, results=results)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    lines = ["# Float32 DCTL quality in linear XYZ", "",
             f"{len(pixels)} samples per test. The chain evaluates Linear, Tone, Color J/C and Warp.",
             "Each output is compared with its float64 reference at a tolerance of 0.1% of the expected pixel peak, with an absolute floor of 1e-7.",
             "", "| Stage | Worst error / tolerance | Pixels outside tolerance |",
             "| --- | ---: | ---: |"]
    for stage, row in results.items():
        lines.append(f"| {stage} | {row['maximum_tolerance_fraction']:.6g} | {row['failed_pixels']} |")
    (output / "summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--size", type=int, default=9)
    args = parser.parse_args()
    run(args.output_dir, args.size)
