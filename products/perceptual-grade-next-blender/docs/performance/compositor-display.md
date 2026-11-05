# Compositor slider display baseline

This benchmark measures the installed Compositor Grade through the live Viewer
image displayed in Blender's Image Editor. It uses the Shader baseline's Exposure
and Tone Fit widgets, source colors, Tone anchors, native slider recipes, and
latency/update-frequency definitions. The evaluation image is **438 × 841**,
matching the recorded Shader viewport region. The Shader fixture shades a plane
inside that region; the two contexts have different rendering work.

## Run and compare

On an idle machine, with no concurrent Blender or numerical workloads, run:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:compositor_display_timing -- --output-dir /tmp/pg-compositor-display --baseline products/perceptual-grade-next-blender/docs/performance/compositor-display-baseline.json
```

Use a fresh output directory. Five fresh Blender processes each drag both
controls for three seconds, then repeat with observation disabled. Requested
input spacing is 50 ms and external X11 capture spacing is 5 ms. The actual
intervals and accepted values are retained. This is a drag-only benchmark;
the existing Shader baseline also contains isolated edits.

The shorter native integration check is:

```sh
buck2 test //products/perceptual-grade-next-blender/tests:compositor_display_native
```

## Measurement contract

The main clock starts on entry to the actual Grade property callback and ends
when an external capture first contains all four independently calculated
graded swatches. Event injection to capture is also reported. The source is a
full-size floating-point image of four broad vertical stripes feeding the
installed Grade into a live Viewer, with the GPU Compositor and AUTO precision.
The display uses Standard/sRGB, with fixed view settings and no dithering.

Inputs use Blender's native simulated events on the production sidebar. A held
slider alternates two calibrated endpoints and ends on a third distinct value.
The next motion waits only for acceptance, allowing updates to supersede each
other. Missed deadlines skip catch-up bursts. Calibration and independent
reference calculations happen outside measured intervals.

Only observed palette transitions count as displayed updates. Every accepted
callback remains in the report, including superseded values. The final value
must receive a matching capture after release. Compositor evaluation receipts
tie matching pixels to settings evaluated after the acceptance; canceled
evaluations cannot supply a completion witness. The benchmark observes native
refresh, without issuing renders or manually publishing replacement previews.

Reports include accepted and displayed updates per second, displayed/superseded
fractions, p50/p95 latency, gaps between displayed updates, release-to-final
settling, and observer-on/off input and Image Editor draw cadence. The displayed
rate uses the active drag interval up to release; the displayed fraction also
includes final observations after release. Capture completion includes sampling
delay and X11 readback and does not establish physical monitor scanout.

The measured drag results are comparable at the input and capture-contract
level, while the Shader and Compositor workloads remain different:

| Control | Context | Accepted-to-display p50 / p95 (ms) | Displayed updates/s |
|---|---|---:|---:|
| Exposure | Shader viewport | 226.369 / 241.854 | 4.40 |
| Exposure | Compositor Viewer | 193.697 / 216.971 | 6.71 |
| Tone Fit | Shader viewport | 221.666 / 231.196 | 4.53 |
| Tone Fit | Compositor Viewer | 198.491 / 211.743 | 6.76 |

These numbers are from separate five-session Mesa llvmpipe baselines. The
Compositor row evaluates a 438 × 841 floating-point image through the live
Viewer; the Shader row renders the same swatches in a 438 × 841 viewport region.
Captured pixels include X11 sampling overhead, so the table establishes a
repeatable relative baseline rather than physical display-scanout time.

## Baseline maintenance

The [frozen JSON](compositor-display-baseline.json) retains each edit, matching
RGB witnesses, evaluation receipts, and capture timestamps. The
[measured table](compositor-display-baseline.md) records results and the Shader
drag figures side by side. Both were measured on Linux/Xvfb/Mesa llvmpipe, which
executes GPU work on CPU cores; these figures do not measure Mac/Metal performance.

Future Compositor comparisons require identical environments and workload
profiles, including image dimensions, device/precision, display geometry, and
measurement code hashes. Differences between Shader and Compositor profiles
are intentional, so the automated regression comparator rejects cross-context
reports. Keep the Shader baseline and its measurement sources frozen.

Timing warnings are descriptive: they require changes beyond session variation
and capture uncertainty. Invalid pixel evidence or a missing final target fails
the run and preserves partial evidence. To replace this baseline deliberately,
run without `--baseline`, review all five sessions, then copy the reports into
the tracked baseline files. Preserve full color traces and logs as run artifacts;
the tracked JSON may omit redundant colors from unmatched capture rows while
retaining every capture timestamp and matching witness.
