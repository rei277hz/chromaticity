# Perceptual Grade for DaVinci Resolve

Six DCTLs grade scene-linear **XYZ D65**, with reference white at Y = 1
(203 nits). XYZ Input converts to signed modCAM16 cone responses for Tone and
both Color nodes. XYZ Output converts back to scene-linear XYZ D65.

| DCTL | Adjustments |
| --- | --- |
| `Perceptual-Grade-1-Linear.dctl` | Exposure, CAT16 source white, and balance, spread and heading on the cyan–red and yellow–blue axes |
| `Perceptual-Grade-1B-XYZ-Input.dctl` | Converts linear XYZ D65 to signed cone responses |
| `Perceptual-Grade-2-Cone-Tone.dctl` | Black, Shadows, Midtones, White and Highlights input levels in nits, curve Fit and output peak |
| `Perceptual-Grade-3A-Cone-Color-JC.dctl` | J and C contrast per tone, separate J and C saturation centers and widths, overall chroma gain, direction |
| `Perceptual-Grade-3B-Cone-Warp.dctl` | Chroma, integer hue and scale on six Rec.709 handles across four tonal rows, four Adaptance centers, half saturation, direction |
| `Perceptual-Grade-4-XYZ-Output.dctl` | Final H–K repair, optional saturation compression, and decode to linear XYZ D65 |

## Install and use

1. Build both locales. Buck prints the directory containing all 12 files.

   ```sh
   buck2 build --remote-only //products/perceptual-grade-dctl:dctl --show-output
   ```

2. In Resolve's **Project Settings → Color Management → Lookup Tables**, open
   the LUT folder and install the six English files or the six Simplified
   Chinese files with the `-zh-HANS` suffix. Choose **Update Lists**. On the
   Color page, add the DCTL effects on serial nodes in the order shown above.
3. If your node graph works in RGB or log, place a Color Space Transform before
   Linear to convert the working gamut and gamma to **CIE XYZ** with **Linear**
   gamma and D65 white. After XYZ Output, use the reverse transform to return to
   the working gamut and gamma. Set tone mapping and gamut mapping to **None**
   on both transforms. Keep display rendering and RGB operations outside the
   cone-response nodes.
4. Match **Peak Nits** across Tone, Color J/C and Warp. The default is 1000 nits.
   Linear, Tone and both Color nodes pass valid input through exactly at their
   default settings. The XYZ Input and Output pair applies a float32 round trip
   with export repair where the final appearance requires it.

## Color and export

Use the **Direction** menu to audition a Color node's inverse. To undo both
nodes within the same cone chain, place their copies between Forward Warp and
XYZ Output, in the order Warp **Inverse** → Color J/C **Inverse**, with the
matching settings and Peak Nits. [Stage 3 design and audition](REVERSIBLE-STAGE-3.md)

Warp uses 57 floating-point sliders and 24 integer hue sliders in degrees.
That keeps the floating-point sliders within Resolve's limit of 64 per DCTL.

XYZ Output preserves signed and HDR values, including values above 1024. The
Resolve chain omits the input RGB repair and AP1-D65 boundary mapping used
for Blender and ACES 2.0 compatibility. Invalid cone data propagates through
the cone nodes to the magenta diagnostic at XYZ Output. Invalid ordering of
the Warp hues triggers the diagnostic across the image.

**Saturation Compression** is an optional XYZ Output control, off by default.
After H–K repair it uses the modCAM16 saturation ratio `C / |J_A|`, preserving
signed achromatic lightness and scaling the opponent axes together. Colors up
to the **Saturation Knee** pass through the shoulder unchanged. Above the knee,
the output saturation approaches the **Saturation Ceiling** smoothly. The
defaults are 0.5 for the knee and 1 for the ceiling. Both controls must be
finite and satisfy `0 ≤ knee < ceiling ≤ 8` regardless of the switch position.
Invalid controls trigger the magenta diagnostic. At zero achromatic lightness,
enabled compression sends chromatic input to black.

## Tone and Color J/C variant catalog

Each design below is available in English and Simplified Chinese. The variant
links lead to the corresponding build instructions.

### Integrated 2-3A variants

