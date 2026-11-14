# Next Blender policy machines

<a id="next-policy.overview"></a>

This chapter documents the policy layer in `products/perceptual-grade-next-blender`.
That product is a separate generation from the historical extension described by
the other development chapters. The policies are deliberately host-free Python:
they observe facts from Blender or a worker, reduce one event at a time, and
return effects for a runtime consumer to perform. They do not call Blender,
start threads, write images, or send process commands themselves.

Each machine is a small protocol:

```text
state + event -> policy.step(...) -> new state + effects
```

An effect is the policy's authorization for one external operation. The runtime
executes it and feeds the resulting receipt back as the next event. This keeps
the state transition testable while making the side-effect boundary explicit.

![The policy and effect-consumer boundary](../assets/illustrations/next-policy/00-policy-layer.svg)

<p class="figure-caption">Grade settings remain authoritative. Runtime observations enter a pure reducer; only its effects authorize adapter operations, and receipts return as events. The parameter/image transactions are comparison examples, while compositor callbacks also use the production gate.</p>

## What a policy stores

<a id="next-policy.contract"></a>

The design goal is to store independent facts and derive readiness from them.
The simplification candidates below identify places where the implementation
still duplicates facts or phases. A signature is an immutable correlation key
for a request. Job IDs, observer tokens, and render generations distinguish
receipts whose lifetimes must not be confused. Absence is `None`; an empty string
is never a stand-in for "no demand".

The common safety rules are:

* Correlation checks govern receipts. Stale helper generations and gesture
  tokens are ignored; a same-generation render identity mismatch fails the
  ticket. During a gesture, a superseded node result may still become a preview.
* One-shot completion receipts cannot complete the same slot twice. Declarative
  node output effects deliberately repeat on idempotent events so the consumer
  can reconcile host state; preview receipts can also repeat.
* A current failure clears the renderable installation and selects the visible
  error path. A stale failure cannot damage newer demand.
* The consumer executes effects in order and reports success or failure. Policy
  code never performs a best-effort side effect in an exception handler.

The `.inv` files in `requirements/` describe these transition contracts and
examples. The verifier checks the declared properties against the Python source
under their stated assumptions. It does not prove Blender's native observations, image validity, thread
affinity, worker implementation, or collection bookkeeping. The runtime tests
and installed Blender tests cover those adapter premises.

Read an edge as **event or receipt [condition] / requested effect**; the condition
and effect are omitted when unnecessary. Each box represents one phase, or one
configuration of facts for a policy that has no phase field. Phase labels match
the implementation; configuration labels describe derived states rather than
additional stored flags. Sequential phases always have separate boxes.
`running` and `desired` abbreviate preparation signatures; `current` and
`pending` in the observer figure abbreviate tokens. The join's `pending` count
is derived from its three child flags, not stored as another counter. For
synchronous transactions, `success` and `failed` abbreviate operation receipts.
Entering a synchronous operation phase requests its namesake effect; those
repeated effect names are omitted from edges. A semicolon separates alternative
events. The helper's operation effects are described in its lifecycle section.

A **double border** marks an absorbing state: later events cannot leave it.
Some policies name that phase `terminal`; others retain names such as `released`
or `closed`. Finality does not imply success. The publication transactions share
their `terminal` phase between successful and failed paths, and resource
retirement can finish without deleting anything. Ordinary states such as `idle`,
node `error`, and helper `failed` can still transition and have a single border.
The policy/effect-consumer overview above depicts data flow rather than states.

The figures emphasize lifecycle decisions; the prose describes correlation
checks, unchanged-state receipts, and less common transitions. Explanatory
notes and the numbered simplification candidates stay outside the boxes.

The sequence diagrams below follow those decisions through their effect
consumers and Blender operations. Time runs downward. `opt` encloses optional
work, `loop` repeated work, `alt` alternative paths, and `par` concurrent work.
The frames describe control flow rather than additional stored states. Related
policies share a sequence when they participate in the same interaction.

## Preparation: latest demand, one worker

<a id="next-policy.preparation"></a>

`src/policy/preparation.py` is used by `src/runtime/preparation.py`. Its state is
just `desired_signature` and `running_signature`. A request always replaces the
latest demand. If no work is running, the request also returns
`prepare_signature`; otherwise it waits for the current physical worker to
retire. A preview receipt publishes an intermediate result but does not free the
running slot. A final receipt for the running signature retires that slot and,
when a newer request exists, authorizes the newest successor.

![Latest-demand preparation scheduling](../assets/illustrations/next-policy/01-preparation.svg)

<p class="figure-caption">A superseded success can still be delivered as a preview. A superseded failure is suppressed, and the latest demand is started after the old worker's final receipt.</p>

The distinction between preview and final matters. The host preparation lane
may produce a preview and then continue working. Treating the preview as
retirement would allow a second job to overlap the physical slot. Conversely,
withdrawing demand does not claim that the worker has stopped; its final receipt
still provides the retirement fence.

The owning runtime also fences source lifetimes. `request`, `collect`, and
`wait` in `runtime/preparation.py` do not let a caller's cancellation release a
slot before the executor function returns.

### The three-child join

<a id="next-policy.preparation-join"></a>

`src/policy/preparation_join.py` is the aggregate barrier used by
`src/runtime/grade_preparation.py`. `new(signature)` marks `linear`, `tone`, and
`boundary` pending. Each matching component receipt clears one bit. The final
distinct receipt returns `completion_signature`; the first error is retained and
returned only at that final point. Stale and duplicate receipts do nothing.

