# Centralized Grade work scheduling

## Goal

Coordinate Grade kernel preparation and publication, plot previews and exact
capture, Bake work, lifecycle recovery, and render preflight through one host-thread
scheduler. Shared Grades can invalidate many consumers at once, so work
selection must keep interactive plots responsive without weakening output
freshness, graph safety, or recovery guarantees.

The scheduler owns task admission, ordering, coalescing, cooperative yielding,
and retry timing. A feature remains the authority for its task's inputs,
current signature, publication checks, and failure behavior. A scheduler
choice alone never authorizes a feature result to become visible.

## Design choices

| Decision area | Selected design | Reason and tradeoff |
| --- | --- | --- |
| Durable state | Save authored Grade settings, committed derived buffers, and existing Bake receipts. Rebuild task demand from the saved project after load. | Queues and worker handles refer to Blender IDs and artifacts from the running session. Reconstructing demand avoids resuming work against invalid IDs or incomplete artifacts. |
| Scheduler ownership | Centralize host-thread admission, priority, coalescing, safe yielding, and retry timing. Keep input validation, signatures, worker internals, publication, and rollback in their owning features. | This coordinates competing work without making the scheduler a second authority for Grade or Bake correctness. Existing worker lanes still own asynchronous preparation and native capture execution. |
| Task identity | Coalesce replaceable work by its owner and current demand. A newer plot request replaces the old request for that plot and editor. | Repeated edits should not create an unbounded queue of obsolete intermediate states. |
| Priority order | Exact scene/frame render preflight first, lifecycle recovery second, eligible plots third, ordinary consistency work fourth, and user-requested Bake last. | Render preflight protects the requested render. Recovery protects project coherence. Plots are interactive. Manual Bake can wait. |
| Plot priority | Give eligible plots strict priority over unrelated consistency and Bake work, with the foreground Node Editor first and newest demand first within an editor. | A plot should react to the latest user edit instead of waiting behind background work. Continuous plot demand can starve lower-priority work, which is accepted for responsiveness. |
| Plot dependencies | Promote only the Grade Stack and upstream Grade preparations needed by the next eligible plot. | This makes a plot's prerequisites ready promptly without turning one interactive request into a global priority boost. |
| Progressive Stack preparation | Promote a Stack only until a validated preview for its current settings is published. Keep its task queued for full-quality refinement, and keep exact plot capture blocked on that task until full publication completes. | This lets other Stack consumers prepare current previews while one helper job waits on refinement. Cancellation occurs only at helper-supported checkpoints. |
| Shared preparation lane turns | At a safe phase boundary, let equal-priority Stack preparation tasks sharing the LUT lane take turns. A strictly higher-priority plot or exact render may still preempt lower-priority work. | Shared Grades can have multiple Stack consumers. Fair turns keep one consumer from holding the lane while another current preview is waiting. |
| Appearance Distribution preview | Give the bounded GPU preview plot priority when current input samples and validated Grade parameter images are available. Keep an exact evaluated capture queued for settled controls. | Grade edits can refresh the diagram without recapturing its input. Exact capture remains authoritative for the evaluated graph. |
| Plot freshness | Publish a plot only when its captured request generation and all required Grade signatures remain current. Keep the last completed appearance trace visible while replacement samples are prepared. Show an updating status for source or frame recapture, not for every Grade edit. | Retaining context avoids a blank diagram. Status distinguishes an exact trace, a preview for current controls, and a retained trace. |
| Cooperative preemption | Yield at worker phase boundaries and between atomic Blender operations. Keep completed phases in memory when the request is still current. Never interrupt a Blender operation in progress. | This permits safe responsiveness while respecting host API boundaries. A long atomic operation can still delay higher-priority work until Blender returns control. |
| Bake capture | Keep native capture serialized on its existing helper lane. Defer request snapshot creation until its Grade prerequisites are current. If a plot preempts capture, request cooperative cancellation, wait for helper retirement, then restart a still-current Bake from its immutable snapshot. | Native Blender Bake does not expose resumable phase artifacts. Deferring snapshots avoids capturing stale Grades. Restarting avoids publishing partial work, at the cost of repeating capture after preemption. |
| Grade preparation | Prepare one current Grade signature at a time, with its existing bounded parallel lanes for Linear, Tone, Color, and boundary components. Retire obsolete signatures before publication. | This bounds resource use while retaining parallelism among independent components of one Grade preparation. |
| Publication authority | Recheck exact signatures or generations and current project lifecycle immediately before installing any result. A feature's validated publication path remains authoritative. | Work can become stale while queued, executing, or waiting for host admission. Freshness checks at installation close those races. |
| Error handling | Track errors per owner, fail affected Grade outputs closed with magenta while preserving alpha, and retry consistency work with bounded backoff. Exact render preflight may repair only its requested scene and frame during broader recovery. | A local failure should remain visible and recoverable without claiming stale output is current or allowing unrelated work to take ownership. |
| Lifecycle recovery | On file load or undo, withdraw prior-project queues, captures, previews, and unfinished manual Bake launches. Repair Grade kernels first, reconcile Bake outputs after Grade preparation completes, then admit plots. | A saved Bake can be disabled permanently if its output is reconciled while a valid Grade is temporarily showing a repair error. In-memory pointers and captures also belong to the previous project lifecycle. |
| Extension startup | Schedule initial inventory after Blender exposes project data. During the startup phase admit Grade consistency and exact render work, but fence plots and manual Bake until all inventoried Grade kernels and Bake receipts reconcile. | Blender restricts project data access during registration. The separate startup phase permits consistency work needed to become ready without exposing plots or Bake to partially recovered data. |
| Pending indicators | Derive pending, current, and error status from owner state and scheduler demand. | Persisted pending flags can contradict committed data after interruption. Deriving status keeps recovery based on authoritative settings and receipts. |
| Exact render exception | During pending lifecycle recovery, admit exact preflight for the requested scene and frame. Dispatch a main-thread render callback synchronously through that exact task. | Blender cannot run a timer while a main-thread render callback is active. The exact request can establish its own consistency without admitting unrelated plot or background work. |

