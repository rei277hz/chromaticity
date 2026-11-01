# Perceptual Grade 1.15.0: working-white validation and LUT precision

The extension uses fixed **linear Rec.709 / D65 LUT boundaries**. Grades in this measurement use D65, ACES and D50 respectively. Their matrices are first constructed in D65 and then rebased to the chosen white; Tone/Color values are retained. The mixed sequence is Forward A → Inverse B → Forward C. The Stack bakes every Stage 1 and white connection into one 65³ LUT; the comparison chain samples three separate nonlinear LUTs with their exact external Stage 1 matrices.

## Measurement contract

- Four IMG_* fixtures contribute 2,048 deterministic, unclipped samples each (seed 1140065). Their source is linear Rec.2020/D65; samples are converted to the fixed Rec.709/D65 coordinates before grading.
- Additional probes: 2,048 positive HDR colors, 2,048 signed HDR colors and 256 inputs beyond the grid. The signed shaper grid spans RGB −64 to +64; forward-transformed inverse inputs can fall outside it.
- Bake evaluation uses float64 analytic equations and best-effort numerical inverse solves. Cubes store float32. Off-grid lookup uses tetrahedral interpolation in physical linear RGB.
- Error is `max(abs(actual-reference)) / (1+max(abs(reference)))` per sample, measured in the fixed linear Rec.709 coordinates. It is neither perceptual ΔE nor percent brightness. JSON includes absolute and floor-relative errors too.
- Full settings, sampling definitions and lattice diagnostics are in `working-white-precision.json`; the executable measurement is `tests/blender/evaluate_working_white_precision.py`.
- These results use different whites and RGB coordinates from the historical 1.14.1 report. Their numerical errors are not a direct before/after comparison.

## Ordinary inverse interpolation

The inverse LUT plus exact inverse Stage 1 is compared against the selected analytic-model inverse. Reproduction sends that LUT result through the complete analytic forward Grade.

| Fixture | Inverse p99 | Inverse max | Reproduction p99 | Reproduction max |
| --- | ---: | ---: | ---: | ---: |
| IMG_0436 | 0.000751503 | 0.0040726 | 0.000520829 | 0.00350806 |
| IMG_0441 | 0.00153069 | 0.00378575 | 0.000743295 | 0.00220643 |
| IMG_0446 | 0.00158654 | 0.00466975 | 0.00104419 | 0.00307211 |
| IMG_0472 | 0.00363339 | 0.206524 | 0.00215582 | 0.180873 |

The analytic-model inverse itself has photographic p99 normalized reproduction errors below 2.60e-11; its worst sample is 4.11e-8. LUT interpolation is the larger error in these fixtures. IMG_0472 has a substantial inverse interpolation outlier (0.206524 normalized error); a small p99 must not be read as a bound on every pixel.

## One mixed Stack versus three LUTs

| Fixture | Stack p99 | Chain p99 | Stack max | Chain max |
| --- | ---: | ---: | ---: | ---: |
| IMG_0436 | 0.000496867 | 0.000671023 | 0.0121756 | 0.0113885 |
| IMG_0441 | 0.00042816 | 0.000432172 | 0.00104849 | 0.00171259 |
| IMG_0446 | 0.00037127 | 0.000420846 | 0.000564323 | 0.000623718 |
| IMG_0472 | 0.00157522 | 0.00291375 | 0.0820831 | 0.121844 |

The Stack reduces p99 error in all four samples. Maximum error is not uniformly lower: the Stack is worse in IMG_0436. IMG_0472 still contains a large Stack outlier (0.0820831). Composing the analytic transforms removes intermediate interpolation, but does not guarantee greater accuracy everywhere.

## Fully forward sequence

| Fixture | Stack p99 | Chain p99 | Stack max | Chain max |
| --- | ---: | ---: | ---: | ---: |
| IMG_0436 | 0.000543056 | 0.000835097 | 0.00380997 | 0.0107333 |
| IMG_0441 | 0.000256401 | 0.000379576 | 0.00118668 | 0.00139403 |
| IMG_0446 | 0.000313456 | 0.00036245 | 0.000426742 | 0.00129732 |
| IMG_0472 | 0.00221842 | 0.00499369 | 0.116752 | 0.107312 |

## Signed/HDR and extrapolation stress

| Population | Inverse p99 / max | Mixed Stack p99 / max | Mixed chain p99 / max |
| --- | ---: | ---: | ---: |
| positive-HDR | 0.0221016 / 0.0298319 | 0.00119775 / 0.00272632 | 0.00129284 / 0.00387085 |
| signed-HDR | 0.0846788 / 0.303485 | 0.0704336 / 0.256936 | 0.0885569 / 0.283841 |
| outside-grid | 0.289935 / 0.401413 | 0.287751 / 0.381646 | 0.329417 / 1.16977 |

These broad stress errors are substantial. The fixed cube is not uniformly accurate across extreme signed colors, selected-inverse branches and extrapolation. No clipping is added to hide such errors.

## Inverse lattice solves

| Bake | Samples | Approximate | Worst reproduction residual |
| --- | ---: | ---: | ---: |
| Ordinary nonlinear inverse | 274625 | 174 | 0.0376056 |
| Inverse within mixed Stack | 274625 | 130 | 0.0266325 |

Approximate means forward reproduction residual exceeds 2e-8 before LUT storage. It records the bounded solver result, not proof that no exact preimage exists. This mixed Stack has no singular Stage 1 matrix.

## Working-space invariance and native validation

The new Blender fixture passed **102 checks** across all eight Grade whites, all three scene RGB spaces, both editors and four rendering paths (Direct, Forward LUT, Inverse, Stack). It covers shared values, unchanged Tone/Color controls, matrix-only Linear data and animation, white rebasing of animated matrices, unchanged anchors, derived controls, arbitrary/singular matrix retention, scope behavior, native Add-menu availability, save/load and LUT reuse across scene spaces.

- Maximum Stage 1 rebasing difference: 8.88178e-16 (absolute RGB-matrix coefficient error).
- Maximum regular matrix reconstruction difference: 5.2458e-15 (absolute XYZ-matrix coefficient error).
- Maximum coordinate-invariance error: 1.60216e-08 on the probe set, normalized per channel by `1+abs(reference channel)`.
- Maximum native CPU shader/compositor error against the matching numerical cube/Direct evaluator: 3.49617e-07, normalized per channel by `1+abs(reference channel)`. The fixture includes 24 native renders, and checks compositor alpha separately.

These boundary/rendering checks do not measure off-grid LUT approximation; the preceding tables do. Complete native results are in `working-white-native.json`.

## Time and verification scope

The fresh numerical precision bakes took **4.08 s** for the ordinary inverse, **5.13 s** for the mixed-white Stack and **1.05 s** for the forward Stack. These are single-run measurements on this host, excluding the edit debounce and Blender publication. The ordinary inverse meets five seconds in this run; the mixed Stack exceeds it. Settings, stack length and machine load affect timing.

All **53 fixtures** passed: 20 numerical, 19 Blender, 4 render, 7 DCTL and 3 parity fixtures. The UI fixture includes 1,648 checks. The tests ran with the explicit authoring-preview runner, pinned CPython/NumPy and Blender 5.2.2 LTS; Buck2 is unavailable here, so its release gate is not claimed. GPU/Metal and interactive desktop operation were not exercised. `working-white-validation.json` records each latest successful fixture log's hash.

The extension ships Python source and uses Blender's bundled NumPy. No platform-specific solver binary or external precompiled package is introduced. Only the current unpublished project format is handled; there is no older-project migration path.