![The three-component preparation join](../assets/illustrations/next-policy/01b-preparation-join.svg)

<p class="figure-caption">All three physical children retire before aggregate completion, including after an error. The runtime already wraps the receives in a shielded `asyncio.gather`; that is a scheduling fence in addition to this reducer's decision.</p>

![Preparation join workflow](../assets/illustrations/next-policy/01b-preparation-join-sequence.svg)

<p class="figure-caption">Each worker sends a component receipt to the join. `par` permits any completion order; the final distinct receipt authorizes assembly. Cancellation still waits for every physical worker through the shielded group.</p>

The preparer launches all three functions before awaiting any one of them. It
then assembles the `PreparedGrade` only after the join authorizes completion,
checks that boundary geometry belongs to the same appearance context, and
prepares the parameter atlas. This is why a first error cannot immediately
release the executor slot.

**Simplification candidate J1.** The fixed three-child barrier could be expressed
directly around `asyncio.gather`, reducing the explicit pending-bit reducer.
That is safe only if the replacement still rejects stale or duplicate receipts,
retains the first error until every child has retired, preserves cancellation
shielding, and leaves proof evidence for those properties. The current reducer
is verbose, but its contract is easy to audit independently of asyncio.

## Node output policy

<a id="next-policy.node-output"></a>

`src/policy/node.py` is the per-node decision layer. The runtime creates and
updates it from `nodes.py` and consumes its effects in `_consume_effects`. The
state records current demand, the installed signature and quality, whether a
gesture is active, the preparation correlation signature, and an optional
error. It does not store an `output_mode` flag. `output_mode()` derives one of
`current`, `preview`, `pending`, or `error`.

Only this predicate permits rendering:

```text
desired_signature == applied_signature
and desired_signature is not None
and applied_quality == "full"
and error is None
```

A new request may retain the last-good installation as a preview. A preparation
receipt authorizes a build; an installation receipt records the resulting kernel.
A current error removes the applied kernel from the policy state and selects
the fail-closed output. A later request clears that error and starts again;
`recovery_result` can also clear it when recovery installs a full result for
the current non-`None` signature.

The build consumer instantiates a native tree from the product's generated
`node_templates.blend` library and binds the prepared parameter banks or Stack
LUT. Its runtime index identifies the complete Shader/Compositor variant,
working space, LUT size, resource slots, and expected structure. The same Buck
target supplies the installed product and installed tests. Canonical graph
emitters remain in the repository's build-only `tools/template_build` package;
they are absent from the extension ZIP. The Stack helper likewise reads the
generated `grade_stack.glsl` resource instead of emitting the shared equations
at runtime.

Template loading introduces no independent policy machine. Append, binding,
validation, and cleanup execute only as consumers of existing installation,
bank-publication, and resource-retirement effects. A missing or incompatible
template is an installation failure and follows the existing visible-error
path. The asset contains topology and static data; Grade settings and prepared
payloads remain authoritative. File load and render preflight keep their
existing reconciliation obligations.

The preparation signature identifies shared prepared Grade data; the desired
kernel signature can additionally identify the node's graph context. A current
preparation receipt must match both correlations. A superseded successful
receipt is eligible only while a gesture is active, and becomes a preview rather
than current output. Once current full output exists, later receipts cannot
replace it; a preview cannot downgrade a full installation of the same signature.
`presentation` reissues the derived output policy without starting new work.
`gesture_begin` and `gesture_release` change only gesture participation; release
does not discard a retained preview. `request(None)` clears demand and the
applied kernel. `dispose` resets the entire lifecycle and emits only disposal,
without a presentation effect. The consumer fences subscriptions and releases
references through the resource policy.

The host shows a retained kernel as an updating preview. With no installed
kernel, pending presentation may use an identity placeholder. A current error
selects visible magenta output with alpha preserved; render preflight must not
release a frame with this error or with merely pending/preview output.

![Node output and installation policy](../assets/illustrations/next-policy/02-node.svg)

<p class="figure-caption">Presentation is derived from authoritative demand and installation facts. A stale receipt cannot replace a current result, and a preview is never render-ready.</p>

![Preparation and node output workflow](../assets/illustrations/next-policy/01-preparation-node-sequence.svg)

<p class="figure-caption">Preparation owns the worker slot, while the node owns presentation. A, B, and C name settings versions; preparation and kernel signatures still have their separate correlations. This trace runs outside a gesture, so an obsolete A cannot replace the retained Z preview. A preview receipt does not retire A. Current C is instantiated from the bundled native template and installed through existing publication effects. Preparation, template, binding, or installation failure selects visible magenta output with alpha preserved.</p>

`stack_replace` and `grade_changed` are scalar observations. They may authorize
reconciliation, but they do not themselves change the node's kernel state. The
runtime owns ordered Stack membership and Grade lookup; this proof does not
prove those collections.

**Simplification candidate J2.** Rebuild observations return the same state and
add a `rebuild` permission to the resulting presentation effect. A stateless
policy helper could authorize that reconciliation while the lifecycle reducer
continues to own presentation. This is a possible organizational reduction,
not evidence of redundant stored state. Keep reconciliation behind an effect
consumer, including on these state-preserving transitions.

