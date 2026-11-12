# Direct and sampled evaluation

The independent analytic reference is `libraries/perceptual-grade-reference`; the DCTL and frozen Blender product retain older production profiles. The Next Blender product currently exposes Stage 1 and Tone, and has not implemented Warp. This chapter describes the reference and sampled-kernel coordinates, while each table names the implementation it applies to.

## Choose the input sample grid

The reference and shared native LUT kernels use **linear ACEScg / ACES white** coordinates, independent of Blender's scene working space and each Grade's chosen white. Each component covers **0…1024**, with **64 positive intervals** and no negative sample branch. The LUT input repair maps out-of-cube RGB into this domain before sampling; the output cube guard is a separate projection after grading.

Let \(k=0.01\), \(R=1024\) and \(A=\ln(1+R/k)\approx11.536652\). For a nonnegative channel \(x\), the address shaper and inverse are

$$
S(x)=\frac{\ln(1+x/k)}{A},\qquad
S^{-1}(u)=k[\exp(Au)-1].
$$

Final vertices are \(x_i=S^{-1}(i/64)\), \(0\le i\le64\), with exact zero and upper endpoints. The 33-point preview takes every second vertex, giving 32 positive intervals in the same domain. This is plain log1p; the experimental warp exponent 0.9 is not used.

The bound is not a display range. A different bound changes the vertices throughout: at \(R=128\) the halfway address lands near \(1.121\), at \(R=1024\) near \(3.190\), and every intermediate vertex moves with it. Text or tooling carried over from the earlier \(0…128\) grid describes a different table, not a different naming of this one.

**No negative sample branch does not mean per-channel clipping.** Before reference-kernel lookup, `input_repair` projects an out-of-cube input: a neutral lift removes negative components while preserving nonnegative AP1 luminance, then one common scale brings the largest component to at most 1024. In-cube inputs are unchanged. Stored LUT outputs may still be signed or exceed the bound; this input projection is not output clipping.

The reference/shared sampler computes its physical interpolation fractions from the repaired input and clamps them to \([0,1]\). This differs from the book's legacy generator and the Next Blender kernel sampler, which use their own boundary contracts and may extrapolate the edge cell. Compare those profiles only after identifying their input repair and fraction rules.

![Native AP1 input samples](../assets/figures/lut-input-grid.svg)

<p class="figure-caption">The archived 0…128 ACEScg grid illustrates the sampling distribution. The current 0…1024 grid described above has different vertex positions. All intervals are positive; the zoom shows density close to zero.</p>

At 203 reference nits, neutral \(\mathrm{RGB}=1024\) corresponds to 207,872 nits. Peak Anchor remains an independent tonal target. Ordinary Grades keep Stage 1 as an exact matrix before the cube. Grade Stacks include every stage inside one cube.

## Preserve the grading function when changing the sampling basis

Canonical Grade coordinates still use Rec.709 primaries interpreted through the selected Grade white. They do not become AP1 primaries. Let \(f\) be the canonical analytic function, \(P_0\) the Rec.709/D65 RGB-to-XYZ matrix, \(P_{\mathrm L}\) the native AP1/ACES-white RGB-to-XYZ matrix, and \(C_{0\to\mathrm L}\) Bradford adaptation from D65 to ACES white. Define

$$
B_{\mathrm L}=P_{\mathrm L}^{-1}C_{0\to\mathrm L}P_0,\qquad
f_b(z)=B_{\mathrm L}f(B_{\mathrm L}^{-1}z).
$$

Surrounding matrices convert the scene to and from fixed LUT coordinates. An ordinary forward Grade composes Stage 1 into the input matrix. A Stack includes each entry's matrix and white connection in the sampled function. The [full specification](../development/forward-inverse-math.md#195-lut-boundaries-and-mixed-white-stacks) gives the historical deployed equations; its reference section defines current reference evaluation.

Switching Blender's working space updates matrices and may reuse a cube when the canonical sampled function is unchanged. Changing a Grade white changes that function and requires a new bake. The matrix adapters do not clip channels; the LUT input-repair contract still applies at the native cube boundary. ACES white at the LUT boundary is a sampling choice, not a change to the default D65 Grade white or a display assumption.

