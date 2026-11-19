# Perceptual Grade for Blender

Grade and Grade Stack nodes appear in the Shader and Compositor Color Add
menus. Regular Grade nodes apply Linear, Tone, and Stage 3 Color through the
product's `kernel` package; Grade Stack nodes apply ordered, forward-only complete
Grades through progressive 33³/65³ GPU LUTs. Both use shared static Grade datablocks.
The Add menus provide one Grade entry. Right-click a Grade node and choose
**Convert to Node-Owned Grade** to give it independent settings and numeric keyframes
in Blender's native animation editors. All variants use the same Grade controls and preparation
model. Regular Grade controls remain disabled until a Grade datablock is selected.

The [Perceptual Grade handbook](../perceptual-grade-book/README.md) follows the
latest mathematical reference in English and Simplified Chinese, with HTML,
PDF, and EPUB editions. Its bilingual User Manual describes current Next
behavior and retains a clearly labeled legacy 1.23.2 ZIP link. Stage 3 supplies
numeric J, C, Adaptance, and Warp controls; the draggable Warp diagram is deferred.
Warp hue is displayed as its stored degree offset. All Grade paths follow the
reference's Adaptance → H–K repair → common positive Scale order.

Adaptance drags use 0.01 increments and tonal soft spans of ±4, ±10, ±20,
and ±25. Finite requests beyond the physical response domain are limited
radially, preserving the a/b tint direction. Warp hue edits maintain at least
4° between cyclic target angles by pushing neighbors. Returning the initiating
handle restores its neighbors toward their saved positions until blocked. A
manual edit detaches only that handle. A new push transfers ownership using
its current position as the new baseline.
Claims persist through copy, conversion, save, and undo. Actual frame/subframe
changes expire per-node claims; shared Grade claims remain. Animated samples
resolve through the same immutable settings boundary for Grade and Stack,
without rewriting RNA or keyframes; Limited identifies raw/effective differences.
Tone Peak edits clear claims and revalidate hue and Adaptance together.
Settings-resolution schema 1 versions derived signatures independently of the
unchanged template topology and texture schemas. Authoring provenance never
enters those signatures; bake freshness still includes the raw control values.

A private asyncio loop owns the preparation schedulers. Each shared
Grade has one active preparation and one replaceable latest settings snapshot;
rapid edits do not enqueue a history of slider positions. Linear, Tone-table, and
boundary preparation run concurrently from one frozen Grade snapshot and join
before a complete prepared result can publish. Shader and Compositor share that
result, while Blender's main thread owns their separate kernel graphs and per-node
policy state.
The loop starts the newest successor as soon as active preparation finishes,
without waiting for Blender's publication timer.

A Grade appends its complete Linear/Tone/Color graph from the bundled native template
library once per tree type. Working-space-dependent output conversion is bound
through the parameter image. Each of two fixed banks owns five RGBA32F helper
images: scalar/Tone parameters, Color coefficients, Web parameters, Web toes,
and Adaptance parameters. One complete bank is 2,916,976 bytes; the pair uses
5,833,952 bytes (about 5.56 MiB), excluding the shared boundary image. All Shader and Compositor
nodes using one Grade share these banks. Every role of the inactive bank is
staged and checked in one admitted publication scope before the shared selector
switches. An unchanged role can reuse a candidate image with the matching clean
receipt. Bank identities remain fixed across edits, and independent Grades own
separate pairs.

Slots 0–256 contain the Tone endpoint value, slope, and curvature; slots 257–259
contain the Linear matrix's red/blue columns and neutral row sums; slots 260–261
contain the Tone scalars and domain; slots 262–264 contain the output conversion
matrix rows. Further slots carry Stage 3 flags, scalars, and field domains;
two texels hold the tonal anchors and authored Adaptance-row activity flags.
These preserve exact-zero cardinal support across atlas interpolation without
tolerance-based suppression. Parameter schema 4 retains the 512×1 scalar image;
the other role images carry the prepared coefficient and web data. Fixed texture
samples read these values instead of baking them into socket defaults. The
Adaptance field always uses 32,768 cells in an 8193×4 RGBA32F image
(524,352 bytes per bank); runtime never selects its resolution from settings.
This replaces the earlier 3,072-cell field to satisfy the retained extreme-grade
RGB gate near exact-zero cardinal support. Field layout schema is 6.
The boundary texture and viewing constants remain shared across working spaces.
Publication packs a complete inactive bank before changing the marked selector.
A failed transaction restores the previous selector and metadata; any failure to
restore or deliver closes the Grade output visibly. File-load reconciliation
checks both bank bindings, reader markers, selector agreement, and kernel schema
before accepting restored data. If the active bank fails its content receipt,
recovery first revokes the Grade output and proceeds to rewrite both banks only
after the fail-closed receipt succeeds.