## Helper process lifecycle

<a id="next-policy.helper"></a>

`src/policy/helper.py` governs one helper process and one physical work slot.
`runtime/execution.py` translates its effects into process and transport
operations. The generation fences a process session; `probe_id` fences startup
and `active_id` fences submitted work. The policy does not own payload queues or
join implementation.

Startup proceeds from `stopped` to `starting`, then `probing` after `hello`, and
to `ready` only after a matching successful probe. A preview publishes while
the slot remains active. A final result or cancellation retires the slot before
the next dispatch. An active cancellation sends a cancel request; it is not a
receipt that the work has stopped.

![Helper process lifecycle](../assets/illustrations/next-policy/03-helper.svg)

<p class="figure-caption">Shutdown escalates from a channel shutdown request to terminate, kill, and an explicitly unretired condition. Physical exit settles work before cleanup is attempted.</p>

![Helper process workflow](../assets/illustrations/next-policy/03-helper-sequence.svg)

<p class="figure-caption">The process and transport perform only operations requested by helper effects. Cancellation leaves active work owned until its final receipt or physical exit. Shutdown deadlines control escalation; cleanup begins only after exit and completes through its own receipt.</p>

Failure or timeout moves a live process toward termination. A channel shutdown
uses `stopping`; a process without that transport uses `terminating`. Terminate
and kill timeouts lead to `unretired`, which keeps ownership visible rather than
pretending cleanup succeeded. After physical exit, the policy publishes job and
probe outcomes, queues cancellation or failure, and enters `retiring`. Cleanup
may be retried; only a successful cleanup receipt reaches `closed` or `failed`.
Cleanup failure itself requests no new work; a later `shutdown` event requests
another cleanup attempt. `failed` can still become `closed` on shutdown, so
only `closed` has the absorbing-state border.

| Observation | Additional runtime detail |
|---|---|
| Shutdown during starting, probing, or ready | Enter `stopping` when a channel exists; otherwise `terminating`. Failure enters `terminating` directly. |
| Cancel the startup probe | Withdraw startup and shut down; a late successful probe cannot grant readiness. |
| Cancel active ordinary work | Send cancellation but retain the physical slot until a matching result/cancel receipt or exit. |
| Poll while the process lives | Authorize channel pumping, or listener acceptance during starting/stopping. No transport work after retirement. |
| EOF during normal operation | Enter the failure path. EOF during shutdown is insufficient evidence of process exit. |
| Timeout | Ignore a stale stage; escalate starting/stopping to termination, terminating to killing, and killing to unretired. |
| Planned exit, with no earlier error | Settle outstanding work as cancellation; otherwise preserve the first causal failure. |
| Shutdown after `failed` | Reach `closed`; cleanup already succeeded. |

Generation and job identity are intentionally separate. The current runtime
cannot restart a failed helper object: it creates a new owner whose numeric job
IDs start again at one. Process session and token checks in the transport provide
additional isolation; the reducer still checks generation before every receipt.

**Simplification candidate J3.** A smaller lifecycle could remove generation or
combine probe and active correlation only if the runtime contract guarantees
process restart isolation and ordered receipts. Until that contract changes,
keep the generation fence; otherwise an old helper can publish into a new one.

## Production bank publication

<a id="next-policy.bank-publication"></a>

`src/policy/bank_publication.py` is the active production publication path. The
parameter-image code in `nodes.py` constructs two packed image banks, while
`runtime/bank_publication.py` consumes the reducer's effects. The inactive bank
is staged and checked before the selector changes. Selection is read back, then
delivery publishes the resource and dispatches installation results to all
affected node records.

When a required Grade tree is missing or structurally damaged, the admitted
stage/repair consumer appends the matching bundled template and binds its two
parameter-image slots before returning a clean staging receipt. Ordinary edits
retain the existing graph and bank identities. Template append is an operation
inside the existing effect, not a new state or permission that bypasses the
publication gate.

![Production two-bank publication](../assets/illustrations/next-policy/04-bank-publication.svg)

<p class="figure-caption">An invalid active bank first closes output, then repairs both banks. A selection or delivery failure restores the old selector before failing closed.</p>

![Bank publication workflow](../assets/illustrations/next-policy/04-bank-publication-sequence.svg)

<p class="figure-caption">The consumer writes the packed banks, appends and binds a native template when the graph needs replacement, reads back the selector, and dispatches installation receipts to Blender nodes. Alternative frames distinguish ordinary staging and repair. A failed selector change or delivery restores the old selector before bounded failure-output closure retries.</p>

The admission facts require two distinct valid bank indices and an admitted
publication context. If the active bank is invalid, `repair_gate` first waits
for confirmed failure-output closure. Only then may `repair_stage` repair both
banks. A failed stage or unclean pack fails closed. A wrong selector readback or
delivery receipt enters `restore_selector`; the old bank and graph bindings are
restored before the final failure output is attempted. The runtime bounds failed
closure retries and reports `indeterminate` if it cannot establish a reliable
output.

Both successful delivery and a successful `closed` receipt in `fail` reach the
same `terminal` phase. The reducer does not store separate success and failure
end states. A failed closure receipt remains in `fail` and requests another
closure attempt; it has not reached `terminal`.

