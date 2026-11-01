# State-machine design for reliable evaluation and preparation

Date: 2026-11-01  
Revision: native Grade, reference-aligned Stack, Bake and Linux acceptance handoff

**Status: design choices are settled. Core numerical/workflow policies, static
native preparation, exact owner receipts, scope/Gizmo composition and viewport
capture, frozen Bake sources, durable field/tree recovery, owned Save/Render
continuations and the four agreed File/Render menu redirects are implemented.
Packaged Blender 5.2.2 tests exercise direct Image, UV and Compositor Grade Bake
through registered operator poll/execute, plus package save/reopen, idle Restart,
modified-Image Save diagnostics and viewport statistics/charts. A five-owner
readiness regression and per-window viewport fallback/transfer tests pass.
One installed crash/reopen fixture also passes for a saved binding-only partial
transaction with the owner marked `PENDING`. Grade and Stack now reject both
ledger forms and compare installed content with accepted manifests. Recovery,
snapshot inventory and cleanup defects still remain, and the current recovery,
Stack and installed smoke targets fail. Coherent scope batches, reader/fault
interleavings, broader crash/autosave/Undo, Restart under active work, and the
complete Linux/Blender acceptance matrix remain open. The unbounded readiness
kernel proof passes 170 obligations and 4 mutation checks; production record
conversion remains outside that proof, and no fresh aggregate receipt is recorded.**
[GOAL.md](GOAL.md) and [CHECKLIST.md](CHECKLIST.md) track the
implementation handoff.

Implement this design in `libraries/perceptual-grade-next-core` and
`products/perceptual-grade-next-blender`, using Python packages
`perceptual_grade_next_core` and `perceptual_grade_next_blender`. Preserve the
current `perceptual-grade-core` / `perceptual-grade-blender` implementation,
tests, Buck targets and historical evidence for comparison. Instructions below
to merge authorities or remove animation apply to the new pair.

Start with the desired complex properties, then choose state and operations that
make them expressible. Existing machine boundaries are replaceable in the new
implementation. “Coordinator” and “regular state machine” are organizational
labels, not different semantic kinds or mandatory layers: both use checked
transitions and generated contracts. Merge coupled authorities now; a later split
must preserve the merged properties.

Only Grade/Stack parameters are non-animated. Inputs and scenes may animate;
scopes still refresh on frame changes after native evaluation finishes, pause
during playback, and refresh after playback stops and evaluation finishes.
Animated Grade controls, texture sequences and deduplicated texture banks remain
deferred. This handoff starts Next implementation with the current native Grade
layout; the original node-count goal and known alternating-extremes GPU finding
are recorded deferred work, not prerequisites for this implementation or release.

## 1. Desired complex properties, in natural language

The central requirement is:

> Every result presented as current belongs to the user's current intent and a
> completed, coherent generation. Closing, changing inputs, playback, cancellation,
> Save, Render, Undo, load and crashes cannot turn incomplete or obsolete work into
> current output, lose physical obligations, or prevent dismissal of the Gizmo.
> Required derived preparation converges to ready or an explained waiting,
> unavailable or failed state. Reopening reconstructs unfinished preparation from
> the document actually opened.

### P1. A visible scope makes coherent progress

Opening a Grade or Stack scope acquires its effective input and analyzes it using
the applicable grading settings. The coherence unit is the **visible page's
measurement bundle**: its rasters, primary/reference overlays, interpreting axes,
frame labels and provenance belong to one source batch, frozen analytical revision
and compatible layout. Statistics appear only when they match that exact visual;
otherwise they are pending or unavailable.

Compatible, uncancelled work may provide progressive results during edits.
Current controls can move ahead of a retained measured result, but that result is
clearly Updating and keeps its own axes and labels. Hidden pages may cache older
bundles; they do not impose an all-pages publication barrier. A newly selected
cached page displays its actual provenance, not another lane's newest metadata.
Repeated demand must not discard every useful compatible completion indefinitely.

Once demand stabilizes and healthy services receive fair execution, the displayed
page reaches that demand or a defined failure. A constant Color may correctly make
one dot. A varied evaluated image must not collapse to one dot because capture
omitted its lighting context.

### P2. Cancellation cannot reverse

Returning to the same semantic input creates a new request; it cannot reactivate
a cancelled attempt. Cancelled work cannot obtain a new operation grant, advance
to another submission, publish new results, or fail or fulfill its successor.
Operations already granted before cancellation remain accounted for under the
start/receipt protocol in section 5; their late receipts cannot restore authority.

Settling an old request cannot erase newer demand, even when both have the same
semantic key. A previously accepted display may remain explicitly stale when
appropriate. That retained result does not make its cancelled producer live again.

### P3. The single Gizmo can always be dismissed independently

There is at most one visible Gizmo across the extension's windows/editors.
Opening it elsewhere moves ownership and revokes the preceding view's authority.

Once Blender dispatches a release inside the X armed by its matching press, the
Gizmo hides and old draw/publication authority is revoked immediately. This does
not require Grade reads, new RNA ownership, an actor round trip, scope cleanup,
gesture completion or Undo. Release outside, Escape, focus loss and
editor replacement cancel the armed close click.

The guarantee begins after Blender dispatches the event; it cannot make Blender's
own blocked main event loop dispatch Python events.

### P4. Late work cannot cross a lifetime boundary

Every completion retains its original App, owner/editor incarnation, demand,
batch, submission and operation identities. Native-to-direct source changes,
target deletion, editor replacement, close/reopen, Undo and load never relabel
old work as current. Obsolete receipts take defined accounting/discard paths and
cannot dispatch through a destroyed actor or fence unrelated editing.

### P5. Logical completion and physical completion are different facts

Started workers, returned handles, snapshots, native readers, borrows and partial
effects remain owned until their exact terminal, release or repair receipts.
This includes handles returned after cancellation. A timeout, exception,
consumer done flag, hidden panel or playback stop cannot certify retirement.

An older batch remains owned while any live analysis, staged effect or accepted
display references it. Disjoint private retiring work need not block every new
operation, but its capacity and cleanup obligations remain real.

### P6. Capture evaluates the intended source

Material scopes follow the last-used 3D Viewport in the same window, falling back
to the largest available viewport and then the established camera fallback.
Capture includes effective engine, lighting, World, projection and visibility.
Material Preview's studio environment is part of the input when active.

**Authored World scopes are an explicit exception:** they inspect the selected
authored World even when Material Preview displays a studio HDRI, and are labelled
**Scene World**. They do not require the user to change viewport settings.

Primary/reference preparation uses one coherent environment and source revision.
Helpers consume immutable snapshots and do not change the user's scene engine or
World. Direct original-Image sampling retains its data semantics.

Shader Image/UV Bake remains separate. Scope lighting substitution cannot change
Bake eligibility. UV Bake requires the scene's Cycles engine; Shader to RGB and
other unsupported routes disable Bake with an explanation.

### P7. Bake readiness reflects relevant facts and actual admission

Cosmetic names, layout, node selection, unrelated graphs, inactive settings and
generated transform publication do not invalidate another Bake's eligibility.
Playback, actual native readers, destination conflicts and unsupported routes
disable the button with a useful explanation.

A cached eligibility verdict does not authorize a click. The click freshly checks
effective inputs before reservation, freezing or submission. A newly discovered
blocked route updates the defined outcome and returns normally. No raw exception
popup is an expected user flow.

Eligibility and evaluator readiness are distinct. A supported Stack with only a
33³ preview can accept a Bake request that waits for its matching 65³ final;
pixel evaluation cannot start until that final is committed and frozen. A Grade
waits for its one complete native graph revision. This wait has a preparation
owner and preserves the existing cancellation and destination-ordering rules.

### P8. Waiting and failure have an owner and an exit

Every pending state names real work, a dependency, resource capacity or a live
service responsible for progress. A lost timer cannot leave permanent unexplained
Preparing. Cancellation, obsolescence and native waiting are not failures.

After existing worker retries/fallbacks are exhausted, a local failure preserves
valid prior output and offers explicit Retry or a meaningful corrective edit.
Unchanged polling does not retry forever. Scope failure must not disable Add
Grade or unrelated editing. Real infrastructure failures remain safely fenced;
dismissal and the separate Restart Perceptual Grade action stay available.

### P9. Editing and explicit Bake retain their established semantics

An unfinished Image/UV Bake interrupts on relevant Grade, Stack, binding or source
changes, playback, or accepted Save. It preserves the previous committed Image and
requires a fresh click. Returning to the original input does not revive it.
Recovery never automatically resumes an explicit Bake.

Ordinary gesture release commits without keyframing; genuine uncommitted
cancellation restores the original live target. Already accepted native numeric-field commits
remain commits. Close only changes visibility immediately; settlement is separate,
exactly once and bound to the original target. Undo/load discard obsolete gesture
settlement without writing old values into restored data.

Preserve native Image selectors, + New and rename behavior, the separate Bake
row, the Vector name, private implementation sockets, Grade/Stack controls and
current-format save/Undo restoration. New bake Images receive no forced fake user.
Existing explicit flags are untouched; no migration is introduced.

### P10. Static grading remains coherent while inputs and scenes animate

A Grade output uses one completed forward native node tree for interactive and
final evaluation; there is no separate Grade preview transform or quality tier.
A Stack may publish an intermediate 33³ preview before its 65³ final. Each
published graph/LUT, packed field, endpoint matrix and native binding belongs to
one authored intent and backend numerical contract. A Stack preview never grants
final readiness for Bake, Save or Render. A frame change alone does not change
these transforms or request preparation. Explicit Grade/Stack edits create new
preparation demand.

This version supports no animation of Grade/Stack controls or selections and no
animated LUT sequence. Remove that implementation from the new pair. Unsupported
authored animation receives an explained unavailable outcome; it is never silently
sampled at one frame, frozen, stripped or migrated.

Animated input Images, upstream nodes, the Grade's input Color and ordinary scene
animation remain supported. While playback is stopped, frame changes request
fresh scopes once native evaluation finishes. Playback pauses acquisition and new
scope publication; stopping it requests the current frame after actual native
completion. Scope source identity includes frame when relevant, independently of
static Grade preparation identity.

Prepare static outputs automatically after meaningful edits. Save/Render waits
for required final-quality outputs, then invokes Blender once. Native movie and
image-sequence rendering use the same installed static transforms; their encoding
and frame iteration remain Blender's responsibility.

### P11. Every derived preparation is fenced and recoverable

A preparation is complete only after its required computations, producer
retirement, packed assets, matrices, native bindings and
publication receipts actually establish completion for the current intent.
Queue acceptance, progress 100%, a returned handle or a metadata boolean is not
completion.

Record incomplete intent before effects that could otherwise resemble completed
output. Retain the previous committed generation until replacement is verified.
Distinguish asset readiness, native output commitment and serialization to disk.

Reopening validates the actual authored data and prepared representation in the
.blend or autosave opened. It automatically finishes or rebuilds missing,
incomplete or mismatched derived preparations. Verified pieces may be reused.
Recovery is idempotent and uses fresh requests and ownership, never replay of old
actor grants or process handles.

This does not recover edits absent from the opened file, automatically resume an
Image/UV Bake, reopen the Gizmo, or repeat a pending Save/Render operation.

### P12. Save and Render have explicit relationships with preparation and Bake

Accepted Save revokes unfinished Image/UV Bake publication and blocks new explicit
Bake admission while saving. It saves committed Images and complete required
derived preparations. A Bake committed before the cancellation barrier is included;
a completion afterward cannot enter that save. Cancelling Save As's file picker
before Save acceptance does not cancel Bake.

Render uses committed Image contents/bindings for the whole operation, including
animation-frame gaps. Bake computation may continue when its inputs remain valid,
but its publication waits until native rendering actually ends. A relevant input
change still interrupts the Bake, regardless of who caused it.

Common Save/Render actions wait for one complete preparation barrier and then
invoke Blender normally. The extension does not render animation frame by frame.
Prepared data does not bypass native-reader exclusion for later mutations.

### P13. Restart preserves the project and cannot abandon an old session

Restart Perceptual Grade is owned outside the failed computational App.
It revokes admissions, dismisses the Gizmo, drains necessary obligations,
preserves committed outputs and current-format controls, detaches exact old
registrations, then starts and validates a fresh session.

