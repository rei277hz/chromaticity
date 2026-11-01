# Direct and sampled evaluation

The DCTL is the analytic reference. Direct uses native Blender nodes and tonal curve tables; Baked LUT uses a \(65^3\) color table. This chapter describes the extension's rendering approximations.

## Choose the input sample grid

The production cube uses **native linear ACEScg / ACES white**, independent of Blender's scene working space and each Grade's chosen white. Each component covers **0…128**, with **64 positive intervals** and no negative sample branch. The selected experimental configuration is `AP1_ACES_neg0_pos128_n0_log1p0.01`.

Let \(k=0.01\), \(R=128\) and \(A=\ln(1+R/k)\). For a nonnegative channel \(x\), the address shaper and inverse are

$$
S(x)=\frac{\ln(1+x/k)}{A},\qquad
S^{-1}(u)=k[\exp(Au)-1].
$$

Final vertices are \(x_i=S^{-1}(i/64)\), \(0\le i\le64\), with exact zero and upper endpoints. The 33-point preview takes every second vertex, giving 32 positive intervals in the same domain. This is plain log1p; the experimental warp exponent 0.9 is not used.

**No negative sample branch does not mean clipping RGB.** Only addresses are bounded to [0,128]. Negative inputs extrapolate the first physical linear-RGB cell; inputs above 128 extrapolate the last. Stored outputs may be signed or exceed 128.

![Native AP1 input samples](../assets/figures/lut-input-grid.png)

<p class="figure-caption">The ACEScg grid covers 0…128. All intervals are positive; the zoom shows density close to zero.</p>

At 203 reference nits, neutral \(\mathrm{RGB}=128\) corresponds to 25,984 nits. Peak Anchor remains an independent tonal target. Ordinary Grades keep Stage 1 as an exact matrix before the cube. Grade Stacks include every stage inside one cube.

## Preserve the grading function when changing the sampling basis

Canonical Grade coordinates still use Rec.709 primaries interpreted through the selected Grade white. They do not become AP1 primaries. Let \(f\) be the canonical analytic function, \(P_0\) the Rec.709/D65 RGB-to-XYZ matrix, \(P_{\mathrm L}\) the native AP1/ACES-white RGB-to-XYZ matrix, and \(C_{0\to\mathrm L}\) Bradford adaptation from D65 to ACES white. Define

$$
B_{\mathrm L}=P_{\mathrm L}^{-1}C_{0\to\mathrm L}P_0,\qquad
f_b(z)=B_{\mathrm L}f(B_{\mathrm L}^{-1}z).
$$