**Simplification candidates B1 and B2.** `stage` and `repair_stage` have the same
receipt and outgoing transitions, so one phase could carry a `repair` effect
variant while retaining the close-before-repair gate. The candidate bank is also
mathematically `1 - active_bank` for this fixed two-bank resource and is already
derived by `GradeResource`; storing both indices duplicates a fact. Either
change must retain the distinct-bank admission check, repair ordering, selector
restoration, and fail-closed retry bound.

## Publication strategies in the comparison example

The repository contains a publication comparison example under
`examples/publication_compare`. Its policies are useful design experiments,
but they are not one sequential production pipeline. Production uses the
two-bank transaction above, the save-packing helpers described below, and the
separate Bake transaction later in this chapter.

### Immutable parameter-image transaction

<a id="next-policy.parameter-publication"></a>

`examples/publication_compare/policy/parameter_publication.py` models a fresh
immutable image: stage, snapshot, bind, commit, activate, deliver, then retire.
Stage or snapshot failure goes directly to visible failure and retirement.
Failure from binding through delivery enters the restoration sequence
(`restore_bindings`, `restore_metadata`, `restore_resource`) first.
The comparison node calls it from `examples/publication_compare/nodes.py`.

Its separate `candidate_effect()` permits reuse only when the candidate is not
exposed, and allocation only while the pool contains fewer than three images.
`retirement_effect()` protects current and candidate images; removal requires
quiescence, zero native users, and no protection. These are allocation predicates,
not extra phases of the binding transaction.

![Immutable parameter-image publication](../assets/illustrations/next-policy/05-parameter-publication.svg)

<p class="figure-caption">This strategy keeps the current and candidate versions separate through binding and activation. Every restoration component is attempted after a failed transaction.</p>

![Immutable parameter publication workflow](../assets/illustrations/next-policy/05-parameter-publication-sequence.svg)

<p class="figure-caption">This comparison-only sequence follows one fresh immutable candidate. Each operation returns a receipt before the next action is authorized. Failed binding through delivery enters restoration; every restoration component is attempted even if an earlier component fails.</p>

### Shared-image transaction

<a id="next-policy.image-publication"></a>

`src/policy/image_publication.py` is also exercised by the comparison example.
It snapshots an existing image, uploads and packs when the snapshot is not
already matching and clean, commits metadata, delivers, and retires. Upload,
packing, or metadata-commit failure enters restoration. Restore-upload failure
stops restoration immediately; restore-pack failure or an unclean restored image
does the same. Only successful restoration of both reaches restore-metadata,
after which the transaction still reports failure. Preparation or snapshot
failure, and failed delivery, go directly to failure and retirement. Production
save handling instead calls
`request_save_packing()` and `finish_save_packing()` for a generated dirty
parameter image. Those helpers do not claim a new publication.
Bake production does not call this reducer: it uses `policy/bake.py`,
`ImageSnapshot`, and the admitted `PublicationGate.commit()` transaction
described below.

![Shared-image publication and restoration](../assets/illustrations/next-policy/05b-image-publication.svg)

<p class="figure-caption">The shared-image strategy can skip upload and packing when the captured image is already matching and clean. Its rollback still cannot make stale output current.</p>

![Shared image publication workflow](../assets/illustrations/next-policy/05b-image-publication-sequence.svg)

<p class="figure-caption">This comparison-only sequence changes one existing image. The clean-snapshot branch skips upload and packing. Restore-metadata is reached only after restore-upload and restore-pack succeed; failed restoration goes directly to visible failure and retirement.</p>

### Compositor supersession

<a id="next-policy.compositor-publication"></a>

`src/policy/compositor_publication.py` protects a compositor snapshot with a
positive scene ID and epoch. It is used in production by `PublicationGate` for
finished/reset evaluation callbacks and activity observations. Its live
`admit`/`superseded` publication effect is used by the comparison example's
`snapshot_commit()` path. Admission of an eligible unprotected snapshot emits
an epoch without changing state. The subsequent `superseded` receipt records
the protected scene and epoch; a successful later completion for the same scene
clears protection.
Old epochs, other scenes, cancellation, and non-quiescent reset are ignored.

![Compositor supersession protection](../assets/illustrations/next-policy/05c-compositor-publication.svg)

<p class="figure-caption">The production gate uses the callback and reset transitions; the live admission/supersession flow is comparison-only. Protection prevents a second live swap until a later evaluation completes.</p>

![Compositor supersession workflow](../assets/illustrations/next-policy/05c-compositor-publication-sequence.svg)

<p class="figure-caption">Live admission and fresh-image binding belong to the comparison example. Production also delivers evaluation-finished and reset observations to the policy. An older epoch, a different scene, or an unsuccessful completion leaves protection in place.</p>

## Bake requests and managed output

<a id="next-policy.bake"></a>

Bake is a separate production transaction for the shared Grade and Grade Stack
nodes. Per-Node Grade nodes deliberately have no bake controls: their purpose is
animated, key-framed adjustment, so turning those values into a static image
would discard the workflow they represent. Shader and Compositor Grade/Stack
nodes use the same policy and manager, while each node owns a private wrapper
around its live kernel and its own baked-output selector.

`src/policy/bake.py` stores only the request phase, an optional request
signature and generation, and an optional error. A present generation is
positive; signature and generation are both absent in `idle` and `terminal`.
The request path is:
`idle -> queued -> running -> ready -> publishing -> activating -> terminal`.
`cancelling` is entered when a running helper must be withdrawn. A request is
accepted only with a non-empty signature, a positive generation, an admitted
queue slot, and no other request for that node. `can_enqueue()` is a stateless
admission predicate: queued, running, and deferred-publication requests together
are bounded at eight. The manager snapshots the route and scene at click time,
then dispatches requests through one serialized helper lane.

