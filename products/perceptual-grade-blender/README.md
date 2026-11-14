# Perceptual Grade for Blender

This is the **preserved implementation**. Its source, tests, Buck targets and
package behavior remain the baseline; the commands below still build this
product. The replacement is planned separately in
[`perceptual-grade-next-blender`](../perceptual-grade-next-blender/README.md), with
its audited [state-machine design](../perceptual-grade-next-blender/STATE_MACHINE_DESIGN.md).
That documentation does not implement fixes in this product or certify new
behavior here. [GOAL.md](../perceptual-grade-next-blender/GOAL.md) and [CHECKLIST.md](../perceptual-grade-next-blender/CHECKLIST.md)
separate the new implementation plan from historical delivery evidence.

This product contains the extension manifest, registration entrypoint, package
builder and installed acceptance tests. Implementations belong to
`products/perceptual-grade-blender`, `libraries/perceptual-grade-core` and their
explicit generic dependencies. The numerical reference and DCTL are separate
library/product owners.

## Build and installation

Run from the monorepo root:

```sh
buck2 build //:perceptual_grade //:verify --show-output
buck2 test //products/perceptual-grade-blender/tests/packaging:architecture
buck2 test //products/perceptual-grade-blender/tests/installed:standalone
```

Install the resulting `perceptual_grade.zip` through Blender's **Install from
Disk**. This product and [HDR Color Picker](../hdr-color-picker-blender/README.md)
can be enabled together; compare preserved Grade and Next in separate Blender
profiles/processes. Installed acceptance runs on stable Blender 5.3.0 and LTS
Blender 5.2.4; the `bpy` test wheel uses 5.3.0. Buck downloads pinned
dependencies and generates numerical resources without sibling source
repositories.

When replacing an installation that uses the old `_vendor` package layout,
disable it before replacement and restart Blender before enabling the new
version. Persisted node IDs, settings and Image bindings do not contain those
Python package paths; this namespace relocation does not provide data-schema
migration. The extension is in unpublished rapid development: only the current
data and kernel layouts are supported. There is no old-schema repair or
compatibility conversion.
Existing development projects, including `train-model.blend`, are preserved as
files and are not upgraded automatically. Complete component packages live
directly beneath the extension root. Implementation files live in `src/`;
`entrypoint.py` supplies the ZIP root bootstrap.

The scheduling and output policies are handwritten Python modules in the core
library. The shared Invariant framework proves their separate `.inv` requirements
and supplies runtime contracts to actor-owned Stores. `//:verify` checks all leaf
machines, workflow coordinators and retained Lean color-model theorems. Packaging
binds the proofs to the exact shipped policies and generated contracts. Native
tests separately cover Blender effects; Z3 and proof payloads stay outside the
extension.

Packaging compares the archive's inventory and bytes against declared inputs,
rejects unsafe or conflicting paths, and explicitly inventories runtime JSON.
Packages retain their source without `sys.path` overlays or global import aliases;
each extension has separate module state and an App domain. Blender supplies
NumPy at installation. See the [component and packaging guide](../../build_defs/README.md)
for shared dependency and archive rules.

## Saved state, scopes and Bake

New saves retain the Grade/Stack editor controls and their selected Grade and Bake
Image when reopened with the extension enabled. The save format still uses native
Blender groups; explicit wrapper metadata restores the registered editor controls
during recovery while preserving the saved output. Existing unmarked development
files and missing selections are not repaired or inferred.

An unfinished Bake interrupts when its selected Grade, grading parameters, Stack
contents or effective upstream inputs change. The Bake request observes those
dependencies itself. Its previous baked Image remains available, and another Bake
click starts a fresh request. Selecting another node, arranging the graph and
editing unrelated inputs leave the request running.

Scopes automatically read original Image/Image Texture pixels, independently of
scene geometry, lighting, UV placement and viewport framing. Constants, reroutes,
muted bypasses, exact group occurrences, Baked Color and upstream analytical
Grades / exact Grade Stacks retain this route. A compositor Transform on that
route deliberately ignores placement and resampling. Simple movies and image
sequences follow the current scene frame, including source offset and cyclic
settings, even when the source's Auto Refresh control is off.

Complex processing such as HSL, Curves, Color Balance, Mix and Blur uses Blender's
native evaluator. Opening a visible scope automatically requests its processed
inputs. Foreground discovery observes source, frame, view and occurrence changes;
drawing and hovering only consume status and accepted results. Primary and
reference inputs form one coherent batch, including a direct Image or constant
companion when the other input needs native evaluation. A replacement retains the
previous coherent pair until both new members are ready.

Selected Grade edits reuse accepted input and update analysis throughout a drag.
An active compatible capture can complete while a newer source request is pending;
only the newest successor is retained. Native capture materializes frozen managed
PG models in its private helper graph. It never completes a live pending LUT or
changes the selected bank in the project. Adopted native output keeps its authored
meaning and carries no invented numerical provenance.

