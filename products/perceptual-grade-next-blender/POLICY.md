# Grade Policies

The product-owned `policy` package owns Grade preparation scheduling, per-node
output decisions, helper lifecycle, generated-resource retirement, parameter
bank publication, bake scheduling, and gesture coordination. These host-free
policies use the Invariant verifier. Packaging requires source-bound evidence
for every policy module. Proof evidence remains a separate build artifact.

Preparation stores only optional desired and running signatures. While one
snapshot prepares, each request replaces the newest demand. Completion retires
the active work and immediately authorizes the latest successor. A successful
superseded result can become a pending preview; an obsolete failure does not
invalidate the newest demand. Absence is `None`, never an empty signature.

Per-node policy stores desired and last-applied kernel signatures, the current
preparation correlation signature, applied quality, gesture state, and an
optional current error. The runtime retains ordered Stack Grade IDs and sends
scalar observations for stack changes and referenced Grade edits. The policy
decides whether settings need preparation, whether those observations authorize
reconciliation, whether an async receipt may authorize a kernel build, and
derives current, preview, pending, or error presentation. Blender translates
host and runtime receipts into policy events and applies only effects the
reducer returns. A last-good kernel remains visible as an updating preview until
replacement;
when none exists, pending policy allows an identity placeholder. Only an exact
full-quality current installation is ready for rendering. A current failure
selects magenta output until a new request. Reducer effects alone authorize
preparation, reconciliation, result delivery, graph installation, and
presentation.

Native template instantiation is part of those existing graph-installation and
bank-staging effects. The consumer appends a schema-checked bundled tree, binds
the authoritative parameter banks or Stack LUT, and reports installation only
after the complete result is valid. The loader has no independent scheduling or
publication authority and introduces no policy machine. Missing, corrupt, or
incompatible assets return through the current failure receipt; they never
silently retain stale output or fall back to a runtime graph emitter.

Helper policy owns startup/probe admission, transport polling, shutdown
escalation, and cleanup receipts. Cancelling the startup probe withdraws startup;
a late successful probe cannot grant readiness. Successful probe completion
publishes its result and enters `ready` with the work slot idle. Ordinary work
is submitted afterward. Physical process exit settles job outcomes before
fallible cleanup, so cleanup failure cannot hide the worker
error. An incompletely cleaned helper remains owned until an explicit close
retry succeeds. Queue ordering, payload transfer, and joins retain their existing
adapter contracts and are not certified by this process-lifecycle proof.
Protocol version 2 and the session field are shared by the host and worker.
Every frame carries the helper owner's session UUID; the initial worker hello
also carries the protocol version and a random token checked by the host. Work
receipts carry a numeric job ID. The reducer correlates those IDs with its
separate startup probe and active-work identities, while timeout receipts must
match the current deadline stage. Helper effects are named scalar
authorizations. The runtime translates them into the established command order,
which runtime tests cover.

Resource policy decides adoption from native observations and sequences disposal
through subscription fencing, detachment, cache eviction, and fresh eligibility
checks. Native deletion requires zero users and successful cache invalidation.
An invalid wrapper can authorize eviction, never another native deletion. Native
counts and host identities remain observations rather than a duplicate Python
ownership ledger.

File load, undo, and redo fence ordinary Grade work before Blender replaces
data. The lifecycle coordinator reopens admission after it releases retained
resources and reconciles the output registry and node presentation. A
temporary publication conflict schedules another attempt. An unexpected
failure authorizes visible error output and leaves recovery pending. A render
preflight admitted by an active render lease can reconcile its scene and
frame while the global fence is pending. A render may use banks verified
against its settings. It reports an error if recovery needs to update banks
also attached to nodes outside the preflight. The preflight's permission
expires when it ends or a newer lifecycle begins.

Parameter publication stages and packs the inactive bank before selecting it.
A damaged active bank requires a confirmed error output before repair. Delivery
requires a successful selector readback. A selection or delivery failure attempts
selector restoration, checks the Blender readback, and fails closed for the
source's current users. During file save, the bank policy authorizes packing
dirty generated parameter images. The save handler verifies that Blender
reports a packed file and a clean image before
accepting a successful pack.

Bake policy bounds accepted requests and authorizes enqueue, helper start,
cancellation, publication, activation, rollback, and retirement. The accepted
request signature remains in policy state, while later policy events are scoped
to that request by the manager. The execution runtime correlates receipts by
session and job ID. The manager validates the result signature before reporting
completion. Each request writes `bake.exr` in a unique artifact directory.
Publication and activation recheck the current source signature and freshness
observations, including dependency generations. A deferred publication retains
its finished artifact until admission is available, while an edit
discards it. The runtime serializes helper work and keeps snapshot files alive
until physical cancellation completes. Publication, activation, and rollback
share one gate admission. Runtime and installed tests cover the host
transactions and native pixel evaluation. The proof covers the policy's scalar
authorizations.

Use Bake selects the bound managed Image while it is valid and the live Grade
has no error. Each node keeps its own input receipt when returning to live
output or when inputs change. A mismatch displays a warning and leaves the
selection in effect. Returning to the recorded engine and inputs clears the
mismatch. A tracked source update persists on the receipt until a successful
rebake or explicit Image binding establishes a new baseline. Rebaking a shared
managed Image updates the pixels for all its readers. Each reader compares
its own live inputs against its own receipt.

Gesture policy decides observer admission, handoff, participation, deferred
completion, and undo permission. Its runtime coordinator stores the per-window
registries and supplies observations to those decisions. A pending observer replaces
the current observer only after native installation succeeds. Activity is derived
from participating gestures; only the final participant releases a node. Native
gestures never authorize manual undo checkpoints. Reset preserves monotonically
allocated identities while invalidating previous observers and callbacks.

Collection bookkeeping is trusted runtime code, covered by ordinary tests.
Gesture proofs check scalar decisions using observations from that code: current
tokens, participation, deferred completion, and undo permission. They do not prove
list filtering, lookup, order preservation, or iteration. Stack order and
membership are likewise observed by the runtime; node policy proves how its
scalar rebuild authorizations are handled.

Effect consumers retain native handles and exception details, execute authorized
effects, and return observations. Native hit testing, event delivery, resource
validity, clean packing, GPU behavior, and thread affinity still require adapter
and installed-Blender tests. These proofs do not establish those host premises
or replace the real widget, save-dialog, and populated-Stack acceptance tests.

Build and test through remote execution:

```sh
buck2 build //products/perceptual-grade-next-blender:verify_policies --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_verification --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_preparation --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_node --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_helper //products/perceptual-grade-next-blender/tests:policy_resources //products/perceptual-grade-next-blender/tests:policy_bank_publication //products/perceptual-grade-next-blender/tests:policy_gesture --remote-only
```

CI checks this product automatically on pushes and pull requests. Its selection
includes policy proofs, the extension package, and unit, runtime, numerical, GPU,
installed-Blender, and native UI acceptance tests. Tests and proofs from
`libraries/perceptual-grade-core` and `products/perceptual-grade-blender` are
excluded; shared source dependencies may still build as prerequisites.

The product's verifier regressions exercise assumption-guided expansion using
the helper policy and focused safety cases. They check that unreachable branches
are pruned while reachable errors, contradictory premises, and unsafe
assumptions still fail. Structural checks avoid machine-dependent timing limits.
