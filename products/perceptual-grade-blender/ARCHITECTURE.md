# Perceptual Grade source boundaries

This document describes the **preserved implementation** in this product and
`libraries/perceptual-grade-core`. Its source, tests, Buck targets and package
behavior are unchanged by the new implementation plan. The replacement has its
own [architecture](../perceptual-grade-next-blender/ARCHITECTURE.md) and canonical
[state-machine design](../perceptual-grade-next-blender/STATE_MACHINE_DESIGN.md).
[GOAL.md](../perceptual-grade-next-blender/GOAL.md) and [CHECKLIST.md](../perceptual-grade-next-blender/CHECKLIST.md) distinguish that
pending work from historical delivery evidence.

## Preserved implementation and evidence

The source map and detailed sections below describe this runtime, including its
known limitations. Separate scope/Bake/output/recovery machines, foreground
sampling, movie-reader restrictions and adoption without derived-asset validation
remain baseline behavior. Statements that Material Preview lighting is omitted
or recovery never rebuilds derived output describe this implementation; they do
not constrain the new product. Historical results do not certify the new design,
and documenting that design does not fix this runtime.

This product owns Blender graph/UI, GPU programs, native capture/publication and
application composition. Host-independent mathematics, catalogs, identities,
codecs and scheduler/output reducers live in `perceptual-grade-core`. The
reference model lives in `perceptual-grade-reference`. The DCTL is the sibling
`products/perceptual-grade-dctl` product.

See the [component and packaging guide](../../build_defs/README.md) for normal
Buck Python dependencies and private extension bundling. Development uses
`color_tools.perceptual_grade_blender`; installation places the unchanged package
directly beneath the extension root as `perceptual_grade_blender/`. Physical
implementation files live directly in `src/`, while `entrypoint.py` becomes the
ZIP root `__init__.py`. No source overlays or duplicate portable kernels remain.

Source-aware scope acquisition automatically chooses original-Image reads or
native graph capture for a visible consumer. [CHECKLIST.md](../perceptual-grade-next-blender/CHECKLIST.md)
records the separate implementation plan; historical sections in
[GOAL.md](../perceptual-grade-next-blender/GOAL.md) retain this product's validation evidence.
`scopes/sources.py` performs short iterative occurrence walks;
`scopes/images.py` owns immutable source descriptors and sampled-pixel revisions.
Stored Image decoding runs through `jobs/handlers/images.py` and
`scopes/image_decode.py` in a private helper. Its source recipe contains values
and encoded packed bytes, never foreground RNA or a live scene snapshot.

`scopes/automatic.py` owns visible demand, playback epochs and the active/newest
request policy. `scopes/sampling.py` coordinates source sampling on the foreground thread.
`scopes/capture.py` freezes scene snapshots and owns capture requests; the
`jobs/handlers/native_capture.py` helper evaluates their native Blender graphs.
`scopes/jobs.py` coordinates detached numerical execution and publication through
`graph/scheduler.py`. The scheduler runs the pure policy from the core library
and executes admitted effects with receipts. Scope analysis is host-free;
capture, textures, timers and publication retain explicit execution/ownership
protocol dependencies.

## Current public graph and failure boundaries

Kernel numerical schema 25 uses resource layout 2. The six scene/LUT matrix rows
are private `ShaderNodeCombineXYZ` constants tagged `_pg_matrix_row`; the bank
selector is a private Math ADD constant tagged `_pg_output_selector`. Pending and
final LUT branches remain internal links. No matrix rows, bank selectors or
intermediate result sockets appear on Grade/Stack public interfaces.

Shader Grade inputs are Color, Alpha, Color Reference and Vector; Shader Stack
omits Color Reference. Outputs are Color, Alpha, Baked Color and Baked Alpha.
Compositor Grade inputs are Color and Color Reference; Stack has Color only.
Both Compositor nodes output Color and Baked Color. Vector controls only baked
texture sampling. New saves record the original editor wrapper type and dependency
driver mute state on their portable native groups. Recovery restores those marked
wrappers after adopting their output, preserving public links, socket visibility,
Grade/Stack settings and the canonical Image pointer, including rollback. This
restores the registered selectors, Bake action and tooltips. It is a native
serialization operation, not a schema upgrade. Saved journals remain historical;
unmarked development layouts and absent selections are never reconstructed.

