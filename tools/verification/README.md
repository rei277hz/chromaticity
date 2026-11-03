# Verification and artifact gates

`buck2 build //:verify` combines retained Lean color-model theorems with the shared
Invariant `.inv` verifier. The generic process lifecycle, thirteen leaf
machines and ten workflow coordinators have separate requirements. Handwritten
Python is the behavior authority; proofs are build evidence and produce no runtime
code. See [the framework authoring guide](../../libraries/invariant/README.md).
These retained Grade/Picker gates do not certify the rebuilt Blender product.
Its product-owned [policy documentation](../../products/perceptual-grade-next-blender/POLICY.md)
describes its separate machine requirements and proof targets.

## Source-bound machine verification

The reusable source model, symbolic interpreter, obligation builder and concrete
counterexample evaluator live in `libraries/invariant/verification/`. Requirements name invariants,
function pre/postconditions, relational properties, witnesses, source mutations
and loop induction clauses. Initialization establishes the invariants; each
admitted event preserves them. Helper calls, result types, definedness, exceptional
paths and loop exits are checked against the actual implementation.

Exact identities distinguish booleans, integers and Unicode strings. Finite enum
labels use nominal solver values; unrestricted strings use codepoint sequences.
Arbitrary finite tuple queries retain duplicate and empty-input behavior. Loop
induction proves counting, universal checks and cyclic selection without bounding
sequence lengths. Requirements cannot assume an unproved helper summary.

The [bake-image requirements](../../libraries/perceptual-grade-core/requirements/bake_image.inv)
and [mandatory inventory](../../libraries/perceptual-grade-core/requirements/inventory.bzl)
name the properties, positive witnesses and source-mutated controls.
Counterexamples execute through ordinary Python; unsupported syntax, solver
unknown/timeouts, vacuity, missing claims and nonreproducing controls fail closed.
Native observations and receipt identity remain explicit adapter premises.

Each `invariant_proof` action declares the policy, `.inv`, mandatory inventories,
all verifier modules and pinned Z3 wheel as an exact closure. The checker validates
its executing modules and solver against those inputs. Successful artifacts include
SMT queries, the report and a receipt. The receipt binds the closure, source,
requirements, report and mandatory claim inventories.
Current Buck actions use a ten-second per-query timeout and Z3 4.15.4.

```sh
buck2 build //libraries/invariant:verify //libraries/blender-runtime:verify
buck2 build //libraries/perceptual-grade-core/proofs:verify
buck2 test //libraries/invariant:tests
buck2 test //tools/verification/tests:invariant_packaging
```

The interpreter, contract binding, supported Python semantics, build tools and
Z3 are trusted. The checker is not itself proved correct by Lean. Native behavior,
scheduling fairness and unconditional eventual recovery remain outside these
protocol proofs.

## Lean mathematics

`//libraries/perceptual-grade-core/proofs:color_model` provisions pinned
Lean/Mathlib, compiles the model theorems and audits transitive axioms. These
prove color mathematics, not all Python/shader/DCTL implementations or the
picker's different appearance model. Packaging requires machine proofs; the root
verification target additionally requires the Lean gate.

## Archive integrity

Product archives contain exact declared runtime sources; proof bundles remain
outside the archive. Packaging checks mandatory claims, witnesses, replayed
mutations, complete input inventories, and that each shipped policy source matches
its proof receipt. Changed or missing evidence removes stale ZIPs and reports
rather than leaving a previously accepted artifact. The package report records
accepted source, report and closure hashes. Native safety assumptions are not
expanded by an archive integrity check.

The new Perceptual Grade product uses this proof-only package boundary. Existing
Grade and Picker consumers are deferred for migration and their package targets
are not compatible until that work is completed.
The [component packaging guide](../../build_defs/README.md) describes the source
ownership and private namespace layout checked by these gates.

The architecture gate rejects retired package imports, product cross-imports
and native dependencies in mathematical packages. The generic Invariant framework
has no Blender dependency. The preserved Grade and Picker products consume the
narrow `blender_runtime` host adapter without importing or discovering one another;
DCTL generation has no Blender dependency.

```sh
buck2 test //tools/verification/tests:package_boundary //tools/verification/tests:invariant_packaging
buck2 test //tools/verification/tests:archive //tools/verification/tests:grade_archive
buck2 test //tools/architecture/tests:components
```

## Runtime and native regressions

Framework tests exercise typed function bindings, exact domains, immutable
effects, initializer validation, Store preview/commit behavior and App/Store
identity isolation. Policy and product tests exercise scheduler/output traces,
worker occupancy, retries, ownership and native adapter behavior. Installed
tests load real extension archives in pinned Blender.

The GUI Undo stress target performs 50 real event-driven cycles, including
pending-worker cancellation, native Undo/Redo and reset chains. Its native
scenario has a 29-minute budget and its process wrapper allows 30 minutes.
Allow that existing budget through Buck's outer executor (whose default is
10 minutes):

```sh
buck2 test //products/perceptual-grade-blender/tests/installed:gui_undo -- --timeout 1830
```

The bake-image Z3 gate is complemented by policy runtime tests for concrete
recovery behavior, typed domains and App/Store envelope rejection, plus a
source-interpreter correspondence regression. The recovery adapter fences Image
identity, scalar publication operation IDs and observation generations without
reading pixels or hashing packed data. Installed fixtures independently inspect
pixels and packed bytes to test native Undo/Redo, dirty-buffer preservation,
failure/retry and helper retirement. These checks supply evidence about native
observations that the symbolic policy takes as inputs; cache invalidation does
not certify numerical contents.

Other passing tests provide finite regression evidence. Scheduler progress still depends
on a stable resident set, continuous eligibility, preserved/advanced cursors,
finite successful worker/capture completion and fair timer/compositor dispatch.
A worker may keep emitting progress, a wait without a deadline may remain pending,
and priority work may starve other jobs.

Native coverage remains incomplete (`coverage_complete=false`). Public job
queries and main-thread publication do not establish reader exclusion for the
USD/Alembic export startup interval: a private native job can start before the
interface lock is set. Guarded Save/Render entrypoints prepare
output for those operations; compatibility handlers cannot veto native work
when preparation fails. Arbitrary later edits and native crashes remain outside
that preparation contract. macOS/Metal, physical HDR display and manual
painting retain separate acceptance gates. See the
[Grade architecture](../../products/perceptual-grade-blender/ARCHITECTURE.md).

## Historical material

The machine INVARIANT sources, Z3 proofs/checkers, unfinished Rocq migration,
proof-specific tests and requirements, receipts and migration reports are
archived outside the source tree at `../perceptual-grade-proof-archive/` relative
to the repository root. The archive records original paths and file hashes.
Pre-cutout documentation is retained there as historical context.

The archived results apply only to their original inputs. Archived DSL sources,
generators, receipts and historical equivalence reports are not inputs to the
shared `.inv` proofs. The current gate verifies the checked-in Python source
and its current obligations; it does not claim preservation of all historical
formal obligations or revive the unfinished Rocq migration.
