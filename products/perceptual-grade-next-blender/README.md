# Perceptual Grade for Blender

This step adds Grade and Grade Stack nodes to the Shader and Compositor Color Add
menus. Grade nodes apply Stage 1 and Tone through the product's `kernel` package;
Stack nodes apply ordered, forward-only Stage 1 and Tone Grades through progressive
33³/65³ GPU LUTs. Both products use shared Grade datablocks and the same Grade controls.
Create or select a Grade using the node's datablock selector before adjusting it.
Without a Grade, Linear and Tone controls are disabled and local setting writes reset
to neutral without creating a datablock.

A private asyncio loop owns the preparation schedulers. Each shared
Grade has one active preparation and one replaceable latest settings snapshot;
rapid edits do not enqueue a history of slider positions. Linear, Tone-table, and
boundary preparation run concurrently from one frozen Grade snapshot and join
before a complete prepared result can publish. Shader and Compositor share that
result, while Blender's main thread owns their separate kernel graphs and per-node
policy state.
The loop starts the newest successor as soon as active preparation finishes,
without waiting for Blender's publication timer.

A Grade builds its complete Linear/Tone graph once per working space and tree
type. Ordinary adjustments publish a complete 512 × 1 RGBA32F parameter image
(8 KiB), shared by every Shader and Compositor node using that Grade. Published
images remain immutable while native readers may use them. Each Grade and working
space owns at most three versions: its current image, retained published images,
and an unpublished candidate. When the pool is full, preparation keeps only the
newest CPU result until a version can retire safely. Equal-valued independent
Grades have separate pools.

Slots 0–256 contain the Tone endpoint value, slope, and curvature; slots 257–259
contain the Linear matrix's red/blue columns and neutral row sums; slots 260–261
contain the Tone scalars and domain. Fixed texture samples read these values
instead of baking them into socket defaults. The boundary texture, viewing
constants, links, and output adapter remain fixed within a working space.
Publication packs a complete candidate before rebinding every marked parameter
reader. A failed transaction restores bindings and metadata without rewriting the
previous image. File-load reconciliation checks the installed signature, reader
markers, and kernel schema before accepting restored data.

Compositor Grade graphs support both GPU Auto and Full precision without changing
the scene setting. The output guard carries signed achromatic lightness and a
bounded normalized distance to white, avoiding large squared-energy intermediates
that can clip in Auto's half-precision preview buffers. CPU and GPU Full retain
the existing full-precision accuracy gates; Auto previews allow half-precision
rounding.

Foreground publications coalesce to the newest complete result per source and
process one source per timer turn, with no preview frequency cap or settle delay.
Render, bake, and interface locks defer ordinary publication. During one observed
compositor evaluation, a complete new image can be bound while the evaluated tree
retains the previous image. After that supersession, another live swap waits for a
successful newer evaluation of the same scene. Cancellation or completion of a
different scene cannot release this protection. Quiescent publication remains
available while a successor is pending. Old versions retire when native user
counts permit removal and readers are quiescent, including inside an exclusive
render preflight whose worker is parked before evaluation.

Blender's public job notifications provide admission checks, not a universal lock
against native image readers. A render worker waits at its pre-evaluation callback
while a foreground timer performs exact reconciliation; synchronous main-thread
renders use the same scoped preflight directly. Kernel readiness and Viewer
completion are separate: a newly bound kernel can be current while the display
still carries an updating indication until its evaluation completes.

Stack LUT preparation runs in a private Blender GPU helper. Each helper job
dispatches its 33³ preview and 65³ refinement back-to-back, with a private output
texture per quality. A continuous pointer drag can install the matching preview
while the helper continues; at most one latest Stack snapshot waits behind active
work. Direct value entry requests only the final 65³ cube. The main thread polls
helper receipts asynchronously, so GPU dispatch and texture readback do not block
Blender's UI thread. A matching 33³ result remains marked as a preview until the
full cube installs.

A complete previous result can remain visible with an amber `Updating` indication.
Only the exact current kernel is ready for rendering. Render reconciliation joins
preparations asynchronously, then installs and validates kernels on the main thread;
preparation never waits for graph installation. Current failures produce a visible
error and magenta output with alpha preserved. File load, working-space changes,
and Grade reassignment fence obsolete source subscriptions and reconcile kernels.
Shutdown withdraws pending demand and waits for active physical work to retire.

To diagnose slider dragging, use **F3 → Perceptual Grade: Start Drag Trace**.
Shift-drag a Grade slider in Shading, release and let it settle, then repeat in
Compositing with Viewer Node visible in an Image Editor. Use
**F3 → Perceptual Grade: Stop Drag Trace** after the second drag settles.
Both commands are also available in the **Help** menu and report the absolute
log path. Files are saved under
`~/perceptual-grade-drag-logs/`. Send the resulting `.jsonl` file for analysis.

