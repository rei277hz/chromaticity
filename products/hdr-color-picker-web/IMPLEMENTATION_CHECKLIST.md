# Implementation checklist

## Documentation and contracts

- [x] Documentation defines display sources and RAW preparation at the XYZ-D65 boundary.
- [x] Document ACEScg/AP0 as scene-reference-only formats.
- [x] Document `inverse_from_xyz_d65` as the sole canonical inverse entry.
- [x] Document RGB→XYZ-D65 adapters and the DNG linear-1.0 reference-white policy.
- [x] Use Color trackpad and J′ trackwheel consistently for the related
      track-motion controls.
- [x] Check in the official post-November-2014 X-Rite 24-patch Lab D50 file
      with source, checksum, measurement, format, and active-subset metadata.
- [x] Document the 18 chromatic-patch UI subset and retain all six neutral
      patches in the provenance asset without adding UI dots.
- [x] Document direct CAT02 D50→ACES-white adaptation without ColorChecker
      RICD scaling, inverse ACES, or scene-side 203-nit placement.
- [x] Document the DNG ForwardMatrix and ColorMatrix camera-to-D50 branches
      separately from the common CAT02 D50→D65 application boundary.
- [x] Document Bradford for project-owned ICC PCS adaptations and CAT02 for
      project-owned non-ICC white-point boundaries, with the explicit DNG
      fallback and CAT16 exceptions.

## ACES source conversion

- [x] ACEScg preparation performs AP1→AP0 exactly once.
- [x] Preserve ACES2065-1/AP0 identity conversion.
- [x] AP0 is never interpreted as XYZ-D65.
- [x] Add regression coverage for primaries and neutral XYZ-D65 conversion.
- [x] Replace the project-owned D65↔ACES-white Bradford matrix pair with
      mutually inverse CAT02 matrices.

## Canonical inverse and scene paths

- [x] The canonical inverse implementation is `inverse_from_xyz_d65` and
      matches the official numerical behavior.
- [x] Supported display-referred RGB sources have RGB→XYZ-D65 adapters.
- [x] No inverse-from-ACEScg, inverse-from-AP0, or inverse-from-Rec.2020 entry
      points exist.
- [x] Direct scene-reference ACEScg and AP0 forward paths are available.
- [x] Ensure decomposition CPU paths call the native AP0 forward transform
      without an AP0→AP1→AP0 roundabout.
- [x] Mirror the native AP0 boundary in WebGPU/WGSL and remove its unused
      AP0/AP1 roundtrip matrices.
- [x] Expose forward target RGB for output clipping instead of converting
      XYZ→RGB→XYZ.
- [x] Retain the picker's intentional nonlinear inverse/forward reconstruction;
      it applies the selected ACES view's gamut mapping and is not a redundant
      color-space matrix roundabout.
- [x] Add same-profile conversion fast paths and complete the production
      A→B→A audit.
- [ ] Verify CPU/WASM/WebGPU parity after the direct-path changes.

## RAW/DNG

- [x] RAW decoding includes calibration, demosaicing, opcodes, and orientation.
- [x] Use a valid ForwardMatrix plus its required white-balance/calibration
      factors as the profile-defined camera→XYZ-D50 transform, and report it
      as used only when that transform succeeds.
- [x] Without a usable ForwardMatrix, use the ColorMatrix path with linear
      Bradford from the selected camera white to D50.
- [x] Apply the same CAT02 XYZ-D50→XYZ-D65 boundary after either DNG branch.
- [x] Preserve signed and above-one XYZ-D65 values without clamping.
- [x] Diagnostics, metadata, and source modes identify XYZ-D65.
- [x] Route DNG through inverse HDR Rec.2020 with linear 1.0 as reference white.
- [x] Force the DNG 2.03-encoded reference-white option unchecked and disabled.
- [x] Show helper text explaining the fixed DNG reference-white convention.
- [x] Use the same XYZ-D65 path for preview, loupe, and sampling.

## Image and EXR routing

- [x] Route ACEScg EXR through direct scene-reference ACEScg presentation.
- [x] Route ACES2065-1 EXR through direct scene-reference AP0 presentation.
- [x] Ensure scene-reference EXR bypasses inverse ACES and reference-white scaling.
- [x] Route display-referred RGB images through RGB→XYZ-D65 adapters.
- [x] Production display and analysis routing uses the XYZ-D65 boundary.
- [x] Adapt embedded ICC XYZ-PCS/D50 output to XYZ-D65 with Bradford.
- [x] Generate SDR ICC colorants and `chad` tags with Bradford.

## Tests

- [x] ACEScg conversion regression (no erroneous XYZ-D65 round trip).
- [x] Canonical inverse and adapter equivalence tests.
- [x] Scene-reference EXR tests proving inverse bypass.
- [x] DNG camera-neutral XYZ-D65 test.
- [ ] DNG signed/above-one preservation test.
- [x] DNG disabled-control UI test for the fixed linear-1.0 reference-white path.
- [ ] End-to-end DNG preview, loupe, sampling, and availability tests.
- [ ] CPU/WASM/WebGPU numerical parity tests for the direct AP0 paths.
- [x] Verify all 24 provenance records and exact mapping of the active 18 Lab
      D50 constants.
- [x] Verify direct CAT02 D50→ACES-white/AP1 conversion without an
      intermediate D65 ColorChecker adaptation.
- [x] Verify ICC PCS D50→D65 and generated ICC `chad` adaptations are
      Bradford.
- [x] Verify valid, absent, and invalid ForwardMatrix branches, including the
      common CAT02 final boundary and accurate diagnostics.
- [x] Verify ColorChecker uses direct CAT02-derived ACEScg targets without RICD
      or a calculated 203-nit scene gain.
- [x] Verify every ColorChecker API shares the same scene targets while
      preserving record layouts, patch order, dot availability, and snapping.

## ColorChecker scene targets

- [x] Centralize official Lab D50 patch data and the active 18-patch mapping.
- [x] Convert Lab D50→XYZ D50→CAT02-adapted ACES-white XYZ→ACEScg/AP1.
- [x] Do not apply RICD flare/scale or any separate scene gain.
- [x] Do not run ColorChecker patches through inverse ACES view transforms.
- [x] Update active normalized and legacy/public ColorChecker APIs to use the
      shared target helper.

## Consistency

- [x] Comments, names, and documents describe DNG as XYZ-D65.
- [x] Production inverse API names and source-mode strings match current routing.
- [x] Update the standalone ColorChecker tool, independent OCIO oracle, and
      user-facing README to match the adaptation policy.
- [x] Run Rust color-core tests, decomposition checks/WASM builds, TypeScript,
      OCIO, PNG/ICC, and the full browser/image-worker suite using the original Node environment.
      The monorepo import removes the stale declaration of the absent native GPU
      test module. Imported native tests and production archive acceptance
      are separate Buck checks; GPU parity still requires explicit evidence.
