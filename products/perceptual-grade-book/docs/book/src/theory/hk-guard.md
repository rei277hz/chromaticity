# Bounded H–K guard

Creative lightness and chroma requests can cross into negative carried achromatic energy. The reference's signed appearance map still has a real signed \(J_A\) there. With the default `hk_guard=True`, H–K repair selects a nonnegative-energy result on the \(H\ge0\) branch by sharing the adjustment between a bounded increase in \(H\) and a reduction in \(C\), preserving hue. It runs after Adaptance and before the final common Scale inside Stage 3. Negative \(H\) takes the signed bypass; the explicit `hk_guard=False` diagnostic mode skips repair.

## Set the energy knee

Keep the Stage-2 carried energy \(E_2\) as the per-pixel reference. For a finite request with \(H\ge0\), define squared lightness \(X\), squared deficit \(D\), and clamped reference energy \(E_0\):

$$
X=H^2,\qquad D=X-66C,\qquad E_0=\max(E_2,0),
\qquad\delta=\frac{E_0X}{E_0+X}.
$$

The signed requested energy \(E_{\mathrm{req}}=J_A\lvert J_A\rvert\) is authoritative. On the negative branch it differs from \(D\). The implementation avoids subtracting rounded \(H^2\) and \(66C\) by evaluating

$$
B=\sqrt{66C},\qquad u=\frac{E_{\mathrm{req}}}{\sqrt{\lvert E_{\mathrm{req}}\rvert+66C}+B},\qquad
D=\begin{cases}E_{\mathrm{req}},&E_{\mathrm{req}}\ge0,\\ E_{\mathrm{req}}+2u^2,&E_{\mathrm{req}}<0.\end{cases}
$$

Use \(u=0\) when its denominator is zero. The harmonic expression for \(\delta\) uses min/max normalization to avoid a large product and is zero when either \(E_0=0\) or \(X=0\), including the joint zero case. Its coefficient is the fixed internal constant 1.0, independent of image statistics.

For \(D\ge\delta\), retain the request and set \(E_g=E_{\mathrm{req}}\). Below a positive knee, use the repaired energy

$$
t=\frac{\delta-D}{\delta},\qquad
E_g=\frac{\delta}{(1+4t+10t^2)^{1/4}}.
$$

This branch matches value, slope and second derivative at \(D=\delta\). The implementation uses \(v=1/(1+t)\) for bounded intermediate values. At \(\delta=0\), the limit is \(E_g=\max(D,0)\). Thus \(H\ge0\) and \(E_0\ge0\) guarantee \(E_g\ge0\); \(H>0\) and \(E_0>0\) give \(E_g>0\), regardless of the signed raw deficit.

![Guard energy and nonnegative-energy boundary](../assets/figures/guard-energy.svg)

<p class="figure-caption">With positive requested \(H\) and reference energy, the knee keeps repaired energy strictly positive, above \(H^2=66C\). Zero-reference and zero-lightness cases can lie on the boundary.</p>

## Share the repair

Let \(Z\) be the energy deficit and \(L\) the maximum squared-lightness lift. Allocate a smooth, bounded amount \(G\) to \(H\):

$$
Z=\max(E_g-D,0),\qquad L=(1.2^2-1)X=0.44X,
\qquad G=\frac{LZ}{\sqrt{4L^2+Z^2}}.
$$

Then recover the output pair:

$$
H_g=\sqrt{X+G},\qquad
C_g=\frac{X+G-E_g}{66},\qquad
(a_g,b_g)=\frac{C_g}{C}(a,b).
$$

Explicit zero branches handle black and \(C=0\). Rounding protection bounds \(C_g\) between zero and requested \(C\). On the repair branch, \(H\le H_g\le1.2H\) and \(0\le C_g\le C\). These are bounds on repair alone; the later Scale can increase both coordinates. At \(H=50,\ C=80\) with positive-branch reference \(H=50,\ C=20\), the repaired output is approximately \(H=58.188,\ C=48.142\).

![Sharing repair between H and C](../assets/figures/guard-boundary.svg)

<p class="figure-caption">At requested \(H=50\), stronger chroma requests gradually use the bounded lift and more chroma reduction. The lift approaches the fixed 20% relative cap.</p>

## Carry energy through Scale and decoding

