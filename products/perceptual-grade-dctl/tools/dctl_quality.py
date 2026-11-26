"""Measure DCTL precision at the signed XYZ and cone-response boundaries."""
import argparse
import json
from pathlib import Path

import numpy as np
from color_tools.perceptual_grade_reference.model import rgb_matrix

from tests.support import cone_reference as cone, dctl_reference as reference, oracle
from tests.support.dctl import PROTOTYPES, STAGES, SURFACE_PROTOTYPES

XYZ = "Linear XYZ D65, 203-nit reference white"
CONE = "Raw modCAM16 cone responses"


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
    result = {
        "linear": dict(srcWhite=3, globalExposure=.2, ls=5., ba=7.),
        "input": {},
        "tone_jc": dict(inputShadows=4., inputMidtones=43., remapFit=2,
                        cMutedGain=-.25, cVividGain=.5, cSaturationCrossover=.4,
                        shadowChroma=.3, highlightChroma=-.2),
        "warp": dict(toneMAdaptanceA=2., webhue00=-6, webchroma14=.2, webscale25=-.15),
        "output": {},
        "surface": dict(toneSJContrast=1.2, toneMJContrast=-.8, toneHCContrast=.12,
                        toneWCContrast=-.2, jSaturationCenter=.42, jSaturationWidth=.35,
                        cSaturationCenter=.65, cSaturationWidth=.75, globalChromaGain=.08),
    }
    prototype = dict(lightnessFit=2, chromaFit=-1, toneMCGain=.1, toneWCGamma=-.2,
                     toneSJLift=1.2, toneHJGain=-.15)
    result.update({stage: prototype | ({"saturationPivot": .2} if stage == "lgg_pivot" else {})
                   for stage in PROTOTYPES})
    return result


def metrics(actual, expected, inputs, *, comparison, space):
    error = np.max(abs(actual - expected), axis=-1)
    ratio = error / reference.tolerance(expected)
    worst = int(np.argmax(ratio))
    return dict(comparison=comparison, space=space,
                failed_pixels=int(np.count_nonzero(~(ratio <= 1.))),
                maximum_tolerance_fraction=float(ratio[worst]),
                output_minimum=float(np.min(actual)), output_maximum=float(np.max(actual)),
                worst=dict(input=inputs[worst].tolist(), expected=expected[worst].tolist(),
                           actual=actual[worst].tolist()))


def run(output, size):
    pixels = samples(size)
    wire = cone.from_xyz(pixels).astype("f4")
    settings = cases()
    results = {}
    actual_chain = expected_chain = baseline_chain = pixels
    reversible = ("tone_jc", "warp")
    for stage in (*STAGES, *PROTOTYPES, *SURFACE_PROTOTYPES):
        inputs = wire if stage in (*reversible, "output") else pixels
        space = CONE if stage in ("input", *reversible) else XYZ
        result = oracle.run(stage, inputs, settings[stage])
        expected = reference.apply(stage, inputs, settings[stage])
        results[stage] = metrics(result, expected, inputs, comparison="Float64 reference", space=space)
        if stage in reversible:
            inverse = dict(settings[stage], direction=1)
            restored = oracle.run(stage, result, inverse)
            results[stage + "_round_trip"] = metrics(restored, inputs, inputs,
                                                     comparison="Forward then inverse", space=space)
            restored = oracle.run(stage, oracle.run(stage, inputs, inverse), settings[stage])
            results[stage + "_inverse_first"] = metrics(restored, inputs, inputs,
                                                        comparison="Inverse then forward", space=space)
        if stage in STAGES and stage != "output":
            actual_chain = oracle.run(stage, actual_chain, settings[stage])
            expected_chain = reference.apply(stage, expected_chain, settings[stage])
            if stage not in reversible:
                baseline_chain = reference.apply(stage, baseline_chain, settings[stage])

    forward_output = oracle.run("output", actual_chain)
    results["chain"] = metrics(forward_output, cone.output(expected_chain), pixels,
                               comparison="Float64 forward chain", space=XYZ)
    for stage in reversed(reversible):
        actual_chain = oracle.run(stage, actual_chain, dict(settings[stage], direction=1))
    results["chain_appearance_round_trip"] = metrics(actual_chain, baseline_chain, pixels,
                                                     comparison="Undo Warp and Tone J/C against float64 XYZ Input",
                                                     space=CONE)
    results["chain_export_after_undo"] = metrics(oracle.run("output", actual_chain), cone.output(baseline_chain),
                                                pixels, comparison="Export after undoing Warp and Tone J/C", space=XYZ)
    report = dict(samples=len(pixels), controls=settings, results=results)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    lines = ["# Float32 DCTL quality", "",
             f"{len(pixels)} samples per test. The chain evaluates Linear, XYZ Input, Tone J/C, Warp and XYZ Output.",
             "The tolerance is 0.1% of the maximum expected channel magnitude in each pixel, with an absolute floor of 1e-7.",
             "", "| Stage | Comparison | Output space | Worst error / tolerance | Pixels outside tolerance |",
             "| --- | --- | --- | ---: | ---: |"]
    for stage, row in results.items():
        lines.append(f"| {stage} | {row['comparison']} | {row['space']} | "
                     f"{row['maximum_tolerance_fraction']:.6g} | {row['failed_pixels']} |")
    (output / "summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--size", type=int, default=9)
    args = parser.parse_args()
    run(args.output_dir, args.size)