Compositor Grade graphs retain the Scene's GPU Auto or Full precision selection.
Stage 3 carries signed energy divided by 4096 and carries J_A explicitly.
Disabled stages and inactive H-K repair preserve J_A; positive Scale multiplies
it directly, alongside Scale squared on energy. Changed energy can still recover
J_A through its signed square root scaled by 64. This avoids an unscaled squared-
energy image and redundant half-precision round trips at output projection.
When all authored Color families are inactive and H-K is provably inactive
(`J_A >= 0` or reflected `H < 0`), output projection can retain Tone's raw
response basis. It still checks actual AP1 cube legality and endpoint policy.
For that legal identity path, uniform output-conversion rows are composed with
the cone-to-AP1 matrix before spatial decode, avoiding an extra half-precision
AP1 image. Active Color always uses its actual transformed coordinates.
If the primary projected decode is illegal, the Compositor path tries one
radius multiplied by `0.99609375`; only an actually legal retry is accepted
before the existing interior-neutral fallback. A legal primary result is
unchanged. Generic full-Grade and Stack default paths keep their prior behavior.
The output router checks original source RGB, the final Stage 3
carrier, and projected RGB. Observed nonfinite or representational-edge values
select magenta with alpha preserved; accepted output pixels are unchanged.
This check does not certify every finite intermediate's accuracy. Finite
saturation is a separate diagnostic. CPU and GPU Full retain full-precision
accuracy gates; Auto previews allow half-precision rounding.
Remote live acceptance passed in build `252b9488-83c2-49de-8943-8f509bc7e8f0`:
the installed Viewer fixture took 61.382 s, including 16 exercise frames,
12 automatic updates, signed/HDR/nonfinite colors, alpha, two reload-repair
frames, and normal exit. Its limits remain 0.01 for Auto and `1e-4` for Full.
The source carrier gate passed 18 live evaluations in 226.453 s and all five
transport checks passed. These are correctness-fixture timings.

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

## Baking Grade Output

Shared Grade and Grade Stack nodes expose a Bake control in both Shader and
Compositor trees. A bake captures the current native node-tree result into a
managed packed 32-bit float RGBA Image and switches the node to that reader.
Use Bake can be disabled at any time without unbinding the Image; changing the
authoritative Grade or Stack settings or a detected source change revokes the
bake receipt, returns the node to live output, and disables Use Bake until a
new bake is published. Nodes retain source tracking while Use Bake is off. A
managed Image may be selected by multiple nodes, so a rebake updates every
reader of that Image.

Shader bakes retain the legacy route distinction. A pointwise graph with one
still Image source uses the Image route and evaluates one output pixel per
source texel. Linked coordinates, surface-dependent nodes, an upstream managed
UV bake, or multiple source Images use the UV route and require a Cycles mesh
with one non-overlapping UV map. Compositor bakes use native compositor evaluation and retain its output
image domain.
Value-only Shader graphs with no source Image use the Image route and publish a
1x1 managed Image. Compositor constants retain the compositor canvas dimensions.
Image-domain Shader bakes follow the active Scene render choice: EEVEE uses a
private orthographic node-tree render, while Cycles uses the Scene's CPU or GPU
selection. Workbench and unknown engines use Cycles CPU. UV bakes remain
Cycles-only but honor the Scene's CPU/GPU choice. A GPU request freezes the
Cycles compute backend and exact enabled device identities at click time; an
unavailable selection fails visibly and is never silently changed to CPU.
The helper does not modify the user's Scene or preferences. EEVEE's limited
color-pass precision is handled with split signed-HDR AOV readback before the
float Image is published.
The Shader Vector input controls only baked sampling. When unlinked, it uses
the recorded bake UV map (or the active render UV map for Image bakes).
Grade parameters are evaluated through the native Grade helper-image tree, and
Grade Stack parameters through its complete 65^3 LUT tree; per-node animated
Grade nodes intentionally have no Bake control.

Bake rejects UDIM/tiled Images, movie or sequence sources, multiview or
multilayer data, Shader to RGB, movie-clip and mask inputs, linked or animated
cache/Alembic geometry, missing UVs, degenerate or overlapping UV islands,
unsupported group occurrences, and dimensions outside the bounded pixel
budget. Apply unsupported modifiers before a UV bake, including Array, Mirror,
Subdivision, Geometry Nodes, Armature, Curve, Lattice, and Displace. The supported
unapplied modifiers are Cast, Corrective Smooth, Laplacian Smooth, Normal Edit,
Simple Deform, Smooth, Warp, Wave, and Weighted Normal. Requests are serialized through one
helper lane and capture a frozen click-time snapshot; an edit, frame change, or
invalidated source discards the in-flight result rather than publishing stale pixels.

