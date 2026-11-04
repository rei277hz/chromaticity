# Perceptual Grade core

`color_tools.perceptual_grade_core` owns host-independent grading math, immutable
scope/job records, Python scheduling/publication policies, message catalogs and
the shared portable kernels used by the reference model. The package depends
only on `color_core`, the host-free Invariant runtime, NumPy and the Python standard
library. It does not import Blender, execution services, native arenas or any
product package.

This is the preserved core used by the existing Blender, DCTL and reference
consumers. The rebuilt Blender product owns separate state-machine policies in
its `policy` package; preserved proof receipts do not certify those policies.

`//libraries/perceptual-grade-core:model_code` supplies the source package;
`:runtime` adds generated numerical and locale resources. Buck's component
providers retain each source's single owner and bundle the intact package.
The generated DCTL reads these data/resources through ordinary Python imports.
Host-free message catalogs serve DCTL and Blender; locale selection belongs to
the host adapter. See [component packaging](../../build_defs/README.md) for the
development namespace and private installed package layout.

`model/` owns Grade controls and transform pipelines; shared generic linear
color math, signed Grade modCAM16/HK equations, and extended-range arithmetic
live in `color_core`. The independent reference lives in its own library and
explicitly supplies its own encoder/response semantics where a shared
algorithm needs them. Core tests are under `tests/`. Lean color-model theorems
belong to the [reference library](../perceptual-grade-reference/proofs/README.md)
and are checked by `//libraries/perceptual-grade-reference/proofs:color_model`.
Core scheduling and publication policy proofs remain under `proofs/`.
Grade retains source-white admissibility/projection. Relocating shared appearance
records does not change scope transport tags, fields or version.

## Policies and workflow requirements

The six modules in `src/perceptual_grade_core/graph/policies/` directly implement
channel, lifecycle, exact-operation, scope-display, output-authority and baked
Image revision behavior.
They are checked-in Python with immutable records and pure transitions/queries.
The `scheduler_policy` and `output_policy` facades retain public schemas,
constants and input normalization. Product Sessions use typed App-owned Stores
for every state transition.

The [leaf inventory](requirements/inventory.bzl) names the required `.inv` claims.
The [workflow inventory](requirements/coordinators/inventory.bzl) covers bake
admission and queues, publication/repair, exact output, scope capture/analysis,
scope demand, native scope-input authority and recovery. Shared source
interpretation generates Z3 obligations for initialization, admitted transition
preservation, function contracts and named properties. Generated modules supply runtime contracts;
handwritten Python remains the implementation authority.

Cyclic selection normalizes any integer cursor over the actual sequence length,
scans one rotation, and returns `-1` for empty or all-ineligible input. These scans
and final-resolution collection checks live in the `scheduler_policy` runtime
facade and are covered by ordinary tests, outside the channel proof.

The `bake_queue` coordinator keeps its public eight-reservation state and computes
occupancy and destination-order observations with ordinary collection operations.
Every transition calls `bake_queue_policy`, whose scalar proof covers admission,
one selected reservation's physical lease, receipt identity, closing, and
publication permission. Queue-wide uniqueness, scans, and updates are trusted
adapter behavior tested in Python; the proof manifest identifies the scalar
policy source rather than claiming to certify that bookkeeping.

The `bake_image` policy governs decoded Image cache reconciliation through finite
phases and booleans with an integer observation generation. Its
[requirements](requirements/bake_image.inv) and leaf inventory declare the
properties, positive witnesses and source mutations requiring concrete Python
replay. A changed known managed publication can authorize invalidation of a
clean decoded buffer backed by packed data. Only the current operation's
completion receipt settles invalidation; dirty, unknown or unpacked output is
preserved. Neither preservation nor invalidation certifies numerical contents.
Failed invalidation retains debt, and newer observation generations fence old
receipts. The correspondence regression compares the source interpreter with
Python across every finite-field combination at zero/current/new observation
generations; the inductive requirements cover unbounded generations separately.

Native adapters must report observations truthfully and fence receipts by
App/Store ownership, Image identity, scalar publication operation identity and
observation generation. The preserved product's recovery adapter checks these
before and after native cache invalidation without reading pixels or hashing
packed data. Its separate recovery coordinator tracks physical retirement,
finite owner adoption and activation; adoption does not certify output.
Protocol proofs do not establish Blender semantics or eventual recovery.

## Build and verification

Run from the repository root:

```sh
buck2 build //libraries/perceptual-grade-core/proofs:verify
buck2 test //tools/verification/tests:bake_correspondence
buck2 build //:verify
```

The root verification target includes these proofs and the separate Lean
color-model mathematics. Grade packaging checks exact policy, requirements,
checker, solver and report identities. Z3 and proof artifacts are
not installed. Historical machine DSL, Z3/Rocq proofs and code generators remain
in the external `perceptual-grade-proof-archive` directory; they do not certify
this implementation. The historical sections in
[GOAL.md](../../products/perceptual-grade-next-blender/GOAL.md) record accepted validation evidence.
