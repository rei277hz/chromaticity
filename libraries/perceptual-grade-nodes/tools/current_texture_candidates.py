"""Independent texture reductions from the current runtime layout.

These helpers create diagnostic immutable payloads. They never change runtime
capacities or admit a smaller production layout, and do not time generation.
Color field scalar audits are intentionally separate from native accuracy runs.
"""
from dataclasses import replace
import hashlib

import numpy as np

from color_tools.perceptual_grade_nodes.boundary import (
    SEED_LOW_CELLS, SEED_HIGH_CELLS, SEED_HUE_CELLS,
)
from color_tools.perceptual_grade_nodes.color_prepare import _generate_field, _prepare_tables
from color_tools.perceptual_grade_nodes.layouts import FIELD_CELLS, TONE_CELLS, supported_cells
from color_tools.perceptual_grade_nodes.tables import build_diagnostic_table, TABLE_ERROR_LIMIT
from .build_boundary import generate_boundary


ATTRIBUTES = {
    'Color coefficients': 'coefficient_table',
    'Web parameters': 'web_table',
    'Web toes': 'web_toe_table',
    'Adaptance parameters': 'adaptance_table',
}
REDUCED_CELLS = {
    'Tone': (128,),
    'Color coefficients': (4096,),
    'Web parameters': (2048,),
    'Web toes': (1280, 1024, 768),
    'Adaptance parameters': (2048,),
}
REDUCED_BOUNDARIES = ((64, 96, 256), (32, 48, 128))


def baseline_layout(prepared=None):
    """Describe current capacities and optionally verify an actual baseline.

    The baseline comes from runtime constants, with no historical overrides.
    A prepared baseline must contain every current field and the fixed boundary.
    """
    result = {'Tone': TONE_CELLS, **dict(FIELD_CELLS), 'Output boundary': dict(
        low_cells=SEED_LOW_CELLS, high_cells=SEED_HIGH_CELLS, hue_cells=SEED_HUE_CELLS,
        width=SEED_HUE_CELLS+1, height=SEED_LOW_CELLS+SEED_HIGH_CELLS+1)}
    if prepared is not None:
        for role, cells in result.items():
            table = _table(prepared, role)
            if table is None:
                raise ValueError('Current baseline is missing texture: '+role)
            if role != 'Output boundary':
                if table.cells != cells:
                    raise ValueError('Baseline is not the current runtime size: '+role)
            elif (table.seed_low_cells != cells['low_cells'] or
                  table.seed_high_cells != cells['high_cells'] or
                  table.seed_hue_cells != cells['hue_cells'] or
                  table.pixels.shape != (cells['height'], cells['width'], 4)):
                raise ValueError('Baseline is not the current output boundary')
        if hasattr(prepared.color, 'adaptance_interior_table'):
            raise ValueError('Current baseline must use Compact-only Adaptance')
    return result


def _positive_integer(value, label):
    if not isinstance(value, (int, np.integer)) or isinstance(value, (bool, np.bool_)) or value < 1:
        raise ValueError(label+' must be a positive integer')
    return int(value)


def validate_spec(spec):
    """Reject same-size/larger grids and malformed diagnostic requests."""
    role = spec.get('role')
    layout = baseline_layout()
    if role not in layout:
        raise ValueError('Unknown current texture role: '+str(role))
    if role == 'Output boundary':
        names = ('low_cells', 'high_cells', 'hue_cells')
        values = [_positive_integer(spec.get(name), name) for name in names]
        baseline = [layout[role][name] for name in names]
        if any(value > current for value, current in zip(values, baseline)) or values == baseline:
            raise ValueError('Boundary candidate must be strictly smaller than current')
        if (values[0]+values[1]+1)*(values[2]+1) >= (baseline[0]+baseline[1]+1)*(baseline[2]+1):
            raise ValueError('Boundary candidate must reduce stored payload')
    else:
        cells = _positive_integer(spec.get('cells'), 'cells')
        if cells >= layout[role]:
            raise ValueError('Candidate must be strictly smaller than current: '+role)
        if role == 'Tone':
            if cells & (cells-1):
                raise ValueError('Diagnostic Tone cells must be a power of two')
        elif cells not in supported_cells(role):
            raise ValueError('Unsupported diagnostic grid: '+role)
    return spec


