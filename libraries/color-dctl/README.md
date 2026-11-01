# DCTL color primitives

`src/linear.dctlh` provides `ColorMat` and the `color_*` matrix, CAT16,
chromaticity, Rec.709 and sRGB helpers. It has no UI globals, product controls,
viewing-condition policy, grading model or overlay state.

Consumers declare a Buck dependency on `//libraries/color-dctl:linear` and
include that source once before their own types/functions. Perceptual Grade's
generator embeds it into the standalone DCTL; there is no runtime include or
installation dependency. The product's numerical and portability tests compile
and exercise these exact helpers through the emitted DCTL.
