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
type. Ordinary adjustments replace the pixels of one persistent 512 × 1 RGBA32F
parameter image (8 KiB), shared by all nodes using that Grade, including Shader
and Compositor nodes. Equal-valued independent Grades own separate writable
images. Slots 0–256 contain the Tone endpoint value, slope, and curvature; slots
257–259 contain the Linear matrix's red/blue columns and neutral row sums; slots
260–261 contain the Tone scalars and domain. Fixed texture samples read these
values instead of baking them into socket defaults. The boundary texture,
viewing constants, links, and output adapter remain fixed within a working space.
Updates therefore require no graph replacement, image allocation, or repacking.
Dirty parameter images are packed when saving; file-load reconciliation checks
the installed signature before accepting restored data.

Foreground publications coalesce to the newest complete result per source and
process one source per timer turn, with no preview frequency cap. They defer for
observed render/compositor/bake activity and interface locks. Blender's public
job notifications provide admission checks, not a universal lock against native
image readers. A render worker waits at its pre-evaluation callback while a
foreground timer performs exact reconciliation; synchronous main-thread renders
use the same scoped preflight directly.

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
