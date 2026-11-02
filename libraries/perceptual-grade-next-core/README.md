# Perceptual Grade Core

This host-free library contains the ordered Grade Stack policy, shared Grade
preparation scheduling, and per-node kernel readiness. All policies use the
Invariant verifier; generated proof evidence remains a build artifact and is not
included in the runtime package.

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
buck2 build //libraries/perceptual-grade-next-core:verify --remote-only
buck2 test //libraries/perceptual-grade-next-core/tests: --remote-only
```
