"""Source-bound local Web diagnostics for actual reduced toe textures.

Scalar/local precision does not admit a toe layout: the complete HDR report
owns that decision. This report retains local errors and enforces finite,
sign and saturation checks against the legacy fine-toe native baseline.
"""
import argparse
from dataclasses import asdict, replace
from functools import partial
import hashlib
import json
from pathlib import Path

import numpy as np

from color_tools.perceptual_grade_nodes import prepare
from color_tools.perceptual_grade_nodes.color_prepare import _generate_field
from color_tools.perceptual_grade_nodes.layouts import supported_cells
from color_tools.perceptual_grade_reference import grading
from color_tools.perceptual_grade_reference.responses import State
from . import color_local, full_cases, oracle
from .color_local import stage_builder, connect_frozen, rounded_state, local_color_frames
from .evaluate import evidence_hashes
from .gate_policy import texture_admission_policy, web_local_limit
from .native import NativeFixture


LEGACY_TOE_CELLS = 524288
DEFAULT_CASES = ('all_active', 'web_log_chroma', 'web_log_scale', 'web_alternating_extremes')


def with_toe_cells(prepared, cells):
    """Replace only the toe payload, without a development audit or search."""
    if cells not in supported_cells('Web toes'):
        raise ValueError('Unsupported Web-toe diagnostic size')
    current = prepared.color.web_toe_table
    # A specialized inactive Web path owns neither a toe image nor the Web
    # geometry needed to evaluate one. Preserve that legitimate omission.
    if current is None or current.cells == cells:
        return prepared
    color = prepared.color
    def evaluator(x):
        return np.concatenate((color.web_toes(x*color.high), np.zeros(x.shape+(1,))), axis=-1)
    table = _generate_field('Web toes', evaluator,
        {'angular_toe': (0,), 'chroma_toe': (1,), 'scale_toe': (2,)},
        'linear', color.high, color.anchors/color.high,
        relative_columns=(0, 1, 2), cells=cells)
    return replace(prepared, color=replace(color, web_toe_table=table))


def _identity():
    return dict(**evidence_hashes(), local_tool_sha256={
        Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in (__file__, color_local.__file__)})


def _web_expected(reference, source, frozen):
    captured = []
    def capture(q, energy):
        captured.append(State(q, energy))
        return q, energy
    final_q, _ = reference.web.apply(source.q, source.energy,
                                    frozen[:, 0].astype(float), transform=capture)
    expected = captured[0] if captured else source
    before = np.hypot(expected.q[:, 1], expected.q[:, 2])
    scale = np.divide(np.hypot(final_q[:, 1], final_q[:, 2]), before,
                      out=np.ones_like(before), where=before != 0)
    return expected, scale


def seam_inputs(prepared):
    """Every target sector seam, both adjacent float32 directions, tonal rows."""
    anchors = prepared.color.anchors
    heights = np.unique(np.r_[0., anchors, (anchors[:-1]+anchors[1:])/2,
                              prepared.color.high*1.25]).astype(np.float32)
    angles = prepared.color.web_parameters(heights.astype(float))['target_angles']
    inputs, frozen = [], []
    for h, row in zip(heights, angles):
        for angle in row:
            ab = (5*np.array((np.cos(angle), np.sin(angle)))).astype(np.float32)
            for component in (0, 1):
                for direction in (-np.inf, None, np.inf):
                    point = ab.copy()
                    if direction is not None:
                        point[component] = np.nextafter(point[component], np.float32(direction))
                    c = np.hypot(*point.astype(float))
                    inputs.append((80., *point, 80.**2-66*c))
                    frozen.append((h, c, 80.**2-66*c, 1.))
    return np.asarray(inputs, np.float32), np.asarray(frozen, np.float32)


