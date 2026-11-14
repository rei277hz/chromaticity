# Linux build and test results

- Commit: `b037f2d76c644119ec2c7a0bc73fe483898bb24d`
- Recorded at: 2026-11-14T01:48:36+00:00
- Run: https://github.com/rei277hz/chromaticity/actions/runs/43542332322

Counts represent the selected build targets and smoke suites, not individual test cases or the full monorepo suite.

## Linux build targets: 1/2 passed

Run outcome: **failed**. Command exit: `2`.

| Target | Result |
| --- | --- |
| `//products/perceptual-grade-next-blender:verify_policies` | passed |
| `//products/perceptual-grade-next-blender:extension` | failed |

Reporting notes:

- build-report.json: the build command did not report complete success

## Linux smoke suites: 12/41 passed

Run outcome: **failed**. Command exit: `2`.

| Target | Result |
| --- | --- |
| `//products/perceptual-grade-next-blender:publication_compare_parameter_policy` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_preparation` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_preparation_join` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_node` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_helper` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_verification` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_resources` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_image_publication` | passed |
| `//products/perceptual-grade-next-blender/tests:policy_gesture` | passed |
| `//products/perceptual-grade-next-blender/tests:preparation_runtime` | failed |
| `//products/perceptual-grade-next-blender/tests:lut_worker` | failed |
| `//products/perceptual-grade-next-blender/tests:lut_shader` | failed |
| `//products/perceptual-grade-next-blender/tests:preparation` | failed |
| `//products/perceptual-grade-next-blender/tests:color_preparation` | failed |
| `//products/perceptual-grade-next-blender/tests:lut` | failed |
| `//products/perceptual-grade-next-blender/tests:lut_gpu` | failed |
| `//products/perceptual-grade-next-blender/tests:reference` | failed |
| `//products/perceptual-grade-next-blender/tests:boundary_resource` | failed |
| `//products/perceptual-grade-next-blender/tests:native` | failed |
| `//products/perceptual-grade-next-blender/tests:stages` | failed |
| `//products/perceptual-grade-next-blender/tests:stage2` | failed |
| `//products/perceptual-grade-next-blender/tests:color_stages` | failed |
| `//products/perceptual-grade-next-blender/tests:persistent_color_stages` | failed |
| `//products/perceptual-grade-next-blender/tests:persistent` | failed |
| `//products/perceptual-grade-next-blender/tests:guards` | failed |
| `//products/perceptual-grade-next-blender/tests:saturation` | failed |
| `//products/perceptual-grade-next-blender/tests:full` | failed |
| `//products/perceptual-grade-next-blender/tests:grade_render_preflight` | failed |
| `//products/perceptual-grade-next-blender/tests:gate_policy` | failed |
| `//products/perceptual-grade-next-blender/tests:hdr_metrics` | failed |
| `//products/perceptual-grade-next-blender/tests:architecture` | failed |
| `//products/perceptual-grade-next-blender/tests:policy_coverage` | passed |
| `//products/perceptual-grade-next-blender/tests:package` | failed |
| `//products/perceptual-grade-next-blender/tests:publication_compare_package` | passed |
| `//products/perceptual-grade-next-blender/tests:install_workspace` | passed |
| `//products/perceptual-grade-next-blender/tests:installed` | failed |
| `//products/perceptual-grade-next-blender/tests:compositor_gui` | failed |
| `//products/perceptual-grade-next-blender/tests:gesture_undo_gui` | failed |
| `//products/perceptual-grade-next-blender/tests:gesture_drag_gui` | failed |
| `//products/perceptual-grade-next-blender/tests:image_save_gui` | failed |
| `//products/perceptual-grade-next-blender/tests:stack_helper` | failed |

Reporting notes:

- test-build-report.json: the build command did not report complete success
