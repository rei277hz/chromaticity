# Perceptual Grade Next core

Last updated: 2026-11-01

**Status: the portable core is implemented.** The unbounded readiness kernel
proof passes 170 obligations and 4 mutation checks in build
`e458d854-a0f2-474f-9ee4-e903e6da13b7`. That receipt proves the kernel model,
not production record conversion or complete native acceptance. Production
correspondence and full acceptance remain pending. This directory contains the independent runtime package, numerical
Grade/Stack modules, immutable settings, a Stack LUT builder,
readiness/preflight policies and tests. The canonical
[state-machine design](../../products/perceptual-grade-next-blender/STATE_MACHINE_DESIGN.md),
product [GOAL.md](../../products/perceptual-grade-next-blender/GOAL.md) and [CHECKLIST.md](../../products/perceptual-grade-next-blender/CHECKLIST.md) define and track
the new implementation.

The library provides the independent `perceptual_grade_next_core` package for
[`perceptual-grade-next-blender`](../../products/perceptual-grade-next-blender/README.md).
It owns host-independent grading mathematics, immutable descriptions, identities
and checked scope/project workflow policies. Blender RNA, UI, native capture and
publication adapters belong to the product. The
[product architecture](../../products/perceptual-grade-next-blender/ARCHITECTURE.md)
describes composition with foreground authority and the Restart supervisor.
The [current handoff](../../products/perceptual-grade-next-blender/CHECKLIST.md#current-audit-handoff-2026-11-01)
records the proof boundary, validation receipts, retained-ledger readiness gaps
and the documentation-only stopping point.

The selected next milestone is
[recoverable Grade/Stack preparation and trustworthy admission](../../products/perceptual-grade-next-blender/READINESS_RECOVERY_STEP.md).
The kernel proof now establishes an inductive readiness decision for every
finite owner count. The remaining proof work is to check production record
conversion and correspondence to actual owner discovery and admission. Independent
revision/evaluator/repair assertions now pass in the kernel. The product must also close the
snapshot, recovery-debt and cleanup defects recorded in the checklist. These
acceptance requirements remain open; the proof does not claim full Scope/Restart/
native composition.

The new pair does not depend on the runtime packages of `perceptual-grade-core`
or `perceptual-grade-blender`; those implementations remain preserved. Reuse the
generic Invariant and color libraries through explicit dependencies, with
generic Blender execution/ownership services composed by the product. Preserve
the numerical contract in Next, and do not retain old workflow authorities
behind its policies.

Grade/Stack parameters and transform preparation are static in this version.
Dynamic source observations and frame-driven scope demand remain part of the
workflow. There is no Grade animation, per-frame texture bank, auto-keying or
separate Exact LUT machine family in the new implementation. Static readiness
still requires matching computation, packing, binding and publication receipts.

The reference numerical contract separates forward-only native Grade from
ordered Stack LUT execution. Stack entries may run FORWARD or INVERSE and retain
the current reference's 35/75 `abs(J_A)` low/high crossover, raw handoffs,
endpoint matrices and finite inverse-search residuals. Next runtime follows this
contract; the old accelerated capacity-based `.4*U` crossover and its
restrictions are not the authority for the new product. The authored UI/model
contract uses the supported fixed D65 / 203-nit viewing context, Tone Fit
`[-2, 2]` and Color lightness/chroma Fits `[-2, 6]`.

Eight independent `.inv` targets have historical receipts for preflight, scope,
foreground, project receipt predicates, preparation/recovery policy, Restart and
reduced composition. The new `project_unbounded_proof` is wired into runtime and
verification and passes the kernel receipt above. Its proof boundary stops
before production `project.py` owner/evaluator/artifact conversion and native
adapter admission. `scope_view.inv` contains five proposed properties but has
no Buck proof target and lacks the required nonempty `invariants` mapping. The
canonical inventory has 60 IDs: 43 partial, 11 adapter premises and 6 open.
Production adapters use several previously checked helpers, but a reference to
those helpers does not prove the current full workflow. No fresh aggregate
receipt has been recorded after this audit.
The [coverage inventory](PROOF_COVERAGE.md) records the canonical families,
partial projections and absent native claims. Preparation/recovery policy and
the composed model remain smaller specification models; the production owner
worklist is not proved by the reduced project receipt kernel. Cross-family
grant transport and native effects retain explicit external premises.
Old proof inventories and acceptance results are historical evidence, not proof
of the new composition. No broad shared-runtime rewrite or compatibility
migration is part of this implementation.

## Temporary runtime without the unbounded project proof

Run from the repository root:

```sh
buck2 build //libraries/perceptual-grade-next-core:unsafe_runtime --show-output
```

`unsafe_runtime` uses the same handwritten sources, package namespace and
dependencies as `runtime`, but omits only `workflow/_project_unbounded_contracts.py`
and its `project_unbounded_proof` build dependency. It still requires
`project_proof` and all other runtime proof dependencies. The handwritten
unbounded readiness kernel remains present and is still called by production
code; this target does not establish its proof for the current sources.

Consumers must opt into `:unsafe_runtime` explicitly; its component bundle is
`:unsafe_runtime_bundle`. Next Blender currently uses this variant temporarily
for development, so `//:perceptual_grade_next` skips the unbounded project proof.
Restore its core dependency to `:runtime` to require the proof during packaging.
The normal `:runtime`, `:verify`, `:verify_extended` and root `//:verify_next`
retain both project proofs. The unbounded proof also remains directly runnable:

```sh
buck2 build //libraries/perceptual-grade-next-core:project_unbounded_proof
```

## Native Grade integration status

The active persistent-Grade contract supersedes per-edit native tree creation.
Core prepares immutable updates using fixed helper-field layouts selected by
development audit. Runtime does not search resolutions or run dense reference
accuracy gates. Dependency-aware preparation reuses unaffected fields; Linear
edits leave Tone/Color payloads and authored active routes intact. Audit identity
and layout schema accompany the preparation recipe.

Next Blender initializes every stage/family path and fixed-size helper image,
then applies changed values and bypass links to the same tree under native-reader
exclusion. Neutral routes are bypassed without removing nodes. Complete verified
updates retain prior data for rollback and advance publication revisions only
after success. Next Blender now prepares Grade snapshots in the background and
applies them through the persistent controller on Blender's main thread; Stack
edits construct a separate LUT candidate. Product-wide owner readiness, checked
Bake receipts, Image publication recovery and owned Save/Render continuation
are integrated. Packaged Linux/Blender acceptance covers direct Image and UV
Shader Bake and Compositor Bake through the registered operator, with native
evaluator output; broader lifecycle and failure interleavings remain open. The standalone
library has source-bound persistent lifecycle, numerical and synthetic GUI
timing evidence, including retained failures in its
[report](../perceptual-grade-nodes/EVIDENCE.md). That evidence does not implement
or certify the Next workflow.

The standalone [`perceptual-grade-nodes`](../perceptual-grade-nodes/README.md)
implements the forward native numerical path intended for Next Grade nodes. Its
[current handoff evidence](../perceptual-grade-nodes/EVIDENCE.md) distinguishes
the 1D-only implementation from the earlier accepted 2D-enabled baseline. Fixed
boundary geometry is a Buck2 resource. The under-1,000-node target and known
extreme-Web software-GPU error remain deferred findings, not product-integration
prerequisites for this work. Native Grade uses the complete Linear, Tone, Color,
H–K and output-boundary tree with packed coefficient/geometry fields; its input
RGB repair is omitted. Grade has no separate preview transform.

Stack remains a separate LUT backend: a 33³ preview uses every second vertex of
the 65³ final lattice, and only the completed 65³ LUT is final or used for
Stack Bake. A GPU helper may generate a Stack LUT if it conforms to the current
reference. Bake itself samples the accepted LUT using the installed mapping; it
does not run per-pixel GPU-helper grading. Grade Bake uses the accepted native
Grade node-tree output. Next Blender owns frozen-source capture, installation,
Image publication and Save/Render effects; UV/Compositor native capture has
packaged acceptance, while complete reader-retirement and publication proofs
remain pending. Next core owns portable settings,
equations and workflow policies.

Next core remains portable: it composes value-only settings, numerical
preparation and partial readiness policies, while Next Blender constructs,
installs, owns and serializes native trees/images.
The preparation/publication contract binds backend, settings, schema, Stack
quality tier, endpoint matrices and packed field identities to one revision. A
built node group or LUT alone is not a product readiness receipt. The checked
project workflow has partial checked coverage for owner admission, Bake
sequencing, Save/Render holds and exact terminal receipts. Current Grade and
Stack readiness reject both JSON and retained-pointer transaction debt and
compare installed content against accepted manifests. Proof correspondence for
production record conversion and remaining native admission/effects is open.
The [proof coverage handoff](PROOF_COVERAGE.md) records the boundary and missing
production composition.

## Required core properties

- Grade has one forward native graph contract. Preview and final output use the
  same prepared settings, graph schema and helper layouts; a Grade LUT or second
  preview recipe cannot satisfy readiness.
- A Stack preparation names its ordered settings/directions, reference recipe,
  endpoint matrices and quality tier. Preview completion can grant interactive
  display, but only matching 65³ completion can grant final, Save, Render or
  Stack Bake readiness. Even-grid 33³ samples are reused exactly in refinement;
  a cancelled or superseded preview/final attempt cannot certify another one.
- Every Bake request binds a frozen input revision and accepted output
  descriptor. Grade receipts name the native graph/resources; Stack receipts
  name the 65³ LUT, lookup/transport recipe and matrices. Publication requires
  matching evaluator and image receipts. Grade Bake evaluates the accepted
  native graph; Stack Bake samples only the accepted 65³ LUT. Custom GPU compute
  may generate and validate Stack lattice values, and a helper process may host
  Blender's native evaluator, but neither a separate analytic/custom-GPU pixel
  grader nor the 33³ preview can substitute as Bake output.
- Forward and inverse Stack preparation follow the current reference equations,
  including raw appearance handoffs and matching nonlinear-pair cancellation.
  Inverse results retain measured forward residual and status; a failed search
  is neither proof of unreachability nor a promise of a unique inverse.
- Portable control metadata maps the complete reference settings, defaults,
  units and supported choices within the fixed D65 / 203-nit viewing context.
  The product's gizmo and sidebar use that same mapping, with Tone Fit `[-2, 2]`
  and Color Fits `[-2, 6]`. Other existing UI ranges remain unless the reference
  supplies a specific limit.
- Preparation, Bake, Save, Render and recovery retain exact attempt/resource
  identities, permanent cancellation and native-reader exclusion. Existing
  node-budget and extreme-Web findings remain recorded as the two explicit
  deferrals; they do not authorize a different evaluator or hide other failures.

Source-bound requirements, witnesses, mutations and native correspondence tests
must cover these properties. They add to the canonical design's scope, project,
ownership and recovery properties. All runtime libraries and helpers use explicit
Buck2 dependencies and pinned external packages.
