# Shader display baseline — 2026-11-05

Measured on AMD EPYC 7763, Blender 5.2.2 LTS (`d13f752e3b9c`), OpenGL/Mesa llvmpipe 25.0.7. Five fresh sessions; 100 isolated edits per control per session.

Frozen data: [shader-display-baseline.json](shader-display-baseline.json). [Run and comparison instructions](shader-display.md). The JSON preserves every edit, full matching pixel witnesses, and all capture timestamps. Full color traces and logs: `/tmp/pg-shader-display-baseline-20261105`.

Latency runs from accepted slider settings to completion of the first matching viewport framebuffer capture. Native event injection is reported separately.

Session aggregates are medians of process-level p50, p95, and maximum values; p50 uses the median and p95 uses the nearest rank. Raw samples remain in JSON.

Valid observations: `True`.

| Control | Scenario | Displayed / accepted | Accepted p50 (ms) | Accepted p95 (ms) | Median session max (ms) | Absolute max (ms) | Injected p50 (ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| exposure | isolated | 500 / 500 | 212.149 | 228.361 | 233.199 | 244.670 | 212.392 |
| exposure | drag | 78 / 78 | 226.369 | 241.854 | 241.854 | 249.150 | 343.712 |
| fit | isolated | 500 / 500 | 217.397 | 237.744 | 283.585 | 287.545 | 217.652 |
| fit | drag | 79 / 79 | 221.666 | 231.196 | 231.196 | 239.817 | 339.172 |

| Control | Scenario | Displayed update gap p50 / p95 (ms) | Accepted / displayed / superseded per second | Displayed / superseded (%) |
|---|---|---:|---:|---:|
| exposure | isolated | 262.068 / 284.550 | — | — |
| exposure | drag | 224.916 / 270.867 | 4.72 / 4.40 / 0.00 | 100.00 / 0.00 |
| fit | isolated | 266.030 / 297.940 | — | — |
| fit | drag | 221.442 / 245.452 | 4.83 / 4.53 / 0.00 | 100.00 / 0.00 |

exposure release to final capture p50 / p95: 213.872 / 213.872 ms.

fit release to final capture p50 / p95: 221.433 / 221.433 ms.

Captured 57687 X11 samples; capture duration p50 / p95 / max: 0.513 / 0.789 / 3.943 ms; within-request cadence gap p50 / p95: 5.657 / 5.969 ms.

Observer cadence diagnostic (draw rate is viewport draw callbacks per second):

| Control | Mode | Sessions | Injected motions | Draws | Injected / s | Draws / s |
|---|---|---:|---:|---:|---:|---:|
| exposure | observer_on | 5 | 78 | 151 | 4.72 | 9.12 |
| exposure | observer_off | 5 | 80 | 155 | 4.85 | 9.41 |
| fit | observer_on | 5 | 79 | 153 | 4.83 | 9.35 |
| fit | observer_off | 5 | 80 | 155 | 5.07 | 9.83 |

Captures bound observation time and include readback overhead. They do not measure physical monitor presentation. Superseded drag updates are counted, and missing isolated updates or a missing final drag display invalidate the run.

Performance comparisons require equal environment and profile values. Source and package hashes are provenance; measurement-harness identity is part of the profile. A warning requires an increase greater than both the baseline session spread and the sum of the two runs' p95 capture gaps. Drag rates use the active interval up to release; displayed rates exclude later captures, while displayed fractions include final observations. Rate warnings convert capture cadence to the metric's units and allow one update of quantization. Warnings do not fail correctness or establish population confidence.
