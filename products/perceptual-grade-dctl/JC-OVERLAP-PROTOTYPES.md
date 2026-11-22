# Color J/C cone prototypes

Adjacent Overlap and Broad Overlap use the shipping cone Color J/C controls.
Both spread each slider's influence across Shadows, Midtones, White, and
Highlights before evaluating the J and C curves. Broad Overlap with Anchor
Centers adds independent J and C saturation centers at each tonal anchor.
Linear Gain and Log Gain use the same Broad Overlap weights with two controls
per anchor, a saturation-preserving J Contrast and a C Gain that fades near gray.
Global Shape uses continuous lightness and saturation curves with movable pivots.
Integrated Tone and J/C combines the Tone curve with Global Shape's C controls
so Tone can be auditioned as the source of lightness contrast.

## Build and install

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_overlap_prototypes --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_anchor_centers_prototype --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_gain_prototypes --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_global_shape_prototype --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_prototype --show-output
```

| Prototype | English filename |
| --- | --- |
| Adjacent Overlap | `Perceptual-Grade-3A-Cone-Color-JC-Adjacent-Overlap-Prototype.dctl` |
| Broad Overlap | `Perceptual-Grade-3A-Cone-Color-JC-Broad-Overlap-Prototype.dctl` |
| Broad Overlap with Anchor Centers | `Perceptual-Grade-3A-Cone-Color-JC-Broad-Overlap-Anchor-Centers-Prototype.dctl` |
| Linear Gain | `Perceptual-Grade-3A-Cone-Color-JC-Linear-Gain-Prototype.dctl` |
| Log Gain | `Perceptual-Grade-3A-Cone-Color-JC-Log-Gain-Prototype.dctl` |
| Global Shape | `Perceptual-Grade-3A-Cone-Color-JC-Global-Shape-Prototype.dctl` |
| Integrated Tone and J/C | `Perceptual-Grade-2-3A-Cone-Tone-JC-Prototype.dctl` |

The Simplified Chinese filenames end in `-zh-HANS.dctl`. Use the overlap
and Global Shape prototypes in the Color J/C position. Integrated Tone and J/C
replaces both Cone Tone and Color J/C. It follows XYZ Input and precedes Warp
and XYZ Output. [DCTL installation](README.md#install-and-use)

## Effective amounts

For each anchor, average the four slider values using the weights below.
Divide by their sum at that anchor. The distance `d` counts rows, so Midtones
is one row from both Shadows and White even though their `J_A` intervals
differ. Apply the average separately to J and C.

| Prototype | Weight at distance `d` | Raw weights for `d = 0, 1, 2, 3` |
| --- | --- | --- |
| Adjacent Overlap | `max(0, 1 - d/2)^2` | `1, 1/4, 0, 0` |
| Broad Overlap | `2^(-d^2)` | `1, 1/2, 1/16, 1/512` |

With a single Midtones slider at `+1`, the effective amounts at the four
anchors are as follows. These numbers are inputs to the saturation response.

| DCTL | Shadows | Midtones | White | Highlights |
| --- | ---: | ---: | ---: | ---: |
| Shipping cone Color J/C | 0 | 1 | 0 | 0 |
| Adjacent Overlap | 0.200 | 0.667 | 0.167 | 0 |
| Broad Overlap | 0.320 | 0.485 | 0.242 | 0.040 |

The shipping C curve already blends neighboring settings between anchors.
For a Midtones-only `+1` edit, the amount is `+0.5` halfway from Midtones to
White and reaches zero at White. The prototypes blend the effective amounts
over the same interval. The wider reach reduces the peak response to an
isolated slider. All four sliders at `+1` give an effective `+1` at every
anchor. The standalone XYZ Surface prototype uses H-K magnitude for its tonal
selector and applies an additive lightness edit. [XYZ Surface design](JC-SURFACE-PROTOTYPE.md)

## Per-anchor saturation centers

Broad Overlap with Anchor Centers uses the Broad Overlap weights for contrast.
Each row groups J Contrast, J Center, C Contrast, and C Center. Centers range
from 0.05 to 0.95 in steps of 0.01 and default to 0.50. With one J Width,
one C Width, and Overall Chroma Gain, there are 19 float sliders plus Peak
Nits and Direction. Setting all four J centers to the Broad Overlap J Center
and all four C centers to its C Center reproduces the Broad Overlap grade
when the other settings match.

**C Center** is the normalized saturation where that tone's C contrast
preserves chroma before Overall Chroma Gain. At a given `|J_A|`, normalized
saturation is `C / (C + (35/75) * |J_A|)` for chromatic samples. Each anchor
uses its selected center. Between two anchors the curve blends
`ln(center / (1 - center))` with cubic smoothstep along `|J_A|`. It holds
the Shadows center below Shadows and the Highlights center above Highlights.
At zero achromatic lightness, chromatic samples use the vivid limit.

**J Center** sets the saturation where the anchor's local lightness slope
is one. Each slope uses the resulting chroma after the C edit, the lightness
of its own anchor, and its selected J Center. The integrated lightness curve
can move a sample at this center through edits accumulated at lower tones.
J Width and C Width each control how gradually that family's contrast builds
with saturation distance from the center. Contrast sets the direction and
maximum strength of the response.

## Forward and inverse for the contrast prototypes

Both directions derive the same effective amounts from the sliders. Forward C
uses fixed signed `J_A` and hue to select and apply a strictly increasing radial
map. Forward J then holds the resulting chroma fixed and integrates positive
local slopes. A Midtones J edit already shifts brighter colors through the
cumulative integral. The prototype weights allow that edit to change the local
spacing at White as well.

Inverse first recovers signed `J_A` with the same integrated slopes. With the
original tone recovered, it retrieves the same C Center used by the forward
grade, divides out Overall Chroma Gain, and negates the effective C contrast
to undo the radial edit. The inverse operates between
cone nodes and is subject to float32 precision. H-K repair occurs at XYZ
Output. [Cone J/C equations and inverse scope](REVERSIBLE-STAGE-3.md#how-color-jc-preserves-order)

## Saturation-preserving J Contrast and C Gain

Linear Gain and Log Gain have eight sliders with a range of `−2` to `+2`
stops, plus Peak Anchor Nits and Direction. Each tonal row pairs J Contrast
with C Gain. Positive C Gain adds chroma and negative C Gain removes it.
Both variants apply C Gain first and hold signed lightness and hue fixed
during this step.

Let `s = C / (C + (35/75) * |J_A|)` be the input's normalized saturation in
the cone chart. The C Gain weight is `q = 9s / (1 + 8s)`. It is zero on gray,
half at `s = 0.10`, and 0.90 at `s = 0.50`. For the effective C Gain `A` at
the current tone, the two variants blend in different units.

| Variant | Chroma multiplier | At half weight and `+2` stops | At half weight and `−2` stops |
| --- | --- | --- | --- |
| Linear Gain | `1 + (2^A − 1) * q` | 2.5× | 0.625× |
| Log Gain | `2^(A * q)` | 2× | 0.5× |

J Contrast then uses the saturation after the C edit. Its influence fades
from zero on gray to full strength at `s = 0.10` with cubic smoothstep.
At full strength, an effective `+1` stop doubles local lightness spacing at
that anchor. The kernel integrates the positive slopes along `|J_A|` with
a slope of one at black. It scales the two opponent coordinates by the same
factor as signed lightness, preserving the hue and normalized saturation
established by C Gain. A chromatic sample at `J_A = 0` receives the full C
gain for its tone and passes through the J step.

The inverse reads the preserved saturation to recover the J slopes and undo
the lightness stretch and its chroma scaling. At the recovered lightness,
each C curve is strictly increasing throughout the slider range. Linear
Gain recovers the input radius from a quadratic equation. Log Gain solves
for it between the output radius and the output radius divided by `2^A`.

## Global J/C shaping

With only J Contrast active, a positive adjustment lowers lightness below
J Pivot, holds the pivot, and raises lightness above it through the contrast
range. The same move applies to grays and colors at the default J Saturation
Bias. C Contrast separates muted and vivid colors around the C Pivot.

| Control | Default and range | Behavior |
| --- | --- | --- |
| J Contrast and J Pivot | `0` stops from `-2` to `+2`, pivot `45` from `10` to `160` | Set the lightness slope at the pivot and position the crossover along the magnitude of signed lightness. |
| J Toe and J Shoulder | `0` from `-1` to `+1` | Lift or lower the dark and bright ends independently while holding J Pivot. |
| J Saturation Bias | `0` from `-1` to `+1` | Positive values give vivid colors more of the J edit. Negative values favor muted colors and gray. |
| C Contrast and C Pivot | `0` stops from `-2` to `+2`, pivot `0.50` from `0.05` to `0.95` | Set the saturation slope at the pivot and position the crossover along normalized saturation. |
| C Muted and C Vivid | `0` from `-1` to `+1` | Enrich or subdue the muted and vivid ends independently while holding C Pivot. |
| Shadow Chroma and Highlight Chroma | `0` stops from `-2` to `+2` | Add or remove chroma as a function of lightness. Chroma gain fades near gray. |
| C Tone Crossover | `45` from `10` to `160` | Position the lightness where both tonal chroma gains reach zero. The gains reach full strength at zero lightness and twice the crossover, respectively. |
| Direction | Forward | Apply or undo the same grade in the cone chain. |

Each axis uses two monotone rational-quadratic splines, with lightness in
`log2(1 + |J_A|/16)` and saturation in `-log2(1 - s)`. Contrast fixes zero,
the pivot `p`, and `p + 2` in curve coordinates. Its slope at the pivot is
`2^Contrast` and its continuation above `p + 2` is the identity. The shape
spline moves the output at `p/2` and `p + 2`, holds the pivot, and keeps a
unit slope in the upper tail. Toe, Shoulder, Muted, and Vivid can act with
Contrast at zero.

The C step applies the saturation curve, then the lightness-dependent chroma
gains, at fixed hue and signed lightness. The J step uses the resulting
saturation, remaps `|J_A|`, and scales both opponent coordinates by the
same lightness factor. That preserves hue and normalized saturation while
letting gray move along the neutral axis. Exact black stays fixed. Chromatic
samples at `J_A = 0` use the finite C tail gain and pass through the J step.
The inverse undoes J first, then the tonal chroma gain and global C curve.

| Design decision | What to judge in Resolve | Flexibility before promotion |
| --- | --- | --- |
| Contrast coordinates and reach | Whether the fixed pivots keep the intended subjects stable and the upper contrast fade handles bright highlights | High. The coordinate scales and upper reach can be tuned while keeping the pivots. |
| Independent curve ends | Whether Toe, Shoulder, Muted, and Vivid give sufficient control with Contrast at zero | High. The shape knots and amount calibration can be tuned together. |
| J Saturation Bias | How much J adjustment neutral and vivid colors should share | High. The influence function can change while using the same preserved saturation in both directions. |
| Shadow and highlight chroma | Whether the crossover and near-gray fade isolate the desired tonal ranges | High. The taper and gain calibration can be tuned while keeping the chroma map ordered. |

1. On a gray ramp and a constant-saturation lightness ramp, set J Pivot to
   `45` and J Contrast to `+1` with the other adjustments at reset. Verify
   that `J_A = 25` darkens, `45` holds, and `75` brightens.
2. Set J Contrast to zero, then try J Toe at `+0.5` and J Shoulder at
   `-0.5`. Compare the effect on gray and a vividly colored ramp at both
   ends of J Saturation Bias.
3. On a muted-to-vivid ramp and bright colored objects, test C Contrast
   around `0.50`, use C Muted and C Vivid separately, then try negative
   Highlight Chroma. Use the crossover to control where it begins.
4. Compare Global Shape with Cone Tone active and bypassed on the same
   neutral and HDR material. Test a matching Forward and Inverse pair
   between the cone nodes. Record the accepted curve behavior and whether
   it covers the Tone adjustments you need before moving the design to the
   reference library and then Next Blender.

## Integrated Tone and J/C

Place the integrated node after XYZ Input and before Warp and XYZ Output.
Tone supplies the full J curve. The node pairs its source-nit mapping
controls with the seven Global Shape C controls.

| Control | Default | Behavior |
| --- | --- | --- |
| Input Shadows, Midtones, White, and Highlights | Existing Tone defaults | Set the source-nit landmarks for the Tone curve. |
| Remap Fit and Peak Nits | Existing Tone defaults | Set the fit of the Tone curve and the neutral highlight target. |
| Black Compression Nits | `0` nits, range `0–2` | Compress the low end of the source coordinate. The kernel converts the control to a lightness parameter `B` and maps samples and source landmarks with `x (x + B) / (x + 2B)`. For positive `B`, the curve starts at zero with a slope of one half. |
| H-K Influence | `1`, range `0–1` | Blend the J-only gain at zero with the full Helmholtz–Kohlrausch Tone gain at one. Full Influence matches Stage 2 at zero Black Compression with the C controls at reset. |
| C Contrast, C Pivot, C Muted, C Vivid | `0`, `0.50`, `0`, `0` | Keep the global saturation curve reset by default. |
| Shadow Chroma, Highlight Chroma, C Tone Crossover | `0`, `0`, `45` | Keep the lightness-dependent chroma gains reset by default. |
| Direction | Forward | Apply or undo the integrated grade in the cone chain. |

Both Tone endpoints and their blend scale signed `J_A` and the two opponent
coordinates by the same positive gain. Tone preserves hue and normalized
saturation across the Influence range, including on negative `J_A`.
The H-K contribution lets brighter-looking colors receive a different Tone
gain from grays of equal `J_A`. This is intentional alongside the separate
C adjustments. XYZ Output performs H-K repair at export.

Forward applies C at the incoming signed lightness and hue, then applies
Tone. The lightness-dependent chroma gains use that incoming lightness, so
moving a Tone landmark leaves C Tone Crossover in the same input region.
Inverse recovers the input tone along the preserved saturation and hue ray
before undoing C.

| Design choice | What to compare in Resolve | Flexibility before promotion |
| --- | --- | --- |
| H-K Influence | Compare gray and saturated ramps at both endpoints and halfway between them | High. The gain blend can be tuned while keeping the Tone ray fixed. |
| Black Compression | Compare separation near black and the placement of source-nit landmarks | Medium. The compression law can change if it stays invertible and applies to samples and landmarks together. |
| C selector at input tone | Move the Tone landmarks while keeping C Tone Crossover fixed | Low. Changing the selector would change which input colors receive each gain and how the inverse recovers it. |
| H-K and C interaction | Compare bright color separation at full H-K Influence with the C controls at reset and then active | High. Influence and the C curve provide independent controls for the overlap. |

1. Match the source-nit landmarks, Remap Fit, and Peak Nits in the integrated
   node and a standalone Cone Tone on parallel branches. At zero Black
   Compression, full H-K Influence, and C reset, compare gray and colored HDR
   ramps.
2. Keep those landmarks and sweep H-K Influence down to zero on skin and
   saturated highlights. Raise Black Compression on a dark ramp to check
   low-end separation and the placement of the source-nit landmarks.
3. Set Highlight Chroma to `-1` and move the Tone landmarks. Compare where the
   chroma change starts on the same input ramp. Pair Forward and Inverse with
   matching controls ahead of Warp and XYZ Output to check signed and HDR
   round trips.
4. Record the behavior accepted in Resolve. Promote it through
   `libraries/perceptual-grade-reference` and then
   `products/perceptual-grade-next-blender`.

## Decisions for audition

| Decision | What to judge in Resolve | Flexibility before promotion |
| --- | --- | --- |
| Falloff and reach | Whether a single Midtones edit should affect White and how much should reach Highlights | High. The falloff can be tuned while keeping the four anchors. |
| Normalization | Whether the gentler isolated edit feels right alongside equal edits across all tones | Medium. Normalization preserves equal settings and keeps the effective amount within the slider range. |
| Shared overlap for J and C | Whether the preferred chroma reach also suits local lightness spacing | High. J and C can use separate weights. |
| Per-anchor centers and shared widths | Whether skin tones and bright fabrics need different crossovers while sharing the same transition width | High. Compare with Broad Overlap on identical material. |
| Saturation-preserving J | Whether skin retains its color as Midtones J Contrast changes the lightness spacing | Medium. The near-gray fade and positive slopes can be tuned while keeping J on a constant-saturation ray. |
| Tonal C Gain near gray | Whether a softly colored neutral stays close enough to gray when a vivid patch gains chroma at the same tone | High. The half-weight point can move. The curve must stay increasing over the full slider range. |
| Linear or log-like C gain | Compare the multipliers in the table on the same muted-to-vivid ramp | High. Both variants share controls, tonal weights, and near-gray protection. |

1. Compare shipping Color J/C, Adjacent Overlap, and Broad Overlap on the
   same skin shot, muted-to-vivid ramp, and colored lightness ramp. Use
   identical XYZ Input and XYZ Output nodes, Tone settings, and Peak Nits.
2. Set Midtones C Contrast to `+1` with the other controls at reset. Compare
   the chroma separation through White, then set White C Contrast to `-1`
   to judge how neighboring edits interact. Repeat for J. On the lightness
   ramp, look at local spacing at White and the cumulative shift above White.
3. Set all four amounts in one family to `+1` and compare the three nodes.
   Test a forward/inverse pair of each prototype with identical settings
   before XYZ Output.
4. Compare Broad Overlap and its Anchor Centers edition on muted skin and
   vivid fabric at several lightnesses. Start with matching centers, set all
   C Contrast sliders to `+1`, and keep Overall Chroma Gain at zero. In
   Anchor Centers, set Midtones C Center to `0.35` and White C Center to
   `0.65`. A patch at normalized saturation `0.50` gains chroma at the
   Midtones anchor and loses chroma at White. Set all C amounts to `-1`
   to reverse both moves. Try the corresponding J centers on a colored
   lightness ramp and inspect the spacing around each anchor.
5. Compare Anchor Centers, Linear Gain, and Log Gain on a constant-saturation
   lightness ramp. Leave C at reset and raise Midtones J Contrast to `+1`.
   Inspect the spacing through Midtones and the saturation of the lifted
   colors. The two Gain variants should give the same result on this test.
6. On a muted-to-vivid ramp, leave J at reset and set all four C Gain sliders
   to `+2` to isolate the gain blend. Compare the half-weight patch at
   `s = 0.10` with the multipliers above, then repeat at `−2`. Set Midtones J
   Contrast to `+1` and White J Contrast to `−1`, then audition matching
   Forward and Inverse nodes before XYZ Output on signed and HDR material.
7. Record the accepted behavior after Resolve audition. Implement it in
   `libraries/perceptual-grade-reference`, then propagate the reference
   behavior to `products/perceptual-grade-next-blender`.
