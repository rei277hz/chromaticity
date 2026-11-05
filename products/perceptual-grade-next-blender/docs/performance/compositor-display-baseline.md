# Installed Compositor Grade display timing

This report measures accepted Grade slider settings until the first matching live Viewer pixels in Blender's Image Editor are captured. It is a separate workload from the Shader viewport benchmark.

Session aggregates are medians of process-level p50, p95, and maximum values. p50 uses the median and p95 uses the nearest rank; raw observations remain in JSON.

Valid observations: `True`.

| Control | Displayed / accepted | Accepted p50 / p95 (ms) | Injected p50 / p95 (ms) | Displayed gap p50 / p95 (ms) | Accepted / displayed / superseded per second | Displayed / superseded (%) |
|---|---:|---:|---:|---:|---:|---:|
| exposure | 113 / 125 | 193.697 / 216.971 | 255.065 / 272.221 | 126.215 / 258.246 | 8.09 / 6.71 / 0.94 | 88.46 / 11.54 |
| fit | 114 / 123 | 198.491 / 211.743 | 257.141 / 272.778 | 131.176 / 203.108 | 7.88 / 6.76 / 0.63 | 92.31 / 7.69 |

Final settling after native drag release:

| Control | Release to capture p50 (ms) | p95 (ms) | Median session max (ms) | Absolute max (ms) |
|---|---:|---:|---:|---:|
| exposure | 195.390 | 195.390 | 195.390 | 235.762 |
| fit | 183.485 | 183.485 | 183.485 | 198.705 |

Captured 9182 X11 samples; per-capture duration p50 / p95 / max: 0.386 / 0.716 / 1.610 ms; within-request cadence gap p50 / p95: 5.508 / 5.879 ms.

Observer cadence diagnostic:

| Control | Mode | Sessions | Injected motions | Draws | Injected / s | Draws / s |
|---|---|---:|---:|---:|---:|---:|
| exposure | observer_on | 5 | 125 | 169 | 8.09 | 11.00 |
| exposure | observer_off | 5 | 125 | 171 | 7.91 | 10.76 |
| fit | observer_on | 5 | 123 | 162 | 7.88 | 10.68 |
| fit | observer_off | 5 | 126 | 176 | 8.04 | 11.37 |

Capture completion is an upper observed latency that includes X11 readback and sampling delay; it does not establish physical monitor scanout. Comparisons require identical environment and Compositor profile, including measurement-harness hashes. Product hashes identify the measured subject. Only drag observations for both exposure and Fit are accepted by this report. Each pixel witness requires a logged, completed Compositor evaluation of those accepted settings with current Grade output allowed before capture starts. Timing warnings require changes beyond baseline session variation and capture uncertainty; they do not establish statistical confidence. Missing or mismatched final pixels invalidate the run, while superseded intermediate updates are retained.
