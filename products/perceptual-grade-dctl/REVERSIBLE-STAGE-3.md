# Reversible Color J/C and Warp

Positive Midtones C Contrast reduces chroma on the muted side of C Center and
increases it on the vivid side. C Width controls how gradually that change
takes effect. Four tonal amounts share this pair of controls. The four J
controls set the **local lightness stretch** for colored samples at those
tones. Positive Midtones J Contrast increases the spacing of vivid midtone
lightnesses and compresses the spacing of muted ones. Exact gray follows Tone.

## Node connections and inverse scope

XYZ Input encodes the three signed modCAM16 cone responses, each strictly
inside `(-400, 400)`. Tone, Color J/C and Warp consume and return this same
triplet. These nodes open each component `r` into a grading coordinate
`u`. For `|r| <= 200`, `u = r`. Beyond that,
`u = sign(r) * 40000 / (400 - |r|)`. Closing the chart uses the identity up to
200 and `r = sign(u) * (400 - 40000/|u|)` beyond it. The open chart permits a
finite grade anywhere along an extended cone axis without clipping it to a
physical pole. Its appearance coordinates are signed achromatic lightness
`J_A` and the two opponent coordinates `a,b`, with `C = hypot(a,b)`.

For valid settings each Stage 3 operation has one real-valued inverse on this
domain. In Resolve, float32 quantization limits recovery, particularly near a
cone pole, on a compressed hue interval or after a large chroma reduction.
When a result rounds all the way to a pole, the cone nodes propagate an
invalid triplet and XYZ Output displays a magenta diagnostic.

To check a round trip against the post-Tone image, insert copies in this order
before XYZ Output and keep the paired settings identical.

```
Color J/C Forward -> Warp Forward -> Warp Inverse -> Color J/C Inverse
```

The inverse covers Stage 3 within the cone chain. Tone can clip at its black
level. XYZ Output can repair the final physical appearance using its own signed
energy before decoding to XYZ for the downstream RGB conversion. A host that
also applies AP1-D65 boundary mapping would place that mapping after this
repair. Resolve uses open-range XYZ export.

## How Color J/C preserves order

1. At fixed `J_A` and hue, the C curve remaps radius. Its amount blends the
   two adjacent tonal controls using `|J_A|`. Let `C*` be the crossover
   `(35/75) * |J_A| * center/(1-center)` and `W = 1 + 2*width`. For either
   side of the crossover, the distance `d = |ln(C/C*)|` maps to
   `W * ln(1 + 2^(amount/W) * (exp(d/W) - 1))`. This increases strictly
   with `d` and preserves the side of the crossover. A final uniform gain in
   stops scales the result. The inverse removes that gain and evaluates the
   same ordered curve with the opposite amount. At `J_A = 0` chromatic samples
   use the vivid limit. Multiplication preserves exact gray.
2. Using the resulting fixed `C`, the J curve maps `|J_A|` along the tone
   axis. Each tonal setting supplies a local slope in stops, weighted by the
   saturation response at **that anchor**. The J response fades with cubic
   smoothstep from gray to full strength at normalized saturation `0.10`.
   The slope equals one at black and remains positive along the entire axis,
   holding the Highlights slope above the final anchor. The kernel integrates
   the smoothly blended slopes and restores the sign of `J_A`. Moving a lower
   anchor can shift higher lightnesses, even where their local slope is one.
   The inverse solves the same increasing integral, then undoes the C curve
   at the recovered `J_A`.

## How Warp preserves order

1. **Hue and chroma.** `|J_A|` selects the tone rows and stays fixed throughout
   the web edit. Integer hue offsets move six Rec.709 handles. All six target
   hue gaps, including magenta back to red, must remain positive in every row.
   Interpolation preserves that order between rows. At fixed incoming chroma,
   the hue map increases around the ring and fades toward gray. At fixed
   destination hue, the radial chroma map increases from zero through the
   edited handle radius. The inverse solves the radius first, then the angle
   using the recovered chroma.
