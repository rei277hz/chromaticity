# Blender runtime policies

<a id="grade-policy.overview"></a>

This chapter documents the Blender runtime policy layer in
`products/perceptual-grade-next-blender`. The policies are host-free Python:
they observe facts from Blender or a worker, reduce one event at a time, and
return effects for a runtime consumer to perform. They do not call Blender,
start threads, write images, or send process commands themselves.

Each machine is a small protocol:

```text
state + event -> policy.step(...) -> new state + effects
```

An effect is the policy's authorization for one external operation. The runtime
executes it. When completion affects later decisions, an operation receipt
returns as the next event; synchronous authoring admission needs no completion
event. This keeps transitions testable while making the side-effect boundary
explicit.

![The policy and effect-consumer boundary](../assets/illustrations/grade-policy/00-policy-layer.svg)

<p class="figure-caption">Grade settings remain authoritative. Runtime observations enter a pure reducer. Its effects authorize adapter operations, and receipts return as events.</p>

## What a policy stores

<a id="grade-policy.contract"></a>

The design goal is to store independent facts and derive readiness from them.
The simplification candidates below identify places where the implementation
still duplicates facts or phases. A signature is an immutable correlation key
for a request. Job IDs and observer tokens distinguish receipts whose lifetimes
must not be confused. The render gate correlates publication through the exact
active ticket and its exclusive scope. Absence is `None`; an empty string is
never a stand-in for "no demand".

The common safety rules are:

* Correlation checks govern receipts. Stale helper sessions, job IDs, and
  gesture tokens are ignored. Render publication requires the exact active
  ticket and matching scene and time inside its exclusive scope. During a
  gesture, a superseded node result may still become a preview. A node-owned
  Grade can also display a superseded full result from active timeline playback.
* One-shot completion receipts cannot complete the same slot twice. Declarative
  node output effects deliberately repeat on idempotent events so the consumer
  can reconcile host state; preview receipts can also repeat.
* A current failure clears the renderable installation and selects the visible
  error path. A stale failure cannot damage newer demand.
* The consumer executes effects in order and reports success or failure. Policy
  code never performs a best-effort side effect in an exception handler.

The `.inv` files in `src/requirements/` and beside feature policy packages
describe these transition contracts and examples. The verifier checks the
declared properties against the Python source under their stated assumptions.
It does not prove Blender's native observations, image validity, thread
affinity, worker implementation, or collection bookkeeping. The runtime tests
and installed Blender tests cover those adapter premises.

Read an edge as **event or receipt [condition] / requested effect**; the condition
and effect are omitted when unnecessary. Each box represents one phase, or one
configuration of facts for a policy that has no phase field. Phase labels match
the implementation; configuration labels describe derived states rather than
additional stored flags. Sequential phases always have separate boxes.
`running` and `desired` abbreviate preparation signatures; `current` and
`pending` in the observer figure abbreviate tokens. For synchronous
transactions, `success` and `failed` abbreviate operation receipts.
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

## Color authoring: ownership before preparation

<a id="grade-policy.color-authoring"></a>

`src/features/grade/color_authoring.py` consults the per-handle ownership policy
before ordinary Grade preparation. The sparse `Claim(origin_handle,
restore_offset)` holds the current owner and the exact authored return
position. An absent claim means the handle has no automatic-restoration owner.
The symbolic verifier checks a `State` to `State` transition, so the runtime
projects the claim's owner into `State(origin_handle: Optional[int])` for each
edit. A capture stores the owner returned by that transition with the new
return position.

The events are `manual`, `push`, `restore`, and `clear`. A push by the current
owner preserves the earlier return position. A push from another owner returns
`capture`, authorizing the runtime to capture the handle's current position
before moving it. Manual editing and explicit clearing return `clear` only
when a claim exists. Restoration clears a claim only for its current owner
when the runtime reports `at_baseline`; a constrained or blocked return keeps
the claim. `Effects(action: Optional["capture" | "clear"])` is the sole
permission to replace or remove that ownership metadata. Events with no
authorized mutation have empty effects.

The runtime combines these scalar decisions with a numerical transaction. It
pins the edited hue, pushes neighbors to preserve every cyclic 4° gap,
including the seam in either edit direction, and then restores claimed offsets
as far as the same constraints allow. Manually editing a displaced hue starts
from its current position and detaches only that handle. Aggregate
`Effects(settings: Optional[Settings], claims: Optional[Claims])` authorizes
the single Blender consumer to apply settings and claim replacements together
in one edit scope. Callbacks and error handlers do not bypass that consumer.

The claims do not affect the mathematical settings signature, prepared image
payloads, Stack function, or bake freshness digest. A separate undo fingerprint
includes them, so editing-history changes can still restore correctly even
when the effective transform is unchanged. `COLOR_RESOLUTION_SCHEMA = 1`
versions Grade, preparation, and Stack derived signatures independently of
template topology and texture schemas. Bake freshness still observes the raw
control values, so equal effective repairs do not hide an authored edit. This
authoring boundary adds no template group, role Image, or texture-layout change.
Node-owned claims clear on an
actual frame or subframe change; repeated notifications at the same time do
not clear them. Shared Grade claims survive timeline changes. A Peak change
clears claims and resolves the new hue geometry and radial Adaptance limits in
one transaction. Reset, copy, conversion, load, and undo adapters must preserve
this ownership boundary rather than writing metadata on their own.

The 24 hue controls and eight Adaptance axis controls have custom RNA
getters/setters backed by explicit ID-property keys. Blender's native
`is_property_set()` and `property_unset()` do not describe or clear that
storage. Reset therefore removes those keys explicitly, while ordinary Color
properties retain native RNA handling. The authoring effect consumer records
the actual key presence before a write and restores it on failure: an absent
key remains absent rather than becoming an explicitly stored default.
Ownership metadata stays inside the existing transaction and clear effects;
this storage repair adds no policy state or numerical signature field.

Animation uses a different admission path. Invalid sampled hue rows are
projected to the unique closest feasible lifted angles under squared-angle
distance. The repair solve uses a 4.0001° gap before float32 storage, then
checks the stored row against the public 4° minimum; an already-valid row is
preserved exactly. Finite out-of-range Adaptance targets
are shortened along their a/b ray; nonfinite requests fail visibly. These
effective settings feed preparation without changing authored values,
keyframes, or ownership claims. **Limited** compares raw with effective
settings and is not an independent persisted validity flag.

![Color authoring and evaluated constraints](../assets/illustrations/grade-policy/10-color-authoring-sequence.svg)

<p class="figure-caption">The runtime solves geometry and asks the scalar policy for capture or clear permission. One consumer applies the composed settings/claim effects before requesting ordinary preparation. Invalid animated samples produce effective settings without rewriting keys.</p>

