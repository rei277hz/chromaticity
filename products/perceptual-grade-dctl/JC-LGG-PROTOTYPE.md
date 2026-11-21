# Color-JC LGG prototype

The Color-JC prototype uses Lift, Gamma and Gain controls inspired by
traditional grading wheels. Resolve audition determines the control labels,
ranges and response before the design becomes a reference library contract.

## Development path

1. Build the DCTL prototypes with the `:jc_prototype` Buck target and audition
   them in Resolve.
2. Record the accepted design after Resolve audition. Iterate on the DCTLs if
   the audition calls for changes.
3. Implement the accepted behavior in `libraries/perceptual-grade-reference`.
4. Propagate the accepted reference behavior into
   `products/perceptual-grade-next-blender`.

## Prototype files

The target emits three variants for each supported locale, six prototype files
in total.

| Variant | English | Simplified Chinese | Purpose |
| --- | --- | --- | --- |
| Baseline | `Perceptual-Grade-3A-Color-JC-LGG-Prototype.dctl` | `Perceptual-Grade-3A-Color-JC-LGG-Prototype-zh-HANS.dctl` | Evaluate the default axis and fixed perceptual pivot |
| Non-log | `Perceptual-Grade-3A-Color-JC-LGG-NonLog-Prototype.dctl` | `Perceptual-Grade-3A-Color-JC-LGG-NonLog-Prototype-zh-HANS.dctl` | Compare an inverse-square-root saturation axis |
| Adjustable pivot | `Perceptual-Grade-3A-Color-JC-LGG-Pivot-Prototype.dctl` | `Perceptual-Grade-3A-Color-JC-LGG-Pivot-Prototype-zh-HANS.dctl` | Test whether a direct saturation pivot is useful in grading |

Build them with

```sh
buck2 build --remote-only //products/perceptual-grade-dctl:jc_prototype --show-output
```

## Control model

The four tonal rows are named `S`, `M`, `W` and `H` for Shadows, Midtones,
White and Highlights. The six controls in each row use the generated names
`tone{row}{channel}{control}`.

| Channel | Controls per row | Range | Step | Meaning |
| --- | --- | ---: | ---: | --- |
| J | `tone{S/M/W/H}JLift`, `tone{S/M/W/H}JGamma`, `tone{S/M/W/H}JGain` | Lift -20 to +20 H-K points, Gamma/Gain -2 to +2 stops | Lift 0.1, Gamma/Gain 0.01 | Lightness change |
| C | `tone{S/M/W/H}CLift`, `tone{S/M/W/H}CGamma`, `tone{S/M/W/H}CGain` | -2 to +2 stops | 0.01 | Chroma change |

The shared controls are `lightnessFit`, `chromaFit` and `peakNits`. The Pivot
variant adds `saturationPivot`, with a range from `0.05` to `2.00`, a step of
`0.01`, and a default computed from `35/75`. The other variants use the fixed
pivot `35/75`.

The existing J and C Fit curves select how much each tonal row contributes.
Within a row, the Lift, Gamma and Gain response runs along saturation. For
example, Midtones J Gamma changes the lightness of muted and vivid midtone
colors in opposite directions. The controls are scalar and hue-independent.
The six controls per row replace the original low/high-chroma drivers and
a/b pads for this prototype. For hue adjustments in the cone chain, use Warp.

## Saturation axis

Before any J or C request, the kernel freezes the incoming H-K magnitude
`hypot(J_A, sqrt(66*C))`, chroma `C`, and signed achromatic lightness `J_A`.
It then computes

`r = C / (pivot * abs(J_A))`

with a stable zero-`J_A` branch. The baseline and Pivot variants use the
log-like axis

`u = log2(1 + r)`

`x = u / (1 + u)`

The NonLog variant uses the inverse-square-root axis

`x = 1 - 1 / sqrt(1 + 3*r)`

Both axes map neutral gray to `x = 0`, the pivot condition to `x = 0.5`, and a
chromatic sample with `J_A = 0` to `x = 1`.

The gamma bend is

`B(gamma) = -gamma * (2*x - 1)`

A negative Gamma reduces the request on the muted side and increases it on
the vivid side. Gamma contributes zero at the pivot.

## C response

For each tonal row, the requested C adjustment in stops is

`stops = C Lift * (1 - x) + B(C Gamma) + C Gain`

The kernel blends the row requests in stops using Chroma Fit, then requests

`C' = C * 2^stops`

A blended C Gain of `+1` alone requests twice the input chroma. At full row
influence, C Gamma of `-1` alone makes the near-gray slope approach 0.5 and
the vivid-end gain approach 2. The C-only path keeps the incoming H-K value
as the target and updates signed energy for the requested chroma before
applying the existing H-K guard. Multiplication preserves exact gray and
applies the full relative response to weak colors.

## J response