`integration.outcomes` stores bounded plain status values under a passive Session
epoch. Registered operator, draw, RNA-property, handler and timer boundaries
contain failures, log diagnostic details and display localized inline outcomes.
Status drawing does not access actors or grant authority. Exact native handler
and timer identities remain tracked through failed cleanup; retries cannot erase
unreleased transaction or helper debt. Internal operations still raise normally
so transactional compensation and source-bound failure transitions remain intact.

## Analytic compositor image baking

The Bake action captures the Color input of a Compositor Grade or Grade Stack
at the current frame and native image domain. An isolated Blender helper
evaluates upstream operations, then applies the selected node's frozen grading
model directly to the full-resolution pixels. The host-free evaluator uses the
same production kernels that calculate 33³/65³ LUT samples, without LUT
interpolation for the selected node. Stage 1 and scene-color endpoint matrices
apply once, model input/export guards remain in force, and alpha is unchanged.
Stack inverse entries retain their existing production solver behavior.

The result is a packed float RGBA Image with source, frame, domain and analytic
model provenance. A separate Baked Color output reads it while existing Color
connections retain live grading. The standalone `PGCompositorBake` node can
reference the same Image. Grade, Stack and standalone readers use Blender's native
Image selector (`template_ID`) with search, New and unlink controls. The saved
`Node.pg_bake_image` PointerProperty is the sole binding authority; kernel Image
nodes and texture settings are derived materializations. Selecting, clearing,
creating and binding Images use current-generation ownership transactions with
verified compensation. An empty binding creates an Image on successful Bake;
unlinking does not delete shared data. Binding changes observe the same native
reader and repair boundaries as publication.

Foreground route preflight caches an immutable eligibility receipt. Drawing,
operator polling and hover use that receipt and passive native readiness. Source,
engine, selection and coordinate changes invalidate preflight; an unavailable
receipt keeps the control disabled until foreground validation completes.

Bake pins the initiating node, kernel and selected Image until publication and
rejects a changed binding. Each request observes its own effective target and
upstream inputs; Grade selection, grading parameters, Stack occurrences and
relevant source or topology changes interrupt the unfinished request. Source-local
grading-intent revisions retain change/revert observations without asking upstream
nodes to find or cancel their consumers. The request requires a new explicit Bake
click and preserves its previous Image. Node selection, names, layout, unrelated
graphs, generated LUT updates and unused live grading behind a Baked Color output
do not revoke it. It evaluates the initiating node and overwrites only its Image.
Input observations use the exact effective graph and group occurrence. Shader UV
routes fingerprint positions, topology, UVs and semantic mesh attributes in bulk;
selection/display attributes are omitted. The request rechecks current data before
dispatch and publication independently of the scope revision cache.
Nodes intentionally sharing the selected Image observe its new pixels without
starting another bake. Progress and errors are associated with the initiating
node; only that node's controls are disabled during its request. The actor-owned
`bake_queue` coordinator holds eight request reservations and two physical worker
leases. Snapshots freeze at click; dedicated `bake_0` and `bake_1` lanes evaluate
independent destinations concurrently. A shared destination waits for every
earlier request's publication or completed rollback, not merely its worker's
retirement. Native snapshots and publications remain serialized foreground
operations under the output guard and existing 512 MiB snapshot budget.
The Baked Color output is transparent black while unbound.
New kernels construct their complete current public interface and private storage
once. Unsupported or incomplete layouts are unavailable; no operation appends
sockets, rebuilds an old schema or migrates saved data. Copies preserve the
canonical Image pointer, independently of their private LUT banks. Generic kernel
assignment materializes only the receiving node's canonical destination.

