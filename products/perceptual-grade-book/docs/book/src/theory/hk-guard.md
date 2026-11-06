# Bounded H–K guard

Creative lightness and chroma requests can reach \(H^2<66C\), where a real achromatic lightness cannot be recovered. The guard shares that repair between a bounded increase in \(H\) and a reduction in \(C\) while preserving hue.

## Set the energy knee

Keep the Stage-2 point as the per-pixel reference. Define requested squared lightness \(X\), requested achromatic energy \(D\), and reference energy \(E_0\):

$$
X=H^2,\qquad D=X-66C,\qquad E_0=\max(H_2^2-66C_2,0),
\qquad\delta=\frac{E_0X}{E_0+X}.
$$

The harmonic expression is evaluated with min/max normalization to avoid a large product. \(\delta\) is zero when both energies vanish. Its coefficient is the fixed internal constant 1.0, independent of image statistics.

For \(D\ge\delta\), retain the request. Below the knee, use a positive energy floor:

$$
t=\frac{\delta-D}{\delta},\qquad
E=\frac{\delta}{(1+4t+10t^2)^{1/4}}.
$$

The \(E\) branch matches value, slope and second derivative at \(D=\delta\). The implementation uses \(v=1/(1+t)\) for bounded intermediate values. The zero-delta branch uses the corresponding nonnegative-energy limit.

![Guard energy and real-domain boundary](../assets/figures/guard-energy.png)

<p class="figure-caption">The knee transitions to a positive achromatic energy. Repaired points remain above \(H^2=66C\), so the inverse has a real \(J_A\).</p>

## Share the repair

Let \(Z\) be the energy deficit and \(L\) the maximum squared-lightness lift. Allocate a smooth, bounded amount \(G\) to \(H\):

$$
Z=\max(E-D,0),\qquad L=(1.2^2-1)X=0.44X,
\qquad G=\frac{LZ}{\sqrt{4L^2+Z^2}}.
$$

Then recover the output pair:

$$
H_{\mathrm{out}}=\sqrt{X+G},\qquad
C_{\mathrm{out}}=\frac{X+G-E}{66},\qquad
\mathbf u_{\mathrm{out}}=\frac{C_{\mathrm{out}}}{C}\mathbf u.
$$

Explicit zero branches handle black and \(C=0\). Rounding protection bounds \(C_{\mathrm{out}}\) between zero and requested \(C\). Eligible outputs satisfy \(H\le H_{\mathrm{out}}\le1.2H\) and \(0\le C_{\mathrm{out}}\le C\). At \(H=50,\ C=80\) with reference \(H=50,\ C=20\), the output is approximately \(H=58.188,\ C=48.142\).

![Sharing repair between H and C](../assets/figures/guard-boundary.png)

<p class="figure-caption">At requested \(H=50\), stronger chroma requests gradually use the bounded lift and more chroma reduction. The lift approaches the fixed 20% relative cap.</p>

## Carry energy into decoding

The decoder receives \(E\) directly. Reconstructing it from rounded \(H_{\mathrm{out}}^2-66C_{\mathrm{out}}\) could erase a small positive achromatic component. The DCTL, analytic Python model and native nodes preserve this energy path. Exact reset, neutrals and unchanged requests retain their bypass behavior. Negative requested \(H\), nonfinite values and cone-response poles follow the necessary inverse-domain policy.