def selection(candidate_ids=None):
    """Return stable smaller-only specifications, optionally selecting IDs."""
    specs = [dict(id=f'{role}/{cells}', role=role, cells=cells)
             for role, counts in REDUCED_CELLS.items() for cells in counts]
    specs += [dict(id=f'Output boundary/{hue+1}x{low+high+1}', role='Output boundary',
                   low_cells=low, high_cells=high, hue_cells=hue)
              for low, high, hue in REDUCED_BOUNDARIES]
    for spec in specs:
        validate_spec(spec)
    if candidate_ids is not None:
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError('Candidate IDs must be unique')
        unknown = set(candidate_ids)-{spec['id'] for spec in specs}
        if unknown:
            raise ValueError('Unknown current-layout candidates: '+repr(sorted(unknown)))
        specs = [spec for spec in specs if spec['id'] in candidate_ids]
    return specs


def _table(prepared, role):
    if role == 'Tone':
        return prepared.tone.table
    if role == 'Output boundary':
        return prepared.boundary
    return getattr(prepared.color, ATTRIBUTES[role])


def collect_evaluators(prepared):
    """Capture each current Color field's exact generator arguments.

    Accepts either PreparedGrade or PreparedColor. No field arrays are generated
    and no scalar audit or native graph is constructed.
    """
    color = getattr(prepared, 'color', prepared)
    result = {}

    def collect(name, *args, **kwargs):
        result[name] = ((name, *args), kwargs)
        return None

    _prepare_tables(color, builder=collect)
    return result


def _metadata(role, table):
    result = dict(name=role, shape=list(table.pixels.shape), bytes=int(table.pixels.nbytes),
                  pixels_sha256=hashlib.sha256(table.pixels.tobytes()).hexdigest())
    if role == 'Output boundary':
        result.update(low_cells=table.seed_low_cells, high_cells=table.seed_high_cells,
                      hue_cells=table.seed_hue_cells, correction_steps=table.correction_steps)
    else:
        result['cells'] = table.cells
    return result


def candidate(prepared, spec, cache=None):
    """Replace exactly one texture in an otherwise current prepared baseline.

    Returned metadata records actual packed bytes, not estimated cell ratios.
    A caller-owned cache reuses immutable boundary geometry for equal context
    and grid. No duration from this function is performance evidence.
    """
    baseline_layout(prepared)
    validate_spec(spec)
    role = spec['role']
    original = _table(prepared, role)
    if role in ATTRIBUTES:
        args, kwargs = collect_evaluators(prepared)[role]
        table = _generate_field(*args, **kwargs, cells=spec['cells'])
        result = replace(prepared, color=replace(prepared.color, **{ATTRIBUTES[role]: table}))
        diagnostics = dict(scalar_audit='not_run', field_passed=None)
    elif role == 'Tone':
        table = build_diagnostic_table(prepared.tone, spec['cells'])
        result = replace(prepared, tone=replace(prepared.tone, table=table))
        diagnostics = dict(scalar_audit='complete', field_passed=bool(
            table.monotone and table.max_error <= TABLE_ERROR_LIMIT),
            max_conditioned_error=table.max_error, scalar_limit=TABLE_ERROR_LIMIT,
            probes=table.probe_count, monotone=table.monotone, limited_knots=table.limited_knots)
    else:
        key = ('current-boundary', prepared.fl, prepared.aw, prepared.gamma,
               spec['low_cells'], spec['high_cells'], spec['hue_cells'])
        if cache is None:
            cache = {}
        if key not in cache:
            cache[key] = generate_boundary(prepared.fl, prepared.aw, prepared.gamma,
                low_cells=spec['low_cells'], high_cells=spec['high_cells'],
                hue_cells=spec['hue_cells'], enforce_accuracy=False)
        table = cache[key]
        result = replace(prepared, boundary=table)
        diagnostics = dict(scalar_audit='complete', field_passed=bool(table.max_error <= 2e-5),
                           corrected_radius_error=table.max_error, corrected_radius_limit=2e-5,
                           probes=table.probe_count)
    for other in baseline_layout():
        if other != role and _table(result, other) is not _table(prepared, other):
            raise AssertionError('Candidate changed an unrelated texture: '+other)
    metadata = dict(id=spec.get('id'), role=role, **_metadata(role, table),
                    baseline=_metadata(role, original), saved_bytes=int(original.pixels.nbytes-table.pixels.nbytes),
                    changed_roles=[role], **diagnostics)
    if metadata['saved_bytes'] <= 0:
        raise AssertionError('Candidate did not reduce packed texture storage')
    return result, metadata