Publication stages a verified artifact, then creates or updates the Image inside
the final modal callback, immediately before FINISHED. Shared-image replacement
uses packed EXR bytes plus buffer invalidation, with same-operation rollback from the
previous packed data and metadata. It does not reload an external filepath.
Pixels, metadata and binding belong to one Undo/Redo step; redo does not evaluate
the model again. Target ownership and binding are rechecked before publication.
The saved canonical destination pointer also belongs to native Node wrappers, so
an adopted portable group can select an Image and bake without conversion.
A fresh producer operation ID enters WRITING before transfer and COMPLETE only
after native transfer, packing and binding succeed. This records completion
history, not current content validity. Artifact transport checks remain separate.

Recovery treats Blender's restored data as authoritative. Runtime fencing does
not restore backup bytes, change user graph links, or select a generated fallback.
Actual native replacement supersedes old publication ownership; manual runtime
reconciliation can relinquish ownership without asserting restoration. Physical
helper retirement and replacement completion remain independent obligations.
Ordinary failure rollback inside a still-owned producer operation is separate.

Blender can restore older packed bytes during Undo while retaining a newer decoded
buffer. A bounded Image reconciler records scalar Image UID and producer commit
identity before replacement for both bake Images and permanent LUT Images. Clean
known managed commit changes request guarded buffer invalidation, acknowledged
only for the same observation, UID and commit. No recovery path hashes packed
bytes, reads pixels, or validates their numerical contents. Dirty and unknown Images are preserved. A known managed-to-unknown Undo
transition can invalidate a stale decoded buffer when authoritative packed
backing exists; resident-only unknown data is preserved. This is current native
Undo reconciliation, not data-schema migration.

The App-owned bake_image machine distinguishes settled_preserved,
settled_invalidated, removed and failed outcomes. An interrupted native cache
operation remains tracked until retry or supersession. External edits can settle
older runtime debt without discarding those edits or certifying their content.
App/Store envelopes and observation generations reject stale receipts, including
re-entry into the same phase.

`//libraries/perceptual-grade-core/proofs:proof_bake_image` checks nine properties,
two positive witnesses and three mutation controls through the shared source-bound
`.inv` verifier. Symbolic/Python correspondence tests cover all finite phase/boolean
combinations at boundary observation generations and exercise each mutation's
native counterexample. Native integration tests cover actual Undo, shared Images,
cache invalidation, external-data preservation and physical retirement.

The actor-owned bake coordinator stages artifacts and admits publication only
from the foreground modal operation. Pending operators pass timer events onward
so a queued request cannot consume a predecessor's publication event.
The queue proof covers target uniqueness, destination order, the two worker
leases, frozen identity, generation fences and validated terminal release.
The publication coordinator retains repair
debt until verified restoration or acknowledged native replacement. The exact
coordinator retains native-stop barriers and explicit animation frame numbers.
The scope-demand coordinator starts one active acquisition and retains only its
newest successor. Scope-input authority binds each immutable source/target once;
numerical scope analysis has a separate coordinator. Physical leases survive
logical cancellation until validated retirement receipts.

Linux validation before the Z3 migration passed six analytic raster cases, nine
then-current policy checks, 20 focused native bake cases, and installed Blender
5.2.2 acceptance.
Grade/Stack and same-size/resized rebakes match direct production-kernel pixels
exactly. Real Undo failure/retry, shared consumers, packed persistence, no-recapture
Redo, dirty-buffer preservation and helper retirement pass. That validation run
passed 25 Buck targets / 400 unittest cases;
[GOAL.md](../perceptual-grade-next-blender/GOAL.md) records build IDs and the
retained source hashes, archive inventory and native reports. This evidence does
not establish the separate platform/native-reader boundaries below.

Focused bake coverage includes independent
destinations, selector filtering and binding, node-specific progress/errors,
publication rollback and native recovery. Installed acceptance also verifies
that rebaking one destination preserves another Image's pixels and metadata,
separate native workers make progress independently, shared destinations follow
click order, and each completed publication has its own native Undo record.

An Image snapshot establishes a finite raster boundary. Downstream spatial
nodes may differ when the original lazy graph depended on off-canvas values.
Only the selected node becomes analytic; upstream nodes retain native evaluation.
Shader Grade/Stack baking supports ordinary still-image domains and Cycles
active-mesh UV domains, with shared flat Image readers across editors. Arbitrary
node baking, automatic rewiring and graph-preserving raster replacement are
deferred. Acceptance scenes are generated; `train-model.blend`
remains a temporary manual input excluded from Buck resources and artifacts.

