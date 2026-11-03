# Grade Policies

The product-owned `policy` package contains the ordered Grade Stack policy,
shared Grade preparation scheduling, and per-node kernel readiness. These
host-free policies use the Invariant verifier; proof evidence remains a build
artifact and is not included in the runtime package.

Preparation stores only optional desired and running signatures. While one
snapshot prepares, each request replaces the newest demand. Completion retires
the active work and immediately authorizes the latest successor. A successful
superseded result can become a pending preview; an obsolete failure does not
invalidate the newest demand. Absence is `None`, never an empty signature.

Node readiness stores desired and last-applied kernel signatures and an optional
current error. It derives current, preview, pending, or error presentation. A
last-good kernel remains visible as an updating preview until replacement; when
none exists, pending policy allows an identity placeholder. Only an exact current
installation is ready for rendering. A current failure selects magenta output
until a new request. Reducer effects alone authorize preparation, result delivery,
graph installation, and presentation.

Build and test through remote execution:

```sh
buck2 build //products/perceptual-grade-next-blender:verify_policies --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_preparation --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_readiness --remote-only
buck2 test //products/perceptual-grade-next-blender/tests:policy_stack --remote-only
```
