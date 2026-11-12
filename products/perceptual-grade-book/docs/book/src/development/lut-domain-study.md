# LUT sampling study: upper bound 128

This experiment compares LUT sampling coordinates while keeping the analytic grading function unchanged. It tests fixed Rec.2020/D65, native ACEScg/ACES white with a nonnegative axis, and AP1 primaries normalized to D65 with a signed axis. The experiment is separate from the current production sampling policy.

## Eligibility and error

Let \(\mathbf q\) be the exact color entering the LUT, expressed in canonical Linear Rec.709/D65. For an ordinary forward Grade this is **after Stage 1**. For an inverse-roundtrip test it is the forward Grade result. For a Stack it is the input of the complete Stack, whose Stage 1 matrices are included in the bake.

Let \(T_R\) convert canonical coordinates to Linear Rec.2020/D65, and \(T_A\) convert them to standard ACEScg/ACES white using the stock Blender/OCIO conversion. The two eligibility masks are

\[
m_R(\mathbf q)=\mathbf 1\{T_R\mathbf q\in[0,10]^3\},\qquad
m_A(\mathbf q)=\mathbf 1\{T_A\mathbf q\in[0,128]^3\}.
\]

They are **independent masks**, not their intersection. A pixel outside one domain does not contribute to that domain's metric. A pixel outside both contributes to neither. Masks use strict float64 comparisons, are determined before candidate evaluation, and do not depend on the candidate's gamut, shaper, bounds or approximate output.

Let \(F(\mathbf q)\) be the full analytic reference and \(\widehat F_g(\mathbf q)\) the result sampled with grid \(g\). The scene error, used only where \(m_R=1\), is

\[
e_R^{(g)}(\mathbf q)=
\left\|T_R\left(\widehat F_g(\mathbf q)-F(\mathbf q)\right)\right\|_\infty.
\]

The infinity norm is the largest absolute error of the three RGB channels. It does not divide by brightness or reference RGB. The reported RMS is the RMS of these per-pixel maximum-channel errors.

For each ACES 2.0 output \(v\), let \(V_v\) include rendering and the declared output encoding. For pixels with \(m_A=1\), the ranking uses

\[
e_v^{(g)}(\mathbf q)=
\left\|V_v\!\left(\widehat F_g(\mathbf q)\right)-V_v\!\left(F(\mathbf q)\right)\right\|_\infty.
\]

The four outputs are SDR 100 nits Rec.709/BT.1886, SDR 100 nits P3-D65/sRGB, HDR 1000 nits P3-D65/PQ and HDR 1000 nits Rec.2020/PQ. ACES creative white is D65. There is no additional view exposure or look. **Rendered RGB means encoded output RGB for the primary ranking.** The tables also include absolute emitted RGB in nits, emitted RGB divided by output peak nits, luminance error and ΔE_ITP.

An empty domain has a null distribution. It is not treated as zero error. Eligible pixels outside a candidate's grid are retained and extrapolated through the boundary tetrahedron; they are not discarded. `coverage.csv` records those counts separately from domain exclusions.

## Three sampling bases

Standard ACEScg uses AP1 primary chromaticities and the ACES white \((0.32168,0.33767)\). Its conversion includes stock Blender/OCIO Bradford adaptation to/from D65. This experiment's **AP1/D65** candidate keeps those AP1 primary chromaticities but recomputes their normalized primary matrix for D65 \((0.3127,0.3290)\). AP1/D65 is an experimental sampling basis, not standard ACEScg.

For primary XYZ columns \(P\) and normalized white XYZ \(\mathbf w\), the normalized primary matrix is

\[
N_{\mathbf w}=P\,\operatorname{diag}\!\left(P^{-1}\mathbf w\right).
\]

The AP1/D65 coordinate conversion is \(T_D=N_{\mathrm{AP1},D65}^{-1}N_{709,D65}\). Adapting the **entire** native AP1 basis to D65 would instead reproduce essentially the same RGB sampling coordinates as native ACEScg with Bradford conversion, so it would not be a distinct gamut experiment.

Every candidate converts its lattice vertices back to canonical coordinates, evaluates the same \(F\), then stores the result in its sampling basis. Grade working whites remain D65, ACES and D50 in the three specified Grades, independently of the LUT basis. “No negative” describes the native AP1 lattice starting at zero; input and output RGB are not clipped.

With the upper bound fixed at 128, the native AP1 source cube reaches approximately **−3.879…+131.879** in Rec.2020/D65 and **−1.167…+129.167** in fixed-primary AP1/D65. The tested signed lower bounds are therefore −4/−8 and −2/−4 respectively. Native AP1 uses zero. The two D65 bases need extrapolation for some upper source-cube corners even with properly selected lower bounds. Full matrices and channel-wise extrema are in `metadata.json`.

