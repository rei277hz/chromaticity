"""Measure current and independently reduced texture generation costs.

Only Color `_generate_field` or Tone `_build_table` is timed. Parameter
preparation, dense scalar audits, hashing, upload and native grading are
excluded. Run without concurrent accuracy or performance jobs. Boundary rows
report resident bytes only: their offline geometry generation is not a UI
preparation cost. Runtime sizes and admission policies are unchanged.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np

from color_tools.perceptual_grade_nodes import prepare_tone
from color_tools.perceptual_grade_nodes.color_prepare import _generate_field, _prepare_color_parameters
from color_tools.perceptual_grade_nodes.layouts import LAYOUT_SCHEMA
from color_tools.perceptual_grade_nodes.tables import _build_table, TEXTURE_WIDTH
from . import current_texture_candidates, full_cases
from .current_texture_candidates import baseline_layout, collect_evaluators, selection
from .evaluate import evidence_hashes


CASE_NAMES = ('reset', 'all_active', 'web_alternating_extremes', 'all_families_max_active_tail')


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _tool_hashes():
    return {Path(module.__file__).name: _sha256(Path(module.__file__).read_bytes())
            for module in (sys.modules[__name__], current_texture_candidates)}


def _summary(values):
    return dict(count=len(values), minimum=min(values), median=statistics.median(values), maximum=max(values))


def _boundary_row(spec, *, current):
    width, height = spec['hue_cells']+1, spec['low_cells']+spec['high_cells']+1
    return dict(name='Output boundary', current=current, low_cells=spec['low_cells'],
                high_cells=spec['high_cells'], hue_cells=spec['hue_cells'],
                shape=[height, width, 4], bytes=height*width*4*np.dtype(np.float32).itemsize,
                generation_seconds=None, timing_scope='not_timed_shared_resource')


def run(output_dir, *, repeats=5, candidate_ids=None):
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ValueError('Repetitions must be a positive integer')
    specs = selection(candidate_ids)
    if not specs:
        raise ValueError('Select at least one current-layout reduction')
    layout = baseline_layout()
    identities, tool_hashes = evidence_hashes(), _tool_hashes()
    started_utc = datetime.now(timezone.utc).isoformat()
    grids = {role: [count] for role, count in layout.items() if role != 'Output boundary'}
    for spec in specs:
        if spec['role'] != 'Output boundary':
            grids[spec['role']].append(spec['cells'])
    grids = {role: tuple(dict.fromkeys(counts)) for role, counts in grids.items()}
    boundary_rows = [_boundary_row(layout['Output boundary'], current=True)]
    boundary_rows += [_boundary_row(spec, current=False) for spec in specs
                      if spec['role'] == 'Output boundary']
    boundary_current_bytes = boundary_rows[0]['bytes']
    for row in boundary_rows:
        row['saved_bytes'] = boundary_current_bytes-row['bytes']
    corpus = {row[0]: row for row in (*full_cases.grades(), *full_cases.ui_boundaries())}
    if set(CASE_NAMES)-set(corpus):
        raise AssertionError('A generation cost case is missing')
    rows, settings = [], {}
    for case in CASE_NAMES:
        _, linear, tone_settings, color_settings = corpus[case]
        settings[case] = dict(linear=asdict(linear), tone=asdict(tone_settings), color=asdict(color_settings))
        tone = prepare_tone(tone_settings, full_fields=True)
        color = _prepare_color_parameters(color_settings, tone, full_fields=True)
        evaluators = collect_evaluators(color)
        if set(evaluators) != set(grids)-{'Tone'}:
            raise AssertionError('Current Color evaluator collection differs from runtime inventory')
        for role, counts in grids.items():
            for ordinal in range(repeats):
                order = counts if ordinal % 2 == 0 else tuple(reversed(counts))
                for position, count in enumerate(order):
                    if role == 'Tone':
                        width = TEXTURE_WIDTH if count == layout[role] else min(TEXTURE_WIDTH, count+1)
                        began = time.perf_counter()
                        table = _build_table(tone, count, width)
                        duration = time.perf_counter()-began
                    else:
                        args, kwargs = evaluators[role]
                        began = time.perf_counter()
                        table = _generate_field(*args, **kwargs, cells=count)
                        duration = time.perf_counter()-began
                    row = dict(case=case, name=role, cells=count, current=count == layout[role],
                               ordinal=ordinal, order_index=position, shape=list(table.pixels.shape),
                               bytes=int(table.pixels.nbytes), pixels_sha256=_sha256(table.pixels.tobytes()),
                               generation_seconds=duration)
                    rows.append(row)
                    print(f'{case} {role} {count} {ordinal+1}/{repeats}: '
                          f'generate={1000*duration:.3f}ms', flush=True)
                    del table
    groups = []
    for case in CASE_NAMES:
        for role, counts in grids.items():
            baseline = None
            for count in counts:
                samples = [row for row in rows if row['case'] == case and row['name'] == role and row['cells'] == count]
                payloads = {(tuple(row['shape']), row['bytes'], row['pixels_sha256']) for row in samples}
                if len(samples) != repeats or len(payloads) != 1:
                    raise AssertionError('Repetitions have inconsistent coverage or payloads')
                first = samples[0]
                group = dict(case=case, name=role, cells=count, current=count == layout[role],
                             shape=first['shape'], bytes=first['bytes'], pixels_sha256=first['pixels_sha256'],
                             generation_seconds=_summary([row['generation_seconds'] for row in samples]))
                if group['current']:
                    baseline = group
                if baseline is None:
                    raise AssertionError('Current baseline must be measured before reductions')
                group['saved_bytes'] = baseline['bytes']-group['bytes']
                group['median_relative_to_current'] = (group['generation_seconds']['median']/
                                                       baseline['generation_seconds']['median'])
                groups.append(group)
    candidates = []
    for role, counts in grids.items():
        for count in counts:
            selected = [group for group in groups if group['name'] == role and group['cells'] == count]
            payload_sizes = {(tuple(group['shape']), group['bytes']) for group in selected}
            if len(payload_sizes) != 1:
                raise AssertionError('Packed storage is not invariant across generation cases')
            candidates.append(dict(name=role, cells=count, current=count == layout[role],
                                   shape=selected[0]['shape'], bytes=selected[0]['bytes'],
                                   saved_bytes=selected[0]['saved_bytes'],
                                   worst_case_median_seconds=max(group['generation_seconds']['median'] for group in selected),
                                   maximum_sample_seconds=max(group['generation_seconds']['maximum'] for group in selected)))
    current_bytes = sum(row['bytes'] for row in candidates if row['current'])+boundary_current_bytes
    stable = identities == evidence_hashes() and tool_hashes == _tool_hashes() and layout == baseline_layout()
    report = dict(schema=1, **identities, tool_sha256=tool_hashes, layout_schema=LAYOUT_SCHEMA,
                  runtime_layout=layout, runtime_layout_unchanged=layout == baseline_layout(),
                  sources_stable_during_run=stable, started_utc=started_utc,
                  finished_utc=datetime.now(timezone.utc).isoformat(), platform=platform.platform(),
                  execution=dict(python=platform.python_version(), numpy=np.__version__, cpu_count=os.cpu_count(),
                                 cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                                 argv=sys.argv, thread_environment={name: os.environ.get(name) for name in
                                     ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}),
                  contract=__doc__, repeats=repeats, cases=list(CASE_NAMES), grids=grids,
                  candidate_specs=specs, settings=settings,
                  ordering='Current then smaller counts on even repetitions; reverse on odd repetitions; no warm-up.',
                  current_total_bytes=current_bytes, current_without_boundary_bytes=current_bytes-boundary_current_bytes,
                  accuracy_evaluated=False, boundaries=boundary_rows, groups=groups, candidates=candidates,
                  runs=rows, complete=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Current texture generation and lower-grid costs', '', __doc__.strip(), '',
             f'Coverage: {len(CASE_NAMES)} cases × {repeats} repetitions; {len(rows)} component measurements.',
             f'Current payload: {current_bytes:,} bytes, or {current_bytes-boundary_current_bytes:,} without boundary.', '',
             '| Case | Texture | Cells | Current | Width × height | RGBA32F bytes | Generation min / median / max (ms) |',
             '|---|---|---:|---|---|---:|---:|']
    for group in groups:
        costs = group['generation_seconds']
        times = ' / '.join(f'{1000*costs[key]:.3f}' for key in ('minimum', 'median', 'maximum'))
        lines.append(f"| {group['case']} | {group['name']} | {group['cells']:,} | {group['current']} | "
                     f"{group['shape'][1]:,} × {group['shape'][0]:,} | {group['bytes']:,} | {times} |")
    lines += ['', '| Texture | Cells | Current | RGBA32F bytes | Saved bytes | Worst case generation median (ms) | Maximum sample (ms) |',
              '|---|---:|---|---:|---:|---:|---:|']
    for row in candidates:
        lines.append(f"| {row['name']} | {row['cells']:,} | {row['current']} | {row['bytes']:,} | "
                     f"{row['saved_bytes']:,} | {1000*row['worst_case_median_seconds']:.3f} | "
                     f"{1000*row['maximum_sample_seconds']:.3f} |")
    lines += ['', '| Shared boundary | Current | RGBA32F bytes | Saved bytes | UI generation |',
              '|---|---|---:|---:|---|']
    for row in boundary_rows:
        lines.append(f"| {row['shape'][1]:,} × {row['shape'][0]:,} | {row['current']} | "
                     f"{row['bytes']:,} | {row['saved_bytes']:,} | Not timed; reused resource |")
    lines += ['', 'Boundary byte counts follow exact RGBA32F dimensions; no offline geometry-generation duration is presented as UI preparation.',
              f'Sources stable during measurements: {stable}. Runtime dimensions are unchanged.',
              'JSON retains every sample, exact settings, payload hashes, current baselines, environment and source/resource identities.',
              'Generation measurements do not establish scalar, local, native or HDR accuracy admission.', '']
    (output_dir/'report.md').write_text('\n'.join(lines))
    if not stable:
        raise RuntimeError('Sources or runtime layout changed during generation measurements')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--candidate-ids', nargs='+')
    args = parser.parse_args(argv)
    try:
        run(args.output_dir, repeats=args.repeats, candidate_ids=args.candidate_ids)
    except ValueError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