For each tonal row, the J request before Fit interpolation is

`deltaJ = 2^(J Gain) * (20*x * 2^B(J Gamma) + J Lift*(1 - x)) - 20*x`

The kernel blends the row offsets using Lightness Fit and fades that result
toward black with the existing quintic smoother from zero input H-K magnitude
to the Shadows anchor. At full row influence and above the black fade, J Gain
of `+1` alone requests `+10` H-K points at the pivot and approaches `+20`
points at the vivid endpoint. J Lift supplies the neutral-end offset. J Gain
also scales that offset when J Lift is active.

## Decision record

| Design choice | Prototype behavior | Flexibility | What to audition |
| --- | --- | --- | --- |
| Saturation axis | Baseline and Pivot use the log-like curve. NonLog uses the inverse-square-root curve | High. Swapping the axis preserves control names and pivot meaning | Compare muted, middle and vivid colors with equal settings in Baseline and NonLog |
| Fixed or adjustable pivot | Baseline and NonLog fix `35/75`. Pivot exposes `saturationPivot` from `0.05` to `2.00` | High. The same kernel can support either policy | Compare responses at `0.25`, the default `35/75`, and `1.0`. Check whether adjusting the pivot is practical from shot to shot |
| C response near gray | Exact gray stays neutral. Weak colors receive the full relative response | High. A smooth fade can protect muted colors while preserving the controls | Apply C Gain and C Gamma to gray ramps, pastel material and skin. Decide whether a fade would help and where it should start |
| Lift and Gamma taper | Lift uses `(1-x)` and Gamma uses a signed bend centered at `x = 0.5` | Medium. The tapers can be tuned within the same layout | Check whether Lift covers enough muted colors and Gamma redistributes saturation or lightness as intended |
| J calibration and slider ranges | The J expression uses a 20 H-K-point scale. J Lift spans -20 to +20 points. The stop controls span -2 to +2 | Medium. Calibration and ranges can be tuned before promotion | Compare J Gain `+1`, J Lift `+10` and J Gamma `-1` and `+1` on ramps. Judge the useful range and step sizes |
| J fade near black | A quintic fade reaches full strength at the Shadows anchor, based on incoming H-K magnitude | Medium. The fade can be retuned while preserving exact black | Sweep J Lift and J Gain through dark neutral and chromatic ramps |
| Saturation-driven J and C | J and C use the same frozen `x` with separate requests | Medium. Channel-specific axes would change how the two sets of controls relate | Compare muted and vivid samples at the same tonal anchor to see whether it is useful to control their lightness separately |
| Scalar hue-independent controls | Each control is one scalar. Warp provides hue-specific shaping | Low. Adding hue dependence changes the interface | Compare hues at matched H-K magnitude and saturation. Check whether Warp supplies enough separate hue control |
| Existing tonal Fit interpolation | J and C requests use the corresponding Fit curves for Shadows, Midtones, White and Highlights | Medium. Recalibrating Fit would also change how adjacent rows blend | Sweep the tonal range and check row isolation and smooth handoffs |
| Signed XYZ, exact reset and H-K repair | The signed XYZ range stays open. Reset and black pass through exactly. Active edits use H-K repair and visible diagnostics | Low. These contracts preserve interoperability with the DCTL stages | Compare reset on negative and HDR input. Examine extreme active settings for visible repair or diagnostic behavior |

## Resolve audition checklist

1. Build `:jc_prototype` remotely and install one locale's three files alongside
   the existing DCTLs.
2. Run the prototype on scene-linear XYZ D65, outside the XYZ Input/Output
   cone chain, and keep display rendering downstream.
3. Compare Baseline and NonLog with identical settings on neutral ramps,
   saturated ramps and skin-like colors.
4. Start the Pivot variant at its default, then move `saturationPivot` through
   its range and compare against Baseline.
5. Lower Midtones C Gamma to `-1` and set C Gain to `+0.5`. At full row
   influence, the chroma request ranges from `-0.5` stops near gray through
   `+0.5` stops at the pivot to `+1.5` stops at the vivid endpoint. Check how
   that separation looks after H-K repair.
6. Exercise the J and C controls across all four rows. Record the accepted
   axis, pivot policy, near-gray policy and any range changes before
   implementing the reference library.

The DCTL test harness covers both locales, float64 numerical comparisons and
C++ and OpenCL compilation. Design acceptance depends on the Resolve audition.

## Processing contracts

All prototype variants grade signed linear XYZ D65 and decode directly to XYZ
D65 with an open output range. Pre-input RGB repair and pre-output AP1-D65
boundary mapping belong to the Blender and ACES 2.0 compatibility path for
`[0,1024]`. Reset and black passthrough are exact. Active edits carry signed
energy through the existing H-K repair. Invalid settings or a failed
pixel decode produce visible magenta diagnostics.
