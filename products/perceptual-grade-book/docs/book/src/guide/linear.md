# Linear

Linear performs an exact matrix transform before the nonlinear Tone and Color
stages. It establishes a useful exposure and color balance for the rest of the
grade.

## Exposure and source white

**Exposure** is measured in stops; +1 doubles scene-linear RGB. Set it early so
the image uses a useful signal range, then avoid using it to erase highlight
detail. The source-white x and y controls set the chromaticity that Stage 1
adapts. Use **Match White** to return the source white to D65.

The displayed Working White label is fixed at D65 in this Next version. The
Linear controls also include Cyan-Red and Yellow-Blue **Balance**, **Spread**,
and **Heading**. Balance changes the relative exposure of opposing colors;
Spread changes the reference displacement from white; Heading rotates that
direction in the xy plane. These controls combine into the Grade's matrix.

For a white-balance correction, choose a neutral surface photographed under the
lighting you want to correct. Adjust source white until that surface is neutral,
then inspect other colors and skin tones. If the neutral moves correctly but
colored surfaces remain wrong, use Balance, Spread, or Heading for the broad
relationship. They affect the whole image, not one sampled patch.

Blender decodes each Image Texture according to its Color Space setting. Check
that input setting before grading; an incorrect transfer function or gamut
cannot be repaired reliably by the Grade. The scene working color space is
handled by the node's scene adapter. Next supports Linear Rec.709, Linear
Rec.2020, and ACEScg.

An ordinary Grade evaluates Stage 1 as an exact matrix before its native
nonlinear stages. In a Grade Stack, the complete ordered transform is sampled
together. See [working spaces](working-white.md) for how those sampling
coordinates relate to scene RGB.
