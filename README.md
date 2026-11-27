# Linux build and test results

- Commit: `af39b64c8cf6d1bf708000409c5c4cba6ae203a5`
- Recorded at: 2026-11-27T18:17:41+00:00
- Run: https://github.com/rei277hz/chromaticity/actions/runs/46043384232

Each test row represents one selected Buck suite. A suite may contain several test cases.

## Linux build targets: 2/2 passed

Run outcome: **passed**. Command exit: `0`.

| Target | Result |
| --- | --- |
| `//products/perceptual-grade-next-blender:verify_policies` | passed |
| `//products/perceptual-grade-next-blender:extension` | passed |

## Linux test suites: 68/70 passed

Run outcome: **failed**. Command exit: `3`.

Duration sums Buck-reported execution time across attempts. 'n/a' means no complete timing is available.

| Test ID | Purpose | Result | Duration | Attempts |
| --- | --- | --- | ---: | ---: |
| `//products/perceptual-grade-next-blender/tests:persistent` | Checks persistent Grade graph updates, resource reuse, rollback, and save/reopen. | passed | 09:27.13 | 1 |
| `//products/perceptual-grade-next-blender/tests:persistent_color_stages` | Runs Color-stage numerical checks through persistent native Grade graphs. | passed | 06:46.26 | 1 |
| `//products/perceptual-grade-next-blender/tests:installed` | Exercises extension registration, Grade and Stack lifecycle, save/load, undo, and recovery in Blender. | passed | 06:42.82 | 1 |
| `//products/perceptual-grade-next-blender/tests:vectorscope_native` | Checks live scope updates during compositor edits and playback and shader viewport capture. | passed | 05:36.64 | 1 |
| `//products/perceptual-grade-next-blender/tests:stage2` | Checks the public interface of reset and active Grade node trees and rejects incomplete preparation. | passed | 05:24.40 | 1 |
| `//products/perceptual-grade-next-blender/tests:stage2_extreme` | Compares extreme compositor Tone settings across parameterized and generic Grade graphs. | passed | 05:19.47 | 1 |
| `//products/perceptual-grade-next-blender/tests:stage2_updates` | Checks repeated parameter publication and verifies updated snapshots survive save and reload. | passed | 04:50.29 | 1 |
| `//products/perceptual-grade-next-blender/tests:full_compositor` | Checks the full guarded Grade pipeline in compositor graphs across working spaces. | passed | 04:33.39 | 1 |
| `//products/perceptual-grade-next-blender/tests:full` | Checks the full guarded Grade pipeline in shader graphs across working spaces. | passed | 04:12.91 | 1 |
| `//products/perceptual-grade-next-blender/tests:stage2_compositor` | Compares guarded Stage 2 compositor output against the independent reference. | passed | 03:54.62 | 1 |
| `//products/perceptual-grade-next-blender/tests:lut_gpu` | Checks GPU Stack LUTs against reference and native Blender graphs, including inverse grades. | passed | 03:09.40 | 1 |
| `//products/perceptual-grade-next-blender/tests:compositor_carriers` | Checks live compositor intermediates and output with GPU Auto, GPU Full, and CPU Full precision. | passed | 02:53.36 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_preparation` | Checks preparation and reuse of Color parameters for Adaptance and Warp. | passed | 02:36.49 | 1 |
| `//products/perceptual-grade-next-blender/tests:bake_installed` | Exercises native Bake routes, artifact publication, and bake state transitions in Blender. | failed | 02:01.39 | 1 |
| `//products/perceptual-grade-next-blender/tests:installed_animation` | Checks continuous Grade animation in background and GUI-driven Blender sessions. | passed | 02:00.63 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_stages` | Checks native Color stages against reference numerics, including hue seams and sharp control boundaries. | passed | 01:39.95 | 1 |
| `//products/perceptual-grade-next-blender/tests:template_receipts_blender` | Runs native template receipt checks in the Blender application. | passed | 01:24.62 | 1 |
| `//products/perceptual-grade-next-blender/tests:compositor_gui` | Checks live compositor edits, automatic precision, and recovery of saved Grade kernels. | passed | 01:19.15 | 1 |
| `//products/perceptual-grade-next-blender/tests:stage2_shader` | Compares guarded Stage 2 shader output against the independent reference. | passed | 01:12.84 | 1 |
| `//products/perceptual-grade-next-blender/tests:template_receipts` | Checks native template validation receipts before and after runtime bindings through bpy. | passed | 01:01.03 | 1 |
| `//products/perceptual-grade-next-blender/tests:node_templates` | Checks template manifests, working spaces, private bindings, and saved instances. | passed | 00:57.08 | 1 |
| `//products/perceptual-grade-next-blender/tests:image_save_gui` | Checks that saving generated Grade images preserves Blender's unsaved user-image warnings. | passed | 00:49.04 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_templates_compositor` | Checks compositor Color templates with active and extreme controls across working spaces. | passed | 00:31.60 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_templates` | Checks shader Color templates with active and extreme controls across working spaces. | passed | 00:30.14 | 1 |
| `//products/perceptual-grade-next-blender/tests:gesture_drag_gui` | Checks that Blender mouse events publish drag previews and finish gestures. | passed | 00:27.76 | 1 |
| `//products/perceptual-grade-next-blender/tests:native` | Checks raw shader and compositor output against the reference, plus native resource ownership and save/reopen. | passed | 00:21.72 | 1 |
| `//products/perceptual-grade-next-blender/tests:boundary_resource` | Checks deterministic output boundary data and rejection of missing or invalid resources. | passed | 00:20.02 | 1 |
| `//products/perceptual-grade-next-blender/tests:grade_render_preflight` | Checks that pending Grades are reconciled before Blender evaluates a render. | passed | 00:17.63 | 1 |
| `//products/perceptual-grade-next-blender/tests:guards` | Checks native H–K and gamut boundary guard accuracy and fallback behavior. | passed | 00:15.62 | 1 |
| `//products/perceptual-grade-next-blender/tests:preparation` | Checks Linear and Tone preparation, parameter snapshots, and tone-anchor limits. | passed | 00:09.80 | 1 |
| `//products/perceptual-grade-next-blender/tests:gesture_undo_gui` | Checks that distinct GUI drags produce independent undo steps. | passed | 00:09.23 | 1 |
| `//products/perceptual-grade-next-blender/tests:stack_helper` | Checks that first-time Grade Stack preparation uses the real GPU helper. | passed | 00:08.54 | 1 |
| `//products/perceptual-grade-next-blender/tests:bake_workspace_installed` | Checks native Bake results in non-default working spaces. | passed | 00:08.22 | 1 |
| `//products/perceptual-grade-next-blender/tests:stages` | Checks appearance stage handoffs, generic decoding, and native graph cleanup after build failure. | passed | 00:07.94 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_transport` | Checks achromatic and chromatic coordinates carried between Tone and Color stages. | passed | 00:07.12 | 1 |
| `//products/perceptual-grade-next-blender/tests:reference` | Checks Linear and Tone numerics and full Grade oracle behavior against the reference model. | passed | 00:05.92 | 1 |
| `//products/perceptual-grade-next-blender/tests:fallback_pool_lts` | Runs fallback node group checks in Blender LTS. | passed | 00:05.88 | 1 |
| `//products/perceptual-grade-next-blender/tests:fallback_pool` | Checks fallback node group reuse, validation, and retention for undo through bpy. | passed | 00:04.94 | 1 |
| `//products/perceptual-grade-next-blender/tests:preparation_runtime` | Exercises asynchronous Grade and Stack preparation, helper coordination, and publication recovery. | passed | 00:04.22 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_verification` | Checks proof verification against unreachable branches, unsafe operations, and inconsistent assumptions. | passed | 00:03.89 | 1 |
| `//products/perceptual-grade-next-blender/tests:saturation` | Checks saturating arithmetic for overflow, sign handling, and division by zero. | passed | 00:02.86 | 1 |
| `//products/perceptual-grade-next-blender/tests:compositor_validity` | Checks compositor graphs for magenta error output, alpha preservation, and invalid state rejection. | passed | 00:02.72 | 1 |
| `//products/perceptual-grade-next-blender/tests:compositor_validity_blender` | Checks invalid pixel and state handling in Blender's GPU compositor. | passed | 00:02.67 | 1 |
| `//products/perceptual-grade-next-blender/tests:hdr_metrics` | Checks HDR comparison metrics, display transforms, and reported worst-case samples. | passed | 00:02.22 | 1 |
| `//products/perceptual-grade-next-blender/tests:vectorscope` | Checks Gizmo geometry, scope capture and analysis, freshness, and white-point dragging. | passed | 00:02.12 | 1 |
| `//products/perceptual-grade-next-blender/tests:lut_worker` | Checks Stack LUT request validation, progressive results, and worker cancellation. | passed | 00:01.25 | 1 |
| `//products/perceptual-grade-next-blender/tests:runtime_bake_routes` | Checks Bake source routing, dependency fingerprints, and UV geometry validation. | passed | 00:01.01 | 1 |
| `//products/perceptual-grade-next-blender/tests:lut_shader` | Checks compute shader assembly and compares generated Stack LUT shader source. | passed | 00:01.00 | 1 |
| `//products/perceptual-grade-next-blender/tests:lut` | Checks Stack LUT baking, atlas layout, interpolation, and boundary extrapolation. | passed | 00:00.96 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_authoring` | Checks Color control edits, including hue-handle constraints, restoration, and Adaptance limits. | passed | 00:00.86 | 1 |
| `//products/perceptual-grade-next-blender/tests:color_resolution` | Checks resolution of Color settings into valid Adaptance and hue-warp geometry. | passed | 00:00.83 | 1 |
| `//products/perceptual-grade-next-blender/tests:package` | Checks extension ZIP contents, proof coverage, and runtime import boundaries. | passed | 00:00.81 | 1 |
| `//products/perceptual-grade-next-blender/tests:architecture` | Checks component dependencies and verifies portable preparation can run without Blender. | passed | 00:00.81 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_node` | Checks Grade node readiness, failure states, and Grade Stack transitions. | passed | 00:00.80 | 1 |
| `//products/perceptual-grade-next-blender/tests:bake_worker_runtime` | Checks Bake worker dispatch and capture helper cancellation and cleanup. | passed | 00:00.72 | 1 |
| `//products/perceptual-grade-next-blender/tests:gate_policy` | Checks numerical admission limits and the conditions for HDR-based exceptions. | passed | 00:00.58 | 1 |
| `//products/perceptual-grade-next-blender/tests:technical_report_audit` | Checks technical report chapters and links to implementation and test evidence. | passed | 00:00.55 | 1 |
| `//products/perceptual-grade-next-blender/tests:vectorscope_latency` | Checks timing evidence for cold and warm Vectorscope updates. | passed | 00:00.38 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_gesture` | Checks drag activation, observer handoff, release, and undo ownership. | passed | 00:00.35 | 1 |
| `//products/perceptual-grade-next-blender/tests:install_workspace` | Checks installation into a workspace and safe replacement of the existing extension. | passed | 00:00.24 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_coverage` | Checks that proof evidence covers every shipped policy module. | passed | 00:00.21 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_bake` | Checks bake request admission, artifact activation, and live output selection. | passed | 00:00.17 | 1 |
| `//products/perceptual-grade-next-blender/tests:scheduler_render` | Checks synchronous exact render preflight dispatch, capture preemption, and scheduler admission. | passed | 00:00.17 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_helper` | Checks helper process startup, job admission, cancellation, and shutdown deadlines. | passed | 00:00.16 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_resources` | Checks resource ownership, validation, and retention for undo. | passed | 00:00.16 | 1 |
| `//products/perceptual-grade-next-blender/tests:scheduler` | Checks shared work priorities, dependency promotion, coalescing, yielding, and startup and recovery admission. | passed | 00:00.16 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_preparation` | Checks preparation scheduling and replacement of outdated requests. | passed | 00:00.16 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_bank_publication` | Checks parameter image staging, bank switching, and rollback. | passed | 00:00.15 | 1 |
| `//products/perceptual-grade-next-blender/tests:policy_render_preflight` | Checks render admission against the requested scene, frame, and published Grade signature. | passed | 00:00.14 | 1 |
| `//products/perceptual-grade-next-blender/tests:handbook_audit` | Checks published handbook formats, source references, and browser rendering fixtures. | failed | n/a | 0 |

Reporting notes:

- test-build-report.json: the build command did not report complete success
