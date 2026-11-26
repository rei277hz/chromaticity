# Color

Color is Stage 3. It adjusts appearance after Linear and Tone, with smooth
controls across tone, chroma, and hue. The sidebar separates the numeric controls
into **J**, **C**, **Adaptance**, and **Warp**.

## J and C response

J changes perceptual lightness response and C changes chroma response. Each
family has four tone anchors: Shadows, Midtones, White, and Highlights. At each
anchor, low/high chroma weights adjust the radial contribution, while a/b values
adjust opponent directions. The fit controls shape the blending across tone;
Global C Gain applies an overall chroma multiplier.

Use small values first. J changes can alter contrast or emphasize a subject;
changes to C can strengthen or quiet color. Inspect neutrals and saturated
colors while adjusting, because a large adjustment can affect colors beyond the
intended subject.

## Selective Adaptance

Adaptance assigns a/b target coordinates at Shadows, Midtones, White, and
Highlights. Its saturation parameter sets where the correction reaches half
influence. Use it for a targeted appearance shift across selected tonal ranges;
it is not the Linear white-balance control.

The two coordinates form one radial destination. The extension shortens an out-of-range
request along its direction so the calibrated cone responses remain valid;
it does not clip a and b independently. **Limited** marks a sampled request
whose effective destination must be shortened, such as an animated value.
The normal slider spans are ±4, ±10, ±20, and ±25 for Shadows, Midtones, White,
and Highlights, with a 0.01 drag increment. Typed values are not rounded to
that increment. These are editing spans; the valid radial
boundary depends on the tone anchor. A nonfinite request fails visibly.

## Warp color web

Warp supplies six cyclic color handles—red, yellow, green, cyan, blue, and
magenta—at each of the four tone anchors. Chroma values are log2 changes in
stops. Hue values are the stored degree offsets. Scale values are also in stops
and determine the common positive scale used after the H–K repair. The controls
interpolate around the cyclic web and between tone anchors. The current UI has
numeric fields and does not provide a draggable diagram.

Neighboring destination hues keep at least 4° of cyclic separation, including
the magenta-to-red seam. An edit pins the selected hue and pushes neighbors
when needed, in either direction around the web. Later edits of the initiating
hue solve its automatic return positions together, approaching each saved
position as far as neighboring gaps allow. A blocked return stays pending.
Editing one of those hues yourself starts from its current position
and detaches only that hue from the earlier automatic adjustment.

Changing Peak clears the automatic return relationships and resolves the new
hue geometry and Adaptance limits together. Shared Grades keep their automatic
relationships across frame changes. A node-owned Grade clears them when the
actual frame or subframe changes. If interpolated animation violates the hue
gaps, evaluation projects the angles into the valid range and shows **Limited**; it does
not rewrite stored values or keyframes.

Review the entire image after changing Warp. Its evaluation uses frozen
post-Tone selectors, then performs J/C response, Warp hue/chroma and Scale
selection, selective Adaptance, H–K repair, and finally applies Scale to the
repaired opponent coordinates and Scale squared to signed energy. This order preserves the
reference model's guard-before-Scale contract. RGB cube containment is a
separate output-boundary operation.

Node-owned Grades expose their Stage 3 values to Blender keyframing. Shared
Grades and Stack entries remain static. A Stack samples all enabled forward
Grades into a single 33³ preview and then a 65³ final transform; see [Grade
Stacks](inverse-stack.md).