This guard addresses the model’s real-energy boundary. Output gamut and tone rendering remain downstream. A LUT samples the complete guarded transform; interpolated RGB has its own finite-grid error. The [fixture comparisons](#rebuilt-fixture-comparisons) illustrate both issues separately.

Implementation sources are `libraries/perceptual-grade-reference/src/responses.py` for the signed H–K map and carried energy, `libraries/perceptual-grade-core/src/perceptual_grade_core/model/hk_guard.py` for the guard itself, and the product graphs at `products/perceptual-grade-blender/src/graph/` and `products/perceptual-grade-dctl/src/core.dctlh`. Tests cover independent high-precision calculations, float DCTL parity, native expressions, signed inputs and the sampled EXR/PQ fixtures through [Buck2](../development/building.md#run-tests).

## Project into the export cube

H–K repair leaves a valid appearance pair, not displayable RGB. The reference applies a second, separate guard at export, and the two must not be conflated:

1. H–K repair, with the post-Tone reference energy, produces \((H_g,a_g,b_g)\) and carries \(E\).
2. The decoder runs on that pair. Any point whose cone response approaches the \(\lvert r\rvert=400\) pole is rejected rather than clamped.
3. A cube guard searches for the largest chroma at the repaired \(J_A\) and hue that decodes inside the native AP1 cube. It brackets the radius from the eight cube vertices in cone coordinates, seeds the search with the fitted capacity at that lightness and hue, and then bisects, validating every trial through the actual decoder. The capacity seed is only a starting guess; it never decides the result. Accepted RGB is saved only when it is finite and inside \([0,1024]^3\).

The cube guard therefore holds \(J_A\) and hue fixed while reducing chroma, which is a different policy from the H–K guard's bounded lightness lift. It is a projection, not an inverse: two different appearance requests can export to the same RGB, and the projection is lossy by construction. Only the H–K guard participates in the fixed-reference invertibility argument above; the cube guard's output does not inherit it.

The graded intermediate is never forced through the cube guard before export. Grading operates on raw signed appearance coordinates and the guard runs at the boundary, so a Stack can carry one appearance value through several stages and project once at the end. Export-only repair also means an inverse cannot assume the forward path already projected.

The earlier 1.23.2 release applies an equivalent export guard over its own cube domain. Comparisons across releases must state the bound: this part describes the reference's \([0,1024]\) AP1 domain, while the 1.23.2 sampling grid is documented in the archived LUT study.

## Historical evaluation

This archived study concerns the earlier retain-C guard and its original LUT encoding. The current implementations use the [bounded shared guard](hk-guard.md) and [asymmetric input grid with linear-RGB interpolation](lut.md). The measurements below document that earlier experiment. Current regression fixtures and acceptance results are described under [validation](../development/building.md). The package retains sampled EXR probes and the PQ PNG. The current Buck2 build uses those fixtures to create the comparisons below.

### Recorded experiment: 1.4.0

Selected coefficient: \(k=1.0\), fixed inside both implementations. The Color-stage guard preserves the requested chroma and hue and smoothly lifts H–K lightness near its real-domain boundary. The DCTL and the extension’s native-node calculations agree closely. A \(65^3\) LUT remains a material approximation under strong grading, even with this smoother guard.

### Calculation

Use actual modCAM16 chroma, \(C=\sqrt{a^2+b^2}\), and \(H=J_{\mathrm{HK}}\), with \(H^2=J_A^2+66C\). The default reference/adapting luminances remain 203/20.3 nits. \(H=100\) identifies a reference-white neutral; HDR \(H\) continues above 100.

Keep the Tone-stage output \((H_2,a_2,b_2)\) as the reference for the Color-stage request \((H,a,b)\). Define:

$$
E_0=\max(H_2^2-66C_2,0),\quad D=H^2-66C,\qquad
\delta=k\frac{E_0H^2}{E_0+H^2}.
$$

$$
E=\begin{cases}
D,&D\ge\delta,\\[2pt]
\displaystyle\frac{\delta}{1+t+t^2},\quad t=\frac{\delta-D}{\delta},&D<\delta.
\end{cases}
\qquad H_{\rm safe}=\sqrt{66C+E}.
$$

The inverse receives \(J_A=\sqrt E\) and the original \((a,b)\). For positive \(\delta\), the branches meet with matching value, slope and curvature. The smooth knee starts within the valid domain, providing a gradual approach to the boundary. With \(\delta=0\), the limit is \(E=\max(D,0)\).

At reset, \(D=E_0\) and \(\delta\le E_0\) for \(0<k\le1\), so the request is retained exactly. For neutrals, \(D=H^2\ge\delta\). The harmonic expression for \(\delta\) avoids multiplying two large squared-lightness values. The rational branch uses the bounded variable \(v=1/(1+t)\), evaluating \(E=\delta v^2/(1-v+v^2)\).

Precision matters: the decoder carries \(E\) directly. Reconstructing it from rounded \(H_{\mathrm{safe}}^2-66C\) can lose the entire small achromatic component in float32. This direct energy path is shared by the analytic DCTL, Python baking/scopes, and native nodes. Signed RGB uses paired references for the main signal and its neutral cone offset.

The coefficient is a global engineering choice. \(\delta\) varies deterministically with the point’s coordinates, like every other color transform term. Image statistics, neighboring pixels, exposure metadata and scope selection have no influence on \(k\). The production UI and saved grading parameters contain no coefficient control.

For example, take the incoming point \(H_2=50,\ C_2=20\) and request \(H=50\):

| Requested \(C\) | Previous output \(C\) | New output \(C\) | New output \(H\) |
|------------:|------------------:|-------------:|-------------:|
|          20 |             20.00 |           20 |        50.00 |
|          30 |             30.00 |           30 |        50.24 |
|          40 |             37.88 |           40 |        53.53 |
|          80 |             37.88 |           80 |        72.88 |
|         160 |             37.88 |          160 |       102.79 |

The guard keeps these high-chroma requests distinct. Negative requested \(H\), nonfinite values and the inverse cone response’s finite domain retain their existing paired fallback. Output tone and gamut mapping remain downstream.

### Photographs and procedure

The four supplied half-float EXRs identify Rec.2020/D65 chromaticities. Values were interpreted as linear RGB with reference white 1.0 = 203 neutral nits. Their signed channels were preserved.

| Source   |  Dimensions | RGB minimum / maximum | Negative channels |
|----------|------------:|----------------------:|------------------:|
| IMG_0436 | 4032 × 3024 |    −0.01275 / 1.02344 |            0.929% |
| IMG_0441 | 4032 × 3024 |    −0.00450 / 1.00488 |            0.605% |
| IMG_0446 | 4032 × 3024 |    −0.00243 / 0.87695 |            0.658% |
| IMG_0472 | 3024 × 4032 |    −1.75488 / 4.92578 |            2.258% |

Fixtures retain every twelfth row and column, respecting each EXR’s data window. The original images’ hashes and the sampling method are recorded in `tests/blender/fixtures/hk-real-world/metadata.json`. Every candidate receives identical input pixels and slider settings.

The Practical grade combines Global C Gain at +0.35 stops with Midtones Cₗ → J at −4, White Cₕ → J at +6, and small Adaptance and Hue changes. Chroma ×8 uses Global C Gain at +3 stops. Darken + chroma combines Midtones \(a\) → J at −15 and White b → J at −20 with Global C Gain at +2 stops.

Tonal chroma combines Midtones Cₗ → C at +2, White Cₕ → C at +3, signed a/b contributions and Global C Gain at +0.5. Strong Adaptance uses \(a=[30,-50,60,-80]\), \(b=[-30,50,60,80]\) and strength 0.75. Remap + color places input Midtones, White and Highlights at 50, 350 and 1500 nits, adds +1.5 stops of global chroma gain and applies tonal J/C changes.

The maximum-control stress grade sets all four Cₕ → C values to +16 stops and Global C Gain to +3, requesting up to 524,288 times the input chroma. Other settings remain at defaults.

The JSON reports contain every parameter, including the settings abbreviated above. The broad sweep used 254,016 pixels per candidate: all four photographs sampled every 24 pixels, at 0/+2/+4 exposure stops, in ACEScg and Linear Rec.2020. It compared the previous cap and \(k\)=0.05/0.1/0.2/0.4/0.75/1.0: 98 grade/space/ coefficient comparisons. ACEScg conversion in this numerical sweep uses XYZ and CAT16 D65→ACES adaptation explicitly.

The display study separately used Blender’s own OCIO input conversion and ACES 2.0 HDR 1000-nit view on Rec.2100-PQ. It used 75,264 pixels per candidate, 0/+2 stops, and \(k\in\{0.1,0.4,0.75,1.0\}\) plus the old cap. Display errors are \(\Delta E_{\mathrm{ITP}}\) between the resulting display RGB values. These exposure brackets exercise the supplied HDR photograph through approximately the intended 1000/4000-nit range; peak RGB component values are not luminance measurements.

### Coefficient choice and interpolation errors

The \(65^3\) cube retains its signed-asinh input/output shaper, ±64 input-component domain, tetrahedral interpolation and outer-cell extrapolation. Each LUT is compared with its own analytic model, so the table measures interpolation accuracy separately from the intended appearance change between old and new guards.

Define relative RGB error per pixel as \(\frac{\lVert\mathbf{RGB}_{\mathrm{LUT}}-\mathbf{RGB}_{\mathrm{analytic}}\rVert_\infty}{\max(0.01,\lVert\mathbf{RGB}_{\mathrm{analytic}}\rVert_\infty)}\). P99 is the error below which 99% of the sampled pixels fall. \(\Delta E_{\mathrm{ITP}}\) is a display-space distance, not a percentage.

| Grade            | Old RGB error P99 | \(k=1\) RGB error P99 | Old \(\Delta E_{\mathrm{ITP}}\) P99 | \(k=1\) \(\Delta E_{\mathrm{ITP}}\) P99 |
|------------------|------------------:|------------------:|---------------:|---------------:|
| Practical        |             8.21% |         7.69% |           9.74 |       6.84 |
| Chroma ×8        |            85.93% |        77.96% |      89.06 |         102.06 |
| Darken + chroma  |            96.25% |        54.82% |          86.39 |      80.59 |
| Tonal chroma     |            89.57% |        60.99% |         112.87 |      88.65 |
| Strong adaptance |            69.76% |        38.71% |          45.98 |      44.76 |
| Remap + color    |            74.65% |        53.43% |          63.08 |      47.42 |

Coefficient 1.0 achieved the lowest relative-RGB P99 among the tested candidates in all six display-study grades, and the lowest display P99 in five. The Chroma ×8 display result favored a smaller knee and the previous cap. Across the six grades, the equal-weight mean of their display P99 values was 67.85 for the old cap, 67.09 for \(k=0.1\), 63.00 for \(k=0.4\), 61.89 for \(k=0.75\) and 61.72 for \(k=1.0\). This supports 1.0 as a tested compromise, together with its exact-reset guarantee, rather than a universal perceptual optimum.

Strong grades still show visible LUT differences. The smoother H–K guard improves interpolation in most tested cases, while the inverse appearance transform, signed extension and shaped RGB coordinates can still vary rapidly within a cube cell. A single coefficient cannot provide an overall accuracy bound for that approximation.

The +4-stop stress bracket also drives some input components outside ±64; edge extrapolation can produce extremely large errors there. Those maxima are reported separately in the per-image/exposure JSON. The maximum-control grade hits the remaining inverse response-domain guard for 236,390 of 254,016 pixels in each working space; mixing valid and fallback vertices gives very poor LUT results. The six representative grades had zero analytic inverse fallbacks in the broad sweep. These are separate limits from the H–K real-domain repair.

### Rebuilt fixture comparisons

The following sheets are generated anew from today’s model. They compare the source, the historical retain-C formula embedded in the current surrounding pipeline, the current bounded guard, and the current \(65^3\) LUT. They isolate the guard change; the historical numerical tables above remain recorded results from their original experiment.

![Practical grade across five fixtures](../assets/figures/photo-practical.png)

<p class="figure-caption">Four point-sampled EXRs and one decoded P3-D65/PQ image. Every column uses the same Blender ACES 2.0 / sRGB view.</p>

![Strong chroma gain across five fixtures](../assets/figures/photo-chroma-8x.png)

<p class="figure-caption">Global \(C\) Gain = +3 stops stresses the guard and finite LUT sampling.</p>

![Directional darkening with chroma gain](../assets/figures/photo-dark-chroma.png)

<p class="figure-caption">Midtones \(a\) → J = −15, White \(b\) → J = −20 and Global \(C\) Gain = +2 stops. The calculation uses Linear Rec.709 working RGB throughout.</p>

[Current comparison metrics](../downloads/photo-metrics.json) record all 15 grade/fixture pairs. [Grade definitions](../downloads/photo-grades.json) contain the complete deviations from current defaults.

The rebuilt columns show source, historical retain-C formula, current analytic result, and current \(65^3\) LUT result. Every column uses the same Blender ACES 2.0 sRGB view. The point-sampled photographs retain their original aspect ratios. These SDR figures complement the HDR display-space measurements above.

The large-gain examples show how sharing the repair changes lightness and chroma. Differences between the two rightmost columns reveal the remaining LUT approximation, including changes to the red-lit subject and HDR foliage.

### Implementation checks and performance

| Check                                         | Measured result                                                                              |
|-----------------------------------------------|----------------------------------------------------------------------------------------------|
| H–K invariants                                | 16 checks; 12,000 numerical samples; 700 independent 70-digit Decimal cases                  |
| DCTL vs Python, supplied-photo probes         | 10,476 samples; max relative RGB difference 0.0024%                                          |
| DCTL vs Python, signed/HDR control sweep      | 34,344 cases; max relative XYZ difference 0.173%                                             |
| Native Color-stage rendering vs DCTL          | CPU Compositor/Cycles passed; compositor maximum relative error 0.0149%                      |
| Native LUT sampler vs CPU tetrahedral sampler | Maximum relative difference 0.000338%                                                        |
| Full extension graph in Blender                            | 1,256 compositor node instances; 792 reachable in responsive path, 170 in LUT path           |
| Native-test cold bake                         | 1.48 s on this test host                                                                     |
| Numerical cached rebake                       | 0.45 s in the seeded cube test; approximately 0.13–0.23 s for coefficient-only cached sweeps |

Implementation agreement and LUT approximation are different measurements. The sampler accurately evaluates the baked cube, while a cube can still differ substantially from the analytic transform between its vertices.

The complete DCTL, parity, extension numerical/UI and CPU render suites passed. Resolve Metal/CUDA compilation and interactive GPU performance require a workstation run. Clang was unavailable here, so the provided OpenCL syntax check was skipped; C++ float compilation and static portability checks passed.

### Current reproducible inputs

Sampled EXR probes and source metadata live in `tests/blender/fixtures/hk-real-world/`; the original PQ PNG and its metadata are in `tests/blender/fixtures/hk-pq/`. The selected shared-guard numerical reference is in `tests/blender/fixtures/hk-bounded/`, and frozen independent LUT comparisons are in `tests/blender/fixtures/lut-asymmetric/`.

Run current fixture targets through [Buck2](../development/building.md). Running an exploratory script against today’s model evaluates today’s equations; it does not recreate an older release’s results. Generated comparison sheets and their metrics are included in the deployment. Temporary test report directories remain isolated build outputs.