`jobs/` holds Grade-specific operations and detached bake adapters. The reusable
host adapter owns `blender_runtime.execution`, `blender_runtime.ownership` and
`blender_runtime.blender`; `services.py` configures the product's lazy App capabilities.
Each foreground module exports a `create(session)` factory. Mutable graph, UI,
scope, transaction and output state belongs to the resulting explicit Session;
peer components resolve through that Session, without a module-global registry.

Channel/lifecycle/exact/display/output/bake-image transitions run through App Stores using
directly maintained policies from `perceptual_grade_core.graph.policies`. Native
handlers consume plain effects and dispatch bound event receipts against
current Store state after the operation. `ownership/` and
`integration/lifecycle.py` retain Grade's native reader barrier, rollback and
ordered recovery. Registered RNA classes retain their original Session through
reload; teardown uses those exact arenas, callbacks, classes and runtimes.

Native load/Undo/Redo recovery is an actor-owned `recovery` coordinator with
source-bound `.inv` safety and progress properties. Native pre fences old interests;
native post acknowledges replacement and retires old runtime publication authority.
A timer waits for physical retirement, snapshots a finite owner worklist, adopts
one owner per step, restores explicitly marked editor wrappers one per step, and
reconciles Image runtime state before activation. Each phase uses current-generation
receipts; wrapper restoration preserves adopted output without numerical validation.
Progress,
failure and explicit retry are visible in the sidebar. Retirement has a five-second
deadline; expiry reports failure and retains obligations. Completion assumes native
calls return and Blender schedules the timer. A retry does not invent a native
replacement or erase current-generation transaction debt.

Restored native graphs and Images are authoritative, including user edits. Adoption
records a scalar Grade/Stack control-intent baseline and protects the native selected
bank, but grants no numerical provenance. Recovery never reads pixels, hashes output,
repairs graph values, rebakes, or replays saved repair journals. Unchanged intent
(including forced idle refresh) preserves adopted output. A subsequent actual control,
animation, selected Grade or Stack occurrence change admits normal production.
Downstream visible scopes encountering adopted upstream output automatically
capture the actual authored native graph without certifying or rewriting it.

Production establishes output validity by ordered effects: reserve an inactive bank,
transfer, native update, pack, record completion, then select under the reader guard.
The COMPLETE state follows successful effects; there is no native-payload readback.
Only runtime-produced Cubes carry mathematical provenance. Transport checksums and
input/artifact constraints remain separate from native output certification. A clean
Image crossing a known managed publication revision may have its decoded buffer
invalidated so Blender reloads authoritative packed backing. The Image state machine
tracks this effect without inspecting payloads; dirty or externally authored buffers
are preserved.

Revocable `OwnershipContext.observation()` scopes remain available for bounded
read-only reference resolution. They hold no RNA and cannot grant publication or
recovery authority. Saved transaction records are historical; live same-generation
failure debt remains executable only through its owning current runtime transaction.

## Scope identity contract

### Source acquisition

The automatic route reads original Image/Image Texture pixels, independently of
scene geometry, UV placement, lighting and viewport framing. It resolves
constants, reroutes, muted bypasses, exact nested occurrences, Baked Color and
upstream analytical Grade / final 65³ Stack chains. Only compositor Transform
has an explicit spatial bypass: its placement/resampling does not change these
original-Image scopes. Other native processing requests automatic native acquisition.

Value-only Image descriptors include lifetime/session, interpretation, frame,
layer/pass/view, resource metadata and sampling layout. Selected Grade controls
are analysis inputs, not pixel-cache keys. Movie reads use a private Image and
explicit frame load; sequence reads resolve the selected frame file. The source
Image and its user settings remain unchanged. CPU byte reads convert through
OCIO; a private source-only linear EXR conversion handles standalone Blender
builds without the Python OCIO binding. GPU sampling uses explicit nearest decoded-pixel coordinates and the same source
alpha interpretation. Squeezed stereo movie eyes require Blender-matching linear
reconstruction before sampling. Movie decoding requires a visible Blender window;
background sequence and still-image readers have separate native tests. A wholly
direct source route does not describe or serialize a native graph.

