# Final desired behavior

## Rec.2020 Color-Authoring Model

The picker is authored in HDR Rec.2020-D65 display-linear RGB. The selected
`(J′, x′, y′)` coordinates decode to linear Rec.2020 values. A coordinate is
available only when every Rec.2020 channel is finite and within the configured
Rec.2020 authoring range; when limited mode is active it must also be inside the linear
P3 cube. Unavailable slice pixels are black.

The authored Rec.2020 value is converted to XYZ-D65 where code value `(1, 1,
1)` is the 203-nit reference white. That value enters the canonical inverse
ACES 2.0 HDR 1000 nits Rec.2020 path directly and produces the canonical
ACEScg scene-linear value. The selected presentation view then converts that
ACEScg value to the app's display-linear RGB representation.

## ACES color-space boundaries

ACEScg/AP1 and ACES2065-1/AP0 are scene-reference formats only. They are never
treated as display-referred inputs to an inverse view transform.

Scene-reference ACEScg:

```text
ACEScg/AP1 scene RGB → AP1→AP0 once → selected forward ACES view
```

Scene-reference ACES2065-1:

```text
ACES2065-1/AP0 scene RGB → selected forward ACES view
```

Both paths preserve signed and above-one scene values until the official
forward view transform handles them. Sampling uses the direct scene value and
does not apply the inverse view transform or the display-linear multiplier.

There is exactly one canonical inverse API:

```text
inverse_from_xyz_d65(profile, xyz_d65) → ACEScg
```

It implements the official ACES 2.0 inverse output transform. Any
display-referred RGB source first uses its RGB→XYZ-D65 adapter, then calls this
API. Adapters never duplicate ACES fixed-function code, and there are no
separate ACEScg/AP0/Rec.2020 inverse ACES implementations.

Project-owned conversions between XYZ-D65 and the ACES white use CAT02. This
policy does not replace matrices that are part of the canonical ACES/OCIO
transform itself. Likewise, CAT16 remains part of the modCAM16-HK appearance
model and the RAW white-balance implementation; it is not a selectable
boundary adaptation.

Production color paths do not convert A→B→A merely to recover a value that
was already available in A. AP0 inputs enter the native AP0 forward transform,
and output-gamut clipping operates on the forward transform's target RGB before
a single conversion to XYZ. Intentional one-way conversions at an input or
output boundary, such as ACEScg input to AP0 processing or AP0 solver output to
an ACEScg EXR, remain explicit.

## RAW/DNG interpretation

RAW processing includes DNG decoding, active-area handling, black/white
normalization, demosaicing, supported opcodes, calibration interpolation,
white balance, baseline exposure, and orientation.

The camera-to-XYZ-D50 stage follows the selected DNG camera-profile path.

With a valid ForwardMatrix:

```text
camera RGB
→ camera-space white-balance and calibration factors
→ profile ForwardMatrix
→ XYZ-D50
```

The ForwardMatrix and its required factors define this camera-to-D50 stage. No
generic Bradford or CAT02 operation is inserted in place of the profile's
adaptation.

Without a usable ForwardMatrix:

```text
camera RGB
→ inverse ColorMatrix
→ linear Bradford from the selected camera white to D50
→ XYZ-D50
```

Both branches then use the same application boundary conversion:

```text
XYZ-D50 → CAT02 D50→D65 → linear XYZ-D65
```

CAT02 at this final boundary is an application policy, not a requirement
inferred from the presence of a ForwardMatrix. The same XYZ-D50 value therefore
produces the same XYZ-D65 value regardless of the camera-profile branch that
created it. A present but unusable ForwardMatrix falls back to the ColorMatrix
path and is reported as not used.

The prepared DNG raster is XYZ-D65. It does not round-trip through AP0 or
ACEScg, and negative or above-one XYZ values are not clamped.

The same XYZ-D65 boundary is used for ordinary display-referred PNG/JPEG,
manual RGB overrides, ICC RGB profiles, and HEIC/HEIF (including gain-map)
pixels. ICC DeviceToPCS processing remains profile-defined; the resulting
XYZ-PCS values are adapted from D50 to D65 with Bradford. Generated SDR ICC
profiles likewise use Bradford for their D65-to-D50 colorants and `chad` tag.
ACEScg/AP0 choices are available only for EXR scene-reference input.

For this application, DNG camera white uses the fixed 1.0 reference-white
workflow:

```text
prepared XYZ-D65
→ inverse_from_xyz_d65(HDR 1000 nits Rec.2020)
→ ACEScg
```

The image, loupe, and sample analysis use this same path. The image option
`Image reference white is encoded as linear 2.03` is unchecked and disabled for
DNG, with helper text explaining that RAW/DNG uses linear 1.0 as reference
white.

## Scene-reference EXR

An EXR identified or manually overridden as ACEScg is decoded as scene ACEScg;
an ACES2065-1 EXR is decoded as scene AP0. Both bypass inverse ACES and any
reference-white scaling. They are presented through the selected forward view
and sampled directly as scene data.

## Presentation and encoding

The selected view determines the displayed encoding:

- SDR Rec.709: 8-bit RGB PNG with sRGB ICC.
- SDR P3-D65: 8-bit RGB PNG with Display P3 ICC.
- HDR P3-D65: 16-bit PQ RGB PNG with P3-D65 metadata.
- HDR Rec.2020: 16-bit PQ RGB PNG with Rec.2020-D65 metadata.

The gamut slice, ColorChecker layer, picked-color preview, image preview, and
loupe use the selected view’s after-transform display-linear values. For HDR
PNG encoding only, those values are multiplied by 2.03 before PQ encoding so
linear `(1, 1, 1)` is stored with the common 203-nit viewer convention.

## ColorChecker references

ColorChecker targets use the official post-November-2014 X-Rite ColorChecker
Classic CIELAB D50 reference data. The checked-in provenance asset contains all
24 patches; the picker continues to expose the 18 chromatic patches in its
established UI order. The six neutral patches remain reference data and are not
rendered as picker dots.

Each active patch is converted to its ACEScg scene-reference target through one
direct white adaptation:

```text
official Lab D50
→ XYZ D50
→ CAT02 D50→ACES white (x=0.32168, y=0.33767)
→ ACEScg/AP1
```

ColorChecker references never use RICD scaling, inverse ACES view transforms,
post-forward RGB multipliers, or an intermediate D65 adaptation before being
adapted to the ACES white.

The interactive gamut-slice surface is the **Color trackpad**. The vertical
lightness control is the **J′ trackwheel**. Both use the shared track-motion
velocity and acceleration profile while retaining their respective two-axis
and one-axis coordinate mappings.

## Validation invariants

- CPU/WASM and WebGPU use identical official ACES tables and equations.
- Scene ACES inputs never call the inverse output transform.
- Display-referred RGB inputs always pass through RGB→XYZ-D65 before the one
  canonical inverse API.
- Project-owned ICC PCS adaptations use Bradford; project-owned non-ICC
  white-point boundary adaptations use CAT02 except for the DNG ColorMatrix
  fallback's specified linear-Bradford camera-white→D50 stage.
- A successful DNG ForwardMatrix is used as the profile-defined camera→D50
  transform, followed by the same CAT02 D50→D65 boundary as the fallback.
- DNG diagnostics and source modes identify XYZ-D65, never AP0.
- DNG analysis uses the prepared XYZ-D65 raster.
- Production transform paths contain no redundant A→B→A color-space
  roundabouts.