Every helper completion, publication receipt, and activation receipt must match
both signature and generation. Uncorrelated reducer events leave state unchanged
and request no effects. A successful completion whose route has changed is
discarded, and a queued result is retired without touching the image. Changes
during a helper run request cancellation; load, undo, and frame lifecycle
events withdraw all accepted work. Publication and activation begin only inside
an admitted host gate. If the gate is busy, the ready artifact remains in a
deferred publication queue and is retried later. Once image publication has
started, the transaction owns the gate through activation or rollback, so a
partially committed image cannot be observed as current. Activation failure
restores the captured image and metadata in the same scope before the node is
returned to live output. Running cancellation retains helper ownership until
its final receipt or physical shutdown; a failed helper close retains ownership
and its error for retry. Terminal retirement removes the job and temporary
snapshot files. `terminal` is absorbing and does not itself imply success.

`output_policy()` is derived from the node's Use Bake setting, the desired
signature, the artifact signature, image validity, and any live-kernel error; it
is not another stored mode flag. Use Bake can be disabled while retaining the
managed Image binding. A stale artifact automatically selects the live Grade or
Stack result. An invalid managed image or an unrecoverable live kernel selects
the visible error path and clears baked selection rather than rendering stale
pixels. When a shared Image is selected by several Grade nodes, a successful
rebake updates the Image once and synchronizes every reader; rollback likewise
fans out to all readers.

![Bake request and publication policy](../assets/illustrations/next-policy/09-bake.svg)

<p class="figure-caption">A stale or cancelled request is retired before publication. Publication admission, image commit, activation, and rollback are one fenced transaction; derived output policy falls back to live output when the signature no longer matches.</p>

![Bake request workflow](../assets/illustrations/next-policy/09-bake-sequence.svg)

<p class="figure-caption">The click-time route snapshot enters the single helper lane. The helper receipt is checked again before the gate commits a managed float Image, activates the requesting node, and synchronizes shared readers. A changed signature before publication discards the artifact; a publication or activation error restores the ImageSnapshot.</p>

### Route selection and source constraints

`src/runtime/bake_routes.py` discovers the effective upstream graph and supplies
a cheap observation signature plus a full semantic signature that remains stable
across save/load. It resolves the exact graph owner and nested group occurrence,
rejecting ambiguous occurrences. It preserves
the legacy distinction between Image and UV bakes:

* An Image bake evaluates one output pixel per texel of a single ordinary still
  Image source through a pointwise graph. It uses
  the source image dimensions and rejects linked source coordinates, UDIM/tiled
  images, sequences or movies, multiview/multilayer sources, unsupported
  projections, and feedback where the destination Image is also an input.
* A UV bake is selected for a material graph with multiple image inputs, linked
  source coordinates, surface-dependent inputs, or an existing UV-domain
  destination. It requires Cycles, an active render UV
  map in the 0-1 tile, finite non-degenerate faces, bounded non-overlap, the
  selected material slot, and a render-visible mesh in the selected scene.
  Alembic and mesh-cache geometry, topology-changing modifiers, unsupported
  UV/deformation modifiers, hidden render meshes, and world UV routes are
  rejected explicitly. Dimensions and overlap work are bounded by the pixel
  and comparison budgets.
* A Compositor bake uses the compositor graph and its native output route. It
  cannot write a UV-domain destination. Unsupported compositor sources and
  scene/render observations become part of the signature or block the route
  before a helper is started. Shader to RGB, movie-clip, and mask sources are
  rejected explicitly.

The full signature includes graph and Grade settings, source file and sidecar
identity, effective source pixels, scene/render state, and (for UV routes)
mesh attributes, color attributes, weights, corner normals, smoothing/sharp
edges, auto-smooth settings, active color metadata, UV geometry, and material
slot. Unsupported attribute data fails closed. The cheaper observation
signature is used for UI reconciliation; only the full signature can authorize
publication.

### Native evaluation and wrapper graph

`src/runtime/bake_worker.py` opens an isolated `.blend` snapshot, restores float
Image sidecars, and evaluates the native Blender graph. A Shader Grade bake
captures RGB and alpha in independent native passes through the Grade helper
Image nodes. A Grade Stack bake evaluates the complete node tree containing its
65^3 LUT; it does not run a Python approximation of the LUT. Compositor bakes
use a native compositor output/File Output EXR path. The worker returns a
checksummed artifact receipt only after dimensions, channels, finite pixels,
and the expected route identity have been verified.

`src/runtime/bake_graph.py` instantiates a private wrapper template for each Grade or Stack node
that uses baking. Authoritative Grade settings still determine the embedded
live kernel; the wrapper holds only the node's derived selection and reader.
A managed Image
reader and a live/baked selector sit beside it, with independent Color and
Alpha selectors in Shader graphs. Shader wrappers expose an optional Vector
input used only by baked sampling; when it is unlinked, the reader uses the
captured bake UV map, or the active render UV map for an Image bake. Compositor
wrappers use the compositor switch. Copies have private wrappers and selectors;
shared Grade nodes continue to share their live Grade kernel, and the managed
Image may also be shared. Updating the live kernel preserves the wrapper's
outer socket identities and its per-node Image binding.