The symbolic requirements establish scalar ownership and effect admission;
they do not prove the numerical optimizer or float equality at the return
position. Runtime and numerical tests cover the cyclic geometry, exact captured
baselines, push/restore interactions, and evaluation projection. The scalar
proof, nine numerical checks, and 15 reversible-edit runtime checks pass. Native
animation, conversion, and provenance-only undo checks also pass on current
Blender and LTS. The [Blender validation record](testing.md#blender-extension)
separately records LTS native undo crashes before the hue checks and the active
[fallback-lifetime repair](#persistent-fallback-lifetime-and-undo). Earlier
passing retries do not establish that this separate defect is fixed. The
earlier Stage 3 receipts do not certify these authoring adapters.

## Preparation: latest demand, one worker

<a id="grade-policy.preparation"></a>

`src/policy/preparation.py` is used by `src/runtime/preparation.py`. Its state is
just `desired_signature` and `running_signature`. A request always replaces the
latest demand. If no work is running, the request also returns
`prepare_signature`; otherwise it waits for the current physical worker to
retire. A preview receipt publishes an intermediate result but does not free the
running slot. A final receipt for the running signature retires that slot and,
when a newer request exists, authorizes the newest successor.

![Latest-demand preparation scheduling](../assets/illustrations/grade-policy/01-preparation.svg)

<p class="figure-caption">A superseded success can still be delivered as a preview. A superseded failure is suppressed, and the latest demand is started after the old worker's final receipt.</p>

The distinction between preview and final matters. The host preparation lane
may produce a preview and then continue working. Treating the preview as
retirement would allow a second job to overlap the physical slot. Conversely,
withdrawing demand does not claim that the worker has stopped; its final receipt
still provides the retirement fence.

The owning runtime also fences source lifetimes. `runtime/preparation.py`
coordinates the asynchronous Grade preparer and the main-thread-polled Stack
helper. The Grade preparer owns its worker pool. Withdrawing demand leaves the
physical slot occupied until the Grade work or Stack helper retires.

If the coordinator itself fails, it keeps the original exception and discards
undelivered preparations. Later requests and render waits report that cause.
The main-thread timer waits for publication admission, clears pending
installations, and delivers the error output once. Active helper work remains
owned and polled until retirement.

Each physical job records the playback session that requested it, or `None`
for ordinary requests. The job's preview and final receipts carry the
originating session to every subscriber. When a request reuses an already
prepared value from the cache, its new receipt carries that request's session.
Equal signatures share prepared values across sessions. The receipt's session
determines whether playback can display that value after the playhead has
moved on.

### Concurrent Grade preparation

<a id="grade-policy.preparation-join"></a>

`src/features/grade/preparation.py` submits three jobs for each immutable Grade
input before awaiting any of them. Linear, Tone with Color, and boundary
geometry run concurrently. The Tone job prepares Color against the frozen
Tone result. Each invocation owns its three futures and awaits one result
from each in a shielded `asyncio.gather` group.

The group waits for every worker to retire before assembly or error delivery.
Cancellation waits for the same group before releasing the preparation slot.
Receiver failures are reported in component order. If the receivers complete
normally, the first observed worker exception takes priority over timing
callback failures.

Once all three results are available, the preparer checks that Tone and the
boundary geometry share the same appearance context and assembles a
`PreparedGrade`. The parameter atlas is assembled in a final shielded worker
call before the runtime returns the complete parameter bundle.

## Central scheduling and recovery

<a id="grade-policy.scheduler"></a>

`src/policy/scheduler.py` defines the scalar priority contract used by
`src/runtime/scheduler.py`. The scheduler admits and orders host-thread work.
Feature owners still run their worker lanes and retain authority over source
signatures, publication, and rollback. Render preflight and lifecycle recovery
remain correctness work. A foreground plot is selected before unrelated Grade
consistency or Bake work, and the Grade tasks required by that plot are
promoted until the exact plot can run. Plot generations are latest-only.

Initial extension enable uses a `starting` phase. It permits Grade consistency
and exact render work while fencing plot captures and manual Bake. The startup
task inventories project data after Blender releases its restricted
registration context, repairs Grade kernels, and then reconciles Bake output
selection. File load and undo use a stricter `recovering` phase. They discard
old task demand, repair Grade kernels before Bake output reconciliation, and
admit plots only after the saved project is coherent. Exact render preflight
can establish consistency for its own scene and frame during that fence.

Appearance Distribution can publish a bounded GPU preview from current input
samples and validated Grade parameter images. Exact capture remains queued to
replace that preview after the controls settle. A retained trace remains
visible while either replacement is being prepared, with its freshness
reported separately.

The host scheduler advances one bounded unit at a time. A higher-priority task
may request cancellation at a worker checkpoint, while the feature owning the
physical operation continues polling until retirement. Failed owners remain
visible and retry with bounded backoff. Saving never serializes executor
queues. Load recovery discards plot demand and reconstructs consistency from
authoritative settings, receipts, and Bake provenance before accepting new
plots.

The scalar policy proof is paired with scheduler selection, coalescing,
startup and recovery admission, synchronous render dispatch, and source-scoped
preparation tests. Runtime ordering tests do not import Blender.

## Node output policy

<a id="grade-policy.node-output"></a>

`src/features/grade/policy/node.py` is the per-node decision layer. The runtime creates and
updates it from `src/features/grade/host.py` and consumes its effects in `_consume_effects`. The
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
LUT. Its runtime index identifies the Shader/Compositor tree type, resource
slots, and expected structure. There is one Stack topology per tree type;
preview/final resolution, cube strides, and atlas-height scaling come from a
dedicated 1×1 RGBA32F runtime configuration image bound alongside the LUT and
working-space basis images. The final frozen
pinned Blender 5.2.4 Stage 3 generator produced
a **3,688,385-byte** library containing 12 groups, a **9,464-byte** runtime
manifest, and a **67,226-byte** Stack shader. These are uncompressed artifact
sizes, not the extension ZIP's compressed size. Its **7,896,941-byte** detailed
structure report is a build diagnostic and is excluded from the extension ZIP.
The stored kernel inventory is:

| Kernel | Nodes | Links |
|---|---:|---:|
| Grade Shader | 1,795 | 3,099 |
| Grade Compositor | 3,042 | 5,402 |
| Stack Shader | 214 | 320 |
| Stack Compositor | 238 | 356 |

These counts describe the stored kernel trees, not an expanded-occurrence cost
or an evaluation-speed measurement. The remaining eight groups are private bake
wrappers and interface-specific pending/error fallbacks. The same Buck target
supplies the installed product and installed tests. Canonical graph
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

Exact structure receipts must survive both library append and runtime resource
binding. The receipt audit exercises the generated 12-group library through
both the bpy 5.3 wheel and the native Blender 5.3 executable; it also checks
Grade bindings in all three working spaces and both editor tree types. The
build-only Color emitter expresses its overflow threshold with two normal
float32 factors rather than a subnormal socket literal, which native Blender
can flush to zero. Receipt validation remains exact. Detailed expected structure
payloads are recorded only in the generator's diagnostic report, outside the
shipped manifest and ZIP.

Adoption, playback, and full validation share a metadata check for the two
parameter banks. Each bank must have valid role receipts, and the two banks
must own distinct images. Playback checks that the images are packed and clean.
Full validation also checks sampler wiring and reads the active bank's pixels.

Runtime parameter-sampler validation builds a fresh socket-to-link index from
the kernel's links for each validation call. Blender's RNA `socket.links`
lookup scans the tree's edges; repeating it throughout a large Grade caused
long save/recovery validation. The index preserves the same exact edge and
cardinality checks without retaining a cache across graph mutations. The native
`image_save_gui` regression passed in 33.338 s after this change; the preceding
same-fixture run timed out at 300 s with stacks in repeated `socket.links`
scans. That passing fixture retains real image packing failures, complete role
bundles, reload, dirty user-image preservation, and transaction rollback checks.
This is a fixture result, not a general kernel-evaluation latency measurement.

Compositor Grade output has a separate graph-level finite-value router. Stage 3
carries signed energy as `Ecarrier = E / 4096` and carries `J_A` explicitly.
Changed energy can recover `J_A = sign(Ecarrier) * sqrt(abs(Ecarrier)) * 64`;
disabled stages and inactive H–K repair retain the current `J_A` instead.
Positive Scale multiplies that coordinate directly and multiplies energy by
its square. Output projection uses `J_A` and a compensated distance to white,
avoiding an unscaled squared-energy
image. The router observes original source RGB and the final Stage 3 `H`, `a`,
`b`, chroma, carried energy, and reference energy. Each observed value must
satisfy `abs(x) < FLOAT_MAX`; projected RGB must satisfy `abs(x) < 65504`.
These strict bounds conservatively reject the representational endpoints as
well as NaN and infinity. Invalidity selects magenta `(1, 0, 1)`, and the
existing alpha-restoration path preserves source alpha.

This explicit coordinate avoids inferring semantic identity from equality of
stored energy, which can hide a Scale change after half-float underflow.
Active H–K repair still uses its original predicate and frozen post-Tone energy;
carrying `J_A` does not bypass repair for a negative achromatic coordinate when
reflected `H` is nonnegative. It adds no texture role, schema, or policy machine.
The production Compositor path can also retain Tone's raw response basis when
every authored Color family is inactive and H–K is provably inactive: `J_A >= 0`
or reflected `H < 0`. A negative achromatic coordinate with nonnegative
reflected H remains eligible for repair. The retained decode still passes the
actual AP1 cube-legality and endpoint checks. Uniform runtime output-matrix
rows compose with the cone-to-AP1 matrix before touching spatial cone values,
avoiding a separately rounded half-precision AP1 image on that legal identity
path. Active Color, including non-unit Web Scale, uses its transformed state.

After an illegal primary projected decode, this Compositor path evaluates one
retry at `0.99609375` times the radius and accepts it only if the actual decoded
RGB passes the same legality check. Already-legal primary output stays
unchanged; an illegal retry retains the interior-neutral fallback. Generic
full-Grade and Stack default projection paths retain their previous behavior.
These precision adaptations add no texture role, schema, or policy machine.
The shipped live-Viewer and source-carrier gates pass, with unchanged 0.01 Auto
and `1e-4` Full limits; [testing](testing.md) records the workload and evidence.

Validity always uses the original values. Ordered minimum/maximum operations
sanitize only the unused interpolation operand, so a NaN cannot contaminate
the selected magenta branch; accepted RGB values remain unchanged. This is a
check of observed source, state, and output, not a proof that every intermediate
is finite or numerically accurate. Finite saturation remains a separate
representational diagnostic. The router adds no policy machine: graph-value
invalidity and installation/publication failure retain their distinct paths.

The isolated router tests cover CPU and GPU final rendering with exact alpha
preservation. Blender promotes requested Auto precision to effective Full for
those final renders; live-Viewer acceptance separately checks actual Auto
half-precision image materialization.

The preparation signature identifies shared prepared Grade data; the desired
kernel signature can additionally identify the node's graph context. A current
preparation receipt must match both correlations. During a gesture, a superseded
success can update the preview. During forward or reverse playback, a node-owned
Grade can also preview a superseded full result when its originating session
matches the node's active session at delivery and installation. Stopping playback
closes that session and requests the selected frame. During playback, the frame
handler reconciles evaluated demand and offers a queued completion to the
publication gate before the next Viewer evaluation can start. Once current
full output exists, later receipts cannot replace it. A preview cannot
downgrade a full installation of the same signature.
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

![Node output and installation policy](../assets/illustrations/grade-policy/02-node.svg)

<p class="figure-caption">Presentation is derived from authoritative demand and installation facts. A stale receipt cannot replace a current result, and a preview is never render-ready.</p>

![Preparation and node output workflow](../assets/illustrations/grade-policy/01-preparation-node-sequence.svg)

<p class="figure-caption">Preparation owns the worker slot, while the node owns presentation. A, B, and C name settings versions; preparation and kernel signatures still have their separate correlations. This trace runs outside a gesture and timeline playback, so an obsolete A cannot replace the retained Z preview. A preview receipt does not retire A. Current C is instantiated from the bundled native template and installed through existing publication effects. Preparation, template, binding, or installation failure selects visible magenta output with alpha preserved.</p>

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

<a id="grade-policy.helper"></a>

`src/policy/helper.py` governs one helper process and one physical work slot.
`runtime/execution.py` translates its effects into process and transport
operations. Protocol version 2 is shared by the host and worker through
`runtime/transport.py`. Each runtime launches once and creates a UUID session
and a random hello token. Both sides check the session on incoming frames.
The host checks the protocol version and token in the worker's `hello` before
dispatching the probe. A replacement runtime creates a fresh session, so it
can safely reuse numeric job IDs.

Startup proceeds from `stopped` to `starting`, then `probing` after `hello`, and
to `ready` only after a successful probe result matches `probe_id` and
`active_id`. The probe result is published and leaves the work slot idle.
Ordinary submissions are accepted afterward and dispatch through their own
submit transition. A preview for an ordinary active job publishes while its slot
remains occupied. A final result or cancellation retires that slot and can
dispatch the next queued job. A cancel request keeps the slot occupied until a
matching final receipt or physical exit. Timeout events carry the deadline
stage and have an effect only when that stage matches the current phase.

![Helper process lifecycle](../assets/illustrations/grade-policy/03-helper.svg)

<p class="figure-caption">Shutdown escalates from a channel shutdown request to terminate, kill, and an explicitly unretired condition. Physical exit settles work before cleanup is attempted.</p>

![Helper process workflow](../assets/illustrations/grade-policy/03-helper-sequence.svg)

<p class="figure-caption">The process and transport perform only operations requested by helper effects. Cancellation leaves active work owned until its final receipt or physical exit. Shutdown deadlines control escalation; cleanup begins only after exit and completes through its own receipt.</p>

Failure or timeout moves a live process toward termination. A channel shutdown
uses `stopping`; a process without that transport uses `terminating`. Terminate
and kill timeouts lead to `unretired`, which keeps ownership visible rather than
pretending cleanup succeeded. After physical exit, one publication effect
settles the owned probe or job, and a separate queue effect cancels or fails
pending work. The policy enters `retiring`. Cleanup
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

## Production bank publication

<a id="grade-policy.bank-publication"></a>

`src/features/grade/policy/bank_publication.py` is the active production publication path. The
parameter-image code in `src/features/grade/host.py` constructs two packed banks, each with five
fixed RGBA32F image roles: scalar/Tone parameters, Color coefficients, Web
parameters, Web toes, and Adaptance parameters. `src/features/grade/bank_publication.py`
consumes the reducer's effects. One shared selector chooses the entire bundle;
there are no independent Stage 2 and Stage 3 publication policies. Every role of
the inactive candidate is staged and its schema, role identity, dimensions, and
content receipt checked before selection changes. An unchanged candidate role
may retain its clean matching payload. Selection is read back, then delivery
publishes the resource and dispatches installation results to all affected node
records.

Delivery invalidates all five active role Images before recording the bound
generation and dispatching successful installation results. Only after those
node receipts are current does it request a live compositor reevaluation. On
Blender 5.3, plain `ID.update_tag()` does not request `ID_RECALC_COMPOSITOR`;
the consumer reasserts each consuming scene's unchanged
`compositing_node_group` through its RNA setter, including nested Grade users.
This preserves root identity and topology while requesting the host's compositor
recalculation. The operation remains inside the policy-authorized delivery
effect and adds no policy state or machine. The final installed live-Viewer
fixture passes all 12 automatic updates; [testing](testing.md) records its
precision, reload-repair, and native-exit coverage.

The fixed role layouts occupy 2,916,976 bytes per bank (5,833,952 bytes, about
5.56 MiB, for both),
excluding the shared boundary image. The scalar/Tone image is 512×1; the Color,
Web, Web-toe, and Adaptance images are 8193×2, 4097×32, 1537×1, and 8193×4.
Role image contents remain derived from the authoritative settings. Schema 4
receipts and the v4 template marker reject mixed roles or obsolete saved
layouts instead of accepting partial data.

Field layout schema 6 fixes Adaptance at 32,768 cells, segmented into four
8193-pixel rows of RGBA32F (524,352 bytes per bank). This is one invariant
layout for every Grade, rather than a resolution chosen from authored values.
It replaces the 3,072-cell, 49,168-byte field: interpolation near a zero-support
boundary otherwise fails the unchanged extreme-grade RGB gate. The increase
is 475,184 bytes per bank. Earlier HDR-budget studies of the smaller field
remain historical diagnostics, not certification of the current layout.

Two scalar-image texels carry the four tonal anchors and four authored
Adaptance-row activity flags. They preserve exact-zero cardinal support when
the prepared Adaptance atlas is interpolated: sampling across a boundary must
not invent a correction in an inactive interval or at an inactive anchor.
The graph derives this support from authoritative controls, rather than
discarding small values with a tolerance. The scalar image remains 512×1, so
these fields do not change the bundle's byte size or publication mechanism.

When a required Grade tree is missing or structurally damaged, the admitted
stage/repair consumer appends the matching bundled template and binds both
complete role bundles before returning a clean staging receipt. Ordinary edits
retain the existing graph and all ten role image identities. Template append is an operation
inside the existing effect, not a new state or permission that bypasses the
publication gate.

![Production two-bank publication](../assets/illustrations/grade-policy/04-bank-publication.svg)

<p class="figure-caption">One selector publishes a complete five-role bank for Tone and Stage 3. An invalid active bank first closes output, then repairs both banks. A selection or delivery failure restores the old selector before failing closed.</p>

![Bank publication workflow](../assets/illustrations/grade-policy/04-bank-publication-sequence.svg)

<p class="figure-caption">The consumer stages all five roles, reusing only matching clean candidate payloads, before one selector changes. It appends and binds a native template only when the graph needs replacement. Failed selection or delivery restores the old selector before bounded failure-output closure retries.</p>

The reducer derives the candidate as `1 - active_bank` from a valid active
index. An invalid active bundle enters `repair_gate` and requests failure-output
closure. A confirmed closure enters `stage` with the repair effect, which
rebuilds both banks. Ordinary staging enters the same phase and updates the
inactive bank. A clean packed role is reusable when its contents match the
prepared receipt. A mismatch triggers a rewrite and repack before selection.

A failed stage or unclean pack requests failure output. A selector readback or
delivery failure first attempts to restore the old selector and graph bindings.
The reducer authorizes one retry at each closure phase. A second failed
closure reports `indeterminate`. Confirmed final closure reports
`failed_closed`, and successful delivery reports `committed`. All three
outcomes enter the same absorbing `terminal` phase.

At save time, `runtime/image_publication.py` consumes the bank policy's
packing decisions for generated dirty parameter images. Successful packing
requires both a packed file and a clean Image. Native errors propagate to
the save handler. This path leaves the selected bank and publication generation
as they were.

## Bake requests and managed output

<a id="grade-policy.bake"></a>

Bake is a separate production transaction for the shared Grade and Grade Stack
nodes. Per-Node Grade nodes deliberately have no bake controls: their purpose is
animated, key-framed adjustment, so turning those values into a static image
would discard the workflow they represent. Shader and Compositor Grade/Stack
nodes use the same policy and manager, while each node owns a private wrapper
around its live kernel and its own baked-output selector.

`src/features/bake/controller.py` coordinates the Blender Image transaction,
source observations, and output selection. It retries deferred selector
changes under the graph gate, including changes on nodes without a receipt.

`src/features/bake/policy/bake.py` stores the request phase and optional request signature.
The signature is present from acceptance through the active request and absent
in `idle` and `terminal`. Terminal effects carry errors for the manager to
report. A successful request follows
`idle -> queued -> running -> ready -> publishing -> activating -> terminal`.
`cancelling` is entered when a running helper must be withdrawn. A request is
accepted only with a non-empty signature, a free queue slot, and no other
request for that node. `can_enqueue()` is a stateless predicate over queue
capacity and per-node ownership. Queued, running, and deferred-publication
requests together are bounded at eight. The manager snapshots the route and
scene at click time, then dispatches requests through one serialized helper
lane. Each request has a unique artifact directory and uses the fixed filename
`bake.exr` within it.

The manager associates later policy events with their accepted request. Node
deletion withdraws the accepted request by its saved identity, so retirement
can proceed after Blender invalidates the node wrapper. The execution runtime
correlates helper receipts by session and job ID, and the
manager checks the returned signature before reporting completion. The policy
compares the current source signature at completion, publication, and
activation. Dependency generations still contribute to freshness checks. A
successful completion whose route has changed is discarded, and a queued result
is retired without touching the image. Changes during a helper run request
cancellation. Load, undo, and frame lifecycle events withdraw all accepted work.
Publication
and activation begin only inside the host gate. The manager sends the
publication event after acquiring the gate. If the gate is busy, the ready
artifact remains in a deferred publication queue and is retried later. Once
image publication has started, the transaction owns the gate through activation
or rollback, so a partially committed image cannot be observed as current.
Activation failure restores the captured image and metadata in the same scope
before the node is returned to live output. Running cancellation retains helper
ownership until its final receipt or physical shutdown; a failed helper close
retains ownership and its error for retry. Terminal retirement removes the job
and temporary snapshot files. `terminal` is absorbing and does not itself imply
success.

`output_policy()` derives output from the node's Use Bake setting, managed
Image validity, and live-kernel error. Turning Use Bake off selects live output
and retains the Image binding. When Use Bake is on, a valid Image remains
selected when its inputs change and the node displays a freshness warning with
the reason. An invalid selected Image or an unrecoverable live
kernel selects the visible error path. Toggle availability depends on Image
validity and live-kernel health. When several Grade nodes select a shared
Image, a successful rebake updates the Image once and synchronizes every
reader. Rollback likewise synchronizes all readers. Each reader keeps its own
input receipt.

![Bake request and publication policy](../assets/illustrations/grade-policy/09-bake.svg)

<p class="figure-caption">A stale or cancelled request is retired before publication. Publication admission, image commit, activation, and rollback are one fenced transaction. An already published Image remains selectable with a warning when its inputs change.</p>

![Bake request workflow](../assets/illustrations/grade-policy/09-bake-sequence.svg)

<p class="figure-caption">The helper writes bake.exr in the request's private artifact directory. A changed graph/settings digest or dependency generation before publication discards the artifact. The gate commits a managed float Image, activates the requesting node, and synchronizes shared readers. A publication or activation error restores the ImageSnapshot. Load and undo restore the selection and receipt and rebaseline transient source generations.</p>

### Route selection and source constraints

`src/features/bake/routes.py` discovers the effective upstream graph and supplies
a small graph/settings digest plus a cheap observation of each source Image.
It resolves the exact graph owner and nested group occurrence, rejecting
ambiguous occurrences. It preserves
the legacy distinction between Image and UV bakes:

* An Image bake evaluates one output pixel per texel of a single ordinary still
  Image source through a pointwise graph with unlinked source coordinates. It
  uses the source image dimensions. A value-only Shader graph with no source
  Image is the explicit constant case and produces a 1x1 Image. Image-domain
  sources must not be UDIM/tiled, sequences or movies, or multiview/multilayer;
  the destination Image cannot also be an input. In the isolated snapshot,
  ordinary source textures use flat projection, closest interpolation, extended
  edges, and identity texture mapping so each output pixel samples its source
  texel directly. UV-route sources retain their captured sampling settings.
* A UV bake is selected for a material graph with multiple image inputs, linked
  source coordinates, surface-dependent inputs, or an existing UV-domain
  destination. It requires an active render UV
  map in the 0-1 tile, finite non-degenerate faces, bounded non-overlap, the
  selected material slot, and a render-visible mesh in the selected scene.
  Alembic and mesh-cache geometry, topology-changing modifiers, unsupported
  UV/deformation modifiers, hidden render meshes, and world UV routes are
  rejected explicitly. A pixel budget limits image dimensions, and a separate
  comparison budget bounds the UV overlap check.
* A Compositor bake uses the compositor graph and its native output route. A
  compositor constant uses the scene's scaled output canvas rather than the
  Shader constant's 1x1 result. It cannot write a UV-domain destination.
  Unsupported compositor sources and scene/render observations become part of
  the signature or block the route before a helper is started. Shader to RGB,
  movie-clip, and mask sources are rejected explicitly.

The persisted bake receipt stores a small signature over the graph/settings
digest, route and UV context, and cheap metadata for every unique source Image:
its semantic ID, source kind and path, dimensions and channels, color and alpha
modes, packed or external status, packed size when available, and external-file
stat facts (device, inode, size, mtime, and ctime when available) for the image
and relevant sidecars. `src/features/bake/freshness.py` keeps runtime per-ID
generations for referenced Images, Meshes, and Objects, together with the durable
receipt codec. Blender evaluates mesh attributes, vertex weights, and custom
normals from the saved mesh. Their values are not scanned for a digest.
Observing these facts reads no source Image pixels or
packed/external Image bytes. Source and bake payloads are never hashed; small
graph/settings and metadata digests are allowed. At request acceptance, each
unique source Image is copied once into
the click-time snapshot so the helper evaluates a stable request; the `.blend`,
`.npy`, and `.exr` payloads are not hashed.

The helper returns the request signature with its pixels. For an output that
uses the scene canvas, this signature includes the expected pixel dimensions
so resizing the canvas cancels pending work. A published bake keeps the
original receipt signature and the Image's actual dimensions. Restoring the
canvas size therefore clears a size warning without a rebake.

The graph digest records effective socket values and links. Linked sockets
ignore unused defaults, and unavailable sockets do not enter the digest. The
fingerprint version makes older receipts stale while keeping their valid baked
Images selectable.

The settings digest includes every Linear, Tone, and Stage 3 numeric field,
including J/C response, fit, Global C Gain, Adaptance, and all Warp handles.
The same Stage 3 field inventory supplies node settings and bake observation.
It covers the bake target, every enabled Stack Grade, and live upstream Grade
or Stack nodes. This keeps completion fencing and persisted load/undo receipts
sensitive to Stage 3 changes as well as the immediate edit callbacks.

Freshness warnings are derived from the receipt, cheap Image metadata, per-ID
generations, graph/settings digest, and live route observation; no duplicate
`ready` or `stale` flag is stored. Nodes bound to a managed Image remain tracked
while Use Bake is off. A notified source update persists a source-invalidated
marker on each affected node's receipt, including when its cheap signature is
unchanged. A detected route, Grade, or Stack mismatch leaves the receipt
intact and warns while a valid Image remains selected when Use Bake is on.
Rebaking or explicitly binding an Image records a new node-specific baseline.
Output selection separately fails closed for an invalid Image or failed live
Grade.

Dependency notifications advance generations for changed Images, Mesh geometry,
and Object transforms. When Blender supplies update flags, an Object notification
with geometry or shading set but no transform update is ignored: Blender also
emits those flags for material changes, node changes, and derived selector
reconciliation. Mesh data has its own generation, while Object transforms,
material slots, modifiers, and other relevant metadata are observed separately.
Mesh shading-only notifications are also ignored. Recovery and synchronization
of the managed graph can emit these notifications.

After file load or undo, transient per-ID generations are rebaselined against
the cheap persisted metadata. A matching receipt with no recorded source update
clears the freshness warning.
A mismatched receipt remains available for a warning and does not disable a
valid selected Image. A valid Image without a readable receipt is marked
unverified. Rebaseline does not claim that pixel contents were checked.
External-file changes that preserve the recorded metadata may therefore be
missed. Scripts that change an Image
must explicitly invalidate it with
`bpy.ops.perceptual_grade.invalidate_image(image="Image Name")` or the
extension's exported `invalidate_image(image)` Python function; calling
`image.update()` alone does not reliably notify the tracker. Changes made by
scripts while the add-on is inactive can also be missed when their cheap
metadata is unchanged.

Passive reconciliation compares the cheap observations and per-ID generations;
it performs no image-sized hashing. Request, completion, publication, and render
boundaries check the current receipt, graph/settings digest, generations, and
metadata before accepting or activating output. This intentionally accepts the
documented blind spot for unnotified edits that preserve all recorded cheap
facts.

### Native evaluation and wrapper graph

`src/runtime/capture_host.py` opens an isolated `.blend` snapshot and restores
float Image sidecars. `src/features/bake/worker.py` evaluates the native Blender
graph. Shader Image and UV
bakes both run on Cycles CPU in the private scene. Switching the foreground
engine or Cycles device preserves pending and published Shader bakes.
An upstream managed UV bake
requires the UV route to preserve its surface sampling coordinates.
Cycles captures RGB and alpha in native passes through the Grade helper Image
nodes. A Grade Stack bake evaluates the complete node tree containing its 65^3
LUT; it does not run a Python approximation of the LUT. Compositor bakes use a
native compositor output/File Output EXR path. Render Layers inputs are
rendered by their scene's engine, which contributes to their freshness.
The worker returns a receipt only
after dimensions, channels, finite pixels, and the expected route identity have
been verified; it does not hash the `.blend`, `.npy`, or `.exr` payloads.

`src/features/bake/graph.py` instantiates a private wrapper template for each Grade or Stack node
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
The receipt identifies Grade and Grade Stack sockets by their public names,
including when they occur upstream. It ignores the generated `Socket_N`
identifiers of live, wrapper, and fallback interfaces, which can change during
kernel recovery. Rebuilding derived kernels therefore preserves a matching
receipt when the authoritative settings and public connections are unchanged.

### Managed Image publication

Bake publication uses the bake reducer's admitted transaction, `ImageSnapshot`
capture/restore helpers, and `PublicationGate.commit()`. The destination is a
managed packed float RGBA Image with bake metadata, dimensions, domain, UV map,
and freshness receipt. A new destination is installed only after the artifact
receipt is valid; an existing shared destination is captured before pixels,
colorspace, alpha mode, precision, and metadata are changed. Any failure in
packing, metadata, activation, or signature admission restores that snapshot
and synchronizes all readers. A successful rollback returns the initiating node
to live output with a visible bake error. Failed restoration invalidates the
managed Image and closes affected readers with visible failure output.

## Resource adoption and retirement

<a id="grade-policy.resources"></a>

`src/policy/resources.py` contains two related decisions. `may_adopt()` is a
predicate, not a state machine: owner, node, space, completeness, image
validity, and image agreement must all be true. `runtime/grade_resources.py`
uses it at the boundary where a persisted host resource is considered the
installed resource.

Local Grade ownership uses the containing datablock and a UUID stored on the
node. Renaming a node preserves its ownership, and copying a node gives the copy
a new UUID. The add-on rebuilds older name-owned kernels from the stored Grade
settings. Adoption and initial render preflight check generated graph structure
against the shipped template manifest and verify packed Grade boundary and
Stack LUT pixels against their content receipts.

The lifecycle coordinator attempts gesture restoration, subscription cleanup,
Bake withdrawal, and cache invalidation before Blender replaces IDs on load,
undo, or redo. A failed gesture restoration still allows the remaining steps
to run. Reconciliation releases the pinned resources and repairs installed
output after Blender finishes replacing the data.

The reducer sequences disposal, retention, and retirement. Disposal fences subscriptions,
then detaches the node's Grade and kernel references. Retirement observes the
native resource. A live, owned resource whose observation requests
`retain_for_undo` returns `Effects(action="retain")`, then terminates without
eviction or removal. The effect consumer sets the fake user; callbacks and
cleanup paths do not perform that retention mutation independently. A live,
owned, zero-user, unprotected resource without that retention requirement is
eligible for eviction; a non-live wrapper can be evicted directly. After
eviction, the policy requires a fresh eligibility observation before native
removal. This adds a branch to the existing resource policy, not a new machine.

![Resource adoption and retirement](../assets/illustrations/grade-policy/06-resources.svg)

<p class="figure-caption">Adoption is a conjunction predicate. Deletion is a separate receipt sequence with a fresh zero-user and protection check. The retention branch described here ends after its policy-authorized fake-user effect.</p>

![Resource retirement workflow](../assets/illustrations/grade-policy/06-resources-sequence.svg)

<p class="figure-caption">Disposal optionally adds the fencing and detachment prefix to retirement. The consumer obtains native facts again after eviction, so the original zero-user observation cannot by itself authorize native deletion. Undo-retained fallbacks take the retention branch instead.</p>

### Persistent fallback lifetime and undo

Blender's `ID.users` counts current references; it does not count every raw ID
reference retained by undo memfiles. A fallback with no current readers can
still be part of an earlier undo state. Ordinary cleanup therefore preserves
published pending/error node groups, including legacy helpers. It does not
use a zero user count to infer that undo has released them.
Legacy fallback recognition checks marker presence, so a historical marker
whose value is `0` or `False` still receives retention.

The fallback pool is lazy and has six supported variants:

| Output | Shader, no Vector | Shader, Vector | Compositor |
| --- | --- | --- | --- |
| Pending passthrough | one reusable group | one reusable group | one reusable group |
| Error magenta, preserving alpha | one reusable group | one reusable group | one reusable group |

Acquisition scans the current Blender datablocks, tries the current group
first, and reuses a local group only after its host type, mode, interface, topology,
effective settings, and exact manifest structure receipt validate. A marker or
matching name alone cannot admit it. Otherwise the runtime appends the matching
shipped template and validates it before publication. It retains no RNA wrapper
cache across undo, load, or graph changes. Each valid variant is immutable and
can be shared by independent readers. A pending→live→pending transition reuses
the retained pending group, while fake-user protection keeps its identity
available through reader removal and save/load.

An invalid historical helper is retained unused rather than repaired in place,
adopted, or deleted. A new validated group supplies current output. Repeated
external corruption can therefore leave additional unused historical IDs; the
six-variant contract bounds the reusable variants, not every historical ID in
a user file. A failed candidate that has never been published still follows
the ordinary candidate-cleanup path. No settings texture, template variant,
graph emitter, or runtime color equation is added by this lifetime repair.

The source-level reason for this boundary is documented in the testing chapter:
Blender's undo writer records raw ID addresses, its restore path remaps old
addresses before later library linking, and the node-tree preview updater walks
group references recursively. The report links the pinned source ranges and
labels the address-reuse/self-remap path as an inference; only the recursive
stack overflow itself is confirmed by the native crash report.

The native regression repeats reconciliation, sharing and reader removal,
pending→live→pending publication, undo identity checks, save/load, and
acyclic traversal. Policy, runtime, template, GUI undo/drag, packaging, and LTS
animation checks pass, including three concurrent remote LTS undo executions,
the current/LTS six-variant native pool matrices with false-valued legacy-marker
cases, an explicit resource-proof report build, and documentation artifact audits. The
[Blender validation record](testing.md#blender-extension)
keeps these repair receipts separate from earlier pre-repair passing retries.

**Simplification candidate R1.** The `disposal` and `retirement` entry paths
already share the suffix beginning at `observe`. Their two initial phases exist
only to issue the first effect. An initializer returning `(state, effects)` could
remove these entry phases, at the cost of a different runtime runner contract.
Disposal must still fence and detach before observation. Ordinary retirement
begins with observation. Native
user counts remain authoritative for current readers; the independent
`retain_for_undo` observation protects historical fallback references that
those counts do not represent. A Python reader-count ledger would duplicate
current Blender state.

## Gesture observer and participants

`src/features/interaction/policy/gesture.py` supplies scalar decisions to
`src/features/interaction/runtime.py`. The coordinator owns the per-window gesture
collections, target filtering, and native event routing. The policy owns token
allocation, observer handoff, phase checks, deferred completion, participant
release, and undo permission.

### Observer installation

<a id="grade-policy.observer"></a>

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

![Observer handoff policy](../assets/illustrations/grade-policy/07-gesture.svg)

<p class="figure-caption">A stale installation or loss receipt has no authority. The current observer stays usable until the pending native installation succeeds.</p>

### Gesture participation

<a id="grade-policy.gesture"></a>

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

![Gesture participation in the runtime coordinator](../assets/illustrations/grade-policy/07b-gesture-participants.svg)

<p class="figure-caption">The policy checks scalar token and phase facts. The runtime remains responsible for collection order, lookup, target filtering, and native event delivery.</p>

![Observer and gesture workflow](../assets/illustrations/grade-policy/07-gesture-sequence.svg)

<p class="figure-caption">Observer acknowledgement precedes token promotion. Movement activates participants; finishing waits until the native widget has applied its final value. The coordinator releases a node only when its final active participant finishes, with optional auto-keying and adapter-owned undo handled by its effects.</p>

## Render preflight

<a id="grade-policy.render-preflight"></a>

`src/policy/render_preflight.py` protects the render boundary. A ticket records
the requested scene pointer, frame, and exact subframe. The gate binds the
ticket to the matching native render lease and admits only its active ticket
into an exclusive render-preflight scope. The gate uses object identity to
match a publication to that ticket and lease.

The main-thread consumer resolves the requested scene, sets its requested
frame and subframe, reconciles the affected Grade nodes, and waits for their
preparations. It validates the exact Grade signature and current outputs, then
reads the live Blender scene and time again before publishing. Publication
rechecks that this remains the sole native evaluation and that no other host
reader is active. Only a receipt for the active ticket with matching scene,
time, and Grade signature releases the render. Any mismatch or failure
enters `failed` with an error. The consumer attempts to install visible
failure output before delivering the failed ticket. When a render lease
ends, the gate invalidates and wakes any ticket bound to that lease.

The foreground timer services render preflight before collecting compositor
Viewer updates. A Viewer failure is reported separately and retried on a
later tick. It cannot delay release of a validated render or put unrelated
Grades into error.

![Render preflight authorization](../assets/illustrations/grade-policy/08-render-preflight.svg)

<p class="figure-caption">Only the active ticket can publish inside its exclusive scope. Release requires matching scene and time, the exact validated Grade signature, and current output.</p>

![Render preflight workflow](../assets/illustrations/grade-policy/08-render-preflight-sequence.svg)

<p class="figure-caption">The render thread waits while the main thread sets the requested scene time, reconciles Grade kernels, then validates the live scene time, signature, and outputs. Only the active ticket may publish while its render has exclusive access. The failure path attempts to install visible error output before delivering the failed ticket.</p>

`PublicationGate` checks the render lease at admission and builds the
publication event from the main thread's observations inside the active
ticket's scope. A failure event carries its error. The render thread wakes
after the consumer completes any required failure handling and signals delivery.
Render and compositor evaluation leases in `PublicationGate` account for
native jobs from start to matching finish and protect image writes while
those jobs run. Render preflight admits an exclusive main-thread scope for
its own render lease when other activity permits it.

## Live Grade scopes

<a id="grade-policy.vectorscope"></a>

`src/features/vectorscope/` owns the Linear plot, Tone histogram, and Appearance
Distribution. The runtime reads a small, loaded Compositor Image directly when
its buffer preserves the evaluated values. Native captures use an isolated
Compositor tree or Shader AOVs with the active viewport projection. Bake and the
scopes share a native capture helper and submit independent jobs. Each feature
keeps its snapshot files until its job retires.

The scope policy distinguishes structural source identity, capture identity,
and analysis identity. A Linear or Tone edit can reuse matching input samples.
Frame, viewport, and upstream changes can require a fresh capture. Property
and dependency callbacks invalidate the affected readouts immediately. The
timer reconciles the invalidation against the observed demand and schedules
the first ready request in capture queue order.

The renderer reads the policy's display status. A complete Linear or Tone
result from the same source can remain visible as Updating. Appearance
Distribution shows an exact current capture or an explicitly labeled drag
preview with matching input and Grade receipts. A retired request cannot update
a reopened editor. White drag keeps the input receipt and samples captured at
the start of the gesture while its own edits change the analysis.

The Linear analysis plots alpha-weighted Rec.709 Cb/Cr density. The focused
tests cover histogram coordinates, sample filtering, and receipt ordering.
The installed Blender tests exercise the Node Editor display through Linear
edits, source changes, and playback.
[Focused tests](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/tests/runtime/test_vectorscope.py) · [Installed Blender tests](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/tests/installed/test_vectorscope_native.py).

## How the proofs should be read

The policy requirements are executable contracts, not a model of all Blender
behavior. For example:

* `src/requirements/preparation.inv` proves latest-demand replacement and receipt
  correlation; it does not prove executor cancellation.
* `src/features/grade/requirements/color_authoring.inv` proves scalar ownership and capture/clear
  admission. Exact floating-point baselines, cyclic geometry, closest-angle
  projection, and radial Adaptance limiting belong to the runtime tests.
* Runtime Grade preparation tests cover concurrent child startup, delayed
  failure delivery, and cancellation that waits for physical worker retirement.
* `src/features/grade/requirements/node.inv` proves current/full/error presentation decisions;
  runtime checks and host tests must establish kernel structure, image contents,
  and graph ownership.
* `src/requirements/helper.inv` proves job and deadline-stage fencing, escalation,
  exit ordering, and cleanup ownership; transport session/token validation and
  queue ordering remain adapter contracts.
* The bank and resource requirements prove fail-closed sequencing and
  eligibility predicates, including the bank's per-phase closure retry bound
  and save-packing decision. Their consumers perform native operations and
  collect receipts. The resource retention branch proves that an admitted
  `retain_for_undo` observation cannot authorize removal; native undo pointer
  lifetimes, fake-user persistence, and acyclic restored graphs remain host-test
  premises.
* `src/features/interaction/requirements/gesture.inv` proves scalar token, phase, participant, and undo
  decisions. It does not prove the coordinator's collection bookkeeping.
* `src/requirements/render_preflight.inv` proves scene/time correlation, exact
  publication signatures, and fail-closed mismatches. It does not prove
  Blender's live scene observations or exclusive host-scope premises.
* `src/features/vectorscope/requirements/authority.inv` proves scalar
  publication conditions. `scope.inv` proves per-scope freshness and active
  capture admission. The runtime owns editor-keyed storage and FIFO queue
  ordering, establishes capture identity, completes density analysis, and
  applies policy effects.
* `src/features/bake/requirements/bake.inv` proves bounded queue capacity, signature admission,
  current-input checks, stale-result discard, cancellation, publication and
  activation rollback, and the derived live/baked/error output policy.
  `src/features/bake/manager.py` consumes those decisions. `src/features/bake/routes.py` and
  `bake_worker.py` specialize route discovery and Blender evaluation. The shared
  `runtime/capture_snapshot.py` freezes the native scene and its image buffers.

Some named requirements make the review points especially concrete. The
authoring invariant is `owner_is_a_handle_or_absent`; its properties are
`same_owner_retains_baseline`,
`takeover_captures_current_position`, `manual_detaches_only_this_claim`,
`restore_requires_current_owner_and_baseline`,
`baseline_completion_releases_claim`, `clear_removes_claim`,
`absent_claim_has_no_clear_effect`, and `invalid_push_has_no_effect`.
The reachable witness covers push, ownership takeover, rejected old-owner
restoration, and final release. Mutations check that same-owner pushes cannot
recapture the baseline and that an old owner or blocked return cannot release
the claim. These scalar proofs do not establish the numerical optimizer or
the runtime's floating-point `at_baseline` calculation. The
preparation queue properties are `running_request_only_replaces_latest_demand`,
`final_receipt_starts_latest_successor`, and
`obsolete_failure_does_not_publish_error`. The join uses
`any_completion_order_joins_after_all_three` and
`child_error_is_retained_until_last_retirement`. The node uses
`full_quality_is_required_for_current_output`,
`current_failure_clears_applied_output`,
`stale_full_result_updates_drag_preview`, and
`lagging_full_playback_receipt_requires_authorization_at_delivery`. The helper uses
`stale_job_receipt_is_ignored`, `stale_stage_timeout_has_no_effects`,
`cancel_request_retains_active_slot`, and
`cleanup_failure_retains_owner_and_error`. The production bank uses
`repair_requires_successful_closed_receipt`,
`selector_change_requires_clean_staging_receipt`, and
`failed_delivery_restores_original_selector`. Resource deletion uses
`deletion_requires_eviction_and_fresh_eligibility`; gesture behavior uses
`observer_handoff_commits_only_after_ack`,
`last_participant_authorizes_release`, and `native_finish_never_pushes_undo`;
render release requires the active ticket, its requested scene and time, and
the exact Grade signature observed after reconciliation. Failures carry an
error and enter the visible failure path before the render thread is released.
These are the concrete contracts behind the diagrams and prose above.
Bake uses `request_requires_valid_signature`,
`completion_requires_current_signature`,
`publication_requires_current_signature`,
`publication_failure_authorizes_rollback`,
`activation_failure_authorizes_rollback`,
`valid_artifact_remains_baked`,
`source_invalidation_requires_tracked_receipt`,
`toggle_requires_valid_artifact_and_live_kernel`, and
`manual_bypass_selects_live_output`. These properties establish the policy's
authorization boundary; native snapshot correctness and rollback success remain
adapter premises. The `request_runs_and_publishes` and
`failed_request_retires_without_publishing` witnesses exercise successful and
failed request paths. The mutations `skip_current_signature_check`,
`select_live_for_valid_bake`, `allow_invalid_artifact`,
`drop_live_error_guard`, `drop_source_tracking_requirement`, and
`allow_invalid_toggle` check that the corresponding properties detect weakened
contracts. Helper session, job ID, and result-signature validation are runtime
contracts.

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
| Final success for `A` | Retire `A` and start `C`. Outside a gesture and playback, the node keeps `Z` as its preview. |
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
[diagram provenance manifest](../downloads/provenance/grade-policy-diagrams.json).
The links below open the policy implementations, formal requirements, and
runtime consumers.

* Preparation scheduler: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/preparation.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/requirements/preparation.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/preparation.py).
* Color authoring derives its per-handle decision from the stored claim. [Policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/policy/color_authoring.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/requirements/color_authoring.inv) · [composer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/color_authoring.py) · [Blender consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/host.py).
* The Grade preparation runtime joins the three worker results. [Implementation](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/preparation.py) · [runtime tests](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/tests/runtime/test_grade_preparation.py).
* Node output: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/policy/node.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/requirements/node.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/host.py).
* Helper process: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/helper.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/requirements/helper.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/execution.py).
* Production bank publication: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/policy/bank_publication.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/requirements/bank_publication.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/bank_publication.py), called from `features/grade/host.py`.
* Resource lifecycle: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/resources.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/requirements/resources.inv) · [consumers](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/resource_lifecycle.py), [Grade resources](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/resources.py), and [fallback acquisition](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/grade/host.py).
* Gesture coordination: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/interaction/policy/gesture.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/interaction/requirements/gesture.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/interaction/runtime.py).
* Render preflight: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/policy/render_preflight.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/requirements/render_preflight.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/runtime/publication.py), resolved from `features/grade/host.py`.
* Bake requests: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/bake/policy/bake.py) · [requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/bake/requirements/bake.inv) · [manager](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/bake/manager.py) · [routes](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/bake/routes.py) · [worker](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/bake/worker.py) · [wrapper graph](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/bake/graph.py).
* Live scope publication: [policy](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/vectorscope/policy/scope.py) · [publication requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/vectorscope/requirements/authority.inv) · [scope requirements](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/vectorscope/requirements/scope.inv) · [consumer](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/src/features/vectorscope/runtime.py).

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
chapter and its 18 generated SVGs appear only in English. The diagram source
files, D2 archive, renderer adapter, and figure manifest are declared Buck2
inputs, so the first command is reproducible without a system D2 installation.

Build and run the product policy evidence with Buck2's remote execution:

```sh
buck2 build //products/perceptual-grade-next-blender:verify_policies --remote-only
buck2 build //products/perceptual-grade-next-blender:proof_bake --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_verification --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_preparation \
  //products/perceptual-grade-next-blender/tests:policy_node \
  //products/perceptual-grade-next-blender/tests:policy_helper \
  //products/perceptual-grade-next-blender/tests:policy_resources \
  //products/perceptual-grade-next-blender/tests:policy_bank_publication \
  //products/perceptual-grade-next-blender/tests:policy_gesture \
  //products/perceptual-grade-next-blender/tests:policy_render_preflight --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_bake \
  //products/perceptual-grade-next-blender/tests:bake_manager_runtime \
  //products/perceptual-grade-next-blender/tests:runtime_bake_routes \
  //products/perceptual-grade-next-blender/tests:bake_installed --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:vectorscope \
  //products/perceptual-grade-next-blender/tests:vectorscope_native --remote-only
```

These checks are deliberately scoped to `products/perceptual-grade-next-blender`.
They complement runtime and installed-host tests; passing the `.inv` proofs
alone is not evidence that a native image write, process operation, or gesture
observer succeeded.

