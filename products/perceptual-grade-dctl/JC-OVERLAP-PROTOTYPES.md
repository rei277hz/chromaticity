# Color J/C cone prototypes

Adjacent Overlap and Broad Overlap use the shipping cone Color J/C controls.
Both spread each slider's influence across Shadows, Midtones, White, and
Highlights before evaluating the J and C curves. Broad Overlap with Anchor
Centers adds independent J and C saturation centers at each tonal anchor.
Linear Gain and Log Gain use the same Broad Overlap weights with two controls
per anchor, a saturation-preserving J Contrast and a C Gain that fades near gray.
Global Shape uses continuous lightness and saturation curves with movable pivots.
The Unified Chroma baseline combines the Tone curve with a single saturation
curve for muted and vivid gains. The earlier integrated Log Gain and Linear
Gain variants are available for comparison.

## Build and install

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_overlap_prototypes --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_anchor_centers_prototype --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_gain_prototypes --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_global_shape_prototype --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_prototype --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_linear_gain_prototype --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_unified_chroma_prototype --show-output
```

| Prototype | English filename |
| --- | --- |
| Adjacent Overlap | `Perceptual-Grade-3A-Cone-Color-JC-Adjacent-Overlap-Prototype.dctl` |
| Broad Overlap | `Perceptual-Grade-3A-Cone-Color-JC-Broad-Overlap-Prototype.dctl` |
| Broad Overlap with Anchor Centers | `Perceptual-Grade-3A-Cone-Color-JC-Broad-Overlap-Anchor-Centers-Prototype.dctl` |
| Linear Gain | `Perceptual-Grade-3A-Cone-Color-JC-Linear-Gain-Prototype.dctl` |
| Log Gain | `Perceptual-Grade-3A-Cone-Color-JC-Log-Gain-Prototype.dctl` |
| Global Shape | `Perceptual-Grade-3A-Cone-Color-JC-Global-Shape-Prototype.dctl` |
| Integrated Tone and J/C Legacy Log Gain | `Perceptual-Grade-2-3A-Cone-Tone-JC-Prototype.dctl` |
| Integrated Tone and J/C Linear Gain | `Perceptual-Grade-2-3A-Cone-Tone-JC-Linear-Gain-Prototype.dctl` |
| Integrated Tone and J/C Unified Chroma baseline | `Perceptual-Grade-2-3A-Cone-Tone-JC-Unified-Chroma-Prototype.dctl` |

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
Bias. C Pivot selects the crossover for C Contrast. C Muted and C Vivid shape
the lower and upper saturation ranges around a fixed midpoint, independent of
C Pivot.

| Control | Default and range | Behavior |
| --- | --- | --- |
| J Contrast and J Pivot | `0` stops from `-2` to `+2`, pivot `45` from `10` to `160` | Set the lightness slope at the pivot and position the crossover along the magnitude of signed lightness. |
| J Toe and J Shoulder | `0` from `-1` to `+1` | Lift or lower the dark and bright ends independently while holding J Pivot. |
| J Saturation Bias | `0` from `-1` to `+1` | Positive values give vivid colors more of the J edit. Negative values favor muted colors and gray. |
| C Contrast and C Pivot | `0` stops from `-2` to `+2`, pivot `0.50` from `0.05` to `0.95` | Set the slope and crossover of the monotonic contrast component. Raising C Pivot raises saturation with negative contrast and lowers it with positive contrast. |
| C Muted and C Vivid | `0` from `-1` to `+1` | Enrich or subdue the lower and upper ends around fixed normalized saturation `0.50`, regardless of C Pivot. |
| Shadow Chroma and Highlight Chroma | `0` stops from `-2` to `+2` | Add or remove chroma as a function of lightness. Chroma gain fades near gray. |
| C Tone Crossover | `45` from `10` to `160` | Position the lightness where both tonal chroma gains reach zero. The gains reach full strength at zero lightness and twice the crossover, respectively. |
| Direction | Forward | Apply or undo the same grade in the cone chain. |

J uses monotone rational-quadratic splines in `log2(1 + |J_A|/16)`. Its
contrast and end shaping each preserve the selected J Pivot. C Contrast uses
an analytic two-branch chroma curve with pivot `p` in normalized saturation
`s = C/(C + B)`, where `B = (35/75)|J_A|`. Let `K = B*p/(1-p)` and
`g = 2^CContrast`. The forward contrast mapping is
`C/(g + (1-g)*C/K)` for `C < K`, and `g*C + (1-g)*K` for `C >= K`. Both
branches meet at `K` with slope `g` for `K > 0`. Near gray the contrast gain
approaches `1/g` at nonzero lightness. The inverse uses the same branches
with `1/g` and the same `K`.

For contrast-adjusted chroma `C1`, C Muted and C Vivid shape
`x = log2(1 + C1/B)` at nonzero lightness. With slider values `M` and `V`,
input knots `(0, 0.5, 1, 3)` map to `(0, 0.5 + 0.25*M, 1, 3 + V)`.
Each rational-quadratic segment has unit slopes at both ends. For start
`(x0, y0)`, width `w` and rise `h`, set `t = (x - x0)/w` and `d = w/h`.

```text
y = y0 + h * (t^2 + d*t*(1-t)) / (t^2 + 2*d*t*(1-t) + (1-t)^2)
```

Above `x = 3`, `y = x + V`. The output chroma is `B*(2^y - 1)`. The fixed
knot `x = 1` corresponds to saturation `0.50` after contrast. At `B = 35`
and input `C = 70`, C Pivot `0.50` and C Contrast `-2` take chroma to
`43.75`. C Vivid `+1` then takes it to `44.68`.

The end shape is strictly increasing and independent of C Pivot, so it
preserves the pivot sweep direction. With negative C Contrast, increasing
the pivot raises cone-chart saturation for chromatic samples at nonzero
lightness. Positive contrast reverses that direction. Muted/Vivid may move
the final output at the contrast pivot.

The C step applies the saturation curve, then the lightness-dependent chroma
gains, at fixed hue and signed lightness. The J step uses the resulting
saturation, remaps `|J_A|`, and scales both opponent coordinates by the
same lightness factor. That preserves hue and normalized saturation while
letting gray move along the neutral axis. Exact black stays fixed. Chromatic
samples at `J_A = 0` use the finite C tail gain `2^(C Contrast + C Vivid)`
before tonal chroma gain and pass through the J step. The C controls leave
exact gray fixed. The inverse undoes J first, then the tonal chroma gain,
C Muted/Vivid shaping, and C Contrast.

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
   at `-2` with C Muted at `-1` and C Vivid at `+1`. Sweep C Pivot from
   `0.05` to `0.95` and verify each fixed sample moves monotonically toward
   higher saturation. Repeat with C Contrast at `+2` and verify the direction
   reverses, then set contrast to zero and verify the pivot has no effect.
   Change C Muted and C Vivid while holding the pivot fixed to audition their
   fixed-midpoint end shaping. Then try negative Highlight Chroma.
4. Compare Global Shape with Cone Tone active and bypassed on the same
   neutral and HDR material. Test a matching Forward and Inverse pair
   between the cone nodes. Record the accepted curve behavior and whether
   it covers the Tone adjustments you need before moving the design to the
   reference library and then Next Blender.

## Integrated Tone and J/C

Place the integrated node after XYZ Input and before Warp and XYZ Output.
Tone supplies the full J curve in all three designs. This table describes
the Legacy Log Gain controls. Linear Gain shares these controls.

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

### Linear Gain audition

The integrated Linear Gain variant keeps the C Contrast, C Pivot, C Muted and
C Vivid curve and gives Shadow Chroma and Highlight Chroma a different fade.
For effective tonal amount `A`, chroma `C` after the C curve, and knee
`k = (35/(75*9)) * |J_A|`, its gain is `1 + (2^A - 1) * C/(C+k)`.
For nonzero `|J_A|`, gain approaches one near gray and `2^A` at high
saturation. At `J_A = 0`, chromatic samples receive the full tonal gain, and
exact gray stays gray.

The tonal gain uses input `|J_A|` to choose `A` and `k`. Inverse first
recovers that lightness with the existing Tone solve, then uses a quadratic
root to undo the tonal gain before undoing the C curve. For output chroma
`Y > 0` and `k > 0`, the equation `2^A * C^2 + (k - Y)*C - k*Y = 0`
has exactly one positive root because the product of its roots is negative.
At `k = 0`, the inverse is `C = Y / 2^A`. The C operation is closed form
in this variant. Legacy Log Gain interpolates the gain in stops,
which changes the response between gray and high saturation.

Build the variant with

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_linear_gain_prototype --show-output
```