Bake freshness uses small graph/settings digests, cheap Image metadata, and
per-ID change generations for referenced Images, Meshes, and Objects. The
metadata includes dimensions, channels, color/alpha modes, packed status and
size, plus external-file device, inode,
size, mtime, and ctime facts when available. Source pixels, packed/external
Image bytes, and `.blend`, `.npy`, or EXR bake payloads are never hashed.
Accepting a request copies each unique source Image once to freeze its
click-time state. Request, publication, and render boundaries compare receipts
and tokens without image-sized hashing. File load and undo rebaseline transient
generations against the persisted cheap receipt and preserve Use Bake when it
still matches; a missing or mismatched receipt returns to live output and
requires rebaking. Earlier receipt versions are not migrated. Toggle
availability is derived from this same freshness decision and remains greyed
out after revocation until a new bake publishes.

Grade and Grade Stack receipts identify their sockets by public names, so
generated socket identifiers can change during live/wrapper/fallback kernel
recovery without invalidating unchanged settings and connections. Dependency
tracking invalidates on Image updates, Mesh geometry updates, and Object
transform updates. It ignores Object geometry-only or shading notifications
from material/node changes and Mesh shading-only notifications; Mesh data and
Object metadata are observed separately.

Scripts that modify an Image must call
`bpy.ops.perceptual_grade.invalidate_image(image=...)` to notify dependent bakes;
use the operator's `image="Image Name"` argument or the extension's exported
`invalidate_image(image)` Python function. `image.update()` alone is
insufficient. Unnotified pixel changes that preserve cheap metadata can be
missed, including edits made while the add-on is inactive or external-file
replacements with unchanged recorded metadata.

The Technical Report documents the [bake request policy and native evaluation
contracts](../perceptual-grade-book/docs/book/src/development/next-policies.md#next-policy.bake),
including queue bounds, signature fencing, publication admission, and rollback.
Keep observable behavior changes consistent with that report and its
[`technical-report-audit.json`](../perceptual-grade-book/technical-report-audit.json)
evidence inventory. The Next `tests:technical_report_audit` Buck target checks
chapter coverage, policy references, and evidence paths; reviewers must also
compare the prose with the implementation. The audit tooling is build-only.

## Animated Grades

Add a regular Grade node, then right-click it and choose **Convert to Node-Owned
Grade** in either the Shader or Compositor editor. This copies the selected Grade's
Linear, Tone, and Color settings; an empty Grade node uses the default settings. Editing the
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
available EEVEE or Cycles engine. Stable Blender 5.3.0 and LTS Blender 5.2.4
installed targets currently expose EEVEE only; Cycles coverage remains
outstanding:

```sh
buck2 test --remote-only //products/perceptual-grade-next-blender/tests:installed_motion_blur_conformance //products/perceptual-grade-next-blender/tests:installed_motion_blur_conformance_lts
```

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

The `node_templates` Buck target runs the canonical emitters in pinned Blender
5.2.4 and produces `kernel/node_templates.blend`, its runtime index
`kernel/node_templates.json`, and `kernel/grade_stack.glsl`. Its 12 groups are
Shader and Compositor Grade kernels, one Stack topology per tree type, two
private bake wrappers, and six pending/error fallbacks for the supported
interfaces. Node-owned Grades use the same Grade templates with independent
parameter banks. Working-space-dependent Grade conversion rows and Stack basis
matrices are bound through runtime images alongside Stack LUT pixels and its
resolution configuration. Stack quality selects 33³ or 65³ runtime LUT/config
data without changing template topology. Live kernels and bake Images remain
runtime resources. Missing or incompatible assets produce a visible error and
the existing alpha-preserving magenta output.

The final measured 12-group `.blend` is **3,688,385 bytes**; its runtime manifest is
**9,464 bytes**, and the Stack shader is **67,226 bytes**. These are raw asset
sizes before ZIP compression. The **7,896,941-byte** detailed structure report
is build-only and is excluded from the extension ZIP. Stored Grade Shader and
Compositor kernels contain 1,795/3,042 nodes and 3,099/5,402 links; Stack kernels
contain 214/238 nodes and 320/356 links. These inventories do not measure
evaluation speed.

The installed product and installed tests consume those exact generated
resources. The long graph emitters live under `tools/template_build/` and are
available only to build tools and native emitter tests; they are absent from
the extension ZIP. The runtime keeps numerical preparation, resource loading,
binding, and existing publication policies. Template instantiation executes
inside the existing authorized publication effects and adds no policy machine.

Build the shared template artifact with:

```sh
buck2 build --remote-only //products/perceptual-grade-next-blender:node_templates
```

Build the package and run the installed smoke test with:

```sh
buck2 build //products/perceptual-grade-next-blender:extension
buck2 test //products/perceptual-grade-next-blender/tests: --remote-only
buck2 run //products/perceptual-grade-next-blender:install_workspace
```
