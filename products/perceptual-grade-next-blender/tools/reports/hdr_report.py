"""Actual native texture reductions measured in ACES HDR/PQ RGB code units.

The report is diagnostic: local and scalar failures remain visible and do not
prevent a finite candidate from being measured through the complete graph.
"""
import argparse
import copy
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

from color_tools.kernel import prepare, prepare_linear
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.color_prepare import _generate_field, _prepare_tables
from color_tools.kernel.layouts import supported_cells
from color_tools.kernel.tables import build_diagnostic_table, TABLE_ERROR_LIMIT
from . import cases, full_cases, oracle
from .evaluate import assess, evidence_hashes
from .field_effects import ATTRIBUTES, _candidate as color_candidate
from .gpu_report import _json_values
from .hdr_metrics import HDRDisplay, compare
from .gate_policy import texture_admission_policy


COLOR_CELLS = {
    'Color coefficients': (65536, 32768, 16384, 8192, 4096, 2048),
    'Web parameters': (16384, 8192, 4096, 2048),
    'Web toes': (262144, 131072, 65536, 32768, 16384, 8192, 4096,
                 2048, 1792, 1536, 1280, 1024, 768, 512, 256),
    'Adaptance parameters': (8192, 4096, 2048),
}
TONE_CELLS = (256, 128, 64, 32)
BOUNDARY_CELLS = ((64, 96, 256), (32, 48, 128), (16, 24, 64))
ROLES = ('Tone', *COLOR_CELLS, 'Output boundary', 'Combined Web', 'Combined Color')
TOE_ADMISSION_CELLS = tuple(range(256, 2049, 256))
ORIGINAL_TOE_CELLS = 524288
ORIGINAL_COLOR_CELLS = 131072
ORIGINAL_COMPACT_ADAPTANCE_CELLS = 16384
HDR_FIELD_ROLES = ('Color coefficients', 'Adaptance parameters')


def case_shards(case_names, count):
    """Partition case names into deterministic, balanced shards.

    Case order comes from the canonical corpus.  Round-robin assignment keeps
    the work reasonably balanced while preserving the same membership every
    time a report is split into ``count`` workers.
    """
    names = list(case_names)
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError('case shard count must be an integer')
    if count < 1:
        raise ValueError('case shard count must be positive')
    if len(set(names)) != len(names):
        raise ValueError('case names must be unique before sharding')
    if not names:
        raise ValueError('cannot shard an empty case corpus')
    if count > len(names):
        raise ValueError('case shard count cannot exceed the case corpus size')
    return [names[index::count] for index in range(count)]


def _validate_axes(spaces, contexts):
    """Reject ambiguous report axes before any native work starts."""
    if not spaces:
        raise ValueError('at least one space is required')
    if not contexts:
        raise ValueError('at least one context is required')
    if len(set(spaces)) != len(spaces):
        raise ValueError('spaces must be unique')
    if len(set(contexts)) != len(contexts):
        raise ValueError('contexts must be unique')


def _backend_threads(backend, threads):
    """Validate the native backend before importing Blender or opening a display."""
    if backend not in ('cpu', 'software-gpu'):
        raise ValueError('Unsupported HDR backend; choose cpu or software-gpu')
    if threads is not None and (not isinstance(threads, int) or isinstance(threads, bool) or threads < 1):
        raise ValueError('HDR native thread count must be a positive integer')
    if backend == 'software-gpu' and threads is None:
        from .benchmark import available_threads
        return available_threads()
    return threads


def _graph_builder(graph_builder):
    if graph_builder == 'specialized':
        return None
    if graph_builder == 'persistent':
        from color_tools.template_build.persistent import build_persistent
        return build_persistent
    raise ValueError('Unsupported graph builder; choose specialized or persistent')


def _request(*, samples, spaces, contexts, cases, case_universe, candidates,
             baseline_toe_cells, baseline_parameter_cells, baseline_color_cells,
             baseline_compact_adaptance_cells, backend, threads, case_shard, graph_builder):
    request = dict(samples=samples, spaces=list(spaces), contexts=list(contexts),
                   cases=list(cases), case_universe=list(case_universe),
                   baseline_toe_cells=baseline_toe_cells, candidates=candidates,
                   graph_builder=graph_builder)
    for key, value in (('baseline_parameter_cells', baseline_parameter_cells),
                       ('baseline_color_cells', baseline_color_cells),
                       ('baseline_compact_adaptance_cells', baseline_compact_adaptance_cells)):
        if value is not None:
            request[key] = value
    if backend != 'cpu' or threads is not None:
        request.update(backend=backend, threads=threads)
    if case_shard is not None:
        request['case_shard'] = case_shard
    return request


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def identities():
    """Include the diagnostic code, not just the runtime/reference closure."""
    from . import hdr_metrics, field_effects, benchmark, gpu_report
    from tools import build_boundary
    result = evidence_hashes()
    result['hdr_tool_sha256'] = {Path(path).name: _hash(Path(path).read_bytes())
                                for path in (__file__, hdr_metrics.__file__,
                                             build_boundary.__file__, field_effects.__file__,
                                             benchmark.__file__, gpu_report.__file__)}
    return result


def selection(roles=None, candidate_ids=None):
    """Stable, complete finite sweep; IDs are useful for smoke/resume runs."""
    specs = [dict(id=f'Tone/{n}', role='Tone', cells=n) for n in TONE_CELLS]
    specs += [dict(id=f'{role}/{n}', role=role, cells=n)
              for role, sizes in COLOR_CELLS.items() for n in sizes]
    specs += [dict(id=f'Output boundary/{hue+1}x{low+high+1}', role='Output boundary',
                   low_cells=low, high_cells=high, hue_cells=hue)
              for low, high, hue in BOUNDARY_CELLS]
    specs += [dict(id='Combined Web/4096+32768', role='Combined Web',
                   parameter_cells=4096, toe_cells=32768)]
    specs += [dict(id='Combined Color/16384+8192', role='Combined Color',
                   color_cells=16384, compact_adaptance_cells=8192)]
    if roles:
        unknown = set(roles)-set(ROLES)
        if unknown:
            raise ValueError(f'Unknown roles: {sorted(unknown)}')
        specs = [s for s in specs if s['role'] in roles]
    if candidate_ids:
        unknown = set(candidate_ids)-{s['id'] for s in specs}
        if unknown:
            raise ValueError(f'Unknown candidates in selected roles: {sorted(unknown)}')
        specs = [s for s in specs if s['id'] in candidate_ids]
    return specs


def _payloads(prepared):
    return {'Tone': None if prepared.tone.table is None else prepared.tone.table.pixels,
            'Output boundary': None if prepared.boundary is None else prepared.boundary.pixels,
            **{role: None if getattr(prepared.color, attr) is None else
               getattr(prepared.color, attr).pixels for role, attr in ATTRIBUTES.items()}}


def _inventory(fixture, prepared, roles=None):
    """Prove each surviving native helper image's dimensions and float payload."""
    result = {}
    expected = {role: data for role, data in _payloads(prepared).items()
                if data is not None and (roles is None or role in roles)}
    by_digest = {}
    for image in fixture.built.images:
        pixels = np.empty(int(image.size[0]) * int(image.size[1]) * 4, np.float32)
        image.pixels.foreach_get(pixels)
        by_digest.setdefault(_hash(pixels.tobytes()), []).append((image, pixels))
    for role, data in expected.items():
        digest = _hash(np.asarray(data, dtype=np.float32).tobytes())
        matches = by_digest.get(digest, ())
        if len(matches) > 1:
            raise AssertionError(f'Ambiguous native image payload for {role}')
        if not matches:
            continue
        image, pixels = matches[0]
        if list(image.size) != [data.shape[1], data.shape[0]]:
            raise AssertionError(f'Native image dimensions differ for {role}')
        if not np.array_equal(pixels, np.asarray(data, dtype=np.float32).ravel()):
            raise AssertionError(f'Native image payload differs for {role}')
        result[role] = dict(name=image.name, size=list(image.size), bytes=int(pixels.nbytes),
                            pixels_sha256=digest, verified=True)
    return result


