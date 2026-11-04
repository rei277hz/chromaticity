# Grade Policies

The product-owned `policy` package owns Grade preparation scheduling, per-node
output decisions, helper lifecycle, generated-resource retirement, image
publication, and gesture coordination. These host-free policies use the Invariant
verifier. Packaging requires source-bound evidence for every policy module;
proof evidence remains a build artifact outside the runtime package.

Preparation stores only optional desired and running signatures. While one
snapshot prepares, each request replaces the newest demand. Completion retires
the active work and immediately authorizes the latest successor. A successful
superseded result can become a pending preview; an obsolete failure does not
invalidate the newest demand. Absence is `None`, never an empty signature.

Per-node policy stores ordered Stack Grade IDs, desired and last-applied kernel
signatures, the current preparation correlation signature, applied quality,
gesture state, and an optional current error. It decides whether settings need
preparation, whether Stack changes require reconciliation, whether an async
receipt may authorize a kernel build, and derives current, preview, pending, or
error presentation. Blender translates host and runtime receipts into policy
events and applies only effects the reducer returns. A last-good kernel remains
visible as an updating preview until replacement;
when none exists, pending policy allows an identity placeholder. Only an exact
full-quality current installation is ready for rendering. A current failure
selects magenta output until a new request. Reducer effects alone authorize
preparation, reconciliation, result delivery, graph installation, and
presentation.

Helper policy owns startup/probe admission, transport polling, shutdown
escalation, and cleanup receipts. Cancelling the startup probe withdraws startup;
a late successful probe cannot grant readiness. Physical process exit settles
job outcomes before fallible cleanup, so cleanup failure cannot hide the worker
error. An incompletely cleaned helper remains owned until an explicit close
retry succeeds. Queue ordering, payload transfer, and joins retain their existing
adapter contracts and are not certified by this process-lifecycle proof.

Resource policy decides adoption from native observations and sequences disposal
through subscription fencing, detachment, cache eviction, and fresh eligibility
checks. Native deletion requires zero users and successful cache invalidation.
An invalid wrapper can authorize eviction, never another native deletion. Native
counts and host identities remain observations rather than a duplicate Python
ownership ledger.

Image publication is a synchronous transaction inside the existing publication
gate. Snapshot, upload, packing/verification, metadata commitment, and completion
are separate authorized effects. Upload, packing, or metadata failure restores
the snapshot where possible and fails closed for every current source user,
including users outside the initiating receipt. Rollback does not make stale
output current. The delivery consumer invalidates Blender's cached image result
after metadata commits and before reporting successful installation. Invalidation
failure follows the same source-wide failure path; the policy's failed-delivery
contract covers this receipt. Graph-link replacement and publication-gate
admission retain their separate adapter contracts.

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
list filtering, lookup, order preservation, or iteration. Stack Grade ordering
remains an input to the node policy's rebuild decision because it affects the
rendered result.

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
buck2 test //products/perceptual-grade-next-blender/tests:policy_helper //products/perceptual-grade-next-blender/tests:policy_resources //products/perceptual-grade-next-blender/tests:policy_image_publication //products/perceptual-grade-next-blender/tests:policy_gesture --remote-only
```

CI checks this product on pushes, pull requests, and manual runs. Its selection
includes policy proofs, the extension package, and unit, runtime, numerical, GPU,
installed-Blender, and native UI acceptance tests. Tests and proofs from
`libraries/perceptual-grade-core` and `products/perceptual-grade-blender` are
excluded; shared source dependencies may still build as prerequisites.

The product's verifier regressions exercise assumption-guided expansion using
the helper policy and focused safety cases. They check that unreachable branches
are pruned while reachable errors, contradictory premises, and unsafe
assumptions still fail. Structural checks avoid machine-dependent timing limits.