## Shapers and selection

The specification tests 150 grids: two production comparison grids and 148 candidates with upper bound 128. The wide sweep and local refinement are recorded in `lut-domain128-screening.json` and `lut-domain128-refinement.json`; the combined `lut-domain128.json` is the canonical Buck2 experiment. Families are asinh, log1p, a linear-to-log toe, power, and log1p with a power warp of the normalized axis. Signed grids vary lower bound, negative allocation and curve scale, including two negative intervals. Native AP1 spends all 64 intervals on the nonnegative branch. Negative allocations are even, preserving the shared zero vertex and nested 33/65 grids.

The ordinary asinh/log1p/toe signed branches match their first derivatives at zero. Power-warp variants are additional sample-placement experiments; they are not all claimed to be differentiable at zero. LUT interpolation always uses physical scene-linear RGB fractions, rather than shaper-space fractions.

Screening uses a deterministic 2,048-pixel subset per fixture. Full validation includes all 338,688 stored pixels from the four IMG fixtures at −2, 0, +2, +4 and +6 input-exposure stops: 1,693,440 pixels per workload before masking. These are the existing sampled fixture arrays, not full-resolution original EXRs. Workloads are forward Grade, inverse, inverse roundtrip, all-forward Stack and mixed forward/inverse Stack. Three fixed shared Grade definitions are stored in the spec.

For each grid and each of ten terms—scene RGB p99/RMS and encoded RGB p99/RMS in each of four views—the score first takes the worst statistic over all fixture/exposure/workload cases. It then minimizes the largest ratio to the current production −2…+64 grid. This avoids averaging away a poor case. Tie breaks use the mean ratio and then the grid name. “Best” means the best measured option in the fully validated shortlist under these declared inputs and domains, not a universal optimum.

## Recorded result

The 150-grid screen and 12 full finalists select **native ACEScg/ACES white, [0,128], 64 positive intervals, warped log1p with κ = 0.003 and power p = 0.9** under the encoded-RGB objective. For vertex index \(i\in\{0,\ldots,64\}\), its channel axis is

\[
x_i=\kappa\left[\exp\!\left(\left(\frac{i}{64}\right)^p\ln\!\left(1+\frac{128}{\kappa}\right)\right)-1\right],
\qquad \kappa=0.003,\quad p=0.9.
\]

For an in-range channel \(x\), the continuous index is

\[
s(x)=64\left[\frac{\ln(1+x/\kappa)}{\ln(1+128/\kappa)}\right]^{1/p}.
\]

The lower cell index comes from this address; interpolation fractions remain \((x-x_i)/(x_{i+1}-x_i)\) in linear RGB. The formula does not prescribe clipping outside the grid: boundary-cell interpolation is extrapolated. The 33³ preview takes every second 65³ vertex.

The stock Rec.2020/D65 → native AP1 matrix has nonnegative coefficients. Its maxima over `[0,10]³` are about 10 per channel, so this native `[0,128]³` grid contains **both requested metric domains**. No negative allocation is needed to contain these inputs. This conclusion is about the sampling grid, not a change to the Grade working white or a restriction on signed output RGB.

| Best balanced full finalist by basis | Bounds | Curve | Negative / positive intervals | Balanced ratio |
|---|---|---|---:|---:|
| Native ACEScg/ACES white | 0…128 | log1p, κ .003, warp p .9 | 0 / 64 | **0.725347** |
| AP1/D65 | −2…128 | asinh, κ .01 | 2 / 62 | 0.868271 |
| Rec.2020/D65 | −4…128 | linear-to-log toe, κ .003 | 8 / 56 | 0.875586 |
| Former production Rec.2020/D65 | −2…64 | log1p, κ .003 | 20 / 44 | 1.000000 |

| Worst per-case statistic | Former production | Selected native AP1 |
|---|---:|---:|
| Scene Rec.2020 absolute RGB p99 | 0.073063413 | 0.041688502 |
| Scene Rec.2020 absolute RGB RMS | 0.018554004 | 0.010447717 |
| SDR 100 Rec.709 encoded RGB p99 | 0.008575175 | 0.005389426 |
| SDR 100 P3-D65 encoded RGB p99 | 0.007430241 | 0.004507332 |
| HDR 1000 P3-D65 encoded RGB p99 | 0.004731874 | 0.002988917 |
| HDR 1000 Rec.2020 encoded RGB p99 | 0.003490032 | 0.002195976 |

All ten primary terms improve: scene p99/RMS decrease by approximately 42.94%/43.69%, and the four rendered p99 values by 36.83–39.34%. The smallest improvement among the ten terms is 27.47%. This is a relative comparison with the former grid under the new domains and exposure sweep, not with the older unmasked experiment's statistics.