def _render(prepared, values, context, expected, *, required_roles=(), backend='cpu',
            threads=None, render_backend=None, graph_builder='specialized'):
    from .native import NativeFixture
    threads = _backend_threads(backend, threads)
    engine = 'BLENDER_EEVEE' if backend == 'software-gpu' and context == 'shader' else 'CYCLES'
    device = 'GPU' if backend == 'software-gpu' else 'CPU'
    if backend == 'software-gpu' and render_backend is None:
        from .benchmark import software_gpu_info
        render_backend = software_gpu_info()
    start = time.perf_counter()
    fixture = NativeFixture(prepared, values, context, engine=engine, device=device,
                            precision='FULL', threads=threads, builder=_graph_builder(graph_builder))
    try:
        execution = dict(backend=backend, threads=threads, engine=fixture.scene.render.engine,
                         compositor_device=fixture.scene.render.compositor_device,
                         compositor_precision=fixture.scene.render.compositor_precision,
                         native_threads=fixture.scene.render.threads,
                         native_threads_mode=fixture.scene.render.threads_mode,
                         graph_builder=graph_builder,
                         render_backend=render_backend)
        images = _inventory(fixture, prepared, required_roles or None)
        missing = set(required_roles)-set(images)
        if missing:
            return None, dict(status='not_sampled', **execution, image_receipts=images,
                              missing_roles=sorted(missing))
        actual = fixture.render()
        assessment = assess(actual, expected, values)
        native = actual['rgb'] @ np.linalg.inv(expected['to_scene']).T
        magnitude = np.maximum(1., np.max(abs(native), axis=-1))
        violation = np.maximum(np.max(-native, axis=-1), np.max(native-1024., axis=-1))
        containment = float(np.max(np.maximum(0., violation)/magnitude, initial=0))
        finite = all(np.isfinite(actual[key]).all() for key in ('rgb','alpha','valid','margin','saturated'))
        result = dict(status='measured' if finite else 'nonfinite', **execution, image_receipts=images,
                      scene_linear=assessment,
                      final_rgb_passed=bool(assessment['passed'] and finite and containment <= 8e-6),
                      containment_max_normalized=containment, stats=actual['stats'],
                      node_budget_passed=actual['stats']['expanded_nodes'] < 1000,
                      render_seconds=actual['seconds'], readback_seconds=actual['readback_seconds'],
                      total_fixture_seconds=time.perf_counter()-start)
        return actual, result
    finally:
        fixture.close()


def _texture_metadata(role, table):
    return dict(name=role, shape=list(table.pixels.shape), bytes=int(table.pixels.nbytes),
                pixels_sha256=_hash(table.pixels.tobytes()))


def _with_baseline_field(base, role, cells):
    """Replace one baseline field, retaining every other prepared payload."""
    if cells not in supported_cells(role):
        raise ValueError(f'Unsupported baseline {role} cell count')
    if getattr(base.color, ATTRIBUTES[role]).cells == cells:
        return base
    original = {table.name: table for table in base.color.tables}

    def builder(name, *args, **kwargs):
        if name != role:
            return original[name]
        return _generate_field(name, *args, cells=cells, **kwargs)

    color = _prepare_tables(base.color, builder=builder)
    return replace(base, color=color)


def _with_baseline_toe(base, cells):
    """Replace only the baseline toe, without running a dense scalar audit."""
    return _with_baseline_field(base, 'Web toes', cells)


def _with_baseline_parameters(base, cells):
    """Keep a historical parameter baseline after changing the runtime layout."""
    return _with_baseline_field(base, 'Web parameters', cells)


def _make_candidate(base, spec, boundary_cache):
    role = spec['role']
    if role in COLOR_CELLS:
        candidate, metadata = color_candidate(base, role, spec['cells'])
        return candidate, [metadata]
    if role == 'Tone':
        table = build_diagnostic_table(base.tone, spec['cells'])
        metadata = dict(**_texture_metadata(role, table), cells=table.cells,
                        scalar_error=table.max_error, scalar_limit=TABLE_ERROR_LIMIT,
                        field_passed=bool(table.monotone and table.max_error <= TABLE_ERROR_LIMIT),
                        monotone=table.monotone, limited_knots=table.limited_knots,
                        audit_complete=True, probes=table.probe_count)
        return replace(base, tone=replace(base.tone, table=table)), [metadata]
    if role == 'Output boundary':
        from tools.build_boundary import generate_boundary
        key = (base.fl, base.aw, base.gamma, spec['low_cells'], spec['high_cells'], spec['hue_cells'])
        if key not in boundary_cache:
            boundary_cache[key] = generate_boundary(*key[:3], low_cells=key[3], high_cells=key[4],
                                                    hue_cells=key[5], enforce_accuracy=False)
        boundary = boundary_cache[key]
        metadata = dict(**_texture_metadata(role, boundary),
                        corrected_radius_error=boundary.max_error, corrected_radius_limit=2e-5,
                        field_passed=bool(boundary.max_error <= 2e-5), probes=boundary.probe_count,
                        audit_complete=True, seed_split=boundary.seed_split,
                        low_cells=boundary.seed_low_cells, high_cells=boundary.seed_high_cells,
                        hue_cells=boundary.seed_hue_cells, correction_steps=boundary.correction_steps)
        return replace(base, boundary=boundary), [metadata]
    if role == 'Combined Web':
        candidate, parameter = color_candidate(base, 'Web parameters', spec['parameter_cells'])
        candidate, toe = color_candidate(candidate, 'Web toes', spec['toe_cells'])
        return candidate, [parameter, toe]
    if role == 'Combined Color':
        candidate, color = color_candidate(base, 'Color coefficients', spec['color_cells'])
        candidate, compact = color_candidate(candidate, 'Adaptance parameters', spec['compact_adaptance_cells'])
        return candidate, [color, compact]
    raise ValueError(f'Unknown candidate role: {role}')


def _required_roles(spec):
    if spec['role'] == 'Combined Web':
        return ('Web parameters', 'Web toes')
    if spec['role'] == 'Combined Color':
        return HDR_FIELD_ROLES
    return (spec['role'],)


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(_json_values(value), indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def _load_journal(path):
    if not path.exists():
        return []
    records = []
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    for i, line in enumerate(lines):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines)-1 or line.endswith(b'\n'):
                raise ValueError(f'Corrupt checkpoint journal: {path}') from None
            # Only an interrupted final append may be discarded.
            path.write_bytes(b''.join(lines[:i]))
    return records


def _append_journal(path, row):
    with path.open('a') as stream:
        stream.write(json.dumps(_json_values(row), separators=(',', ':'), allow_nan=False)+'\n')
        stream.flush()


def _metric_peak(row, key):
    metrics = row.get('hdr', {})
    if key == 'current':
        return metrics.get('current', {}).get('pixel_peak', {}).get('max')
    if key == 'candidate':
        return metrics.get('candidate', {}).get('error', {}).get('pixel_peak', {}).get('max')
    if key == 'movement':
        return metrics.get('candidate', {}).get('movement', {}).get('pixel_peak', {}).get('max')
    return metrics.get('candidate', {}).get('worsening', {}).get('max')


def _worsening_percentage_peak(row):
    """Return the maximum signed percentage over eligible reference pixels."""
    return row.get('hdr', {}).get('candidate', {}).get('worsening', {}).get('percentage', {}).get('max')