No new App starts before the old session's terminal teardown receipt. Failure
retains the exact restart phase and cleanup ledger for Retry Restart. Elapsed
time never substitutes for teardown, and an App fence alone does not prove
preservation or cleanup occurred.

### P14. Bake preserves the accepted native evaluator

A Grade Image/UV Bake evaluates the accepted Grade node tree's output for the
frozen source and settings revision. A Stack Bake evaluates the accepted 65³ LUT
with its actual native shaper, lookup/interpolation, packed transport and endpoint
matrices. Neither Bake substitutes a separately implemented analytic or custom
GPU-helper pixel-grading program. Blender's native CPU/GPU evaluation is allowed;
a helper process may host that native evaluation and return its pixels.

The Bake descriptor and result receipt bind the evaluator kind, final quality,
authored revision, complete packed assets, matrices, native context and source
snapshot. A matching immutable copy of the accepted native evaluator may execute
in a private snapshot; merely copying its settings into another grader cannot
satisfy this property. Relevant edits interrupt the request. Private completion
does not permit publication without current authority and reader exclusion.

A custom GPU grading program may generate and validate the Stack LUT's lattice
values before publication. Its LUT-generation result grants no Bake result or
final-output authority by itself. This restriction does not prohibit a helper
process from hosting the accepted native evaluator for Bake capture.
Scene-linear Color/Alpha output is captured before display/view transforms;
source sampling, UV coverage and alpha follow the declared native Bake route.

### P15. Controls and directed Stack evaluation share the current reference contract

Standalone Grade remains forward-only. Stack entries support forward and inverse
directions using the current analytic reference's equations, order, raw appearance
handoffs and endpoint matrices. In particular, low/high chroma membership uses
`C=(35/75)*abs(J_A)` with frozen post-Tone drivers; the retained old-core
capacity-based crossover cannot stand in for the new model.

Inverse results preserve the reference's finite found-root search contract and
forward-reproduction residual reporting. An approximation is not proof that a
target is unreachable, and no unique inverse is promised. Matching adjacent
forward/inverse nonlinear stages retain their defined raw-handoff cancellation.

Authored values, UI controls, reset/default behavior and numerical preparation
use one Next settings schema aligned with the full reference model. The supported
grading context is fixed to D65 and 203-nit reference white; UI presets and
serialization cannot request unsupported white/reference-nits contexts. Tone Fit is
`[-2, 2]`; separate lightness and chroma Fits are `[-2, 6]`. Sidebar, Gizmo,
numeric entry, reset and serialization agree on those domains. These are the
supported product controls; the analytic oracle's wider finite-input domain is
not an additional UI range.

## 2. Audit decisions, ownership and scope

These are the user's settled behavior choices and the selected implementation
boundaries. Section 15 lists evidence still required, not unresolved product
choices.

| Topic | Audited decision |
| --- | --- |
| Implementation location | New `perceptual-grade-next-core` / `perceptual-grade-next-blender` pair; preserve the current implementation |
| Computation ownership | Actor-owned scope workflow with independent foreground UI |
| Gizmo ownership | One visible Gizmo globally; opening another moves it |
| Viewport selection | Last-used 3D View in the same window, then largest fallback |
| World scope | Inspect authored World; label Scene World |
| Local failure | Explicit Retry after existing retries/fallbacks; no blind loop |
| Machine merger | Merge Bake, native output and recovery wherever joint properties require; no mandatory coordinator/regular split |
| Common output UI | Integrate Save, Save As, Render Image and Render Animation actions/shortcuts |
| Save during explicit Bake | Cancel unfinished Bakes after destination/confirmations; save committed Images |
| Render during explicit Bake | Use committed Images; defer Bake publication through the whole render |
| Grade animation | Remove support and implementation from the new pair, including auto-keying and per-frame LUT controllers |
| Animated inputs and scopes | Retain frame-change updates after native completion, playback pause and update after stopping |
| Static preparation | Complete verified kernels per owner; all required owners ready before Save/Render |
| Grade evaluator | One forward native node tree and fixed helper layout; no separate preview grader |
| Stack evaluator | Current-reference forward/inverse entries; 33³ intermediate preview and 65³ final LUT |
| Explicit Bake source | Accepted native Grade output or accepted 65³ Stack lookup output; no separate analytic/custom-GPU pixel grading |
| GPU-helper scope | Custom GPU grading may generate/validate Stack lattice values; a helper may host native evaluation, but separate analytic/custom-GPU pixels cannot substitute for native Bake output |
| UI schema | Full current reference control mapping in fixed D65/203-nit context; Tone Fit [-2, 2], Color Fits [-2, 6] |
| Deferred numerical work | Original fewer-than-1000-node goal and known alternating-extremes GPU error remain reported and do not block this handoff |
| Persistence | Self-contained packed derived assets with real native ownership for staged resources |
| Save dialog integration | Owned confirmation followed by preparation and native execution; accepted compression-default difference, no workaround |
| Crash authority | The .blend/autosave actually opened; no unsaved-edit restoration |
| Crash restart scope | Derived preparation automatically; explicit Image/UV Bake requires a new click |
| Terminal service fault | Explicit Restart Perceptual Grade action |
| Fake users / compatibility | No forced fake user on new bake Images; no historical migrations or compatibility code |

The earlier prepared-Grade-animation design, image-sequence-only Render restriction,
per-editor foreground scope Store and scope-only redesign are superseded. Native
scene animation and animated input support remain part of this design. The
standalone `perceptual-grade-nodes` library has a
[current schema-5 handoff](../../libraries/perceptual-grade-nodes/EVIDENCE.md): boundary
geometry is generated at build time, Web uses 1D fields, and Tone/Color/Web/toe/
Compact cells are 256/8192/4096/1536/3072. Its packed payload is 5,076,560 bytes,
including the fixed boundary. Next integration is now the implementation task.
The original node budget and known `web_alternating_extremes` GPU error remain
deferred, with their evidence retained; neither is silently marked passed or
made a required fix for this delivery. New integration regressions retain their
own acceptance obligations. This design update does not implement Next.

### 2.1 Preserve the current pair and isolate the new implementation

Keep the current pair's source, tests, Buck definitions and package behavior
intact. Existing `//:perceptual_grade` and `//:verify` targets continue to describe
the current implementation. DCTL and the reference library retain their current
core dependencies. Documentation may identify that preserved baseline and link
to this design; historical evidence does not certify the new pair.

The new core owns its numerical models, value records, catalogs, checked policies,
requirements and proof inventories. Port necessary Grade-specific mathematics
and assets with provenance and numerical checks. Its runtime must not depend on
the old core runtime: the old model target also brings its old machines into the
closure. The new product owns Blender/UI adapters, composition and acceptance.
Use distinct Python component names so Buck can enforce ownership in both the
development and installed namespaces.

Reuse generic `color-core`, `invariant` and `blender-runtime` facilities. Start
with their existing public APIs; no broad shared-runtime rewrite belongs here.
If a narrow additive API is necessary, document it and validate all existing
consumers. New product authority stays in the new pair. Shared dependencies mean
preserving the old pair is a source baseline, not a claim of bit-identical builds
under arbitrary future changes; record exact source and package identities.

During implementation, add independent next proof/package targets and planned
root aliases `//:perceptual_grade_next` and `//:verify_next`. These targets do not
exist in this documentation scaffold. Do not switch existing aliases. New package
proofs bind to its actual new sources and generated contracts; old certificates
cannot stand in for them. Reference comparisons may use old/reference code in
test-only dependencies without importing old workflows into the new runtime.

Use separate Blender profiles/processes to compare packages. Retain extension
identity `perceptual_grade`; simultaneous enablement with the
current Grade product is outside this work because RNA/operator registrations
share public names. No coexistence or migration mechanism is requested.

## 3. Evidence and its limits

| Observation | Finding | Property |
| --- | --- | --- |
| Supplied Shading graph, Principled → Shader to RGB | Scene World yielded 2,340 identical samples; preview HDRI yielded 2,320 distinct colors | P1, P6 |
| Hide/reopen same scope while old work retires | Adapter recomputed keep permission and collected a cancelled handle | P2, P4 |
| Native input becomes direct Color | Observation closed a record before a callback dispatched through it, fencing the App | P4, P8 |
| Toggle another Grade's pencil | Unrelated Bake became checking for about 0.25 seconds with native guard ready | P7 |
| New-result Image creation | Code explicitly forces fake user although bindings already retain used Images | P9 |
| X event path | Visibility change follows ownership/gesture-dependent work | P3 |
| Save during explicit Bake | Wrapper replacement currently indirectly cancels the old target; this is not an explicit Save barrier | P12 |
| Restored incomplete LUT | Current tests expect preservation-only adoption, with no automatic rebuilding | P11 |

The native-to-direct failure is a separate reproduction, not confirmation of the
user's exact pencil-only global-hang sequence. The newly-created-node missing-UI
report was withdrawn as unreproducible.

Static publication probes on pinned Blender 5.2.2 showed that an interface-identical
kernel replacement can preserve external links and socket defaults, and real
Scene/ledger NodeTree references can retain prior/candidate kernels across reopen
without fake users. They support the design in section 10; production content
validation, failure compensation and platform coverage still need acceptance.

Earlier animated-LUT transport probes are historical investigation only. They do
not add timeline sampling, paging or Grade animation requirements to this version.
Relevant investigation artifacts include:

- ../../buck-out/shader-scope-investigation/ and ../../buck-out/fake-user-investigation/
- /tmp/pg-guard-ui-investigation/
- /tmp/pg-preparation-commit/

Artifacts are not permanent test dependencies. Synthetic scenes replace the
supplied project in acceptance tests. The supplied train-model.blend is read-only,
SHA256 81d89bbddaaffb153652aaef3787fcede987a941841e1dbddcde92f592c24dcd.

## 4. Derive machine boundaries from the properties

### 4.1 One ScopeActor per computational App

Merge scope demand, input acquisition, analysis workflow, scope-specific channel
admission and display acceptance into one actor-owned **scope_session**. Keep one
long-lived ScopeActor per App; editor, target and view generation are data, not
reasons to destroy the actor. Implement this authority in the new core/product;
do not bring competing baseline scope Stores into its runtime closure.

The actor persists while old submissions retire. A source-route change or
close/reopen cannot invalidate the actor needed to account for their receipts.
Only actual App teardown destroys it after obligations settle.

### 4.2 Foreground view authority outside the App

An extension-lifetime foreground **ViewAuthority** owns global visibility, owner
editor incarnation, view epoch and armed-close identity. It survives computational
App failure. The X path executes a bounded checked transition against cached
geometry; it never calls synchronous Store dispatch, App admission or actor state.

Any pg_diagram_enabled RNA value is a derived mirror, not another lifecycle
authority. Drawing uses committed display tokens plus current foreground
visibility/owner/epoch; a stalled actor cannot keep a closed Gizmo visible.

### 4.3 Merge coupled project workflows

Create one actor-owned **project_workflow** for joint product admission:

- The eight-entry explicit Bake queue, its two physical worker leases, destination
  ordering, immutable request intent and manual publication state.
- Static derived preparation generations and per-owner publication.
- The current Save or Render operation and its preparation/native-retirement gates.
- Product lifecycle, replacement/recovery generation and activation decisions.
- Native effect tickets, partial-effect repair and old-generation retirement debt.

Implement the required Bake/queue/publication/output/lifecycle/recovery behavior
in this model in the new pair. Preserve the old implementation separately; its
Stores must not also decide admission in the new product.
Resource-bank metadata and caches may remain separate implementation services,
but cannot grant semantic publication or completion on their own.

This merger makes Save cancellation, whole-render Image exclusion, preparation
commit and load/recovery fencing directly relational in one authoritative state.
It does not require putting the ScopeActor's analysis semantics in that actor.

### 4.4 Retained boundaries

