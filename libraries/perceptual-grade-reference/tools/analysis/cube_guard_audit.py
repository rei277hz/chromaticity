"""Audit and time the adopted actual-cube guard on production 65³ samples."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from color_tools.perceptual_grade_core.model import lut as production_lut
from color_tools.perceptual_grade_core.model.bake import Kernel
from color_tools.perceptual_grade_reference.cube_guard import guard
from color_tools.perceptual_grade_reference.grading import ColorSettings, ToneSettings
from color_tools.perceptual_grade_reference.model import Model, Settings


def inside(rgb):
    return np.isfinite(rgb).all(axis=-1) & np.all((rgb >= 0) & (rgb <= 1024), axis=-1)


def counts(state, direct, safe, kernel):
    energy = state[:, 3]
    c = np.hypot(state[:, 1], state[:, 2])
    capacity = kernel.capacity(energy, state[:, 1:3])
    ratio = np.divide(c, capacity, out=np.full_like(c, np.inf), where=capacity > 0)
    edges = (0, .4, .8, 1., 1.2, 2., np.inf)
    positive = (energy > 0) & (energy < kernel.white**2)
    bins = []
    for low, high in zip(edges[:-1], edges[1:]):
        subset = positive & (ratio >= low) & (ratio < high)
        bins.append(dict(relative_capacity=[low, high if np.isfinite(high) else None], vertices=int(subset.sum()),
                         directly_inside=int((subset & safe).sum())))
    return dict(input_vertices=len(state), interior=int(positive.sum()),
                outside_appearance_energy=int((~positive).sum()),
                direct_inside=int(safe.sum()), direct_cube_escapes=int((positive & ~safe).sum()),
                direct_response_poles=int((positive & ~np.isfinite(direct).all(axis=-1)).sum()),
                direct_below_zero=int((positive & np.any(direct < 0, axis=-1)).sum()),
                direct_above_1024=int((positive & np.any(direct > 1024, axis=-1)).sum()),
                chroma_over_capacity=bins)


def audit(name, settings, lattice, data, repeats, reference_sample):
    model = Model(settings, space='ACEScg', hk_guard=False)
    kernel = Kernel(data, model.tone, model.color)
    # The LUT's native lattice itself is the production input. Use its
    # appearance state exactly as the bake does, avoiding model-space adapter
    # ambiguity while retaining the full 65³ population.
    state = kernel.grade(kernel.tone_state(kernel.enter(lattice)))
    direct = kernel.decode(state)
    legal = inside(direct)
    record = dict(name=name, histogram=counts(state, direct, legal, kernel))
    timings = []
    for _ in range(repeats):
        start = perf_counter()
        result = kernel.export(state)
        timings.append(1000*(perf_counter()-start))
    record['float32_export_ms'] = dict(median=float(np.median(timings)), samples=timings)
    record['float32_after'] = dict(escaped=int((~inside(result)).sum()),
                                   valid_rgb_changed=int(np.count_nonzero(np.any(result[legal] != direct[legal], axis=-1))),
                                   max_chroma=float(np.max(np.hypot(state[:, 1], state[:, 2]))))

    # Independent reference guard timing is measured on a fixed stratified
    # subset. Float64 geometry is substantially more expensive than a bake.
    ids = np.linspace(0, len(lattice)-1, reference_sample, dtype=int)
    reference = model.grade_state(model.enter_native(lattice[ids].astype(float)))
    start = perf_counter()
    _, _, decoded = guard(model.boundary, reference.q, reference.energy)
    record['float64_guard_subset'] = dict(vertices=len(ids), milliseconds=1000*(perf_counter()-start),
                                           escaped=int((~inside(decoded)).sum()))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--reference-sample', type=int, default=2048)
    args = parser.parse_args()
    if args.repeats <= 0 or args.reference_sample <= 0:
        parser.error('Sample and repeat counts must be positive')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with np.load(args.candidate, allow_pickle=False) as archive:
        data = dict(archive)
    if int(data['format']) != 16 or production_lut.SIZE != 65 or production_lut.KAPPA != .01:
        raise ValueError('Audit requires the active format-16 resource and production 65³ shaper')
    lattice = production_lut.lattice().astype('f4')
    if len(lattice) != 65**3 or not np.all((lattice >= 0) & (lattice <= 1024)):
        raise ValueError('Unexpected production cube lattice')
    cases = (
        ('tone', Settings(tone=ToneSettings(input_nits=(0, 7, 45, 203, 1000)))),
        ('global_gain_1', Settings(color=ColorSettings(global_gain=1.))),
        ('global_gain_3', Settings(color=ColorSettings(global_gain=3.))),
    )
    report = dict(scope='Full 65³ production shaper, actual decoded AP1 [0,1024]³ guard',
                  resource_format=16, vertices=len(lattice), cases=[])
    for name, settings in cases:
        item = audit(name, settings, lattice, data, args.repeats, args.reference_sample)
        report['cases'].append(item)
        print(json.dumps(item), flush=True)
    report['pass'] = all(item['float32_after']['escaped'] == 0 and
                         item['float32_after']['valid_rgb_changed'] == 0 and
                         item['float64_guard_subset']['escaped'] == 0 for item in report['cases'])
    (args.output_dir/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    if not report['pass']:
        raise SystemExit('Validated cube guard audit failed')


if __name__ == '__main__':
    main()