Surrounding matrices convert the scene to and from fixed LUT coordinates. Ordinary Grades compose Stage 1 into the input matrix. Direct retains its canonical matrices, keeping the preview correct during baking. Stacks include every Grade matrix and white connection in the analytic function before sampling. The [full specification](../development/forward-inverse-math.md#195-lut-boundaries-and-mixed-white-stacks) gives the complete equations.

Switching Blender's working space updates matrices and reuses the cube. Changing a Grade white changes the function and triggers a rebake. No conversion clips negative RGB. ACES white at the LUT boundary is a sampling choice, not a change to the default D65 Grade white or a display assumption.

## Why this grid was selected

The [+128 study](../development/lut-domain-study.md) screened 150 grids and fully evaluated 12 finalists on all 338,688 stored IMG_* samples at −2, 0, +2, +4 and +6 stops, under five Grade/Stack workloads and four ACES 2.0 outputs. Scene RGB is scored for exact LUT inputs inside Rec.2020/D65 [0,10]³; rendered RGB is scored separately for exact inputs inside native ACEScg/ACES-white [0,128]³. Outside-domain pixels are excluded from the corresponding metric.

**Version 1.21.0 adopts plain native AP1 log1p, κ = 0.01.** Among the full finalists, it wins the objective using display-linear RGB divided by each output's peak nits together with scene RGB p99/RMS: the worst ratio to the former production baseline is 0.530634. The encoded-RGB minimax winner was warped κ = 0.003, exponent 0.9. These are different objectives; plain log1p is the deliberate production choice.

| Recorded worst per-case statistic | Former Rec.2020 −2…64 | Adopted AP1 0…128 |
|---|---:|---:|
| Scene Rec.2020 absolute RGB p99 | 0.073063413 | 0.038344395 |
| Scene Rec.2020 absolute RGB RMS | 0.018554004 | 0.009574135 |
| SDR 100 Rec.709 encoded RGB p99 | 0.008575175 | 0.004779925 |
| SDR 100 P3-D65 encoded RGB p99 | 0.007430241 | 0.004028931 |
| HDR 1000 P3-D65 encoded RGB p99 | 0.004731874 | 0.003116317 |
| HDR 1000 Rec.2020 encoded RGB p99 | 0.003490032 | 0.002718339 |

These are photographic study measurements, not universal bounds. The adopted candidate improves all ten encoded-RGB objective terms too, with worst ratio 0.842753, but rare outliers remain. The stock Rec.2020/D65 → native AP1 matrix is nonnegative and maps [0,10]³ below 128. Thus the new grid contains both requested metric domains without negative vertices. Signed colors outside those domains still need extrapolation. The study records complete distributions, limits and Buck2 reproduction commands.

## Interpolate physical linear RGB

For each channel, locate the cell with a bounded address, then calculate the fraction from the original input:

$$
i=\operatorname{clamp}\!\left(\left\lfloor64S(\operatorname{clamp}(x,0,128))\right\rfloor,0,63\right),\qquad
f=\frac{x-x_i}{x_{i+1}-x_i}.
$$

Sort fractions \(f_1\ge f_2\ge f_3\). The tetrahedron vertices \(v_0,v_1,v_2,v_3\) follow that channel order from the low to high corner. Barycentric weights are \((1-f_1,f_1-f_2,f_2-f_3,f_3)\). The implementation uses their equivalent difference form:

$$
v=v_0+f_1(v_1-v_0)+f_2(v_2-v_1)+f_3(v_3-v_2).
$$

This avoids cancellation of a constant offset under large signed extrapolation. Native graphs use fused multiply-adds and select the middle fraction with min/max comparisons. Physical-cell interpolation reproduces affine transforms in exact arithmetic and joins continuously. Far-negative inputs amplify vertex and arithmetic roundoff because the first cell is small; extrapolation is not an accuracy guarantee.

![Shaping and physical-cell interpolation](../assets/figures/lut-interpolation.png)

Shader lookup stores raw float RGB. Compositor lookup stores the base RGB and three forward-axis differences in four planes of one image. Each coefficient has signed mantissas and its own shared power-of-two exponent. Four reads select one base and three ordered edges, avoiding subtraction of quantized neighboring vertices; the atlas uses four times the raw vertex storage. [Runtime architecture](../development/architecture.md#cross-compositor-storage-boundaries-safely) explains float32 computation and half-float image boundaries. Automatic precision remains a host setting.

## Curve tables and current-grade publication

Direct uses 2048 intervals per tonal basis curve. Shared endpoint value, first derivative and second derivative define a quintic interpolant, preserving \(C^2\) joins. The tone residual has a monotonicity certificate; its linear asymptote is analytic outside the domain. DCTL curves remain analytic. The p=2 chroma classifier is analytic in both methods: Direct stores 14 basis curves and no sampled chroma-threshold curve.

A bake uses the analytic model and publishes only for its current parameter signature. Ordinary Grades preview current Direct values while baking; final render preparation finishes the selected table. Sampler agreement and analytic approximation error are separate checks. A uniform `.cube` reader would require resampling this paired nonuniform baker/sampler.

## Inverse and Stack sampling

The [inverse and Stack workflow](../guide/inverse-stack.md) uses this same grid. Inverse baking evaluates float64 equations and bounded numerical root solves. Every Stack stage runs analytically at each vertex, including all Linear matrices, with no intermediate LUT lookup.

Editing installs a 33³ preview, then refines to 65³, reusing all 35,937 preview vertices exactly and evaluating only the remaining 238,688. Output and scopes use the same installed cube. A first pending state passes input through; final rendering and normal saving require the current 65³ result. See the [nested-grid equations](../development/forward-inverse-math.md#184-runtime-and-acceptance-evidence). Small inverse residuals at vertices do not establish between-vertex accuracy.

[Download the production axes, matrices and constants](../downloads/lut-production.json).
