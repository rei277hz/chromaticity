# Perceptual Grade 1.14.1: inverse baking performance

The ordinary 65³ inverse test now takes **4.11–4.60 seconds** across the three repeated benchmark bakes and the separate precision run. The tested three-grade Forward A → Inverse B → Forward C Stack takes **4.61–5.23 seconds**. Thus the ordinary case meets the five-second goal on this machine; the mixed Stack remains near the threshold and is not reliably below it. These are numerical bake times, not end-to-end UI latency or a guarantee for every grade, CPU or Stack length.

## Reproducible measurements

The extension uses Python source and Blender's bundled NumPy. No platform binary, compiler, SciPy runtime dependency or external precompiled package was added. The test environment uses CPython 3.13.6, NumPy 2.5.3, and one OpenBLAS/OMP thread. No other project test/benchmark was running during the three-repeat measurements. Shared-host load outside this task is uncontrolled.

Each run constructs a new immutable model and computes all 274,625 vertices, including final float32 storage. It does not reuse a completed LUT. Imports/process startup, the 250 ms edit debounce, Blender packed-image publication and render preparation are excluded. Coefficient and lattice caches may be warm between repetitions. All inverse residuals evaluate the full analytic float64 forward equations; no intermediate 3D LUT or Quintic table is queried. Grid size, signed [-64,64] domain, tetrahedral runtime sampling and solver iteration budgets are unchanged.

| Case | Repeat 1 | Repeat 2 | Repeat 3 | Median | Separate precision run |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordinary nonlinear inverse | 4.160 s | 4.107 s | 4.203 s | 4.160 s | 4.600 s |
| Three-grade mixed Stack | 4.998 s | 4.955 s | 4.614 s | 4.955 s | 5.230 s |
| Three-grade forward Stack | 0.929 s | 0.943 s | 0.948 s | 0.943 s | 1.274 s |

Complete Grade settings, runtime versions, raw times and diagnostics are in `inverse-bake-performance.json`. The precision presets and seed are the same as version 1.14.0.

## Why the old solver was expensive

The earlier worker solved each small block independently. Most vertices converged quickly, but every block still paid Python/NumPy dispatch costs for its few difficult vertices. Returning to the main-thread timer between blocks added another scheduling cost. The numerical method also rebuilt a finite-difference Jacobian repeatedly, requiring several complete forward evaluations per active vertex per iteration. Scalar Tone/guard bisections and repeated coefficient/neutral-offset work amplified that cost.

Historical 1.14.0 workload measurements were 247.79 s for the ordinary inverse and 198.78 s for the mixed Stack. Other validation shared the host during those measurements, so these are not controlled speedup ratios. In this optimization session, putting the unchanged inverse equations into one full vertex pool took 21.83 s, with the original 122 approximate ordinary-inverse vertices. Pooling alone was useful but insufficient for five seconds.

## What changed

1. **One unresolved pool.** All vertices enter the inverse together. Converged rows leave the active array; difficult rows from across the grid share the remaining work. The two recovery seeds are also evaluated together. Forward evaluations may use 32,768-row cache tiles inside that solve; tile boundaries do not restart inverse iteration.
2. **Safeguarded scalar Newton.** Tone and fixed-reference H–K inverses use analytic scalar derivatives and retain valid brackets. Out-of-bracket steps use the midpoint; unfinished rows still have bisection safeguards.
3. **Damped Broyden.** Finite differences initialize the Jacobian; accepted steps update it using their measured input/residual changes. Rejections and periodic refreshes recover a measured Jacobian. The full forward residual still decides acceptance. Coordinate scaling uses each target's RGB magnitude, improving the signed/HDR solve compared with the former asinh coordinates.
4. **Less repeated forward work.** Equal coefficient weights are shared, only required stable softplus branches are evaluated, and invalid-row fallback work is lazy. On the neutral offset ray used by signed lifting, Hue/Concentration and J/C contributions vanish; only Tone and Adaptance need evaluation before the unchanged guard/decoder. The guard and decoder share repeated radius/energy calculations. The independent reference implementations remain available for parity tests.
5. **A continuous cancellable worker job.** The worker finishes the pool without timer round trips. Edits cancel obsolete work at numerical checkpoints. Blender publication remains on the main thread and checks the current signature. The last finished cube stays visible while its replacement is pending.

The forward/inverse equations, scalar derivatives, rank-one update, damping and exact candidate-priority policy are specified in section 18 of [the full forward/inverse handbook chapter](../book/src/development/forward-inverse-math.md). The branch-selection algorithm is deterministic but can select a different valid preimage from the old solver; it is not an exhaustive inverse or a guarantee of continuity across folds.

## Accuracy and rejected shortcuts

| Measure | 1.14.0 | 1.14.1 |
| --- | ---: | ---: |
| Ordinary inverse approximate vertices / 274,625 | 122 | 88 |
| Ordinary inverse worst normalized reproduction residual | 0.0473517 | 0.0482578 |
| Mixed Stack approximate inverse vertices / 274,625 | 100 | 78 |
| Mixed Stack worst normalized reproduction residual | 0.217034 | 0.0383937 |

An approximate vertex has forward reproduction residual above 2e-8 before final storage. Fewer such vertices does not imply every error improved: the ordinary worst residual is slightly higher. Photographic inverse and Stack LUT errors are unchanged at the precision displayed in the companion report. The analytic photographic maximum is 3.28e-8, while its p99 is at most 2.25e-11. Extreme signed colors and extrapolated inputs still have substantial LUT errors; the speed work does not solve that sampling/branch problem.

No solver iteration-budget reduction was shipped. Reducing regular/RGB budgets from 24/30 to 16/18 gave 5.43 s before the final forward optimizations but raised approximate vertices to 123; 12/12 gave 5.63 s and 407 approximate vertices. Other rejected prototypes included coarse 17³ inverse initializers (roughly 7–11 s), extra Python worker threads (about 10–12 s at that stage), and unguarded or column-rescaled Newton variants (about 11–14 s with worse residual counts). These timings describe exploratory implementations, not directly controlled comparisons with the final code.

## Validation and limits

The 52-fixture numerical/Blender/render/DCTL/parity suite passed. The final neutral-offset/fused-decode optimizations were followed by successful focused reruns of the inverse solver, inverse math and native Grade Stack fixtures. The solver fixture now has 24 checks, including optimized-versus-independent forward/neutral/guard parity, narrow Tone intervals, derivative checks, whole-lattice scheduling and cancellation. Native CPU rendering agrees with the matching cube/matrix evaluator within 1.95e-7 normalized RGB on the tested scenes.

Whole-lattice solving uses larger arrays than small batches. Grades with severe folds, more inverse entries or different CPUs can take longer; neither the worker nor the solver imposes a time cutoff. Cancellation is cooperative, so it cannot interrupt a single NumPy operation already running. Blender UI/image publication time is not measured here. GPU/Metal and desktop interaction were not exercised. Runs use the explicit authoring-preview environment; the unavailable Buck2 release gate is not claimed.

## Reproduce

Run `tests/blender/benchmark_inverse.py --repeats 3` in the prepared environment described in the handbook, with `PG_AUTHORING_PREVIEW=1`. It writes `tests/blender/reports/inverse-bake-performance.json`. Run `evaluate_inverse_precision.py` separately for photographic and signed/HDR off-grid errors; it caches signature-keyed finished cubes and therefore is not the repeated timing benchmark. Keep other project workloads idle when comparing timings.
