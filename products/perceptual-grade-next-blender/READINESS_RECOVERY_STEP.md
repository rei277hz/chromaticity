# First implementation step: trustworthy readiness and recovery

Updated: 2026-11-01

**Status: partially implemented; the milestone remains unfinished.** The
unbounded kernel proof passes, and production now uses it for every owner count.
Both-ledger rejection and accepted native content manifests are implemented.
Production record correspondence, recovery/cleanup defects and installed Stack
acceptance remain open. This documentation pass records the latest audit and
stops without runtime, Buck or `.inv` changes. The
[canonical design](STATE_MACHINE_DESIGN.md) defines the underlying contract;
the [audit handoff](CHECKLIST.md#current-audit-handoff-2026-11-01) records
the current defects and latest versus historical receipts.

## Latest audit and remaining implementation

The unbounded proof passes 170 obligations and 4 mutation checks in build
`e458d854-a0f2-474f-9ee4-e903e6da13b7`; it covers `project_unbounded.py`, not
production record alignment/conversion in `workflow/project.py:251–318`.
Invariant 57, core workflow 75, readiness 11, native Grade 8, Bake lifecycle 20,
output 19 and canonical inventory 6 tests pass. Recovery has 2 failures among
34 tests, native Stack has 1 failure among 9, and installed smoke fails during
Stack setup/reopen after reaching the Grade boundaries. There is no complete
passing installed or fresh aggregate proof/package receipt for this step.

| Remaining issue | Where to resume | Required result |
| --- | --- | --- |
| Backup cleanup deletes resources before ledger retirement can fail | `preparation_ledger._discard_backup_images`, `recovery.requeue_prepared_nodes` | Repeated recovery must distinguish restoration from cleanup and must not require already-deleted backups. |
| Snapshot shape checks do not establish complete inventories | `preparation_ledger._validate_tree_snapshot`, `_validate_grade_snapshot` | Reject empty/truncated structural defaults, properties or links and truncated Grade bindings/defaults before effects. Use independently checkable expected inventories; accept legitimately empty links only when completeness is established. |
| In-place Grade lacks a durable committed field-ledger state | `updates._install_admitted` | A saved interruption after verified manifest acceptance must preserve the commit and finish cleanup, rather than restore old fields. |
| Stack candidate disposal removes Images twice | `updates._dispose`, `stack_graph.NativeStack.dispose` | One disposal authority per resource; repeated cleanup is safe and preserves the original error. |
| Native Stack fixture lacks owner schema | `tests/test_native_stack.py:56–65` | Construct a valid owner before exercising preview-to-final replacement; keep explicit invalid-schema rejection coverage. |
| Installed Stack host is unreferenced when saved | `tests/installed/runner.py:169–195` | Retain the synthetic host across reopen and complete the Stack interruption cases. |
| Production conversion is outside the kernel proof | `workflow/project.py:251–318` | Prove alignment preserves exact owner/evaluator/artifact identity and admission uses the checked result. |

The older JSON-only debt checks and identity-only Grade manifest findings are
superseded: both ledger forms are now rejected and accepted manifests include
graph/image contents. Grade publication checks prepared pixels using the live
controller; admission compares observed content to the accepted record. Full
initial/update/recovery/Save/Render/Bake correspondence remains to be accepted.
The complete cross-machine proof and orphan `scope_view.inv` work remain in the
broader checklist; fixing this milestone alone does not complete those claims.

## Objective and boundaries

Make Grade and Grade Stack readiness trustworthy for every finite number of
owners and recoverable across the represented saved preparation boundaries. An
owner with incomplete preparation, corrupted installed content or unresolved
transaction debt cannot satisfy native Bake binding or project Save/Render
admission, even when its revision, resource IDs or saved `READY` marker appear
unchanged. Failed compensation retains the backing needed to restore or repair
the owner. Reopening restores a coherent prior state, preserves a verified
commit, or retains explicit repair debt and blocks dependent output.

Cover initial Grade/Stack creation, in-place Grade field updates, structural
replacement, recovery, and output admission. Keep the current numerical layouts
and native Grade/Stack evaluators. Broader Scope/view composition, Bake
concurrency and reader-lifetime work, Undo/Redo completion, macOS/Metal and
physical HDR acceptance remain later milestones. The existing graph-budget and
extreme-Web GPU findings remain deferred and unresolved.

## Required implementation

These are the continuing acceptance requirements. The current status above
distinguishes implemented portions from the work still needed to close the step.

### Mandatory proof gate and one readiness decision

`project_unbounded_proof` remains required for runtime, test and aggregate
acceptance. Next Blender's [temporary development build](README.md#temporary-development-build)
uses `unsafe_runtime`; restore its normal core dependency for this acceptance
gate. The normal core runtime and verification aggregates still require the
proof. Preserve the shared Invariant verifier repair so helper summaries whose
results lose quantified binder dependencies fail closed. Cover transitive calls,
wrappers, contracts and nested `forall_range`, `exists_range` and `sum_range`.
Preserve directly inlined loop-free pure helpers used by existing proofs. Prevent
binder-dependent assumptions from escaping through other interpreter paths,
including arithmetic normalization. Increasing solver timeouts or removing the
dependency is not a repair.

The kernel uses direct quantified field relations in readiness assertions and loop
invariants. Any lookup must be total first-match lookup without an unestablished
uniqueness precondition; reject duplicate worklist entries separately. Revision,
evaluator and repair-debt mutations must be checked against independent field
assertions rather than the helpers being mutated. Prove the empty case, arbitrary
prefix preservation from `k` to `k+1`, the full-list conclusion and termination
by `n-k`. No fixed owner-count cap replaces this induction.

Production uses that single decision for all owner counts. Still prove conversion
from immutable production owner requirements and artifacts into `ReadinessState`:
preserve every required owner exactly once, its required evaluator, exact current
revision, evaluator/artifact/manifest identities and repair debt. Reject duplicate,
unpaired, missing or malformed records. Keep the separate four-slot model out of
runtime readiness authority; its historical proof and independently used receipt
predicates need not be discarded. Connect the checked decision to actual
Save/Render admission and fresh native Bake evaluator binding. Blender discovery
and actual native-content observations remain explicit adapter premises with
native tests; they are not conclusions of a scalar readiness theorem.

### Installed content, manifests and admission

For both Grade and Stack, reject unresolved JSON transaction markers and retained
PointerProperty ledgers independently, before trusting saved readiness flags.
Apply the same validation to initial creation, subsequent edits, replacements
and recovery; initial operators must not set `READY` through a weaker path.

A Grade manifest binds the current algorithm/layout schema, authored settings
and revision, both matrices, exact graph bindings and each schema-defined field
role. Validate actual dimensions, packed float32 contents/digests, color
interpretation, image assignments, native links and defaults. A fingerprint of
resource IDs or a minimum image count is insufficient. Record the accepted
expected contents at verified publication and compare fresh native observations
against them at admission; hashing current corrupted data into a new manifest
must not make it accepted. Missing or obsolete derived manifests fail closed
and queue preparation from authored controls.

For Stack, retain separate identities for the stable authored recipe/demand and
the exact installed evaluator content. A waiting Bake must survive the matching
33^3 preview to 65^3 final refinement. Final admission and capture bind the exact
65^3 LUT content, lookup/transport graph and matrices after readback. The 33^3
preview can serve interactive display but never Bake, Save or Render readiness.
Preserve existing LUT content validation and make both ledger checks mandatory.

Only fully validated publication advances the accepted manifest/revision and
retires its transaction. Revalidate the exact current owner and evaluator when
binding Bake or invoking owned Save/Render. This step does not claim to intercept
arbitrary direct native operator/script calls outside the owned gate.

### Compensation, malformed backing and cleanup

Retain prior fields, links/defaults, metadata and controller revision until
compensation has completed and been read back. If any metadata or native rollback
fails, invalidate/quarantine the controller and retain its ledger and backups.
Dependent Bake/Save/Render remains blocked; unaffected owners retain their
accepted output. `controller.valid` alone cannot authorize backup disposal.

Validate complete structural and Grade snapshot inventories, including required
properties, bindings, defaults, links and field slots, before recovery mutates
any data. Checking only the shape of entries supplied by the snapshot cannot
detect omitted entries. Missing or malformed
backing, including an empty `grade_snapshot`, remains explicit repair debt.
Deduplicate candidate and ledger Image references by Blender identity before
deletion. Cleanup failure must remain accounted for and retryable; do not retire
the last recovery reference or delete resources still owned by a live tree.
Persist the distinction between uncommitted restoration and verified-commit
cleanup before deleting backing. A retained ledger after partial cleanup must
resume cleanup without attempting restoration from resources already removed.

## Required regression and installed evidence

| Layer | Required cases and result |
| --- | --- |
| Verifier | Reject unsupported direct/transitive summarized or loop-lowered calls under all three range operators, including nesting and contract paths; preserve inline pure helpers and their precondition/bounds checks; prevent escaped binder-dependent assumptions. Existing induction, empty-input and early-return checks still pass. |
| Portable readiness | Empty, reordered, duplicate, missing and unpaired owners; malformed parallel tuples; stale revisions, wrong evaluators, blank identities, repair debt, five-plus and larger lists. Mutation controls detect and replay independent revision/evaluator/debt errors. Finite test lengths supplement the arbitrary-length proof. |
| Native manifests | Corrupt pixels, dimensions, precision, color interpretation, matrices, image assignments, links/defaults, schema or revision while retaining resource IDs. Each mismatch prevents output admission; initial insertion and later updates establish the same accepted manifest. |
| Recovery debt | Grade and Stack with JSON-only, pointer-only or both ledger forms, including `READY` and absent JSON. Neither final admission nor native Bake binding succeeds while debt remains. |
| Compensation and cleanup | Metadata commit/rollback failure, malformed/incomplete snapshots, duplicate resource references and cleanup failure. Backing survives failure; successful repair verifies prior output and releases debt exactly once; shared/live resources remain owned. |
| Stack refinement | A matching waiting Bake survives preview-to-final recipe identity; only the fresh accepted final-content identity binds capture. Preview, stale final manifests and changed LUT/lookup contents are rejected. |

Extend packaged Linux/Blender 5.2.2 forced-exit/reopen tests using synthetic
projects and the actual extension. Save at each named semantic interruption
boundary, terminate without cleanup, then reopen in a fresh process:

| Saved interruption boundary | Required reopened outcome |
| --- | --- |
| Partial field upload/packing | Restore packed prior fields and bindings, or retain repair debt if backing cannot be validated. |
| Binding-only change | Restore exact links/defaults even with unchanged field/resource IDs and absent JSON. |
| Metadata publication | Restore a coherent prior generation after an uncommitted edit; `READY` cannot override retained debt. |
| Grade/Stack structural replacement | Restore the prior binding for an uncommitted swap; preserve the candidate only when its commit and complete installed contents verify. |
| Commit/ledger retirement | Preserve the verified committed output after lost acknowledgement; finish retained cleanup idempotently and do not replay the operation. |

Verify repeated recovery, failed-repair retention, fresh authority before
readiness and blocked dependent output during repair. Explicit Bake, Save,
Render and hidden-Gizmo work must not replay. Use only the opened `.blend` or
autosave as recovery authority. These tests cover completed saved snapshots of
partial operations, not interrupted file serialization, power-loss durability
or unsaved changes absent from the opened file. Broader autosave timing remains
separately tracked.

## Completion and reporting

This is one milestone; a green solver target alone does not complete it. Obtain
fresh successful evidence in this order:

1. `//libraries/invariant:tests` and
   `//libraries/perceptual-grade-next-core:project_unbounded_proof`, including
   mandatory properties, positive witnesses, replayed mutations and generated
   runtime validators.
2. Next core workflow and canonical-inventory tests; product `project_readiness`,
   `native_grade`, `native_stack`, `recovery`, `output_operators` and affected
   Bake-binding/lifecycle tests. Exercise the real conversion and admission
   callers rather than only a copied readiness fixture.
3. The expanded installed crash/reopen fixture, owned Save/Render checks and
   native Grade/Stack Bake binding on Linux/Blender 5.2.2. Keep other installed
   workflow gaps explicitly open.
4. `//:verify_next` and `//:perceptual_grade_next`, followed by preserved
   `//:verify`, `//:perceptual_grade`, `//:hdr_color_picker` and `//:dctl` checks
   because verifier changes affect shared proof/package closures.

Record source, requirement, verifier, generated-validator and archive identities,
build IDs, exact passing counts and remaining premises. Update the checklist
and proof inventory only from fresh evidence. Partial canonical families remain
partial wherever other requirements are outside this milestone.

No public UI or extension API change is intended. Internal readiness records
and the serialized derived-manifest schema may change. Rebuild obsolete derived
state from authored controls without historical migration, changing authored
Images/committed Bakes or touching the supplied project. All dependencies remain
explicit and pinned through Buck2.
