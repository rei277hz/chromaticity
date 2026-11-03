# Grade Policies

The product-owned `policy` package contains shared Grade preparation scheduling
and per-node output decisions, including ordered Stack membership. These
host-free policies use the Invariant verifier; proof evidence remains a build
artifact and is not included in the runtime package.

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

Build and test through remote execution:

```sh
buck2 build //products/perceptual-grade-next-blender:verify_policies --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_preparation --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_node --remote-only
```
