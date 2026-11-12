# Next Blender policy machines

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

Read an edge as **event or receipt / requested effect**. A box containing
`a -> b -> c` compresses successive states to keep the print figure legible;
each operation still produces its own receipt. A slash between phase names
groups alternatives with the same outgoing decisions. These are drawings of
the current implementation, not proposed atomic operations or merged phases.
The prose describes conditional entry points and less common transitions.
Callout codes such as **B1** refer to the simplification discussion beside
that figure.

## Preparation: latest demand, one worker

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

`src/policy/preparation_join.py` is the aggregate barrier used by
`src/runtime/grade_preparation.py`. `new(signature)` marks `linear`, `tone`, and
`boundary` pending. Each matching component receipt clears one bit. The final
distinct receipt returns `completion_signature`; the first error is retained and
returned only at that final point. Stale and duplicate receipts do nothing.

![The three-component preparation join](../assets/illustrations/next-policy/01b-preparation-join.svg)

<p class="figure-caption">All three physical children retire before aggregate completion, including after an error. The runtime already wraps the receives in a shielded `asyncio.gather`; that is a scheduling fence in addition to this reducer's decision.</p>

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

Failure or timeout moves a live process toward termination. A channel shutdown
uses `stopping`; a process without that transport uses `terminating`. Terminate
and kill timeouts lead to `unretired`, which keeps ownership visible rather than
pretending cleanup succeeded. After physical exit, the policy publishes job and
probe outcomes, queues cancellation or failure, and enters `retiring`. Cleanup
may be retried; only a successful cleanup receipt reaches `closed` or `failed`.

| Observation | Decision that the compact figure abbreviates |
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

`src/policy/bank_publication.py` is the active production publication path. The
parameter-image code in `nodes.py` constructs two packed image banks, while
`runtime/bank_publication.py` consumes the reducer's effects. The inactive bank
is staged and checked before the selector changes. Selection is read back, then
delivery publishes the resource and dispatches installation results to all
affected node records.

![Production two-bank publication](../assets/illustrations/next-policy/04-bank-publication.svg)

<p class="figure-caption">An invalid active bank first closes output, then repairs both banks. A selection or delivery failure restores the old selector before failing closed.</p>

The admission facts require two distinct valid bank indices and an admitted
publication context. If the active bank is invalid, `repair_gate` first waits
for confirmed failure-output closure. Only then may `repair_stage` repair both
banks. A failed stage or unclean pack fails closed. A wrong selector readback or
delivery receipt enters `restore_selector`; the old bank and graph bindings are
restored before the final failure output is attempted. The runtime bounds failed
closure retries and reports `indeterminate` if it cannot establish a reliable
output.

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
two-bank transaction above and the save-packing helpers described below.

### Immutable parameter-image transaction

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

### Shared-image transaction

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

![Shared-image publication and restoration](../assets/illustrations/next-policy/05b-image-publication.svg)

<p class="figure-caption">The shared-image strategy can skip upload and packing when the captured image is already matching and clean. Its rollback still cannot make stale output current.</p>

### Compositor supersession

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

## Resource adoption and retirement

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

The observer state has `current_token` and `pending_token`, plus a monotonically
allocated serial. The first window observation invokes an installation. During a
replacement, the current observer remains admitted while the new token is
pending. Only an installation receipt for that pending token can promote it;
failure leaves the current observer. A lost current observer may leave a
pending replacement alive. Reset invalidates callbacks but preserves the serial.
The compact pending box covers both first installation and replacement; losing
`A` while `B` is pending leaves that box with `current=None`. Reset always clears
both tokens, including from pending. Native input must match the current token;
an explicit adapter event with token `None` remains allowed. Handoff also checks
the captured gesture token and its armed/active phase. After installation, the
coordinator replays the latest move/finish or requests handoff for a newer gesture.

![Observer handoff policy](../assets/illustrations/next-policy/07-gesture.svg)

<p class="figure-caption">A stale installation or loss receipt has no authority. The current observer stays usable until the pending native installation succeeds.</p>

### Gesture participation

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

## Render preflight

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
directory. The generated figure hashes and renderer pin are recorded in the
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

Regenerate the diagram assets and both English reading formats from the
repository root with the declared Buck2 targets:

```sh
buck2 build --remote-only //products/perceptual-grade-book/diagrams:assets
buck2 build --remote-only \
  '//products/perceptual-grade-book:site[html]' \
  '//products/perceptual-grade-book:book[pdf]' \
  '//products/perceptual-grade-book:book[epub]'
```

The site target includes the English and Simplified Chinese editions; the policy
chapter and its 13 generated SVGs appear only in English. The diagram source
files, D2 archive, renderer adapter, and figure manifest are declared Buck2
inputs, so the first command is reproducible without a system D2 installation.

Build and run the product policy evidence with Buck2's remote execution:

```sh
buck2 build //products/perceptual-grade-next-blender:verify_policies --remote-only
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
