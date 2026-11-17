# Tone

Tone maps neutral input luminance to a perceptual lightness curve. Complete
Linear first, then set the curve's input landmarks and diffuse/peak reference.

## Set the landmarks

Tone exposes Black, Shadows, Midtones, White, and Highlights input levels in
nits. Black maps to black; Shadows, Midtones, and White map to their respective
neutral lightness anchors; Highlights maps to the configured peak anchor. These
are soft curve landmarks, not hard clamps or independent output values.

Place the levels according to the image. An SDR image may keep most tones near
or below diffuse white. In HDR, distinguish a diffuse surface from emissive or
specular peaks instead of moving ordinary midtones toward the brightest pixel.
The curve fit changes how closely the curve approaches each control point and
how narrowly each point influences its neighbors. Peak selects one of the
supported neutral peak targets.

The shared Grade and Stack controls are static. A Grade converted to
**Node-Owned Grade** can animate numeric controls other than the discrete Peak
selection. Keyframes live on the containing node tree's Action and are shared by
all users of that tree.

## Evaluate the curve

Inspect the Grade output and the rendered/viewed image under the intended scene
display transform. A tone adjustment changes the signal consumed by Color, so
after moving a landmark recheck selective Color work. Use Blender's image and
Viewer displays to compare the result while editing a selected Stack Grade.

The [Tone model](https://rei277hz.github.io/perceptual-grade/technical/en/theory/tone.html) details the smooth interpolation and its
reference-lightness scale.