def toe_admission(report):
    """Select the smallest fully measured toe layout under the HDR policy.

    Raw scalar failures stay failures.  This separate receipt admits only a
    toe layout, and cannot waive final-output or semantic flag checks.
    """
    policy = texture_admission_policy('Web toes')
    limit = policy['max_worsening_codes']
    request = report.get('request', {})
    specs = [spec for spec in request.get('candidates', ()) if spec.get('role') == 'Web toes']
    if not specs:
        return None
    reasons = []
    canonical_cases = [row[0] for row in list(full_cases.grades()) + list(full_cases.ui_boundaries())]
    spaces, contexts = request.get('spaces', ()), request.get('contexts', ())
    requested_cases = request.get('cases', ())
    if report.get('complete') is not True or report.get('sources_stable_during_run') is not True:
        reasons.append('Report is incomplete or sources changed during measurement')
    if report.get('identity', {}).get('request') != request:
        reasons.append('Request differs from its source-bound identity')
    if request.get('baseline_toe_cells') != ORIGINAL_TOE_CELLS:
        reasons.append('Admission requires the explicit original 524288-cell toe baseline')
    if (set(requested_cases) != set(canonical_cases) or len(requested_cases) != len(canonical_cases)
            or set(spaces) != set(cases.SPACES) or len(spaces) != len(cases.SPACES)
            or set(contexts) != {'shader', 'compositor'} or len(contexts) != 2
            or request.get('samples') != 1024 or request.get('case_shard') is not None):
        reasons.append('Admission requires the complete 149-case, three-space, two-context corpus at 1024 samples')
    expected_keys = {(case, space, context) for case in canonical_cases
                     for space in cases.SPACES for context in ('shader', 'compositor')}
    baseline_rows = report.get('baselines', ())
    baseline_by_key = {(row.get('case'), row.get('space'), row.get('context')): row for row in baseline_rows}
    if len(baseline_by_key) != len(baseline_rows) or set(baseline_by_key) != expected_keys:
        reasons.append('Baseline coverage is incomplete or duplicated')
    elif any(row.get('status') != 'measured' or row.get('final_rgb_passed') is not True
             for row in baseline_rows):
        reasons.append('Baseline contains a nonfinite or failed final-output comparison')
    candidates = []
    for spec in sorted(specs, key=lambda spec: spec['cells']):
        selected = [row for row in report.get('rows', ()) if row.get('candidate') == spec['id']]
        keys = [(row.get('case'), row.get('space'), row.get('context')) for row in selected]
        rejected = list(reasons)
        coverage_complete = len(keys) == len(set(keys)) and set(keys) == expected_keys
        if not coverage_complete:
            rejected.append('Candidate coverage is incomplete or duplicated')
        measured = [row for row in selected if row.get('status') == 'measured']
        inactive = [row for row in selected if row.get('status') == 'not_sampled']
        failures = [row for row in selected if row.get('status') not in ('measured', 'not_sampled')]
        if failures:
            rejected.append('Candidate contains generation, render or nonfinite failures')
        if any('Web toes' in baseline_by_key.get(key, {}).get('image_receipts', {})
               for key, row in zip(keys, selected) if row.get('status') == 'not_sampled'):
            rejected.append('An active baseline toe was not sampled by the candidate')
        if not measured:
            rejected.append('No native toe sampling was measured')
        if any(row.get('final_rgb_passed') is not True for row in measured):
            rejected.append('Final scene-linear RGB comparison failed')
        if any(not np.isfinite(row.get('containment_max_normalized', np.inf))
               or row.get('containment_max_normalized', np.inf) > 8e-6 for row in measured):
            rejected.append('Containment check failed or is missing')
        if any(row.get('changed_validity_pixels') != 0 for row in measured):
            rejected.append('Validity flags changed or were not compared')
        if any(row.get('changed_saturation_pixels') != 0 for row in measured):
            rejected.append('Saturation flags changed or were not compared')
        if any(not row.get('image_receipts', {}).get('Web toes', {}).get('verified') for row in measured):
            rejected.append('Native toe image readback is missing')
        segment_cells = min(spec['cells'], 8192)
        segments = spec['cells'] // segment_cells
        expected_shape = [segments, segment_cells + 1, 4]
        expected_bytes = segments * (segment_cells + 1) * 16
        for row in measured:
            metadata = next((item for item in row.get('texture_metadata', ())
                             if item.get('name') == 'Web toes'), None)
            receipt = row.get('image_receipts', {}).get('Web toes', {})
            if (metadata is None or metadata.get('cells') != spec['cells']
                    or metadata.get('shape') != expected_shape
                    or metadata.get('bytes') != expected_bytes
                    or receipt.get('size') != [segment_cells + 1, segments]
                    or receipt.get('bytes') != expected_bytes):
                rejected.append('Candidate toe dimensions or byte count differ from the requested layout')
                break
        if any(not any(item.get('name') == 'Web toes' and item.get('audit_complete') is True
                       for item in row.get('texture_metadata', ())) for row in measured):
            rejected.append('Complete scalar diagnostics are missing')
        peaks = [_metric_peak(row, 'worsening') for row in measured]
        movements = [_metric_peak(row, 'movement') for row in measured]
        percentages = [_worsening_percentage_peak(row) for row in measured]
        percentages = [value for value in percentages if value is not None and np.isfinite(value)]
        finite_metrics = bool(peaks) and all(value is not None and np.isfinite(value)
                                            for value in (*peaks, *movements))
        maximum = max(peaks) if finite_metrics else None
        movement = max(movements) if finite_metrics else None
        if not finite_metrics:
            rejected.append('HDR worsening or movement metric is nonfinite or missing')
        elif maximum > limit:
            rejected.append('Maximum signed HDR worsening exceeds 0.05 codes')
        worst = max(measured, key=lambda row: _metric_peak(row, 'worsening')) if finite_metrics else None
        witness = None if worst is None else dict(case=worst['case'], space=worst['space'],
            context=worst['context'], pixel=worst.get('hdr', {}).get('witnesses', {}).get('worsening'))
        candidates.append(dict(id=spec['id'], cells=spec['cells'], measured_rows=len(measured),
            inactive_rows=len(inactive), coverage_complete=coverage_complete,
            max_worsening_codes=maximum, max_movement_codes=movement,
            max_worsening_percentage=max(percentages) if percentages else None,
            scalar_failure_rows=sum(any(not item.get('field_passed', True)
                for item in row.get('texture_metadata', ())) for row in measured),
            passed=not rejected, rejection_reasons=rejected, worst_worsening=witness))
    grid_complete = set(TOE_ADMISSION_CELLS) <= {
        row['cells'] for row in candidates if row['coverage_complete']}
    passing = [row['cells'] for row in candidates if row['passed'] and row['cells'] in TOE_ADMISSION_CELLS]
    return dict(policy=policy, baseline_toe_cells=request.get('baseline_toe_cells'),
                selection_grid_cells=list(TOE_ADMISSION_CELLS), selection_grid_complete=grid_complete,
                selected_cells=min(passing) if passing and grid_complete else None,
                candidates=candidates)