Each variant replaces Cone Tone and Color J/C in the cone chain. Forward
applies global chroma shaping, then Shadow and Highlight Chroma, then
saturation-preserving Tone. **C Tone Crossover**
sets the input lightness where both tonal chroma adjustments reach zero.
The Unified Chroma crossover uses raw input saturation `C / abs(J_A)`.
Legacy variants use `s = C / (C + (35/75) * abs(J_A))` for their pivots.

| Variant and Buck target | Tone Fit and H–K Influence | Global chroma controls | Saturation pivot or crossover | Global gain near gray | Shadow and Highlight Chroma fade | Inverse |
| --- | --- | --- | --- | --- | --- | --- |
| [Unified Chroma baseline](#unified-chroma-baseline) (`:jc_tone_fit_unified_chroma_prototype`) | Fit `-2` to `+2`, H–K Influence fixed at `1.0` | C Muted Gain and C Vivid Gain shape one curve | Raw input saturation `C / abs(J_A)`, default `0.45`. At a positive crossover the gain is halfway between the endpoints in stops. | Approaches `2^(C Muted Gain)` at a positive crossover. Zero crossover gives Vivid Gain. | Interpolates the gain multiplier and approaches unity near gray | Chroma closed form. Tone uses a scalar solve. |
| [Legacy Log Gain](#integrated-tone-and-color-jc-prototype) (`:jc_tone_fit_prototype`) | Fit `-2` to `+6`, H–K Influence `0` to `1` | C Contrast followed by C Muted and C Vivid | Adjustable C Pivot for contrast. Muted and Vivid meet at `s = 0.50` after contrast. | Approaches `2^(-C Contrast)` as Muted and Vivid fade | Interpolates in stops and approaches unity near gray | Global curve closed form. Tonal gain and Tone use scalar solves. |
| [Linear Gain](#linear-gain-audition) (`:jc_tone_fit_linear_gain_prototype`) | Fit `-2` to `+6`, H–K Influence `0` to `1` | C Contrast followed by C Muted and C Vivid | Adjustable C Pivot for contrast. Muted and Vivid meet at `s = 0.50` after contrast. | Approaches `2^(-C Contrast)` as Muted and Vivid fade | Interpolates the gain multiplier and approaches unity near gray | Chroma closed form. Tone uses a scalar solve. |

Near-gray gain describes faintly colored pixels at nonzero lightness. Exact
gray stays neutral.
[Equations and Resolve audition](JC-OVERLAP-PROTOTYPES.md#integrated-tone-and-jc)

### Standalone 3A variants

Cone variants occupy the Color J/C position after Cone Tone. XYZ variants
operate directly on scene-linear XYZ D65, outside the cone chain. LGG means
Lift, Gamma, and Gain.

| Variant | Domain | Tonal weighting | J adjustment | C adjustment and pivot | Near-gray behavior | Inverse in the DCTL |
| --- | --- | --- | --- | --- | --- | --- |
| [Shipping Color J/C](#install-and-use) (`:dctl`) | Cone | Four anchors with interpolation between neighbors | Local lightness contrast at fixed chroma, shared J center and width | Per-tone contrast, shared C center and width, overall gain | J fades. C retains relative gain. | J scalar solve, C closed form |
| [Adjacent Overlap](#color-jc-tonal-overlap-prototypes) (`:jc_overlap_prototypes`) | Cone | Each anchor also receives its immediate neighbors | Local lightness contrast at fixed chroma, shared J center and width | Per-tone contrast, shared C center and width, overall gain | J fades. C retains relative gain. | J scalar solve, C closed form |
| [Broad Overlap](#color-jc-tonal-overlap-prototypes) (`:jc_overlap_prototypes`) | Cone | Each anchor receives all four rows with distance falloff | Local lightness contrast at fixed chroma, shared J center and width | Per-tone contrast, shared C center and width, overall gain | J fades. C retains relative gain. | J scalar solve, C closed form |
| [Broad Overlap with Anchor Centers](#color-jc-tonal-overlap-prototypes) (`:jc_anchor_centers_prototype`) | Cone | Broad overlap for contrast amounts | Local lightness contrast at fixed chroma, J center per anchor, shared J width | Per-tone contrast, C center per anchor, shared C width, overall gain | J fades. C retains relative gain. | J scalar solve, C closed form |
| [Linear Gain](#color-jc-tonal-overlap-prototypes) (`:jc_gain_prototypes`) | Cone | Four anchors with broad overlap | Saturation-preserving local contrast | Gain per tone, linear multiplier blend, half weight at `s = 0.10` | J and C gains fade to unity | J scalar solve, C quadratic |
| [Log Gain](#color-jc-tonal-overlap-prototypes) (`:jc_gain_prototypes`) | Cone | Four anchors with broad overlap | Saturation-preserving local contrast | Gain per tone, blend in stops, half weight at `s = 0.10` | J and C gains fade to unity | J and C scalar solves |
| [Global Shape](#global-color-jc-shaping-prototype) (`:jc_global_shape_prototype`) | Cone | Global curves with a shadow/highlight crossover | Saturation-preserving contrast, pivot, toe, shoulder, and saturation bias | C Contrast and C Pivot, fixed-midpoint Muted and Vivid, tonal gain in stops | J can move gray. C Contrast retains relative gain. Muted/Vivid and tonal gains approach unity. | J and global C closed form, tonal C scalar solve |
| [Surface](#color-jc-saturation-surface-prototype) (`:jc_surface_prototype`) | XYZ | Adjacent H–K anchors with cubic interpolation | Additive lightness offset, shared J center and width | Per-tone contrast, shared C center and width, overall gain | J fades. C retains relative gain. | Forward only |
| [LGG Baseline](#color-jc-lgg-prototype) (`:jc_prototype`) | XYZ | Four H–K anchors with separate J and C Fit | LGG per tone | LGG on a log-like axis, fixed `35/75` ratio pivot | J Lift can move gray. C retains relative gain. | Forward only |
| [LGG NonLog](#color-jc-lgg-prototype) (`:jc_prototype`) | XYZ | Four H–K anchors with separate J and C Fit | LGG per tone | LGG on an inverse-square-root axis, fixed `35/75` ratio pivot | J Lift can move gray. C retains relative gain. | Forward only |
| [LGG Pivot](#color-jc-lgg-prototype) (`:jc_prototype`) | XYZ | Four H–K anchors with separate J and C Fit | LGG per tone | LGG on a log-like axis, adjustable ratio pivot from `0.05` to `2.00` | J Lift can move gray. C retains relative gain. | Forward only |

The LGG pivot is the chroma-to-lightness ratio `C / abs(J_A)`. A ratio of
`35/75` corresponds to `0.50` on the normalized saturation scale `s`.
Cone variants defer H–K repair to XYZ Output. The standalone XYZ variants
apply H–K repair inside the DCTL.
[Shipping Color J/C](REVERSIBLE-STAGE-3.md#how-color-jc-preserves-order) ·
[Cone auditions](JC-OVERLAP-PROTOTYPES.md) ·
[Surface audition](JC-SURFACE-PROTOTYPE.md) ·
[LGG auditions](JC-LGG-PROTOTYPE.md)

## Color J/C tonal overlap prototypes

Adjacent Overlap and Broad Overlap spread the influence of each J and C
Contrast slider across the existing tonal anchors. Use either prototype in
the Color J/C position of the cone chain. The target builds four files across
English and Simplified Chinese.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_overlap_prototypes --show-output
```

Broad Overlap with Anchor Centers gives each tonal row its own J Center and
C Center. Use the separate target to build the English and Simplified Chinese
editions.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_anchor_centers_prototype --show-output
```

The Linear Gain and Log Gain prototypes preserve saturation during J
adjustments. Each tonal row pairs J Contrast with a C Gain control that fades
near gray.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_gain_prototypes --show-output
```

[Overlap weights, anchor centers, gain variants, and Resolve audition](JC-OVERLAP-PROTOTYPES.md)

## Integrated Tone and Color J/C prototype

The Legacy Log Gain prototype combines Cone Tone and Global Shape's original
chroma controls in one DCTL for comparison with Unified Chroma. Place it after
XYZ Input and before Warp and XYZ Output when auditioning it.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_prototype --show-output
```

Build details and Resolve audition steps are in the
[integrated Tone and J/C guide](JC-OVERLAP-PROTOTYPES.md#integrated-tone-and-jc).

### Linear Gain audition

This integrated variant gives Shadow and Highlight Chroma a Linear Gain fade
with a quadratic inverse. C Contrast, C Pivot, C Muted and C Vivid use the same
curve as Legacy Log Gain. The target builds English and Simplified Chinese files.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_linear_gain_prototype --show-output
```

Tone's inverse still uses a scalar solve. [Linear Gain behavior and Resolve audition](JC-OVERLAP-PROTOTYPES.md#linear-gain-audition)

### Unified Chroma baseline

C Muted Gain and C Vivid Gain shape incoming saturation together. C Saturation
Crossover selects raw input saturation `C / abs(J_A)` from `0` to `1`,
with a default of `0.45`. At a positive crossover, the applied gain in stops
is the average of the two settings. A zero crossover applies Vivid Gain to
every chromatic sample. C Muted Gain, C Vivid Gain, Shadow Chroma, and
Highlight Chroma range from `-4` to `+4` stops. The baseline uses the
original smooth Tone curve and the Linear Gain fade for Shadow and
Highlight Chroma. H–K Influence is fixed at `1.0` and
Remap Fit is limited to `-2` through `+2`. The target builds English and
Simplified Chinese DCTLs.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_unified_chroma_prototype --show-output
```

[Unified curve, inverse, and Resolve audition](JC-OVERLAP-PROTOTYPES.md#unified-chroma-audition)

### Tone curve overlay

Enable **Show Tone Curve** in Unified Chroma to see how the four source
levels, Black Compression, Remap Fit, and Peak Nits shape the
neutral tone curve. The lower-left graph plots input J against output J.
Both axes run from zero to the normalized J of 4000 nits, with 203 nits
at J = 1. Selecting **Inverse** swaps the plotted input and output.

Hollow rings mark the Shadows, Midtones, White, and Highlights targets.
Filled dots mark the fitted values. A chevron at the plot edge indicates an
anchor beyond the axis limit.
The checkbox is off by default. Turn it off for clean playback and delivery
because the enabled overlay is drawn into the image.

## Global Color J/C shaping prototype

Global Shape gives lightness and saturation separate contrast pivots and
controls for each end of their curves. J Contrast grades neutral colors and
preserves cone-chart saturation. Shadow Chroma and Highlight Chroma adjust
saturation by lightness. C Pivot controls only the C Contrast crossover.
Muted and Vivid shape opposite ends around a fixed midpoint. Raising C Pivot
raises saturation at negative contrast and lowers it at positive contrast
for chromatic samples at nonzero lightness.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_global_shape_prototype --show-output
```

Use the English or Simplified Chinese DCTL in the Color J/C position of the
cone chain. [Controls and Resolve audition](JC-OVERLAP-PROTOTYPES.md#global-jc-shaping)

## Warp quadratic Scale audition

This Warp variant linearly interpolates positive scale slopes between radial
anchors, giving the scale operation a closed-form quadratic inverse. The target
builds English and Simplified Chinese files for the Warp position in the cone
chain.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:warp_quadratic_scale_prototype --show-output
```

Hue, chroma radius and Adaptance retain their iterative inverses.
[Scale behavior and Resolve audition](REVERSIBLE-STAGE-3.md#warp-quadratic-scale-audition)

## Color-JC saturation surface prototype

The standalone XYZ surface prototype gives J and C one contrast amount per
tone anchor and independent saturation centers and widths. A single slider
sets overall chroma gain. Build the English and Simplified Chinese versions with

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_surface_prototype --show-output
```

The control equations, design decisions, and Resolve audition steps are in the
[saturation surface design](JC-SURFACE-PROTOTYPE.md).

## Color-JC LGG prototype

The standalone XYZ prototype puts six scalar Lift, Gamma and Gain controls in
each tonal row, three for lightness and three for chroma. Build all three
variants in English and Simplified Chinese, for six prototype files total, with

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_prototype --show-output
```

The file list, control equations, Resolve audition procedure and development
path through the reference library and Next Blender are in the
[LGG prototype design](JC-LGG-PROTOTYPE.md).

## Verification

The DCTL test harness compiles the generated float32 entry points, compares
them with independent float64 calculations, and checks color ordering and
round trips. The portability suite checks both locales with C++ and OpenCL.

```sh
buck2 test --remote-only \
  //products/perceptual-grade-dctl/tests:interface \
  //products/perceptual-grade-dctl/tests:numerical \
  //products/perceptual-grade-dctl/tests:portability
buck2 build --remote-only //products/perceptual-grade-dctl:quality_report --show-output
```

The DCTL product uses the root [MIT](../../LICENSE-MIT) or
[Apache-2.0](../../LICENSE-APACHE) license, at your option.
