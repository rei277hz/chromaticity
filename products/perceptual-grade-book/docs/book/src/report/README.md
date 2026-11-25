# Technical Report

This report documents Perceptual Grade's analytic model, product
implementations, and development contracts. The model chapters follow
`libraries/perceptual-grade-reference`. Product chapters cover the Blender
extension and the Resolve DCTL chain, with source and test evidence for
observable behavior.

The analytic reference defines the model's forward transform and inverse
contract. Product adapters organize controls and execution around host
constraints. Their implementation details can differ at export boundaries,
so the report identifies the reference equations separately from product
execution paths.

The companion [User Manual](https://rei277hz.github.io/perceptual-grade/manual/en/index.html)
describes Blender workflows in English and Simplified Chinese. It retains one
archived extension ZIP as its sole extension download. The current model and
product chapters describe the active implementation.

`products/perceptual-grade-book/technical-report-audit.json` records chapter
scope, source and test evidence, and stable policy anchors. The report audit
checks chapter coverage and source references. Reviewers also verify that each
claim matches the implementation.

Submit [issues](https://github.com/rei277hz/perceptual-grade/issues) to the
downstream project and [pull requests](https://github.com/rei277hz/chromaticity/pulls)
to this development repository. Both books' GitHub toolbars link here.
