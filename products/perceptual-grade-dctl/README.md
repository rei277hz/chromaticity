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
| `Perceptual-Grade-4-XYZ-Output.dctl` | Applies H–K repair using final signed energy, then decodes to linear XYZ D65 |

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

This prototype combines Cone Tone and Global Shape's chroma controls in one
DCTL. Use it in place of the separate Cone Tone and Color J/C nodes. Keep XYZ
Input before it and retain Warp and XYZ Output after it.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_tone_fit_prototype --show-output
```

Build details and Resolve audition steps are in the
[integrated Tone and J/C guide](JC-OVERLAP-PROTOTYPES.md#integrated-tone-and-jc).

## Global Color J/C shaping prototype

Global Shape gives lightness and saturation separate contrast pivots and
controls for each end of their curves. J Contrast grades neutral colors and
preserves cone-chart saturation. Shadow Chroma and Highlight Chroma adjust
saturation by lightness.

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_global_shape_prototype --show-output
```

Use the English or Simplified Chinese DCTL in the Color J/C position of the
cone chain. [Controls and Resolve audition](JC-OVERLAP-PROTOTYPES.md#global-jc-shaping)

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
