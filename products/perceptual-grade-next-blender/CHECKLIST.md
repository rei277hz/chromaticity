# Active Perceptual Grade Next implementation handoff

Last updated: 2026-11-01

**Status: implementation underway; earlier core and focused product checks pass.
The unbounded readiness kernel now has a fresh passing proof receipt, but its
production owner-record projection and complete aggregate acceptance remain
open. The latest recovery and native Stack regressions and installed smoke fail;
the readiness/recovery milestone remains unfinished. Earlier packaged
Linux/Blender 5.2.2 acceptance covers direct Image and UV Shader
Bake, Compositor Bake, extension save/reopen, idle and fault-retried Restart,
modified-Image Save diagnostics, Render receipts and viewport capture with
histogram, waveform and vectorscope pages.** Recovery blocks edits while
unresolved owner ledgers remain and can recover field metadata from the
persistent ledger when its JSON marker is absent.
Owner discovery now retains a damaged fifth owner as unready, and the five-owner
test confirms that it blocks both Save and Render. Scope selects the last observed
VIEW_3D area per window, falls back to the largest live view, and fences old
captures after transfer. Full scope batch coherence, native fault/reader
interleavings, broader installed Undo/crash/autosave behavior, and Restart during
active work remain open. The
[canonical design](STATE_MACHINE_DESIGN.md)
defines required core properties, numerical behavior, native effects and
acceptance. The Next pair now includes independent core/product packages,
reference-aligned math, native Grade/Stack adapters, static edit-triggered
preparation and initial package/core/native coverage. This checklist tracks
remaining integration and acceptance; helper or component tests do not certify
the complete application workflow.

## Phase 0: implementation contract (complete)

- [x] Update the Next product handoff, checklist, architecture/readmes and canonical
      state-machine core properties before changing source.
- [x] Specify the single native Grade graph, Stack 33³/65³ quality tiers,
      exact Grade/Stack Bake evaluators, current-reference directed Stack math,
      full UI schema and static-animation policy.
- [x] Defer the inherited node-count and extreme-Web GPU findings without
      marking them resolved or making them blockers for this Next delivery.
- [x] Correct the reference README's stale native Tone Fit/table description.

## Phase 1: isolate the new pair

- [x] Implement the source/build scaffolding under the documented
      `libraries/perceptual-grade-next-core` / `perceptual_grade_next_core` and
      `products/perceptual-grade-next-blender` / `perceptual_grade_next_blender`.
- [x] Preserve old core/product source, Buck targets, tests and aliases; keep
      DCTL/reference consumers on the existing core.
- [x] Add independent `//:perceptual_grade_next` and `//:verify_next` targets.
      Do not redirect existing targets or import the old core/product runtime.
- [x] Declare independent package ownership, inventories and baseline numerical
      comparisons. Reuse shared Invariant, Blender runtime and color-core without
      a generic runtime rewrite; account for shared-source changes explicitly.
- [x] Retain extension identity `perceptual_grade`; isolate old/new testing in
      separate Blender profiles/processes. Do not implement coexistence.
- [x] Pin runtime numerical dependency through Buck2's existing pinned NumPy
      target; this implementation added no new external package.

## Phase 2: source-bound models and proofs

- [x] Implement one global `ScopeActor` plus foreground `ViewAuthority`, exact
      display issue/apply receipts, frame/playback barriers, and a dismissible
      Gizmo entry/close surface. Installed capture verifies finite scene-linear
      statistics and histogram, waveform and vectorscope pages. Per-window
      last-observed viewport selection, largest-view fallback and old-capture
      fencing are implemented. Installed acceptance verifies stopped-frame
      recapture, acquisition/publication pause during playback, and a fresh
      visual for the final stopped frame. Coherent primary/reference batches
      remain open.
- [x] Implement `project_workflow` for explicit Image Bake, static final
      preparation, output and recovery with cross-operation properties. Native
      source/evaluator and Image publication adapters now bind those receipts.
- [x] Model extension-lifetime Restart, permanent cancellation, exact owner/
      attempt/view identities and retained physical cleanup debt. Product-side
      receipt-driven restart execution and installed idle-Restart acceptance pass;
      fault/late-handle teardown acceptance remains open.
- [x] Prove the checked admission and receipt ordering for the deterministic
      portable kernel; correspondence with the production owner-collection
      adapter and native effects remains an acceptance task. The aggregate
      gate includes bounded, order-independent Restart/composition ledgers and
      generated validators for eight historically passing proof targets. The
      ninth unbounded target has a fresh kernel receipt, but production
      projection/admission and current aggregate acceptance remain open.