def _field_shape(role, cells):
    """Expected RGBA32F packing for the two HDR-admitted field roles."""
    segment = min(cells, 8192)
    semantic_rows = 2 if role == 'Color coefficients' else 1
    height = semantic_rows*(cells//segment)
    return [1 << (height-1).bit_length(), segment+1, 4]


def _verified_field_image(receipt, role, cells, metadata=None):
    shape = _field_shape(role, cells)
    size, count = [shape[1], shape[0]], shape[0]*shape[1]*16
    digest = receipt.get('pixels_sha256')
    valid_digest = (isinstance(digest, str) and len(digest) == 64
                    and all(char in '0123456789abcdef' for char in digest))
    if (receipt.get('verified') is not True or receipt.get('size') != size
            or receipt.get('bytes') != count or not valid_digest):
        return False
    return metadata is None or (metadata.get('name') == role and metadata.get('cells') == cells
        and metadata.get('shape') == shape and metadata.get('bytes') == count
        and metadata.get('pixels_sha256') == digest)


def _complete_field_diagnostics(field):
    """Require recorded finite scalar evidence even when precision is diagnostic."""
    def finite(value, *, nonnegative=False):
        return (isinstance(value, (int, float, np.integer, np.floating))
                and not isinstance(value, (bool, np.bool_)) and np.isfinite(value)
                and (not nonnegative or value >= 0))

    errors = ('max_conditioned_error', 'max_pointwise_error', 'max_mapper_error',
              'relative_interpolation_error', 'absolute_interpolation_error')
    if (field.get('audit_complete') is not True
            or not isinstance(field.get('field_passed'), bool)
            or any(not finite(field.get(key), nonnegative=True) for key in errors)):
        return False
    probes = field.get('probes')
    if not isinstance(probes, int) or isinstance(probes, bool) or probes <= 0:
        return False
    witnesses = field.get('witness')
    if not isinstance(witnesses, dict) or 'conditioned' not in witnesses:
        return False
    for metric in ('relative', 'absolute'):
        limit = field.get(f'{metric}_interpolation_limit')
        if not finite(limit, nonnegative=True) or (limit > 0 and metric not in witnesses):
            return False
    for witness in witnesses.values():
        if not isinstance(witness, dict):
            return False
        channel = witness.get('channel')
        if (not isinstance(channel, int) or isinstance(channel, bool) or channel < 0
                or any(not finite(witness.get(key)) for key in ('coordinate', 'expected', 'actual'))
                or not finite(witness.get('error'), nonnegative=True)):
            return False
    return True


def field_admission(report):
    """Admit explicit Color/Compact candidates by HDR worsening and safety.

    Scalar/local precision is diagnostic under the authorized policy. Every
    measured native image must match the complete scalar-diagnostic payload.
    Inherited construction failures remain separate; new failures reject a
    candidate, and this receipt never establishes complete graph admission.
    """
    request = report.get('request', {})
    specs = [spec for spec in request.get('candidates', ())
             if spec.get('role') in (*HDR_FIELD_ROLES, 'Combined Color')]
    if not specs:
        return None
    policies = {role: texture_admission_policy(role) for role in HDR_FIELD_ROLES}
    reasons = []
    if any(policy.get('basis') != 'hdr_worsening' for policy in policies.values()):
        reasons.append('Color and Compact Adaptance HDR admission is not authorized')
    limit = min(policy.get('max_worsening_codes', -np.inf) for policy in policies.values())
    if report.get('complete') is not True or report.get('sources_stable_during_run') is not True:
        reasons.append('Report is incomplete or sources changed during measurement')
    if report.get('identity', {}).get('request') != request:
        reasons.append('Request differs from its source-bound identity')
    if (request.get('baseline_color_cells') != ORIGINAL_COLOR_CELLS
            or request.get('baseline_compact_adaptance_cells') != ORIGINAL_COMPACT_ADAPTANCE_CELLS):
        reasons.append('Admission requires the explicit original 131072 Color / 16384 Compact Adaptance baseline')
    if request.get('graph_builder') != 'persistent':
        reasons.append('Admission requires the persistent graph builder')
    names = [row[0] for row in (*full_cases.grades(), *full_cases.ui_boundaries())]
    if (set(request.get('cases', ())) != set(names) or len(request.get('cases', ())) != len(names)
            or set(request.get('case_universe', ())) != set(names)
            or len(request.get('case_universe', ())) != len(names)
            or set(request.get('spaces', ())) != set(cases.SPACES)
            or len(request.get('spaces', ())) != len(cases.SPACES)
            or set(request.get('contexts', ())) != {'shader', 'compositor'}
            or len(request.get('contexts', ())) != 2
            or request.get('samples') != 1024 or request.get('case_shard') is not None):
        reasons.append('Admission requires the complete 149-case, three-space, two-context corpus at 1024 samples')
    expected = {(case, space, context) for case in names for space in cases.SPACES
                for context in ('shader', 'compositor')}
    baselines = report.get('baselines', ())
    by_key = {(row.get('case'), row.get('space'), row.get('context')): row for row in baselines}
    if len(by_key) != len(baselines) or set(by_key) != expected:
        reasons.append('Baseline coverage is incomplete or duplicated')
    if any(row.get('status') != 'measured' or row.get('final_rgb_passed') is not True
           or not np.isfinite(row.get('containment_max_normalized', np.inf))
           or row.get('containment_max_normalized', np.inf) > 8e-6 for row in baselines):
        reasons.append('Baseline contains a nonfinite or failed final-output/containment comparison')
    if any(not isinstance(row.get('node_budget_passed'), bool) for row in baselines):
        reasons.append('Baseline node-budget checks are missing')
    if len({spec['id'] for spec in specs}) != len(specs):
        reasons.append('Candidate selection contains duplicate IDs')
    candidates = []
    for spec in specs:
        changed = _required_roles(spec)
        sizes = ({'Color coefficients': spec.get('color_cells'),
                  'Adaptance parameters': spec.get('compact_adaptance_cells')}
                 if spec['role'] == 'Combined Color' else {spec['role']: spec.get('cells')})
        rejected = list(reasons)
        if any(not isinstance(count, int) or isinstance(count, bool) or count not in supported_cells(role)
               for role, count in sizes.items()):
            rejected.append('Candidate has an unsupported field layout')
            candidates.append(dict(id=spec['id'], cells=sizes, passed=False, rejection_reasons=rejected))
            continue
        selected = [row for row in report.get('rows', ()) if row.get('candidate') == spec['id']]
        keys = [(row.get('case'), row.get('space'), row.get('context')) for row in selected]
        coverage = len(keys) == len(set(keys)) and set(keys) == expected
        if not coverage:
            rejected.append('Candidate coverage is incomplete or duplicated')
        measured = [row for row in selected if row.get('status') == 'measured']
        if not measured:
            rejected.append('No native field sampling was measured')
        if any(row.get('status') not in ('measured', 'not_sampled') for row in selected):
            rejected.append('Candidate contains generation, render or nonfinite failures')
        for key, row in zip(keys, selected):
            baseline = by_key.get(key, {})
            active = set(changed) & set(baseline.get('image_receipts', {}))
            if row.get('status') == 'not_sampled':
                if active:
                    rejected.append('An active baseline field was not sampled by the candidate')
                continue
            if row.get('status') != 'measured':
                continue
            if set(row.get('sampled_roles', ())) != active or not active:
                rejected.append('Sampled roles differ from the active baseline fields')
            if set(row.get('changed_roles', ())) != set(changed):
                rejected.append('Changed roles differ from the requested candidate')
            metadata = row.get('texture_metadata', ())
            for role in changed:
                fields = [item for item in metadata if item.get('name') == role]
                if len(fields) != 1 or not _complete_field_diagnostics(fields[0]):
                    rejected.append('Complete scalar diagnostics are missing')
                    continue
                field = fields[0]
                shape = _field_shape(role, sizes[role])
                if (field.get('cells') != sizes[role] or field.get('shape') != shape
                        or field.get('bytes') != shape[0]*shape[1]*16):
                    rejected.append('Candidate field dimensions or byte count differ from the requested layout')
                if role not in active:
                    continue
                base_cells = ORIGINAL_COLOR_CELLS if role == 'Color coefficients' else ORIGINAL_COMPACT_ADAPTANCE_CELLS
                if not _verified_field_image(baseline.get('image_receipts', {}).get(role, {}), role, base_cells):
                    rejected.append('Baseline native image dimensions or payload verification are missing')
                if not _verified_field_image(row.get('image_receipts', {}).get(role, {}), role, sizes[role], field):
                    rejected.append('Candidate native image does not match the scalar-diagnostic payload')
        if any(row.get('final_rgb_passed') is not True for row in measured):
            rejected.append('Final scene-linear RGB comparison failed')
        if any(not np.isfinite(row.get('containment_max_normalized', np.inf))
               or row.get('containment_max_normalized', np.inf) > 8e-6 for row in measured):
            rejected.append('Containment check failed or is missing')
        if any(row.get('changed_validity_pixels') != 0 for row in measured):
            rejected.append('Validity flags changed or were not compared')
        if any(row.get('changed_saturation_pixels') != 0 for row in measured):
            rejected.append('Saturation flags changed or were not compared')
        if any(not isinstance(row.get('node_budget_passed'), bool) for row in measured):
            rejected.append('Candidate node-budget checks are missing')
        new_budget_failures = [row for row in measured if row.get('node_budget_passed') is False
            and by_key.get((row['case'], row['space'], row['context']), {}).get('node_budget_passed') is True]
        if new_budget_failures:
            rejected.append('Candidate introduced a new node-budget failure')
        peaks = [_metric_peak(row, 'worsening') for row in measured]
        movement = [_metric_peak(row, 'movement') for row in measured]
        finite = bool(peaks) and all(value is not None and np.isfinite(value) for value in (*peaks, *movement))
        if not finite:
            rejected.append('HDR worsening or movement metric is nonfinite or missing')
        elif max(peaks) > limit:
            rejected.append(f'Maximum signed HDR worsening exceeds {limit:g} codes')
        percentages = [_worsening_percentage_peak(row) for row in measured]
        percentages = [value for value in percentages if value is not None and np.isfinite(value)]
        worst = max(measured, key=lambda row: _metric_peak(row, 'worsening')) if finite else None
        candidates.append(dict(id=spec['id'], cells=sizes, measured_rows=len(measured),
            inactive_rows=sum(row.get('status') == 'not_sampled' for row in selected), coverage_complete=coverage,
            max_worsening_codes=max(peaks) if finite else None, max_movement_codes=max(movement) if finite else None,
            max_worsening_percentage=max(percentages) if percentages else None,
            scalar_failure_rows=sum(any(not field.get('field_passed', True) for field in row.get('texture_metadata', ()))
                                    for row in measured),
            node_budget_failure_rows=sum(row.get('node_budget_passed') is False for row in measured),
            new_node_budget_failure_rows=len(new_budget_failures), passed=not rejected,
            rejection_reasons=list(dict.fromkeys(rejected)),
            worst_worsening=None if worst is None else dict(case=worst['case'], space=worst['space'],
                context=worst['context'], pixel=worst.get('hdr', {}).get('witnesses', {}).get('worsening'))))
    return dict(policies=policies, max_worsening_codes=limit,
        baseline_color_cells=request.get('baseline_color_cells'),
        baseline_compact_adaptance_cells=request.get('baseline_compact_adaptance_cells'),
        baseline_node_budget_failure_rows=sum(row.get('node_budget_passed') is False for row in baselines),
        admitted_candidates=[row['id'] for row in candidates if row['passed']], candidates=candidates,
        scope='Texture layout admission only; inherited full-grade node-budget failures remain open.')


def _markdown(report):
    baselines = report['baselines']
    rows = report['rows']
    measured = [row for row in rows if row['status'] == 'measured']
    failures = [row for row in rows if row['status'] in ('generation_failed', 'render_failed', 'nonfinite')]
    current = [(_metric_peak(row, 'current'), row) for row in baselines if row.get('hdr')]
    worst = max(current, key=lambda item: item[0], default=None)
    lines = ['# HDR 10-bit RGB code-value sensitivity', '', report['scope'], '',
             f"Complete: **{report['complete']}**. Baselines: {len(baselines)}; "
             f"measured candidates: {len(measured)}; unused candidates: {sum(row['status'] == 'not_sampled' for row in rows)}; failures: {len(failures)}.", '']
    if worst:
        value, row = worst
        lines += [f"Current-layout worst pixel error: **{value:.9g} codes** "
                  f"({row['case']}, {row['space']}, {row['context']}).", '']
    if 'baseline_toe_cells' in report['request']:
        lines += [f"Explicit baseline Web toes: **{report['request']['baseline_toe_cells']:,} cells**.", '']
    if 'baseline_parameter_cells' in report['request']:
        lines += [f"Explicit baseline Web parameters: **{report['request']['baseline_parameter_cells']:,} cells**.", '']
    for key, label in (('baseline_color_cells', 'Color coefficients'),
                       ('baseline_compact_adaptance_cells', 'Compact Adaptance')):
        if key in report['request']:
            lines += [f"Explicit baseline {label}: **{report['request'][key]:,} cells**.", '']
    execution = report.get('execution')
    if execution:
        request = report['request']
        lines += [f"Native backend: **{request.get('backend', 'cpu')}**; requested threads: "
                  f"**{request.get('threads', 'host default')}**. Engine, device, precision and renderer are retained per measured row.", '']
    lines += [f"Graph builder: **{report['request'].get('graph_builder', 'specialized')}**.", '']
    lines += ['| Candidate | Measured rows | Reduced max error | Movement max | Worsening max | Worsening max (% reference peak) | Scalar failures |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for spec in report['request']['candidates']:
        selected = [row for row in measured if row['candidate'] == spec['id']]
        if not selected:
            lines.append(f"| {spec['id']} | 0 | — | — | — | — | — |")
            continue
        maximums = [max(_metric_peak(row, key) for row in selected)
                    for key in ('candidate', 'movement', 'worsening')]
        failed = sum(any(not item.get('field_passed', True) for item in row['texture_metadata'])
                     for row in selected)
        percentages = [_worsening_percentage_peak(row) for row in selected]
        percentages = [value for value in percentages if value is not None and np.isfinite(value)]
        percentage = f'{max(percentages):.9g}' if percentages else '—'
        lines.append(f"| {spec['id']} | {len(selected)} | " +
                     ' | '.join(f'{value:.9g}' for value in maximums) + f' | {percentage} | {failed} |')
    lines += ['', 'The table reports maxima over measured rows, not pooled percentiles. JSON retains per-row distributions and full worst-pixel witnesses.',
              'Code values are fractional full-range 10-bit RGB after the pinned ACES HDR-1000/PQ view. Near-black percentages are excluded below one reference code; their absolute errors remain recorded.',
              'Raw scalar failures remain visible. Web toes, Color coefficients and Compact Adaptance use their authorized HDR layout budgets with retained final-output/flag/containment checks; other roles retain scalar/local gates. Local/native-stage and GPU evidence are separate. No per-pixel archive is stored.', '']
    admission = report.get('toe_admission')
    if admission is not None:
        lines += [f"Web-toe HDR admission: smallest passing supported size **{admission['selected_cells']} cells** "
                  f"(maximum signed worsening {admission['policy']['max_worsening_codes']} codes).", '',
                  '| Toe cells | Maximum worsening | Maximum worsening (% reference peak) | Maximum movement | Admitted | Rejection reasons |',
                  '|---|---:|---:|---:|---|---|']
        for row in admission['candidates']:
            values = ['—' if row.get(key) is None else f"{row[key]:.9g}" for key in
                      ('max_worsening_codes', 'max_worsening_percentage', 'max_movement_codes')]
            lines.append(f"| {row['cells']} | {' | '.join(values)} | {row['passed']} | {'; '.join(row['rejection_reasons'])} |")
        lines.append('')
    admission = report.get('field_admission')
    if admission is not None:
        lines += ['Color/Compact HDR layout admission: complete scalar precision diagnostics; '
                  f"maximum signed worsening {admission['max_worsening_codes']:g} codes. "
                  'Inherited construction failures remain separate.', '',
                  '| Candidate | Maximum worsening | Admitted | New node-budget failures | Rejection reasons |',
                  '|---|---:|---|---:|---|']
        for row in admission['candidates']:
            maximum = '—' if row.get('max_worsening_codes') is None else f"{row['max_worsening_codes']:.9g}"
            lines.append(f"| {row['id']} | {maximum} | {row['passed']} | "
                         f"{row.get('new_node_budget_failure_rows', '—')} | {'; '.join(row['rejection_reasons'])} |")
        lines.append('')
    return '\n'.join(lines)


def _report_path(path):
    path = Path(path)
    return path/'report.json' if path.is_dir() else path


def _identity_without_case_shard(identity):
    """Return the provenance identity shared by all case workers."""
    if not isinstance(identity, dict):
        raise ValueError('Shard report identity is not an object')
    result = copy.deepcopy(identity)
    request = result.get('request')
    if not isinstance(request, dict):
        raise ValueError('Shard report identity has no request object')
    request.pop('cases', None)
    request.pop('case_shard', None)
    return result


def _row_keys(report, specs, spaces, contexts, universe):
    """Validate one complete shard and return its baseline/candidate keys."""
    cases_in_shard = list(report['identity']['request'].get('cases', ()))
    if not cases_in_shard or len(set(cases_in_shard)) != len(cases_in_shard):
        raise ValueError('Shard request must contain unique, nonempty cases')
    if not set(cases_in_shard) <= set(universe):
        raise ValueError('Shard request contains a case outside case_universe')
    expected_baselines = {(case, space, context)
                          for case in cases_in_shard for space in spaces for context in contexts}
    candidate_ids = tuple(spec['id'] for spec in specs)
    expected_rows = {(case, space, context, candidate)
                     for case, space, context in expected_baselines for candidate in candidate_ids}
    baselines = report.get('baselines')
    rows = report.get('rows')
    if not isinstance(baselines, list) or not isinstance(rows, list):
        raise ValueError('Shard report is missing baseline or candidate rows')
    baseline_keys = []
    for row in baselines:
        try:
            key = (row['case'], row['space'], row['context'])
        except (KeyError, TypeError):
            raise ValueError('Malformed baseline row in shard report') from None
        baseline_keys.append(key)
        if row.get('status') != 'measured':
            raise ValueError(f'Incomplete baseline row in shard report: {key}')
    if len(set(baseline_keys)) != len(baseline_keys) or set(baseline_keys) != expected_baselines:
        raise ValueError('Shard baseline coverage is incomplete or duplicated')
    row_keys = []
    for row in rows:
        try:
            key = (row['case'], row['space'], row['context'], row['candidate'])
        except (KeyError, TypeError):
            raise ValueError('Malformed candidate row in shard report') from None
        row_keys.append(key)
    if len(set(row_keys)) != len(row_keys) or set(row_keys) != expected_rows:
        raise ValueError('Shard candidate coverage is incomplete or duplicated')
    coverage = report.get('coverage')
    if coverage is not None and (
            coverage.get('expected_baselines') != len(expected_baselines)
            or coverage.get('actual_baselines') != len(baseline_keys)
            or coverage.get('expected_candidate_rows') != len(expected_rows)
            or coverage.get('actual_candidate_rows') != len(row_keys)):
        raise ValueError('Shard coverage counters differ from its rows')
    return cases_in_shard, baseline_keys, row_keys


def _write_journal(path, rows):
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w') as stream:
        for row in rows:
            stream.write(json.dumps(_json_values(row), separators=(',', ':'), allow_nan=False)+'\n')
    temporary.replace(path)


def _read_complete_journal(path):
    records = []
    for line in Path(path).read_bytes().splitlines(keepends=True):
        if not line.endswith(b'\n'):
            raise ValueError(f'Unterminated row in completed journal: {path}')
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f'Corrupt completed journal: {path}: {error}') from None
    return records


def merge_shards(output_dir, shard_dirs, *, expected_cases=None):
    """Merge complete, disjoint HDR case shards into a normal report.

    Workers write their own journals and report files.  This coordinator only
    combines committed JSON rows after checking that every non-case request
    identity matches and that the shard union exactly covers ``case_universe``.
    """
    shard_dirs = [Path(path) for path in shard_dirs]
    if not shard_dirs:
        raise ValueError('at least one shard report is required')
    loaded = []
    for directory in shard_dirs:
        path = _report_path(directory)
        if not path.exists():
            raise ValueError(f'Missing shard report: {path}')
        try:
            report = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f'Cannot read shard report: {path}: {error}') from None
        if not isinstance(report, dict):
            raise ValueError(f'Shard report is not an object: {path}')
        manifest_path = path.parent/'checkpoint.json'
        if not manifest_path.exists():
            raise ValueError(f'Missing shard checkpoint: {manifest_path}')
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f'Cannot read shard checkpoint: {manifest_path}: {error}') from None
        if manifest.get('complete') is not True or manifest.get('identity') != report.get('identity'):
            raise ValueError(f'Shard checkpoint is incomplete or has a different identity: {manifest_path}')
        if manifest.get('baseline_rows') != len(report.get('baselines', ())) or \
                manifest.get('candidate_rows') != len(report.get('rows', ())):
            raise ValueError(f'Shard checkpoint row counts differ from report: {manifest_path}')
        baseline_journal = path.parent/'baselines.jsonl'
        candidate_journal = path.parent/'candidates.jsonl'
        if not baseline_journal.exists() or not candidate_journal.exists():
            raise ValueError(f'Missing shard journals beside {path}')
        if (_read_complete_journal(baseline_journal) != report.get('baselines') or
                _read_complete_journal(candidate_journal) != report.get('rows')):
            raise ValueError(f'Shard journals differ from the committed report: {path.parent}')
        loaded.append((path, report))

    first = loaded[0][1]
    if first.get('schema') != 1:
        raise ValueError('Unsupported HDR shard report schema')
    identity = first.get('identity')
    if not isinstance(identity, dict):
        raise ValueError('Shard report has no identity')
    request = identity.get('request')
    if not isinstance(request, dict):
        raise ValueError('Shard identity has no request')
    universe = request.get('case_universe')
    if not isinstance(universe, list) or not universe or len(set(universe)) != len(universe):
        raise ValueError('Shard identity must declare a unique nonempty case_universe')
    if expected_cases is not None:
        if len(set(expected_cases)) != len(expected_cases) or set(expected_cases) != set(universe):
            raise ValueError('Explicit expected cases do not match the shard case_universe')
    spaces = tuple(request.get('spaces', ()))
    contexts = tuple(request.get('contexts', ()))
    _validate_axes(spaces, contexts)
    specs = request.get('candidates')
    if not isinstance(specs, list) or any(not isinstance(spec, dict) or 'id' not in spec for spec in specs):
        raise ValueError('Shard identity has malformed candidate selection')

    canonical_identity = _identity_without_case_shard(identity)
    all_cases = set()
    all_baselines, all_rows = [], []
    shard_metadata = []
    for path, report in loaded:
        if report.get('schema') != 1:
            raise ValueError(f'Unsupported HDR shard report schema: {path}')
        if report.get('complete') is not True:
            raise ValueError(f'Shard is incomplete: {path}')
        if report.get('sources_stable_during_run') is not True:
            raise ValueError(f'Shard sources were not stable: {path}')
        shard_identity = report.get('identity')
        if _identity_without_case_shard(shard_identity) != canonical_identity:
            raise ValueError(f'Shard non-case identity differs: {path}')
        if report.get('request') != shard_identity.get('request'):
            raise ValueError(f'Shard report/request identity differs: {path}')
        if report.get('scope') != first.get('scope') or report.get('limitations') != first.get('limitations'):
            raise ValueError(f'Shard report metadata differs: {path}')
        cases_in_shard, _, _ = _row_keys(report, specs, spaces, contexts, universe)
        overlap = all_cases.intersection(cases_in_shard)
        if overlap:
            raise ValueError(f'Shard case coverage overlaps: {sorted(overlap)}')
        all_cases.update(cases_in_shard)
        all_baselines.extend(report['baselines'])
        all_rows.extend(report['rows'])
        metadata = shard_identity.get('request', {}).get('case_shard')
        shard_metadata.append(metadata)

    if all_cases != set(universe):
        missing = sorted(set(universe)-all_cases)
        extra = sorted(all_cases-set(universe))
        raise ValueError(f'Shard case coverage differs from case_universe (missing={missing}, extra={extra})')
    present_metadata = [item for item in shard_metadata if item is not None]
    if present_metadata:
        if len(present_metadata) != len(shard_metadata):
            raise ValueError('Shard metadata is present only on some workers')
        if any(not isinstance(item, dict) or item.get('count') != len(loaded)
               or not isinstance(item.get('index'), int) for item in present_metadata):
            raise ValueError('Case shard metadata does not match the merge set')
        indices = [item['index'] for item in present_metadata]
        if sorted(indices) != list(range(len(loaded))):
            raise ValueError('Case shard indices must cover each worker exactly once')

    case_order = {name: index for index, name in enumerate(universe)}
    space_order = {name: index for index, name in enumerate(spaces)}
    context_order = {name: index for index, name in enumerate(contexts)}
    candidate_order = {spec['id']: index for index, spec in enumerate(specs)}
    all_baselines.sort(key=lambda row: (case_order[row['case']], space_order[row['space']],
                                        context_order[row['context']]))
    all_rows.sort(key=lambda row: (case_order[row['case']], space_order[row['space']],
                                   context_order[row['context']], candidate_order[row['candidate']]))
    combined_request = copy.deepcopy(request)
    combined_request['cases'] = list(universe)
    combined_request.pop('case_shard', None)
    combined_identity = copy.deepcopy(identity)
    combined_identity['request'] = combined_request
    expected_baselines = len(universe)*len(spaces)*len(contexts)
    expected_rows = expected_baselines*len(specs)
    result = copy.deepcopy(first)
    worker_seconds = [float(report.get('session_seconds', 0.)) for _, report in loaded]
    result.update(identity=combined_identity, request=combined_request,
                  baselines=all_baselines, rows=all_rows, complete=True,
                  sources_stable_during_run=True,
                  session_seconds=max(worker_seconds, default=0.),
                  worker_session_seconds_total=sum(worker_seconds),
                  shard_count=len(loaded),
                  coverage=dict(expected_baselines=expected_baselines,
                                actual_baselines=len(all_baselines),
                                expected_candidate_rows=expected_rows,
                                actual_candidate_rows=len(all_rows),
                                status_counts={status: sum(row['status'] == status for row in all_rows)
                                               for status in ('measured', 'not_sampled',
                                                              'generation_failed', 'render_failed',
                                                              'nonfinite')}))
    result['toe_admission'] = toe_admission(result)
    result['field_admission'] = field_admission(result)
    if len(all_baselines) != expected_baselines or len(all_rows) != expected_rows:
        raise ValueError('Merged report coverage is incomplete')
    output_dir = Path(output_dir)
    resolved_output = output_dir.resolve()
    if any(resolved_output == path.parent.resolve() for path, _ in loaded):
        raise ValueError('Merge output directory must differ from every shard directory')
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError('Merge output directory must be empty')
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_journal(output_dir/'baselines.jsonl', all_baselines)
    _write_journal(output_dir/'candidates.jsonl', all_rows)
    _write_json(output_dir/'checkpoint.json',
                dict(schema=1, identity=combined_identity, complete=True,
                     baseline_rows=len(all_baselines), candidate_rows=len(all_rows)))
    _write_json(output_dir/'report.json', result)
    (output_dir/'report.md').write_text(_markdown(result))
    return result


