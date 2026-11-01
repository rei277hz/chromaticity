# Perceptual Grade Next for Blender

Last updated: 2026-11-01

**Status: the native Grade/Stack workflow and focused Linux/Blender acceptance
are implemented, but delivery is incomplete. Known readiness, compensation,
content-validation and proof gaps remain.** The
[current audit handoff](CHECKLIST.md#current-audit-handoff-2026-11-01)
records exact receipts, confirmed findings and ordered remaining work. The
[state-machine design](STATE_MACHINE_DESIGN.md) is the canonical implementation
contract; [GOAL.md](GOAL.md) and [CHECKLIST.md](CHECKLIST.md) track
delivery. This documentation pass records the handoff and stops; it does not
fix the newly identified runtime or proof issues.

The selected first complete implementation step is
[trustworthy readiness and recovery](READINESS_RECOVERY_STEP.md). It includes
the proof gate, one owner-readiness path, exact installed-content validation,
compensation/backing retention and packaged saved-interruption acceptance.
Its checklist and exit criteria remain open. The kernel proof passes, but native
recovery, production source correspondence and installed acceptance are not
complete.

This product owns Blender integration under `perceptual_grade_next_blender`
and uses the independent
[`perceptual-grade-next-core`](../../libraries/perceptual-grade-next-core/README.md)
library under `perceptual_grade_next_core`. The
[architecture](ARCHITECTURE.md) records ownership and effect boundaries. The
preserved [`perceptual-grade-blender`](../perceptual-grade-blender/README.md)
product and `perceptual-grade-core` library remain intact; the new pair does
not depend on their runtime packages. All dependencies and generated assets
remain explicit Buck2 dependencies with pinned external versions.

Grade is forward-only and uses one persistent native node tree without a
separate preview transform. Control edits coalesce settings, prepare immutable
fields away from Blender's UI thread, then update the fixed graph with packed
field and binding readback. Grade Stack uses an ordered 33³ preview and 65³
final LUT; the preview vertices are reused from the final lattice. Both use
the portable evaluator's shaper, tetrahedral interpolation and endpoint
matrices. The 33³ image is never a Bake source. Stack entries support
reference-compatible FORWARD and INVERSE directions, including the 35/75
`abs(J_A)` crossover, raw appearance handoffs and finite inverse residuals.

Grade Bake evaluates the installed Grade node-tree output on frozen inputs;
Stack Bake evaluates the accepted 65³ LUT with the installed mapping. No custom
GPU helper grades Bake pixels directly. The checked `OutputGateway` binds
captures to frozen sources and evaluator identities, drives Bake receipts and
publishes through a recoverable packed float32 Image transaction. Installed
Linux/Blender 5.2.2 acceptance covers the registered Shader Image/UV and
Compositor Bake routes. Broader cancellation, reader retirement and concurrent
destination interleavings remain open.

Owned Save/Save As and Render operators provide confirmation, readiness waiting,
one native invocation and terminal receipts. Matching user-keymap actions and
the four agreed File/Render menu entries have reversible redirects. Direct
native operator/script calls can bypass this gate. Save honors the selected
compression value in the written file; Blender's remembered checkbox/default
may differ until reopen, and no tracking workaround is planned.

Scope/Gizmo composition observes viewport identity, frame/playback and native
reader barriers with exact display receipts. Non-destructive GPUOffScreen
capture supplies scene-linear statistics and histogram, waveform and
vectorscope pages. Installed acceptance covers animated source observations,
paused acquisition/publication during playback, and a fresh final-frame visual.
Coherent primary/reference/environment batches and remaining service/resource
interleavings are unfinished. Grade/Stack controls and transform preparation
remain static: animated Grade controls, per-frame texture banks, auto-keying and
separate Exact LUT workflows are deferred. The control panel uses the supported
fixed D65 / 203-nit context, Tone Fit `[-2, 2]` and Color Fits `[-2, 6]`.

Load/Undo/Redo recovery validates reusable Stack payloads, rebuilds Grade
controllers, repairs saved preparation/publication transactions and discards
transient Bake/Save/Render operations. Structural replacement retains real
prior/candidate tree references plus host links, defaults and metadata. Grade
updates retain packed float32 backups of changed fields and a binding/metadata
snapshot, including binding-only transactions. New edits are blocked while a
ledger is retained, and field recovery uses the retained ledger's own
transaction/slot metadata when the redundant JSON marker is absent. Those
focused edit/recovery regressions are fixed; source correspondence and recovery
edge cases still keep the readiness/admission milestone open.

The latest source audit confirms that Grade and Stack readiness reject both JSON
and retained-pointer transaction debt, and compare installed content against
accepted manifests. Remaining gaps are: partial backup deletion can strand
restoration when ledger retirement fails; structural and Grade snapshot
validators accept incomplete inventories; in-place Grade field publication has
no durable committed marker; and Stack candidate cleanup double-removes Images.
The native Stack fixture lacks owner schema, while the installed Stack fixture
saves an unreferenced host tree. These are known implementation gaps, not
assumptions covered by the proofs. The [current handoff](CHECKLIST.md#current-audit-handoff-2026-11-01)
names the affected functions and required regressions.

Native tests exercise actual `.blend` library serialization of field and tree
backing. Packaged Blender 5.2.2 crash/reopen acceptance also saves a partial
binding-only transaction with absent JSON and owner state `PENDING`, then calls
`os._exit(99)`. A fresh process restores the saved bindings/settings and prepares
Grade to `READY`. This establishes recovery from that completed save. It does
not establish partial field-write recovery in a terminated process, `READY`
with absent JSON, every structural-swap/ledger-retirement boundary, interrupted
file serialization, power-loss durability or recovery of unsaved edits. Idle
Restart and an injected recovery-failure retry also pass; interrupted native
work, broader crash/autosave and Undo/Redo acceptance remain open.

## Temporary development build

This product temporarily depends on Next core's
[`unsafe_runtime`](../../libraries/perceptual-grade-next-core/README.md#temporary-runtime-without-the-unbounded-project-proof).
Build from the repository root:

```sh
buck2 build //:perceptual_grade_next --show-output
```

The development package omits only `workflow/_project_unbounded_contracts.py`
and its `project_unbounded_proof` dependency. `project_proof` and all other
runtime proofs remain required. The handwritten unbounded readiness kernel is
unchanged. Restore the core dependency in this product's `BUCK` to `:runtime`
to require the unbounded proof during packaging. `//:verify_next` still runs
both project proofs through the full verification aggregate.

## Refresh the development checkout

The **downstream repo** at `~/workspace/perceptual-grade/` currently contains
the preserved Perceptual Grade **v1.23.2** code snapshot extracted from
`perceptual_grade-v1.23.2-20261101.zip`. It does not contain Perceptual Grade Next.

The `:install_workspace` target remains available for the future update to
**Next** in this same downstream repo. Its default destination is still
`~/workspace/perceptual-grade/`; running it replaces the current snapshot with
Next. Committing or pushing the downstream repo is a separate step.

Run from the monorepo root:

```sh
buck2 run //products/perceptual-grade-next-blender:install_workspace
```

Buck first builds the actual `perceptual_grade_next.zip` through the configured
NativeLink platform. It then runs the installer locally on the client. No
execution-mode switch or `--local-only` override is needed.

The installer validates the complete ZIP, removes **every file and directory
except `.git`** from the selected worktree, then extracts the ZIP's
contents there. This includes deleting stale hidden files. The destination must
already be a directory containing a `.git` directory or worktree file; that Git
metadata is preserved. Use `-- --destination /path/to/worktree` to select another
existing Git worktree.

The ZIP's user-facing [README](package/README.md) describes installation, use,
and the installed file layout. The repository README here remains the developer
guide.

## Verification and acceptance

Existing Buck aliases still select the preserved product; separate
`//:perceptual_grade_next` and `//:verify_next` targets are present. The eight
historically passing Next proof targets reported **493 obligations and 27
detected/replayed mutations**. The `project_unbounded_proof` kernel now passes
170 obligations and 4 mutation checks in build
`e458d854-a0f2-474f-9ee4-e903e6da13b7`; it does not prove production
`project.py` owner/evaluator/artifact conversion or native admission, and no
fresh aggregate receipt is recorded after this audit. `scope_view.inv` proposes
five joint properties but has no Buck target and lacks the required nonempty
`invariants` mapping. The [proof inventory](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
distinguishes those gaps, reduced specification models and native premises.
Inventory consistency tests do not establish theorem validity or current package
buildability.

Validate old and new extensions in separate Blender profiles/processes;
simultaneous enablement is outside scope. Retain extension identity
`perceptual_grade` with separate source/package namespaces. This delivery covers
Linux/Blender; macOS/Metal and physical HDR acceptance remain separately deferred.
The standalone [`perceptual-grade-nodes`](../../libraries/perceptual-grade-nodes/README.md)
backend uses a build-time boundary asset and 1D-only Web. Its under-1,000-node
target and known extreme-Web software-GPU error remain unresolved deferred
findings in its [evidence](../../libraries/perceptual-grade-nodes/EVIDENCE.md).
The 33³/65³ quality tiers apply only to Stack.
