# Technical Report

> **A maintained reference:** this book aims to keep up with the latest
> Perceptual Grade. The model chapters follow the current analytic reference in
> `libraries/perceptual-grade-reference`. Some implementation and runtime
> engineering chapters still describe 1.23.2, while measurement records retain
> the version of the experiment. Each chapter identifies its scope; current
> model behavior should not be read as a claim about every released product.

This report covers the appearance model and grading calculations, evaluation
and interpolation, the H–K guard, and the architecture and development history
of the project. Historical implementation details and measurements remain
useful for understanding earlier products, but are labeled separately from the
current reference. The English-only Next Blender policy chapter describes
Next's current policies, including Stage 3 Warp and the five-image parameter
publication bundle.

For Blender behavior, `products/perceptual-grade-next-blender` is the current
authority: its source, requirements, and tests define the implemented routes,
state transitions, native evaluation, failure behavior, and host boundaries.
The analytic reference remains the authority for model mathematics. Any
observable Next change must update this report and link to the relevant source
or test evidence. The 1.23.2 implementation, user-facing workflow, downloads,
media, measurements, legacy generators, manifests, and preservation checks are
temporary migration material. The planned end state removes all of that legacy
content after Next coverage replaces it; this report currently retains the
historical labels and archive while that migration is coordinated.

The repository's `products/perceptual-grade-book/technical-report-audit.json`
records chapter scope, source and test evidence, policy anchors, and remaining
legacy replacement work. The Next Buck test `technical_report_audit` verifies
that coverage and the references. Reviewers also compare the prose with the
implementation; valid references alone do not establish semantic agreement.

The User Manual describes current Next node workflows and retains a clearly
labeled link to the legacy 1.23.2 ZIP. It does not offer a Next ZIP download.
See the [User Manual](https://rei277hz.github.io/perceptual-grade/manual/en/index.html)
for Blender setup and grading instructions.

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) is the
downstream code snapshot repository. It currently contains preserved
Perceptual Grade v1.23.2 code from the 2026-11-01 build, not Perceptual Grade
Next. It accepts
[issues](https://github.com/rei277hz/perceptual-grade/issues), but does not
accept pull requests. Submit pull requests to the development repository,
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity/pulls).