Curve choice depends on the error objective. Among the same finalists, **plain native AP1 log1p with κ = .01** wins the display-linear RGB/peak-nits objective with ratio 0.530634. It also has lower aggregate scene and encoded p99 values, but the warped curve produces a more uniform improvement across the separately weighted encoded views, especially HDR Rec.2020 RMS. Both are reasonable candidates for adoption when those priorities differ.

The view metrics materially change the choice. Native AP1 log1p with κ = .1 achieves scene RGB p99 **0.025908**, lower than the selected 0.041689, but its worst encoded ACES p99 is **0.035947**, over six times the selected 0.005389. Minimizing scene RGB alone would therefore favor a curve with much worse rendered errors.

Rare errors remain. The selected grid's maximum HDR P3-D65 encoded error is **0.184539**, compared with 0.190931 for the former grid; its p99 is 0.002989. Maximum scene RGB error is 0.126010 versus 0.189842. The complete tables retain these outliers and their pixel coordinates. The choice optimizes p99/RMS, not maximum error.

![Full-finalist error tradeoffs](../assets/illustrations/lut-domain128-errors.svg)

![Sample placement by basis](../assets/illustrations/lut-domain128-placement.svg)

{{#include ../assets/fragments/lut-domain128-key.md}}

These book figures are redrawn as vectors from the recorded study data. The domain-128 finalist error coordinates are available in the published report to eight decimal places; two comparison axes in the placement chart are reconstructed from the documented sampling formulas. The original engineering report and its archived figures remain unchanged. [Download the chart sources and plotted data](../downloads/chart-sources.zip).

[Download the selected axes and scores](../downloads/lut-domain128-selection.json). The full source includes `docs/engineering/lut-domain128/report.md`; the separately provided result archive contains all JSON/CSV records, plots and fingerprints. Version 1.21.0 now adopts the plain native AP1 log1p κ = 0.01 candidate for its display-linear/peak-nits objective. The warped curve above remains the encoded-objective study winner, not the production curve. See [the production sampling contract](../theory/lut.md).

## Reproduce with Buck2

```sh
buck2 build //:lut_domain128_evaluation //:lut_domain128_report --show-full-output
buck2 test //:lut_domain128_math_test //:lut_domain128_smoke_test
buck2 test //:lut_domain128_full_result_test
buck2 test //:lut_domain128_confirmation_test
buck2 build '//:lut_domain128_evaluation[metrics]' \
  '//:lut_domain128_evaluation[coverage]' \
  '//:lut_domain128_evaluation[selection]' --show-full-output
```

The spec is `tests/blender/experiments/lut-domain128.json`. It declares fixture hashes, complete Grade matrices/white/Tone/Color parameters, exposures, seed, workloads, curve families/scales/variants, allocations, domains, four output transforms and the shortlist. Buck2 fingerprints the exact math sources, sampled photographic fixtures, generated translations, Python lock and complete Blender OCIO snapshot. Analysis packages do not enter the extension.

The evaluation creates JSON/CSV metrics, counts, rankings, complete per-case records, exact axes, solver diagnostics, float32 vertex hashes and a hash manifest. The report action produces Markdown and two scientific plots. Smoke checks verify the output contract and candidate-independent masks; the full-result checker independently reconstructs the selection. The math checker tests the two AP1 definitions, cube extrema, masks, zero nesting and affine interpolation/extrapolation.

An authoring preview can use the pinned analysis environment and a complete Blender OCIO snapshot:

```sh
python -m tools.experiments.lut_domain128 --tree . \
  --spec tests/blender/experiments/lut-domain128.json \
  --ocio-config /path/to/colormanagement/config.ocio --output-dir /fresh/results
python -m tools.experiments.check_domain128_result --results /fresh/results
python -m tools.experiments.report_domain128 --results /fresh/results --output-dir /fresh/report
```

Elapsed bake times are observations; input fingerprints, axes, vertices and metric values are the reproducibility contract. The authoring sandbox cannot start native Buck2 because `/proc/self/exe` is unavailable. Direct execution of declared Python actions and sparse input audits does not claim that the native Buck2 release gate passed. These measurements do not cover native GPU/Metal transport or colors excluded by the masks.

## Adopted production choice

Version **1.21.0** uses `AP1_ACES_neg0_pos128_n0_log1p0.01`: native ACEScg/ACES-white [0,128], 64 positive intervals, plain log1p κ = 0.01. Its encoded balanced ratio is 0.842753; its display-linear/peak-nits balanced ratio is 0.530634, the best among these full finalists. Scene p99/RMS are 0.038344395/0.009574135, and worst encoded view p99 is 0.004779925. These are the recorded study statistics. The production sampler is separately checked against an independent AP1/Bradford oracle and native Shader/Compositor rendering. Grade whites and the analytic grading model remain unchanged.
