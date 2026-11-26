# Grade in three stages

A Grade applies three connected stages: **Linear** establishes exposure, white
balance, and broad color relationships; **Tone** maps scene luminance to
perceptual lightness; **Color** shapes lightness and chroma by tone and hue.
Adjust them in that order, checking the complete image after each stage.

Start with a neutral reference and a correctly decoded input. In Linear, correct
the cast and set an overall level without forcing highlights to white. In Tone,
place the black, shadow, midtone, white, and highlight anchors for the image's
dynamic range. In Color, make selective changes while watching skin, neutrals,
and saturated colors together. A single grade is a global transform, so it
cannot compensate for local lighting or an incorrect input color profile.

The extension exposes the full numeric Stage 3 controls in the sidebar. **J** adjusts
lightness response by low/high chroma and opponent direction. **C** adjusts
chroma response using the same drivers, plus global chroma gain. **Adaptance**
sets opponent-space targets at Shadows, Midtones, White, and Highlights with a
shared half-influence saturation. **Warp** uses a six-handle cyclic color web at
the four non-black tone anchors: chroma is expressed in stops, hue as the stored
degree offset, and Scale in stops. Each family is interpolated smoothly across
tone. The draggable Warp diagram is not part of this control set; use its numeric
fields.

The numerical grading model uses frozen post-Tone selectors and signed energy.
The order is J/C response, Warp hue/chroma and positive Scale selection,
selective Adaptance, H–K repair, then Scale on the repaired opponent coordinates
and Scale squared to energy. The H–K guard runs before Scale. The output boundary separately
projects values into the supported RGB cube when required.

Keep exposure, view transform, and input decoding consistent while comparing
versions of a grade. Scene-linear values can exceed display white; judge them
through the intended display transform rather than clamping source highlights.

Continue with [Linear](linear.md), [Tone](tone.md), and [Color](color.md).