### Managed Image publication

Bake publication uses the bake reducer's admitted transaction, `ImageSnapshot`
capture/restore helpers, and `PublicationGate.commit()`. It is intentionally
separate from the comparison-only `src/policy/image_publication.py` reducer and
its `run_image_publication()`/`snapshot_commit()` helpers. The destination is a
managed packed float RGBA Image with bake metadata, dimensions, domain, UV map,
and artifact signature. A new destination is installed only after the artifact
receipt is valid; an existing shared destination is captured before pixels,
colorspace, alpha mode, precision, and metadata are changed. Any failure in
packing, metadata, activation, or signature admission restores that snapshot
and synchronizes all readers. A successful rollback returns the initiating node
to live output with a visible bake error. Failed restoration invalidates the
managed Image and closes affected readers with visible failure output.

## Resource adoption and retirement

<a id="next-policy.resources"></a>

`src/policy/resources.py` contains two related decisions. `may_adopt()` is a
predicate, not a state machine: owner, node, space, completeness, image
validity, and image agreement must all be true. `runtime/grade_resources.py`
uses it at the boundary where a persisted host resource is considered the
installed resource.

The reducer sequences disposal and retirement. Disposal fences subscriptions,
then detaches the node's Grade and kernel references. Retirement observes the
native resource. A live, owned,
zero-user, unprotected resource is eligible for eviction; a non-live wrapper
can be evicted directly. After eviction, the policy requires a fresh eligibility
observation before native removal.

![Resource adoption and retirement](../assets/illustrations/next-policy/06-resources.svg)

<p class="figure-caption">Adoption is a conjunction predicate. Deletion is a separate receipt sequence with a fresh zero-user and protection check.</p>

![Resource retirement workflow](../assets/illustrations/next-policy/06-resources-sequence.svg)

<p class="figure-caption">Disposal optionally adds the fencing and detachment prefix to retirement. The consumer obtains native facts again after eviction, so the original zero-user observation cannot by itself authorize native deletion.</p>

**Simplification candidate R1.** The `disposal` and `retirement` entry paths
already share the suffix beginning at `observe`. Their two initial phases exist
only to issue the first effect. An initializer returning `(state, effects)` could
remove these entry phases, at the cost of a different runtime runner contract.
This offers less benefit than B1/B2 or P1. Disposal must still fence and detach
before observation; ordinary retirement must begin with observation. Native user counts remain authoritative; adding a
Python ownership ledger would create a second, stale source of truth.

## Gesture observer and participants

`src/policy/gesture.py` supplies scalar decisions to
`runtime/gesture_coordinator.py`. The coordinator owns the per-window gesture
collections, target filtering, and native event routing. The policy owns token
allocation, observer handoff, phase checks, deferred completion, participant
release, and undo permission.

### Observer installation

<a id="next-policy.observer"></a>

The observer state has `current_token` and `pending_token`, plus a monotonically
allocated serial. The first window observation invokes an installation. During a
replacement, the current observer remains admitted while the new token is
pending. Only an installation receipt for that pending token can promote it;
failure leaves the current observer. A lost current observer may leave a
pending replacement alive. Reset invalidates callbacks but preserves the serial.
The figure separates pending installation with and without a current observer;
losing the current observer while a replacement is pending moves between those
configurations. Reset always clears
both tokens, including from pending. Native input must match the current token;
an explicit adapter event with token `None` remains allowed. Handoff also checks
the captured gesture token and its armed/active phase. After installation, the
coordinator replays the latest move/finish or requests handoff for a newer gesture.

![Observer handoff policy](../assets/illustrations/next-policy/07-gesture.svg)

<p class="figure-caption">A stale installation or loss receipt has no authority. The current observer stays usable until the pending native installation succeeds.</p>

### Gesture participation

<a id="next-policy.gesture"></a>

The coordinator stores `armed`, `active`, and deferred finishing phases for each
gesture, together with its participating node targets. Movement of at least
three pixels on either axis crosses the active
threshold. Release or cancel is deferred until the native widget has applied its
final value; observation then authorizes participant completion. Activation
begins a node gesture unless another active participant already owns it, in which
case it requests a refresh. An armed gesture that finishes without activating
refreshes a changed target. Only the final active participant releases a node.
Native gestures do not authorize a manual undo checkpoint;
manual undo is allowed only for an adapter-owned changed gesture.

![Gesture participation in the runtime coordinator](../assets/illustrations/next-policy/07b-gesture-participants.svg)

<p class="figure-caption">The policy checks scalar token and phase facts. The runtime remains responsible for collection order, lookup, target filtering, and native event delivery.</p>

![Observer and gesture workflow](../assets/illustrations/next-policy/07-gesture-sequence.svg)

<p class="figure-caption">Observer acknowledgement precedes token promotion. Movement activates participants; finishing waits until the native widget has applied its final value. The coordinator releases a node only when its final active participant finishes, with optional auto-keying and adapter-owned undo handled by its effects.</p>

## Render preflight

<a id="next-policy.render-preflight"></a>

`src/policy/render_preflight.py` protects the render boundary. A ticket starts in
`waiting` with a render identity, scene identity, frame, subframe, and
generation. `runtime/publication.py` queues it and `nodes.py` performs the
main-thread reconciliation before resolving it.