The grid budget is 49,152 samples. Ordinary grids preserve aspect ratio and
sample nearest original pixel centers. Stored UDIM tiles reserve one sample per
tile and distribute the remaining budget by pixel population with deterministic
largest-remainder allocation. Immutable mass, local UV, tile IDs and logical X
travel with RGBA through CPU/GPU analysis. Histogram, waveform, cloud opacity and
robust-fit sampling use mass separately from physical alpha. Logical X includes
gaps between UDIM columns. Unsaved painted UDIM pixels are explicitly unavailable.
Multilayer/pass/view selection applies to non-tiled sources; combined tiled
multilayer/multiview formats fail explicitly. Edited animated multiview Images
require saving because Blender's resident-view export cannot select a frozen
frame. Static edited multiview export requires an initialized resident eye;
physical/manual painting remains a separate acceptance boundary. Native scene
snapshots reject edited/generated tiled, multiview and multilayer resources that
cannot be faithfully represented by their single-buffer snapshot path; save
those sources first.

References reuse the primary grid: tiled sources match tile numbers/local UV;
ordinary references repeat per primary tile; ordinary primary sources match
reference tile 1001. Missing tiles have zero coverage and are reported incomplete.
Whenever either input requires native evaluation, primary and reference form one
immutable batch. Direct Image/constant companions decode in the same private
snapshot context. The reference waits for the primary candidate's exact grid;
both members become visible together. Source replacement retains the prior
coherent pair, including its layout, until the new pair is accepted.

Draw and hover consume published results/status. Foreground timers discover
visible consumers and probe changed source data at bounded intervals. No
persistent graph index or reverse-dependency cache is retained. Sample and
analysis cache keys exclude editor ownership; publication tickets retain exact
node/occurrence/editor and lifecycle fences. Local Grade edits reuse accepted
input and continue analysis during a drag. Compatible completed work may publish
while a newer request is pending, with its actual identity and freshness status.

Playback callbacks latch a new epoch and pause flag without actor calls. Ordinary
foreground work cancels publication authority, retains physical retirement debt
and pauses all automatic acquisition and analysis publication. Previous results
remain visible. Stop resumes only the newest final demand after the native reader
guard acknowledges completion. A completion from an earlier playback epoch
cannot publish in the resumed session.

Acquisition pins the original frame, models, primary/reference grids and arrays.
Each input is acquired once per active cycle; a newer request replaces only the
pending successor. Source or lifecycle replacement cancels publication and
retains each helper lease until physical retirement. Clearing a cache never
manufactures a retirement receipt.

The source-bound `scope_demand` actor governs active/newest demand, compatibility,
playback epochs and completion. `scope_input` binds exact source/target authority
and physical leases, including atomic batch adoption. The `scope` and channel
machines govern immutable-array analysis and compatible publication. `.inv`
properties, positive witnesses and replayed mutations cover these policies;
Blender effects remain separately tested adapter premises. No generic Invariant
framework changes are required.

### Native graph capture

A visible Shader or Compositor scope automatically evaluates its current native
input demand. Source, occurrence, frame and view discovery belongs to foreground
work; drawing and hover never authorize a snapshot. There is no Refresh button,
manual capture gesture or corresponding modal/Undo action.
Any connected output Blender exposes as Color/RGBA can be captured at the selected
Grade input, before display transforms. The numerical workers then apply that
Grade's Linear, Tone and Color stages exactly once. Scopes do not measure the
final image after downstream composition. This native path is also the route for
ordinary non-Grade nodes that provide Color outputs; node-specific Python
evaluation is not part of the contract.

Each request freezes the owning material, World or compositor scene, selected
Grade/input, and the exact nested group-instance path. A shared group is not
treated as a unique occurrence: the node-editor path or an unambiguous owner
must identify which instance Blender should evaluate. Requests are separated by
their editor consumer and view context so one window or region cannot reuse
another's framing. Detached node groups support the same automatic source route. Native acquisition
requires an unambiguous scene-backed occurrence.

