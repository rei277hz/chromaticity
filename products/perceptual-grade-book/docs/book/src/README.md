# Introduction

> **A maintained handbook:** this publication aims to keep up with the latest
> Perceptual Grade. Its User Manual describes the 1.23.2 interface and workflow;
> those instructions, host recordings, and much of the runtime engineering text
> still lag behind the current reference. Downloads and measurements retain
> their original version and scope. Chapters identify the product or model they
> describe.

Perceptual Grade connects white balance, a custom tone curve, and selective
color adjustments in three stages. Blender implementations provide nodes for
Shading and Compositing; the retained DCTL runs in DaVinci Resolve. Their
available controls and Stage 3 policies differ from the latest reference, so
check the implementation profile when reproducing a grade.

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
everyday workflow below retain the 1.23.2 interface; they have not been updated
for Next or the current reference's Warp controls.

Start with [installation](guide/install.md), then [grade in three
stages](guide/workflow.md). Choose your white and color directions in
**Linear**, place important scene tones in **Tone**, and refine lightness,
chroma, adaptance, and hue in **Color**. The [Technical
Report](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
covers the current analytical model, its calculations, and the engineering
behind the implementations.

See the [credits](reference/credits.md) for appearance-model papers and
implementation references, and the [license](reference/license.md) for
licensing.
