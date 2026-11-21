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
