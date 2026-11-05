# Shader slider display baseline

The baseline measures the installed Shader Grade in Blender's rendered Eevee
viewport on the pinned Linux Xvfb/Mesa llvmpipe fixture. Exposure and Tone Fit
exercise the Linear and Tone update paths. llvmpipe executes GPU work on the CPU;
this baseline applies to that environment.

## Run and compare

Use an idle machine and run no other Blender or numerical workloads concurrently:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:shader_display_timing -- --output-dir /tmp/pg-shader-display --baseline products/perceptual-grade-next-blender/docs/performance/shader-display-baseline.json
```

Use a fresh output directory. Each of five fresh Blender processes performs 100
isolated edits per control and a three-second drag per control. The requested
drag input interval is 50 ms; the requested capture interval is 5 ms. The report
preserves actual injection times, capture intervals, raw settings, and logs.
A shorter integration check is available as:

```sh
buck2 test //products/perceptual-grade-next-blender/tests:shader_display_native
```

## What the clock measures

The primary clock starts when the actual sidebar widget's new RNA value reaches
the Grade callback and ends when an external X11 capture first contains the
matching graded swatch palette. Event-injection-to-capture time is reported
separately. Input comes through Blender's native simulated events; timer delays
are recorded and skipped input deadlines do not produce catch-up bursts. One
native motion must be accepted before injecting the next. The achieved rate can
therefore fall below the requested 20 Hz when Blender's event loop is busy.

The fixture uses fixed emission swatches, display settings, viewport size, and
sampling. Expected display colors come from the independent reference outside
measured intervals. Calibration verifies that the mouse recipes actually change
the intended controls and produce distinguishable palettes. A match requires
all four swatches; stale or ambiguous colors do not complete an edit.

Pixels identify settings values. Consecutive isolated edits must have distinct
palettes, and observations must follow value acceptance. The benchmark waits for
each isolated target's matching capture before advancing. During a drag it
retains every accepted callback, including values superseded before display,
and observes the final value after release. The fixed workload alternates two
calibrated endpoints; only an observed palette transition counts as another
displayed update. A separate final endpoint makes final progress distinguishable.

Each X11 capture has start and completion timestamps. Completion gives an upper
observed latency that includes readback and sampling delay. The report retains
capture duration, achieved cadence, and observer-on/off activity checks. Window
pixels establish neither physical monitor scanout nor one displayed frame per
texture upload. Initialization and warmup are excluded from steady edit timings.
The capture-disabled repeat also disables acceptance snapshots, while retaining
the draw counter. Its cadence comparison estimates observation cost, with actual
input and draw counts reported for each repeat.

## Interpret and maintain the baseline

Read `report.md` for each control's isolated and drag p50/p95 and final settling;
`report.json` retains the individual sessions and samples. Session aggregates
are medians of session statistics, with nearest-rank p95. Supersession and gaps
between displayed updates describe drag responsiveness alongside latency.

Comparisons require matching CPU/affinity, OS, Blender/GPU/driver identities,
and workload settings. Measurement code hashes are part of the profile; changing
the benchmark requires a new baseline. The extension hash identifies the measured
subject and may differ between candidate and baseline. An environment mismatch is
reported as incomparable. Timing increases warn only when they exceed baseline
session variation and recorded capture uncertainty; every signed change remains
available for review. These warnings are descriptive, without a statistical
confidence claim. Invalid pixel evidence or missing isolated/final targets fails
the measurement, preserving its partial report and logs.

The frozen baseline is [shader-display-baseline.json](shader-display-baseline.json),
with its measured table in [shader-display-baseline.md](shader-display-baseline.md).
Rerun the full command before Shader-affecting changes. To intentionally replace
the baseline, run without `--baseline`, review all five valid sessions and the
environment, then explicitly copy the new JSON and Markdown reports into those
files. Baselines are never replaced automatically. Keep the full session logs
and capture traces with the run artifacts; bulky captures are not tracked.

The tracked JSON is minified and keeps every sample, native event, calibrated
setting, and matching RGB witness. Capture timelines retain every start/end
timestamp and request identifier; redundant colors from unmatched captures stay
in the full run artifacts. This storage reduction preserves all summary and
comparison values exactly. The baseline records the original report's SHA-256.