def _render(prepared, inputs, frozen, context):
    fixture = NativeFixture(prepared, inputs, context,
        builder=partial(stage_builder, isolated=True, stage='web', local=True))
    connect_frozen(fixture, frozen)
    try:
        table = prepared.color.web_toe_table
        digest = hashlib.sha256(table.pixels.tobytes()).hexdigest()
        receipt = None
        for image in fixture.built.images:
            pixels = np.empty(int(image.size[0])*int(image.size[1])*4, np.float32)
            image.pixels.foreach_get(pixels)
            if hashlib.sha256(pixels.tobytes()).hexdigest() == digest:
                if receipt is not None:
                    raise AssertionError('Ambiguous local toe image')
                if tuple(image.size) != (table.pixels.shape[1], table.pixels.shape[0]):
                    raise AssertionError('Local toe image dimensions differ')
                receipt = dict(cells=table.cells, shape=list(table.pixels.shape),
                               bytes=int(table.pixels.nbytes), pixels_sha256=digest,
                               verified=True)
        if receipt is None:
            raise AssertionError('Local graph did not sample the requested toe payload')
        return fixture.render(), receipt
    finally:
        fixture.close()


def local_result(actual, baseline, expected, source, expected_scale, limit):
    """Keep precision results distinct from the retained local safety checks."""
    finite = bool(all(np.isfinite(actual[key]).all()
                      for key in ('rgb', 'valid', 'margin', 'saturated')))
    metrics = oracle.state_metrics(actual['rgb'], actual['valid'], expected.q,
        expected.energy, source.q, source.energy)
    scales = abs(actual['margin']-expected_scale)/expected_scale
    worst = int(np.argmax(scales))
    scale_error = float(np.max(scales, initial=0))
    changed_saturation = int(np.sum((actual['saturated'] > .5) != (baseline['saturated'] > .5)))
    return dict(state=metrics, scale_relative_error=scale_error,
        state_error_limit=limit, scale_relative_error_limit=limit,
        raw_precision_passed=bool(all(metrics[key] <= limit for key in ('h', 'ab', 'energy'))
                                  and scale_error <= limit),
        safety_passed=bool(finite and not changed_saturation
                           and not metrics['significant_sign_mismatches']),
        finite=finite, changed_saturation_pixels=changed_saturation,
        decode_validity_checked=False,
        worst_scale=dict(index=worst, expected=float(expected_scale[worst]),
            actual=float(actual['margin'][worst]), expected_q=expected.q[worst].tolist(),
            actual_q=actual['rgb'][worst].tolist()))


