# Color

> **Preserved release:** this usage chapter and its captures describe 1.23.2 and still lag the latest model. See [Understanding the model](../theory/structure.md) for the current reference; these controls do not describe Next’s future Warp implementation.

Keep the Linear and Tone results. Each operation below adds to the preceding one in both examples; do not reset between recordings. A stays SDR, B stays HDR. In Resolve, use the named Perceptual Grade DCTL sliders given beside each demonstration.

Select a tone with its curve dot, S/M/W/H label or waveform indicator. The curve height is the strength of an adjustment, not a final pixel value. Cₗ favors lower-chroma colors and Cₕ favors higher-chroma colors, with smooth weights. The scope shows the selected input-tone region after grading.

## Lightness J curve: two tones in each image

Choose Lightness J and the Cₗ curve. In A, open Shadows and give White a little more presence. In B, open Midtones and restrain Highlights. Both images use the same kind of handle twice, on two tonal regions, to serve different purposes.

<figure class="grade-demo">
<img src="../assets/demos/color-j.webp" data-still="../assets/demos/color-j-still.webp" alt="Lightness J: A adjusts Shadows and White; B adjusts Midtones and Highlights." loading="lazy">
<figcaption>Lightness J: A adjusts Shadows and White; B adjusts Midtones and Highlights.</figcaption>
</figure>

DCTL sliders: A uses Shadows Cₗ → J and White Cₗ → J; B uses Midtones Cₗ → J and Highlights Cₗ → J. Choose the corresponding Cₕ → J slider when working on higher-chroma colors instead. Lightness Fit controls how broadly the tonal coefficients blend.

## Lightness J and Chroma C curves: one shared tone

Select Midtones in both examples. Adjust the Cₗ → J curve, then switch to Chroma C and adjust Cₗ → C without changing that tone selection. A can lift a muted subject and add color; B can lower an overly prominent midtone and soften its color. The two receivers work together on the same tonal region.

<figure class="grade-demo">
<img src="../assets/demos/color-jc-curves.webp" data-still="../assets/demos/color-jc-curves-still.webp" alt="Both examples select Midtones and combine the Lightness J and Chroma C curves." loading="lazy">
<figcaption>Both examples select Midtones and combine the Lightness J and Chroma C curves.</figcaption>
</figure>

DCTL sliders: Midtones Cₗ → J and Midtones Cₗ → C. The corresponding higher-chroma controls are Midtones Cₕ → J and Midtones Cₕ → C. In a fully weighted chroma contribution, +1 doubles C and −1 halves it. Chroma Fit shapes the tonal reach; Global C Gain changes chroma across all tones.

## Lightness J and Chroma C a/b pads: one shared tone

Keep Midtones selected in both images. In the Lightness J pad, move the handle to raise one hue direction while lowering its opposite. Switch to Chroma C and shape the color strength along the same direction. A might emphasize a subject against its background; B might reduce a competing color while retaining the subject. These are paired J and C adjustments to the same tone in each image.

<figure class="grade-demo">
<img src="../assets/demos/color-jc-pads.webp" data-still="../assets/demos/color-jc-pads-still.webp" alt="Both examples use the Midtones a/b pads to combine directional lightness and chroma changes." loading="lazy">
<figcaption>Both examples use the Midtones a/b pads to combine directional lightness and chroma changes.</figcaption>
</figure>

DCTL sliders: Midtones a → J, Midtones b → J, Midtones a → C and Midtones b → C. Diagonal pad movement combines a and b. On the extension’s pads, +a points upward and +b points leftward, matching its vectorscope orientation.

## Adaptance pad: two tones in each image

Choose Adaptance. In A, reduce a cast in Shadows, then refine White. In B, correct Midtones, then refine Highlights. Watch a surface that should stay near-neutral in each region while moving each tone’s pad handle.

<figure class="grade-demo">
<img src="../assets/demos/color-adaptance.webp" data-still="../assets/demos/color-adaptance-still.webp" alt="Adaptance: A adjusts Shadows and White; B adjusts Midtones and Highlights." loading="lazy">
<figcaption>Adaptance: A adjusts Shadows and White; B adjusts Midtones and Highlights.</figcaption>
</figure>

In the DCTL, A uses Shadows Adaptance a, Shadows Adaptance b, White Adaptance a and White Adaptance b. B uses Midtones Adaptance a, Midtones Adaptance b, Highlights Adaptance a and Highlights Adaptance b.

Adaptance Strength controls the amount and chroma protection; Adaptance Fit controls the tonal blend. The pad’s mean cross and confidence range describe sampled near-neutral pixels, enlarged 5× to make small casts visible.

## Hue concentration pad: two tones in each image

Choose Hue and use its a/b concentration pad. In A, gather a distracting spread of hues in Shadows, then refine White. In B, gather hues in Midtones, then refine Highlights. Concentration draws hues toward the chosen direction and opens their spacing on the opposite side.

<figure class="grade-demo">
<img src="../assets/demos/color-hue-pad.webp" data-still="../assets/demos/color-hue-pad-still.webp" alt="Hue concentration: A adjusts Shadows and White; B adjusts Midtones and Highlights." loading="lazy">
<figcaption>Hue concentration: A adjusts Shadows and White; B adjusts Midtones and Highlights.</figcaption>
</figure>

DCTL sliders: A uses Shadows Hue Concentration a, Shadows Hue Concentration b, White Hue Concentration a and White Hue Concentration b. B uses Midtones Hue Concentration a, Midtones Hue Concentration b, Highlights Hue Concentration a and Highlights Hue Concentration b.

## Hue rotation: two tones in each image

Use the Hue rotation curve to turn colors together within a tone region. In A, steer Shadows toward one palette and White toward another. In B, steer Midtones and Highlights independently. Rotation turns the hue wheel; the preceding concentration operation changes the spacing around it.

<figure class="grade-demo">
<img src="../assets/demos/color-hue-rotation.webp" data-still="../assets/demos/color-hue-rotation-still.webp" alt="Hue rotation: A adjusts Shadows and White; B adjusts Midtones and Highlights." loading="lazy">
<figcaption>Hue rotation: A adjusts Shadows and White; B adjusts Midtones and Highlights.</figcaption>
</figure>

DCTL sliders: Shadows Hue and White Hue for A; Midtones Hue and Highlights Hue for B. Hue Fit controls how both rotation and concentration blend across tonal regions. Revisit the complete image after each adjustment, with all earlier work retained.

## Try a broader creative grade

Experiment with Global Cₗ → Hue and Global Cₕ → Hue yourself. They rotate lower- and higher-chroma colors with smooth weights across all tones. Combine them with the tonal controls to explore a more stylized palette.
