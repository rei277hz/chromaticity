# Perceptual Grade for DaVinci Resolve

Four standalone DCTLs grade scene-linear **XYZ D65**, with reference white at
Y = 1 (203 nits). Install either the English files or the Simplified Chinese
files with the `-zh-HANS` suffix. Each node can be used independently.

| Node order | DCTL | Adjustments |
| --- | --- | --- |
| 1 | `Perceptual-Grade-1-Linear.dctl` | Exposure, CAT16 source white, and balance, spread and heading on the cyan–red and yellow–blue axes |
| 2 | `Perceptual-Grade-2-Tone.dctl` | Black, Shadows, Midtones, White and Highlights input levels in nits, curve Fit and output peak |
| 3A | `Perceptual-Grade-3A-Color-JC.dctl` | Global chroma gain, J and C Fits, low/high chroma responses and signed a/b coefficients for all four tonal rows |
| 3B | `Perceptual-Grade-3B-Warp.dctl` | Chroma, hue and scale for each of six Rec.709 handles in each tonal row, plus four Adaptance centers and half-influence saturation |

## Install and use

1. Build both locales. Buck prints the directory containing all eight files.

   ```sh
   buck2 build --remote-only //products/perceptual-grade-dctl:dctl --show-output
   ```

2. In Resolve's **Project Settings → Color Management → Lookup Tables**, open
   the LUT folder, copy the four files for your locale there and choose **Update
   Lists**. On the Color page, add a DCTL effect to each serial node and choose
   its stage from the DCTL menu.
3. If your node graph works in RGB or log, place a Color Space Transform before
   the first DCTL to convert the node's working gamut and gamma to **CIE XYZ**
   with **Linear** gamma and D65 white. After the last DCTL, use the reverse
   transform to return to the working gamut and gamma. Set tone mapping and
   gamut mapping to **None** on both transforms. Put display rendering
   downstream of this scene-linear chain.
4. Match **Peak Nits** across Tone, Color J/C and Warp so their output tonal
   anchors agree. The default is 1000 nits. With all controls at reset, each
   stage passes finite input through exactly, including negative and HDR values.

## Color controls and output

J/C has 32 float coefficients across Shadows, Midtones, White and Highlights.
Low and high chroma have equal influence at C = (35/75) × |J_A|. The signed a/b
sliders specify the two components of each tonal pad. Warp has 24 integer hue
sliders in degrees and 57 float sliders. Hue displacements must preserve the
cyclic order red, yellow, green, cyan, blue, magenta in each row.

Both Color nodes derive their selectors and H–K reference energy from the XYZ
image entering that node. Active J/C edits receive H–K repair before XYZ
output. Warp applies hue and chroma, selects its scale, applies selective
Adaptance and H–K repair, then scales the result. Chaining active J/C and Warp
can differ from the single reference Color stage, which retains selectors from
before the J/C edit.

All four outputs have an open range. The signed appearance decoder can return
negative values and values above 1024. The Blender input RGB repair and AP1-D65
output projection are omitted. Invalid settings, including crossed Warp hues,
display a magenta error pattern across the image. A pixel whose grade crosses a
cone-response pole displays the diagnostic at that pixel.

## Verification

The DCTL test harness compiles the generated float32 entry points and compares
their output with the independent float64 reference stages in linear XYZ.
The portability suite checks both locales with C++ and OpenCL.

```sh
buck2 test --remote-only \
  //products/perceptual-grade-dctl/tests:interface \
  //products/perceptual-grade-dctl/tests:numerical \
  //products/perceptual-grade-dctl/tests:portability
buck2 build --remote-only //products/perceptual-grade-dctl:quality_report --show-output
```

The DCTL product uses the root [MIT](../../LICENSE-MIT) or
[Apache-2.0](../../LICENSE-APACHE) license, at your option.
