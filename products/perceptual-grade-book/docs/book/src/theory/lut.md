# Direct and sampled evaluation

The DCTL is the analytic reference. Direct uses native Blender nodes and tonal curve tables; Baked LUT uses a \(65^3\) color table. This chapter describes the extension's rendering approximations.

## Choose the input sample grid

The production cube uses **native linear ACEScg / ACES white**, independent of Blender's scene working space and each Grade's chosen white. Each component covers **0…1024**, with **64 positive intervals** and no negative sample branch. The bound is the same one the export cube guard enforces, so the table and the guard share a domain.

Let \(k=0.01\), \(R=1024\) and \(A=\ln(1+R/k)\approx11.536652\). For a nonnegative channel \(x\), the address shaper and inverse are

$$
S(x)=\frac{\ln(1+x/k)}{A},\qquad
S^{-1}(u)=k[\exp(Au)-1].
$$

Final vertices are \(x_i=S^{-1}(i/64)\), \(0\le i\le64\), with exact zero and upper endpoints. The 33-point preview takes every second vertex, giving 32 positive intervals in the same domain. This is plain log1p; the experimental warp exponent 0.9 is not used.

The bound is not a display range. Only addresses are clamped, and a different bound changes them throughout: at \(R=128\) the halfway address lands near \(1.121\), at \(R=1024\) near \(3.190\), and every intermediate vertex moves with it. Text or tooling carried over from the earlier \(0…128\) grid describes a different table, not a different naming of this one.

**No negative sample branch does not mean clipping RGB.** Only addresses and interpolation fractions are bounded; the sampled value itself is never clipped. Inputs outside the grid's cells hold the nearest edge cell's value along that axis — constant extension, not linear extrapolation, because the fraction is clamped to \([0,1]\). Stored outputs may still be signed or exceed the bound, and a negative input can therefore produce a different result from a table with a negative branch.

This is one place where implementations differ and prose has been wrong before. The shared sampler and the Blender graph clamp the fraction, which is the behaviour described here. The book's own legacy generator and the next-blender kernel leave it unclamped, so they extrapolate the edge cell linearly. Neither behaviour is wrong in isolation; they disagree outside the grid, and a comparison across them inside the grid still agrees. The reference's own README states the clamp explicitly.

![Native AP1 input samples](../assets/figures/lut-input-grid.png)

<p class="figure-caption">The ACEScg grid covers 0…1024. All intervals are positive; the zoom shows density close to zero.</p>

At 203 reference nits, neutral \(\mathrm{RGB}=1024\) corresponds to 207,872 nits. Peak Anchor remains an independent tonal target. Ordinary Grades keep Stage 1 as an exact matrix before the cube. Grade Stacks include every stage inside one cube.

## Preserve the grading function when changing the sampling basis

Canonical Grade coordinates still use Rec.709 primaries interpreted through the selected Grade white. They do not become AP1 primaries. Let \(f\) be the canonical analytic function, \(P_0\) the Rec.709/D65 RGB-to-XYZ matrix, \(P_{\mathrm L}\) the native AP1/ACES-white RGB-to-XYZ matrix, and \(C_{0\to\mathrm L}\) Bradford adaptation from D65 to ACES white. Define

$$
B_{\mathrm L}=P_{\mathrm L}^{-1}C_{0\to\mathrm L}P_0,\qquad
f_b(z)=B_{\mathrm L}f(B_{\mathrm L}^{-1}z).
$$

