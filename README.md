# Linux build and test results

- Commit: `ead1961eae44275e2ece17ab3d328cadea82112c`
- Recorded at: 2026-11-22T13:35:14+00:00
- Run: https://github.com/rei277hz/chromaticity/actions/runs/45025394642

Counts represent the selected build targets and smoke suites, not individual test cases or the full monorepo suite.

## Linux build targets: 2/2 passed

Run outcome: **passed**. Command exit: `0`.

| Target | Result |
| --- | --- |
| `//products/perceptual-grade-next-blender:verify_policies` | passed |
| `//products/perceptual-grade-next-blender:extension` | passed |

## Linux smoke suites: 63/65 passed

Run outcome: **failed**. Command exit: `32`.

| Target | Result |
| --- | --- |
| `//products/perceptual-grade-next-blender/tests:policy_preparation` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_node` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_helper` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_verification` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_resources` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_bank_publication` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_bake` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_render_preflight` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_gesture` | passed |
| `//products/perceptual-grade-next-blender/tests:color_authoring` | passed |
| `//products/perceptual-grade-next-blender/tests:preparation_runtime` | passed |
| `//products/perceptual-grade-next-blender/tests:runtime_bake_routes` | passed |
| `//products/perceptual-grade-next-blender/tests:bake_worker_runtime` | passed |
| `//products/perceptual-grade-next-blender/tests:lut_worker` | passed |
| `//products/perceptual-grade-next-blender/tests:lut_shader` | passed |
| `//products/perceptual-grade-next-blender/tests:preparation` | passed |
| `//products/perceptual-grade-next-blender/tests:color_preparation` | passed |
| `//products/perceptual-grade-next-blender/tests:color_resolution` | passed |
| `//products/perceptual-grade-next-blender/tests:color_transport` | passed |
| `//products/perceptual-grade-next-blender/tests:lut` | passed |
| `//products/perceptual-grade-next-blender/tests:lut_gpu` | passed |
| `//products/perceptual-grade-next-blender/tests:reference` | passed |
| `//products/perceptual-grade-next-blender/tests:boundary_resource` | passed |
| `//products/perceptual-grade-next-blender/tests:node_templates` | passed |
| `//products/perceptual-grade-next-blender/tests:fallback_pool` | passed |
| `//products/perceptual-grade-next-blender/tests:fallback_pool_lts` | passed |
| `//products/perceptual-grade-next-blender/tests:template_receipts` | passed |
| `//products/perceptual-grade-next-blender/tests:template_receipts_blender` | passed |
| `//products/perceptual-grade-next-blender/tests:compositor_validity` | passed |
| `//products/perceptual-grade-next-blender/tests:compositor_validity_blender` | passed |
| `//products/perceptual-grade-next-blender/tests:color_templates` | passed |
| `//products/perceptual-grade-next-blender/tests:color_templates_compositor` | passed |
| `//products/perceptual-grade-next-blender/tests:native` | passed |
| `//products/perceptual-grade-next-blender/tests:stages` | passed |
| `//products/perceptual-grade-next-blender/tests:stage2` | passed |
| `//products/perceptual-grade-next-blender/tests:stage2_shader` | passed |
| `//products/perceptual-grade-next-blender/tests:stage2_compositor` | passed |
| `//products/perceptual-grade-next-blender/tests:stage2_extreme` | passed |
| `//products/perceptual-grade-next-blender/tests:stage2_updates` | passed |
| `//products/perceptual-grade-next-blender/tests:color_stages` | passed |
| `//products/perceptual-grade-next-blender/tests:persistent_color_stages` | passed |
| `//products/perceptual-grade-next-blender/tests:persistent` | passed |
| `//products/perceptual-grade-next-blender/tests:guards` | passed |
| `//products/perceptual-grade-next-blender/tests:saturation` | passed |
| `//products/perceptual-grade-next-blender/tests:full` | passed |
| `//products/perceptual-grade-next-blender/tests:full_compositor` | passed |
| `//products/perceptual-grade-next-blender/tests:grade_render_preflight` | failed |
| `//products/perceptual-grade-next-blender/tests:gate_policy` | passed |
| `//products/perceptual-grade-next-blender/tests:hdr_metrics` | passed |
| `//products/perceptual-grade-next-blender/tests:architecture` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_coverage` | passed |
| `//products/perceptual-grade-next-blender/tests:package` | passed |
| `//products/perceptual-grade-next-blender/tests:technical_report_audit` | passed |
| `//products/perceptual-grade-next-blender/tests:handbook_audit` | passed |
| `//products/perceptual-grade-next-blender/tests:install_workspace` | passed |
| `//products/perceptual-grade-next-blender/tests:installed` | passed |
| `//products/perceptual-grade-next-blender/tests:installed_animation` | passed |
| `//products/perceptual-grade-next-blender/tests:bake_installed` | passed |
| `//products/perceptual-grade-next-blender/tests:bake_workspace_installed` | passed |
| `//products/perceptual-grade-next-blender/tests:compositor_gui` | passed |
| `//products/perceptual-grade-next-blender/tests:compositor_carriers` | passed |
| `//products/perceptual-grade-next-blender/tests:gesture_undo_gui` | failed |
| `//products/perceptual-grade-next-blender/tests:gesture_drag_gui` | passed |
| `//products/perceptual-grade-next-blender/tests:image_save_gui` | passed |
| `//products/perceptual-grade-next-blender/tests:stack_helper` | passed |