def run(output_dir, *, samples=1024, spaces=cases.SPACES, contexts=('shader','compositor'),
        selected=None, roles=None, candidate_ids=None, resume=False, case_shard=None,
        baseline_toe_cells=ORIGINAL_TOE_CELLS, baseline_parameter_cells=None,
        baseline_color_cells=None, baseline_compact_adaptance_cells=None,
        backend='cpu', threads=None, xvfb=None, graph_builder='specialized'):
    spaces = tuple(spaces)
    contexts = tuple(contexts)
    _validate_axes(spaces, contexts)
    _graph_builder(graph_builder)
    if baseline_toe_cells not in supported_cells('Web toes'):
        raise ValueError('Unsupported baseline Web-toe cell count')
    if baseline_parameter_cells is not None and baseline_parameter_cells not in supported_cells('Web parameters'):
        raise ValueError('Unsupported baseline Web-parameter cell count')
    for role, cells in (('Color coefficients', baseline_color_cells),
                        ('Adaptance parameters', baseline_compact_adaptance_cells)):
        if cells is not None and cells not in supported_cells(role):
            raise ValueError(f'Unsupported baseline {role} cell count')
    threads = _backend_threads(backend, threads)
    import bpy
    from .benchmark import available_threads, software_gpu_info, thread_snapshot
    render_backend = software_gpu_info() if backend == 'software-gpu' else None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_identity = identities()
    display = HDRDisplay(spaces=spaces)
    all_corpus = list(full_cases.grades()) + list(full_cases.ui_boundaries())
    all_corpus_names = [row[0] for row in all_corpus]
    if len(set(all_corpus_names)) != len(all_corpus_names):
        raise ValueError('Evaluation case identities must be unique')
    if selected:
        unknown = set(selected)-set(all_corpus_names)
        if unknown:
            raise ValueError(f'Unknown cases: {sorted(unknown)}')
        selected_set = set(selected)
        all_corpus = [row for row in all_corpus if row[0] in selected_set]
    corpus_names = [row[0] for row in all_corpus]
    shard_metadata = None
    if case_shard is not None:
        try:
            shard_index, shard_count = case_shard
        except (TypeError, ValueError):
            raise ValueError('case_shard must be a pair of (index, count)') from None
        if not isinstance(shard_index, int) or not isinstance(shard_count, int):
            raise ValueError('case shard index and count must be integers')
        shard_names = case_shards(corpus_names, shard_count)
        if not 0 <= shard_index < shard_count:
            raise ValueError('case shard index must be in [0, count)')
        selected_names = set(shard_names[shard_index])
        corpus = [row for row in all_corpus if row[0] in selected_names]
        shard_metadata = dict(index=shard_index, count=shard_count)
    else:
        corpus = all_corpus
    specs = selection(roles, candidate_ids)
    request = _request(samples=samples, spaces=spaces, contexts=contexts,
        cases=[row[0] for row in corpus], case_universe=corpus_names, candidates=specs,
        baseline_toe_cells=baseline_toe_cells, baseline_parameter_cells=baseline_parameter_cells,
        baseline_color_cells=baseline_color_cells,
        baseline_compact_adaptance_cells=baseline_compact_adaptance_cells,
        backend=backend, threads=threads, case_shard=shard_metadata, graph_builder=graph_builder)
    identity = dict(sources=source_identity, display=display.metadata,
                    blender=bpy.app.version_string, request=request)
    if render_backend is not None:
        identity['render_backend'] = render_backend
    manifest_path = output_dir/'checkpoint.json'
    baseline_path, rows_path = output_dir/'baselines.jsonl', output_dir/'candidates.jsonl'
    if manifest_path.exists():
        if not resume:
            raise ValueError('Output already contains a checkpoint; use --resume or a new output directory')
        if json.loads(manifest_path.read_text())['identity'] != _json_values(identity):
            raise ValueError('Cannot resume: source, display, dependency or request identities differ')
    else:
        if baseline_path.exists() or rows_path.exists():
            raise ValueError('Orphaned report journal without identity manifest')
        _write_json(manifest_path, dict(schema=1, identity=identity, complete=False))
    baselines, rows = _load_journal(baseline_path), _load_journal(rows_path)
    baseline_done = {(r['case'],r['space'],r['context']): r for r in baselines}
    row_done = {(r['case'],r['space'],r['context'],r['candidate']) for r in rows}
    boundary_cache, candidate_boundary_cache = {}, {}
    report = dict(schema=1, identity=identity, request=request,
                  backend=backend, threads=threads, render_backend=render_backend, graph_builder=graph_builder,
                  execution=dict(available_cpu_count=available_threads(),
                      cpu_affinity=(sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None),
                      xvfb_fixture=str(Path(xvfb).resolve()) if xvfb is not None else None,
                      worker_environment={key:os.environ.get(key) for key in
                          ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'LP_NUM_THREADS',
                           'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', '__GLX_VENDOR_LIBRARY_NAME')},
                      process_threads=thread_snapshot()),
                  scope='Matched independent reference, current native graph and actual reduced-texture native graph through ACES 2.0 HDR 1000 nits on Rec.2100-PQ.',
                  limitations=['Finite deterministic corpus, not a continuous-domain proof.',
                               'Web-toe, Color coefficient and Compact Adaptance sizing use authorized HDR policies; scalar and local diagnostics remain visible.',
                               'Float64 grading reference rounded to float32 at the shared OCIO display boundary.',
                               ('Mesa software-GPU Shader/Compositor evidence; physical GPU behavior and interactive timing are separate.'
                                if backend == 'software-gpu' else
                                'CPU Shader/Compositor evidence; physical GPU behavior and interactive timing are separate.')],
                  baselines=baselines, rows=rows, complete=False)
    started = time.perf_counter()

    checkpoint_ordinal = 0

    def checkpoint(complete=False, *, persist_report=False):
        nonlocal checkpoint_ordinal
        checkpoint_ordinal += 1
        stable = source_identity == identities()
        report.update(complete=bool(complete and stable), sources_stable_during_run=stable,
                      session_seconds=time.perf_counter()-started)
        if complete:
            report['toe_admission'] = toe_admission(report)
            report['field_admission'] = field_admission(report)
            report['execution']['process_threads'] = thread_snapshot()
        _write_json(manifest_path, dict(schema=1, identity=identity, complete=report['complete'],
                                       baseline_rows=len(baselines), candidate_rows=len(rows)))
        # Journals are flushed per row. Materialize the larger aggregate less
        # often so progress checkpoints do not repeatedly serialize all pixels'
        # witnesses accumulated so far.
        if persist_report or checkpoint_ordinal % 20 == 0:
            _write_json(output_dir/'report.json', report)
            (output_dir/'report.md').write_text(_markdown(report))
        if not stable:
            raise RuntimeError('Sources changed during HDR report; receipt remains incomplete')

    checkpoint()
    for name, linear, tone, color in corpus:
        if all((name,space,context) in baseline_done and
               all((name,space,context,s['id']) in row_done for s in specs)
               for space in spaces for context in contexts):
            continue
        base = prepare(linear, tone, color=color, full_fields=True)
        base = _with_baseline_toe(base, baseline_toe_cells)
        if baseline_parameter_cells is not None:
            base = _with_baseline_parameters(base, baseline_parameter_cells)
        if baseline_color_cells is not None:
            base = _with_baseline_field(base, 'Color coefficients', baseline_color_cells)
        if baseline_compact_adaptance_cells is not None:
            base = _with_baseline_field(base, 'Adaptance parameters', baseline_compact_adaptance_cells)
        context_key = (base.fl, base.aw, base.gamma)
        if context_key not in boundary_cache:
            boundary_cache[context_key] = prepare_boundary(*context_key)
        base = replace(base, boundary=boundary_cache[context_key])
        candidates = {}
        for space in spaces:
            values = full_cases.rgba(space, samples)
            expected = oracle.evaluate_full(values[:,:3], linear, tone, color, space)
            reference_codes = display.codes(expected['rgb'], space)
            current = replace(base, linear=prepare_linear(linear, space), space=space)
            for context in contexts:
                key = (name, space, context)
                pending = [s for s in specs if (*key,s['id']) not in row_done]
                if key in baseline_done and not pending:
                    continue
                actual_base, measured_base = _render(current, values, context, expected,
                    backend=backend, threads=threads, render_backend=render_backend, graph_builder=graph_builder)
                if measured_base['status'] != 'measured':
                    raise RuntimeError(f'Nonfinite current-layout baseline: {key}')
                baseline_codes = display.codes(actual_base['rgb'], space)
                if key not in baseline_done:
                    row = dict(case=name, space=space, context=context, **measured_base,
                               input_sha256=_hash(values.tobytes()),
                               settings=dict(linear=asdict(linear), tone=asdict(tone), color=asdict(color)),
                               hdr=compare(reference_codes, baseline_codes, inputs=values,
                                           reference_rgb=expected['rgb'], baseline_rgb=actual_base['rgb']))
                    baselines.append(row)
                    baseline_done[key] = row
                    _append_journal(baseline_path, row)
                active = set(measured_base['image_receipts'])
                for spec in pending:
                    required = set(_required_roles(spec)) & active
                    row = dict(case=name, space=space, context=context, candidate=spec['id'],
                               changed_roles=list(_required_roles(spec)), sampled_roles=sorted(required))
                    if not required:
                        row.update(status='not_sampled', reason='Current graph omits the changed texture(s).')
                    else:
                        if spec['id'] not in candidates:
                            try:
                                candidates[spec['id']] = _make_candidate(base, spec, candidate_boundary_cache)
                            except Exception as error:
                                candidates[spec['id']] = error
                        candidate = candidates[spec['id']]
                        if isinstance(candidate, Exception):
                            row.update(status='generation_failed', error=repr(candidate))
                        else:
                            prepared, texture_metadata = candidate
                            row['texture_metadata'] = texture_metadata
                            native = replace(prepared, linear=current.linear, space=space)
                            try:
                                actual, measured = _render(native, values, context, expected, required_roles=required,
                                    backend=backend, threads=threads, render_backend=render_backend, graph_builder=graph_builder)
                                row.update(measured)
                                if measured['status'] == 'measured':
                                    encoded = display.codes(actual['rgb'], space)
                                    row['hdr'] = compare(reference_codes, baseline_codes, encoded,
                                                         inputs=values, reference_rgb=expected['rgb'],
                                                         baseline_rgb=actual_base['rgb'], candidate_rgb=actual['rgb'])
                                    row['changed_validity_pixels'] = int(np.sum((actual['valid']>.5) != (actual_base['valid']>.5)))
                                    row['changed_saturation_pixels'] = int(np.sum((actual['saturated']>.5) != (actual_base['saturated']>.5)))
                            except Exception as error:
                                row.update(status='render_failed', error=repr(error))
                    rows.append(row)
                    row_done.add((*key,spec['id']))
                    _append_journal(rows_path, row)
                    if row['status'] != 'not_sampled':
                        print(f'{name} | {space} | {context} | {spec["id"]}: {row["status"]}', flush=True)
                checkpoint()
        checkpoint(persist_report=True)
        print(f'Completed case {name}: {len(baselines)} baselines, {len(rows)} candidate grid rows', flush=True)
    expected_baselines = len(corpus)*len(spaces)*len(contexts)
    report['coverage'] = dict(expected_baselines=expected_baselines, actual_baselines=len(baselines),
                              expected_candidate_rows=expected_baselines*len(specs), actual_candidate_rows=len(rows),
                              status_counts={status: sum(r['status']==status for r in rows)
                                             for status in ('measured','not_sampled','generation_failed','render_failed','nonfinite')})
    complete = len(baselines)==expected_baselines and len(rows)==expected_baselines*len(specs)
    checkpoint(complete, persist_report=True)
    return report