Foreground adapters freeze Blender scene/resource snapshots and publish native
UI/output state. General scope evaluation uses an isolated Blender helper on a
dedicated capture lane; only immutable values and captured arrays reach the
host-free numerical helpers. Physical occupancy and snapshot leases survive
cancellation until terminal acknowledgement or confirmed process exit. An active
CPU crash spends only that attempt's retry budget; queued peers retain theirs.
The [shared runtime guide](../../libraries/blender-runtime/README.md) describes
helper namespaces, dependency fingerprints and process lifecycles.

Stored UDIM tiles are sampled together, weighted by pixel count; waveforms retain
logical tile columns, including gaps. References follow the primary tile/local-UV
grid. Existing Image controls select multilayer passes and views; ALL uses the
first configured view and reports its name. Save painted UDIM tiles and edited animated multiview Images before sampling.
Tiled multilayer/multiview combinations report an explicit unsupported-format
error instead of selecting an arbitrary pass or eye. Native graph snapshots
also require saving edited tiled/multiview/multilayer resources before capture. Image
samples use deterministic nearest decoded pixel centers, scene-linear RGB, source
alpha semantics and a 256×192 sample budget. Squeezed stereo movie eyes first
use Blender-matching interpolation; movie decoding requires a visible Blender
window. Pixel mass remains separate from alpha.

Timeline playback pauses automatic acquisition and scope publication. The last
accepted display remains visible with paused status. On stop, foreground work
waits for acknowledged native evaluation completion, then requests the final
stopped frame. Playback epochs prevent a pre-playback completion from publishing
later. Source and numerical caches can be shared across equivalent consumers;
publication retains exact node, occurrence, editor, lifecycle and presentation
identity. The source-bound `scope_demand`, `scope_input`, `scope` and channel
machines govern demand, immutable acquisition, physical retirement and analysis.
Native tests separately establish Blender's frame, pixel and graph behavior.

The installed native regression exercises automatic acquisition, arbitrary native
color/spatial operations, references, Material/World inputs, and orthographic,
asymmetric and perspective views in Eevee and Cycles. Automatic-source fixtures
cover occurrence walking, shared models, color/alpha, sequence/movie frames,
UDIM and selected pass/view reads. Fixtures are generated scenes; the temporary
manual input `train-model.blend` is neither required by Buck nor shipped.

```sh
buck2 test //products/perceptual-grade-blender/tests/blender:scope_sources //products/perceptual-grade-blender/tests/blender:scope_images
buck2 test //products/perceptual-grade-blender/tests/installed:scope_images //products/perceptual-grade-blender/tests/installed:native_scope_capture
```