## Why log1p on native AP1 was selected

The study below is a recorded measurement, not a description of the current table. It screened grids across a candidate set and selected the shaper and the sampling space; the numeric bound it reports was later raised. Read its bound column as the configuration it actually tested.

The [LUT domain study](../development/lut-domain-study.md) screened 150 grids and fully evaluated 12 finalists on all 338,688 stored IMG_* samples at −2, 0, +2, +4 and +6 stops, under five Grade/Stack workloads and four ACES 2.0 outputs. Scene RGB is scored for exact LUT inputs inside Rec.2020/D65 [0,10]³; rendered RGB is scored separately for exact inputs inside the native AP1 domain it tested. Outside-domain pixels are excluded from the corresponding metric.

**Version 1.21.0 adopts plain native AP1 log1p, κ = 0.01.** Among the full finalists, it wins the objective using display-linear RGB divided by each output's peak nits together with scene RGB p99/RMS: the worst ratio to the former production baseline is 0.530634. The encoded-RGB minimax winner was warped κ = 0.003, exponent 0.9. These are different objectives; plain log1p is the deliberate choice.

| Recorded worst per-case statistic | Former Rec.2020 −2…64 | Adopted AP1 log1p |
|---|---:|---:|
| Scene Rec.2020 absolute RGB p99 | 0.073063413 | 0.038344395 |
| Scene Rec.2020 absolute RGB RMS | 0.018554004 | 0.009574135 |
| SDR 100 Rec.709 encoded RGB p99 | 0.008575175 | 0.004779925 |
| SDR 100 P3-D65 encoded RGB p99 | 0.007430241 | 0.004028931 |
| HDR 1000 P3-D65 encoded RGB p99 | 0.004731874 | 0.003116317 |
| HDR 1000 Rec.2020 encoded RGB p99 | 0.003490032 | 0.002718339 |

These are photographic study measurements, not universal bounds. The adopted candidate improves all ten encoded-RGB objective terms too, with worst ratio 0.842753, but rare outliers remain. The stock Rec.2020/D65 → native AP1 matrix is nonnegative and maps the scene domain below the current bound, so the grid contains both requested metric domains without negative vertices. That historical sampler extrapolated signed inputs outside its domain. The study records complete distributions, limits and Buck2 reproduction commands.

Note that the study's conclusion is about the shaper and the space, not about the bound. Raising the bound from what that study tested to \(1024\) leaves the shaper unchanged and moves every vertex; the error figures above were not recomputed for the wider domain, and they should not be quoted as though they had been.

## Interpolate physical linear RGB

For reference/shared-kernel sampling, first set \(\hat x=\operatorname{input\_repair}(x)\). Locate the cell from its bounded address and calculate the physical fraction from that repaired input:

$$
i=\operatorname{clamp}\!\left(\left\lfloor64S(\hat x)\right\rfloor,0,63\right),\qquad
f=\operatorname{clamp}\!\left(\frac{\hat x-x_i}{x_{i+1}-x_i},0,1\right).
$$

Sort fractions \(f_1\ge f_2\ge f_3\). The tetrahedron vertices \(v_0,v_1,v_2,v_3\) follow that channel order from the low to high corner. Barycentric weights are \((1-f_1,f_1-f_2,f_2-f_3,f_3)\). The implementation uses their equivalent difference form:

$$
v=v_0+f_1(v_1-v_0)+f_2(v_2-v_1)+f_3(v_3-v_2).
$$

This form avoids cancelling a constant offset when the fractions are large, and it reproduces affine transforms in exact arithmetic. Native graphs use fused multiply-adds and select the middle fraction with min/max comparisons. Interpolation joins continuously across cell boundaries.

Because input repair precedes addressing, an input outside the cube is transformed before interpolation rather than independently clamped on each channel or extended along an edge cell. Within the cube, the tetrahedral fractions are bounded and the difference-form interpolant reproduces affine functions in exact arithmetic. Sampling error and input-projection change are separate effects.

![Shaping and physical-cell interpolation](../assets/figures/lut-interpolation.svg)

<p class="figure-caption">The address curve uses the archived 0…128 domain; the current 0…1024 grid has a different curve. The affine-cell example illustrates interpolation in physical input coordinates.</p>

