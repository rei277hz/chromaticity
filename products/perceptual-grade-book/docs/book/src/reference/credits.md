# Credits and references

Perceptual Grade is developed by Rei277Hz and its contributors. The current
analytic reference and product adapters are maintained in the
[chromaticity repository](https://github.com/rei277hz/chromaticity). See the
[License](license.md) for source and package terms.

## Color appearance

Hellwig and Fairchild, [Brightness, lightness, colorfulness, and chroma in
CIECAM02 and CAM16](https://doi.org/10.1002/col.22792), 2022.

Hellwig and Fairchild, [Extending CIECAM02 and CAM16 for the Helmholtz–Kohlrausch
effect](https://doi.org/10.1002/col.22793), 2022.

Hellwig and Fairchild, [Revising CAM16-UCS](https://doi.org/10.2352/CIC.2022.30.1.48),
2022.

[Colour's Hellwig2022 implementation](https://colour.readthedocs.io/en/develop/_modules/colour/appearance/hellwig2022.html)
is a primary implementation reference for the appearance model.
[Colour's von Kries adaptation implementation](https://colour.readthedocs.io/en/develop/_modules/colour/adaptation/vonkries.html)
is a reference for CAT16 chromatic adaptation.

## Product hosts and tools

The Blender extension uses Blender's node, compositor, and color-management
systems. The Resolve DCTL product uses DaVinci Resolve's DCTL interface and
GPU execution. Refer to the documentation distributed with the installed host
for its version-specific behavior.

[Buck2](https://buck2.build/) builds products, generated resources, tests, and
documentation. [mdBook](https://rust-lang.github.io/mdBook/) generates the
static books. [KaTeX](https://katex.org/) renders equations in the site and
print outputs.

The book uses the ColorChecker2014 reference EXR from
[colour-science/colour-nuke](https://github.com/colour-science/colour-nuke),
at the pinned commit in `third_party/book/pins.bzl`, under its BSD license.
Third-party licenses and notices are included with the publication where
required.

## Theme and illustrations

The reading theme adapts typography, navigation, and layout from
[ACES Documentation](https://docs.acescentral.com/), under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The adaptation
changes layout, contrast, and mdBook integration.

The appearance introduction reproduces Figures 2 and 3 from Agahian and
Stolitzka, [Modeling Perceived Brightness in HDR Displays](https://doi.org/10.2352/CIC.2025.33.1.7),
33rd Color and Imaging Conference, 2025, pages 31–34. The figures retain their
original authorship and publication copyright. They illustrate the published
model and are not measurements of Perceptual Grade. Their source details and
hashes are recorded in `docs/data/appearance-references.json`.