Surrounding matrices convert the scene to and from fixed LUT coordinates. Ordinary Grades compose Stage 1 into the input matrix. Direct retains its canonical matrices, keeping the preview correct during baking. Stacks include every Grade matrix and white connection in the analytic function before sampling. The [full specification](../development/forward-inverse-math.md#195-lut-boundaries-and-mixed-white-stacks) gives the complete equations.

Switching Blender's working space updates matrices and reuses the cube. Changing a Grade white changes the function and triggers a rebake. No conversion clips negative RGB. ACES white at the LUT boundary is a sampling choice, not a change to the default D65 Grade white or a display assumption.

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

These are photographic study measurements, not universal bounds. The adopted candidate improves all ten encoded-RGB objective terms too, with worst ratio 0.842753, but rare outliers remain. The stock Rec.2020/D65 → native AP1 matrix is nonnegative and maps the scene domain below the current bound, so the grid contains both requested metric domains without negative vertices. Signed colors outside those domains still need extrapolation. The study records complete distributions, limits and Buck2 reproduction commands.

Note that the study's conclusion is about the shaper and the space, not about the bound. Raising the bound from what that study tested to \(1024\) leaves the shaper unchanged and moves every vertex; the error figures above were not recomputed for the wider domain, and they should not be quoted as though they had been.

## Interpolate physical linear RGB

For each channel, locate the cell with a bounded address, then calculate the fraction from the original input:

$$
i=\operatorname{clamp}\!\left(\left\lfloor64S(\operatorname{clamp}(x,0,1024))\right\rfloor,0,63\right),\qquad
f=\frac{x-x_i}{x_{i+1}-x_i}.
$$

Sort fractions \(f_1\ge f_2\ge f_3\). The tetrahedron vertices \(v_0,v_1,v_2,v_3\) follow that channel order from the low to high corner. Barycentric weights are \((1-f_1,f_1-f_2,f_2-f_3,f_3)\). The implementation uses their equivalent difference form:

$$
v=v_0+f_1(v_1-v_0)+f_2(v_2-v_1)+f_3(v_3-v_2).
$$

This form avoids cancelling a constant offset when the fractions are large, and it reproduces affine transforms in exact arithmetic. Native graphs use fused multiply-adds and select the middle fraction with min/max comparisons. Interpolation joins continuously across cell boundaries.

Because both the address and the fraction are bounded, an input outside the grid resolves to the nearest edge cell rather than being extrapolated. Its error there is therefore the edge cell's own approximation error plus float32 vertex and arithmetic roundoff, not a growing extrapolation term. Far-negative inputs still amplify roundoff when they reach that edge cell, since the first cell is small, but the error does not scale with distance from the grid the way linear extrapolation would.

![Shaping and physical-cell interpolation](../assets/figures/lut-interpolation.png)

Shader lookup stores raw float RGB. Compositor lookup stores the base RGB and three forward-axis differences in four planes of one image. Each coefficient has signed mantissas and its own shared power-of-two exponent. Four reads select one base and three ordered edges, avoiding subtraction of quantized neighboring vertices; the atlas uses four times the raw vertex storage. [Runtime architecture](../development/architecture.md#cross-compositor-storage-boundaries-safely) explains float32 computation and half-float image boundaries. Automatic precision remains a host setting.

## Curve tables and current-grade publication

Tables are not shared across implementations, and they are not the same size even within one. Treating any single count as "the table resolution" has been the source of repeated documentation errors, so each is listed per profile:

| Profile | Stage 2 (Tone) | Stage 3 (Color) | Boundary |
| --- | --- | --- | --- |
| Analytic reference, DCTL | closed form, no table | closed form, no table | DCTL emits compact cubic spline constants |
| Shipped 1.23.2 Blender, inverse bake | adaptive table, cap 2048 cells | analytic | 257 × 257 uint16 per face |
| Next native runtime | fixed 256 cells, \(512\times1\) RGBA32F | four fixed fields | \(321\times513\) float32 root seed |

**The analytic model has no curve table in either stage.** The reference evaluates `coefficient_weights` and the tone kernel directly at every pixel: the sigmoid-window integral is closed form, so Stage 2 needs no tabulation, and the coefficient curves of Stage 3 are computed from the same kernel rather than looked up. This is the model the rest of this part describes.

**The Stage-2 tone table exists only for inverse baking, and it is the adaptive one.** In the shipped 1.23.2 build the inverse bake builds a scalar inverse-tone table whose cells are added by bisection until each cell's five-fraction probe error is within half the accuracy tolerance and a Bernstein monotonicity test passes. `MAX_CELLS = 2048`, 32 refinement rounds, 80 root evaluations and a 64 KiB budget bound that refinement; 2048 is an abort condition, not a stored size, and a typical grade needs a few dozen cells. Above its tail threshold the table is not consulted at all — the linear asymptote is evaluated analytically.

**The native runtime fixes its resolutions instead.** It builds a 256-cell tone field packed into a \(512\times1\) RGBA32F image, and four Stage-3 fields of 8192 (lightness and chroma coefficients), 4096 (web parameters), 1536 (web toes) and 3072 (Adaptance parameters) cells. Those are fixed, not refined per grade, and a build that misses the scalar accuracy gate fails rather than silently falling back to a different resolution.

**The chroma classifier has no table in any profile.** The p=2 low/high split is evaluated from the carried achromatic lightness and the current chroma at every pixel. An earlier design sampled a chroma threshold; that row is gone.

**Boundary representation differs by implementation, and no two agree.** The shipped Blender build and the shared CPU kernels sample a 257 × 257 uint16 face atlas, bilinear-coded then affine-decoded, backed by compact cubic B-spline edge and sector coefficients. The DCTL skips the face grid entirely and ships those compact spline constants as `__CONSTANT__` arrays within a 64 KiB budget. The next native runtime uses a \(321\times513\) float32 seed grid followed by exactly one safeguarded Halley step from the actual decoder. A statement about "the boundary table" without naming the implementation is meaningless.

Shared endpoint value, first derivative and second derivative define the quintic interpolant wherever a tone or coefficient curve is tabulated, preserving \(C^2\) joins at every knot. DCTL curves remain analytic throughout.

A bake uses the analytic model and publishes only for its current parameter signature. Ordinary Grades preview current Direct values while baking; final render preparation finishes the selected table. Sampler agreement and analytic approximation error are separate checks. A uniform `.cube` reader would require resampling this paired nonuniform baker/sampler.

## Inverse and Stack sampling

The [inverse and Stack workflow](../guide/inverse-stack.md) uses this same grid. Inverse baking evaluates float64 equations and bounded numerical root solves. Every Stack stage runs analytically at each vertex, including all Linear matrices, with no intermediate LUT lookup.

Editing installs a 33³ preview, then refines to 65³, reusing all 35,937 preview vertices exactly and evaluating only the remaining 238,688. Output and scopes use the same installed cube. A first pending state passes input through; final rendering and normal saving require the current 65³ result. See the [nested-grid equations](../development/forward-inverse-math.md#184-runtime-and-acceptance-evidence). Small inverse residuals at vertices do not establish between-vertex accuracy.

[Download the production axes, matrices and constants](../downloads/lut-production.json). The file records the earlier \(0…128\) axis and is retained as an archive; it is not regenerated, and its `axis_65` does not describe the \(1024\) bound above.
