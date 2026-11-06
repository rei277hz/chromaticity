# Introduction

> **Version scope:** the guide, the downloads and the recorded measurements
> document Perceptual Grade 1.23.2. [Understanding the model](theory/structure.md)
> follows the analytic reference model in `libraries/perceptual-grade-reference`,
> which has moved past 1.23.2. Each chapter states which of the two it describes.

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) is the
downstream code snapshot, currently containing the preserved Perceptual Grade
v1.23.2 code from the 2026-11-01 build, not Perceptual Grade Next. It accepts
[issues](https://github.com/rei277hz/perceptual-grade/issues),
but does not accept pull requests. Submit pull requests to the development
repository, [rei277hz/chromaticity](https://github.com/rei277hz/chromaticity/pulls).
See [Contributing](development/contributing.md) for the repository roles.

Perceptual Grade connects white balance, a custom tone curve, and selective color adjustments in three stages. Its Blender extension provides a Perceptual Grade node for Shading and Compositing; its analytic DCTL runs in DaVinci Resolve. The two implementations share the same grading model and controls.

<figure class="grade-demo"><img src="assets/intro/match-three-images.webp" data-still="assets/intro/match-three-images-still.webp" alt="Matching three differently lit images" loading="eager"><figcaption>Match three differently lit images. The supplied recording is a replaceable demonstration placeholder.</figcaption></figure>

<!-- Bilibili player proof of concept. Replace the video URL before enabling.
<div class="video-embed">
<iframe src="https://player.bilibili.com/player.html?isOutside=true&amp;aid=116325414341794&amp;bvid=BV17H9GBNEfJ&amp;cid=37150327813&amp;p=1" title="Perceptual Grade video on Bilibili" width="1280" height="720" scrolling="no" frameborder="0" allow="fullscreen" allowfullscreen></iframe>
</div>
-->

<div class="download-grid">
<a class="download primary" href="downloads/perceptual_grade-v1.23.2-20261101.zip"><strong>Get the development extension</strong><span>Perceptual Grade 1.23.2 · 2026-11-01</span></a>
<a class="download" href="downloads/Perceptual-Grade.dctl"><strong>Get the DCTL</strong><span>DaVinci Resolve: English</span></a>
<a class="download" href="downloads/Perceptual-Grade-zh-HANS.dctl"><strong>Chinese DCTL</strong><span>DaVinci Resolve: Simplified Chinese</span></a>
</div>

The download is a Perceptual Grade 1.23.2 development build dated 2026-11-01.
It packages the preserved Perceptual Grade implementation, not Perceptual Grade
Next, and replaces the original extension download. Installation and the
everyday workflow below describe that build and have not been updated for the
development build.

Start with [installation](guide/install.md), then [grade in three stages](guide/workflow.md). Choose your white and color directions in **Linear**, place important scene tones in **Tone**, and refine lightness, chroma, adaptance and hue in **Color**.

The handbook explains everyday use first. [Understanding the model](theory/structure.md) then follows the calculations and their numerical illustrations. Developers can start with [architecture](development/architecture.md), [building and testing](development/building.md), or [contributing](development/contributing.md).

The model part and the guide describe different stages, and the difference is not cosmetic. The 1.23.2 controls include Hue Concentration, Adaptance Strength and Fit, and the global low-chroma and high-chroma Hue coefficients. The analytic reference replaces them with a tonal web of six hue handles across four tonal rows, a selective cone Adaptance driven by direct neutral destinations, and a final chroma scale. Saved settings are not reinterpreted from one to the other. The [Color chapter](theory/color.md) describes the reference stage and keeps the 1.23.2 controls in a separately labelled section, so you can tell which one a sentence belongs to.

The supplied downloads are packaged with this book through Buck2. See the [credits](reference/credits.md) for the appearance-model papers and implementation references, and the [license](reference/license.md) for licensing.