| Boundary | Responsibility and interface |
| --- | --- |
| Physical execution | Process capacity, retry/fallback, exact submission and retirement receipts; never decides semantic relevance |
| Native evaluation guard | Actual Blender readers, callback revisions, jobs/locks and mutation admission; no workflow can clear its leases |
| Ownership/structural effects | RNA lifetimes, borrows, exact native effects and compensation; retains unresolved debt |
| bake_preflight | Observed eligibility and reasons; no authority to submit or publish |
| Foreground effect gateways | Consume exact grants once and check live prerequisites before short native effects |
| Extension supervisor | Restart/status/registration ownership outside the computational App |
| Snapshot/model/GPU adapters | Observe or materialize data named by immutable IDs; no independent workflow decisions |

The foreground supervisor owns checked restart state and exact registrations.
It retains retiring Sessions strongly until cleanup is complete. Recovery inside
a healthy project workflow and replacement of a terminally failed App are distinct
operations with distinct receipts.

A future split of merged authority requires a refinement or explicit
assume-guarantee argument preserving observable traces and resource obligations.
Names in Buck directories do not supply that argument.

## 5. Execution ownership, identities and effect protocol

### 5.1 Exact identities

| Identity | Meaning |
| --- | --- |
| Extension / App lifetime | Supervisor lifetime versus one computational Session; old App receipts never become new App grants |
| Editor incarnation / view epoch | Stable editor lifetime plus immediate foreground revocation on hide, owner transfer or replacement |
| Document / owner / desired revision | Opened-data ownership and current authored intent; fingerprints include applicable context |
| Demand occurrence | Fresh meaningful request or reopening; equal polling does not allocate a successor |
| Semantic recipe | Immutable source or numerical identity; reusable content, never execution authority |
| Acquisition batch / preparation set | Frozen source pair or complete generated output candidate |
| Analysis / preparation request | One logical, cancellable attempt to satisfy a particular demand |
| Submission | Fresh identity for every JobHandle, including register/update phases |
| Operation / start grant | One proposed effect and its one-shot authorization |
| Preview / payload / descriptor | Immutable candidate identity and original provenance |
| Service registration | Exact timer/pump incarnation; old failure cannot stop a replacement |

Raw pointers and names are discovery hints, not durable identities. Receipts
carry captured identities rather than filling fields from current selection.
A→B→A creates successive desired revisions even when content can be reused.

Machine state contains admitted scalar IDs, finite labels, booleans, frozen
records and bounded structures. RNA, arrays, GPU objects, files and JobHandles
remain in owned adapter records addressed by those IDs.

### 5.2 Asynchronous proposal, grant, effect and receipt

Use the same explicit ordering for scope and project effects:

1. **Propose:** the actor reserves an operation with exact input/resource IDs.
   A proposal alone authorizes no effect.
2. **Request start:** the foreground gateway asynchronously returns that proposal
   identity to its actor.
3. **Grant:** the actor rechecks current authority and consumes the proposal into
   one start grant. This transition is the **in-flight linearization point**.
4. **Execute or abort:** foreground consumes the grant once, rechecks current
   view/source/playback/lifecycle authority, native guard and ownership where
   required, then runs the short effect or returns aborted-before-body.
5. **Acknowledge:** success, abort or failure-with-debt settles that exact operation.
   No partial failure is translated into a no-resource receipt.

Cancellation processed before grant prevents execution. Cancellation after grant
retains an in-flight obligation, even if the body has not started. A newly observed
foreground close/source/playback barrier can still reject that grant before its
body. Do not claim that an actor can magically retract an already delivered
instruction from another queue.

Post-grant cancellation prevents new semantic acceptance or phase advancement;
its receipt still accounts for handles or staged resources returned. Duplicate
grants/receipts cannot execute or settle twice. A successful receipt accepted
before cancellation is past committed history, not a post-cancellation update.

Foreground observation records immediate source/playback/owner revocation before
enqueueing its actor notification. Compatible numeric edits must not
indiscriminately revoke every progressive result and cause starvation.

The existing App Store interface is synchronous. Add a narrow exact-envelope
asynchronous bridge over ActorHost/ActorRef (or its corresponding public runtime
API), retaining every unresolved Future through its receipt/fault. X and drawing
must never call synchronous dispatch or wait for that bridge.

### 5.3 Staging precedes visible acceptance

Materializing a visual creates a new non-drawable payload ID. Its successful
receipt returns to ScopeActor. Only acceptance by the still-admissible request
produces an accepted-display token. Before adopting any new visual or attaching
statistics, a checked foreground transition rechecks current view owner/epoch,
source/continuity, playback and lifecycle authority. It rejects new adoption
while paused, including a token issued before the actor received the pause event.
Already installed displays may remain visible and explicitly stale during
playback; retaining them is different from adopting a new token.

Foreground adoption returns an exact applied/discarded receipt. The actor tracks
issued versus actually applied bundles and cannot declare display fulfillment
from token issuance alone. The foreground's old display/resource edge remains
owned until replacement or dismissal is acknowledged; delayed delivery cannot
free the bundle still being drawn. Drawing checks current view owner/epoch, so
closing revokes it immediately even while actor acknowledgement is delayed.

Do not overwrite the accepted binding while a replacement is merely staged.
Statistics attach only to the exact accepted visual's batch, analysis and
submission; mismatched statistics must be absent from the drawable result, not
merely accompanied by a status field the UI may ignore.

### 5.4 Checked composition and its boundary

Put the actual scope step, view_step and gateway_step functions and their frozen
types in one source-bound policy module. ScopeActor uses the ordinary checked
step. The small foreground authorities use declared, checked Machine.call
functions and a thread-owned wrapper committing precisely the returned state;
they do not require an open App Store. Prove close/delivery and acceptance traces
using these actual functions, not a second approximate composition implementation.

Put the actual project step, project gateway, static preparation validators and
foreground restart transitions in the new core's project policy module as checked
functions. The project actor commits its step; foreground wrappers commit exactly
the state returned by their checked calls. Compose traces through those production
functions to establish Save/Render, repair and restart relationships. They do not
require one shared mutable actor/foreground object.

ProjectWorkflow's typed resource grants form an explicit assume-guarantee boundary: Project proves
issuance, exclusion and grant lifetime; Scope proves exact bound consumption and
required admission. Authentic one-shot transport and exact return routing remain
adapter premises. This is not an already-executed cross-module joint-state proof.

Where a promised property needs simultaneous semantic facts beyond that grant
contract, merge or co-locate the relevant production transition authority before
claiming the property proved. Neither arbitrary imported helpers nor a
validated=True field supplies a composition proof.