def run(output_dir, *, cells, samples=256, contexts=('shader', 'compositor'), selected=None):
    sizes = sorted(set(cells))
    if not sizes or any(size not in supported_cells('Web toes') for size in sizes):
        raise ValueError('Unsupported Web-toe diagnostic size')
    if not contexts or len(set(contexts)) != len(contexts):
        raise ValueError('Contexts must be unique and nonempty')
    names = DEFAULT_CASES if selected is None else tuple(selected)
    corpus = {row[0]: row for row in (*full_cases.grades(), *full_cases.ui_boundaries())}
    unknown = set(names)-set(corpus)
    if unknown:
        raise ValueError(f'Unknown local diagnostic cases: {sorted(unknown)}')
    identity = _identity()
    rows = []
    for name in names:
        _, linear, tone, color = corpus[name]
        rotations = (0., -360., 360.) if name == 'web_alternating_extremes' else (None,)
        for rotation in rotations:
            settings = color if rotation is None else replace(color,
                web=replace(color.web, hue_degrees=((rotation,)*6,)*4))
            prepared = with_toe_cells(prepare(linear, tone, color=settings), LEGACY_TOE_CELLS)
            reference = grading.Color(grading.ColorSettings(**asdict(settings)),
                                      grading.Tone(grading.ToneSettings(**asdict(tone))))
            frames = []
            if rotation in (None, 0.):
                tonal = oracle.evaluate(full_cases.rgba(count=samples)[:, :3],
                                         linear, tone, prepared.space)['tone']
                initial = State(tonal.q, tonal.ja*abs(tonal.ja))
                frame = next(frame for frame in local_color_frames(reference, initial) if frame[0] == 'web')
                _, source, expected, frozen, scale = frame
                inputs, source = rounded_state(source)
                frames.append(('float32_handoff', inputs, source, expected, frozen, scale))
            if rotation is not None:
                inputs, frozen = seam_inputs(prepared)
                source = State(inputs[:, :3].astype(float), inputs[:, 3].astype(float))
                expected, scale = _web_expected(reference, source, frozen)
                frames.append(('sector_seams', inputs, source, expected, frozen, scale))
            candidates = {size: with_toe_cells(prepared, size) for size in sizes}
            for probe, inputs, source, expected, frozen, scale in frames:
                for context in contexts:
                    baseline, baseline_image = _render(prepared, inputs, frozen, context)
                    for size in sizes:
                        actual, image = _render(candidates[size], inputs, frozen, context)
                        row = dict(case=name, rotation=rotation, probe=probe, context=context,
                            cells=size, samples=len(inputs), baseline_image=baseline_image, image=image,
                            input_sha256=hashlib.sha256(inputs.tobytes()).hexdigest(),
                            frozen_sha256=hashlib.sha256(frozen.tobytes()).hexdigest(),
                            settings=asdict(settings),
                            **local_result(actual, baseline, expected, source, scale,
                                           web_local_limit(settings, 'web')))
                        rows.append(row)
                        print(f'{name} | {rotation} | {probe} | {context} | {size}: '
                              f'precision={row["raw_precision_passed"]} safety={row["safety_passed"]}', flush=True)
    stable = identity == _identity()
    report = dict(schema=1, identity=identity, policy=texture_admission_policy('Web toes'),
        request=dict(cells=sizes, samples=samples, contexts=list(contexts), cases=list(names),
                     baseline_toe_cells=LEGACY_TOE_CELLS),
        scope='Independent local Web reference at identical float32 handoffs and sector seams; '
              'the local Decode Valid socket carries signed energy, not decode validity. '
              'Decode-validity, containment and final RGB admission belong to the HDR report.',
        complete=True, sources_stable_during_run=stable, rows=rows,
        safety_passed=bool(stable and all(row['safety_passed'] for row in rows)),
        raw_precision_failures=sum(not row['raw_precision_passed'] for row in rows))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Web-toe local diagnostics', '', report['scope'], '',
        f'Source stable: {stable}. Safety: {report["safety_passed"]}. '
        f'Raw precision failures: {report["raw_precision_failures"]}.', '',
        '| Case | Rotation | Probe | Context | Cells | H | Opponent | Energy | Scale relative | Raw precision | Safety |',
        '|---|---:|---|---|---:|---:|---:|---:|---:|---|---|']
    for row in rows:
        lines.append(f'| {row["case"]} | {row["rotation"]} | {row["probe"]} | {row["context"]} | '
            f'{row["cells"]} | {row["state"]["h"]:.9g} | {row["state"]["ab"]:.9g} | '
            f'{row["state"]["energy"]:.9g} | {row["scale_relative_error"]:.9g} | '
            f'{row["raw_precision_passed"]} | {row["safety_passed"]} |')
    (output_dir/'report.md').write_text('\n'.join(lines)+'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--cells', required=True, nargs='+', type=int)
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--contexts', nargs='+', choices=('shader', 'compositor'),
                        default=['shader', 'compositor'])
    parser.add_argument('--cases', nargs='+')
    args = parser.parse_args(argv)
    if args.samples < 256:
        parser.error('--samples must be at least 256')
    report = run(args.output_dir, cells=args.cells, samples=args.samples,
                 contexts=args.contexts, selected=args.cases)
    if not report['safety_passed']:
        raise SystemExit('Local toe safety failed; inspect report.json')


if __name__ == '__main__':
    main()