The ticket releases only when all correlation fields match, the event is a
publication, the signature is non-`None`, it equals the published signature,
and there is no error. A same-generation mismatch or failure enters `failed`.
A stale generation is ignored so an old callback cannot fail a newer ticket.
Terminal receipts do nothing. The non-`None` condition is precise: this reducer
does not independently reject an empty string. Signature construction and other
policy assumptions must establish any stronger signature format rule.

![Render preflight authorization](../assets/illustrations/next-policy/08-render-preflight.svg)

<p class="figure-caption">The gate queues and wakes the waiting thread, but the reducer authorizes release only for an exact published signature. A mismatch fails closed.</p>

![Render preflight workflow](../assets/illustrations/next-policy/08-render-preflight-sequence.svg)

<p class="figure-caption">The render thread waits while Blender's main thread reads the exact frame and reconciles its Grade kernels. Admission can retry before reconciliation begins. An exact publication releases the ticket; a failure applies visible error output before delivering the failed ticket.</p>

**Simplification candidate P1.** `RenderPreflightTicket` currently repeats the
identity fields already held in its policy state so that cross-thread callers
can construct plain events. A ticket could instead expose a correlation value
derived from the state and centralize event construction. This is safe only if
the state remains immutable to the waiting thread and every callback still
passes the same render, scene, frame, subframe, and generation checks.

## How the proofs should be read

The policy requirements are executable contracts, not a model of all Blender
behavior. For example:

* `requirements/preparation.inv` proves latest-demand replacement and receipt
  correlation; it does not prove executor cancellation.
* `requirements/preparation_join.inv` proves the all-three barrier and delayed
  error; `grade_preparation.py` supplies the physical `gather` and shielding.
* `requirements/node.inv` proves current/full/error presentation decisions;
  runtime checks and host tests must establish kernel structure, image contents,
  and graph ownership.
* `requirements/helper.inv` proves generation and job fencing, escalation, exit
  ordering, and cleanup ownership; transport queue ordering remains an adapter
  contract.
* The bank, image, and resource requirements prove fail-closed sequencing and
  eligibility predicates, while their consumers perform native operations and
  collect receipts.
* `requirements/gesture.inv` proves scalar token, phase, participant, and undo
  decisions. It does not prove the coordinator's collection bookkeeping.
* `requirements/render_preflight.inv` proves exact release correlation and
  stale-generation handling. It does not prove that Blender's scene snapshot
  is correct.
* `requirements/bake.inv` proves bounded admission, signature/generation
  fencing, stale-result discard, cancellation, publication/activation rollback,
  and the derived live/baked/error output policy. `runtime/bake_manager.py`,
  `bake_routes.py`, and `bake_worker.py` supply the native snapshot, route, and
  Blender evaluation contracts that the reducer intentionally does not model.

Some named requirements make the review points especially concrete. The
preparation queue properties are `running_request_only_replaces_latest_demand`,
`final_receipt_starts_latest_successor`, and
`obsolete_failure_does_not_publish_error`. The join uses
`any_completion_order_joins_after_all_three` and
`child_error_is_retained_until_last_retirement`. The node uses
`full_quality_is_required_for_current_output`,
`current_failure_clears_applied_output`, and
`stale_full_result_updates_drag_preview`. The helper uses
`stale_generation_is_ignored`, `cancel_request_retains_active_slot`, and
`cleanup_failure_retains_owner_and_error`. The production bank uses
`repair_requires_successful_closed_receipt`,
`selector_change_requires_clean_staging_receipt`, and
`failed_delivery_restores_original_selector`. Resource deletion uses
`deletion_requires_eviction_and_fresh_eligibility`; gesture behavior uses
`observer_handoff_commits_only_after_ack`,
`last_participant_authorizes_release`, and `native_finish_never_pushes_undo`;
render release uses `release_requires_correlated_exact_publication` and
`stale_generation_cannot_release_or_fail_current_ticket`. These are the
concrete contracts behind the diagrams and the simplification notes above.
Bake uses `request_requires_admission_and_valid_identity`,
`completion_requires_exact_identity_and_current_signature`,
`publication_requires_admission_and_current_signature`,
`publication_failure_authorizes_rollback`,
`activation_failure_authorizes_rollback`, and
`stale_bake_automatically_uses_live_output`. These properties establish the
policy's authorization boundary; native snapshot correctness and rollback
success remain adapter premises. The `request_runs_and_publishes` and
`failed_request_retires_without_publishing` witnesses exercise successful and
failed request paths. Mutations remove generation matching, current-signature
matching, or stale-output fallback to check that the corresponding properties
detect each weakened fence.

## Follow one edit through the layer

Suppose the last installed kernel is `Z`, with full quality. The user changes
settings quickly enough to request `A`, then `B`, then `C` while `A` is still
running. The node policy and preparation policy each retain different facts:
the node tracks what may be displayed, while the preparation scheduler tracks
which immutable snapshot occupies its worker.

| Event | Demand, worker, and installation |
|---|---|
| Settled before edit | Demand `Z`; worker idle; `Z` full, current. |
| Request `A` | Demand `A`; start worker `A`; retain `Z` as preview. |
| Request `B`, then `C` | Demand becomes `C`; `A` stays in the worker slot; `Z` remains preview. |
| Final success for `A` | Retire `A`, start `C`; outside a gesture, ignore `A` at the node; retain `Z` preview. |
| Final success for `C` | Worker idle; matching preparation authorizes build `C`; `Z` remains preview. |
| Installation success for `C` | Demand and installation are `C` full; presentation becomes current. |

