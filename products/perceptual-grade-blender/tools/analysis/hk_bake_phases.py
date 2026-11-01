"""Exclusive CPU phase measurements for the H-K bake comparison.

The wrappers call the original methods with their original arguments.  Each
worker has an independent nesting stack, so child calls are subtracted from
their parent's phase.  The worker that completes last supplies one additive
wall-time breakdown; sums across workers describe overlapping elapsed work.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import wraps
from threading import Lock, get_ident, local
from time import perf_counter
from unittest.mock import patch

import numpy as np

from color_tools.perceptual_grade_core.model import bake_inverse


PHASES = {
    'import': 'RGB to appearance',
    'tone': 'Forward tone',
    'grade': 'Creative grade',
    'hk_guard': 'H-K check/repair',
    'cube_export': 'Cube guard and RGB export',
    'raw_solve': 'Raw appearance inverse bookkeeping',
    'tone_inverse': 'Inverse tone and rescaling',
    'validation': 'Candidate validation bookkeeping',
    'assembly': 'Candidate ranking, assembly and Stack bookkeeping',
}


class PhaseProfile:
    """One diagnostic bake, independent of the uninstrumented timing trials."""

    def __init__(self):
        self.local = local()
        self.workers = {}
        self.lock = Lock()

    def _state(self):
        if not hasattr(self.local, 'state'):
            self.local.state = dict(
                frames=[], seconds={name: 0. for name in PHASES}, events={},
                last=None,
                solver_totals={'raw_solve': dict(calls=0, rows=0, seconds=0.)})
            with self.lock:
                self.workers[get_ident()] = self.local.state
        return self.local.state

    def _wrap(self, function, event, phase, row_argument=0, solver=False):
        @wraps(function)
        def measured(*args, **kwargs):
            state = self._state()
            name = event(*args, **kwargs) if callable(event) else event
            group = phase(*args, **kwargs) if callable(phase) else phase
            # Every wrapped method receives the relevant array positionally
            # on the supported portable bake paths, including minimize's seed.
            rows = len(args[row_argument])
            frame = [group, perf_counter(), 0.]
            state['frames'].append(frame)
            try:
                return function(*args, **kwargs)
            finally:
                end = perf_counter()
                duration = end-frame[1]
                state['frames'].pop()
                state['seconds'][group] += duration-frame[2]
                if state['frames']:
                    state['frames'][-1][2] += duration
                else:
                    state['last'] = end
                counter = state['events'].setdefault(
                    name, dict(calls=0, rows=0, maximum_batch=0))
                counter['calls'] += 1
                counter['rows'] += rows
                counter['maximum_batch'] = max(counter['maximum_batch'], rows)
                if solver:
                    total = state['solver_totals'][group]
                    total['calls'] += 1
                    total['rows'] += rows
                    total['seconds'] += duration
        return measured

    def run(self, stacks, operation, rgb, chunk=65536, expected=None):
        """Run ``operation(batch)`` over RGB rows using four CPU workers.

        ``stacks`` must contain every BakeStack used by the operation.  The
        returned phase times exclude stack construction.  ``solver_totals``
        are inclusive diagnostics and must not be added to exclusive phases.
        If ``expected`` is supplied, all output bytes must match it.
        """
        if self.workers:
            raise ValueError('Use a fresh PhaseProfile for each diagnostic bake')
        rgb = np.asarray(rgb)
        if rgb.ndim != 2 or rgb.shape[1] != 3:
            raise ValueError('Phase profiling requires an N by 3 RGB array')
        if len(rgb) == 0 or chunk < 1:
            raise ValueError('Phase profiling requires nonempty input and chunk >= 1')

        targets = []
        for stack in stacks:
            for kernel in stack.kernels:
                targets.extend((kernel, method, event, phase) for method, event, phase in (
                    ('enter', 'enter', 'import'),
                    ('tone_state', 'forward_tone', 'tone'),
                    ('grade', 'forward_grade', 'grade'),
                    ('_hk_export', 'hk_guard', 'hk_guard'),
                    ('export', 'cube_export', 'cube_export')))
            for inverse in stack.solvers:
                targets.extend((inverse, method, event, phase) for method, event, phase in (
                    ('evaluate', 'inverse', 'assembly'),
                    ('reduced', 'raw_residual_or_reconstruction', 'raw_solve'),
                    ('undo_tone', 'tone_inverse', 'tone_inverse'),
                    ('residual', 'candidate_validation', 'validation'),
                    ('forward_prior', 'prior_forward', 'validation')))

        measured_operation = self._wrap(operation, 'chunk', 'assembly')
        batches = [rgb[i:i+chunk] for i in range(0, len(rgb), chunk)]
        with ExitStack() as scope:
            seen = set()
            for owner, method, event, phase in targets:
                key = (id(owner), method)
                if key in seen:
                    continue
                seen.add(key)
                scope.enter_context(patch.object(
                    owner, method, self._wrap(getattr(owner, method), event, phase)))
            scope.enter_context(patch.object(
                bake_inverse, 'minimize', self._wrap(
                    bake_inverse.minimize, 'raw_solve', 'raw_solve', 1, solver=True)))
            start = perf_counter()
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix='PG H-K profile') as pool:
                values = np.concatenate(list(pool.map(measured_operation, batches)))
            wall = perf_counter()-start

        bit_identical = None
        if expected is not None:
            expected = np.asarray(expected)
            bit_identical = (values.shape == expected.shape and values.dtype == expected.dtype
                             and values.tobytes() == expected.tobytes())
            if not bit_identical:
                raise ArithmeticError('Phase instrumentation changed the bake result')

        critical = max(self.workers.values(), key=lambda worker: worker['last'])
        path = dict(critical['seconds'])
        path['host_idle'] = wall-sum(path.values())
        if min(path.values()) < -1e-9:
            raise ArithmeticError('Exclusive phase intervals overlap')
        totals = {name: sum(worker['seconds'][name] for worker in self.workers.values())
                  for name in PHASES}
        events = {}
        solver_totals = {'raw_solve': dict(calls=0, rows=0, seconds=0.)}
        for worker in self.workers.values():
            for name, value in worker['events'].items():
                counter = events.setdefault(name, dict(calls=0, rows=0, maximum_batch=0))
                for key in ('calls', 'rows'):
                    counter[key] += value[key]
                counter['maximum_batch'] = max(counter['maximum_batch'], value['maximum_batch'])
            for name, value in worker['solver_totals'].items():
                for key in ('calls', 'rows', 'seconds'):
                    solver_totals[name][key] += value[key]

        report = dict(
            wall_seconds=wall, workers=len(self.workers), chunk=chunk,
            bit_identical=bit_identical,
            critical_worker_seconds=path, all_worker_seconds=totals,
            events=events, solver_totals=solver_totals,
            raw_solve_rows=solver_totals['raw_solve']['rows'],
            critical_worker_solver_totals=critical['solver_totals'],
            limitations=[
                'One complete instrumented bake; stack construction is excluded.',
                'Critical-worker phases plus host_idle sum to instrumented wall time.',
                'All-worker intervals overlap and include scheduling delays; they are not CPU-cycle measurements.',
                'Inclusive solver_totals contain nested kernel phases and must not be added to exclusive phases.',
                'Row counts include repeated candidate evaluations; solver rows count input lanes to each solve.',
                'Python wrappers add overhead; use separate uninstrumented trials for before/after latency.',
                'The disabled H-K phase measures its no-op flag check and wrapper overhead, not repair arithmetic.',
            ])
        return values, report


def run(stacks, operation, rgb, chunk=65536, expected=None):
    """Convenience entry point for a fresh exclusive CPU phase profile."""
    return PhaseProfile().run(stacks, operation, rgb, chunk, expected)