Shader capture follows the most recently used 3D viewport in the same window,
with the active scene camera as fallback. The frozen view context carries the
viewport's projection, dimensions and visible objects; the scene supplies the
render engine, world, lighting, frame and view layer. Material scopes include
visible users of the selected material. World scopes cover visible background
pixels. Light shader trees do not have this camera-pixel sampling domain. Material
Preview studio lighting and viewport overlays are not part of the signal. If
neither a usable 3D view nor a scene camera exists, capture reports that cause
instead of leaving the scope in Preparing.

Orthographic reconstruction preserves the frozen projection's full depth
interval. For normalized canonical projection `P`, its near and far view-space
planes are `(-1-P[2,3])/P[2,2]` and `(1-P[2,3])/P[2,2]`. The helper shifts the
camera along local positive Z so that both planes lie in the render camera's
forward volume, retaining their separation and the original XY framing. It
checks the complete effective projection after this shift; an XY-only check
would miss visible surfaces behind the original viewport origin. Degenerate or
oblique orthographic matrices that a Blender camera cannot represent fail
explicitly. Perspective reconstruction and scene-camera fallback retain their
existing behavior.

Compositor capture evaluates the owning scene's actual frame and image domain at
native resolution before reducing the completed image to the bounded analysis
grid. This preserves pixel-based transforms, filtering, crop and alpha semantics.
Render Layers follows Blender's owning-compositor canvas semantics even when
the node references another scene with different render dimensions. Image inputs
retain their native image domain. Explicit reference inputs are resampled to
the primary analysis grid so corresponding scope samples have the same shape.
The graph is evaluated by Blender, so support follows the native evaluator
rather than a Python implementation of each node. Missing resources, unavailable
render engines, unresolved graph instances, and outputs without native Color
capability produce an explicit error. Preparing is reserved for a request that
has actually been admitted and is still waiting for a snapshot, render or
analysis result. Context-resolution and capture failures remain attached to the
scope request and are shown as localized outcomes, including failures that happen
before a background job exists. Full diagnostic causes remain in logs.

The capture adapter freezes a scene and its resources under foreground native
operation guards. An isolated native Blender helper evaluates the snapshot on a
dedicated execution lane. Shader captures use Color and coverage AOV taps while
keeping the material output connected; compositor captures use a private output
tap. The helper registers only the minimal PG custom-group types, not the full
extension lifecycle. Native inputs and snapshot files remain App-owned until
physical helper retirement. Only immutable values and arrays enter scope
analysis. Live project graphs, Viewer images and output paths are not capture
scratch space.

Context identities distinguish window/editor consumers and exact nested-group
instances. Each admitted request freezes its graph, resources, scene/view and
required inputs. Revalidation rejects changed immutable authority. Bounded watches
update semantic demand; a compatible active capture can complete during a drag,
and only the newest successor waits. Selected terminal controls reanalyze accepted
pixels; shared upstream uses of the same GradeData remain real dependencies.

Managed upstream PG models are frozen into request values and materialized as
final 65³ payloads and private matrix constants inside the isolated helper. This
preparation never writes live endpoint rows, selects a live bank or waits for a
live LUT publication. Unknown/adopted native dependencies preserve their authored
graph without invented provenance. Snapshot files and helper leases remain owned
until physical retirement, even after logical cancellation. Scope cancellation
never retires independent explicit Bake work.

Each synchronous graph traversal indexes incoming links once per tree. Repeated
socket lookups use that local index rather than Blender's tree-wide
`NodeSocket.links` scan. Graph fingerprinting, dependency discovery, group-instance
discovery and referenced-scene traversal use explicit work stacks. Fingerprint
hashing also handles deep containers iteratively, preserving the previous bytes.
Traversal frames and link indexes are explicitly released on success or failure;
their lifetime does not depend on cyclic garbage collection. Fingerprints exclude
the extension's unused settings on
ordinary native nodes and the sidebar aliases of saved Grade controls; native
operations, input defaults, links, muting, resources and saved controls remain
part of the revision. No persistent graph cache weakens change detection.