The reference next applies the common positive Scale: \((a_g,b_g,E_g)\mapsto(\lambda a_g,\lambda b_g,\lambda^2E_g)\). The decoder receives this scaled energy directly. Reconstructing it from rounded appearance coordinates could erase a small positive achromatic component. The [Color chapter](color.md#saturation-pad-and-scale) explains why the compact saturation pad stays fixed under this Scale.

Requests above the knee retain their coordinates and energy. Negative requested \(H\) bypasses H–K repair and retains the signed state; the nonnegative-energy guarantee does not cover this branch. Nonfinite inputs are rejected. The signed decoder accepts finite signed energy when its cone responses satisfy \(\lvert r\rvert<400\); positivity is a repair/export policy, not a prerequisite for the signed inverse itself.

[HKCubeLuminance.lean](https://github.com/rei277hz/chromaticity/blob/main/libraries/perceptual-grade-reference/proofs/PerceptualGrade/HKCubeLuminance.lean) proves nonnegative repaired energy and \(J_A\), the strict versions under \(H>0,E_0>0\), and the identity \(H_g^2-66C_g=E_g\). [WarpRepairedScale.lean](https://github.com/rei277hz/chromaticity/blob/main/libraries/perceptual-grade-reference/proofs/PerceptualGrade/WarpRepairedScale.lean) proves that positive Scale preserves these signs. Zero reference energy cannot support a universal strict-positivity claim: the proved counterexample \(H=1,C=1,E_0=0\) repairs to zero energy and exports to black.

The reference order is implemented in `libraries/perceptual-grade-reference/src/grading.py`; its signed map is in `src/responses.py`, and the repair formula is shared from `libraries/perceptual-grade-core/src/perceptual_grade_core/model/hk_guard.py`. The frozen Blender product retains Scale-before-repair behavior. Historical DCTL and native-node comparisons below are separate evidence for their recorded implementations.

## Project into the export cube

H–K repair does not guarantee RGB cube containment. The reference applies a separate cube guard at export:

1. Stage 3 supplies the repaired appearance after the final common Scale; export does not apply H–K repair again.
2. For carried energy \(E\le0\), cube export returns black. For \(E\ge W^2\), where \(W\) is the cube-white \(J_A\), it returns the neutral cube-white endpoint, RGB \((1024,1024,1024)\).
3. For \(0<E<W^2\), accept the direct decode if it is finite and inside the native AP1 cube. Otherwise search along the fixed-\(J_A\), fixed-hue ray for the greatest accepted chroma. The search brackets the radius from the eight cube vertices in cone coordinates, uses fitted capacity only as a seed, and bisects while checking each trial through the actual decoder. A trial with \(\lvert r\rvert\ge400\) is rejected. Accepted RGB is saved only when finite and inside \([0,1024]^3\).

Only the interior radial branch holds \(J_A\) and hue fixed while reducing chroma; the black and white endpoint branches have different behavior. Cube projection is lossy: different appearance requests can export to the same RGB. It does not inherit the standalone guard's one-to-one result, which requires fixed positive reference energy and positive requested \(H\).

Appearance Stack handoffs carry each stage's post-policy signed state after Scale, while deferring cube projection until export. With the default guard enabled, nonnegative-\(H\) requests are repaired and negative-\(H\) requests bypass repair; Scale multiplies either carried energy by \(\lambda^2\), preserving its sign. The inverse must evaluate this complete forward order, including the selected export policy.

The ideal cube composition theorem `hk_cube_guard_positive_luminance` in `HKCubeLuminance.lean` proves positive output luminance under \(H>0\), \(E_0>0\), and cube-white \(W>0\), plus explicit assumptions: legal nonnegative output RGB, exact local decode/energy-encoding consistency, zero energy at RGB black, and positive luminance weights. The theorem includes its positive white endpoint. These exact-real results do not certify fitted capacity or floating-point containment; the executable reference checks accepted RGB through its decoder.

This chapter describes the reference's \([0,1024]\) AP1 cube. Historical release domains and LUT sampling studies retain their own stated parameters.

## Historical evaluation

This archived study concerns the earlier retain-C guard and its original LUT encoding. The measurements and fixture comparisons below document that experiment; they do not validate the current reference's repair-before-Scale order. The sampled EXR probes and PQ PNG remain as historical evidence. Current evaluation and sampling contracts are described in [Direct and sampled evaluation](lut.md).

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