def _launch_software_gpu(output_dir, arguments, *, xvfb, threads):
    """Start Blender only after the pinned display and Mesa paths are installed."""
    from .benchmark import software_gpu_environment
    from .gpu_report import display_environment
    if xvfb is None:
        raise ValueError('The software-gpu backend requires the pinned --xvfb fixture')
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    script = ('import sys; sys.path[:]=' + repr(sys.path) + '; '
              'from tools.perceptual_grade.reports.hdr_report import main; main(sys.argv[1:])')
    command = [sys.executable, '-c', script, *arguments, '--worker', '--threads', str(threads)]
    log_path = output_dir/'native.log'
    with tempfile.TemporaryDirectory(prefix='grade-nodes-hdr-') as directory:
        directory = Path(directory)
        try:
            with display_environment(xvfb, directory) as display_env:
                environment = software_gpu_environment(display_env, xvfb, threads)
                with log_path.open('w') as log:
                    process = subprocess.run(command, env=environment, stdout=log,
                                             stderr=subprocess.STDOUT)
        finally:
            if (directory/'xvfb.log').exists():
                (output_dir/'xvfb.log').write_bytes((directory/'xvfb.log').read_bytes())
    if process.returncode:
        raise RuntimeError(f'HDR software-GPU worker failed ({process.returncode}); see {log_path}')
    return json.loads((output_dir/'report.json').read_text())


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--merge-shards', nargs='+', type=Path,
                        help='Merge complete shard output directories into --output-dir')
    parser.add_argument('--samples', type=int)
    parser.add_argument('--spaces', nargs='+', choices=cases.SPACES)
    parser.add_argument('--contexts', nargs='+', choices=('shader','compositor'))
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--roles', nargs='+', choices=ROLES)
    parser.add_argument('--candidate-ids', nargs='+')
    parser.add_argument('--baseline-toe-cells', type=int,
                        help='Explicit baseline toe layout (default: original 524288 cells)')
    parser.add_argument('--baseline-parameter-cells', type=int,
                        help='Explicit baseline Web-parameter layout (default: current runtime cells)')
    parser.add_argument('--baseline-color-cells', type=int,
                        help='Explicit baseline Color coefficient layout (default: current runtime cells)')
    parser.add_argument('--baseline-compact-adaptance-cells', type=int,
                        help='Explicit baseline Compact Adaptance layout (default: current runtime cells)')
    parser.add_argument('--graph-builder', choices=('specialized', 'persistent'),
                        help='Native graph construction path (default: specialized)')
    parser.add_argument('--backend', choices=('cpu', 'software-gpu'))
    parser.add_argument('--threads', type=int)
    parser.add_argument('--xvfb', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--case-shard', nargs=2, type=int, metavar=('INDEX', 'COUNT'),
                        help='Zero-based deterministic case shard as INDEX COUNT')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(arguments)
    if args.merge_shards:
        if args.case_shard or args.resume:
            parser.error('--merge-shards cannot be combined with shard selection or --resume')
        if args.roles or args.candidate_ids:
            parser.error('--roles and --candidate-ids are read from shard identities')
        if args.samples is not None or args.spaces is not None or args.contexts is not None:
            parser.error('--samples, --spaces and --contexts are read from shard identities')
        if any(value is not None for value in (args.baseline_toe_cells, args.baseline_parameter_cells,
                                               args.baseline_color_cells, args.baseline_compact_adaptance_cells)):
            parser.error('Baseline layouts are read from shard identities')
        if args.backend is not None or args.threads is not None or args.xvfb is not None or args.worker:
            parser.error('Backend and thread settings are read from shard identities')
        if args.graph_builder is not None:
            parser.error('Graph builder is read from shard identities')
        try:
            merge_shards(args.output_dir, args.merge_shards, expected_cases=args.cases)
        except ValueError as error:
            parser.error(str(error))
        return
    shard = None if args.case_shard is None else tuple(args.case_shard)
    samples = 1024 if args.samples is None else args.samples
    spaces = cases.SPACES if args.spaces is None else args.spaces
    contexts = ('shader','compositor') if args.contexts is None else args.contexts
    if samples < 256:
        parser.error('--samples must be at least 256')
    backend = args.backend or 'cpu'
    try:
        threads = _backend_threads(backend, args.threads)
        if args.baseline_parameter_cells is not None and args.baseline_parameter_cells not in supported_cells('Web parameters'):
            raise ValueError('Unsupported baseline Web-parameter cell count')
        if args.baseline_toe_cells is not None and args.baseline_toe_cells not in supported_cells('Web toes'):
            raise ValueError('Unsupported baseline Web-toe cell count')
        for role, cells in (('Color coefficients', args.baseline_color_cells),
                            ('Adaptance parameters', args.baseline_compact_adaptance_cells)):
            if cells is not None and cells not in supported_cells(role):
                raise ValueError(f'Unsupported baseline {role} cell count')
    except ValueError as error:
        parser.error(str(error))
    if shard is not None:
        corpus_names = [row[0] for row in list(full_cases.grades())+list(full_cases.ui_boundaries())]
        requested = set(corpus_names if not args.cases else args.cases)
        unknown = requested-set(corpus_names)
        if unknown:
            parser.error(f'Unknown cases: {sorted(unknown)}')
        selected = [name for name in corpus_names if name in requested]
        try:
            case_shards(selected, shard[1])
        except ValueError as error:
            parser.error(str(error))
        if not 0 <= shard[0] < shard[1]:
            parser.error('--case-shard index must be in [0, count)')
    if backend == 'software-gpu' and not args.worker:
        try:
            _launch_software_gpu(args.output_dir, arguments, xvfb=args.xvfb, threads=threads)
        except ValueError as error:
            parser.error(str(error))
        return
    run(args.output_dir, samples=samples, spaces=spaces, contexts=contexts,
        selected=args.cases, roles=args.roles, candidate_ids=args.candidate_ids,
        resume=args.resume, case_shard=shard,
        baseline_toe_cells=ORIGINAL_TOE_CELLS if args.baseline_toe_cells is None else args.baseline_toe_cells,
        baseline_parameter_cells=args.baseline_parameter_cells,
        baseline_color_cells=args.baseline_color_cells,
        baseline_compact_adaptance_cells=args.baseline_compact_adaptance_cells,
        backend=backend, threads=threads, xvfb=args.xvfb, graph_builder=args.graph_builder or 'specialized')


if __name__ == '__main__':
    main()