Shader lookup stores raw float RGB. Compositor lookup stores the base RGB and three forward-axis differences in four planes of one image. Each coefficient has signed mantissas and its own shared power-of-two exponent. Four reads select one base and three ordered edges, avoiding subtraction of quantized neighboring vertices; the atlas uses four times the raw vertex storage. [Runtime architecture](../development/architecture.md#cross-compositor-storage-boundaries-safely) explains float32 computation and half-float image boundaries. Automatic precision remains a host setting.

## Curve tables and current-grade publication

Tables are not shared across implementations, and they are not the same size even within one. Treating any single count as "the table resolution" has been the source of repeated documentation errors, so each is listed per profile:

| Profile | Stage 2 (Tone) | Stage 3 (Color) | Boundary |
| --- | --- | --- | --- |
| Independent analytic reference | closed form, no table | closed form, no curve table | Cached D65 cube context; decoded RGB is validated |
| Reference `BakeStack` | Prepared inverse Tone table | Reference forward kernel | Shared native AP1 LUT and output cube projection |
| Frozen 1.23.2 production profile | Adaptive inverse Tone table, cap 2048 cells | 1.23.2 controls and ordering | Historical production boundary resources |
| Next Blender product | Current Stage 1/Tone implementation | Warp not implemented or exposed | Product LUT contract is still evolving |

**The independent analytic reference has no per-pixel curve table.** It evaluates tone and coefficient kernels directly. Stage 3's tonal web, selective Adaptance and guard-before-Scale order are the current reference model. Next Blender has not yet implemented that Warp path.

**The reference's accelerated `BakeStack` also prepares an inverse Tone table.** This is an acceleration resource, not a change to the independent analytic forward model. Separately, the frozen 1.23.2 inverse bake adaptively adds scalar inverse-tone cells by bisection until five-fraction probe error and a Bernstein monotonicity check pass. `MAX_CELLS = 2048`, 32 refinement rounds, 80 root evaluations and a 64 KiB budget bound that historical refinement; 2048 is an abort condition, not a stored size. Above its tail threshold the legacy table is not consulted and the linear asymptote is evaluated analytically.

**Next Blender's current product scope is narrower than the reference model.** Its user-facing implementation covers Stage 1 and Tone; the future Warp and corrected H–K-before-Scale ordering are not part of its current render contract. Experimental Color preparation code is not a shipped Warp implementation or evidence of renderer behavior.

**The chroma classifier has no table in any profile.** The p=2 low/high split is evaluated from the carried achromatic lightness and the current chroma at every pixel. An earlier design sampled a chroma threshold; that row is gone.

**Boundary resources are implementation-specific.** The archived Blender build and its shared production kernels use the recorded 257 × 257 uint16 face atlas and spline resources. The DCTL carries its own compact constants. The analytic reference validates cube trials through its decoder and uses its cached D65 cube context. Do not attribute one profile's boundary table or solver to another.

Shared endpoint value, first derivative and second derivative define the quintic interpolant wherever a tone or coefficient curve is tabulated, preserving \(C^2\) joins at every knot. DCTL curves remain analytic throughout.

A bake uses the selected model and publishes only for its current parameter signature. Historical Blender Direct previews and final LUT publication are release-specific behavior. Sampler agreement and analytic approximation error are separate checks. A uniform `.cube` reader would require resampling this nonuniform baker/sampler.

## Inverse and Stack sampling

The reference inverse and reference `BakeStack` use the current corrected forward model. The retained production inverse and Stack sections in the full mathematical specification describe their historical profile. Every reference Stack stage runs at each vertex, including its matrix, without sampling an intermediate 3D LUT.

The shared nested-grid profile installs a 33³ preview, then refines to 65³, reusing all 35,937 preview vertices exactly and evaluating only the remaining 238,688. These counts describe the sampled-kernel profile, not proof of reference inverse accuracy. Small inverse residuals at vertices do not establish between-vertex accuracy.

[Download the production axes, matrices and constants](../downloads/lut-production.json). The file records the earlier \(0…128\) axis and is retained as an archive; it is not regenerated, and its `axis_65` does not describe the \(1024\) bound above.