Dependencies follow the consumed output: Baked Color depends on the packed Image,
Alpha follows its passthrough input, and muted nodes follow native bypass links.
Those paths do not require unused live Grade models or LUTs. Shared node groups
retain their exact instance paths during traversal.

Validation uses generated Blender fixtures for scene ownership, exact groups,
transparent direct routes, automatic native authority, native HSL/Curves/Color
Balance/Mix/Blur, Render Layers, references, Material/World and viewport
projection. Installed tests exercise the packaged extension and isolated helper.
The manual project remains unchanged and is never a permanent fixture. The
current evidence and limitations are recorded in
[GOAL.md](../perceptual-grade-next-blender/GOAL.md). macOS/Metal remains a
separate acceptance gate; native graph support follows Blender's evaluator and
does not imply every engine/node combination has been tested.

### Scope preparation diagnostics

An authorized native request resolves the editor/owner context, fingerprints the
upstream graph and resources, updates
view layers, revalidates the request, serializes a private scene, snapshots external
or dirty resources, and hashes the resulting inputs. The dedicated capture helper starts lazily,
verifies and loads those inputs, suppresses user File Output nodes, evaluates
Blender, and reduces the completed raster to an analysis grid. Separate numerical
helpers calculate scope data; foreground publication and a matching board draw
complete the visible update.

Shading additionally fingerprints scene materials, world and view dependencies,
reconstructs the viewport camera, and renders Color/coverage AOVs. Compositing
installs a private output tap and evaluates the input's native image domain.
Render Layers inputs also require scene dependencies and rendering. The native
snapshot is shared by Linear, Tone and Color analyses while its identity remains
compatible; each stage does not inherently require another Blender render.

`scopes.capture.enable_diagnostics(True)` opts into a bounded, value-only event
buffer. `diagnostics()` returns independent plain values, including phase costs,
wait reasons, capture identities, submission/adoption events and successful
helper phase timings. Recording is disabled by default and cannot release a
submitted snapshot if optional diagnostic metadata is unavailable. No native
objects, handles or mutable helper message references are retained. The
diagnostic launcher adds execution send/receipt and matching production-board
draw observations without changing the extension's capture policy.

The manual probe accepts an arbitrary local project; it never saves the input:

```sh
buck2 run //products/perceptual-grade-blender/tools/diagnostics:project_probe -- \
  --mode scopes --blend /absolute/path/project.blend --node Grade \
  --scope-owner compositor --workspace Compositing --gui \
  --scope-diagnostics --complex-native --cold-runs 3 --output-dir /absolute/path/new-evidence
```

Repeat with `--scope-page-order reverse` to measure Color-first acquisition.
`--complex-native` measures automatic acquisition and source replacement for a
temporary complex native input after the direct-source checks.
For Shading use `--scope-owner material --material MaterialName --workspace Shading`.
Omitting `--gui` measures headless current-state completion. GUI draw means a
production board callback completed with the matching scope key, not physical
display scanout. Cold runs use fresh processes and helpers but do not clear OS
disk caches. Phase totals are inclusive and can overlap across foreground and
helpers; they must not be added as if they formed one sequential timeline.
Reports retain project/archive/source hashes, scalar events and native/helper
logs. Generated scenes remain the permanent Buck regression inputs.

`ScopeIdentity`, `LinearScopeIdentity` and `ActiveScopeIdentity` are frozen
dataclasses. Their named fields replace cross-module positional tuple indexing.
`ScopeIdentity` exposes these projections:

| Method | Meaning |
| --- | --- |
| `analysis()` | Numerical identity without raster presentation demand |
| `source_projection(stack=...)` | Raw-source cache identity, including the Stack signature when required |
| `scheduler_projection(evaluation)` | Scheduler semantics with frozen evaluation identity; excludes the replaceable Stack signature |
| `capture_projection(...)` | Captured numerical envelope; callers omit publication ownership from cache keys |

