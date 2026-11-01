# Native AP1 production LUT validation (1.21.0)

Adopts `AP1_ACES_neg0_pos128_n0_log1p0.01`: native ACEScg/ACES white [0,128], plain log1p κ = 0.01, 64 positive intervals. The previous signed Rec.2020 production shaper and its oracle module are removed. No older-project compatibility or migration code was added.

The analytic grading model and shared Grade whites remain unchanged. Bradford converts canonical Rec.709/D65 coordinates to native AP1/ACES white around the cube. Ordinary Stage 1 remains exact outside the cube; Stack stages are baked together. Negative and HDR inputs use physical-cell extrapolation.

Interpolation uses ordered vertex differences, a comparison-based median and native fused multiply-adds. Compositor transport stores one RGBE base and three independently encoded axis differences in one image, retaining four reads and avoiding subtraction of quantized neighbors. Raw Shader atlases are 1024×36/269 for 33³/65³. Compositor atlases are 1024×141/1073; this uses four times the raw atlas storage. Packed readback reconstructs the original float32 vertices exactly.

## Validation

- 17 related fixture scripts and six actual native benchmark cases passed.
- 32 mathematical/transport checks; 102 working-white checks; 53 Stack editing pytest cases; 36 native Stack checks.
- 12 independent-oracle grades and 4 frozen analytic fixture grades passed. The largest oracle relative difference was 5.08641741e-13.
- CPU Shader/Compositor sampler maximum relative difference was 7.65434914e-07.
- 34 buffer-emulation cases of 4483 samples each were finite, with no half-buffer overflow. Maximum full-float/emulated-Python difference was 2.49666085e-05. Half/full differences remain larger for strong controls and cancellation; maximum 0.019081492, within the existing declared grade-specific gate. This is separate from ACES-rendered interpolation quality.
- Nested preview/refinement retains all 35,937 common float32 vertices bit for bit and evaluates exactly 274,625 total analytic vertices for one settled snapshot.

The handbook provides the axes, matrix equations, adoption rationale, Buck2 gates and historical study results. The κ = 0.01 candidate wins the display-linear/peak-nits objective among +128 full finalists; the encoded-RGB objective prefers the different warped candidate. Study metrics are not universal error bounds or GPU transport certification.

Tests ran as isolated authoring previews with the pinned development bpy/NumPy environment. Native Buck2 cannot start here because `/proc/self/exe` is unavailable. No GPU/Metal results are claimed. See `ap1-lut-validation.json` for source/log fingerprints and complete counts; full-source validation records accompany the package.