If `A` fails instead, the preparation policy suppresses that obsolete failure
and starts `C` after `A` retires. If the current `C` build fails, node policy
clears the applied kernel and moves to error output. This trace explains why
the two signature state machines are not redundant: one correlates prepared
data, and one correlates a node's installable graph and rendered output.

## Source map and reproduction

This chapter's diagrams link to authored D2 in the repository's
[`docs/book/diagrams`](https://github.com/rei277hz/chromaticity/tree/main/products/perceptual-grade-book/docs/book/diagrams)
directory. All figures use the pinned D2 distribution's ELK layout engine.
The generated figure hashes, layout flags, and renderer pin are recorded in the
[diagram provenance manifest](../downloads/provenance/next-policy-diagrams.json).
The links below open the implementation, formal requirements, and runtime
effect consumer. The parameter-image policy is in the comparison example; the
other listed policies are in the product's `src/policy` package.

* Preparation scheduler: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/preparation.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/preparation.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/preparation.py).
* Preparation join: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/preparation_join.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/preparation_join.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/grade_preparation.py).
* Node output: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/node.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/node.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/nodes.py).
* Helper process: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/helper.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/helper.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/execution.py).
* Production bank publication: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/bank_publication.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/bank_publication.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/bank_publication.py), called from `nodes.py`.
* Immutable parameter-image comparison: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/examples/publication_compare/policy/parameter_publication.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/examples/publication_compare/requirements/parameter_publication.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/examples/publication_compare/runtime/parameter_publication.py).
* Shared-image publication: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/image_publication.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/image_publication.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/image_publication.py), exercised by the comparison example.
* Compositor publication gate: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/compositor_publication.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/compositor_publication.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/publication.py); live snapshot publication is comparison-only.
* Resource lifecycle: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/resources.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/resources.inv) · [consumers](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/resource_lifecycle.py) and [Grade resources](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/grade_resources.py).
* Gesture coordination: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/gesture.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/gesture.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/gesture_coordinator.py).
* Render preflight: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/render_preflight.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/render_preflight.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/publication.py), resolved from `nodes.py`.
* Bake requests: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/bake.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/requirements/bake.inv) · [manager](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/bake_manager.py) · [routes](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/bake_routes.py) · [worker](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/bake_worker.py) · [wrapper graph](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/bake_graph.py).

Regenerate the diagram assets and both English reading formats from the
repository root with the declared Buck2 targets:

```sh
buck2 build --remote-only //products/perceptual-grade-book/diagrams:assets
buck2 build --remote-only \
  '//products/perceptual-grade-book:site[html]' \
  '//products/perceptual-grade-book:technical-report[pdf]' \
  '//products/perceptual-grade-book:technical-report[epub]'
```

The site target includes the English and Simplified Chinese editions; the policy
chapter and its 25 generated SVGs appear only in English. The diagram source
files, D2 archive, renderer adapter, and figure manifest are declared Buck2
inputs, so the first command is reproducible without a system D2 installation.

Build and run the product policy evidence with Buck2's remote execution:

```sh
buck2 build //products/perceptual-grade-next-blender:verify_policies --remote-only
buck2 build //products/perceptual-grade-next-blender:proof_bake --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_verification --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_preparation \
  //products/perceptual-grade-next-blender/tests:policy_preparation_join \
  //products/perceptual-grade-next-blender/tests:policy_node \
  //products/perceptual-grade-next-blender/tests:policy_helper \
  //products/perceptual-grade-next-blender/tests:policy_resources \
  //products/perceptual-grade-next-blender/tests:policy_image_publication \
  //products/perceptual-grade-next-blender/tests:policy_compositor_publication \
  //products/perceptual-grade-next-blender/tests:policy_bank_publication \
  //products/perceptual-grade-next-blender/tests:policy_gesture \
  //products/perceptual-grade-next-blender/tests:policy_render_preflight --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_bake \
  //products/perceptual-grade-next-blender/tests:bake_manager_runtime \
  //products/perceptual-grade-next-blender/tests:runtime_bake_routes \
  //products/perceptual-grade-next-blender/tests:bake_installed --remote-only
```

These checks are deliberately scoped to `products/perceptual-grade-next-blender`.
They complement runtime and installed-host tests; passing the `.inv` proofs
alone is not evidence that a native image write, process operation, or gesture
observer succeeded.

## A simplification order

The strongest low-risk reductions are the ones that remove duplicated facts
without weakening a correlation fence:

1. Merge bank `stage` and `repair_stage` into one staging phase with an explicit
   repair effect, while preserving close-before-repair.
2. Derive `candidate_bank` from the active bank for the fixed two-bank resource.
3. Centralize render-ticket correlation construction so the ticket does not
   duplicate policy-owned identity fields.
4. Consider replacing the fixed preparation join only after its physical
   retirement, first-error, duplicate-receipt, and cancellation guarantees have
   equivalent executable evidence.

Helper generations and gesture tokens are not redundant state: they protect
against process restart and native observer replacement. Removing them would
require a new runtime contract, not just a smaller diagram. Likewise, replacing
the derived node presentation modes with stored booleans would make stale or
partial output easier to present as current.
