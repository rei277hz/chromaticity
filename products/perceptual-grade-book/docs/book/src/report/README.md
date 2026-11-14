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
Next's current policies; Next has not yet implemented Warp.

The User Manual covers installation and the everyday 1.23.2 workflow. See the
[User Manual](https://rei277hz.github.io/perceptual-grade/manual/en/index.html)
for those instructions and the packaged downloads.

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) is the
downstream code snapshot repository. It currently contains preserved
Perceptual Grade v1.23.2 code from the 2026-11-01 build, not Perceptual Grade
Next. It accepts
[issues](https://github.com/rei277hz/perceptual-grade/issues), but does not
accept pull requests. Submit pull requests to the development repository,
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity/pulls).