The current product calls the source-bound `scope_step`, `foreground_step` /
`foreground_can_apply` and `restart_step` policies from its ScopeActor,
ViewAuthority and RestartSupervisor adapters. The scope policy prevents repeated
starts for a demand, excludes playback and existing physical debt, and separates
issued from consumed display receipts. Foreground close/transfer revokes the
prior epoch, and adoption consumes its matching receipt once. These policies
remain separate modules; their passing proofs and adapter traces do not establish
the complete joint native grant/resource protocol required above. The
[coverage inventory](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
records exact assertions and unrepresented canonical requirements, including
statistics/batch coherence and native service/resource lifetimes.

## 6. Scope state, transitions and operations

### 6.1 Bounded state

| Region | Contents |
| --- | --- |
| Observed owner | Current editor/target/occurrence and captured foreground view epoch |
| Service | Healthy/paused/waiting/failed/retiring; playback epoch, native resume barrier and service incarnation |
| Desired input | Newest occurrence, source/environment/continuity identity, frame and analytical revision |
| Acquisition | One active physical batch, fixed primary/reference members and newest pending demand |
| Accepted input | Coherent immutable source batch and provenance |
| LINEAR and full lanes | One active request and newest pending demand per lane |
| Request/submission | Logical phase, handle identity/kind, physical status, terminal-read status, preview sequence and candidate IDs |
| Operation | One scope adapter operation slot with proposal/grant/receipt and compensation status |
| Display | Existing eleven cached slots: linear, tone, Stack overview, four Warp and four J/C pages; each distinguishes issued tokens from its last foreground-applied bundle |
| Obligations | Retained batches, payloads, submissions, staged operations and display references |

Logical request state is active, retiring or settled. Physical submission state is
independently none, reserved, live or physically retired. Healthy physical
retirement may permit terminal collection; it is not itself logical cancellation.

One synchronous scope effect runs at a time. Physical helper work retains the
existing capacity and fairness rules. Cancellation keeps the physical slot until
real retirement; new demand replaces only the pending slot, bounding debt.

Occupancy is resource-specific. A direct constant Color batch needing no capture
worker may progress while an obsolete native capture retires, provided the
necessary operation/analysis slots are free. Old capture debt stays owned.

### 6.2 Transition rules

| Event | Required behavior |
| --- | --- |
| Open/reopen or move Gizmo | Foreground advances ownership epoch; actor gets fresh demand, preserving old debt |
| Equal observation | Preserve occurrence, useful work and settled failure |
| Compatible analysis edit | Keep useful uncancelled progress; replace newest pending analysis demand |
| Incompatible source/route change | Revoke affected requests; preserve obligations; observe newest source |
| Begin playback | Advance foreground/actor playback epoch; revoke active acquisition/analysis authority; retain accepted display |
| End playback | Wait for actual native readiness, then service fresh newest demand; never revive a pre-playback attempt |
| Close X | Hide/revoke in foreground immediately; actor cancellation follows asynchronously |
| Retry | Fresh attempt/service incarnation for the failed dependency |
| Editor/target removal | Revoke semantic ownership; retain original actor for accounting |
| Old settlement | Settle only its original obligation, never successor demand or failure |
| App teardown | Destroy only after all actor-owned obligations have terminal dispositions |

Playback prohibits new scope acquisition/publication. It does not implicitly
commit or revert grading gestures. Blender continues evaluating animated inputs
through installed static Grade transforms. Stopped-frame changes and playback
stop both request fresh scopes after actual native readiness.

### 6.3 Operation admission

| Operation | Required authority and receipt |
| --- | --- |
| Observe/freeze source | Current acquisition and native admission where needed; exact immutable batch or defined unavailable/failure |
| Submit | Valid input/control acknowledgement and free physical slot; every returned handle remains owned even after cancellation |
| Poll retirement | Existing exact obligation, including cancelled work; grants no result-use authority |
| Read preview | Grant issued while active, matching computation handle and new immutable preview occurrence |
| Read terminal result | Matching physically retired producer, active request at grant and terminal read not yet consumed |
| Advance register/update | Consumed matching ready/needs-seed acknowledgement; allocate a new submission identity |
| Stage/publish visual | Matching candidate, compatible demand, unpaused current view/lifecycle and successful application receipt |
| Attach statistics | Exact visual identity and current acceptance authority |
| Cancel/release/repair | Existing exact obligation; visibility is not required |

The phased register → ready → update and update → needs-seed → register paths
remain, but every new JobHandle has a new submission serial. Runtime-internal
fallback stays runtime-owned. Do not read a cancelled handle because a later
visibility calculation says to keep its semantic key.

A request can settle only its own preview, terminal read and control
acknowledgements. A statistics failure may leave an accepted visual with
statistics unavailable; it cannot become an invented capture failure.

## 7. Effective source observation and immutable snapshots

Add a versioned value-only shader environment to native scope descriptions:
effective engine, scene-light/World flags, studio HDRI content digest, intensity,
world-to-environment rotation, projection and applicable visibility. Transport
paths are not semantic identity. Advance the recipe namespace without an old
format compatibility branch.

| Context | Scope source |
| --- | --- |
| Material Preview material/light scope | Eevee plus effective preview lighting/World flags and studio HDRI |
| Rendered viewport | Scene engine and effective rendered-viewport settings |
| Solid/Wireframe | Existing scene rendering semantics with selected projection |
| Camera fallback | Scene engine, scene lighting/World and camera |
| Authored World scope | Selected authored World, explicitly labelled Scene World |
| Compositor / direct Image or Color | Respective evaluation/data semantics; no preview-lighting substitution |

Observation and freezing must normalize the same environment. Inactive studio
controls and display-only blur/opacity do not change material source identity.
Preserve real geometry, camera, visibility and upstream dependencies. Follow the
pinned Blender camera-relative studio rotation convention.

Copy required environment assets into the immutable helper snapshot under existing
capture limits and verify their digests. Missing resources yield an explained
unavailable state. Changed resources during freezing supersede the batch;
corruption fails its exact request. Helpers must not depend on mutable preference
paths or change live World/engine settings.

Preserve file working-color-space and interpretation identity, including applicable
working_space_interop_id. Verify it in the helper. Primary/reference members and
upstream prepared Grade descriptors must belong to the same frozen revision.
A snapshot must bind the required complete static output versions and their
frozen authored revisions; it cannot use a partially installed owner.

## 8. Bake preflight and defined UI behavior

Use a small checked **bake_preflight** state for owner generation, desired source
revision, check IDs, at most one active check and verdict
UNKNOWN / CHECKING / READY / BLOCKED / FAILED / CLOSED. It observes eligibility;
it owns neither worker admission nor native mutation.

| Event | Behavior |
| --- | --- |
| Dirty hint | Schedule relevant observation; retain the last certificate |
| Equal semantic source | Preserve revision/verdict and do not retry FAILED |
| Different source | Advance revision and expose checking for new input |
| Check completion | Accept only exact owner/check/revision/source match |
| Stale completion | Settle old check; service newest pending observation |
| Unexpected local failure | FAILED with explicit Retry, no blind loop |
| Retry | Allocate fresh check identity |
| Close/replacement | Revoke owner; reject late verdicts |

A→B→A has revisions 1→2→3; check 1 cannot certify revision 3 by digest equality
alone. Cosmetic labels/names, positions, selection, unused controls and unrelated
data are excluded. Grade/Stack selection, relevant bindings, actual UV/geometry
and semantic UV-map/attribute settings remain included. Image-domain routes omit
irrelevant object/UV state.

Draw/poll/hover use cached verdicts and bounded live facts: native readiness,
playback, target existence, conflicts and directly knowable engine/domain limits.
They do not hash pixels/UVs, walk graphs, access files or wait for actors.
Fresh click validation precedes reservation, snapshot and worker effects, including
writes lacking reliable update notifications.

Image targets that now require UV, non-Cycles UV Bake, Shader to RGB and other
unsupported cases disable Bake with a specific explanation. A race at invocation
returns a defined blocked outcome. A ready preparation or eligibility certificate
never clears the native evaluation guard.

The route descriptor includes `Grade native output` or `Stack final LUT output`,
the required native context and the accepted evaluator manifest. Image-domain
capture evaluates that output at the frozen source samples; UV-domain capture
evaluates it in the declared Cycles bake route. The Grade/Stack input alone is
not the Bake result. Preserve context-specific sampling/alpha and full-precision
transport so the native output is not changed by a separate grading pass or an
unintended display transform. Unsupported native-output capture is a defined
blocked route, never permission to fall back to a separate analytic/custom-GPU
pixel grader.

An eligible click reserves its ordinary queue/destination position and waits for
current final evaluator readiness before freezing the source and evaluator.
Receiving a 33³ Stack preview receipt advances interactive output only. A
matching 65³ commitment can satisfy the wait; a changed authored intent interrupts
the explicit request rather than retargeting it. Waiting for preparation has a
visible reason and no held native mutation ticket.

## 9. ProjectWorkflow: preparation, Bake, Save, Render and recovery

### 9.1 State regions and exclusion

The merged project state relates lifecycle/document generation, explicit Bake
entries, current output operation, derived preparation sets, native effect tickets
and repair/retirement obligations. Per-owner preparation records are indexed by
stable owned IDs; snapshots/asset manifests live in validated immutable records.
An immutable worklist records each required owner, desired revision, prior kernel
identity, candidate payload/revision and expected manifest; it records a candidate
kernel identity only when replacement is required. A bounded cursor and resource
grants govern iteration. Matching accepted receipts form the verified prefix;
a count alone cannot prove that every required owner was processed. Superseded
worklists retain their own obligations and cannot certify a successor.

Preserve the existing eight explicit-Bake queue entries, two worker leases and
same-destination order. Background preparation uses existing execution capacity;
it does not consume an explicit Bake click or weaken its cancellation rules.
Repeated edits coalesce to newest demand without discarding useful immutable
asset content. There is no scene-range compilation or frame-indexed Grade work.

Each explicit Bake entry records its owner/authored revision, evaluator kind,
required final quality, dependency on preparation, frozen source/evaluator
manifest and destination reservation. Its admitted stages are
`waiting_for_final → freezing_native_output → evaluating_native_output → staged
→ publishing → finished`, with cancellation/failure routed through the existing
retirement/repair protocol. Final preparation can complete independently of the
Bake; only the exact current Bake request can consume that readiness. Grade has
one final graph revision; Stack preview and final receipts are distinct. Native
evaluation results must retain the frozen evaluator identity through publication.

One foreground structural/publication effect ticket runs at a time. The model
distinguishes private helper obligations from live-datablock writes, readers and
repair. A shared “busy” flag is not a substitute for those resource dependencies.

Explicit Bake publication needs its own current-format recovery record even
though its computation never auto-resumes. Before overwriting an existing Image,
persistently retain the prior packed backing and binding (or an equivalent
no-loss representation) through real native ownership. Runtime-only backup bytes
cannot preserve that Image if autosave captures a partial overwrite. On reopen,
fresh inspection restores an interrupted publication's baseline without
resubmitting the Bake. If native publication actually committed and only its
actor acknowledgement was lost, preserve the verified committed result instead.
Neither case grants permission to resume an old explicit request.

### 9.2 Save

After destination/confirmation stages accept Save:

1. Revoke every unfinished Image/UV Bake's semantic/publication authority and
   reject new explicit Bake admission for this Save.
2. Settle already accepted grading edits once, preserving commit/cancel/Undo
   semantics without keyframing.
3. Finish required derived preparation for the document being saved and revalidate
   its complete manifest; settle live mutation or repair debt.
4. Preserve portable current-format controls and invoke one native Save.
5. Observe the actual save completion/failure and restore editor wrappers through
   exact receipts; release only the obligations actually settled.

Save need not wait for cancelled helpers that use private immutable snapshots
once live-data mutation/read obligations are safely separated. Their slots,
files and handles remain owned until actual retirement. Save failure cannot
resurrect the cancelled explicit Bakes.

Save As cancellation before acceptance does not cancel Bake. After acceptance,
cancelling Save does not reverse already committed cancellation decisions.
Compression, Save Copy, path remapping, modified-Image choices and overwrite
protection retain their normal meaning, with the accepted compression-default
exception in section 9.4.

### 9.3 Render

Acquire a whole-operation Image-publication exclusion before preparation.
Revalidate the committed Image versions and all required static Grade/Stack
outputs, then invoke the ordinary native Render Image or Render Animation
**once**. Do not iterate frames in Python, alter scene output format, or retain the previous
movie-format rejection.

The exclusion remains through complete/cancel and actual native retirement,
including inter-frame gaps. Installed Grade transforms remain static throughout
the render; no per-frame derived-transform writes need an exception to the native guard.
Final receipts release publication exclusion only when the native operation ends.

Explicit Bake input-change cancellation remains in force. Observed relevant
frame/input changes during rendering must be latched; restoring the original
frame cannot erase them. Conservative invalidation where exact relevance cannot
be observed must be explained, not treated as permission to publish a possibly
obsolete Image. A still-valid computation may finish privately and wait.

### 9.4 Common entrypoints and native limitations

Integrate the agreed Save, Save As, Render Image and Render Animation menus and
shortcuts. Preserve selected scene/view context, viewport options, native render
settings and cancellation. Remove the separate “with Exact LUTs” actions from the
new product; ordinary actions use the preparation gate.

Use an owned wrapper of the pinned native File/Render menu draw functions to
redirect only the four agreed action entries and their option assignments.
Preserve unrelated entries and appended add-on callbacks. Mirror the effective
configured shortcuts for those native actions; unrelated bindings remain intact.
A waiting/blocked owned action consumes its event rather than falling through to
an unguarded native operation. Track exact hook/keymap ownership and restore only
owned changes at disable; test conflicts and user changes during registration.

Save follows an owned destination/overwrite/modified-Image confirmation phase,
then the acceptance barrier in section 9.2, preparation, and one native
`EXEC_DEFAULT` call with the confirmed options. Pass
`show_save_modified_images_dialog=False` so no private native dialog continuation
can save outside its permit. Respect the user's modified-Image choice and existing
Always/Ask/Never preference without changing global preferences. Where the owned
Ask confirmation selected saving Images, use Blender's existing modified-Image
save operation; do not build another Image-saving subsystem.

Blender may report Image-save problems while still saving the .blend. Preserve
that behavior with a defined passive status: distinguish an Image-save warning
from failure to save the project. The owned Save checks dirty external Image
destinations before and after Blender's save operator and reports destinations
that were not written, even when the `.blend` succeeds. An Image operator's
FINISHED result does not prove that every Image was saved. Destination/confirmation cancellation before
Save acceptance leaves Bakes untouched; later cancellation cannot revive them.

**Accepted limitation:** the requested compression is written correctly, but
native execution through the owned flow may leave Blender's remembered
compression default different until reopening the file. Add no workaround or
extra default-tracking subsystem. This exception concerns the remembered default,
not chosen file options or successful serialization.

Save/Render completion requires actual native completion/failure and required
cleanup receipts. An operator return, elapsed time or exception alone cannot
release a live reader or certify a saved file. Native animation is invoked once
with the original options and stays owned until the whole operation retires.

Native handlers cannot veto arbitrary caller operations. The preparation wait
guarantee covers these integrated entrypoints and gated script entrypoints using
the same operation/receipt protocol. Unintegrated scripts/operators are not
promised to wait for stale preparation. Standalone Save Copy, Incremental Save,
New/Open, sequencer-specific commands and unrelated menus remain outside this
integration. Preserve Save Copy when selected inside the integrated Save As flow;
that does not extend the guarantee to the separate native Save Copy command.

### 9.5 Undo/load and normal recovery

Replacement advances generation, revokes old semantic work and preserves exact
physical obligations. Fresh inspection of Blender's restored graph supplies
new ownership and demand; old operation journals cannot authorize new writes.

Activate the new generation only once its current native state is safe.
Detached private helpers may retire separately under their old owners when
separation is established. Current readers, borrows and partial mutations still
block affected operations.

Replace a fixed elapsed-time recovery failure with visible waiting while exact
receipts remain outstanding. Automatically continue on those receipts; actual
failures offer explicit Retry. Neither a five-second deadline nor timer removal
is a retirement or replacement receipt.

## 10. Static Grade/Stack preparation and publication

### Persistent Grade update contract

Grade initializes its complete Linear/Tone/Color topology, optional families,
precision alternatives and fixed-size helper images once. Neutral stages are
bypassed by links, including their diagnostic paths. Editing one stage preserves
other authored non-neutral stages. All resident nodes count toward the original
budget, including disconnected paths. Stage activation does not allocate nodes,
groups or images; image dimensions also remain fixed.

The immutable candidate for a Grade update consists of parameter values, fixed
field payloads, routing intent and revision, rather than a newly constructed
tree. Apply it to the existing tree under native-reader exclusion. Retain prior
payloads/defaults/links until readback verifies the complete update; publication
advances only after success. Restore the previous state on partial failure;
failed restoration retains owner repair debt and blocks its readers/readiness.
Native ownership and exclusion remain product responsibilities. Stack retains
its separate candidate-LUT and publication contract.

Development audits select fixed field sizes and retain accuracy/minimality
receipts. Production generates only changed fields at those sizes, without
resolution retries or dense accuracy gates. Linear-only changes update matrices
and reuse Tone/Color data. Tone changes invalidate Color only when its derived
context changes. Frame changes alone do not invalidate grading preparation.

Interaction evidence begins at an accepted parameter occurrence and ends at the
first draw of its matching evaluated revision, including queue/admission waits,
field generation, writes/packing, rewiring and native compilation/evaluation.
Initialization is separate. Superseded or undrawn samples never acquire zero
latency or a later revision's draw receipt. Report p50/p95 without a speed gate;
standalone GUI evidence is not installed Next product acceptance.

### 10.1 Static intent and complete output descriptors

A preparation manifest binds:

- Document/owner identity, desired authored revision and working-color-space
  interpretation.
- Immutable numerical recipe, backend algorithm/transport schema and required
  precision, including the preview/final quality tier for Stack LUTs.
- Complete graph schema and packed coefficient/geometry or LUT content
  identities/digests, with matching input/output rows.
- Stable Grade kernel and candidate update revision, or replacement candidate
  kernel where required; public socket ABI and required baked-Image bindings.

The Grade backend is the forward native Linear/Tone/Color graph from
`libraries/perceptual-grade-nodes`, including H–K and AP1 output guards and
excluding input RGB repair. It uses the current schema-5 fixed layouts: Tone
256, Color coefficients 8,192, Web parameters 4,096, Web toes 1,536, Compact
Adaptance 3,072 and output boundary 513 × 321. Its complete graph and packed
fields are the single interactive/final evaluator; neither a Grade preview LUT
nor a second helper grader is part of this contract. Scope analytical plots
remain measurements and do not create an alternate Grade output path.

Preserve the Grade's explicit signed-input contract when comparing it with the
reference: compose the corresponding reference stages without input repair,
rather than comparing against a differently guarded public entrypoint. Retain
the current internal/field/HDR diagnostics, alpha, containment and native
ownership checks. The original fewer-than-1000-node goal and known
`web_alternating_extremes` GPU failure are deferred by user direction. Keep their
raw counts, witnesses and source-bound evidence visible; do not block this
delivery on fixing them or label them passed. This deferral does not waive new
integration regressions or Next's installation/publication obligations.

Stack remains a separate LUT evaluator. Prepare a 33³ intermediate preview and
refine to the 65³ final for the same authored revision. The 33³ vertices are the
even-coordinate subset of the 65³ lattice and are reused exactly. Preserve the
declared shaper, tetrahedral lookup, Shader/RGBE Compositor transport and endpoint
matrix behavior; preview/final changes never alter the grading equations.
Only the accepted 65³ LUT grants final Bake/Save/Render readiness. A custom GPU
grading program may generate and validate lattice values, but its directly graded
image pixels cannot become explicit Bake output. A helper process may instead
host the accepted native LUT evaluator and return its captured output.

Next Stack preparation must implement the current reference's forward and inverse
entry semantics, including the 35/75 J_A/C crossover, frozen post-Tone drivers,
raw signed-appearance handoffs, forward/inverse cancellation and endpoint matrix
ordering. The public reference `BakeStack` currently rejects nonzero low/high
coefficients because its retained accelerated kernels use `.4 × capacity`;
porting that path unchanged does not satisfy this design. Validate the new
portable/accelerated implementation against the analytic reference `Model` and
`Stack`, including nonzero low/high controls. Keep inverse search residual/status
and root-selection semantics explicit; do not claim global inversion or silently
return the old model when a backend lacks support. Preserve the distinction
between Grade's outer linear transform and Stack's internal composition; do not
fold arbitrary transforms into a bounded cube.

The Stack recipe/schema identity includes the 35/75 law, direction sequence,
matrix order, shaper, quality and transport. A LUT or packed asset created under
the retained `.4 × capacity` law cannot satisfy a current-reference manifest.
There is no cross-product asset migration or compatibility fallback in this
handoff.

Grade helper preparation and Stack lattice preparation remain different recipes.
Their manifests identify equations, schema, packed assets, endpoint matrices and
quality, so equal settings or a shared hash alone cannot substitute one for the
other. Standalone evidence does not complete Next's product workflow acceptance.

Meaningful Grade/Stack edits, selections, working-space interpretation or binding
changes invalidate the applicable output manifest. Frame progression, source
animation and cosmetic UI edits alone do not invalidate an unchanged static
transform. Scope input and explicit Bake source identities still include their
relevant frames and dependencies. A→B→A edits may reuse verified immutable content
but allocate fresh authority; an old cancelled request never becomes active again.

### 10.2 Remove animation implementation from the new pair

Do not carry Grade/Stack keyframing or auto-key callbacks, animation Action copies,
dummy dependency drivers, animation-specific save muting/restoration, per-frame
LUT render controllers or extra Exact LUT actions into the new runtime. Port
static creation/duplication from canonical values so copied datablocks do not
accidentally retain animation. Preserve ordinary edit settlement and Undo.

Declare effective Grade controls non-animatable, including tone/chromatic RNA
properties dynamically replaced by panel setup, and effective Stack/reference
properties. Remove gesture/sidebar/peak-nits keyframe call paths and obsolete
animation-only catalogs, tests, exports and proof bindings in the new pair.
Static final-quality preparation and native completion checks remain required.

Detect unsupported animation targeting Grade model/matrix/white controls,
Grade selection or effective Stack entries, including Actions, NLA and drivers
on those specific destination paths. Direct ID-property animation must not
bypass this guard. Expose an explained unavailable state for affected operations
and retain prior committed output without certifying it as current. Preserve the
authored animation data for the user to remove; do not freeze or migrate it.

Do not reject a whole NodeTree because it has animation_data. The Grade's input
Color, upstream nodes, Image sequences/movies and unrelated destination channels
remain supported. A driver elsewhere reading a static Grade value is allowed.
Retain generic F-curve traversal and node-replacement preservation needed for
those channels, even when their baseline utility lives in the Grade module.

### 10.3 Preparation pipeline and persistent ownership

The preparation state distinguishes:

~~~text
observing → snapshotting → computing → staging → validated → committing → ready
~~~

Every active stage names its attempt, operation, awaited receipt and owned work.
Cancellation, failure and partial effects enter retirement/repair paths; they are
not alternate routes to ready. Compute static numerical payloads from immutable
value snapshots through the existing execution capacity. No animation sampler,
helper timeline evaluation, LUT sequence, paging policy or animation budget is
needed. Native upstream source capture retains its own immutable scene snapshots.

For Stack, the pipeline can complete a preview publication and continue final
refinement under the same authored revision. Store accepted preview and final
manifests separately: `interactive_ready` does not imply `final_ready`. Preview
completions arriving after a matching final cannot downgrade it. An old revision's
final cannot complete the newest revision, and cancellation retires preview and
final work under their exact submission identities. Grade has no preview/final
fork. Bake, Save and Render consume only `final_ready` for every required owner.

Keep the previous committed output separate from one newest candidate per owner.
For first installation or structural recovery, build an unpublished candidate
kernel containing the complete native Grade graph and packed fields (or a Stack
LUT), endpoint matrices, baked-output bindings and the exact public socket
interface. Validate its algorithm schema, numerical gates, payload and packed
backing before installation. For an ordinary Grade edit, prepare immutable
candidate values, changed field payloads and routing intent for the existing
persistent tree; do not build a replacement graph. Stack retains its candidate
LUT contract. Scratch files are temporary transport, never a runtime dependency
of committed packed output.

Before native mutation, create the current-format preparation record with the
owner's real Blender ID references and enough prior/candidate payload state to
verify or restore an interrupted operation. Grade edits retain the same tree,
node and image identities and dimensions; their bypasses rewire existing links.
A document-owned ledger NodeTree can retain references through serialization;
actual ownership and readback are required, not raw pointers, names, runtime-only
bytes or fake-user flags. The record must survive autosave during any partial
publication stage. Account for retained rollback/candidate data under existing
execution and allocation bounds; referenced resources are never evicted to
claim completion. Exhaustion has an explained wait/unavailable outcome, not a
lower resolution or falsely complete payload.

The implemented `preparation_ledger.py` roots recovery backing in a NodeTree
PointerProperty on the owner's controls. Ordinary Grade edits retain actual
target Images and packed float32 prior-field copies with digests. Structural
replacement retains actual prior/candidate tree references plus serialized
external links, input defaults and preparation/evaluator metadata. The redundant
owner-ID custom property can be reconstructed from the referenced ledger; names
and process pointers do not provide its ownership root.

**Implementation status (2026-11-01):** structural tree backing and Grade-field
backing pass focused Blender library write/load tests. Recovery blocks new edits
while any unresolved owner ledger is retained. If the redundant JSON marker is
missing, it reconstructs the field transaction and slots from the persistent
ledger before restoration. The current `recovery` run has 2 failures in 34 tests;
native Stack has 1 failure in 9 tests, and installed smoke fails during Stack
setup/reopen.
An installed crash/reopen test saves a partial binding-only transaction, removes
the redundant JSON marker, exits with `os._exit(99)`, then restores and
re-prepares the Grade in a fresh process. It starts with `PENDING`, so it does
not cover readiness incorrectly surviving with `READY` and retained backing.
Field-write/structural-swap crash windows, autosave, and native reader-release
acceptance remain open; see the
[audit handoff](CHECKLIST.md#current-audit-handoff-2026-11-01).

The requirement applies independently to edit admission and output readiness.
Grade and Stack admission now reject both JSON and retained-pointer transaction
debt. Grade acceptance validates prepared field pixels, then records graph,
field-content and binding data; ordinary admission compares current content with
that accepted manifest. The remaining recovery defects are partial backup
deletion before a failed ledger retirement, incomplete structural/Grade snapshot
inventories, and no durable committed marker for in-place Grade field
publication. Stack candidate cleanup double-removes Images; its native fixture
lacks owner schema, and its installed fixture saves an unreferenced host tree.
These require corrections and regressions before the milestone closes. See the
[audit handoff](CHECKLIST.md#current-audit-handoff-2026-11-01) for exact
functions and remaining acceptance.

### 10.4 Per-owner installation, compensation and completion

Use one project-authorized foreground effect ticket for installation:

1. Revalidate the exact owner, intent revision, Grade/Image bindings, socket ABI,
   candidate payload and fresh native/ownership admission.
2. For an ordinary Grade edit, apply changed values, image payloads and bypass
   links to the existing tree under reader exclusion; never replace that tree or
   allocate nodes/images on first stage activation. For Stack LUT replacement,
   install its validated payload/kernel; for first Grade installation or
   structural recovery, bind the validated complete Grade kernel under the same
   exclusion. Preserve external links and defaults in either case.
3. Read back the existing or newly installed kernel, interface/defaults/links,
   matrices, packed payload and manifest against the immutable candidate.
4. Return the exact successful publication receipt. Only its matching actor
   transition marks this owner committed for the requested intent and quality.
5. Retire prior rollback state only after verification, serialization needs,
   exact references and readers release it. Stack's previous committed LUT
   resources follow its separate replacement contract.

A failure restores and verifies the prior Grade payloads/defaults/links, or the
prior kernel binding when a replacement was required. Failed compensation retains
the exact affected references and prior/candidate recovery data, including both
kernel references for a replacement, and explicit repair debt quarantines that owner.
Other owners' verified complete outputs remain valid. New operations depending
on the affected owner, including required Save/Render preparation, wait or expose
a defined failure until repair succeeds. Do not claim that quarantine can stop
arbitrary native viewport rendering or unintegrated callers.

The current structural adapter records commitment only after candidate binding
and link checks and successful owner registration. A saved uncommitted ledger
restores its prior tree and snapshot; a saved committed ledger preserves the
matching installed candidate. Recovery releases the ledger after that decision
succeeds. Structural compensation retains real tree references and repair debt,
including when the JSON progress marker is absent. Output readiness now rejects
both ledger forms for Grade and Stack. Remaining defects include incomplete
snapshot inventories, partial-backup deletion before ledger retirement, no
durable committed marker for in-place Grade fields, and Stack cleanup that
double-removes Images. Until those gaps are fixed, do not claim every partial
preparation remains ineligible or every failed repair retains its only backup.

Per-owner publication does not promise a globally simultaneous swap across all
independent owners. Project readiness requires the entire immutable required-owner
worklist to match current frozen intent, with no affected repair debt. Validate
that relationship again before invoking Save/Render. Dependencies used together
by a scope snapshot must all have the required complete versions.

Autosave can contain complete owners and pending candidates. Fresh reconstruction
inspects each owner and its actual references; a deleted owner is never recreated
from an old ledger entry. Atomic semantic commitment means verified coherent
publication, not an assertion that several RNA writes are hardware-atomic.

## 11. Fenced completion and crash recovery for every preparation

### 11.1 Three separate completion boundaries

| Boundary | Required evidence |
| --- | --- |
| Asset ready | Matching numerical result, actual producer retirement, complete validated immutable payload and packed backing |
| Output committed | Complete required assets, matching matrices/native bindings, successful installation/readback and exact publication receipt |
| Serialized | A completed native save/autosave actually contains that state |

Runtime readiness uses the second boundary. It does not claim that unsaved state
already exists on disk. A later serialization can capture either a complete
generation or an explicitly incomplete candidate; recovery must handle both.

A flag is a claim to inspect, never its own completion evidence. Completion must
match the required intent even when a dirty notification or pending marker was
not captured. A stale complete flag cannot certify newly edited authored data.

### 11.2 Common preparation contract

Every derived preparation family follows these obligations:

1. Derive demand from current authored input, owner/context, desired revision,
   algorithm/transport, quality and required owner/dependency set.
2. Allocate fresh request/operation identities. Record incomplete intent before
   native mutation and maintain persistent ownership for newly staged native
   resources that an autosave can capture. Ordinary Grade updates retain their
   stable kernel and serialized prior/candidate field state.
3. Stage immutable candidate payloads separately from live output; ordinary
   Grade updates apply them to the existing tree under §10, while Stack LUT and
   necessary structural/schema replacements may stage separate native resources.
   Preserve the previous committed state and never expose a partial payload as
   current.
4. Validate successful computations, physical receipts, assets, packing, complete
   owner descriptors and matrices. Cache presence or process exit alone is
   insufficient.
5. Install under exact native/ownership admission, verify actual bindings and
   commit the generation/manifest. The actor finishes only on its matching receipt.
6. Retire old resources through exact reference/reader obligations. Failure retains
   candidate/repair debt without falsely completing the preparation.

Private scratch computation still needs attempt fencing and owned cleanup.
Durable metadata is needed for saved derived state, not for reviving an obsolete
GPU/process initialization. Scope snapshots, analysis and preflight reconstruct
only current applicable demand; they cannot reopen the Gizmo during recovery.

This applies to static Grade/Stack output, packed payload construction, upstream
capture dependencies and structural/output installation. Each child phase must
be represented in its parent's completion predicate; a successful child cannot
imply the entire parent is ready.

### 11.3 Reopening is reconstruction from the opened document

Recompute the desired fingerprints from the authored .blend/autosave actually
opened. Inspect actual native structure, required owner/dependency completeness,
endpoint rows, packed content identities/digests and bindings.

- A complete matching set gets a fresh validation/ownership receipt.
- Missing, incomplete, mismatched or uncertified derived output automatically
  creates new preparation demand.
- Verified immutable pieces can be reused; incomplete transfer/packing cannot.
- A leftover pending marker does not require recomputation when fresh inspection
  proves the entire saved generation completed.
- Missing pending metadata is never proof of readiness.
- Old App/actor IDs, process handles, grants, pointers and compensation commands
  never become authority in the reopened lifetime.
- Repeated recovery cannot duplicate publication, assets or ownership.
- Explicit Image/UV Bake computation remains interrupted and requires another
  click. Repair an interrupted overwrite from its persistently retained baseline;
  preserve a verified completed native publication whose acknowledgement alone
  was lost. Pending Save/Render operations are not replayed.

The new pair must not inherit preservation-only adoption of incomplete generated
output. This includes missing native Grade graph/helper resources and incomplete
Stack LUTs. Its tests must require reconstruction rather than leaving unfinished derived
output unrepaired until the next edit. Preserve the old pair's tests as evidence
of its different behavior. Preserve user-authored Image data and explicit Bake
results separately; automatic re-preparation applies to derived output, while
explicit-Bake publication repair only restores or recognizes committed data.

Blender ID-property markers become persistent only when serialized. Native
autosave bypasses save_pre, so fencing cannot be added only in a controlled Save
handler. Recovery must work with a snapshot taken during any represented stage.

Native adapter tests now write and reload `.blend` libraries containing the real
structural and Grade-field ledgers. They check retained prior/candidate trees,
packed float32 backup content and restoration after a partial field write,
including an absent owner-ID marker. Recovery also preserves a ledger still
referenced by a live owner during orphan cleanup. This is persistence evidence
for that native serialization route. The installed saved binding-only
`os._exit(99)` test adds one process-termination boundary, but neither test
establishes recovery from interrupted file serialization, power loss, or unsaved
edits absent from the opened file. Autosave at every partial effect and broader
installed recovery acceptance remain open.

No new durable journal for unsaved authored edits is required or authorized by
this choice. Existing execution journals handle process/resource cleanup.
Existing verified caches may optimize reconstruction. Missing cache data must
be reconstructible from the opened file; a cache cannot import newer unsaved
intent or an old session's authority. No new cache subsystem is required.

### 11.4 Crash windows

| Interrupted point | Required reopened behavior |
| --- | --- |
| Before pending metadata reached disk | Derive demand from the opened data and prepare what it requires |
| During static model capture/computation | Start fresh matching demand; reuse only verified pieces |
| During transfer/packing | Reject the partial asset; preserve valid committed output and rebuild |
| Assets ready, installation incomplete | Reuse verified assets and finish a fresh installation |
| During matrix/binding publication | Keep output uncertified until coherent structure is re-established |
| Native commit before completion marker/actor acknowledgement | Fresh inspection may accept the actual complete saved set |
| In-memory completion before next save | Follow the older file actually opened, not lost in-memory intent |
| Old request superseded before crash | Only the opened authored revision can authorize recovery |
| Explicit Bake computation interrupted/cancelled | Preserve previous Image; do not resume |
| Explicit Bake overwrite interrupted | Restore persistent prior backing/binding without resuming computation |
| Explicit Bake native commit before actor acknowledgement | Preserve the verified committed Image; do not repeat the Bake |
| Recovery itself crashes | Repeat safely under fresh identities, without duplicate publication |

Actual failures during reconstruction have defined local failure/Retry outcomes.
Native waiting and physical retirement remain visible waits, never fabricated
completion. Conditional progress assumptions in section 13 still apply.

## 12. Failure, gesture settlement and terminal restart

### 12.1 Services and local outcomes

Each timer/pump has registered/running/failed/stopped status and an exact
registration incarnation. Failure or unregistration from an old callback cannot
stop its replacement. Before a service stops unexpectedly, its owning state
records failure or a closed target; absence of a cached result is not sufficient
to label the UI Preparing.

Passive status names the actual wait: native readiness, playback, capacity,
capture, analysis, preparation, retirement, unavailable or failed. Diagnostics
retain identities and technical details without keeping RNA traceback objects
alive. Public controls expose defined outcomes, not exception popups.

An unexpected infrastructure fault may fence the App. Local Retry does not reset
that fence; Restart uses the separate supervisor. Node creation checks its actual
structural/lifecycle admission. Scope-local failure alone cannot reject it.

### 12.2 Gesture settlement is independent of close

A gesture records immutable identity, original Grade/binding/lifecycle and its
accepted commit/cancel decision. Native fields may accept on Enter, Tab, release,
window deactivation or another press before deferred cleanup runs.

Closing/moving the Gizmo first changes foreground visibility/owner. Already
accepted commits settle once. A genuinely uncommitted interrupted drag restores
only its exact still-live original target. Replacement/deletion discards obsolete
settlement; it cannot write to the new selection or add a duplicate Undo step.
Save retains its explicit accepted-edit settlement behavior.

### 12.3 Restart supervisor

The extension-lifetime supervisor and its Restart/status/X registrations remain
outside each computational App.

| Phase | Obligation |
| --- | --- |
| faulted | Keep computation fenced; show Restart and passive explanation |
| restart_requested | Revoke view/new admissions; allocate one restart occurrence |
| draining | Obtain actual worker, capture, reader, borrow and partial-effect dispositions |
| preserving | Preserve Grade/Image selections, links, parameters, committed output and portable current-format wrappers; no new numerical preparation |
| detaching | Remove exact old callbacks, timers, menus, keymaps, classes and remaining ownership registrations |
| starting | Create a fresh App only after the old session's complete terminal receipt |
| recovering | Inspect/adopt actual retained data and create fresh derived preparation demand |
| active | Publish the new session after safe registration and recovery |

An interrupted phase retains its exact operation and ledger and exposes Retry
Restart. A partially started replacement must itself finish cleanup before
another App is created. Waiting for real native work remains waiting.

The current RestartSupervisor uses the source-bound Restart policy for its
generation, phase and cleanup ledger. Its adapter has at most four cleanup
categories: scope, preparation updates, Bake and native output. Matching receipts
may arrive in any order; duplicate obligations and stale receipts are rejected,
and failed receipts retain debt for Retry Restart. The full preservation,
detach/replacement and installed failure scenarios in the phase table remain
acceptance obligations.

The current cleanup shortcut that interprets app.fenced as evidence of prior
teardown is insufficient. An unexpected live actor fault can reach it without
portable-wrapper preservation. Replace that inference with explicit preservation
and teardown receipts. Cleanup-authorized preservation must remain available when
ordinary App admission is fenced; merely calling the normal prepare_disable path
is not evidence that it can succeed.

## 13. Expressible proof obligations and external premises

### 13.1 Scope/view/gateway requirements

Retain S01–S19 as mandatory inventory IDs, updating their statements for actor
ownership and the explicit grant boundary.

| ID | Required claim | Property |
| --- | --- | --- |
| S01 | close_revokes_view_authority: foreground close hides and advances epoch; old draw/effect envelopes cannot restore it | P3, P4 |
| S02 | cancelled_attempt_stays_cancelled within one request identity | P2 |
| S03 | operation_matches_owner: grants/receipts bind exact lifetime, request, submission and resource | P4 |
| S04 | cancelled_attempt_cannot_gain_new_read_or_advance: no new start grant after cancellation; pre-granted work remains accounting-only if later cancelled | P2, P5 |
| S05 | terminal_read_once_after_retirement for the matching producer | P2, P5 |
| S06 | preview_occurrence_is_bound and consumed once | P1, P4 |
| S07 | control_ack_advances_once to a new submission identity | P1, P4 |
| S08 | publication_requires_applied_receipt: staged success, live actor acceptance and current foreground adoption; token issuance alone cannot fulfill demand | P1, P3 |
| S09 | statistics_match_visual exactly; mismatched values are not drawable | P1 |
| S10 | batch_members_are_coherent for primary/reference/environment | P1, P6 |
| S11 | old_settlement_preserves_new_demand, including equal semantic keys | P1, P2 |
| S12 | cancellation_retains_debt, including handles returned during cancelled submit | P5 |
| S13 | destroyable_has_no_obligations | P4, P5 |
| S14 | older_batches_remain_owned while referenced | P5 |
| S15 | playback_cannot_acquire_or_publish; resume never restores old attempt authority | P9, P10 |
| S16 | pending_has_a_reason and a matching live service or defined wait/failure | P1, P8 |
| S17 | local_failure_is_scoped to its exact request/components | P4, P8 |
| S18 | compatible_progress_does_not_fulfill_newer_demand | P1, P2 |
| S19 | service_failure_matches_incarnation | P4, P8 |

Foreground initialization/transition invariants additionally prove singleton
visibility, owner transfer, close-gesture cancellation and one-shot grant
consumption. Compose the real scope/view/gateway functions for delayed delivery
after close/reopen, transfer and playback.

### 13.2 Project, static preparation, recovery and preflight requirements

| IDs | Required family |
| --- | --- |
| J01–J03 | Accepted Save cancels unfinished explicit Bakes and excludes new admission; whole-render Image publication exclusion persists; native effect tickets require current lifecycle and exact receipts |
| J04–J06 | Same-destination ordering/physical lease conservation; replacement revokes old semantic work; partial native effects retain repair debt |
| J07–J08 | Preparation readiness never bypasses native guard; old operation receipts cannot finish/release a successor output operation |
| T01–T03 | Ready worklist covers every required owner; each static descriptor binds its Grade graph/helper fields or Stack LUT, both matrices and native bindings; a staged candidate is never current output |
| T04–T06 | Equal recipes reuse immutable payloads without reusing request authority; meaningful authored revisions invalidate readiness; frame changes alone preserve static preparation |
| T07–T08 | Packed assets and installed kernels satisfy the committed manifest; admission and repair retain prior/candidate references and resource obligations |
| T09–T11 | Grade descriptor binds one forward native graph and fixed fields with no preview transform; Stack separately binds 33³ interactive and 65³ final identities, with exact even-vertex reuse; directed Stack recipes bind current-reference equations and endpoint ordering |
| F01–F03 | Finished requires matching actual completion/publication receipts; payload readiness differs from output commitment and serialization; saved flags alone grant no readiness |
| F04–F06 | Reopening derives fresh authority from opened data; missing/mismatched derived preparation requeues; repeated recovery is idempotent and old-session grants never replay |
| F07–F08 | Explicit Bakes, Save/Render continuations and hidden Gizmo demand never auto-resume through derived recovery; Bake output binds the accepted native Grade graph or Stack final LUT, never a separate analytic/custom-GPU pixel grader |
| R01–R04 | Restart remains outside failed App; preservation precedes detach; fresh App follows terminal teardown; failed/duplicate restart retains exact debt |
| B01–B08 | Current receipt required for READY; stale revisions rejected; one active check; monotonic attempts; equal observations preserve verdict; failure needs Retry/new intent; closed owners cannot publish; Stack preview cannot satisfy a Bake/final verdict |
| U01–U02 | Authored settings and UI adapters share current-reference control identities/defaults/units and supported domains in fixed D65/203-nit context; Tone Fit [-2, 2] and Color Fits [-2, 6] agree through edits, preparation, persistence and reset |

Each ID must become a concrete requirement over the actual production transition
or checked helper, with its native inputs distinguished from proved conclusions.

#### Arbitrary finite owner lists

The owner-count requirement is for every finite worklist accepted by the
production contract. “Unbounded” here means there is no proof-model cap such as
four owners; it does not mean an actually infinite Python list or that the
implementation can exceed its memory and runtime limits. A finite induction is
the right proof principle and is sufficient in mathematics:

1. At cursor `0`, prove the verified prefix is empty and the invariant holds,
   including for an empty worklist.
2. For arbitrary `k < n`, prove one production readiness step preserves the
   invariant from prefix `k` to prefix `k + 1`. The invariant must retain the
   exact owner, revision, evaluator, artifact and manifest relation for every
   checked element; uniqueness and tuple-shape assumptions must be established
   at admission or checked by the step.
3. Prove the loop exits at `k = n`; then the invariant covers the entire list,
   not merely a prefix or a fixed number of positions. The measure `n - k`
   proves termination for every finite input.

This induction proves an arbitrary-length theorem only for the transition and
state actually used in its premises. It does not by itself prove that Blender
discovery constructs that worklist correctly, that native payloads match the
artifact descriptors, or that Save/Render use the result. Those claims need a
checked projection from immutable production data and source correspondence to
the readiness predicate and its admission callers. External Blender reads may
remain explicit adapter premises, but must not be represented as proved
conclusions.

The four-slot `ProjectState` proof remains a bounded model and cannot substitute
for this induction. Production readiness now uses the unbounded kernel for every
owner count. `project_unbounded_proof` passes 170 obligations and 4 mutation
checks in build `e458d854-a0f2-474f-9ee4-e903e6da13b7`. This establishes the
kernel's induction; production `project.py` record validation/alignment and
conversion into that kernel remain outside the proof. Native owner discovery
and payload admission also require their own correspondence evidence. The
legacy four-slot projection is not a proof of those boundaries.

#### Production composition and inventory completeness

Use one inductively checked readiness predicate for every production owner
count. A separate four-slot authority may retain historical proof evidence but
must not remain a second admission path with assumed correspondence. Prove the
actual Project, Preparation, Recovery, Scope/foreground and Restart transition
relations together wherever a required claim crosses their boundaries. They
may remain separate runtime owners; the proof must express their shared state,
exact tickets, handoffs and retained obligations. A copied reduced machine such
as `composed.py` proves only its own rules until correspondence is established.

As of this audit, the canonical inventory contains 60 IDs: 43 partial,
11 adapter premises and 6 open (S09, S10, S14, S16, S18 and S19). This is an
inventory of obligations, not 60 proved claims. Its validator checks declared
references; it does not validate proof receipts or reject every orphan `.inv`.
There are 10 `.inv` files and 9 proof targets. `scope_view.inv` proposes five
properties but has no Buck proof target and lacks
the required nonempty `invariants` declaration. Complete the properties,
witnesses, independent mutation checks, generated validators and verification/
package dependencies before calling that joint proof implemented. The eight
earlier passing proof targets' 493 obligations and 27 mutations remain historical
receipts; the ninth kernel now passes, while no fresh aggregate is recorded for
the current checkout. Exact scope and evidence are recorded in
[PROOF_COVERAGE.md](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md).

### 13.3 Required sequence witnesses

~~~text
open A → submit A → close → reopen same semantic input as B
→ A retires → no new read/advancement/failure from A → B demand survives

native source A → capture A → direct Color B → late A receipt
→ B remains usable while A debt retires

propose effect → cancel → request start → no grant/body
grant start → cancel → returned handle → exact retirement, no new publication

stage visual → close/transfer → delayed success receipt
→ staged resource accounted for; no old-view draw token

register 1 → ready → update 2 → duplicate ready-1
→ no extra submission or relabelled result

visual B accepted → statistics A arrives
→ B remains visible; A statistics absent

actor accepts visual → foreground begins playback → delayed token arrives
→ no new visual/statistics adoption; prior installed display remains

begin playback → revoke active requests → stop playback
→ old completion → no revival → fresh demand after native readiness

preflight A(1) → B(2) → A(3) → check-1 completion
→ no READY from revision 1

prepare generation 1 → edit generation 2 → generation-1 result
→ reusable immutable content only; no generation-2 completion

Stack revision 1 → publish 33³ preview → Bake click
→ wait on exact 65³ final → final receipt → freeze final LUT/source → evaluate LUT → publish Bake

Grade revision 4 → freeze installed native graph/source → evaluate graph output
→ separate analytic/custom-GPU raster proposal → reject alternate grader result
→ helper-hosted native capture may publish only with matching evaluator/source receipt

Stack forward A → inverse A → raw handoff cancellation
→ identity on matched pair; unmatched inverse → found root/status/residual → validated output only

Tone Fit -2 / 2 and Color Fit -2 / 6 → UI/persist/reopen
→ same authored values and enabled domains; out-of-domain Fit is rejected

static Grade ready → animated input changes frame → native evaluation completes
→ fresh scope source and unchanged Grade graph/helper identity

owner A commits → owner B install fails → B compensation pending
→ A remains valid; Save/Render needing B cannot pass readiness

explicit Bake ready → Save accepted → late Bake publication proposal
→ denied; saved Image is the committed baseline

Render accepted → Bake completes privately → animation frame gap
→ Image publication remains blocked until final native retirement

crash after packing → reopen pending manifest
→ fresh validation reuses asset → fresh installation → ready

crash after native commit before finished marker → reopen
→ fresh inspection accepts complete saved generation exactly once

terminal App fault → Restart → late old handle → exact cleanup
→ preservation/detach → one fresh App → current-data recovery
~~~

Give each safety property a non-vacuous positive witness and a source mutation
the checker detects and replays in ordinary Python. Mutations remove request,
generation, cancellation, grant-consumption, physical-retirement,
publication-success, visual/statistics, owner-worklist completeness, matrix-coherence,
Save/Render exclusion or reopen-authority checks. Include false completion from
queue acceptance, clearing pending before packing/installation and recovery that
trusts a COMPLETE flag without matching current intent.
Also mutate the Stack quality check, final-revision match, Bake evaluator kind,
frozen asset/matrix identity and UI Fit validation. Reject preview-as-final and
separate analytic/custom-GPU pixel-grading results through checked production
transitions; establish actual numerical/evaluator correspondence separately with
native and reference tests, rather than treating an enum or receipt flag as proof
of its pixels.

### 13.4 What is proved, assumed and tested

The verifier establishes initialization, invariant preservation and admitted-step
properties. It is not an unrestricted temporal-logic prover. Pending-has-a-reason
does not by itself prove eventual completion.

For stable demand and finite declared work, use a stage/remaining-work rank and
prove advancement on matching successful receipts. Cancellation/failure leads to
owned retirement or defined terminal state. needs-seed resets and retries require
explicit successful-worker assumptions; do not claim a strictly decreasing rank
through arbitrary resets.

Conditional progress assumes fair foreground/actor servicing, eventual capacity,
native operations eventually terminating and healthy workers returning usable
results or failure. Resource limits may produce an explained unavailable state.
No proof can declare an actually running native reader finished to improve liveness.

| External premise | Required production/integration evidence |
| --- | --- |
| Physical retirement | Exact execution-service receipt for the real submission |
| Safe native mutation | Fresh guard revision plus actual job/lock observations at effect entry |
| Owned RNA | Current incarnation, borrow and replacement validation |
| Authentic grant | Exact unchanged one-shot transport and original-owner receipt routing |
| Observed source/static model | Native evaluated source context, authored Grade values and immutable dependency capture |
| Packed asset identity/content | Complete storage, schema/encoding and actual digest/validation |
| Native kernel/matrices applied | Exact binding readback and rendered native scenario evidence |
| Native Bake evaluator used | Frozen Grade graph or accepted 65³ Stack lookup identity, complete route snapshot and captured native-output comparison; a declared backend tag is insufficient |
| Current-reference equations | Independent analytic forward/inverse and crossover tests with residual witnesses; matching shared implementation results alone are insufficient |
| Native save captured state | Completed serialization and reopen inspection, including autosave |
| X event/geometry | Matching current-editor press/release and cached hit geometry |

Separate these premises, source-bound claims and integration evidence in reports.
Counts of passing obligations do not establish truthful native observations or
unrestricted end-to-end correctness.

## 14. Validation and acceptance plan

### 14.1 Pure model and deterministic adapters

- Prove the required claims, witnesses and mutations against production sources.
- Delay/reorder/duplicate submissions, start grants, previews, terminal/control
  results, publication receipts and service stops.
- Inject cancellation before grant, after grant, during submission, after staging
  and before acceptance; assert both visible outcome and retained obligations.
- Verify denied bodies are not called, while pre-granted aborted/partial effects
  return exact receipts.
- Exercise one global Gizmo across windows, target deletion, native-to-direct,
  same-key reopening and A→B→A inputs.
- Exercise old accepted visual/new pending visual and delayed statistics;
  selecting a cached page must keep its own axes/frame/provenance.
- Verify Grade/Stack static descriptors, exact owner-worklist completeness,
  supersession, immutable payload reuse, capacity waits and source/context mismatch.
- Interleave Stack preview/final completion, revision replacement, Bake wait,
  cancellation and stale receipts. Preview-only state never grants final readiness
  or satisfies Save/Render/Bake.
- Verify each Bake result identity names the frozen native Grade output or
  accepted Stack 65³ lookup; deny separate analytic/custom-GPU per-pixel grading
  even when its pixels or settings digest match. A helper-hosted native evaluator
  follows the same receipt and publication checks.
- Exercise reference-aligned forward/inverse Stack entries, raw handoffs, exact
  paired cancellation, endpoint order, found-root status and residual reporting.
- Check every Save/Render/recovery/restart interleaving that shares a project
  authority; no model-copy oracle replaces the actual transition functions.

### 14.2 Native interactive behavior

Use synthetic scenes matching the relevant structure of the supplied project.

- Shader to RGB with black scene World versus Material Preview HDRI, environment
  rotation/intensity, viewport switching, Rendered/camera fallback and Scene World
  scopes. Include source changes during primary/reference freeze.
- Actual X press/release/cancel while capturing, retiring, failed and App-fenced;
  Add Grade remains usable after local failure.
- Accepted and unaccepted gesture settlement, native numeric commit before close,
  window transfer, close→Undo and deletion before deferred settlement.
- Automatic frame-change scopes and playback stop followed by actual native
  completion; no Refresh control and no pre-playback request revival.
- Unrelated/cosmetic edits without Bake flicker; real native work still disables
  Bake. Include UV changes of equal array sizes and unnotified pixel writes.
- Unsupported Image→UV, non-Cycles and Shader-to-RGB Bake routes show defined
  disabled outcomes. No silent engine substitution or exception popup.
- Grade/Stack selectors, bake Image create/select/rename, separate Bake row, Vector
  naming, hidden implementation sockets through Ctrl-S and save/reopen.
- New Bake/+ New/rebake/unlink/delete/purge and referenced Image persistence,
  with no automatic fake user and no changes to existing explicit flags.
- Exercise Grade, Stack and inverse-entry panels against the full Next settings
  schema: fixed D65/203-nit context, Tone Fit limits `[-2, 2]`, Color Fits
  `[-2, 6]`, matching reset, serialization and numeric-entry validation.

### 14.3 Static output with animated inputs

- Compare the single native Grade graph's stage handoffs and complete guarded
  output against the current reference, including signed HDR, packed float32
  helpers, H–K and output guards. Record the current graph count and deferred
  budget status; do not gate this Next delivery on the old fewer-than-1000 goal.
- Compare reference-aligned Stack forward/inverse output and accepted LUT
  recipes, including the 35/75 crossover at positive/negative/zero `J_A`,
  nonzero low/high controls, raw handoffs, inverse residuals and endpoint rows.
- Verify 33³ preview vertices exactly equal even-coordinate samples of the 65³
  lattice, preview refinement reuses those samples, preview publication cannot
  satisfy final readiness, and final Shader/RGBE Compositor transport preserves
  its declared endpoints.
- Bake Grade Image/UV and Compositor routes from actual native Grade graph
  output, then compare captured baked pixels/alpha with matching native output.
  Bake Stack from the published 65³ LUT's lookup and endpoint matrices; assert
  the 33³ preview and any separate analytic/custom-GPU per-pixel grader are never
  read as Bake sources. Custom GPU grading compute may produce Stack lattice
  values, whose completed LUT must independently match the reference. A helper
  process may host the actual native evaluator for either capture route; verify
  its captured output against the accepted evaluator rather than rejecting it
  merely because execution occurred in a helper.
- Exercise EEVEE/Cycles (including persistent data), CPU/GPU Compositor, nested
  groups and shared/copied static Grades. Validate each backend's declared
  precision and packed layouts.
- Delete scratch files, save/reopen packed output and render natively.
- Verify ordinary Grade updates in the same tree, with all stages/families
  prebuilt and tree/node/image identities stable through first activation.
  Separately verify Stack LUT and necessary structural/schema replacements.
  Both paths require matching matrices/bindings, exact interface/default/link
  preservation, partial failure, successful compensation and retained repair debt.
- Verify one owner's failure preserves other complete owners while blocking
  dependent Save/Render readiness. Never recreate deleted owners from ledgers.
- Verify fixed D65/203-nit context, Tone Fit UI/product validation `[-2, 2]`,
  separate Color Fits `[-2, 6]`, and other controls' names, units, defaults and
  reset behavior against the current reference settings schema.
- Confirm Grade/Stack controls cannot be keyed or driven through ordinary RNA,
  including dynamically installed properties and Auto Key enabled during edits.
- Inject animation on relevant Grade/Stack destination channels and require an
  explained unavailable outcome, no silent static sampling and no data stripping.
- Animate the input Color, upstream nodes and input Images in the same NodeTree;
  these remain supported and must not trigger the Grade-animation guard.
- Change frames forward/backward while stopped: scopes acquire the new source
  after native readiness; unchanged Grade graphs/helpers/matrices remain unchanged.
- Play and stop: no new scope acquisition/adoption during playback, then fresh
  stopped-frame scopes after actual native completion. Old requests never revive.
- Native Render Animation handles movie and image-sequence output with one gated
  invocation and no per-frame Grade helper preparation, graph replacement or
  matrix publication.
- Account for retained old/candidate resources and missing/corrupt packed content;
  allocation failure cannot lower resolution, free live references or claim ready.

### 14.4 Crash, persistence, output and restart

Create next-product coverage using the established real parent-termination,
native-copy and autosave testing techniques. Its expectations require automatic
derived reconstruction; the preserved baseline tests remain unchanged.

- Terminate at every model/compute/transfer/pack/matrix/binding/commit-marker
  boundary; reopen a normal snapshot and a real native autosave.
- Include autosave without save_pre, missing pending marker, falsely stale
  COMPLETE metadata and completed native commit without actor acknowledgement.
- Verify automatic convergence from opened authored data, reuse of valid assets,
  no import of unsaved intent and no replay of old handles/grants.
- Interrupt recovery itself, then reopen again; require no duplicate output/assets.
- Keep interrupted explicit Bake cancelled; preserve its previous Image.
- Autosave during an explicit Bake overwrite, then crash/reopen: restore the
  persistently retained prior backing without resuming computation. Separately
  verify a completed native Bake commit survives lost actor acknowledgement.
- Save cancellation before/after acceptance, dirty-Image and overwrite dialogs,
  Save Copy/path options, the accepted compression-default difference, modified-
  Image warnings versus project-save failure, and restoration of Grade/Stack controls.
- Render while Bake computes; preserve committed Images throughout the entire
  native animation and actual cancellation/retirement.
- Restart from faults before preservation, during detach and during replacement
  registration. Verify Grade/Image selections, links, parameters and committed
  output survive; old cleanup must finish before another App starts.

### 14.5 Independent Buck gates and evidence

Create new-core proof/test targets and next-product adapter/installed suites for
scope/capture/Bake/output/recovery, static preparation, restart and packaging.
Use baseline scenario coverage as a specification aid, preserving its source and
tests. Include scheduler/scopes, gizmo_context, native_scope_capture,
scope_playback, shader_bake, compositor_bake, output_reader and output_resources
behavior in the new acceptance inventory.

Wire the new production policies, .inv requirements, mandatory claims, positive
witnesses, replayed mutations, generated validators and exact package proof closure
through independent Buck targets. The new package must contain no runtime
dependency on the preserved Grade product/core. Extend component checks for both new
namespaces and prohibited old/new runtime imports. This adds new coverage without
retargeting old consumers or treating baseline receipts as next certificates.

After implementation, require planned `//:verify_next` and
`//:perceptual_grade_next`, next numerical/adapter/installed acceptance, and existing
`//:verify`, `//:perceptual_grade`, `//:hdr_color_picker`, DCTL and architecture
checks. Preserve baseline source hashes and record any narrow shared-library
addition separately with regression evidence. Source, requirements, validators,
archive and platform identities belong in the new validation report.

Linux virtual-GUI probes do not certify macOS/Metal or every GPU. Keep local
proofs, adapter/native premises, numerical evidence and platform limitations
explicit. The Next pair contains executable core, product, proof and package
targets; those targets cover only the properties and acceptance cases wired into
them. Historical evidence from the preserved pair does not transfer.

## 15. Implementation and validation obligations

### 15.1 Selected first complete implementation step

The active next milestone is
[trustworthy readiness and recovery](READINESS_RECOVERY_STEP.md). Its status is
partially implemented and unfinished. Its unbounded kernel proof passes, but its
production source correspondence and native acceptance remain incomplete. It
covers the readiness/preparation/recovery boundary of
this design through initial insertion, in-place Grade updates, structural
replacement, fresh reconstruction, Save/Render admission and native Bake binding.

Completion requires a source-checked conversion from production owner records
to the already wired arbitrary-owner readiness kernel, validated native content,
verified compensation before backing retirement, complete snapshot rejection
before mutation, and accounted cleanup. Both JSON and retained-pointer debt are
already rejected by Grade and Stack readiness.
Stack's stable recipe/demand identity must remain distinct from the exact final
LUT/graph content manifest so matching preview-to-final refinement preserves a
waiting Bake without making preview a final evaluator. The step specification
defines the fault matrix, saved interruption boundaries and fresh evidence
required to close this milestone. The unbounded proof gate remains mandatory.

This delivers only the named portions of the canonical requirements. Complete
Scope/view composition, broader native reader/Bake concurrency, Undo/Redo and
remaining full-delivery acceptance are still required later; neither successful
local proofs nor this milestone's installed tests imply those requirements pass.

### 15.2 Complete delivery obligations

The design audit is complete. The items below are implementation obligations,
not pending product choices or permission to weaken P1–P15. Animation coverage,
driver sampling, timeline paging, animation budgets and out-of-range Grade-time
policies were removed with animated Grade support. Existing runtime capacity and
static numerical contracts remain; add no speculative replacement features.

| Obligation | Required evidence |
| --- | --- |
| New pair isolation | Distinct component namespaces, independent runtime/proof/package closures, unchanged baseline source and targets, current DCTL/reference consumers preserved |
| Scope/view/gateway composition | Actual checked production functions, immediate foreground revocation, one-shot grants and applied-display receipts; delayed/reordered trace evidence |
| Static installation | Real persistent prior/candidate references, exact interface and binding readback, correct matrices/payload, compensation and owner-local repair debt |
| Required-owner completeness | Immutable worklist with matching verified prefix, exact current revisions and all relevant owners ready before native output |
| Source observation | Effective viewport/Scene World capture and frame-sensitive inputs; static Grade keys exclude unrelated frame progression |
| Save/Render integration | Owned confirmations, correct options, cancellation barrier, no ungated continuation/fallthrough, actual completion and clean hook removal; accepted compression-default caveat only |
| Proof boundary | Same-module production traces for scope and project families; typed cross-family grants with authentic transport/native observations explicitly assumed and tested |
| Static transport accuracy | Native Grade graph and guarded-HDR gates, matrices, and exact native-output Bake; separate reference-aligned Stack 33³/65³ recipes, forward/inverse semantics and 65³-LUT Bake with Shader/RGBE Compositor payloads |
| Deferred findings | Preserve original graph-budget and alternating-extremes GPU witnesses as nonblocking deferred work; report new regressions separately and never relabel the retained findings as passed |
| UI/reference mapping | Full control schema/default/unit/reset/persistence correspondence in fixed D65/203-nit context, Tone Fit [-2, 2], Color Fits [-2, 6], and forward/inverse directions limited to Stack entries |
| Crash/restart | Real autosave/termination at each partial effect, fresh reconstruction and terminal teardown; no explicit Bake, Save/Render or Gizmo replay |
| Preservation and reporting | New checks distinguish implemented behavior from requirements; old evidence and the supplied project remain intact |

## 16. Implementation sequence in the new pair

1. Establish the new library/product namespaces, provenance, independent Buck
   targets, source/proof/package inventories and baseline preservation checks.
   Port needed numerical code/assets while preserving current DCTL/reference
   dependencies; keep old workflow code out of the new runtime. Implement the
   current-reference forward/inverse Stack math and full settings/UI mapping,
   including low/high drivers and corrected Fit ranges.
2. Implement the merged scope and project policies, foreground view/gate and
   restart transitions with claims, non-vacuous witnesses and replayed mutations.
   Use the shared checked execution framework; do not invent semantic layers from
   coordinator/regular labels.
3. Implement the asynchronous grant/receipt bridge, global Gizmo lifecycle,
   independent X path, monotonic cancellation, coherent display adoption and
   exact service-failure ownership.
4. Implement effective viewport/source capture, automatic frame-driven scopes,
   playback/native completion barriers, semantic Bake preflight and explicit Bake
   interruption/publication. Freeze and evaluate accepted native Grade output or
   the accepted Stack 65³ lookup; keep all defined unavailable/Retry outcomes.
5. Implement static per-owner preparation and remove Grade animation machinery
   from the new pair. Use one native Grade graph and distinct Stack 33³-preview/
   65³-final readiness, with exact even-vertex refinement reuse. Add persistent
   staging, complete kernel installation and
   readback, compensation, owner-worklist readiness and fresh crash reconstruction.
6. Integrate accepted Save and whole-operation native Render behavior, portable
   controls, Undo/load and terminal Restart. Use the accepted simple Save dialog
   path; no compression-default workaround or per-frame render controller.
7. Complete deterministic races, numerical/native UI checks, crash/autosave tests
   and next Buck proof/test/package gates. Recheck preserved targets and record
   exact evidence. Mark implementation items complete only when that evidence
   exists, independently of historical baseline results.

The Next pair already contains executable core, product, proof and package targets.
Keep each remaining checklist item open until its own proof, correspondence or
native acceptance evidence is recorded. The supplied .blend remains unchanged.
