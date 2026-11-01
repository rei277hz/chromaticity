"""Certify outward cube-ray faces for stored and binary32-rounded adapters.

Directed intervals verify real equations using the actual stored constants.
This is a geometric certificate, not a proof of libm or shader execution.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_reference.cube import default_context
from .spindle_certificate import certify_faces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    context = default_context()
    stored = context.cache['matrices']
    rounded = stored.astype(np.float32).astype(np.float64)
    report = {
        'stored_binary64': certify_faces(context.fl, stored),
        'rounded_binary32': certify_faces(context.fl, rounded),
        'scope': 'Fixed-J_A, fixed-hue rays; six AP1 cube faces and both native adapters, including normalized tip limits.',
        'limitations': 'Certifies real decoder geometry at stored/rounded adapter coefficients; does not certify floating-point execution, fitted capacity accuracy, or inverse convergence.',
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    rows = ['# AP1 cube face certificate', '', report['scope'], '',
            '| Adapter constants | Interval boxes | Minimum normalized outward velocity |',
            '| --- | ---: | ---: |']
    for label in ('stored_binary64', 'rounded_binary32'):
        result = report[label]
        rows.append(f'| {label} | {result["interval_boxes"]} | {result["minimum_normalized_outward_velocity"]:.12g} |')
    rows += ['', report['limitations'], '']
    (args.output_dir/'summary.md').write_text('\n'.join(rows))


if __name__ == '__main__':
    main()
