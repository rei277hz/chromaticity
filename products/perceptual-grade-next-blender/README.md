# Perceptual Grade for Blender

This step adds Grade and Grade Stack nodes to the Shader and Compositor Color Add
menus. Regular Grade nodes apply Stage 1 and Tone through the product's `kernel`
package; Grade Stack nodes apply ordered, forward-only Stage 1 and Tone Grades through
progressive 33³/65³ GPU LUTs. Both remain static and use shared Grade datablocks.
The Add menus provide one Grade entry. Right-click a Grade node and choose
**Convert to Node-Owned Grade** to give it independent settings and numeric keyframes
in Blender's native animation editors. All variants use the same Grade controls and preparation
model. Regular Grade controls remain disabled until a Grade datablock is selected.

The [Perceptual Grade handbook](../perceptual-grade-book/README.md) follows the
latest mathematical reference in English and Simplified Chinese, with HTML,
PDF, and EPUB editions. Some usage chapters still describe preserved 1.23.2
behavior; their scope is identified. Next has not yet implemented the Warp UI.
Its future Warp implementation must follow the reference's Adaptance → H–K
repair → common positive Scale order.

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
type. Ordinary adjustments publish complete 512 × 1 RGBA32F parameter data
(8 KiB) through two fixed helper images shared by every Shader and Compositor
node using that Grade. The inactive bank is packed and checked inside an admitted
publication scope; only then does the selector switch to it. Bank identities
stay fixed across edits, so publication does not allocate a version pool or rebind
image readers. Equal-valued independent Grades own separate bank pairs.

Slots 0–256 contain the Tone endpoint value, slope, and curvature; slots 257–259
contain the Linear matrix's red/blue columns and neutral row sums; slots 260–261
contain the Tone scalars and domain. Fixed texture samples read these values
instead of baking them into socket defaults. The boundary texture, viewing
constants, links, and output adapter remain fixed within a working space.
Publication packs a complete inactive bank before changing the marked selector.
A failed transaction restores the previous selector and metadata; any failure to
restore or deliver closes the Grade output visibly. File-load reconciliation
checks both bank bindings, reader markers, selector agreement, and kernel schema
before accepting restored data. If the active bank fails its content receipt,
recovery first revokes the Grade output and proceeds to rewrite both banks only
after the fail-closed receipt succeeds.

Compositor Grade graphs support both GPU Auto and Full precision without changing
the scene setting. The output guard carries signed achromatic lightness and a
bounded normalized distance to white, avoiding large squared-energy intermediates
that can clip in Auto's half-precision preview buffers. CPU and GPU Full retain
the existing full-precision accuracy gates; Auto previews allow half-precision
rounding.

Foreground publications coalesce to the newest complete result per source and
process one source per timer turn, with no preview frequency cap or settle delay.
Render, bake, interface locks, and active compositor evaluation defer ordinary
bank writes. Publication is admitted when native evaluation is quiescent or
inside an exclusive render preflight with its worker parked before evaluation.
The newest prepared result can then replace the inactive bank and switch the
selector. The bank policy requires this admission receipt before it authorizes
staging, and stable image bindings remain intact throughout publication.

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

## Animated Grades

Add a regular Grade node, then right-click it and choose **Convert to Node-Owned
Grade** in either the Shader or Compositor editor. This copies the selected Grade's
Linear and Tone settings; an empty Grade node uses the default settings. Editing the
converted node does not change the original Grade datablock.

To return to shared settings, right-click the node and choose **Convert to
Datablock-Owned Grade**. This creates a new Grade datablock from the current frame's
values, including subframe evaluation. The new Grade is static, and the converted
node's Grade keyframes and drivers are removed. Undo restores the animated node;
converting back to node-owned later starts with the static values and no Grade
animation. Both conversions preserve the node's connections and layout.

Per-Node Grade settings animate on the scene timeline. Hover a numeric control in the
Shader or Compositor sidebar and press `I` to insert a keyframe, or use its right-click
menu. With Blender Auto Key enabled, changed settings are keyed when the slider gesture
ends. The curves belong to the containing Shader or Compositor node tree and appear in
the native Dope Sheet and Graph Editor when that tree is reachable from the scene.
The containing tree owns the animation: reusing a material or node group shares those
curves across its users and instances. Per-Node means each Grade node has its own
channels in the tree Action, not that each object or node-group instance has a separate
animation. Blender's timeline preview reconciles Grade kernels asynchronously, so it
may show an `Updating` result while a replacement is prepared; native animation renders
use exact per-frame preflight before rendering each output frame.
Regular Grade and Grade Stack controls do not support keyframes. The discrete
`peak_nits` control also remains static. Use Blender's F-curve controls to choose
interpolation and edit keyframes. Render
with Blender's native Render Animation command, including Ctrl+F12 or its F3
search result. The per-frame render handler prepares and verifies the full Grade
result before Blender continues each frame, for either image-sequence or movie
output. Shader Grade uses the evaluated Grade settings at the output frame's
exact time and holds that Grade fixed across the frame's motion-blur shutter
samples. Scene motion still receives Blender's native motion blur; Grade values
do not animate within that shutter interval. This is center-frame Grade
semantics, not per-sample Grade animation. Compositor Grade runs once after the
scene render and motion blur, using the exact output-frame time. The render
returns to the starting frame, subframe, and frame range when it finishes or
stops.

The installed motion-blur test compares animated Grade with a static copy made
from the same fractional output time. It checks both Shader and Compositor Grade
while confirming that scene motion still produces visible blur. It runs on each
available EEVEE or Cycles engine. The pinned Blender 5.2.2 test artifact
currently exposes EEVEE only; Cycles coverage remains outstanding:

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:installed_motion_blur_conformance
```

The publication comparison example provides F3 drag recording for comparing
helper-image publication strategies across Shader and Compositor trees. Its
instructions and trace target are in
`examples/publication_compare/README.md`.

The native regression pauses a real compositor worker, verifies that both banks
and the selector stay unchanged during the lease, then checks that publication
uses the same two image identities after the reader exits. It also verifies
intermediate Viewer output and final-value convergence during a CPU Compositor
slider drag. The drag regression exercises Exposure, CR Balance, and Tone Fit at
a requested 277 Hz in both editors, using bounded motion that avoids slider
endpoints:

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:banked_publication_gui
```

The default native fixtures are 128 × 96. Linux software-GPU results do not establish
behavior on macOS Metal; repeat the continuous-drag acceptance run in the user's
Blender environment.

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