On matched skin, muted-to-vivid, and signed HDR ramps, compare Legacy Log Gain
and Linear Gain with Shadow Chroma and Highlight Chroma first at reset,
then at positive and negative stops. Check near-gray fading, the lightness
crossover, and paired forward/inverse round trips.

### Unified Chroma audition

Unified Chroma replaces the serial contrast and end-shaping adjustments with
one curve based on incoming chroma. The baseline retains the original smooth
Tone remap with integer Remap Fit from `-2` to `+2` and a default of `0`.
It applies full H–K Influence (`1.0`) and uses the Linear Gain fade for Shadow
Chroma and Highlight Chroma.

| Control | Default and range | Behavior |
| --- | --- | --- |
| C Muted Gain | `0` stops, `-2` to `+2` | Set the gain limit for nearly gray colors at nonzero lightness. |
| C Vivid Gain | `0` stops, `-2` to `+2` | Set the gain limit for highly saturated colors. Its effect builds smoothly with input saturation. |
| C Saturation Crossover | `0.50`, `0.05` to `0.95` | Set the input saturation where the gain in stops is halfway between Muted and Vivid. |

All three sliders use steps of `0.01`. Let `B = (35/75)|J_A|` and
`s = C/(C+B)`. At the default crossover `s = 0.50`, input chroma equals
`B`. The reference model uses that same ratio for equal low and high driver
weights after Tone. Unified Chroma measures it before Tone. C Tone Crossover
selects lightness for the separate Shadow and Highlight Chroma adjustments.
[Reference chroma drivers](../../libraries/perceptual-grade-reference/src/grading.py)