The execution codec serializes these records by named fields and rejects missing
or extra fields. Sealing and identity validation accept only explicit immutable
record types and value fields. They reject arbitrary objects, subclasses, cycles
and mutable values hidden inside an identity. Arrays elsewhere in payloads receive
owned, plain, read-only NumPy storage. This is a retention contract, not a general
Python object serializer.

## Verification

```sh
buck2 test //libraries/blender-runtime/tests:execution_runtime //libraries/perceptual-grade-core/tests/execution:identity
buck2 test //products/perceptual-grade-blender/tests/blender:scheduler //products/perceptual-grade-blender/tests/blender:scopes
buck2 test //products/perceptual-grade-blender/tests/blender:scope_context //products/perceptual-grade-blender/tests/blender:scope_capture
buck2 test //products/perceptual-grade-blender/tests/blender:scope_camera //products/perceptual-grade-blender/tests/blender:bake
buck2 test //products/perceptual-grade-blender/tests/packaging:architecture
buck2 test //products/perceptual-grade-blender/tests/installed:standalone
buck2 test //products/perceptual-grade-blender/tests/installed:native_scope_capture
buck2 build //:perceptual_grade //:verify
```

[Verification documentation](../../tools/verification/README.md) separates Lean
color-model theorems, source-bound `.inv`/Z3 machine proofs, Python/native
regressions and archive integrity checks. `//:verify` includes all machine proof
groups and retained Lean mathematics. Both Blender packages require proofs for
every shipped generated contract and compare the ZIP inventory and exact bytes
with declared sources. Solver and proof payloads stay outside runtime archives.
The former machine proofs and native source inventories remain historical
material in the external `perceptual-grade-proof-archive` directory.

## Native publication boundary

Coverage remains incomplete (`coverage_complete=false`). Output publication
requires a non-reentrant main-thread interval without active native readers.
The adapter checks public job kinds, interface locking, active callbacks,
paired render/compositor evaluations and known modal readers before transfer,
packing, scalar selection and notification. Native image update is
not an atomic publication operation or a general reader barrier.

The shared source-bound `native_evaluation` machine owns exact evaluation leases,
generation and acknowledged observation revision. Native callbacks only enqueue
scalar observations and revoke prior readiness; ordinary foreground polling,
recovery and cleanup drain them into the actor. Passive UI reads the immutable
acknowledged snapshot, and live job checks finish with a revision recheck.
Compositor pre/post-or-cancel pairs and whole-render init/complete-or-cancel
pairs supply native receipts; a render's per-frame post does not end its lease.
Repeated starts retain separate leases. Blender supplies scene identity, not
operation IDs, so native pairing remains an integration-tested premise; captured
duplicate or foreign-generation receipts cannot release another machine lease.

Bake drawing, operator polling and admission share this readiness boundary in
both editors. Playback stop never retires a lease. Unacknowledged completion,
active native jobs/locks and pending actor transitions keep the control disabled;
localized hover help explains the wait. Transient race clicks create no request
or snapshot and do not report an error. Only the recovery coordinator's confirmed
native replacement can clear old evaluation debt. These checks preserve automatic
stored-source scopes and the independent explicit Bake queue.

USD and Alembic export use private job kinds outside public job queries. Their
initiating operators can finish before the worker sets the interface lock, so
there is an interval in which the current checks can admit publication while
export has begun. Neither main-thread execution nor a second lock check
establishes exclusion for every native reader. This remains an open acceptance
boundary, independently of render-engine choice.

Guarded Save/Render entrypoints finish managed intent and preserve unchanged adopted
output before native invocation. Explicit portable wrapper conversion preserves
links, values and Image bindings while carrying adoption through conversion. Save
restoration uses its original wrapper kind and driver mute value; an already native
wrapper stays native. Ordinary refresh preserves that identity even when a control
change resumes production, so active Bake requests retain their target.
Native invocation handlers can record failed preparation but cannot veto native work.
Interrupted live transfers retain same-generation repair obligations; acknowledged
native replacement retires their old runtime authority. These mechanisms do not make a torn
project file readable or prevent Blender from reading before recovery handlers.
Installed crash/save/load tests provide finite regression evidence for the
tested paths. macOS/Metal acceptance remains open.