## Priority and dependency contract

1. Exact render preflight for its requested scene and frame.
2. Grade kernel repair followed by durable Bake reconciliation on file load or undo.
3. Eligible previews, exact plots, and their promoted prerequisites, with the
   foreground Node Editor first and newest demand first.
4. Other Grade and Grade Stack consistency work.
5. User-requested Bake work.

Lifecycle recovery is a fence for plot admission. Exact render preflight is
scoped to its requested scene and frame and may proceed while that fence is
pending. Plot tasks promote the transitive producer tasks they actually need,
then publish only after the exact captured signatures still match. A Stack
preview can stop receiving promotion once its current signature is installed,
but its task remains a prerequisite until its full-quality result is installed.

## Save and recovery contract

Saving may occur while work is queued, paused, or running. Save the authored
settings and already committed derived data. Do not serialize executor queues,
task identifiers, helper handles, plot captures, or additional pending flags.
Before serialization, persist any durable Bake source invalidation provenance
that is already known.

After load or undo, reconstruct demand from the project contents. Validate
saved Grade kernel signatures and Bake source provenance. Adopt matching
results and rebuild missing, stale, or damaged results. Derive each owner's
pending, current, and error status from this reconciliation. Discard
unfinished manual Bake launches and transient plot work. Admit new plot work
after Grade and Bake consistency recovery completes, while preserving scoped
exact render preflight.

### Example: saving halfway through a shared Grade edit

Suppose two Grade Stacks reference an edited Grade. The open Node Editor
displays a plot that depends on the first Stack. The plot and its required
preparation take priority. The second Stack may still contain its last
published LUT when the user saves. The file records the new Grade settings
alongside each Stack's committed data.

| What was in progress at save | How reopening decides what to do |
| --- | --- |
| The first Stack published its full result. | Recompute its expected signature from the saved settings and validate its kernel. Adopt it when both checks pass. |
| The second Stack has an older LUT, or only a preview of the new Grade. | Compare its saved signature and quality with current full-quality demand. Prepare and publish the missing full result. |
| A plot had shown a preview or had an exact capture pending. | Discard the session's plot state. When recovery finishes, an open editor can request samples for the reopened scene and frame. |
| A manual Bake had started. | Discard the unfinished launch. Reconcile any previously committed Bake using its saved receipt, source provenance, and Grade signature. |

If a render starts during recovery, its preflight checks the Grades needed
for that scene and frame. A successful check admits that render. If repair
fails, the affected output shows the error and renders magenta with its
original alpha; recovery retries automatically.

## Acceptance criteria

- A single edit to a shared Grade cannot enqueue unbounded obsolete work.
- Current foreground plots run ahead of unrelated Grade consistency and manual
  Bake work, with only their required Grade prerequisites promoted.
- A result whose generation, source signature, or lifecycle no longer matches
  cannot be published.
- Saving during active work produces a project that reopens coherently without
  restoring process-local queues or treating interrupted work as committed.
- Load and undo rebuild invalid derived results and adopt valid committed ones.
- Bake source invalidations survive save/load even when a reconciliation task
  had not yet run.
- Exact scene/frame render preflight can establish readiness during recovery
  without admitting unrelated plot requests.
- Affected Grade outputs visibly fail closed and retain alpha when consistency
  work fails. Retry behavior is bounded and owner-specific.