For Muted and Vivid stops `M` and `V`, set `L = 2^M` and `H = 2^V`.
For a crossover setting `p`, chroma `K` is where input saturation equals
`p`. The forward curve blends the two gains once.

```text
K = B*p/(1-p)
k = K*sqrt(H/L)
C_out = C*(L*k + H*C)/(k + C)
```

At `C = K`, the gain is `sqrt(L*H)`. Equal gains scale chroma uniformly. Equal and
opposite stops hold the crossover fixed. Raising the crossover increases
saturation when `M > V` and decreases it when `V > M`, for chromatic
samples at nonzero lightness. With `B = 35`, `C = 70` and crossover `0.50`,
Muted Gain `-1` gives `C_out` of `55.50` at Vivid Gain `0` and `87.50` at
Vivid Gain `+1`, before tonal chroma and Tone.

Exact gray stays gray. At nonzero lightness, the near-gray gain approaches
`L`, so Muted Gain also affects faintly colored pixels. At zero lightness, a
chromatic sample receives `H*C`. For `k > 0`, the slope of the curve is
`(L*k^2 + 2*H*k*C + H*C^2)/(k+C)^2 > 0` throughout the chroma range.
Given output chroma `Y > 0`, the quadratic
`H*C^2 + (L*k - Y)*C - k*Y = 0` has one positive root. The DCTL evaluates
it with the stable Linear Gain inverse using output `Y/L`, knee `k`, and
relative gain `H/L`. Inverse recovers input lightness with the Tone solve
and undoes tonal chroma gain before undoing the unified curve.

Build the English and Simplified Chinese DCTLs with

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_unified_chroma_prototype --show-output
```

Compare Unified Chroma and integrated Linear Gain on the same muted-to-vivid
ramp and skin shot, with matching Tone settings, full H–K Influence, and tonal
chroma at reset.
Set Muted Gain to `-1` and sweep Vivid Gain from `0` to `+1`. At `+1`, sweep
C Saturation Crossover from `0.05` to `0.95`, then swap the endpoint gains
and confirm that the sweep reverses. Check matching Forward and Inverse nodes
with Tone and both tonal chroma gains active on signed HDR material before
export. Record the accepted controls and curve in Resolve before implementing
them in `libraries/perceptual-grade-reference` and then propagating them to
`products/perceptual-grade-next-blender`.

### Integrated Tone audition decisions

| Design choice | What to compare in Resolve | Flexibility before promotion |
| --- | --- | --- |
| Tone fit | Sweep Remap Fit from `-2` to `+2` on gray and saturated ramps | The baseline uses the original smooth remap over this Fit range. |
| H-K Influence | Compare gray and saturated ramps at full influence | Fixed at `1.0` in Unified Chroma. Legacy Log Gain and Linear Gain offer an adjustable blend. |
| Black Compression | Compare separation near black and the placement of source-nit landmarks | Medium. The compression law can change if it stays invertible and applies to samples and landmarks together. |
| Tonal chroma gain | Compare log-gain and Linear Gain between gray and their full-stop endpoints | Medium. Endpoint fades stay fixed while the midrange response changes. |
| Unified saturation gains | Compare Vivid's reach on moderate colors and Muted's effect near gray | High. Slider limits and default crossover can be tuned. |
| Unified saturation blend | Check the ordered crossover sweep and whether opposite stops hold the intended input saturation | Medium. A different blend needs to preserve positive slopes, the crossover behavior, and the closed-form inverse. |
| C selector at input tone | Move the Tone landmarks while keeping C Tone Crossover fixed | Low. Changing the selector would change which input colors receive each gain and how the inverse recovers it. |
| H-K and C interaction | Compare bright color separation at full H-K Influence with the C controls at reset and then active | The C curve shapes incoming chroma before the fixed full H-K Tone gain. |

1. Match the source-nit landmarks, Remap Fit, and Peak Nits in the integrated
   node and a standalone Cone Tone on parallel branches. At zero Black
   Compression, full H-K Influence, and C reset, compare gray and colored HDR
   ramps.
2. Keep those landmarks and sweep Remap Fit from `-2` to `+2` on skin and
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