2. **Adaptance.** At a given `|J_A|`, the interpolated `a,b` target gives the
   displacement of a neutral sample. Samples flow parallel to that direction,
   moving more slowly as chroma increases. For target length `L`, let `u` run
   along the target, `v` perpendicular to it and `K = halfSaturation * |J_A|`.
   The integral of `K^4 + (u^2 + v^2)^2` increases with `u`. The forward grade
   advances the integral by `K^4 * L + L^5/5`, so neutral reaches its target.
   The inverse subtracts that same travel. A zero target leaves the sample
   alone. The target fades to zero toward black.
3. **Scale.** The post-Adaptance direction in `(J_A,a,b)` selects the hue and
   the relative chroma. Along each ray, the neutral H-K tonal anchors define
   the positions of four scale controls. Each sets a **positive local slope**
   `2^stops` at its position, with the stop response fading near the neutral
   axis. The slope holds its Shadows value up to the Shadows anchor and its
   Highlights value above the Highlights anchor. The integrated slope increases
   from radius zero, so stronger settings cannot move an inner point past an
   outer point on the ray. A `+1` local scale doubles the spacing of nearby
   radii at full influence. The inverse recovers radius on the same ray before
   undoing Adaptance and the web.

## Decisions for Resolve audition

| Design choice | Current behavior | Flexibility before promotion |
| --- | --- | --- |
| Saturation centers and widths | J and C have independent centers and widths. Each family shares its shape across four tones. The curve uses log distance on either side of the center. | High. Shape, log-like response and calibration can change if the C curve stays ordered and its inverse follows it. |
| Near-gray response | J fades at normalized saturation 0.10. C keeps its full relative low-chroma response and preserves exact gray. Warp scale fades at `C / hypot(J_A,C) < 0.10`. | High. Thresholds and fade shapes can be auditioned separately. A new C fade requires checking monotonicity. |
| J and scale slider meaning | Stops set a local slope. Integrating it gives the lightness or radius at and beyond the selected tone. | Medium. Knot placement, blending and slider calibration can change while keeping positive slopes. |
| Hue displacement | Six integer degree offsets per row preserve the reference hues at reset. Crossing or coincident handles produce a diagnostic. | Medium. A different UI can encode positive gaps directly. Every valid ring must stay ordered. |
| Adaptance and half saturation | Neutral lands on the requested target. Half saturation selects the scale where instantaneous motion at fixed `J_A` is half its neutral speed. | Medium. The decay law can change if travel remains one-to-one and its inverse uses the same calibration. |
| Selectors and operation order | C uses fixed `J_A`. J uses resulting C. The web and Adaptance use fixed `J_A`. Scale uses a fixed ray direction. | Low. Changing an operation's own selector during its forward and reverse passes requires a new invertibility argument. |
| H-K repair | XYZ Output repairs once, from final physical signed energy. Both Stage 3 directions operate on the cone data upstream. | Low. This boundary defines which values an inverse can recover. |

## Resolve audition and promotion

1. Compare Midtones C Contrast at `+1` and `-1` on muted-to-vivid ramps while
   moving C Center and C Width. Repeat with J Contrast on neutral and colored
   lightness ramps. Check the handoff into White and Highlights.
2. Test an Adaptance tint on neutral, skin and saturated patches. Change half
   saturation to judge its reach. Sweep scale on a bright saturated ray with
   opposite settings in adjacent rows, then move the red and magenta hues
   toward each other across the wraparound. Check the diagnostic at crossing.
3. Compare the paired Forward/Inverse chain with the same nodes bypassed on
   negative, dark and HDR material. Use identical input and output conversion
   on both branches. Inspect both Color nodes alone and together.
4. Record the settings, sample material and design decisions accepted in
   Resolve. Implement that accepted behavior in `libraries/perceptual-grade-reference`,
   then propagate it to `products/perceptual-grade-next-blender`.
