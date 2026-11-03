"""Measure offline Color/compact-Adaptance candidate field generation costs.

The runtime layout is unchanged. Only `_generate_field` is timed: parameter
preparation, payload hashing, scalar audits, native upload and grading are
excluded. Run without concurrent accuracy/native/timing jobs. These timings
describe candidate generation, not accuracy admission or whole preparation.
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
from color_tools.perceptual_grade_nodes.color_prepare import (
    _generate_field, _prepare_color_parameters, _prepare_tables,
)
from color_tools.perceptual_grade_nodes.layouts import FIELD_CELLS, LAYOUT_SCHEMA, supported_cells
from . import full_cases
from .evaluate import evidence_hashes


DEFAULT_GRIDS = {
    'Color coefficients': (131072, 65536, 32768, 16384, 8192, 4096),
    'Adaptance parameters': (16384, 8192, 4096, 2048),
}
CASE_NAMES = ('reset', 'all_active', 'web_alternating_extremes', 'all_families_max_active_tail')


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _summary(values):
    return dict(count=len(values), minimum=min(values), median=statistics.median(values), maximum=max(values))


def run(output_dir, *, repeats=5, grids=None, generation_limit_ms=10.):
    if repeats < 1 or not np.isfinite(generation_limit_ms) or generation_limit_ms <= 0:
        raise ValueError('Repetitions and the generation target must be positive')
    grids = DEFAULT_GRIDS if grids is None else grids
    if not grids or set(grids)-set(DEFAULT_GRIDS):
        raise ValueError('Select Color coefficients or Adaptance parameters')
    grids = {role: tuple(dict.fromkeys(map(int, counts))) for role, counts in grids.items()}
    for role, counts in grids.items():
        if not counts or any(count not in supported_cells(role) for count in counts):
            raise ValueError(f'Unsupported candidate grid for {role}')
    identities = evidence_hashes()
    own_hash = _sha256(Path(__file__).read_bytes())
    runtime_layout = dict(FIELD_CELLS)
    started_utc = datetime.now(timezone.utc).isoformat()
    corpus = {row[0]: row for row in (*full_cases.grades(), *full_cases.ui_boundaries())}
    names = CASE_NAMES if 'reset' in corpus else (next(iter(corpus)), *CASE_NAMES[1:])
    rows, settings = [], {}
    for case in names:
        _, linear, tone_settings, color_settings = corpus[case]
        settings[case] = dict(linear=asdict(linear), tone=asdict(tone_settings), color=asdict(color_settings))
        tone = prepare_tone(tone_settings, full_fields=True)
        prepared = _prepare_color_parameters(color_settings, tone, full_fields=True)
        specs = {}

        def collect(name, *args, **kwargs):
            if name in grids:
                specs[name] = ((name, *args), kwargs)
            return None

        _prepare_tables(prepared, builder=collect)
        if set(specs) != set(grids):
            raise AssertionError('A selected field evaluator was not collected')
        for role, counts in grids.items():
            args, kwargs = specs[role]
            for ordinal in range(repeats):
                order = counts if ordinal % 2 == 0 else tuple(reversed(counts))
                for position, count in enumerate(order):
                    began = time.perf_counter()
                    table = _generate_field(*args, **kwargs, cells=count)
                    generation_seconds = time.perf_counter()-began
                    row = dict(case=case, name=role, cells=count, ordinal=ordinal, order_index=position,
                               shape=list(table.pixels.shape), bytes=table.pixels.nbytes,
                               pixels_sha256=_sha256(table.pixels.tobytes()),
                               generation_seconds=generation_seconds)
                    rows.append(row)
                    print(f'{case} {role} {count} {ordinal+1}/{repeats}: '
                          f'generate={1000*generation_seconds:.3f}ms', flush=True)
                    del table
    groups = []
    for case in names:
        for role, counts in grids.items():
            for count in counts:
                samples = [row for row in rows if row['case'] == case and row['name'] == role
                           and row['cells'] == count]
                payloads = {(tuple(row['shape']), row['bytes'], row['pixels_sha256']) for row in samples}
                if len(samples) != repeats or len(payloads) != 1:
                    raise AssertionError('Candidate repetitions have inconsistent coverage or payloads')
                first = samples[0]
                costs = _summary([row['generation_seconds'] for row in samples])
                groups.append(dict(case=case, name=role, cells=count,
                                   shape=first['shape'], bytes=first['bytes'], pixels_sha256=first['pixels_sha256'],
                                   generation_seconds=costs,
                                   median_under_target=1000*costs['median'] < generation_limit_ms,
                                   all_samples_under_target=1000*costs['maximum'] < generation_limit_ms))
    candidates = []
    for role, counts in grids.items():
        for count in counts:
            selected = [group for group in groups if group['name'] == role and group['cells'] == count]
            candidates.append(dict(name=role, cells=count,
                                   worst_case_median_seconds=max(group['generation_seconds']['median'] for group in selected),
                                   all_case_medians_under_target=all(group['median_under_target'] for group in selected),
                                   all_samples_under_target=all(group['all_samples_under_target'] for group in selected)))
    stable = (identities == evidence_hashes() and own_hash == _sha256(Path(__file__).read_bytes())
              and runtime_layout == dict(FIELD_CELLS))
    report = dict(schema=1, **identities, tool_sha256=own_hash, layout_schema=LAYOUT_SCHEMA,
                  runtime_layout=runtime_layout, runtime_layout_unchanged=runtime_layout == dict(FIELD_CELLS),
                  sources_stable_during_run=stable, started_utc=started_utc,
                  finished_utc=datetime.now(timezone.utc).isoformat(),
                  platform=platform.platform(),
                  execution=dict(python=platform.python_version(), numpy=np.__version__, cpu_count=os.cpu_count(),
                                 cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                                 argv=sys.argv,
                                 thread_environment={name: os.environ.get(name) for name in
                                                     ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}),
                  contract=__doc__, repeats=repeats, cases=list(names), grids=grids,
                  ordering='Candidate counts run in the requested order on even repetitions and reverse order on odd repetitions; no warm-up.',
                  generation_limit_ms=generation_limit_ms, accuracy_evaluated=False,
                  settings=settings, groups=groups, candidates=candidates, runs=rows, complete=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Offline candidate field generation costs', '', __doc__.strip(), '',
             f'Coverage: {len(names)} cases × {repeats} repetitions; {len(rows)} component measurements.',
             f'Generation target: strictly below {generation_limit_ms:g} ms. Accuracy is not evaluated.', '',
             '| Case | Field | Cells | Width × height | RGBA32F bytes | Generation min / median / max (ms) | Median below target |',
             '|---|---|---:|---|---:|---:|---|']
    for group in groups:
        costs = group['generation_seconds']
        times = ' / '.join(f'{1000*costs[key]:.3f}' for key in ('minimum', 'median', 'maximum'))
        lines.append(f"| {group['case']} | {group['name']} | {group['cells']:,} | "
                     f"{group['shape'][1]:,} × {group['shape'][0]:,} | {group['bytes']:,} | {times} | "
                     f"{group['median_under_target']} |")
    lines += ['', '| Field | Cells | Worst case median (ms) | All case medians below target | Every sample below target |',
              '|---|---:|---:|---|---|']
    for candidate in candidates:
        lines.append(f"| {candidate['name']} | {candidate['cells']:,} | "
                     f"{1000*candidate['worst_case_median_seconds']:.3f} | "
                     f"{candidate['all_case_medians_under_target']} | {candidate['all_samples_under_target']} |")
    lines += ['', f'Sources stable during measurements: {stable}. Runtime field layouts are unchanged.',
              'JSON retains every sample, exact settings, payload hashes, runtime layout, environment and source/resource identities.',
              'A timing target pass does not admit a candidate under scalar, local, native or HDR accuracy policies.', '']
    (output_dir/'report.md').write_text('\n'.join(lines))
    if not stable:
        raise RuntimeError('Sources or runtime layouts changed during candidate generation measurements')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--fields', nargs='+', choices=tuple(DEFAULT_GRIDS), default=list(DEFAULT_GRIDS))
    parser.add_argument('--color-cells', nargs='+', type=int, default=list(DEFAULT_GRIDS['Color coefficients']))
    parser.add_argument('--adaptance-cells', nargs='+', type=int, default=list(DEFAULT_GRIDS['Adaptance parameters']))
    parser.add_argument('--generation-limit-ms', type=float, default=10.)
    args = parser.parse_args(argv)
    grids = {name: args.color_cells if name == 'Color coefficients' else args.adaptance_cells for name in args.fields}
    try:
        run(args.output_dir, repeats=args.repeats, grids=grids, generation_limit_ms=args.generation_limit_ms)
    except ValueError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
