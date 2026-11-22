# Implementation Checklist

Update this checklist as work progresses. Validation and formatting must remain scoped to `products/perceptual-grade-next-blender`, and executable checks must use Buck2 with `--remote-only`.

## Main CI follow-up — verified

Run `44146241261` on merged main `5a2cf26636c1` passed both build targets and 62/66 test targets. Three test targets failed and one handbook dependency failed to build; these results supersede any implication that the final merged selection was wholly verified by earlier focused receipts.

- [x] Identify the shared isolated Color fixture's missing `J_A`, the custom hue/Adaptance RNA backing-storage reset and rollback defect, and Chromium's inherited temporary socket path overflow.
- [x] Restore the isolated fixture's signed achromatic coordinate from incoming float32 energy without changing production math or numerical thresholds.
- [x] Repair reset and transaction rollback for custom storage, retaining the existing policy/effect boundaries.
- [x] Add real Blender regressions for unbound neutrality, complete/family resets, claim ownership, and exact rollback of absent/present backing keys.
- [x] Isolate diagram Chromium in a short private temporary directory and add a real-browser regression to the existing Next handbook audit target.
- [x] Document the causes and repairs in the Technical Report.
- [x] Repair the newly exposed conversion-fixture preparation barrier; bound the live compositor probe's Blender/llvmpipe threads and preserve reports on timeout without weakening acceptance.
- [x] Run affected tests through Buck2 `--remote-only`: Color suites each pass nine methods (`5becb784`); complete current/LTS installed and compositor-carrier retests pass (`c7beb653`); current/LTS animation and GUI undo pass (`f8629308`, separately from that command's pre-repair installed failures).
- [x] Pass both selected builds (`54a93cce`, 27 remote commands, zero local) and all 66 explicit Next CI test targets (`c405df87`, seven remote commands, zero local, reusing unchanged passing results). The earlier broad pass `75d35ef8` passed 64/66 before the additional fixture repairs. All timeouts, thresholds, normal-exit checks, and coverage are retained.
- [x] Pass the changed Next BUCK file with pinned buildifier 10.2.0 through Buck2 `--remote-only` (`7cec7ad1`); remove the temporary validation target afterward.
- [x] Repeat documentation acceptance after recording settled evidence: `808f0c10-e844-460d-b96a-7c02f4f2c5d4` passes 15 Technical Report checks (0.229 seconds) and five handbook artifact/browser checks (8.865 seconds), with seven remote commands and zero local. Inspect `sl status`: only intended source and tracking documents are pending, with no temporary validation targets or build outputs.

## LTS undo-lifetime repair — verified

The native recursive crash is reproduced. The source-supported pointer-remap mechanism is a hypothesis until its specific address collision is captured; pre-repair successful retries do not validate a fix.

- [x] Record repeated native `NodeTreeMainUpdater::make_node_previews_dirty` stack exhaustion during the second exposure undo, before the hue assertions, and distinguish it from the uncaptured raw-ID address-reuse hypothesis.
- [x] Record failed reproductions `d215a97d`, `0c52be78`, and `69116c83` separately from isolated passing build `7056eb87`.
- [x] Implement lazy reuse of the six pending/error host/interface variants with exact manifest topology/receipt validation before adoption and no retained RNA-object cache; native acceptance passes below.
- [x] Route fake-user retention through the existing resource policy's returned effects in acquisition and cleanup; prevent ordinary removal of published and legacy fallback helpers while retaining failed-unpublished candidate cleanup.
- [x] Verify repeated reconciliation, sharing/removal, pending→live→pending identity, save/load retention, corruption/replacement, cycle checks, and all six variants.
- [x] Pass focused runtime checks (`6816f1ad`: 126, 2.157 s body), template methods (`cb0091e5`: 15, 39.627 s), and current/LTS undo plus LTS drag (`c97eb4e1`: 12.271/12.822/16.567 s); all execution is remote and native process exit remains required.
- [x] Pass three concurrent LTS undo runs with unique test environment labels, all actual remote executions: `b8ae8c9d`, `16f3fe6b`, `d91cbf63` (15.060/15.029/15.009 s bodies).
- [x] Pass package (three), architecture (two), and LTS animation (two methods, 60.715 s body) in `9a6f09dd` (11 remote commands, zero local).
- [x] Pass the native six-variant pool matrix on current Blender and LTS in `f126a588` (six methods each, 1.758/1.733 s bodies), plus all 15 LTS template methods (40.731 s body); 87 remote commands, zero local. Both pool targets are in the explicit CI inventory.
- [x] Retain legacy fallbacks by marker presence even for `0`/`False`; pass the expanded six-variant current/LTS matrices and 15 report checks in `f62b7ffd-cda9-47d5-90b3-ab5838e81307` (pool bodies 1.635/1.702 s, report 0.229 s; seven remote commands, zero local).
- [x] Pass final LTS undo in `f8a97062-b32d-4cdb-a781-0f4ec0589b66` (12.315 s body; three remote commands, zero local).
- [x] Pass all eight focused resource-policy checks in `57b31729` (five remote commands, zero local); this test command is not a proof-build receipt.
- [x] Explicitly build `proof_resources[report]` in fresh remote build `76919d83-f191-48a1-9b1a-cf7276cc6c97` (seven remote commands, zero local): `ok=true`, ten required properties including both undo properties, two witnesses, two mutations.
- [x] Add the brief AGENTS.md undo-lifetime safeguard and update the Technical Report's resource and test contracts.
- [x] Update the existing resource state and sequence diagrams with the `retain_for_undo` branch and fake-user effect; audit evidence includes the native fallback-pool fixture.
- [x] Pass the Next Technical Report and handbook artifact audits in `2900ea1c-c400-41b6-a9bf-80a8de4bb9d5`: 15 report checks (0.235 s), three handbook checks (7.289 s), updated diagram geometry and all published formats; 872 remote commands, zero local.
- [x] Repeat both documentation gates after the final acceptance prose: `228186dc-dfc4-4a07-bc47-3d8384e67e6e`, 15 report checks (0.224 s), three handbook artifact checks (7.262 s), seven remote commands, zero local.

## Authoring-constraint follow-up — verified

The accepted follow-up below has its own historical passing receipts, kept separate from the initial Stage 3 delivery and the verified undo-lifetime repair above. Its two pre-repair passing LTS reruns did not establish a crash fix.

- [x] Add the synchronous `color_authoring` policy with sparse origin/restore-offset claims and effects as the sole write authorization.
- [x] Enforce the 4° cyclic hue gap in both directions and across the seam, including pinned edits, neighbor pushes, constrained restoration, ownership takeover, single-handle manual detachment, and retained blocked claims (14 runtime checks pass in `de327672-c1bb-4b60-8eef-e19f7f8a728f`).
- [x] Project invalid animated hue samples with the unique squared lifted-angle solve, a 4.0001° pre-storage allowance, and a 4° stored-gap check without changing keys/authored values (nine numerical resolution checks passed in remote build `3826bc77`).
- [x] Implement finite radial Adaptance limiting and tone-row soft spans 4/10/20/25 with 0.01 drag increments and unquantized typed values.
- [x] Implement node-owned claim expiration only on actual frame/subframe changes, preserve shared claims, and resolve Peak-dependent hue/Adaptance changes in one transaction; final native animation/conversion acceptance passes on current Blender and LTS.
- [x] Add derived Auto/Limited UI indicators; exclude authoring metadata from math signatures while retaining a separate undo fingerprint.
- [x] Author the bilingual Color manual, Technical Report math/policy/testing contracts, authoring sequence diagram, and report audit inventory; first and final settled-source remote artifact acceptance pass.
- [x] Add the scalar policy requirements/proof and numerical regressions; pass the proof (`18f94c3f`, one remote command, zero local commands) and all nine resolution checks (`3826bc77`) through Buck2 with `--remote-only`.
- [x] Pass all 14 reversible-edit runtime checks, nine numerical resolution checks, three package checks, 125 preparation-runtime checks, and 53 bake-route checks (47 route plus six geometry) in final remote build `de327672-c1bb-4b60-8eef-e19f7f8a728f` (25 remote commands, zero local commands).
- [x] Complete native animation/conversion and undo acceptance on current Blender and LTS, retaining normal process exit; record three earlier LTS native exposure-undo crashes and two consecutive passing reruns without claiming their cause fixed.
- [x] Pass the final current-Blender undo harness with faulthandler/crash-on-failure reporting in `0f1a8438-cfce-463a-8e00-fbddbd1361a8` (11.205 s); keep the unresolved native LTS crash note and avoid an unsupported production fix.
- [x] Pass the first follow-up documentation audits in `d1fff95f-6075-457e-86d7-e2d88c2343bc`: 15 report checks (0.244 s), three artifact checks (9.098 s), new diagram/label geometry, 872 remote commands, zero local commands.
- [x] Repeat the Next Technical Report and handbook artifact audits after follow-up prose and implementation settle: build `963af662-1d5b-40f4-aa11-697ca0b47170` passed all 15 report checks (0.233 s) and three handbook artifact checks (7.246 s), with seven remote commands and zero local commands.

## Verified initial delivery

Updated 2026-11-17: Stage 3 is implemented and verified, including settings/UI, role-bundle publication, Stack computation, and bilingual handbook changes. Remote preparation (35 tests), reference (7), guards (6), preparation runtime (125), Stack GPU (5), bake routes (53), and bake freshness (12) checks have passed. Final source-emitted full-Grade build `d1006e84-e3fb-4683-aa36-d9ededfe5d21` passed five methods per context (423.640 s Shader, 422.974 s Compositor) and all five Stack GPU checks (190.122 s). Semantic J_A carrier static acceptance passes, including equivalent-arithmetic extreme parity in build `82e081c4-17e1-4921-a756-8daa18cfbd14` (390.0 s action, 386.689 s body) and basic Compositor (303.4 s action, 300.043 s body). Final live build `252b9488-83c2-49de-8943-8f509bc7e8f0` passes the shipped Viewer fixture in 61.382 s, all 18 source-carrier live evaluations in 226.453 s, and five transport checks, retaining 0.01 Auto and `1e-4` Full gates. The complete installed suite passed with semantic J_A carry in build `2e322f99-3ca6-4d12-b4d1-fcf598568d3f`: 223.659 s on Blender 5.3 and 224.968 s on LTS, retaining all sections, removed-primary recovery, the strict one-preparation check, and normal exit. Final frozen-asset build `40fc9dd3-66b5-452b-9bbb-cf052870b80e` passes all five numerical/template/receipt gates. Final raw assets are .blend 3,688,385 bytes, manifest 9,464 bytes, and Stack shader 67,226 bytes; the 7,896,941-byte structure report stays build-only. Final documentation build `b3be89a0-109c-4d88-a334-a79fe339c529` passes all 15 report checks (0.224 s) and three handbook artifact checks (7.180 s), with seven remote commands and zero local commands.

The installed receipt difference was traced to native Blender flushing a float32 subnormal socket literal that the bpy wheel retained. The build-only emitter uses two normal factors; exact receipt gates passed in both hosts for all 12 groups and Grade bindings across three working spaces and two contexts; final refined artifacts pass both exact receipt gates. Static targets are `:stage2` (two interface methods), `:stage2_shader` / `:stage2_compositor` (the basic guarded method's two space cases per context), and `:stage2_extreme` (one extended method); `:stage2_updates` retains two publication/save-load methods. `:full` / `:full_compositor` retain five methods each. The static module validates `PG_STAGE2_SECTION` and the exact union of current Stage 3 methods; default module loading runs only `interface`. Splitting this current suite preserves its methods, subcases, corpus, and limits within separate 600-second actions. Basic guarded parity remains 3 ppm, with a separate `1e-4` oracle gate. The extended active-Color extreme test replaces the older achromatic-only 3 ppm diagnostic; generic, protected-generic, and fixed-tree outputs each face `1e-4` independent RGB acceptance, and equivalent-arithmetic binding parity retains the current extreme test's 5 ppm limit. Static, final live, and frozen shipped-template checks pass.

## Stage 3 math and settings

- [x] Audit frozen selectors, signed energy handoffs, and reference H-K-before-Scale equations.
- [x] Generalize Stage 3 preparation to produce complete default and active field payloads.
- [x] Add a shared build-only Color math implementation for Shader, Compositor, and Stack compute adapters.
- [x] Add Stage 3 settings to snapshots, signatures, preparation scheduling, shared Grade data, Stack entries, and animated node-owned Grades.
- [x] Share the 116-field Stage 3 inventory with target/upstream/Stack bake freshness; verify route and freshness regressions remotely without pixel hashing.
- [x] Implement the complete numeric J, C, Adaptance, and Web sidebar in English and Simplified Chinese; leave the draggable diagram deferred.

## Publication and templates

- [x] Expand parameter banks to five role-based images and update schemas, content receipts, and fixed role-based bindings.
- [x] Add schema 4 tonal anchors and authored Adaptance-row flags to preserve exact-zero cardinal support without enlarging the scalar image.
- [x] Replace the 3,072-cell Adaptance field with one fixed 32,768-cell layout under schema 6; retain the unchanged strict RGB acceptance gate.
- [x] Generalize Grade resources, readers, selectors, recovery, rollback, load/undo reconciliation, and shared Shader/Compositor ownership.
- [x] Emit updated Shader and Compositor Grade templates from the build-only generator.
- [x] Extend Stack snapshot serialization, field uploads, and the bundled compute shader to evaluate full Stage 3 while preserving 33^3/65^3 topology.
- [x] Make Compositor GPU Auto Stage 3 energy transport half-safe; retain visible failure for unsupported values and pass actual live Auto/Full gates.
- [x] Add observed-source/state/output nonfinite routing; verify CPU/GPU final renders separately from the passing live half-precision Grade acceptance.

## Oracle, tests, and reports

- [x] Correct the independent full-grade oracle to use the reference guard-before-Scale behavior.
- [x] Add numerical and native tests for active Adaptance plus non-unit Scale, negative-H bypass, zero chroma, zero reference energy, working spaces, and Stack LUT output.
- [x] Add bundle coverage for staging failure, selector rollback, mixed-role/generation rejection, unchanged-role reuse, and native save/load recovery; retain installed undo/reconciliation coverage.
- [x] Add node-owned Web and Adaptance animation coverage and live-Viewer GPU Auto comparison against CPU Full, including alpha and HDR cases.
- [x] Update the Technical Report, bank publication diagrams, evidence inventory, and report audit evidence.
- [x] Document fixed Adaptance storage and observed-source/state/output finite routing, including strict representational bounds, alpha preservation, and the effective-Full limitation of final-render Auto tests.
- [x] Refresh all four kernel evidence documents for schema 6; preserve schema-5 reports and timings as explicitly historical receipts.
- [x] Document fresh per-validation graph-link indexing and scene compositor recalculation after installation receipts, including installed save and live acceptance, and unchanged policy ownership.
- [x] Split the current Stage 3 parameterized suite into explicit interface/Shader/Compositor/extreme targets with validated selection and exact current method union; preserve that suite's subcases and limits plus the separate two-method publication/save-load target.
- [x] Add a real live carrier regression across 18 GPU Auto/Full and CPU Full evaluations; distinguish the first intermediate-source result from the subsequently passing final semantic and shipped GUI gates.
- [x] Carry J_A explicitly through disabled stages and inactive H–K repair, and scale it directly by positive Scale; avoid identity decisions based on potentially underflowed energy equality.
- [x] Repair role enumeration after an external primary-Image deletion and pass all 125 preparation-runtime tests; pass the complete installed recovery gate separately.

## Handbook and packaging

- [x] Rewrite the English and Simplified Chinese User Manuals for Next while retaining the legacy ZIP link and not adding a Next ZIP link.
- [x] Remove obsolete Resolve/DCTL workflow instructions and stale legacy interface captures from active manual chapters.
- [x] Preserve video generation targets and source recordings while detaching animations and animation-specific manifests from all book product assets.
- [x] Ensure site, site ZIP, PDF, and EPUB contain no animated images.
- [x] Add a Next-scoped handbook audit for manual scope, legacy-link retention, and animation-free book assets.
- [x] Include the handbook artifact audit in the explicit Next CI inventory and extend packaging exclusions for the new build-only Color/output emitter modules.

## Verification

- [x] Resolve extreme-control final RGB deviations without relaxing the numerical acceptance gate; source-emitted full-Grade gates pass in both contexts.
- [x] Pass shipped-template numerical gates in both Shader and Compositor, separately from source-emitted full-graph acceptance.
- [x] Repeat full-Grade and shipped-template acceptance after final unused-branch hardening.
- [x] Pass installed save/recovery acceptance after graph-link indexing (33.338 s, one remote command, zero local commands); retain native packing-failure, complete-bundle, reload, dirty-image, and rollback coverage.
- [x] Pass node-owned Stage 3 animation in background and GUI on Blender 5.3 and LTS (two methods each, 68.866 s / 68.087 s), retaining persistence, per-frame publication, the 300-second limit, and normal native exit.
- [x] Pass real drag and independent undo gesture acceptance (17.075 s / 11.832 s test bodies).
- [x] Pass the complete installed suite with semantic J_A carry on Blender 5.3 and LTS (223.659 s / 224.968 s), retaining removed-primary recovery, the strict one-preparation check, all original sections, normal exit, and per-section timing records.
- [x] Pass all four static sections and publication/save-load after the semantic J_A repair, including equivalent-arithmetic extreme parity; record this separately from the later GPU Auto projection candidate.
- [x] Pass affected basic Compositor and extended extreme static targets on the final accepted GPU Auto candidate (build `931037c4-2077-4e08-9fd9-e864f7e3412d`, 281.0 s / 423.3 s actions), retaining every independent and binding-parity gate.
- [x] Pass final semantic carry regressions and live source/shipped GUI acceptance, preserving the 0.01 Auto and `1e-4` Full gates, automatic updates, alpha, reload repair, and normal native exit.
- [x] Pass final affected shipped-template numerical and exact receipt gates after the accepted GPU Auto projection refinements (frozen-asset build `40fc9dd3-66b5-452b-9bbb-cf052870b80e`).
- [x] Pass extended extreme binding parity against the equivalent-arithmetic protected baseline at 5 ppm, with separate `1e-4` oracle gates for all three graphs; retain the basic guarded test's 3 ppm parity limit.
- [x] Resolve installed Stage 3 template structure receipt mismatches; exact bpy/native receipt gates pass.
- [x] Regenerate node templates through the declared Buck2 target with `--remote-only` and record artifact sizes and kernel inventories.
- [x] Regenerate, remeasure, and recheck exact cross-host receipts after the final projection refinements: .blend 3,688,385 bytes, manifest 9,464 bytes, Stack shader 67,226 bytes; exclude the 7,896,941-byte build-only report.
- [x] Confirm final live-Viewer acceptance across 16 exercise frames and 12 automatic updates, with the separate 18-evaluation source-carrier and five-check transport gates.
- [x] Confirm final packaging exclusion of runtime graph emitters and the build-only structure report (build `dbd09f0a-b260-48b9-b487-963e98a53f7a`: architecture two methods, packaging three, localization four).
- [x] Run focused Next numerical/native/runtime/packaging tests and policy-proof dependencies through Buck2 with `--remote-only`; record their separate acceptance scopes above.
- [x] Run the Next Technical Report audit and handbook artifact audit through their Next-scoped Buck2 targets with `--remote-only` (15 and 3 checks).
- [x] Repeat both documentation audits after numerical code, template measurements, and final report wording settle (build `b3be89a0-109c-4d88-a334-a79fe339c529`: 15 report and three handbook artifact checks, seven remote commands, zero local commands).
- [x] Check `sl status`; only intended Next/book/CI sources and the two root tracking documents are pending, with no build outputs/tool state or `rei-rgb.blend` fixture.

`rei-rgb.blend` is absent, including ignored files; it is not a regression fixture.

## Current implementation: runtime hardening

- [x] Extract Bake state and orchestration into `runtime/bake_controller.py`, retain thin `nodes.py` UI, timer, handler, and public API delegates, and update the Technical Report source inventory.
- [x] Fix Bake deletion retirement, deferred graph reconciliation, and canonical effective-input fingerprints with explicit receipt fingerprint versioning.
- [x] Extract load/undo/redo phase sequencing into `runtime/lifecycle.py` and guarantee invalidation fences despite individual gesture cleanup failures.
- [x] Preserve preparation coordinator root failures, deliver fail-closed output once admission is available, and prevent acknowledged terminal failures from keeping the timer active.
- [x] Replace singleton `JobGroup` wrappers with direct `JobHandle` use while preserving preview suppression, cancellation, and physical retirement polling.
- [x] Assign and enforce persistent UUID identity for locally owned Grade nodes, regenerating it on copies without legacy kernel migration.
- [x] Reuse template manifest validation for full Grade graph checks, verify packed Grade boundary and Stack LUT pixel digests, and keep full checks off interactive hot paths.
- [x] Filter Grade resource adoption before expensive graph checks, remove dead methods, and skip full image retirement sweeps when bank-only publication displaced no kernels.
- [x] Add focused runtime and installed regressions for all changed contracts, including save/load and undo cases.
- [x] Run affected Next Blender runtime, installed Blender, packaging, policy, and documentation audit targets through Buck2 with `--remote-only`.
- [x] Keep root tracking status current and verify DCTL changes remain untouched.

Remote build `1068f756-a591-4a9e-9762-2f715d4363b5` passed preparation, Bake manager/routes/freshness, native node templates, architecture, and packaging. The Technical Report audit identified a missing Bake source marker in `nodes.py`. The marker has been restored and the audit will be rerun.

Remote build `ddd509f2-5f4b-43f4-9381-c30f2152e55b` passed the Technical Report audit, the Blender 5.3 working-space Bake, and Stack helper and gesture reload on Blender 5.3 and 5.2.4 LTS. The installed Grade and Bake fixtures needed corrections to node initialization and a controller reference.

Remote build `cee0343d-66e2-461d-a16e-c8c0430f12bd` passed the corrected full installed Grade suites on Blender 5.3 and 5.2.4 LTS, and both dedicated Bake suites on Blender 5.3.

Final remote build `96f1f60f-0e36-4407-b5d8-cfa49620dc3c` passed 14 runtime, native, policy, packaging, and Technical Report targets. Packaging included the shipped policy proof dependencies. The Buck2 runs used zero local commands.
