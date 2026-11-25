# Contributing and publishing

Perceptual Grade is developed in
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity). Submit
[issues](https://github.com/rei277hz/perceptual-grade/issues) for product
problems and [pull requests](https://github.com/rei277hz/chromaticity/pulls)
for source, tests, documentation, and translations.

The analytic reference in `libraries/perceptual-grade-reference` defines model
mathematics. Blender and Resolve each own their host adapter and observable
behavior. The [model chapter](contributing-model.md) describes where a change
belongs. Update the relevant product tests and this report when a change
affects documented behavior. Keep source comments that point into the report
aligned with its stable anchors.

Choose focused Buck2 build and test targets for the changed behavior, then run
them with `--remote-only`. Product package commands and target ownership are
listed in [Building Perceptual Grade](building.md). Book edits also need the
report audit and the applicable site or print build. The
[Documentation and media](documentation.md),
[Testing and measurements](testing.md), and [Publishing](publishing.md)
chapters describe those workflows.

Keep each change reviewable. Record the user-visible behavior, the affected
model or adapter boundary, and the evidence used to validate it. Publish the
book site through the declared Buck target after the authored and generated
outputs have been reviewed.
