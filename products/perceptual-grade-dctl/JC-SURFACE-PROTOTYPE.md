# Color-JC saturation surface prototype

One Resolve DCTL shapes lightness and chroma over tone and saturation. J and C
each have four tonal contrast amounts and a saturation center and width shared
by their four amounts. Overall Chroma Gain scales chroma uniformly at the
request stage. Tone handles neutral lightness, and Warp handles hue.

## Build and install

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_surface_prototype --show-output
```

The target produces `Perceptual-Grade-3A-Color-JC-Surface-Prototype.dctl` and
`Perceptual-Grade-3A-Color-JC-Surface-Prototype-zh-HANS.dctl`. Use the version
for your locale on a scene-linear XYZ D65 node. To compare the standalone
prototype with the cone Color J/C node, feed identical XYZ into two branches.
Place the prototype on one and XYZ Input → Color J/C → XYZ Output on the other.
Build Color J/C with `:standalone_tone_jc` and match Peak Nits.
[DCTL installation](README.md#install-and-use)

## Controls

| Control | Range | Default | Step |
| --- | ---: | ---: | ---: |
| J Contrast at Shadows, Midtones, White, and Highlights | -20 to +20 H-K points | 0 | 0.1 |
| C Contrast at Shadows, Midtones, White, and Highlights | -2 to +2 stops at saturation extremes | 0 | 0.01 |
| J Center and C Center | 0.05 to 0.95 | 0.50 | 0.01 |
| J Width and C Width | 0.05 to 1.00 | 0.50 | 0.01 |
| Overall Chroma Gain | -3 to +3 stops | 0 | 0.01 |
| Peak Nits | 500, 1000, 2000, 4000 | 1000 | Menu |

A positive J Contrast darkens colors below J Center and brightens colors
above it. A positive C Contrast reduces chroma below C Center and increases
chroma above it. Negative amounts reverse these effects. Both width controls
broaden their respective transitions around the center.

## Evaluation

The kernel freezes input chroma `C = hypot(a, b)`, signed achromatic lightness
`J_A`, and H-K magnitude `H = hypot(J_A, sqrt(66*C))`. For J and C separately,
it interpolates the contrast amounts between the adjacent tone anchors. At
fractional position `u` between two anchors, the blend weight is
`u*u*(3 - 2*u)`. It holds the endpoint amounts outside the anchor range. The
blend has zero slope at each anchor and stays within the two adjacent amounts.

The saturation coordinate is `s = C / (C + (35/75)*abs(J_A))`. For either
control family, let `m` be its center and `W = 1 + 2*Width` its width in
natural-log units. The center corresponds to `C* = (35/75)*abs(J_A)*m/(1-m)`.
For chroma and `abs(J_A)` both positive, define `z = ln(C/C*)` and
`h = 1 - exp(-abs(z)/W)`. The transition factor `h` reaches 0.5 at `abs(z) = W*ln(2)`.
At chromatic `J_A = 0`, the saturation coordinate is 1, and the response uses
the vivid limit.

For J, the requested lightness offset is `A_J * sign(z) * h`, where `A_J` is
the blended J Contrast amount. The kernel multiplies it by cubic smoothstep
from `s = 0` to `s = 0.10` and by the existing quintic black fade from zero
H-K magnitude to the Shadows anchor. Exact gray receives zero J offset.

For C, the blended contrast amount `A_C` remaps the distance `d = abs(z)` to

```
d' = W*ln(1 + 2^(A_C/W)*(exp(d/W) - 1))
```

The kernel retains the sign of `z` and evaluates the stop offset in a bounded
form using `h`.

```
contrastStops = sign(z)*W*log2(1 + (2^(A_C/W) - 1)*h)
```

The total chroma gain is `2^(contrastStops + Overall Chroma Gain)` and scales
the original `a,b`. The contrast offset is zero at C Center, approaches
`-A_C` near gray, and approaches `+A_C` at the vivid end. Exact gray stays
neutral.

For a nonzero combined request, the kernel updates signed energy for both
edits, applies H-K repair once, and decodes directly to signed linear XYZ D65
with an open range. Black, reset, and pixels whose requests preserve their
input state pass through exactly. Invalid parameters and decode failures use
the visible DCTL diagnostic.

## Inverse scope

At fixed incoming tone weights and `J_A`, the requested chroma before H-K
repair is strictly increasing. The inverse for that isolated remap divides
out Overall Chroma Gain, then applies the same contrast remap with `-A_C`.
The full grade inverse also depends on recalculating the selectors, coupling
between J and C, and the H-K repair. A single cubic tone interval can be
inverted when its endpoints differ and the interval is known. Across all four
anchors, repeated amounts can correspond to multiple input tones.

## Decision record

| Design choice | Prototype behavior | Flexibility | What to audition |
| --- | --- | --- | --- |
| Shared shape within each family | Four independently weighted amounts share that family's center and width | Medium. Per-tone shapes would add independent controls | Place one family at a time and compare crossover placement in Shadows, Midtones, White, and Highlights |
| Tone interpolation | Cubic smoothstep between adjacent H-K anchors with constant endpoint extension | Medium. A different interpolation may change handoffs between the existing anchors | Sweep tone ramps with alternating amounts and look for visible plateaus or steps |
| Saturation coordinate and center | A rational ratio puts the default center at `C = (35/75)*abs(J_A)` | High. The coordinate and center calibration can be tuned within the same control layout | Compare equal center settings on muted, vivid, and skin-like samples at different tones |
| Width calibration | `W = 1 + 2*Width` controls how quickly the transition reaches its saturation extremes | High. The slider range and mapping to `W` can be adjusted | Compare minimum, default, and maximum width, especially near each center |
| J near gray and black | The saturation fade reaches full strength at `s = 0.10`, and the black fade reaches full strength at the Shadows anchor | High. Fade endpoints and blend shapes can be tuned while preserving exact gray and black | Compare dark and near-neutral ramps with positive and negative J amounts |
| C near gray | Weak colors receive the relative chroma gain. Exact gray stays neutral | High. A different near-gray response would need to preserve ordering and update the inverse | Check pastel material and low-chroma ramps with positive and negative C amounts |
| C ordering and inverse | The requested C remap is ordered and invertible at fixed selectors before H-K repair | Low. Changes to the remap must preserve ordering | Inspect dense ramps around C Center and compare the requested separation with the result after repair |
| Overall Chroma Gain | A separate uniform gain in stops multiplies the contrast remap | High. Range and step can change independently of the surface | Adjust overall saturation with contrast zero, then combine both controls |

## Resolve audition and development path

1. Build the surface and LGG variants. Compare them on the same scene-linear
   XYZ node with identical input, Peak Nits, and display rendering. [LGG prototype design](JC-LGG-PROTOTYPE.md)
2. Test a neutral ramp, several muted-to-vivid ramps at the four tonal anchors,
   and skin-like material. Change one anchor at a time, then combine adjacent
   anchor amounts to evaluate how the cubic blends the edits.
3. Set Midtones C Contrast to `+1` and Overall Chroma Gain to `+0.5`. Compare
   with Midtones C Gamma at `-1` and C Gain at `+0.5` in LGG. Compare the
   separation of muted and vivid colors, and inspect each variant around its
   crossover. Move J and C centers and widths independently to judge which
   settings are useful across the four tones.
4. Record the explicitly accepted design after Resolve audition. Implement it
   in `libraries/perceptual-grade-reference`, then propagate that reference
   behavior to `products/perceptual-grade-next-blender`.
