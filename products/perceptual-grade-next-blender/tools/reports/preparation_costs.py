"""Measure fixed-layout portable field generation, separately from dense audits.

This development report initializes all resident fields, including neutral ones.
Pixel bytes describe RGBA32F payload, not Python allocation, packed file size,
Blender allocation or VRAM. Run without concurrent accuracy/native jobs.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time

from color_tools.kernel import prepare, prepare_linear, prepare_tone
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.color_prepare import _prepare_color_parameters, _prepare_tables, _generate_field
from . import full_cases
from .evaluate import evidence_hashes


def summary(values):
    return dict(count=len(values), minimum=min(values), median=statistics.median(values), maximum=max(values))


def run(output_dir, *, repeats=5):
    identities = evidence_hashes()
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    corpus = {row[0]: row for row in list(full_cases.grades())+list(full_cases.ui_boundaries())}
    names = ('reset', 'all_active', 'web_alternating_extremes', 'all_families_max_active_tail')
    # Use the corpus's neutral identity regardless of its display name.
    if 'reset' not in corpus:
        names = (next(iter(corpus)), *names[1:])
    base = prepare()
    start = time.perf_counter()
    boundary = prepare_boundary(base.fl, base.aw, base.gamma)
    first_load = time.perf_counter()-start
    rows = []
    for name in names:
        _, linear, tone, color = corpus[name]
        for ordinal in range(repeats):
            start = time.perf_counter()
            prepare_linear(linear)
            linear_seconds = time.perf_counter()-start
            start = time.perf_counter()
            prepared_tone = prepare_tone(tone, full_fields=True)
            tone_seconds = time.perf_counter()-start
            start = time.perf_counter()
            params = _prepare_color_parameters(color, prepared_tone, full_fields=True)
            params_seconds = time.perf_counter()-start
            fields = []
            def measured_builder(*args, **kwargs):
                began = time.perf_counter()
                table = _generate_field(*args, **kwargs)
                fields.append(dict(name=table.name, cells=table.cells,
                    shape=list(table.pixels.shape), bytes=table.pixels.nbytes,
                    generation_seconds=time.perf_counter()-began))
                return table
            _prepare_tables(params, builder=measured_builder)
            start = time.perf_counter()
            complete = prepare(linear, tone, color=color, boundary=boundary, full_fields=True)
            complete_seconds = time.perf_counter()-start
            textures = [dict(name='Tone', cells=complete.table.cells,
                            shape=list(complete.table.pixels.shape), bytes=complete.table.pixels.nbytes),
                        *[{k:v for k,v in row.items() if k != 'generation_seconds'} for row in fields],
                        dict(name='Output boundary', cells=None, shape=list(boundary.pixels.shape), bytes=boundary.pixels.nbytes)]
            rows.append(dict(case=name, ordinal=ordinal, linear_seconds=linear_seconds,
                tone_seconds=tone_seconds, color_parameters_seconds=params_seconds,
                fields=fields, complete_preparation_seconds=complete_seconds,
                textures=textures, resident_pixel_bytes=sum(row['bytes'] for row in textures),
                settings=dict(linear=asdict(linear), tone=asdict(tone), color=asdict(color))))
            print(f'{name} {ordinal+1}/{repeats}: prepare={complete_seconds:.6f}s', flush=True)
    groups = []
    for name in names:
        selected = [row for row in rows if row['case'] == name]
        groups.append(dict(case=name,
            phases={key:summary([r[key] for r in selected]) for key in
                    ('linear_seconds', 'tone_seconds', 'color_parameters_seconds', 'complete_preparation_seconds')},
            fields={f['name']: summary([next(t['generation_seconds'] for t in r['fields'] if t['name']==f['name'])
                                       for r in selected]) for f in selected[0]['fields']},
            textures=selected[0]['textures'], resident_pixel_bytes=selected[0]['resident_pixel_bytes']))
    stable = identities == evidence_hashes() and source_hash == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(schema=1, **identities, tool_sha256=source_hash, platform=platform.platform(),
        execution=dict(python=platform.python_version(), cpu_count=os.cpu_count(),
            cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
            thread_environment={name: os.environ.get(name) for name in
                                ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}),
        sources_stable_during_run=stable, repeats=repeats, first_boundary_loading_seconds=first_load,
        contract='All fixed resident fields. No dense audit or resolution search. Component generation '
                 'and uninstrumented complete preparation are separate measurements and must not be added. '
                 'Boundary data are loaded once and reused. No native construction, image upload or render is timed.',
        groups=groups, runs=rows)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    lines = ['# Fixed-field preparation costs', '', report['contract'], '',
             '| Field | Cells | Width × height | RGBA32F bytes |', '|---|---:|---|---:|']
    for t in groups[0]['textures']:
        lines.append(f"| {t['name']} | {t['cells'] if t['cells'] is not None else 'fixed'} | {t['shape'][1]} × {t['shape'][0]} | {t['bytes']:,} |")
    lines += ['', f"Resident payload: {groups[0]['resident_pixel_bytes']:,} bytes. First boundary load: {first_load:.6f}s.", '',
              '| Case | Complete preparation median (s) | Tone (s) | Color coefficients (s) | Web parameters (s) | Web toes (s) | Compact Adaptance (s) |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        values = [g['phases']['complete_preparation_seconds']['median'], g['phases']['tone_seconds']['median'],
                  *[g['fields'][name]['median'] for name in ('Color coefficients','Web parameters','Web toes','Adaptance parameters')]]
        lines.append('| '+g['case']+' | '+' | '.join(f'{v:.6f}' for v in values)+' |')
    lines += ['', 'JSON retains all repetitions, extrema, settings and source identities. These are host preparation costs, not drag latency.', '']
    (output_dir/'report.md').write_text('\n'.join(lines))
    if not stable:
        raise RuntimeError('Sources changed during preparation measurements')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    run(args.output_dir, repeats=args.repeats)


if __name__ == '__main__':
    main()