Tracing is off by default. One capture records both workspaces, native gesture
receipts, authoritative property callbacks (including suppressed callbacks),
preparation and publication decisions, compositor completion/cancellation, and
main-thread heartbeat and draw activity. The header identifies the installed
sources and Blender/GPU environment. A background writer flushes every 250 ms;
the footer reports dropped events or recording errors. Logging does not read
image pixels, so draw callbacks indicate redraw activity rather than proof of
changed display pixels. Stop removes the diagnostic observers and closes the
file; disabling the extension also closes an active capture.

The native regression pauses a real compositor worker, publishes while the old
snapshot remains leased, verifies the old parameter bytes stay unchanged, and
requires a protected successor to complete. The drag regression exercises
Exposure, CR Balance, and Tone Fit at a requested 277 Hz in both editors, using
bounded motion that avoids slider endpoints:

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:versioned_publication_gui //products/perceptual-grade-next-blender/tests:drag_trace_gui
```

For an opt-in 2000 × 1500 fixture, pass `-- --env PG_VERSIONED_PUBLICATION_LARGE=1`
or `-- --env PG_DRAG_TRACE_LARGE=1` to the respective test command. The default native
fixtures are 128 × 96. The large drag fixture uses GPU Full precision and ten-second Compositor holds. Viewer pixels are read only after evaluation completes in
the versioned regression; drag traces record completions without pixel readback.
Linux software-GPU results do not establish behavior on macOS Metal; repeat the
continuous-drag acceptance run in the user's Blender environment.

The file-load regression reopens a saved file before real sidebar drags in
Material Preview, EEVEE Rendered, and Compositor. It checks that gesture observers
recover, complete lagging preparations publish during dragging, and release
converges to the final settings. It also covers deferred load recovery and
extension disable/re-enable. These checks validate gesture tracking and parameter
publication; they do not measure when changed pixels reach the display.

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:gesture_reload_gui
```

Measure Grade preparation, texture upload, and node-tree construction with:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:grade_preparation_timing -- --output-dir /tmp/perceptual-grade-preparation
```

Measure installed Grade publications during continuous changes in a Shading
workspace with a sidebar and rendered viewport:

```sh
buck2 run --remote-only //products/perceptual-grade-next-blender/tools/reports:grade_update_timing -- --output-dir /tmp/perceptual-grade-updates --stage both
```

This report records preparation, publication, UI heartbeat, and viewport draw
rates, plus resource identity checks and final settling. It has no performance
gate. Uploads exceeding 60/s do not by themselves establish visible 60 fps; the
report distinguishes these measurements. The bundled Linux display fixture
uses Mesa llvmpipe, so its GPU work executes on CPU cores.

Use `--viewport solid` to isolate publication and UI work from the rendered
viewport, and `--verify-render-preflight` to additionally invoke a native GUI
render with a pending adjustment. The latter is also a regression test:

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:grade_render_preflight
```

Measure actual Shader slider updates against captured viewport pixels with:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:shader_display_timing -- --output-dir /tmp/pg-shader-display --baseline products/perceptual-grade-next-blender/docs/performance/shader-display-baseline.json
```

This on-demand benchmark drives the Exposure and Tone Fit sidebar widgets and
matches graded swatches in an external X11 capture. It records five fresh Blender
sessions, 100 isolated updates per control per session, and continuous drags.
The [measurement contract](docs/performance/shader-display.md) explains timing
uncertainty, required environment compatibility, and how to update the baseline.
Rerun it before changes that can affect Shader updates. Timing regressions warn;
incorrect or incomplete pixel observations fail the measurement.

Measure comparable Compositor dragging against the live Viewer display with:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:compositor_display_timing -- --output-dir /tmp/pg-compositor-display --baseline products/perceptual-grade-next-blender/docs/performance/compositor-display-baseline.json
```

This drag-only baseline uses a 438 × 841 image, GPU/AUTO Compositor, and the
same controls and timing definitions. Its [measurement contract](docs/performance/compositor-display.md)
describes the workload and the separate Compositor baseline.

Check interactive compositor pixels and automatic refresh on the installed
extension with:

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:compositor_gui
```

This test uses a varying image and the live Viewer; final renders alone do not
exercise Auto's half-precision path. It checks CPU, GPU Full, and GPU Auto,
including signed/HDR colors and alpha. Auto uses the pixel-normalized error
`max(abs(actual - expected)) / (1 + max(abs(expected)))` with a 0.01 limit.

Measure continuous Stack Tone LUT publication with:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:stack_lut_timing -- --output-dir /tmp/perceptual-grade-stack-timing
```

The extension ZIP uses `src/__init__.py` directly as its root entrypoint and
places the product's `nodes.py` beside it. Product-owned state-machine policies
are packaged under `policy/`; shared library dependencies remain separate
root-level packages in the archive.

Build the package and run the installed smoke test with:

```sh
buck2 build //products/perceptual-grade-next-blender:extension
buck2 test //products/perceptual-grade-next-blender/tests: --remote-only
buck2 run //products/perceptual-grade-next-blender:install_workspace
```