- [x] Add an initial set of owner-local requirements, mandatory
      properties/witnesses/mutations, generated contracts and independent
      proof/package gates. The
      [coverage inventory](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
      names the exact checked source and remaining properties.
- [ ] Complete correspondence and interleaving evidence for every required
      canonical property. Current proofs do not complete S01–S19, full
      production owner-worklist admission, native effects, or serialization and
      installed crash behavior. Do not transfer old-pair evidence to Next.
- [x] Port the current independent reference semantics into Next core without a
      runtime dependency on `perceptual-grade-reference` or the old production
      kernels. Implement forward Grade and ordered FORWARD/INVERSE Stack entries,
      including the `(35/75) * abs(J_A)` crossover, raw appearance handoffs,
      endpoint matrices and inverse residual/status semantics.
- [x] Model Grade graph versus Stack preview/final readiness and exact Bake
      evaluator identity as core properties: a preview, stale revision, model-only
      result or helper-graded pixel buffer cannot satisfy final/Bake admission.
      Core receipt policy and the Blender owner-readiness adapter are implemented.
      Installed Shader UV and Compositor paths now exercise the registered
      operator's poll/execute, native Grade output and Image publication; full
      reader, cancellation and cross-operation lifecycle acceptance remains open.

## Phase 3: foreground adapters and failures

- [x] Implement foreground `ViewAuthority` and value-only scope composition;
      Blender identity/barrier handlers, display receipts and non-destructive
      viewport-pixel capture are present. Installed acceptance verifies
      scene-linear statistics and chart data for all three scope pages,
      stopped-frame recapture, and playback pause/resume behavior; coherent
      reference batches remain open.
- [x] Make Gizmo close revoke visibility independently of computation; add
      focused owner/view transfer and late-display tests.
- [ ] Implement asynchronous proposal/start/grant/effect/receipt handling with
      exact original-owner routing and retained late handles/partial effects.
- [x] Distinguish issued display tokens from foreground application and require
      an exact adoption receipt under current view/playback authority. The
      installed capture path is verified; coherent primary/reference measurement
      bundles are still required.
- [ ] Preserve native-evaluation ordering, pending-transition reconciliation and
      physical retirement. Passive UI must not grant authority.
- [ ] Provide defined localized outcomes, explicit local Retry and previous-result
      preservation; retain cleanup across failure and Restart.
- [x] Omit Grade keyframing/auto-keying, dependency drivers, copied animation
      Actions and separate Exact LUT workflows from the new pair; controls are
      static and relevant destination-channel animation is rejected while input
      and upstream animation remain supported. Broader installed Undo acceptance
      remains open below.
- [x] Bind static Grade/Stack edits to coalesced background preparation; install
      Grade updates to the fixed graph and Stack candidates on Blender's main
      thread only after preparation and readback succeed. Preserve previous
      accepted output and expose local Retry after failure; test Grade bindings,
      Stack links/defaults and failure retention.
- [x] Make Grade/Stack controls non-animatable; detect unsupported animation only
      on effective Grade/Stack destination channels. Preserve authored animation
      data and support input Color/upstream animation in the same NodeTree.

## Phase 4: capture and Bake preflight

- [x] Select the per-window last-observed VIEW_3D area, falling back to the
      largest live viewport; transfer Scope if its area closes and fence late
      captures under the old view identity. The observation comes from the draw
      context because Blender exposes no direct last-focused-area query here.
- [ ] Capture effective last-used viewport lighting/framing; label authored
      World **Scene World** and preserve exact source/occurrence/view identities.
- [ ] Preserve coherent primary/reference batches and compatible progressive
      publication without reviving cancelled attempts.
- [ ] Support dynamic inputs and automatic frame-change scopes after native
      evaluation. Pause acquisition/publication during playback, retain display
      and refresh the latest stopped frame after native acknowledgement.
- [ ] Keep Bake preflight stable across unrelated UI changes; revalidate semantic
      source, binding, route and native readiness at execution/publication.
- [x] Implement portable Bake-route gates for Image-to-UV, non-Cycles UV,
      missing UV maps, playback/readers and Shader-to-RGB. Route facts are not
      yet sufficient for all native lifecycle behavior. Direct Image, UV and
      Compositor Grade capture are connected to the owned Bake path; installed
      tests cover UV coverage/material isolation and Compositor frozen-input
      cancellation.
- [ ] Preserve Grade-change Bake interruption, shared destination ordering,
      committed Images and physical retirement.
- [ ] Preserve Image select/create/rename, + New, separate Bake row, Vector naming
      and private implementation sockets through save/reopen; add no fake users.
- [x] Define Bake's evaluator as part of the frozen source identity: Grade Bake
      evaluates the admitted installed Grade node-tree output; Grade Stack Bake
      samples only the accepted final 65³ LUT using the installed lookup and
      endpoint-matrix semantics. A GPU helper may generate/validate the Stack
      LUT but may not grade Bake pixels directly. The Stack's 33³ preview is
      never a Bake or final-output source. A helper hosting the actual Blender
      native evaluator is allowed; a separate analytic/custom-GPU grader is not.
      Implemented at the adapter boundary: `OutputGateway` binds capture and
      lifecycle receipts to the accepted project evaluator/manifest, requires a
      frozen source route, rejects preview Stack capture, and publishes through
      a packed float32 Image backup transaction. The restricted Shader still-Image
      operator invokes the installed Grade graph or accepted Stack 65^3 LUT.
      Packaged tests now exercise direct Image and UV Shader routes plus private
      Compositor capture with native Grade output. Stack Bake and full
      reader/transaction interleavings remain part of acceptance.
- [x] Implement restricted native evaluated-pixel capture and Bake UI for direct
      still Images in Shader node trees, with source identity and transactional
      Image publication. UV and Compositor paths have separate installed coverage.
- [x] Exercise packaged Shader UV and Compositor Bake through the registered
      operator's poll/execute. UV acceptance checks covered/uncovered texels,
      non-owner exclusion, unchanged mesh/material assignments and recovery
      cleanup. Compositor acceptance checks native graph output, alpha, selected
      destination publication, frozen-input cancellation and recovery cleanup.
      Shader acceptance also injects route-preflight and admitted evaluation
      failures: implicit zero-user targets are removed, while an explicitly
      selected target keeps its prior pixels.
- [ ] Complete native reader exclusion/retirement, destination ordering under
      concurrent Bakes, cancellation at each route stage, and full readback and
      publication-receipt interleavings.

## Phase 5: static preparation and persistence

- [x] Use the installed Grade node tree as its sole grading evaluator; provide
      no separate Grade preview transform. Prepare the full native graph, packed
      helper fields and matrix descriptors after relevant edits. Start from schema
      5: Tone 256, Color 8,192, Web parameters 4,096, toes 1,536, Compact 3,072
      and fixed boundary 513 × 321.
- [x] Prepare Grade Stack as a separate 33³ intermediate preview and 65³ final
      LUT; reuse each even 65³ vertex exactly in the 33³ grid. Publish the final
      output only after the accepted 65³ LUT and bindings are complete. Core and
      Blender readiness gates require the final state for Save/Render; complete
      installed Save/Render acceptance remains open.
- [x] Keep Grade/Stack controls static. Add no scene-range Grade preparation,
      per-frame LUT timeline or per-frame texture bank.
- [x] Stage immutable per-owner Grade/Stack candidates with native Grade graphs and
      packed helper fields (or Stack LUTs), endpoint matrices, exact public sockets
      and baked-Image bindings. Use reference-compatible forward/inverse Stack
      math, including nonzero low/high controls. Full owner-worklist and
      cross-operation proof coverage remains open in Phase 2/7.
- [x] Fence candidate installation with transaction identity, packed readback,
      binding checks and publication state. Grade-field recovery blocks any edit
      while unresolved backing is retained and uses the serialized ledger's own
      transaction/slot metadata if the redundant JSON marker is missing.
- [ ] Complete validation of live Blender Grade/Stack owners against authored revisions,
      packed resources, final evaluator bindings and manifest identities before
      feeding project readiness. Both-ledger rejection and accepted-content
      manifests are implemented; complete production correspondence and the
      installed initial/update/recovery/admission matrix remain open.
- [x] Persist real references to prior/candidate resources before structural
      live replacement. The serialized owner ledger retains both NodeTrees,
      external link descriptors, input defaults and metadata; ordinary Grade
      field edits retain packed float32 backup Images with digest readback.
      Blender library write/load tests cover both. Recovery regressions cover
      retained-ledger edit blocking and field restoration without the JSON marker.
      One saved binding-only crash/reopen fixture passes; reader-release and
      broader field/structural crash/autosave acceptance remain open.
- [ ] Finish compensation/readiness interleavings and exact owner-worklist
      completeness. Failed structural compensation retains repair debt, but
      verify all field/Stack failure paths, unaffected-owner readiness and
      Save/Render blocking in the production adapter.
- [x] Validate packed Stack assets on reopen and reuse only a matching 65^3
      payload; rebuild invalid Stack or Grade controller state from authored
      controls. Recovery restores interrupted Image overwrites and discards
      explicit Bake/Save/Render operations. Native crash/Undo acceptance remains
      open.
- [x] Treat `.blend`/autosave as sole recovery authority; use no unsaved journal
      authority and never resume explicit Image Bakes automatically.
- [x] Repair interrupted explicit Bake Image overwrites from packed prior
      backing and preserve a verified commit after a lost acknowledgement;
      focused recovery tests cover partial write and committed result. Real
      autosave/parent-termination acceptance remains open.
- [ ] Preserve authored Images, committed Bakes and new-format wrappers/Undo;
      add no historical migration or compatibility repair.

## Phase 6: Save, Render, Undo and Restart

- [x] Add owned Save/Save As confirmation and wait continuation before one native
      `EXEC_DEFAULT` Save; pre-acceptance cancellation leaves Bakes untouched and
      a waiting Save can be cancelled without invoking Blender.
- [x] Honor chosen compression and accept the remembered-default difference
      without a workaround. The owned path supplies the chosen compression;
      Blender's remembered default may differ until reopen.
- [x] Keep modified-Image warnings distinct from failure to save the project;
      preserve Blender's existing Image-save behavior. The owned Save reports
      modified external Images whose destinations were not written, even when
      Blender returns `FINISHED` and the `.blend` itself saves successfully.
      Installed Blender acceptance covers an unwritable destination.
- [x] Revoke unfinished explicit Bake authority when Save is accepted, retain
      the publication hold until live Bake readers retire, and invoke Save once.
      The adapter test covers waiting for retirement without an early or second
      native Save. Installed interruption/compensation under native faults remains
      part of Phase 7 acceptance.
- [x] Gate Render once and invoke it once; hold Image publication through the
      whole native operation and exact completion/cancel receipt, including
      animation frames. Keep movie output support.
      The owned Blender operators, confirmations, timer wait, one-shot invocation,
      terminal handler receipts, reversible matching user-keymap redirects and
      wrappers for the four agreed File/Render menu entries are present. Direct
      calls to Blender's native operators/scripts can still bypass the gate.
- [ ] Preserve new-format save/load and Undo/Redo controls, ownership and required
      packed-asset validation after native replacement.
- [ ] Exercise explicit Restart through interrupted native work, failed App
      cleanup, helper retirement and fresh ownership without touching the
      preserved pair. The Restart operator and receipt-driven drain controller
      are implemented; installed idle Restart and injected recovery-failure
      retry pass, but active native work and late-handle acceptance remain open.

## Phase 7: acceptance and delivery

- [ ] Pass new numerical, machine, adapter, locale, packaging and installed suites
      with independent source/proof/archive identities.
- [ ] Verify lighting, close/reopen, late callbacks, Retry/Restart, semantic
      preflight, explicit Bake interruption and independent destinations.
- [ ] Verify static Grades with dynamic scene/Image inputs, frame steps, playback
      stop, native animation rendering and movie output.
- [ ] Compare Grade forward, both Stack directions, 33³ preview, 65³ final and
      both Bake evaluators against independent current-reference results. Verify
      Tone Fit UI/domain `[-2,2]`, Color lightness/chroma Fit `[-2,6]`, and full
      reference control names, defaults, labels, units and authored schemas.
      Keep grading appearance at D65 / 203 nits; preserve source-white controls
      and supported working-space choices without exposing unsupported contexts.
- [ ] Match reference entry/export contracts: native Grade retains signed inputs
      without LUT input repair; Stack retains AP1 repair, raw handoffs and ordered
      endpoints. Report inverse reproduction residuals without assuming unique
      roots or claiming a failed search proves unreachability.
- [ ] Verify actual packed static assets, missing-asset rebuild, Save confirmation/
      cancellation/compression, one native invocation, whole-operation Render
      holds, Undo/Redo and crash/restart boundaries.
- [x] Build `//:verify_next`, `//:perceptual_grade_next`, preserved `//:verify`,
      `//:perceptual_grade`, `//:hdr_color_picker` and `//:dctl` together;
      build `5d874421-237c-4540-9721-a2a38d5bd791` passed. This is
      historical build/proof/package evidence before the new unbounded target,
      not a current aggregate pass or full Next acceptance.
- [ ] Complete all Next numerical, adapter, installed, old-source-preservation
      and architecture acceptance checks. Rerun affected old consumers for any
      shared dependency changes; do not transfer old acceptance to the new pair.
- [ ] Record native/platform limits and deliver the new artifact without replacing
      existing aliases or rewriting the supplied project.

Historical checkmarks below apply only to the preserved old pair at their recorded
revisions. They do not complete tasks above or override static Grade behavior.
The historical delivery records remain unchanged.

The standalone node graph's expanded-node budget and known extreme-Web
software-GPU numerical finding are explicitly deferred separate work. They do
not block this Next implementation or delivery and are not considered resolved or
passing by this handoff; preserve their current evidence and status.

## Current audit handoff: 2026-11-01

The active Next delivery is **not complete**. This section records the current
verified state and the remaining Linux/Blender handoff. Do not infer full
workflow correctness from helper or component tests.

### Latest atomicity and proof audit — documentation stop

The user requested a documentation handoff and a stop after this audit. The
implementation work below is **unfinished**. No runtime, Buck or `.inv` fixes
were made during this documentation pass. Earlier runtime edits remain in the
working tree. The unbounded kernel proof passes, but the milestone still lacks
production correspondence, idempotent cleanup and complete installed evidence.

| Latest evidence | Result / build identity | Limit |
| --- | --- | --- |
| Unbounded readiness kernel | 170 obligations and 4 mutations passed; build `e458d854-a0f2-474f-9ee4-e903e6da13b7` | Proves `project_unbounded.py`, not production record conversion or native admission |
| Focused current checks | Invariant 57, core 75, readiness 11, Grade 8, Bake 20, output 19 and inventory 6 passed | Component evidence does not close cross-machine or installed acceptance |
| Recovery / Stack regressions | Recovery 34 had 2 failures; native Stack 9 had 1 failure | Cleanup/reference errors remain; see findings below |
| Packaged Blender 5.2.2 acceptance | Grade boundaries reached; installed smoke failed during Stack setup/reopen | Stack host was unreferenced and disappeared from the saved file; the target is not a pass |

Production now uses the unbounded readiness kernel for every owner count.
Grade and Stack both reject JSON and retained-pointer transaction debt, and
accepted manifests include graph and image-content records. Grade publication
checks prepared pixels through the live controller; ordinary admission compares
installed contents to that accepted manifest. These changes have focused
evidence, but do not close the remaining recovery or installed acceptance gaps.

The earlier binding-only crash fixture stages persistent backing, deletes the redundant JSON marker,
changes one native binding and metadata, saves, and terminates without cleanup.
A fresh process restores the binding/settings and prepares the Grade to `READY`.
This validates recovery from that completed save. The latest fixture reaches
additional Grade boundaries, but fails before completing the Stack matrix.
Neither receipt establishes all structural-swap/commit/cleanup boundaries or
interruption of Blender file serialization. Unsaved edits absent from the file
opened cannot be recovered by this mechanism.

The following findings are confirmed by source inspection and remain unfixed:

| Finding | Implementation location | Required correction |
| --- | --- | --- |
| Partial backup cleanup can strand an owner | `preparation_ledger._discard_backup_images`, `recovery.requeue_prepared_nodes` | Make cleanup idempotent; retain recoverable references and retry without requiring already-deleted backups |
| Structurally valid but incomplete snapshots can still pass recovery validation | `preparation_ledger._validate_tree_snapshot`, `_validate_grade_snapshot` | Require complete independently checkable inventories, including expected binding/link coverage, before any restore effect or ledger retirement |
| Verified in-place Grade commit has no durable field-ledger marker | `updates._install_admitted` | Persist committed/cleanup state; preserve verified content on reopen and finish cleanup idempotently |
| Stack candidate cleanup double-removes Images | `updates._dispose`, `stack_graph.NativeStack.dispose` | Remove each resource exactly once and add a regression for the original failure path |
| Native Stack test fixture omits the owner schema | `tests/test_native_stack.py:56` | Create a valid owner fixture; preserve coverage that invalid owners are rejected; the cleanup exception must not mask the original validation error |
| Installed Stack host disappears on reopen | Installed smoke `runner.py`, Stack setup/save | Retain the synthetic host with a real saved reference or explicit test ownership, then rerun the Stack interruption matrix |
| Native readiness still lacks complete production correspondence at every admission boundary | `project_readiness._validate_grade`, `_validate_stack`, `workflow/project.py` | Preserve the current both-ledger and accepted-content checks, then prove production record conversion, native payload/readback coverage and every Save/Render/Bake admission path |
| Joint Scope/view inventory is not built (10 `.inv` files, 9 targets) | `requirements/scope_view.inv`, Next core `BUCK` | Supply required nonempty invariants and a target for all five properties, witnesses, mutations and packaged validators |
| Legacy four-slot Project proof is not production correspondence | `workflow/project_proof.py`, `workflow/project.py` | Keep production on the unbounded readiness decision and prove its immutable-record projection and native admission correspondence |
| Cross-machine claims are proved only in reduced or unused models | `workflow/composed.py`, `preparation.py`, `recovery_policy.py` | Compose the actual production functions and exact owner/revision/attempt/manifest/retirement receipts |

The 60 canonical IDs are present: **43 partial, 11 adapter premises, 6 open**.
The open scope claims are S09, S10, S14, S16, S18 and S19. Inventory completeness
does not imply theorem coverage. No full canonical requirement is currently
classified `proved` in that crosswalk.

The unbounded kernel now discharges its induction and mutation checks. The
remaining proof work is source correspondence: production `project.py` aligns
owner/evaluator/artifact records outside the proof target, and the preparation,
recovery and composition targets are reduced policy models with no production
call sites. See [proof coverage](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
for the exact evidence and intended proof boundary.

### Selected first complete milestone: readiness and recovery

Implement the delivery described in
[READINESS_RECOVERY_STEP.md](READINESS_RECOVERY_STEP.md).
It spans preparation, compensation, content validation and real output
admission. A passing proof gate is a prerequisite, not its completion criterion.
The current request ends at documentation. Completed kernel and admission
implementation work is recorded below; the complete milestone remains open.

- [x] Extend the milestone specification, canonical design and proof handoff;
      stop after the documentation pass without runtime, Buck or `.inv` changes.
- [x] Repair quantified-helper handling and pass the mandatory arbitrary-length
      kernel proof with independent mutation controls and generated runtime validators.
- [x] Route production readiness for every owner count through the unbounded kernel.
- [ ] Prove conversion of immutable production owner/evaluator/artifact records
      and its correspondence to actual output admission.
- [x] Implement both-ledger rejection and accepted graph/image-content manifests
      for Grade/Stack admission; focused readiness 11 and native Grade 8 pass.
- [ ] Validate accepted Grade/Stack contents and both recovery-ledger forms
      through initial creation, updates, recovery, Save/Render and Bake binding.
      Preserve Stack recipe identity across preview-to-final refinement while
      binding final output to an exact accepted evaluator-content manifest.
- [ ] Retain backing on failed compensation; reject incomplete snapshots before
      effects; make commit/cleanup retirement durable and idempotent; retain
      unresolved cleanup debt.
- [ ] Repair Stack candidate disposal and both Stack fixtures, then rerun the
      failing recovery, native Stack and installed smoke targets.
- [ ] Pass focused/native regressions and the packaged saved-interruption matrix
      for field writes, bindings, metadata, structural swap and ledger retirement.
- [ ] Record fresh proof, runtime, installed and Next/preserved package receipts;
      update this milestone's status without closing unrelated delivery work.

### Broader audit worklist

The selected milestone above groups the readiness/recovery items below into one
complete delivery. The unbounded kernel proof now passes, but production record
correspondence, cleanup durability and installed Stack acceptance remain open.
Joint Scope/view proofs, broader production composition and inventory enforcement
remain subsequent work.

- [ ] Close the remaining readiness and cleanup gaps: validate complete native
      payload/link inventories at every admission boundary, retain backing after
      failed compensation, reject malformed snapshots, and make duplicate cleanup
      idempotent. Regressions must preserve `READY` and unchanged resource IDs
      while injecting missing JSON, changed pixels or links, and failed rollback.
- [ ] Extend packaged crash/reopen tests to field write, bindings, metadata,
      structural swap and ledger retirement. Verify prior committed output,
      failed-repair debt, idempotent fresh reconstruction, and no Bake/Save/Render
      or hidden-Gizmo replay. Use synthetic projects only.
- [x] Make the verifier fail closed for unsupported helper-summary calls under
      quantifiers. Use direct quantified field relations in the readiness proof,
      total first-match lookup, and independent mutation expectations. Do not
      replace induction with bounded enumeration or merely increase timeouts.
- [ ] Prove record conversion into the single unbounded production readiness
      path. Preserve external native discovery/content observations as explicit
      premises.
- [ ] Wire `scope_view.inv` after correcting its missing invariant declaration.
      Prove actual production project/preparation/recovery and Restart relations;
      keep Scope and the supervisor's runtime ownership independent. A copied
      composition model cannot replace this source correspondence.
- [ ] Extend inventory validation to reject orphan `.inv` files and missing
      verification/package dependencies, then reconcile each canonical property
      with actual code and its remaining premises. Do not relabel unproved
      claims as completed merely because their ID exists.
- [ ] Rerun affected Next tests and installed Linux acceptance, then Next and
      preserved proof/package targets after shared verifier changes. Record new
      counts and artifact identities only from successful reports.

The direct focused adapter command is
`buck2 test //products/perceptual-grade-next-blender/tests:scope_runtime //products/perceptual-grade-next-blender/tests:recovery`.
The kernel proof now passes, but the focused recovery and Stack targets still
fail and the installed smoke target fails during Stack setup/reopen. Earlier
aggregate builds and the 493-obligation/27-mutation total below predate this
target and do not certify the current checkout. The old parse error at Next core
`BUCK:31` was corrected before the passing inventory test; it is not the
remaining blocker.

### Earlier verified baseline and remaining delivery matrix

**Verified recovery and output fixes.** `mark_node_dirty()` refuses edits while
any serialized recovery ledger is retained. `requeue_prepared_nodes()` obtains
the field transaction and slots from the persistent ledger if the redundant JSON
marker is missing. The `recovery` target passes 26 tests. The four agreed File
and Render menu actions are wrapped to invoke owned operators; unrelated menu
entries and callbacks remain intact, with redirects removable on unregister.
`output_operators` passes 19 tests. Regressions cover native Save cancellation,
writer exceptions and a readiness-refresh failure while waiting; they verify
the output hold and pending operation are cleared. The owned Save reports
unsaved modified Image destinations independently of project Save success.
`installed_save` passes on Blender 5.2.2: an unwritable modified Image is
reported while project Save succeeds, then a failed Save As to `/dev/null`
returns an error with no pending operation or publication hold and leaves the
saved project intact.

**Earlier focused checks.** `project_readiness` passes 10 tests, including a
five-owner Blender inventory where loss of the fifth owner's backend marker
keeps it required and blocks both Save and Render. `scope_runtime` passes 24
tests and `scope_ui` passes 2; regressions verify last-observed viewport
preference, largest-area fallback, transfer on area removal, rejection of a
late capture from the old view, frame-barrier release only after dependency
updates settle, and mode-aware environment identity that ignores inactive
studio controls. `recovery` passes 27 tests, including injected recovery-Image
packing failure with no orphan Image or active marker. `restart` passes 10 tests, including reuse of
the retained cleanup ledger after a recovery failure. Bake lifecycle passes 20
tests. The focused Next suite passed 12 targets, including 70 core
numerical/workflow tests. `installed_scope_capture` passes on Blender 5.2.2
after frame-barrier, animated-input and source-identity updates; installed Bake
also passes after recovery-backup cleanup changes. The eight
proof targets report 493 obligations and 27 detected/replayed mutations. Final
combined build `5d874421-237c-4540-9721-a2a38d5bd791` passes `//:verify_next`,
`//:perceptual_grade_next` and the preserved root verification/package targets.
Earlier Next package/proof build `d2d4b73f-a869-4607-9bab-88dad11710b3` passes
`buck2 build //:verify_next //:perceptual_grade_next` after the current adapter
changes.

**Installed Linux/Blender evidence.** Six packaged Blender 5.2.2 targets pass:
extension enable/save/reopen plus idle Restart and injected recovery-failure
retry (`installed_smoke`), Shader Image and UV Bake (`installed_bake`),
Compositor Bake (`installed_compositor_capture`), unwritable modified-Image Save
(`installed_save`), Render receipt and publication-hold behavior
(`installed_render`), and viewport capture (`installed_scope_capture`). Bake
tests exercise the registered operator's poll/execute path. The UV fixture
covers 8 target texels and leaves 8 uncovered,
excludes non-owner faces, preserves mesh/material assignments, and retires
recovery backing. The Compositor fixture compares against an independent native
Grade capture, preserves alpha and caller scene state, publishes to the selected
Image, and cancels a changed frozen input without altering the destination.
The same Shader fixture injects route-preflight and post-admission failures:
implicit zero-user targets are removed, while an explicitly selected target
retains its prior pixels. Idle Restart rebuilds the Grade and settles it READY
with six packed fields and preserved authored settings. A one-shot installed recovery failure leaves
Restart retryable; invoking Restart again drains the retained obligation and
recovers the same authored settings with all six fields packed. Render acceptance
checks one native invocation, rejects a wrong-scene and duplicate terminal
receipt, and releases publication holds after exact completion or cancellation.
Scope capture reads a 1048 × 841 viewport
(881,368 samples), returns finite scene-linear RGB statistics and chart data,
and preserves the graph, viewport settings and Render Result. A keyframed
Shader RGB input changes the captured mean between frame 1
([0.05079, 0.05112, 0.06027]), frame 50 ([0.05631, 0.05084, 0.05475]) and
frame 57 ([0.05516, 0.05090, 0.05589]). Playback advances through frames 51–57
without new acquisition or display adoption, then produces a new visual for
the final frame. This acceptance exposed and fixed a stranded frame-evaluation barrier
when Blender had already completed dependency updates before `frame_change_post`.
It does not establish animated Grade-control behavior, coherent
primary/reference batches, or every lifecycle/platform path.

The source fingerprint also now omits inactive studio-light controls in
Rendered mode and Material Preview with Scene World enabled, while retaining
effective engine, lighting and World changes.

**Remaining implementation/acceptance.** Scope needs coherent
primary/reference/environment batches, dynamic-input/native-evaluation
acceptance, and remaining live-service/resource interleavings. Viewport choice
uses last-draw observation as a proxy for last use; camera-only fallback is
unsupported because capture requires a live VIEW_3D area. Bake acceptance still
needs native reader retirement/exclusion, concurrent destination ordering and
broader cancellation/readback interleavings. Also open: formal proof-to-adapter
correspondence and complete owner/evaluator projection evidence, compensation/
readiness interleavings, Undo/Redo and real crash/autosave boundaries, other
Save cancellation/confirmation/compression interleavings, Restart during
interrupted work with late handles or failed cleanup, dynamic
source/playback/animation-render acceptance,
and independent reference/UI/locale/package acceptance. Direct calls to
Blender's native operators/scripts can still bypass the owned Save/Render gate.

An installed Undo probe was attempted but is not passing evidence: Blender's
Undo step reverted the fixture's node owner rather than restoring the tested
Grade control, so the runner was removed. The test setup has not established a
valid native Undo baseline; product Undo/Redo behavior remains unverified.

**Scope and boundaries.** This handoff covers the active Perceptual Grade Next
phases through Linux/Blender acceptance. The separately recorded macOS/Metal
and physical HDR/manual-painting acceptance stays outside this delivery. The
native node graph's expanded-node budget and extreme-Web software-GPU accuracy
findings remain deferred, unresolved work and must not be reported as passing.
Preserve the old core/product, root aliases, and supplied project.

---

# Completed native grading checklist and historical deliveries

Last updated: 2026-10-30

## Completed layout promotion and absolute HDR reassessment — 2026-10-30

- [x] Promote Tone **256**, Color coefficients **8,192** and Compact Adaptance
      **3,072** together; retain Web parameters **4,096**, toes **1,536** and
      fixed boundary **513 × 321**. Scope support for 3,072 to Compact.
- [x] Advance layout schema to **5**, require persistent-tree rebuilds and
      reject obsolete cached payload reuse, including same-settings Tone.
- [x] Correct Tone Fit to **[-2, 2]**, including cached preparation. Update
      current stress cases/endpoints; retain Color fits [-2, 6] and historical
      receipts with their original scope.
- [x] Run the complete **148-case**, three-space, two-context CPU and software
      GPU corpus with 1,024 inputs per row, retaining persistent trees/images
      through edits. Use llvmpipe / EEVEE Shader and FULL GPU Compositor.
- [x] Reconcile all 12 native workers against **444 fresh float64 reference
      replays**, including pinned ACES 2.0 HDR-1000 Rec.2020 / PQ once,
      absolute fractional 10-bit RGB errors and all/excluded extreme scopes.
- [x] Retain unchanged gates, scalar diagnostics, final-RGB failures and
      safety/semantic checks; complete **86 methods across nine Buck2 test
      targets** and publish source-bound evidence.

The [absolute HDR report](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/absolute-hdr-validation.md)
passes **16,940,389 reconciliation assertions**. Excluding alternating
extremes, each backend covers **147 cases / 903,168 pixel samples**:

| Absolute 10-bit HDR error | CPU | Software GPU |
|---|---:|---:|
| Maximum | 7.98566660 | 8.34962157 |
| p99 | 0.00879572 | 0.00896341 |
| p99.9 | 0.10509517 | 0.10648491 |
| Mean pixel peak | 0.00069342 | 0.00070073 |
| Channel RMSE | 0.01007132 | 0.01028189 |

The existing worst ordinary pixel is `source_boundary_0` / ACEScg / 537 / G
in both contexts, where PQ amplifies a small residual near zero. All 888 CPU
final-RGB rows pass. GPU retains only six alternating-extremes failed rows,
with **337.422684 codes** maximum over all cases. Finiteness, containment,
alpha and reference validity pass; CPU/GPU validity and saturation flags
match. Tone passes all 31 distinct scalar functions and Web parameters all
19. Raw diagnostic failures remain for Color **7/78**, toes **16/16** and
Compact **3/11**; the scalar audit's raw overall result remains failed.

Current payload is **5,076,560 bytes**, or **2,441,792** excluding the shared
fixed boundary. Tone256's production image is 512 × 1 / 8,192 bytes. The
[completion receipt](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/completion.json)
binds current source, raw runs, independent validation and regression tests.
Earlier schema-4 timing/sensitivity receipts below remain historical; no
performance timing was inferred from this accuracy run.

## Historical schema-4 sensitivity from then-current sizes — 2026-10-30

- [x] Document current-only baselines and independent reductions before work.
- [x] Evaluate lower Tone, Color, Web parameter/toe, Compact and boundary sizes
      against current schema 4; leave runtime dimensions unchanged.
- [x] Compare all 149 cases, three spaces and both CPU contexts through the
      reference HDR/PQ path; retain final-output/flags checks and raw failures.
- [x] Check representative and extreme controls on software GPU and reconcile
      retained pixel arrays independently.
- [x] Measure candidate generation without concurrent accuracy work and
      publish the current texture/time breakdown plus sensitivity table.

The [combined report](../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/breakdown.md)
has 12 independent current-to-smaller layouts, 11,622 CPU rows and 1,326
software-GPU subset rows. Independent reconciliation passes 75,983,224 CPU
and 8,989,366 GPU assertions; all six new Buck2 helper checks pass. Isolated
generation timing retains 300 samples. Current payload stays 5,428,848 bytes.

Required Tone scalar and smaller-boundary radius failures remain visible;
toe 768 and both reduced boundaries retain final-RGB findings. The existing
GPU alternating-extremes baseline failure reaches 337.422684 HDR codes in
six rows, before resizing. Safety checks pass and validity/saturation flags
remain unchanged. No smaller runtime size or admission-policy change was made.

## Completed Compact-only Adaptance — 2026-10-30

- [x] Document the user-directed single representation before source changes:
      always use Compact at 8,192 cells; remove Interior and its gain/tail
      selection from runtime preparation and both graph builders.
- [x] Remove Interior payload, update bindings and reuse/migration validation,
      and advance the fixed layout schema. Preserve analytic Compact tails.
- [x] Update reports and regression checks to model one Adaptance texture;
      keep historical receipts scoped to the preceding dual-table source.
- [x] Verify ordinary and strong controls on specialized and persistent paths,
      including HDR worsening against reference and the frozen dual-table
      baseline. Keep raw local diagnostics and required safety/semantic gates.
- [x] Refresh uncontended preparation and software-GPU/Eevee prepared-edit
      timings and publish measured payload/time/accuracy results. Measured
      payload: 5,428,848 bytes including boundary, 2,794,080 without it.

All 90 regression checks pass. The complete 894-row CPU comparison passes,
independently reconciled by 32,668,186 assertions and 447 float64 reference
replays. Maximum added HDR error is 0.0000304877758 codes /
0.0000156437481% reference peak; 36 software-GPU strong-control rows also pass
with the same added-code maximum and 0.0000208583307% maximum percentage.
All semantic flags remain unchanged. Fresh preparation is 37.885 ms all-active
with Compact generation 2.225 ms. The [current breakdown](../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/breakdown.md)
retains all software-GPU edit phases and diagnostic limits. Both local suites
retain 12 raw Compact precision failures as diagnostics; required safety and
sign checks pass. Persistent nodes are 1,445 Shader / 1,382 Compositor, still
above the original cap; the historical software-GPU extreme-Web finding and
Next product integration remain open separately.

## Historical completed Color-coefficient and Compact Adaptance sizing — 2026-10-30

- [x] Measure Color coefficient and Compact Adaptance candidate generations
      over four preparation cases × five repetitions without concurrent heavy
      work in the isolated `_generate_field` candidate study. Color 16,384
      takes 8.091 ms all-active and 9.176 ms worst case median; every sample is
      below 10 ms in that harness. Compact 8,192 halves payload to 131,088
      bytes and takes 2.225 ms all-active.
- [x] Complete full scalar audits (78 Color functions; 11 Compact functions)
      and the matched 149-case CPU HDR comparison against Color 131,072 /
      Compact Adaptance 16,384, with current Web 4,096 / toe 1,536.
- [x] Rerun identical-float32-handoff local-stage comparisons. Color 16,384
      passes local stage metrics in all 36 measured rows but has 18 scalar-fail
      rows; Compact 8,192 has 8 local opponent precision failures among 18
      measured rows, maximum `1.22195872e-5` against `1e-5`.
- [x] Record the user-authorized 0.05-code maximum added-HDR-error admission
      policy to Color coefficients and Compact Adaptance only. Scalar/local
      precision remains diagnostic for these two roles; safety, final RGB,
      containment, semantic flags and node-budget checks remain active.
- [x] Select measured Color 16,384 and Compact Adaptance 8,192 candidates.
      The user explicitly confirmed Compact Adaptance 8,192. Together with
      current Web 4,096 / toe 1,536, resident field payload is 6,477,552 bytes
      (37.0% below the earlier 10,279,104 bytes).
- [x] Set fixed runtime Color / Compact layouts to 16,384 / 8,192 under layout
      schema 3 and implement their scoped HDR admission policy.
- [x] Refresh uncontended, source-stable host-preparation timing over 20 runs.
      Color generation medians are 8.146–9.136 ms across four cases; the
      maximum individual sample is 11.786 ms. All-active Compact generation
      is 2.232 ms and complete preparation is 43.838 ms. Component and complete
      measurements are separate; native upload and evaluation are excluded.
- [x] Verify reuse/migration checks reject obsolete Color, Compact, Web and toe
      dimensions, preserve matching-layout reuse and produce current pixels.
      Existing fixed-layout trees must be rebuilt to adopt new dimensions.
- [x] Rerun native and persistent regressions: all 63 checks across seven
      Buck2 targets pass. Both local-stage suites retain four raw Compact-only
      precision failures as diagnostic; strict-required metrics and safety pass.
- [x] Pass all 24 focused synthetic HDR runner/admission/merge checks.
- [x] Complete the current fixed-layout scalar audit over all Color 78, Web
      parameters 19, toes 16, Compact 11, Interior 11 and Tone 32 distinct
      functions. Retain two Color and 16 toe raw precision failures as
      authorized diagnostics; the other fields pass their scalar policies.
- [x] Independently validate all current persistent HDR/safety/flag gates:
      894 baselines and 2,682 measured candidate rows, 149 cases × three spaces
      × two contexts × 1,024 samples. Color adds at most 0.0115159237 codes /
      0.00529889482%; Compact adds 0.00128048658 codes / 0.000361764104%;
      combined matches the Color maximum. All pass the 0.05-code layout budget.
- [x] Refresh current software-GPU prepared-edit timing: 30 rows at 16²,
      initialization/entry separated from repeated updates, 254 requested
      threads. Exposure repeated end-to-end is 433.792 ms Shader / 103.226 ms
      Compositor; this is not full-resolution preview latency or Grade-only
      per-frame rendering cost.
- [x] Publish the combined texture/time/sensitivity breakdown. Label unchanged
      field sensitivities and full-resolution preview timings historical;
      retain the software-GPU extreme-Web and expanded-node findings separately.

The current [breakdown](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/breakdown.md)
and [independent HDR validation](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/hdr-validation.md)
record the completed promotion. All **87 checks across eight Buck2 targets**
pass; final RGB, containment and unchanged validity/saturation flags pass in
all current persistent CPU HDR rows. Baseline and combined maximum absolute
reference error both remain 7.9856666 codes. Color and combined retain 18 raw
scalar-failure rows; native local suites retain four Compact-only precision
failures each as authorized diagnostics. The earlier specialized full-field
Compact zero movement is historical and was not used for current admission.
The [complete current scalar audit](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/scalar-fixed/report.json)
is separate from representative regression diagnostics.

**Status: reduction, runtime promotion, migration, CPU HDR validation,
regression and current preparation/prepared-edit timing are complete.**
The original expanded-node budget remains unmet: Compact/combined now have
1,468 Shader / 1,399 Compositor nodes, seven below the baseline with no new
budget-failure rows. The retained software-GPU extreme-Web issue and Next
integration remain open. Receipts are under
`buck-out/persistent-grade-evidence/color-compact-promotion-20261030`.

## Historical completed Web-parameter promotion — 2026-10-30

The completed receipts below use 131,072 Color cells and 16,384 Compact
Adaptance cells. Their source hashes, payloads and timings retain that older
scope after the Color/Compact promotion.

- [x] Set the runtime Web-parameter layout to the authorized 4,096 cells.
- [x] Verify full-field dimensions/payload and reject obsolete 32,768-cell
      preparation reuse while preserving current-layout reuse. The current
      payload is 10,279,104 RGBA32F bytes; the migration checks pass.
- [x] Rerun native scalar/local/full/persistent regressions and record retained
      numerical and construction failures separately. The focused preparation,
      full, persistent and persistent Color suites pass; the expanded node cap
      remains an inherited failure.
- [x] Rerun the CPU source-bound HDR evaluation for 4,096 parameters with 1,536
      toes against an explicit 32,768-parameter / 1,536-toe baseline: 149 cases,
      three spaces and both contexts. The receipt has 894 baselines, 90 measured
      candidate rows and 804 inactive rows; both measured contexts pass final
      RGB and containment, with 21 node-budget failures retained.
- [x] Include maximum added codes and percentage of reference peak in generated
      sensitivity tables; fill retained toe 1,536/1,280 percentages and correct
      the Interior Adaptance 32,768 movement-versus-worsening mix-up.
- [x] Complete the equivalent software-GPU HDR corpus and classify its existing
      near-neutral failure separately from the CPU result: six final-RGB
      failures in each of baseline and candidate; no flag/containment changes.
- [x] Refresh clean preparation, persistent edit and software-GPU timing reports,
      then update evidence, totals, gates and the user-facing breakdown.

**Status: the promoted layout, migration checks, both full HDR comparisons,
78 checks across nine Buck2 targets, and the clean 4,096-cell timing refresh
are complete. The known software-GPU extreme-Web numerical failure and the
expanded-node cap remain open; Next product integration is deferred.**

The current [HDR summary](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/hdr-summary.md)
records maximum added error of 0.0404496565 codes / 0.122978849% on CPU and
0.00974084437 codes / 0.122460364% on software GPU. The clean
[timing aggregate](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/timings/aggregate.md)
validates 960 matching draws, 120 superseded occurrences, no missing draws,
30 prepared-edit rows, 18 processes / 144 benchmark renders and 20 preparation
measurements. Resident fields total 10,279,104 bytes; all-active preparation is
102.35 ms and Web parameters take 11.84 ms. The retained toe percentages are
0.151449259% at 1,536 cells and 0.103094441% at 1,280 cells.

## Historical software-GPU timing rerun — 32,768 parameters

- [x] Re-run the prepared 1024×1024 displayed-preview report on Mesa llvmpipe:
      Eevee for Shader, GPU Compositor for Compositor, every one of the 16
      scenarios, three fresh sessions per context and ten steps per scenario.
      Require 960 matching draws, 120 explicitly superseded burst occurrences,
      and zero missing draws across the six sessions.
- [x] Request all 254 CPUs available to native Blender/Mesa work, record CPU
      affinity and requested/effective thread counts, and preserve the Mesa
      25.0.7 limit of 32 threads per llvmpipe worker pool. Keep OpenBLAS
      single-threaded to avoid nested NumPy pools.
- [x] Re-run the persistent prepared-edit diagnostic at 16×16 pixels: five edit
      families, three repetitions and both contexts (30 rows), recording
      preparation, persistent apply, native evaluation and readback separately.
- [x] Re-run the image-sized native benchmark at 1024×1024 for both contexts,
      all three variants (passthrough, Linear + Tone and full guarded 1D Web),
      three fresh processes per variant/context and seven warm renders per
      process (18 processes, 144 renders). Record the backend and thread policy.
- [x] Keep the four-case/five-repeat portable texture-size and preparation
      report separately identified as host-only preparation; rerun it separately
      when refreshing that breakdown, without concurrent heavy timing work.
- [x] Reconcile source-bound reports, exact commands, backend/device, host
      affinity, Mesa thread cap, AOV reconstruction scope and limitations into
      the active goal and evidence after all measurements finish.

The [validated aggregate](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/aggregate.md)
confirms all 960 matching draws, 120 superseded burst samples, zero missing
draws, 30 prepared-edit rows, 18 benchmark processes / 144 renders and matching
current source/resource identities. The sequential launcher also completed the
20-measurement host-only preparation report. Repeated Exposure p50 / p95 is
693 / 748 ms Shader and 206 / 220 ms Compositor; complete host preparation is
184.764–195.257 ms with 24,960,704 resident bytes.

Numerical acceptance is failed: 60 `web_stress` rows exceed the unchanged
`1e-4` RGB limit; maximum error is `1.9390252628269624e-4`. Both contexts
reproduce it, including the GPU Compositor path without AOV transport.

- [x] Isolate the finding with same-engine Cycles CPU/GPU Compositor renders,
      matching 1024² input, settings, and both current/original toe layouts.
      At the 32 GUI probes CPU peaks at `9.59719435e-5` and GPU at
      `1.93317162e-4`; restoring the original toe does not change either peak.
      GPU Compositor alone reproduces the failure without Eevee or AOV
      transport. File/readback reconstruction differences are zero.
- [x] Complete focused GUI-summary, native-fixture and persistent regressions
      after timings; all 15 tests pass.

The unmasked exploratory million-pixel scan in
`buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/report.json`
reports raw maximum normalized errors `0.0300431` CPU and `0.1799924` GPU,
beyond the existing 32-probe acceptance. Its independent scalar/batch review
confirms all 35 retained worst/probe witnesses are valid and well-conditioned;
the larger errors cannot be dismissed as invalid input or response-pole
comparisons. These diagnostic maxima show that sparse probes do not certify
image-wide accuracy. Keep the timing acceptance result separate:
the software-GPU timing receipts are complete, and the GUI numerical gate still
fails for 60 `web_stress` rows.

- [ ] Diagnose and resolve the expanded extreme-Web accuracy finding, including
      CPU errors missed by the existing probes and additional GPU differences;
      retain the completed timing receipts and unchanged accuracy thresholds.

## Audit follow-up — 2026-10-30

- [x] Document user-authorized Web-toe admission by maximum signed HDR worsening
      of 0.05 codes against an explicit 524,288-cell baseline. Toe scalar/local
      precision becomes diagnostic; retained safety/final-output gates and other
      fields' accuracy policies remain authoritative.
- [x] Measure all eight toe candidates from 256 to 2,048 cells in 256-cell steps
      over 149 cases, 1,024 pixels, three spaces and both CPU native contexts;
      retain complete scalar/local/seam diagnostics and rejection witnesses.
- [x] Promote the smallest candidate satisfying HDR and retained checks; guard
      stale-size preparation reuse and preserve persistent image dimensions.
- [x] Run focused Buck2 and native/persistent regressions, verify the promoted
      layout against the original baseline, and refresh source-bound receipts.
      All 11 focused targets pass. The promoted verification repeats 894
      baselines and 894 candidate rows, retains maximum signed worsening
      `0.0393597186` codes and has no validity/saturation changes. The selected
      local/seam report has zero safety failures across 14 comparisons; raw
      scalar/local precision failures remain diagnostic.
- [x] Re-run all texture sizes and four-case/five-repeat preparation timings
      without concurrent heavy work; report byte savings and maximum worsening.
      The [clean report](../../buck-out/persistent-grade-evidence/toe-hdr-005/preparation-costs-final/report.md)
      records 24,960,704 resident bytes, 24,592 toe bytes, 99.7069% toe savings,
      2.122–2.149 ms toe generation and 186.180–192.829 ms complete preparation.
      Timing JSON SHA-256 is
      `cbc240a1226fb77444e95705f5c16a4102ad31c6515d5c828c74a98aaf4003fd`.
      The [aggregate receipt](../../buck-out/persistent-grade-evidence/toe-hdr-005/summary.md)
      links verification, tests and diagnostics. The inherited node cap remains
      an open requirement.

The completed items below retain the layouts and policies of their receipts.

- [x] Add the pinned OCIO HDR end-to-end code-value sensitivity report. Compare
      reference/current/reduced native outputs after the ACES 2.0 HDR-1000
      Rec.2100-PQ view, retain fractional full-range 10-bit codes, and report
      absolute error, candidate movement and signed worsening.
- [x] Run the report over all 149 retained cases, three scene spaces and both
      CPU native contexts for every agreed helper-texture halving, including
      diagnostic Tone/boundary candidates and the combined Web candidate.
- [x] Keep near-black percentage denominators explicit, preserve complete
      worst-pixel witnesses, pin the OCIO/Buck provenance, and leave shipped
      layouts and existing gates unchanged.
      The merged report has 894 baselines and 30,396 candidate rows (8,286
      measured, 22,110 inactive); its JSON SHA-256 is
      `41692459fffffa36b2c99eeeef9b3810da1818a7740376abe2a4ea920466a856`.
      It records 256 final scene-linear failures, 678 node-budget failures and
      3,744 scalar-field failures among measured candidates. See the measured
      [report](../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/report.md)
      and [sensitivity table](../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/sensitivity.md).

- [x] Rerun the fixed-field audit over all 149 retained cases with stable sources;
      keep runtime Color `131072`, Web parameters `32768` and Web toes `524288`
      cells, with smaller candidates retained as failure witnesses.
- [x] Complete the source-stable native Web candidate sweep: 48 comparisons
      retain local field failures while passing the final RGB check.
- [x] Rerun the full 102-row CPU report: numerical acceptance passes and the
      original node-budget acceptance remains failed.
- [x] Record the coherent 4,656-row sensitivity report without changing any
      production gate.
- [x] Rerun the prepared fixed-layout texture-size and preparation-time report
      without concurrent CPU-heavy work; record the source-stable 20-measurement
      receipt, 33,325,744 resident bytes and complete-preparation medians of
      0.859065–0.876255 seconds.
- [x] Apply the user-authorized `1e-4` allowance to both Web-toe scalar errors
      for the alternating-extremes sizing experiment; retain ordinary gates.
      Complete the `65536` audit and the `32768` through `2048` sweep: `32768`
      is the smallest passing supported scalar grid across all 16 retained toe
      functions; every smaller supported grid has a complete failure witness.
- [x] Validate the `32768` candidate in 12 native final-RGB comparisons and
      measure 40 alternating-order paired preparation runs. Toe generation is
      about 36 ms, complete preparation 221–229 ms and candidate resident payload
      25,460,464 bytes. Record this as a candidate study; runtime stays `524288`.

- [x] Apply the same `1e-4` allowance only to the exact alternating Web case:
      Web-parameter conditioned/absolute-log and Web-toe conditioned/relative
      scalar errors, plus Web local H/opponent/energy and returned-scale gates.
      Keep ordinary, non-Web, output, containment and node-budget gates intact.
- [x] Complete the Web-parameter sweep and native local/seam check: `4096`
      parameter cells with `32768` toe cells passes; `2048` parameter cells
      fails both scalar absolute-log and native local/scale checks. Runtime
      dimensions remain unchanged.
- [x] Implement the exception in development audits and native tests only;
      require complete audit traversal, preserve ordinary/control and non-Web
      thresholds, report effective limits, and keep runtime layouts unchanged.
- [x] Run focused policy, preparation, scalar-tool, native and persistent-stage
      checks; measure the combined candidate texture and preparation breakdown.

Receipts and limitations are linked from [EVIDENCE.md](../../libraries/perceptual-grade-nodes/EVIDENCE.md)
and the gate policy analysis in [GATE_REVIEW.md](../../libraries/perceptual-grade-nodes/GATE_REVIEW.md).

## Persistent lifecycle checklist

- [x] Record fixed production layouts, development-only sizing/accuracy audits,
      full prebuilt topology, neutral wiring bypass and same-tree guarded edits.
- [x] Separate fixed-grid runtime generation from explicit accuracy audits;
      certify per-role sizes with smaller-candidate witnesses and source receipts.
- [x] Implement dependency-aware update preparation without audit calls or
      regenerating downstream fields during Linear-only changes.
- [x] Prebuild all stage/family/safety paths and all fixed-size helper images;
      preserve their identities and dimensions across every edit.
- [x] Apply revisions under caller-provided native-reader exclusion with exact stale rejection,
      complete-state rewiring, rollback and explicit failed-owner state.
- [x] Validate initialization, neutral/active transitions, active downstream
      stages, safety routes, rapid revisions, rollback and packed reopen.
- [x] Pass retained scalar/field/local/native numerical gates on fixed layouts;
      count dormant nodes and keep original node-budget failure visible.
- [x] Record actual matching GUI draw latency with initialization separated,
      first activation, p50/p95 and superseded/undrawn sample accounting.
- [x] Reconcile runtime/API, field specification, source-bound evidence and Next
      ownership/publication documentation with measured results and limits.
- [ ] Reduce persistent expanded graphs below 1000 nodes and restore strict
      construction admission without changing equations or accuracy gates.

The [current evidence](../../libraries/perceptual-grade-nodes/EVIDENCE.md) includes
six 1024×1024 GUI sessions: 960 matching draws, 120 superseded occurrences and
zero missing samples, with stable source and resource identities. Persistent
graphs retain 1,499 Shader / 1,430 Compositor expanded nodes.

The checks below belong to earlier source snapshots and do not certify the
persistent implementation or fixed layouts.

---

# Previous build-time boundary resource and 1D-only Web handoff

Last updated: 2026-10-29

**Status: the two-change handoff is ready. All 57 tests and six numerical reports pass; original full-grade node-budget acceptance remains open.**
The active contract is in [GOAL.md](GOAL.md). Earlier checked deliveries below
retain their original 2D-enabled source scope.

- [x] Record the requested build-time boundary asset, complete 2D Web removal,
      and the user's temporary authorization to construct oversized 1D graphs.
- [x] Add an acyclic Buck2 boundary generator/resource/runtime packaging chain;
      preserve geometry, correction and numerical gates.
- [x] Replace runtime geometry generation with immutable resource loading;
      validate context/schema/data and fail explicitly without regeneration.
- [x] Remove all 2D Web APIs, preparation, native branches and fallback retries;
      preserve 1D fields and generic boundary texture sampling.
- [x] Allow oversized complete graphs temporarily while retaining exact expanded
      counts, separate numerical/budget results and combined acceptance failure.
- [x] Validate deterministic generation, invalid-resource rejection, private
      relocation, no-Blender loading and the generated asset's evidence identity.
- [x] Re-run 1D local/seam/saturation, isolated guards, ownership/save-reopen and
      raw/full numerical checks without reducing the required corpus.
- [x] Record current node counts, over-budget cases, resource sizes and separate
      generation/loading/preparation/construction/evaluation timings.
- [x] Reconcile root, library/API/evidence and Next handoff documentation with
      exact artifacts, reproduction commands and unresolved failures.

The next developer must complete the following after this handoff:

- [ ] Optimize the full 1D graph below 1000 expanded nodes in both contexts,
      preserving all accepted equations, settings and numerical gates.
- [ ] Restore strict rejection of oversized complete graphs and its cleanup test.
- [ ] Pass the complete source-and-asset-bound numerical, node-budget, resource
      and native acceptance suite; distinguish software GPU coverage from hardware.
- [ ] Refresh performance measurements after optimization and assess actual
      interactive preparation/update costs separately from render transport.

Current receipts include 57 passing tests, six numerically passing reports and
the 18-process / 144-render benchmark. The full CPU/UI/GPU reports retain combined
acceptance failure solely on the node cap; maxima are 1083 Shader / 1025
Compositor. Exact receipts and the four offending grade cases belong to
[EVIDENCE.md](../../libraries/perceptual-grade-nodes/EVIDENCE.md).
Do not carry the earlier 53-test/six-report pass or 998-node maximum forward as
acceptance of the 1D-only implementation.

---

# Historical delivery: native grading with the 2D Web option

Last updated: 2026-10-29

**Status: complete; numerical/native acceptance and performance evidence are recorded.** The active contract is in [GOAL.md](GOAL.md).

- [x] Read the monorepo ownership, existing goals/checklists and Stage 1–2 evidence;
      agree the complete Stage 3, guard, helper-texture and saturation contracts.
- [x] Re-run the existing 11 preparation tests before changing implementation.
- [x] Add portable Color/Web settings, preparation and independently validated
      coefficient/geometry fields, preserving independent Tone/Color Fit ranges.
- [x] Implement frozen drivers, stable carried energy, tonal web, selective
      Adaptance and final scale as reusable native stages.
- [x] Implement direct H–K repair and decoder-validated AP1 boundary projection;
      all five isolated native/preparation guard tests pass, including returned
      radius and pole-margin diagnostics after neutral fallback.
- [x] Integrate full guarded/default and explicit raw wrappers, finite saturation
      diagnostics, alpha, independent resources and packed save/reopen.
- [x] Pass each Color substage at identical float32 inputs under `1e-5`, report
      accumulated raw Color error separately, pass boundary `2e-5`/containment gates and
      complete guarded `1e-4` RGB comparisons, including saturation cases.
- [x] Keep fully active Shader/Compositor graphs below 1000 expanded nodes and
      retain isolated Stage 1–2 regression budgets.
- [x] Pass preparation/reference/native/ownership/architecture tests, required CPU
      acceptance and available GPU checks; identify untested platform coverage.
- [x] Record reproducible errors, worst cases, saturation, node/resource costs,
      preparation/build time and image-sized cold/warm native timings.
- [x] Reconcile README/API/example/evidence and future Next handoff documentation;
      record final source-bound results without changing old products or Git.

All 53 tests, six end-to-end reports and the 24-process image benchmark pass.
Final identities, the isolated Color timeout/retry, performance variability and
available GPU coverage are recorded in
[the evidence](../../libraries/perceptual-grade-nodes/EVIDENCE.md).

---

# Completed delivery: reference Stage 3 saturation crossover

Last updated: 2026-10-28

**Status: implementation complete; affected reference/product checks pass.** The active contract is in [GOAL.md](GOAL.md).

- [x] Record the agreed 35/75 ratio, signed symmetry, reference-only scope and
      accelerated support boundary before implementation.
- [x] Implement capacity-independent low/high drivers in float64 and scaled
      reference paths, preserving frozen post-Tone sampling and other equations.
- [x] Reject affected reference BakeStack grades explicitly before preparation;
      retain accelerated execution for controls whose equations are unchanged.
- [x] Add verification-only legacy adapters and preserve core/Blender/DCTL tests,
      inverse-baking coverage and offline product analysis without runtime changes.
- [x] Update active reference mathematics/plots and scope historical capacity
      experiments and production proofs accurately.
- [x] Pass reference mathematical/inverse/Stack/CLI and accelerated support tests,
      affected product verification, architecture and Linear + Tone regressions.
- [x] Record final test evidence and remaining accelerated/native Stage 3 limits in
      [`libraries/perceptual-grade-reference/CROSSOVER_EVIDENCE.md`](../../libraries/perceptual-grade-reference/CROSSOVER_EVIDENCE.md).

The broader GPU baking suite still has an unrelated stale `sampling.sample_image`
test failure. All changed oracle comparisons pass, including the focused GPU run;
the linked evidence records the failure and Linux/llvmpipe coverage explicitly.

---

# Completed delivery: native Linear + Tone node experiment

Last updated: 2026-10-28

**Status: implementation complete; Linear + Tone acceptance passes.** This is completed work
specified in [GOAL.md](GOAL.md). The Next handoff below is deferred and preserved;
its unchecked milestones are not prerequisites for this independent experiment.

The agreed **maximum Fit 3 with Quintic 512** is implemented. Dense measurements
pass (`8.2532e-6` worst across 932 comparisons over 233 distinct UI-valid anchor
sets); Fit 4 exceeds the `1e-5` gate. The final 348-case UI CPU report and
optional GPU report pass against the revised mapping. See
[`libraries/perceptual-grade-nodes/EVIDENCE.md`](../../libraries/perceptual-grade-nodes/EVIDENCE.md).

## Ownership and interfaces

- [x] Record the settled standalone-library scope, numerical gates, stage budget
      and future integration boundary before continuing implementation.
- [x] Add independent `perceptual-grade-nodes` component/bundle and local Buck
      test/evaluation/report targets; leave Git and existing product aliases alone.
- [x] Implement immutable reference-schema LinearSettings/ToneSettings and
      host-independent preparation without reference/old-core runtime imports.
- [x] Expose separate Linear, appearance, Tone and decode builders plus a complete
      RGB wrapper; retain post-Tone appearance/J_A/energy for future Stage 3.
- [x] Return explicit caller-owned trees/images/helpers; clean up partial builds;
      add no registration, UI, global cache, actor, timer or handler.

## Compact native mathematics

- [x] Implement full linear controls and XYZ override, D65/203-nit behavior, and
      Rec.709/Rec.2020/Bradford-adapted ACEScg endpoints.
- [x] Implement modern signed modCAM16/Tone without legacy neutral lift/subtract,
      input repair, output guards or input fallback.
- [x] Use constant folding, matrix composition, shared expressions, compact exact
      eccentricity and retained opponent responses to avoid redundant conversion.
- [x] Build shared-jet quintic residual tables with analytic tail/endpoint and
      reference black/Highlights behavior; validate quantized 512 cells against
      dense scalar error <=1e-5 and monotonicity or fail clearly; cap Fit at 3.
- [x] Pack float32 coefficient images with nearest sampling, Non-Color,
      channel-packed alpha, 512-wide packing and no half precision.
- [x] Preserve alpha and identity behavior; expose Decode Valid/Pole Margin,
      finite black on invalid decode, and reusable unmodified appearance outputs.
- [x] Keep each complete two-stage Shader/Compositor wrapper at <=300 expanded
      nodes, aiming for <=200; reserve the remaining <1000 total budget for Stage 3.

## Independent verification and delivery

- [x] Compare settings/matrices, scalar curves, intermediate appearance and raw
      output against the independent reference with entry/export guards disabled.
- [x] Cover signed HDR through +/-1024, all controls, matrix overrides, three RGB
      spaces, minimum-gap knots, fits -2..3, multiple peaks, neutral/black/reset and alpha.
- [x] Enforce normalized RGB error <=1e-4 for reference response magnitudes <=300;
      separately report valid near-pole errors, invalid cases and validity mismatches.
- [x] Verify the 512-cell table and explicit rejection, float32 interpolation,
      monotonicity and continuity, with no 3D LUT or Python pixel evaluator.
- [x] Pass native Blender 5.2.2 Cycles CPU and full-precision Compositor CPU;
      exercise available Eevee/Compositor GPU and identify unavailable coverage.
- [x] Verify independent instances, partial-failure cleanup and packed save/reopen
      without extension registration; test ownership/import boundaries.
- [x] Deliver a scripted example and reproducible JSON/Markdown report with error
      distributions/worst cases, node counts, table memory and preparation/native
      timings. Record measured evidence and remaining limits before completion.

---

# Previous delivery: Bake input interruption and saved editor controls

Last updated: 2026-10-27

**Status: complete; verification and installed acceptance pass.** New projects and
corrected saves are the acceptance boundary; existing empty nodes are not repaired.

- [x] Record explicit editor-wrapper type and original dependency-driver state
      during portable save conversion; preserve canonical Grade and Image pointers.
- [x] Restore marked current wrappers in a bounded recovery phase, with exact
      generation/owner receipts, rollback and retry; preserve adopted native output.
- [x] Update the recovery automaton, `.inv` requirements and source-bound inventory.
- [x] Make each Bake observe its target and exact effective upstream inputs;
      cancel itself after a semantic change without upstream cancellation fanout.
- [x] Cover Grade selector identity, parameters, Stack changes, source/link edits,
      grading change/revert, and relevant native/UV/frame dependencies.
- [x] Keep names/layout/selection, unrelated graphs, generated LUT updates and
      unused live grading behind baked outputs outside invalidation.
- [x] Recheck freezing, queued/running/staged requests and final publication;
      preserve the previous Image and physical leases until retirement.
- [x] Require an explicit Bake retry and show localized input-change status.
- [x] Pass focused policy, Blender, lifecycle/recovery, locale and packaging tests.
- [x] Pass installed Shader/Compositor cancellation and fresh save/reopen checks,
      including actual controls/tooltips, nonempty selections and Undo/Redo.
- [x] Pass root verification and both extension package gates; record final ZIP,
      source/archive identities, test counts and unchanged user-project hash.

Validation is complete: 23 unique test targets cover 263 distinct Python cases.
Final installed checks cover Shader/Compositor controls, selections and tooltips
through save/reopen, Grade-change interruption, previous-image preservation,
Undo/Redo, playback, output resources, crash/restart and native-copy interruption.
Root `//:verify //:perceptual_grade //:hdr_color_picker` passes in build
`5ce714b7-822b-44aa-9947-7466dcda94e5`; all 24 source-bound machine proofs pass
2,702 obligations, 215 mandatory properties, 68 witnesses and 72 replayed mutations.
The retained Lean color-model checks also pass. Generic Invariant sources are unchanged.

Final ZIP: `buck-out/bake-controls-validation/perceptual_grade.zip`.
SHA256: `1cbeac27cd9b6c89a399cb97fcad0adebc972ec0741cdd9aa0eb7f2481a1cba6`.
Exact build/test identities, source and archive hashes, package/proof reports and
installed JSON reports are in `buck-out/bake-controls-validation/summary.json`
and `validation-index.json`. Counts exclude repeated runs and subtest variants.
Installed acceptance used Linux Blender 5.2.2 with virtual GUI/software rendering;
macOS/Metal is not claimed. The supplied `train-model.blend` remains unchanged:
`51f761e91dc23b1bfab8225b1842b27f54e52bcaf6670e3706565b92802be789`.

---

# Automatic scopes and predictable Blender controls

Last updated: 2026-10-26

**Status: complete; verification and installed acceptance pass.** This section supersedes
older manual refresh, playback publication and compatibility behavior below.

- [x] Use native Bake Image create/select/rename/unlink UI and a separate Bake row.
- [x] Rename Baked Vector to Vector; keep matrix/selector/LUT sockets private.
- [x] Preserve public socket hide flags and selected Image through save wrappers.
- [x] Remove scope refresh controls and schedule automatic source demand.
- [x] Pause acquisition/publication during playback; wait for true native completion.
- [x] Retain one immutable acquisition plus newest pending demand; publish compatible
      completed snapshots progressively during edits using latest analytical values.
- [x] Freeze coherent primary/reference inputs and exact upstream Grade payloads.
- [x] Exclude UI-only and unrelated changes from acquisition identity.
- [x] Disable unsupported Bake routes with corrective hover text and scheduled preflight.
- [x] Contain public callback failures as localized outcomes with diagnostic logging.
- [x] Remove migration paths while preserving current-format recovery and Undo.
- [x] Complete affected unit, proof, native and installed GUI acceptance.
- [x] Pass root verification and both extension package gates.
- [x] Record final ZIP, evidence and unchanged user-project hash.

Validation is complete: 42 targeted suites cover 622 distinct Python test cases,
with no unresolved failures. Final installed acceptance includes Shader/Compositor
Bake, all three scope pages, playback stop, native capture, save/Undo, crash/restart
and 12 actual native-copy interruption checkpoints. The root build
`//:verify //:perceptual_grade //:hdr_color_picker` passes in
`129fe117-c091-4faa-ae7e-5334c01a03bb`. All 24 source-bound machine proofs pass
2,674 obligations, 213 mandatory properties, 67 witnesses and 71 replayed mutations;
the retained Lean color-model checks also pass.

Final ZIP: `buck-out/automatic-scope-validation/perceptual_grade.zip`.
SHA256: `41b66a53404ebf0be99229012fb81f59ef060bce43faf66cfd4b34cd988c0cf6`.
Evidence, exact test/build identities, package/proof reports and installed JSON
reports are in `buck-out/automatic-scope-validation/summary.json` and
`validation-index.json`. Counts exclude repeated runs and subtest variants; the
Bake suite's final coverage combines 56 cases with its focused native replay case.
Native acceptance used Linux Blender 5.2.2 with virtual GUI/software rendering;
macOS/Metal is not claimed. The supplied `train-model.blend` remains unchanged:
`4a6fa6569398d058dab073eaa254c8701409f71d68cefd08acbbeaf83053dd79`.

---

# Native evaluation readiness and scope refresh release

Last updated: 2026-10-26

**Status: complete; proofs, tests, installed acceptance and root verification pass.**

- [x] Add actor-owned native evaluation leases with ordered revisions, generation
      fencing, exact validated removal and conservative failure/timeout behavior.
- [x] Wire the policy, generated contracts and mandatory proof claims through the
      shared host library and both extension package proof closures.
- [x] Pass 129 proof obligations, 16 properties, four witnesses and six replayed
      mutations; pass ten actor/runtime tests without generic Invariant changes.
- [x] Keep native callbacks and passive readiness reads free of actor waits;
      recheck ingress after physical job observations and cover timeout futures.
- [x] Track whole renders through init/complete-or-cancel while preserving
      per-frame work; retain separate leases for overlapping evaluation starts.
- [x] Drain observations before recovery/cleanup waits and at explicit background
      effects; preserve real native replacement authority and physical barriers.
- [x] Share Bake readiness across button, poll and admission in both editors and
      Grade/Stack; block after playback stop until evaluation actually settles.
- [x] Show native waiting only in localized hover help. Race clicks and temporary
      capture deferral create no popup, Image, snapshot or retained reservation.
- [x] Arm Refresh on press, activate once on valid release in its original
      button/target/editor occurrence, and restrict chart math to grading modes.
- [x] Cancel outside/Escape/right-click, pending, changed context and lifecycle
      gestures without capture, autokey, parameter changes, Undo or leaked handles.
- [x] Pass focused Bake, route, scope, UI, reader-guard, lifecycle, recovery and
      output tests, architecture checks and both extension packaging tests.
- [x] Pass installed Shader/Compositor Bake and native-reader acceptance.
- [x] Pass installed Gizmo acceptance against the final ZIP: all three
      pages in both editors, real motion/release, cancellation and six captures.
- [x] Pass the formal Buck installed Gizmo target and root
      `//:verify //:perceptual_grade //:hdr_color_picker` build.
- [x] Preserve the supplied project and record the tested archive identity.

All 373 cases across 20 targets pass. Root verification/package build:
`24ffc02a-4a2c-4083-8465-28df4143a12c`; installed Gizmo build:
`7c947dbe-558a-42e1-b3a3-a687e08f9fb2`.
Evidence: `buck-out/native-readiness-validation/summary.json` and adjacent logs.
ZIP SHA256:
`cc7811cae688eeb6dc6779c0edeeac987274bef1607d99f61e3ad29fe6706ed2`.
Native validation uses Linux Blender 5.2.2; macOS/Metal remains separate.
The earlier stale automatic-scope test now checks the intended source-only
playback behavior instead of reinstating a global native-reader restriction.

---

# Shader/image baking, shared readers and playback cancellation

Last updated: 2026-10-26

**Status: complete — Shading UI corrections verified.** Real GUI drawing and
Add Bake operators now supplement the earlier worker/API checks.

- [x] Enable Add Bake in editable local embedded Material/World trees; reject
      evaluated and non-local trees consistently with creation.
- [x] Repair route-preview drawing, show Image/UV and the reason, show UV-only
      dimensions, and keep draw callbacks passive.
- [x] Preserve explicit source-coordinate links as UV; verify an unconnected
      still Image uses Image baking while the foreground scene stays Eevee.
- [x] Verify Shader Grade/Stack Bake Image search and RNA assignment of valid
      packed Compositor data; retain invalid-image exclusion. Disable the
      selector with a waiting explanation while native operations prevent edits.
- [x] Explain Baked Vector and reader Vector sampling in both domains, including
      active-UV fallback and independence from live grading/bake-target UVs.
- [x] Fix standalone-reader binding to update the Image property and kernel
      without adding Grade sockets; cover binding and clearing.
- [x] Extend native Shading UI/installed acceptance for these paths, coordinate
      behavior and save/reopen; run affected Buck tests and final package gates.
- [x] Record corrected validation evidence and final archive identity.

- [x] Add route-aware explicit Bake admission for Shader Grade and Grade Stack.
- [x] Auto-select full-resolution image baking for one ordinary still Image and
      the approved pointwise color/alpha graph; preserve source dimensions.
- [x] Add Cycles active-mesh UV baking for surface-dependent Shader inputs,
      including configurable dimensions for newly created single-tile Images.
- [x] Reject UDIM, Alembic-dependent geometry, movie/image-sequence inputs,
      texture-range bakes, Eevee UV baking and Shader to RGB with an actionable
      65³ LUT recommendation.
- [x] Add Shader Grade/Stack Baked Color, Baked Alpha and shader-only Baked
      Vector input with explicit UV fallback; migrate old kernels append-only.
- [x] Add standalone Shader Bake reader with Vector input and UV fallback;
      preserve existing Compositor reader behavior and manual-only replacement.
- [x] Share flat image-domain artifacts across Shader and Compositor; keep UV
      artifacts selectable only from Shader nodes.
- [x] Preserve terminal Shader Alpha with graded RGB in one packed float RGBA
      Image; verify linked/unlinked alpha and premultiplied/data cases.
- [x] Freeze source/scene/material/UV identities, route native work through
      private helpers, and retain queue lanes, destination ordering, Undo/Redo,
      rollback and physical retirement.
- [x] Latch playback start and cancel every unfinished explicit Bake (freezing,
      queued, running or ready) on the timer/modal path, including a quick
      play-stop; retain prior Images, show per-node interruption, suppress
      race-click popups and preserve an already committed publication. Keep
      physical helper/queue leases until retirement and leave automatic
      scopes/LUT production running.
- [x] Pass numerical, Blender, execution, packaging and installed Shader/
      Compositor Bake acceptance, including save/reopen and Undo/Redo.
- [x] Update product documentation/locales and record final ZIP/evidence.

Final package: `buck-out/shader-ui-validation/perceptual_grade.zip`.
SHA256: `62996495e5d4f1255ca4e2ea3dabe849e394e9039319ae54c93cec969b1da335`.
All seven affected targets pass 126 tests (build
`f41a1eb0-78b2-4799-b373-052cbcdf97da`). Installed Shader GUI acceptance
(`a99c5ba6-2a93-4231-a24c-8c7064465d3f`) verifies Material/World Add Bake,
successful Grade/Stack production draws, a 4×2 packed `SHADER_IMAGE` from Eevee,
manual Color/Alpha routing, coordinate edits and packed save/reopen. The
cross-page selector test uses native RNA search/assignment with a packed
Compositor-shaped fixture; mouse popup selection is not automated. Installed
Compositor acceptance (`12f94d29-a792-466f-98bb-1f9a4257b75a`) verifies shared
rebakes, save/reopen, Undo/Redo, playback cancellation and physical retirement.
Root verify/package pass in `0f9f93ab-e461-454a-9693-fa44c5336a98`; final package
build is `7eb49366-2d83-425c-b05a-b54d0fa48fc4`.

The current task supersedes the earlier completed delivery records below.

---

# Playback, parallel baking and Undo responsiveness

Last updated: 2026-10-26

**Status: complete; implementation, integration and native acceptance passed.**
The current task supersedes the earlier completed delivery records below.

- [x] Keep one immutable active scope acquisition/analysis and one newest pending
      request for Image animation and animated Grade controls.
- [x] Continue metadata discovery, stored-source decode and numerical publication
      while the compositor owns native output readers.
- [x] Pin primary/reference samples independently; retain frame/models through
      partial revision discovery and bind verified identities before analysis.
- [x] Retain cancelled acquisition leases until physical source-helper retirement,
      including across cache clear; preserve guarded resident-buffer reads.
- [x] Show the published scene frame and, when different, the sampled Image frame.
- [x] Add two independent Bake lanes, eight bounded request reservations, per-node
      state/errors, shared-destination click order and independent publication Undo.
- [x] Add the actor-owned `bake_queue` machine and `.inv` safety properties,
      witnesses and replayed source mutations; extend `channel.inv` scheduling checks.
- [x] Establish producer validity through ordered transfer/update/packing and the
      output actor; remove native output readback/hash certification.
- [x] Adopt restored graph/Image state with unknown numerical provenance; protect
      the selected native bank and preserve unchanged intent through idle/save/render.
- [x] Route downstream adopted sources through explicit native scope capture.
- [x] Keep restored native wrapper identity stable after edits and while Bake runs;
      expose the Bake selector directly and restore original wrapper/mute on save.
- [x] Track bounded recovery, progress, physical retirement, failure and retry in a
      source-bound coordinator; preserve live same-generation debt on retry.
- [x] Add shared ownership retry admission without changing replacement generation.
- [x] Reconcile known managed Image revisions without reading payloads; preserve
      dirty, unknown and unpacked native buffers and ignore saved repair journals.
- [x] Pass affected integration tests, installed playback and concurrent Bake
      publication/Undo acceptance; verify the final package.
- [x] Compare Undo timing in a quiet native run; verify the unchanged user project.
- [x] Pass root verification and package gates; record the final ZIP and evidence.

Final package and evidence are in `buck-out/state-recovery-validation/`; the ZIP
SHA256 is `ed64a7f8fd79b193e35789eaacb9f247d78ebe16e8cc9b2ccea55b06a4727ec5`.
Root verification/package build `034cac79-bc4f-462d-a0a6-b5a9e8d2217c` passes,
including 800 affected proof obligations and 21 detected/replayed mutations.
The evidence summary records integration coverage and installed native scenarios.
On Linux Blender 5.2.2, a quiet matched-driver comparison over 12 Undo/Redo
boundaries per package measured median recovery completion **1.651 s → 0.594 s**,
including deferred recovery and excluding later test-driver waits. Recovery made
zero output pixel reads/hashes. Full rows and both archive hashes are in
`undo-summary.json`. Earlier playback and parallel Bake validation remains in
`buck-out/responsiveness-fix-20261025/`.
The user project remains a read-only acceptance input with SHA256
`cf52d5f8e5d12df89fb9e56f3bd29928e35a40cff20681eaec3b756fff0a8647`.

---

# Source-aware scope acquisition

Last updated: 2026-10-25

**Status: implemented, with the Gizmo context regression corrected.** Original
redesign validation passed all 29 affected targets (435 unittest cases), root
verification, extension packaging and 12 clean GUI processes. Delivery records are
in [GOAL.md](GOAL.md). The original detailed implementation contract is preserved
at `buck-out/scope-redesign-validation/implementation-contract.md`.

## Gizmo context regression (2026-10-25)

- [x] Distinguish frozen mappings from Blender RNA contexts before testing
      membership; preserve frozen/read-only/empty descriptors and detached IDs.
- [x] Use the supplied live editor for consumer discovery and failure fallback.
- [x] Cover real context/status lookup, separate editor identities and passive
      hover through the production sampling component.
- [x] Exercise native GUI hover, close press/release, reopen and subsequent tab
      clicks on all three pages against the installed corrected ZIP. Assert zero
      native descriptions/authorizations and clean teardown.
- [x] Confirm the same GUI test fails with the exact reported TypeError against
      the previous ZIP, without changing runtime sources during validation.
- [x] Pass root verification and packaging with existing state machines and
      `.inv` contracts unchanged; preserve one-shot capture authority.
- [x] Pass the complete 71-case scope suite and packaging checks. Aggregate final
      regression validation: 8 targets, 127 cases, all passing; target/build
      identities are in `buck-out/gizmo-context-fix/summary.json`.

Corrected archive and regression evidence: `buck-out/gizmo-context-fix/`.
The installed GUI acceptance ran on Linux Blender 5.2.2; macOS/Metal remains a
separate acceptance boundary. Original redesign timings below are not attributed
to the corrected archive.

## Accepted behavior

These decisions supersede earlier suggestions to remove native capture, reject
sequences, add a persistent graph index, or key computation by editor identity.

| Case | Required behavior |
| --- | --- |
| Image/Image Texture → Grade | Automatic sampling of original Image pixels, independent of mesh, lighting, UVs, viewport framing and occlusion. No refresh button. |
| Image → managed upstream Perceptual Grade/Stack → Grade | Automatic Image sampling plus the existing analytical Grade / exact Stack evaluation. Preserve occurrence order and repeated/shared Grades. |
| Image → compositor Transform → Grade | Automatic original-Image sampling; ignore Transform placement and resampling. This is an intentional signal-contract change. |
| Simple sequence/movie Image node → Grade | Automatically sample the resolved current source frame. Time dependence alone does not require manual capture. No refresh button. |
| Constants, reroutes, native muted bypasses, nested groups | Preserve constants and resolve transparent paths with exact socket/group occurrence semantics. |
| Managed Baked Color → Grade | Read the bound baked Image; do not depend on the unused live Grade controls or LUT. |
| Adopted upstream Grade/Stack after load or Undo | Preserve the actual native graph and unknown numerical provenance. Use explicit Refresh Scope Inputs; a real upstream grading intent change resumes managed production. |
| HSL, RGB/custom curves, Color Balance, Mix, Blur or other complex native processing | Generic Blender evaluation after an explicit Gizmo click. Evaluate the full processed input, including Transform/spatial effects. Do not implement a product-wide supported-node whitelist. |
| Render Layers or scene/surface-dependent source | Manual native capture with the existing native correctness boundaries. |

Automatic routing is an optimization with known signal semantics. Never walk
through arbitrary color/combine nodes and choose the first Image: that would
silently discard upstream adjustments. The specifically agreed spatial bypass
is the compositor Transform case; Blender exposes no general metadata for
classifying all spatial nodes. Other operations can remain generic native
evaluation rather than being incorrectly bypassed.

The scope source is resolved from the existing graph. No new Scope Image picker,
saved mode property, Image socket or graph rewiring is part of this task. The
existing **Bake Image** selector is a separate, completed feature.

**Refresh Scope Inputs appears only on the drawn Gizmo**, on all three pages
when the primary or displayed reference input needs native capture. Hide it
entirely for automatic routes. Native capture requires a click even on first
display. Opening the Gizmo, page changes, ordinary polling, Grade edits, source
edits and render completion must never authorize capture. Keep general native
node support; the requester accepted manual refresh for complex color processing.

One click targets that Gizmo's Grade, exact editor/group occurrence and required
primary/reference inputs. Disable duplicate refresh clicks while pending. Show
waiting-for-refresh, capturing, captured-input, refresh-needed and error states;
do not leave an unrequested source indefinitely Preparing. Retained old input
must be visibly stale, never certified current. Errors stay attached to the
initiating target, and retrying native capture requires another explicit click.

Suggested localized hover text: “Capture this Grade's processed input with
Blender. Inputs remain frozen until you refresh again. Grade controls update the
scope using the captured input. Capture may take several seconds.” Mention
frame/view changes in contextual help for sources that use them.

## Implemented and checked

- [x] Add short iterative, occurrence-aware source walks with temporary incoming
      link indexes. Resolve constants, Images, reroutes, mute bypasses, exact
      group instances, Baked Color, Transform and analytical Grade/Stack chains.
      Native graph description/readiness/snapshot work is absent on automatic
      routes. Deep walks, cycles, repeated/shared Grades and equivalent-editor
      cache sharing have real Blender regressions.
- [x] Read original scene-linear Image pixels with deterministic nearest pixel
      centers after decoding (including native squeezed-eye reconstruction), bottom-up
      rows, signed/HDR values and verified source alpha rules.
      Private sequence/movie reads resolve explicit frames without changing the
      source Image or relying on another editor's resident frame.
- [x] Select multilayer passes/views through existing Image controls. ALL selects
      the first configured view and names it. Support ordinary and stereo movie
      frames, separate views, side-by-side/top-bottom, interlace and anaglyph.
- [x] Sample stored ordinary UDIM tiles within a 49,152-sample budget, proportional
      to pixel population with deterministic quotas. Carry independent mass,
      tile IDs, local UV and logical waveform X through CPU/GPU analysis. Preserve
      column gaps and use mass in histograms, clouds and robust-fit sampling.
- [x] Condition references on the primary sample grid. Match tiled references by
      tile number/local UV, repeat ordinary references per primary tile, and use
      reference tile 1001 for an ordinary primary. Missing tiles have zero
      coverage. Native references sample the same local UV coordinates and become
      unavailable when the accepted grid no longer matches, even at equal shape.
- [x] Separate sample/analysis identity from publication ownership. Include source
      lifetime, resource revisions, decoding interpretation, destination working
      space, selected frame/pass/view and layout. Retain identical sample
      revisions, detect clean reloads and missing-file recovery, and stop hidden
      probes. Selected Grade edits do not force pixel acquisition; independent
      visible-source probes remain bounded at 0.5 seconds.
- [x] Freeze actual frame descriptors/models for delayed capture. Reject changed
      decode settings and actual sample revisions instead of assigning new pixels
      to an old request. Multiview descriptor discovery preserves resident eye
      buffers instead of triggering Blender's unsafe null-ImageUser reload.
- [x] Keep one active animated analysis and one replaceable newest successor.
      Publish compatible historical frames with their actual labels; only the
      current full identity reports current. Request epochs fence loops/reverse
      scrubbing and preserve newer errors. Static/native inputs remain part of
      compatibility when the other input is animated.
- [x] Make draws passive. Foreground timers own source work and boundary checks.
      Native-reader guards defer acquisition/publication, including during shader
      compilation, without recording an ordinary wait as an error.
- [x] Authorize native input only through the conditional Gizmo button on all
      three pages. One click freezes its exact target and required inputs; pending
      exact upstream output remains part of that authorization. Duplicate clicks,
      numerical retries, polling, edits and render completion do not authorize
      another native capture. Source changes revoke the frozen request.
- [x] Retain accepted pixels separately from pending replacements. Adopt two
      native inputs atomically; derive a first native reference grid from the new
      primary. Retain old input on failure, show waiting/capturing/captured/stale/
      error status, and keep automatic primary data live while a reference waits.
- [x] Preserve final 65³ provenance from actual captured Cubes, reject preview
      payloads, and prevent invalid active-source seeds from poisoning retries.
      Keep physical helper retirement, lifecycle fences, Undo/load cleanup and
      independent compositor Bake authority/destinations.
- [x] Add actor-owned `scope_input` with frozen State/Event/Effects and separate
      `.inv`: 150 obligations, 15 required properties, four witnesses and seven
      detected mutations with Python replay. Extend `channel.inv` for historical
      frame authority/compatibility and current-error preservation. Keep generic
      `libraries/invariant` and its upstream manifest unchanged.
- [x] Wire coordinator inventories, JSON mirrors, explicit Buck proof targets,
      runtime machine binding, component registry and lifecycle cleanup. Package
      generated runtime contracts through the existing source-bound proof gates.
- [x] Extend installed native coverage for HSL, Curves, Color Balance, Mix/Blur,
      spatial transforms, Render Layers, references, Material/World, projection,
      pending final65 preparation and isolated helper cleanup.
- [x] Correct diagnostic result attribution. Measure automatic source paths,
      selected/upstream edits, Image replacement, Transform bypass and explicit
      manual click separately. Observe production draws without adding demand.
- [x] Finish archive-wide regression gates and record the final source/archive
      identities in GOAL.md and the evidence summary.
- [x] Complete three uncontended fresh GUI processes per workspace and page
      order, summarize measured timings and preserve the manual input hash.

## Current validation evidence

Final consolidated build `16dcebbb-e64b-4b54-aeac-13a25b724ade` passes all 29
targets and 435 unittest cases: scopes 68, source routes 16, Image readers 17,
capture lifecycle 51, UI/status 17, plus policy, CPU/GPU math, scheduler,
lifecycle/recovery, Bake, packaging and installed acceptance. Installed movie
acceptance includes 36 stereo eye/frame comparisons. Root verification and
packaging pass build `76b5272d-a865-4b3f-8cbc-80483a72a5a8`.

Final archive SHA256:
`6f9c0bf7db1f47e1f75a2c99efd21f6c3365865b22607b631d4d0b9bbdb6f82e`.
`buck-out/scope-redesign-validation/summary.json` records the exact target list,
proof counts, archive identity and frozen runtime inputs. The 12-run GUI report
is `buck-out/scope-redesign-acceptance/report.md`; it binds its measured archive
and explicitly records the final native unsupported-buffer guard-only delta.
The supplied blend remains unchanged. No source or test files changed during
the final consolidated run.

Source-bound proofs establish protocol properties, not native Blender pixels or
painting behavior. Those effects retain separate generated-fixture and installed
checks. Detailed logs live under `buck-out/scope-redesign-baseline/` and
`buck-out/scope-redesign-*.log`; final evidence is indexed under
`buck-out/scope-redesign-validation/`.

## Explicit reader boundaries

- Save unsaved painted UDIM tiles before automatic sampling.
- Multilayer pass/view selection is supported for non-tiled sources. Combined
  tiled multilayer/multiview formats fail explicitly; no default pass/eye is
  silently substituted.
- Movie decoding requires a visible Blender window. Squeezed stereo eyes use
  native-matching interpolation before sampling decoded pixels.
- Dirty static multiview export requires an initialized resident selected eye.
  Dirty animated multiview requires saving because Blender's resident export
  cannot select an exact frozen frame. Actual GUI painting of initialized eyes
  remains within the separate manual-painting acceptance boundary below.
- Native scene snapshots require saving edited/generated tiled, multiview and
  multilayer sources that cannot be preserved by the single-buffer snapshot path.
- Automatic Image scopes deliberately ignore geometry, lighting, UV placement and
  simple compositor Transform placement. Other spatial/color processing uses the
  explicit native path. Native shader capture retains engine precision and
  camera/visibility semantics; Light trees have no camera-pixel domain.
- Linux virtual-GUI/software-rendering measurements do not establish physical
  display latency or macOS/Metal behavior. Cold means a fresh process/session,
  not cleared OS/Mesa caches. Inclusive phase durations overlap.

## Implementation map

| Owner | Responsibility |
| --- | --- |
| `src/scopes/sources.py`, `context.py` | Lightweight occurrence resolution and value-only source route |
| `src/scopes/images.py`, `exr.py` | Frame/pass/view decoding, color/alpha interpretation and sample revisions |
| Core `scopes/samples.py`, `model/scope_grid.py` | Deterministic layouts, mass and weighted sampling |
| `src/scopes/sampling.py` | Frozen descriptions/models, exact grid/provenance, click facade |
| `src/scopes/jobs.py`, `graph/scheduler.py` | Analytical cycles, pending-frame coalescing and publication tickets |
| `src/scopes/capture.py` | Explicit input/batch authority, dependency preparation, watches and retirement |
| `src/jobs/handlers/native_capture.py` | Isolated native graph evaluation and local-UV readback |
| Core `graph/coordinators/scope_input.py`, matching `.inv` | One-shot native authority and physical leases |
| Core `graph/policies/channel.py`, `requirements/channel.inv` | Current/historical publication and compatibility |
| `src/ui/diagram.py`, `geometry.py`, `color.py`, `help.py` | Gizmo action, passive status, frame labels and localization |
| `tools/diagnostics/project_probe.py`, `scope_probe_runner.py` | Observer-only GUI evidence and reproducible manual probes |

Paths beginning `src/` or `tools/diagnostics/` are under
`products/perceptual-grade-blender/`; core paths are under
`libraries/perceptual-grade-core/src/perceptual_grade_core/` unless specified.

```sh
buck2 build //:verify //:perceptual_grade
buck2 test //libraries/perceptual-grade-core/tests/policies:scope_input //libraries/perceptual-grade-core/tests/policies:scope_playback
buck2 test //products/perceptual-grade-blender/tests/blender:scopes //products/perceptual-grade-blender/tests/blender:scope_sources //products/perceptual-grade-blender/tests/blender:scope_images
buck2 test //products/perceptual-grade-blender/tests/blender:scope_capture //products/perceptual-grade-blender/tests/blender:gpu_status
buck2 test //products/perceptual-grade-blender/tests/installed:native_scope_capture //products/perceptual-grade-blender/tests/installed:scope_images //products/perceptual-grade-blender/tests/installed:compositor_bake
```

Use `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` for isolated numerical diagnostic
runs. Keep production source files frozen during helper acceptance: the runtime
correctly rejects helpers whose source manifest changes during startup.

## Completed baseline: viewport scopes and per-node baking

- [x] Preserve orthographic viewport depth, with projection/clipping and installed
      AOV regressions fixing the reported “no visible samples” failure.
- [x] Add filtered per-node Bake Image selection, create-on-Bake behavior,
      target-local status/errors and destination preflight validation.
- [x] Verify destination isolation, deliberate sharing, selection lifecycle,
      cancellation/rollback and native Undo/Redo/save/reopen.
- [x] Add timing diagnostics and three cold runs plus warm refresh/Grade edits
      in each workspace; identify latency causes.
- [x] Pass focused Buck, installed acceptance, packaging and root verification
      for the baseline; retain its evidence and product documentation.

## Deferred product work

- [ ] Import Image Workbench after the Blender/framework migration.

## Carried-over independent validation boundaries

- [ ] Complete macOS/Metal and physical HDR/manual painting acceptance.
      Linux native checks do not establish these separate claims.
- [ ] Establish native-reader exclusion during USD/Alembic export startup.
      Stock Blender's exposed job/lock observations do not cover this interval;
      passing known-reader tests cannot close this separate safety boundary.
