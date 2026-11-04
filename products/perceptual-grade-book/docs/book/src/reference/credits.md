# Credits and references

Perceptual Grade is developed by Rei277Hz. Its current monorepo source, including
DCTL, is available under `MIT OR Apache-2.0`; packaged Blender extensions and
their Corresponding Source are additionally offered under `GPL-3.0-or-later`.
Its analytic DCTL and native extension share the grading model. See the
[License](license.md) for the current policy and the separate historical downloads.

## Color appearance

Hellwig and Fairchild, [Brightness, lightness, colorfulness, and chroma in CIECAM02 and CAM16](https://doi.org/10.1002/col.22792), 2022.

Hellwig and Fairchild, [Extending CIECAM02 and CAM16 for the Helmholtz–Kohlrausch effect](https://doi.org/10.1002/col.22793), 2022.

Hellwig and Fairchild, [Revising CAM16-UCS](https://doi.org/10.2352/CIC.2022.30.1.48), 2022.

[Colour’s Hellwig2022 implementation](https://colour.readthedocs.io/en/develop/_modules/colour/appearance/hellwig2022.html), used as a primary model reference.

[Colour’s von Kries adaptation implementation](https://colour.readthedocs.io/en/develop/_modules/colour/adaptation/vonkries.html), for CAT16 adaptation.

The native Stage 2 graph and NumPy scope implementation share the DCTL’s modCAM16 coordinates, H–K compensation, hue eccentricity, default calibration and monotone softplus remapping. The tool adds its own signed-value extension, tonal coefficient model, Adaptance weighting, hue-concentration controls and bounded H–K inverse guard. These engineering choices are described in the theory chapters.

## Robust statistics

Hubert, Rousseeuw and Verdonck, [A deterministic algorithm for robust location and scatter](https://wis.kuleuven.be/stat/robust/papers/2012/DetMCD.pdf), 2012, supplies the DetMCD algorithm used for diagnostic contours. The implementation is original, using six deterministic starts, Qn scales, concentration steps and reweighting. No code from robustbase or scikit-learn is included. Its contours describe diagnostic pixel distributions and never feed the grading calculation.

The article appears in *Journal of Computational and Graphical Statistics*
21(3), 618–637. The original NumPy implementation now lives in
`libraries/perceptual-grade-core/src/perceptual_grade_core/model/statistics.py`.
It is a two-dimensional, bounded-sample implementation using asymptotic Gaussian
corrections and documented degenerate/display fallbacks.

## Host and build tools

Perceptual Grade runs as an extension inside [Blender](https://www.blender.org/). The extension implements the grading controls, scopes and render methods using Blender’s node system and color-management facilities.

The Perceptual Grade DCTL runs inside DaVinci Resolve. [Blackmagic Design’s documentation](https://www.blackmagicdesign.com/support/family/davinci-resolve-and-fusion) describes the host; use the DCTL Developer documentation shipped with your build for its interface.

[Buck2](https://buck2.build/) builds generated resources, packages and tests.

[mdBook](https://rust-lang.github.io/mdBook/), licensed under MPL-2.0, generates this static handbook.

[KaTeX](https://katex.org/), licensed under MIT, renders equations using version-pinned JavaScript, CSS, and fonts from jsDelivr. The script and stylesheet use integrity hashes; their payloads are not included in the deployment archive.

The build pins actual dependency releases and hashes. Third-party documentation notices are available as [mdBook](../downloads/licenses/mdbook-LICENSE) and [KaTeX](../downloads/licenses/katex-LICENSE) license files.

## Tutorial and chapter organization

The ColorChecker2014 reference EXR is supplied by [colour-science/colour-nuke](https://github.com/colour-science/colour-nuke) at the pinned commit recorded in `third_party/book/pins.bzl`. It is distributed with the project’s [BSD license](../downloads/licenses/colour-nuke-LICENSE).

The [ACES Output Transform structure documentation](https://docs.acescentral.com/system-components/output-transforms/technical-details/rendering-overview/) provides an example of explaining processing stages through purpose, equations and interleaved numerical figures. The handbook’s calculations and figure producers describe Perceptual Grade’s own model.

## Theme and reference illustrations

The reading theme adapts [ACES Documentation](https://docs.acescentral.com/)’s Pontano Sans typography, neutral palette, gold rule and navigation layout. Its [extra.css](https://docs.acescentral.com/stylesheets/extra.css) is Copyright Contributors to the ACES Documentation, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The adaptation changes layout, contrast and mdBook integration. The mdBook layout and reader controls are adapted for this handbook. Text uses Pontano Sans and code uses Roboto Mono, loaded as version-pinned WOFF2 files from the Fontsource distribution on jsDelivr. Their SIL Open Font License 1.1 notices are available for [Pontano Sans](../downloads/licenses/pontano-sans-OFL.txt) and [Roboto Mono](../downloads/licenses/roboto-mono-OFL.txt).

The appearance introduction reproduces Figures 2 and 3 from Agahian and Stolitzka, [Modeling Perceived Brightness in HDR Displays](https://doi.org/10.2352/CIC.2025.33.1.7), 33rd Color and Imaging Conference (2025), pp. 31–34. The figures are unmodified reference illustrations, with original authorship retained; they are replaceable source assets for review. They retain the copyright of the 2025 Society for Imaging Science and Technology publication and are not covered by the project’s original-artwork license grant. They describe the published model, not measurements of this tool. Source details and hashes are kept in docs/data/appearance-references.json.

[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) supplies the pinned FFmpeg binary used to convert screen recordings; Pillow encodes the paired and introductory WebP demonstrations.