See [GOAL.md](../perceptual-grade-next-blender/GOAL.md) for validation and measured latency, and the
[acquisition contract](ARCHITECTURE.md#source-acquisition) for identity, authority
and sampling details. The earlier 2026-10-25 measurements (10.695 s Shading and
3.332 s Compositing first Linear draw) describe an earlier automatic native
capture implementation, not the current coordinator. Linux software-rendering measurements do not establish
macOS/Metal or physical display latency.

Bake captures the pixels entering a Grade or Grade Stack at the current frame
and native image dimensions,
then evaluates the selected node's production grading model directly. It uses
the kernels that calculate LUT samples without interpolating a LUT for that
selected node. Upstream nodes still use Blender's native evaluation.

The packed float RGBA Image supplies a separate Baked Color output. Existing
Color connections keep their live grading behavior; connect Baked Color to use
the snapshot in place. Each Shader or Compositor Grade and Grade Stack has a
native Blender Image selector with search, New and unlink controls for local,
packed float Perceptual Grade Images. Its saved `pg_bake_image` pointer is the
authority for the selected destination and derived native image source.
Leave it empty to create and bind a new Image on a successful Bake; clear it to
unbind without deleting the Image. Baked Color is transparent black while no
Image is selected.

Bake evaluates only the initiating node and writes only its selected Image.
Progress and errors appear on that node. Two independent bakes can calculate at
once, with up to eight accepted requests. Only the initiating node's Bake controls
are disabled. Each click freezes its source frame and model immediately; queued
work uses that snapshot even if the live graph changes. Requests sharing a
destination run in click order, after the preceding publication or rollback.
Selecting the same Image on multiple
nodes intentionally shares its pixels: rebaking it updates every consumer,
including standalone Perceptual Grade Bake nodes, without baking those nodes.
One Undo/Redo action covers the completed pixels, metadata and binding; redo
restores the saved result without calculating it again.

The result is a finite current-frame raster, so later spatial operations can
differ when the original graph relied on off-canvas values. Baking applies only
to the initiating Grade or Stack; arbitrary-node baking and automatic rewiring
are not supported.

Shader Grade and Grade Stack choose between Image and UV baking and display
the chosen route and its reason. An ordinary still Image Texture with an
unconnected Vector input, followed by supported pointwise color/alpha nodes,
uses the source Image's full dimensions, independent of render resolution.
This Image route works while the scene stays in Eevee or Cycles; an isolated
helper uses Cycles to evaluate the source pixels.

Any explicit connection to the source Image Texture's Vector input selects UV
baking to preserve its placement, including a direct Texture Coordinate UV or
UV Map connection. Other surface-dependent inputs and multiple source textures
also use UV baking. This route requires the scene to use Cycles and bakes the
active mesh, active render UV map and selected material slot. New UV Images
default to 2048×2048; width and height controls appear for this route. An
existing selected UV Bake Image keeps its dimensions and keeps the node on the
UV route even after its source becomes a simple Image graph. Clear the binding
to let the graph choose a new destination's route.

Shader Grade/Stack expose Baked Color and Baked Alpha. Their Vector input
controls how these outputs sample the stored Image in **both** bake routes;
it does not affect live Color/Alpha, choose the bake route, or select the mesh UV
map used to bake. An unconnected Vector uses the active UV map. For an
Image bake, connect a coordinate or mapping chain to place the graded texture.
For a UV bake, use the UV map that produced the atlas, either through the
fallback or an explicit matching UV Map connection. Reapplying the original
source Mapping to that atlas can transform its placement twice.

The standalone Shader Bake node offers Vector with the same UV fallback and
separate Color and Alpha outputs. It can be added to editable Material and
World shader trees. The standalone Compositor Bake reader remains available.
Connecting these outputs is manual.

One packed float Non-Color RGBA Image stores graded RGB and the terminal Shader
Alpha. Flat image-domain Images can be shared by Shader and Compositor readers.
A valid local, packed Compositor bake appears in the Shader Grade/Stack Bake
Image selector; selecting it binds the same Image, so rebaking updates its
other consumers too. Arbitrary Images and exported/reloaded files without the
managed bake metadata are not offered as Bake destinations. UV-domain Images
are restricted to Shader readers. UDIM, movie/image-sequence,
multiview and multilayer texture sources, Alembic/cache-dependent geometry,
overlapping or multi-tile UVs, Shader to RGB and texture-range outputs are
unsupported. These cases should use the 65³ LUT workflow where it fits.
UV baking requires Cycles and does not switch the scene's render engine.

Starting timeline playback cancels every unfinished explicit Bake, including
queued requests and completed results waiting for publication. Previous bound
Images remain intact and the initiating node reports the interruption. Playback
disables Bake actions, and an already committed Image remains published. After
stop, the button stays disabled until native evaluation leases and their queued
completion observations are acknowledged. Foreground route preflight publishes
an immutable eligibility receipt; drawing, polling and hover never start capture
or wait for policy actors. A race at click safely defers without a native popup.

Image recovery after Undo/Redo follows a finite revision automaton. A changed,
known completed publication can authorize invalidating a clean decoded buffer
backed by packed data; dirty, unknown or unpacked output is preserved. The native
adapter fences Image identity, completed operation ID and observation generation
around `buffers_free()` without reading pixels or hashing packed bytes. Only the
current operation's completion receipt settles invalidation. Neither preservation
nor invalidation certifies numerical contents. The source-bound Z3 target requires
nine properties, two positive witnesses and three detected source mutations with
Python counterexample replay. Native fixtures separately check pixels, Blender's
buffer behavior and receipt fences; the policy proof does not establish those
native observations or eventual recovery.

Recorded Linux Blender 5.2.2 acceptance covers analytic Grade/Stack pixels, shared
Image rebakes with unchanged or changed dimensions, native Undo/Redo without
recapture, failed recovery retry, dirty-buffer preservation, packed save/reopen,
cancellation, load and disable. Focused bake coverage also checks independent
destinations, selector filtering and binding, node-specific progress/errors,
bounded concurrency, destination ordering and physical retirement. Installed
concurrency coverage uses separate native helpers and individual Undo records.
Final evidence is retained in the historical sections of
[GOAL.md](../perceptual-grade-next-blender/GOAL.md); macOS/Metal remains a separate
acceptance gate.

```sh
buck2 build //libraries/perceptual-grade-core/proofs:bake_image
buck2 test //libraries/perceptual-grade-core/tests/policies:bake_image
buck2 test //products/perceptual-grade-blender/tests/installed:compositor_bake
```

Grade/Stack public interfaces expose only their useful inputs and live/baked
results. Six matrix rows and the LUT bank selector are private kernel constants;
intermediate pending/final LUT results are internal links. Save/Undo preserve
current public links, socket visibility, canonical Image pointers and native
output. Registered controls, operators, handlers and timers report failures as
localized inline outcomes; diagnostic details go to logs.

## Application ownership

Grade constructs an explicit `blender_runtime.App` and product Session. Stateful
modules expose `create(session)` factories; the Session caches their instances
and resolves peer components through ordinary imported factories. Exports read
live closure state, so replacing a Store or registry does not leave a stale
namespace snapshot. Registration classes, callbacks, transaction registries,
output operations and cleanup handles belong to that Session. A fresh enable
creates a fresh Session; native registration identity locates the exact existing
Session for cleanup. Shared framework code does not share state between Apps.

## Native acceptance limits

See the [application architecture](ARCHITECTURE.md) for lifecycle and native-reader
boundaries. Native coverage remains incomplete (`coverage_complete=false`).
USD/Alembic export can start a private native job before setting the interface
lock, leaving an unestablished reader-exclusion interval. Main-thread admission
and public job queries do not close it. macOS/Metal and physical HDR display
acceptance remain separate gates.
