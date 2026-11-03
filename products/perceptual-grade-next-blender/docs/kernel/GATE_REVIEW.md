# Grading-stage gates and end-to-end error

## Current schema-5 layout and absolute HDR error — 2026-10-30

**Implementation and absolute HDR reassessment are complete.** The native
runtime now uses Tone **256**, Color coefficients **8,192** and Compact
Adaptance **3,072** cells together, with Web parameters **4,096**, Web toes
**1,536** and the fixed **513 × 321** output boundary. Tone Fit accepts
**[-2, 2]**; the separate Color fits retain **[-2, 6]**. The current corpus
replaces Tone fit-3 stress settings with fit 2 and excludes the fit-3 endpoint
case; historical fit-3 receipts remain historical. Layout schema **5** requires
rebuilding obsolete persistent trees and rejects obsolete Tone/Color payload
reuse. This combined promotion follows the user's explicit size choices.

Current resident payload is **5,076,560 RGBA32F bytes / 4.841 MiB**, including
its **2,634,768-byte** fixed boundary, or **2,441,792 bytes / 2.329 MiB without
that boundary**. Runtime Tone retains its 512-texel packing width: 256 cells
occupy 512 × 1, whereas the preceding diagnostic candidate used 257 × 1.

| Texture | Cells | Width × height | RGBA32F bytes |
|---|---:|---|---:|
| Tone | 256 | 512 × 1 | 8,192 |
| Color coefficients | 8,192 | 8,193 × 2 | 262,176 |
| Web parameters | 4,096 | 4,097 × 32 | 2,097,664 |
| Web toes | 1,536 | 1,537 × 1 | 24,592 |
| Compact Adaptance | 3,072 | 3,073 × 1 | 49,168 |
| Fixed output boundary | — | 513 × 321 | 2,634,768 |

The [independent absolute HDR report](../../../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/absolute-hdr-validation.md)
replays **444** float64 reference outputs and passes **16,940,389**
reconciliation assertions. Both CPU and software GPU cover all **148 cases ×
1,024 inputs × three spaces × two contexts**: **888 rows / 909,312 pixels per
backend**. Persistent trees and images remain in place through control edits.
Software GPU uses llvmpipe/EEVEE Shader and FULL GPU Compositor. The pinned
ACES 2.0 HDR-1000 Rec.2020 view and Rec.2100-PQ are applied once to obtain
fractional full-range 10-bit RGB codes. Pixel error is the largest absolute
RGB-channel difference; percentiles pool all tested pixels and channel RMSE
pools all three channels.

| Backend | Case scope | Mean pixel error | Channel RMSE | p95 | p99 | p99.9 | Maximum |
|---|---|---:|---:|---:|---:|---:|---:|
| CPU | All 148 | 0.000690513 | 0.0100381 | 0.000762194 | 0.00878810 | 0.104695 | 7.98566660 |
| CPU | Excluding alternating extremes: 147 | 0.000693419 | 0.0100713 | 0.000762194 | 0.00879572 | 0.105095 | 7.98566660 |
| Software GPU | All 148 | 0.00292591 | 0.866809 | 0.000853658 | 0.00896341 | 0.106484 | 337.422684 |
| Software GPU | Excluding alternating extremes: 147 | 0.000700729 | 0.0102819 | 0.000838414 | 0.00896341 | 0.106485 | 8.34962157 |

All numbers in the error table are fractional 10-bit codes. Excluding
`web_alternating_extremes` leaves **903,168 pixels per backend**; **22 CPU /
26 GPU** pixels exceed one code. The worst remaining witness is unchanged:
`source_boundary_0`, ACEScg, pixel 537, green channel, with Shader/Compositor
tied. Its reference green is about `1.30e-15` scene-linear; native green is
`1.50e-5` CPU / `1.62e-5` GPU. PQ turns this near-zero difference into
**7.98567 / 8.34962 codes**. These are absolute reference errors, distinct
from the preceding studies' added error when reducing one field.

CPU passes final RGB for all rows. Software GPU retains **six final-RGB
failed rows**, exclusively `web_alternating_extremes` across all three spaces
and both contexts. The worst is **337.422684 codes** on a nearly neutral
input whose reference output is approximately `4.46e-6` RGB while native is
approximately `0.18`. Independent reconciliation verifies this finding;
it does not make the numerical failure pass. Both backends remain finite and
pass containment, alpha and reference-validity checks, with **zero**
cross-backend validity or saturation-flag changes.

The fresh [scalar audit](../../../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/scalar-fixed/report.json)
passes all **31 distinct Tone functions**, with maximum conditioned error
**3.0973854e-6** against `1e-5`, and all **19 Web-parameter functions** under
their scoped policy. Raw Color, toe and Compact precision diagnostics remain
visible: **7 / 78**, **16 / 16** and **3 / 11** functions fail their raw
scalar limits. Their existing HDR admission policies remain in place; this
absolute-error report does not claim fresh admission against the historical
frozen baselines. The [combined regression receipt](../../../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/tests.json)
passes **86 test methods across nine Buck2 targets**: 40 layout, 30 tool and
16 native/persistent/gate-policy methods.

The preceding schema-4 generation, complete-preparation and prepared-edit
timings remain historical measurements; they are not current schema-5 costs.
Accuracy-run durations are not performance evidence.

## Historical schema-4 layout sensitivity

These retained results describe schema 4, including its own current-to-smaller
denominators and historical timing receipts; they do not measure schema 5.
The earlier study left schema 4 unchanged: Tone 512, Color
16,384, Web parameters 4,096, toes 1,536, Compact 8,192 and boundary 513 × 321.
Each candidate changes one texture. Full CPU coverage has **894 baseline +
10,728 candidate rows**, with **75,983,224 independent reconciliation
assertions**. The 17-control software-GPU subset has **102 + 1,224 rows** and
**8,989,366 assertions**. All numerical failures remain in the receipts.

The [complete tables](EVIDENCE.md) and [combined breakdown](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/breakdown.md)
use current capacities as their denominators. Smaller Color 8,192, Web
parameters 2,048, toes 1,280 and Compact 2,048 add at most **0.0195181 /
0.0410032 / 0.0262652 / 0.0243597 CPU HDR codes**. On the software-GPU subset,
the respective maxima are **0.0497332 / 0.0410127 / 0.0262500 / 0.0236280**.

All current CPU baseline rows pass final RGB. Toe 768 introduces **four** failed rows at alternating Web extremes in Rec.2020 and ACEScg, both contexts. Boundary 257 × 161 introduces **two** failed rows at `adaptance_half_1.0` in ACEScg, both contexts. Boundary 129 × 81 introduces **six** failed rows: that case in both ACEScg and Rec.2020, plus `exposure_0_6` in ACEScg, both contexts. All candidate rows remain finite and pass containment/alpha checks, with exactly zero validity/saturation flag changes.

The reduced Tone tables retain required scalar failures despite passing CPU final RGB: **12 rows at 256 cells** (maximum conditioned field error `1.2040514515e-5`) and **48 rows at 128 cells** (`4.7585139199e-4`), against `1e-5`; both remain monotone. Both reduced boundaries fail their required `2e-5` corrected-radius gate in all 894 CPU rows, with maxima `7.96938434e-5` and `3.46626417e-4`. These scalar values precede Color/view/PQ and are not HDR code errors.

The **0.05-code value is a diagnostic comparison in this study**. Tone, Web parameters and boundary retain their own scalar/local requirements. Existing Color, toe and Compact admission policies—including their explicitly frozen historical baselines—remain unchanged. This report promotes no candidate; runtime sizes stay fixed. Reduced Color-field scalar/local audits are not rerun by this HDR sweep, so absent scalar failures there do not certify scalar accuracy.

The **current-size GPU baseline already fails six final-RGB rows**, all at `web_alternating_extremes`, across all three spaces and both contexts. Its maximum absolute reference error is **337.422683787852 codes** on the nearly neutral ACEScg Compositor input `(0.180000007, 0.180000007, 0.180000097)`: reference scene-linear RGB is about `4.46e-6`, while native RGB is about `0.18`. The reference pixel peak is only `0.000866371` code, so its percentage is excluded by the below-one-code denominator rule; its absolute error remains reported. Small added errors below describe changes relative to this already failing baseline.

Both reduced boundaries introduce additional GPU final-RGB failures: **two** for 257 × 161 and **four** for 129 × 81. Every other candidate adds **zero** failed rows, while retaining the same six baseline failures. No candidate recovers a baseline failure. Every row remains finite and passes alpha/containment checks, with exactly zero validity/saturation flag changes. Passing independent reconciliation verifies these measurements; the retained numerical failures remain open.

HDR compares the reference, current native graph and reduced native graph after the pinned ACES 2.0 HDR-1000 Rec.2020 view with Rec.2100-PQ applied once, yielding fractional full-range 10-bit RGB codes. Signed added error is the per-pixel peak absolute candidate/reference error minus the current/reference error. Percent divides by the reference pixel peak, excluding denominators below one code. Code and percentage maxima can select different pixels. Movement and absolute reference error remain separate metrics.

Fresh generation timing is complete: **300 uncontended component samples**,
four cases × five repetitions, source-stable and runtime unchanged, with **2,949
independent generation-validation assertions**. Current
all-active pure-generation medians are **0.936 / 8.099 / 11.481 / 1.977 /
2.212 ms** for Tone / Color / Web parameters / toes / Compact. The retained
complete preparation **37.885 ms** and 16² software-GPU prepared-edit receipt
remain separately scoped. Retained Tone **1.180 ms** includes parameter
preparation; pure-generation Tone **0.936 ms** excludes it. Component medians
must not be added. Original node-budget and Next integration findings remain
separate; no correctness duration is used as performance evidence.

## Historical schema-4 Compact-only Adaptance change

The user requests one Adaptance representation: always use the **8,192-cell
Compact field**. The source removes Interior generation and storage, the
prepared-field member, native samplers and gain/tail representation routing
from both specialized and persistent trees. Compact retains its full-range map and
analytic exterior endpoint. The reference calibration and grading equations
remain unchanged.

Layout schema 4's calculated inventory is **5,428,848 RGBA32F bytes**, including
the 2,634,768-byte fixed boundary, or **2,794,080 bytes without it**. Removing
Interior saves 1,048,704 bytes. Existing persistent trees must be rebuilt and
reuse from the dual-table schema rejected. The runtime change, 90 regression
checks, independent full-corpus CPU validation, targeted software-GPU
strong-control evaluation and fresh preparation/edit timing are complete.

Retain the authorized **0.05-code maximum signed HDR worsening** for Compact,
and keep raw scalar/local failures diagnostic with their original limits.
The always-Compact path is measured against both the independent reference and
a frozen preceding dual-table baseline, including the retained strong-center
cases. Do not infer acceptance from old full-field results whose Interior
sampler masked Compact errors. Finiteness, significant sign, exact black,
validity/saturation, final RGB and containment remain required. Keep the
inherited node cap and software-GPU extreme-Web findings separately scoped.
The refreshed report binds the new sources and uses uncontended preparation
timing and software-GPU/Eevee edit timing.

The full matched CPU comparison has **894 case/space/context rows** over 149
cases × 1,024 inputs × three spaces × both contexts, using prepared-tree
updates. The preceding dual-table baseline and Compact-only path both pass
required final-output and safety checks. Maximum added error is
**0.0000304877758 HDR codes / 0.0000156437481% reference peak**, below 0.05;
validity/saturation flags never change. Both paths' worst absolute reference
error remains **7.98566659944 codes**. Shader/Compositor node counts fall from
1,468 / 1,399 to **1,445 / 1,382**; six images replace seven. The node cap
remains failed separately.

Each native local-stage suite retains 12 raw Compact precision failures under
the existing diagnostic policy. Worst normalized H/opponent/energy errors are
`5.18723906e-4` / `1.34718606e-4` / `1.19917385e-3`; required precision and
sign/safety checks pass. The complete schema-4 scalar audit retains two Color
failures among 78 functions, all 16 toe failures, and zero failures among the
19 Web-parameter, 11 Compact and 32 Tone functions. Those raw results are not
relabelled as precision passes.

The [independent validator](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/independent-validation.md)
passes **32,668,186 assertions** across all 894 matched rows, with 447
independent float64 oracle replays. It reconciles raw per-channel metrics,
signed worsening/percentages, witnesses, flags, alpha, final RGB, containment,
source hashes, geometry resource and archived native images. Maximum HDR
movement is **0.0000914633274078 codes**; it is separate from maximum added
error. The targeted **36-row software-GPU strong-control** comparison also
passes on llvmpipe/Eevee and full-precision GPU Compositor: at most
**0.0000304877758 added codes / 0.0000208583307% reference peak**, with unchanged
flags. This does not supersede the retained extreme-Web GPU finding.

The new [preparation receipt](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/preparation-costs/report.md)
has 20 uncontended runs. All-active complete preparation is **37.885 ms**;
Tone preparation, including its table, is **1.180 ms**. Pure Color-coefficient,
Web-parameter, toe and Compact generation medians are
**8.135 / 13.782 / 2.014 / 2.225 ms**. These component medians
must not be added to estimate complete time. Color medians across the four
cases are below 10 ms, while its maximum individual sample reaches 10.190 ms.
The fresh [software-GPU edit receipt](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/prepared-edit-costs/report.md)
has 30 rows at 16² with 254 requested logical CPUs and two repeated updates
per group. Repeated end-to-end medians span **463.626–516.755 ms Shader /
93.847–114.391 ms Compositor**; Exposure is **470.200 / 93.847 ms**. Entry and
initialization stay separate; these fixture/EXR costs do not isolate Grade-only
per-frame rendering or full-resolution preview latency. The current
[breakdown](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/breakdown.md)
collects the inventory, timing and sensitivity without changing older receipts.

## Historical Color-coefficient and Compact Adaptance HDR admission

The completed study below uses layout schema 3 with both Adaptance textures.
Its references to current source, routes and timings describe that historical
study, not the always-Compact change above.

The user authorizes **0.05 fractional 10-bit codes of maximum signed HDR
worsening** for Color coefficients and Compact Adaptance. The source now fixes
these roles at **16,384** and **8,192** cells respectively, with Web parameters
4,096, Web toes 1,536 and Interior Adaptance 65,536. The total fixed RGBA32F
payload is **6,477,552 bytes**. Fresh host-preparation timing is source-stable:
Color generation medians are 8.146–9.136 ms across four cases, with a maximum
individual sample of 11.786 ms; all-active complete preparation is 43.838 ms.
All 87 checks across eight targets pass. The independently validated persistent
CPU HDR comparison has 894 baselines and 2,682 measured candidate rows. Color
adds at most **0.0115159237 codes / 0.00529889482%**, Compact
**0.00128048658 codes / 0.000361764104%**, and combined matches the Color
maximum. All pass the 0.05-code layout budget, final RGB, containment and
unchanged validity/saturation flags. Baseline/combined maximum absolute
reference error remains 7.9856666 codes. The node cap remains failed: Compact
and combined remove seven nodes, leaving 1,468 Shader / 1,399 Compositor.
Earlier source identities remain historical.

Color/Compact scalar and local precision thresholds retain their original
values and raw failure results as diagnostics. Layout admission for these two
roles uses the HDR worsening budget. Retain finiteness, significant sign,
exact-black, validity/saturation, containment, final RGB and node-budget checks.
The existing Web-toe HDR policy remains separately scoped; other roles retain
their current scalar/local gates, including the exact alternating-Web exception.
Complete audits must retain every selected function and probe even after a raw
precision failure. A diagnostic failure is never rewritten as a precision pass.

The pre-promotion [candidate study](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/)
has 200 generation measurements, complete 78-/11-function scalar audits and
the matched 149-case CPU HDR corpus. Color 16,384 meets the measured under-10-ms
target and adds at most 0.0115159 HDR codes / 0.00529889% reference peak. Compact
8,192 halves bytes and has zero full-field HDR movement, while the ordinary
compact-only local path retains eight raw precision failures among 18 rows.
That pre-display/PQ normalized opponent metric reaches `1.22195872e-5` against
the unchanged raw `1e-5` diagnostic threshold. The full-field HDR corpus can
mask Compact effects through its Interior Adaptance path; zero HDR movement
does not certify zero isolated local error.
[EVIDENCE.md](EVIDENCE.md) records those historical diagnostics and the complete
current persistent admission, scalar audit and 16² software-GPU edit report.
The persistent report measures nonzero Compact sensitivity through its
common-control route; the specialized zero-movement result is historical.

## Historical 4,096-cell Web-parameter evaluation

This report measured 131,072 Color-coefficient cells and 16,384 Compact
Adaptance cells. It does not certify the current source hashes, layouts or
timings following the Color/Compact promotion.

The user authorized the fixed runtime Web-parameter layout at **4,096 cells**,
with the existing **1,536-cell toe**. The matched
[evaluation](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/hdr-summary.md)
compares against explicit 32,768 parameters / 1,536 toes on all 149 cases,
1,024 pixels, three spaces and both contexts for CPU and software GPU.
Each backend has 894 baselines, 90 measured candidates and 804 inactive rows,
with no generation, render or nonfinite failures. The independent validator
confirms sources and native candidate texture contents/dimensions.

CPU maximum signed worsening is **0.0404496565 fractional HDR codes**, or
**0.122978849% of reference peak**. Software GPU reaches **0.00974084437
codes**, or **0.122460364%**. Percentage and code maxima can occur at different
pixels; percentages exclude reference peaks below one code. CPU has no
final-RGB failures. Software GPU retains six baseline and six candidate
final-RGB failures, all alternating-extreme near-neutral cases, with identical
worst errors before and after the parameter reduction. The candidate has no
scalar failures, changes no validity/saturation flags and passes containment.
The inherited node-budget failures remain separate.

The earlier scalar/local case-specific `1e-4` policy remains in force for
alternating extremes. This promotion changes no equations, accuracy limits,
safety gates or the 0.05-code toe-admission policy. The fresh CPU and GPU
candidate reports supplement the historical sizing receipts below.

## Authorized Web-toe HDR admission

The user subsequently authorized a **0.05-code maximum signed worsening** for
the fixed runtime Web-toe size, measured against an explicit 524,288-cell toe
baseline. Candidate sizes are 256, 512, 768, 1,024, 1,280, 1,536, 1,792 and
2,048 cells. Measure every candidate on the full existing HDR corpus and choose
the smallest passing supported size; sampled maxima need not be monotonic.

For toe size admission, complete scalar errors and local Web H/opponent/energy
and returned-scale precision are diagnostics. Their original limits and raw
pass/fail results must remain visible. Do not convert scalar failure into scalar
success. Strict native arithmetic regression checks retain the legacy fine toe;
the reduced layout receives independent-reference diagnostics and retained
finiteness, significant-sign, validity, saturation, containment and final RGB
checks. Require zero validity/saturation flag changes versus the baseline.
The raw limits remain unchanged. Color coefficients and Compact Adaptance
subsequently received the separately authorized HDR admission policy above;
other field and non-Web local-stage admission gates retain their existing scope.

The admission receipt must bind source, dependency, display, input, baseline
layout and candidate identities. It uses all 149 cases, 1,024 float32 inputs,
three scene spaces and Shader/Compositor CPU. Inactive candidates stay explicit;
generation/render/nonfinite failures reject a layout. The original node-budget
failure is recorded separately.

The source-stable [toe sweep](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/sweep-merged/report.md)
and independent validator select **1,536 cells**: maximum signed worsening
`0.0393597186` codes and movement `0.0393597186`. The next smaller candidate,
1,280 cells, is rejected at `0.0506249517` codes. The promoted payload is
`1,537 × 1` RGBA32F, `24,592` bytes. The [local/seam receipt](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/local/report.md)
records zero safety failures while preserving 16 raw precision failures across
112 comparisons. The [complete scalar diagnostics](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-scalar/report.json)
cover all 149 cases, 16 distinct toe functions and all eight candidates without
turning their raw precision failures into passes.

The [retained percentage summary](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/sensitivity-percentages.md)
fills the previously omitted percentage maxima: **0.151449259%** at 1,536
cells and **0.103094441%** at 1,280. These toe measurements retain the old
32,768-parameter / 524,288-toe baseline. The percentage maxima are independent
of the code maxima and are not recomputed by dividing one maximum by another.

The [promoted-layout verification](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-merged/report.md)
repeats all 894 baselines and 894 candidate rows (90 measured, 804 inactive)
against the original toe. Its maximum signed worsening and movement match the
sizing sweep, all retained scene-linear/containment checks pass, and validity
and saturation flags do not change. The 21 inherited baseline node-budget
failures remain separate. The [independent validator](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-validation.json)
checks exact coverage, identities and candidate results. The fresh
[selected-layout local/seam report](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-local-final/report.md)
has zero safety failures and two raw precision failures across 14 comparisons.
All 11 focused Buck2 targets pass, including full guarded Grade, persistent
update/rollback/save/reopen, and specialized/persistent Color-stage regressions.
The [initial regression log](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-tests.log)
contains nine passing targets; its two helper failures are superseded by the
[final stage regression log](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/corrected-stage-tests.log),
which passes all three rerun targets after the helper corrections.

The isolated [preparation-cost report](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/preparation-costs-final/report.md)
contains five repetitions of four cases, uses CPUs 0–7 with one OpenBLAS/OpenMP
thread and stable sources, and runs without concurrent heavy work. Toe payload
falls by **8,365,040 bytes (99.7069%)**, and total resident payload is
**24,960,704 bytes**. Toe-generation medians span **2.122–2.149 ms**; complete
portable preparation spans **186.180–192.829 ms**. For `all_active`, Web
parameters take **96.489 ms** and toes **2.122 ms**. These costs exclude native
upload/packing, construction, rendering and interaction latency; component and
complete timings are separate measurements.

The [aggregate receipt](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/summary.md)
links diagnostics, tests and independent validation. JSON SHA-256 values are:

- Sweep: `b0ecdcfcb07d6c251cd0ad0541ce3494a16ed71865624017b20089028758bea6`.
- Promoted verification: `a88998093aac15fb25ee93739edcfa0d50f40ba2f3756fe2d5973d6d8175fc84`.
- Clean preparation timing: `cbc240a1226fb77444e95705f5c16a4102ad31c6515d5c828c74a98aaf4003fd`.

The sections below retain the policy and scope of their earlier runs.

## Measured HDR code-value sensitivity diagnostic

The completed [report](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/report.md)
adds a display-referred diagnostic beside these stage
gates. The reference, current native result and each reduced-texture native
result are passed through the same pinned Blender OCIO processor for the
row's input scene space, with display `Rec.2100-PQ` and view `ACES 2.0 - HDR
1000 nits`. The view includes the Rec.2100-PQ encoding, so it is applied once.
The resulting floating values are multiplied by 1023 and compared as
fractional full-range 10-bit code values.

For reference `R`, current `B` and reduced `C`, the report defines:

```
current_error = max(abs(B - R))
reduced_error = max(abs(C - R))
movement      = max(abs(C - B))
worsening     = reduced_error - current_error
```

It reports per-channel and per-pixel-peak distributions, RMSE, percentiles,
maxima, code thresholds and signed improved/unchanged/worsened counts, with
input and all three scene/code RGB values in worst witnesses. Percentage
normalization uses `max(abs(R))` only for reference pixels at least one code
value; near-black pixels are reported in absolute code units. This is a
sensitivity measurement and does not waive any scalar, local, containment,
final-RGB or node-budget gate. No per-pixel archive is required.

The full sweep uses 1,024 deterministic pixels per case, the 149 retained
grade/UI cases, all three scene spaces and both Shader/Compositor CPU contexts.
Each candidate changes only the named texture, except the explicit combined
Web pair. Inactive textures are reported as not sampled. Every halving listed
below is measured even if its existing scalar gate fails.

| Texture | Current layout | Reduced diagnostic layouts |
|---|---:|---|
| Tone | 512 cells | 256, 128, 64, 32 cells |
| Color coefficients | 131,072 cells | 65,536, 32,768, 16,384, 8,192, 4,096, 2,048 |
| Web parameters | 32,768 cells | 16,384, 8,192, 4,096, 2,048 |
| Web toes | 524,288 cells | 262,144, 131,072, 65,536, 32,768, 16,384, 8,192, 4,096, 2,048 |
| Compact Adaptance | 16,384 cells | 8,192, 4,096, 2,048 |
| Interior Adaptance | 65,536 cells | 32,768, 16,384, 8,192, 4,096, 2,048 |
| Output boundary seed | 513×321 pixels | 257×161, 129×81, 65×41 pixels |
| Combined Web | Current parameters and toes | 4,096 parameter / 32,768 toe cells |

Tone candidates retain shared endpoint jets and monotonicity limiting, with
smaller actual pixel storage. Boundary candidates retain the 0.9 split,
proportional low/high height grids and one safeguarded Halley correction;
coordinate mapping must use the candidate's grid metadata. Runtime generation
defaults and canonical resource validation stay fixed. Generation failures,
nonfinite results and unused textures remain explicit outcomes.

OCIO accepts float32 buffers in the pinned build. Reference grading remains
float64 and is rounded once at the shared display-input boundary; all encoded
values are promoted to float64 for code scaling and metric arithmetic. There
is no extra exposure, gamma, look, display clipping or integer quantization.
The report records processor/configuration identities, dependency versions,
source/resource hashes and the precision boundary. JSON and Markdown retain
mean/RMSE, p50/p95/p99/p99.9/max and counts above 0.1/0.5/1/2 codes. Checkpoints
may resume only with matching sources, settings and identities; partial runs
remain visibly incomplete.

The source-stable run covers 149 cases × 3 spaces × 2 CPU contexts, with 894
baselines and 30,396 candidate rows across 34 layouts. It measured 8,286
candidate rows and recorded 22,110 inactive-texture rows as `not_sampled`; no
candidate generation, render or nonfinite rows failed. The worst current-layout
pixel error is **7.9856666 codes**; 24 of 915,456 baseline pixel samples exceed
one code and four exceed two. All baselines pass the scene-linear output gate;
21 retain the existing node-budget failure. Among measured candidates, 256 fail the
complete scene-linear gate, 678 fail the separate `<1000` expanded-node budget,
3,744 fail an intermediate scalar field gate, and none fail containment. The
largest reduced-versus-current worsening is **186.780493 codes** for Tone/32;
the complete witness is retained in the JSON. Web parameters/4096 and the
combined Web 4,096/32,768 candidate have zero scalar-field failures in their
measured rows, while the smaller candidates retain their explicit scalar
witnesses. This diagnostic does not alter any production layout or gate.

The [sensitivity table](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/sensitivity.md)
includes percentage worsening relative to the reference pixel peak. The
combined Web 4,096/32,768 candidate adds at most `0.0404497` codes of error,
with a maximum eligible percentage worsening of `0.145225%`; these maxima can
occur at different pixels. Web toes/32768 adds at most `0.000701219` codes or
`0.00148168%`. The code metric is not monotone with texture size because native
rounding and interpolation errors can cancel or amplify at a sampled pixel.

Reproduce the full sweep into a fresh output directory with:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
buck2 run //products/perceptual-grade-next-blender/tools/reports:hdr_report -- \
  --output-dir buck-out/persistent-grade-evidence/hdr-reproduction
```

Independent workers may add `--case-shard INDEX COUNT`, with a separate output
directory for each zero-based index. Merge all complete shard directories using
`--merge-shards DIR...` into a fresh output directory. Every shard must have
matching sources/display/settings, stable sources and exact disjoint case
coverage; journals and checkpoints must match its committed report. `--resume`
retains committed rows only when the complete identity matches.

This note maps the current numerical acceptance gates to the native grading
pipeline and distinguishes them from a final-output-only policy. The original
gates below remain the ordinary-control baseline; the case-specific Web sizing
studies record the user's explicit scalar and native Web exception. The active
source contract is in [GOAL.md](../../products/perceptual-grade-next-blender/GOAL.md), with field and boundary details
in [COLOR_TABLES.md](COLOR_TABLES.md) and [BOUNDARY.md](BOUNDARY.md).

This review considers allowing a large intermediate error when its measured
effect on final output is small. That would change the current
acceptance contract, which gives several intermediate errors their own gates.
Until that contract is deliberately revised, an end-to-end pass does not waive
an intermediate failure.

## Pipeline and current gates

The reference comparison follows Linear → appearance encoding → Tone → Color
terms → tonal Web → selective Adaptance → Web final scale → H–K repair → AP1
output-boundary projection and scene decode. Parameter textures approximate
functions used inside the Color/Tone stages; their error gates are upstream of
the native stage comparisons.

| Layer | Current measurement and limit | Why it is separate |
|---|---|---|
| Portable Linear preparation | Independent-reference matrix comparison uses `rtol=atol=3e-12`; primitive matrix and endpoint tests have their own tighter float64 tolerances. | Verifies control conventions and matrix construction before native float32 execution. |
| Native appearance/Tone handoff | H/a/b vector normalized error `≤ 1e-4`; `J_A` uses `rtol=1e-4, atol=1e-5`, signed energy uses `rtol=2e-4, atol=1e-5`. Exact black and neutral-opponent cases are asserted. | Tests exposed stage interfaces independently of the complete wrapper. |
| Tone coefficient table | Monotone Quintic 256; `abs(sampled-exact) / max(1, abs(exact)) ≤ 1e-5`. Tone Fit is `[-2, 2]`. | Checks the actual quantized table before its values enter later grading; raw failures remain reportable. |
| Color parameter fields | Per-channel conditioned error `abs(sampled-exact) / max(1 + abs(exact), conditioning_scale) ≤ 1e-5`. | Checks the packed field against its authored function, including signed coefficients and cancellation. |
| Sensitive field interpolation | Chroma coefficients and Web radial log coefficients: absolute error `≤ 3e-6`; positive Web toes: relative error `≤ 1e-6`, at the represented float32 coordinate. | Additional limits protect exponentiation and the quartic radial toe from amplifying interpolation error. These supplement, not replace, the conditioned field gate. |
| Color substages | At identical float32 handoffs and frozen selectors, conditioned H, opponent and signed-energy errors each `≤ 1e-5`; significant energy-sign mismatches are disallowed. Returned Web scale has a relative `1e-5` limit. | Measures each substage independently so later stages cannot conceal a local discrepancy. |
| H–K repair | Coordinate `max(abs(delta_q))/(1+max(abs(q_ref))) ≤ 1e-5`; carried energy `abs(delta_E)/(1+abs(E_ref)) ≤ 1e-5`. | Checks the raw repair before output projection. |
| Boundary projection | Corrected radius `abs(delta_radius)/(1+radius_ref) ≤ 2e-5`, plus legal decoded native AP1 containment in `[0,1024]`. | Radius accuracy and containment are different properties; legal RGB alone does not prove the projected radius is accurate. |
| Complete guarded output | `max(abs(actual-reference)) / (1 + max(abs(reference))) ≤ 1e-4`; validity agrees, outputs are finite, invalid output is black, and alpha error is `≤ 2e-6`. Saturation cases remain included. | Measures the final product output across the retained end-to-end corpus. It cannot identify which intermediate stage caused an error. |
| Raw Linear + Tone regression | Ordinary-response gate `≤ 1e-4` where reference response magnitudes are `≤ 300`; valid near-pole cases above 300 are separately reported, and invalidity must agree. | Preserves the isolated raw-stage contract without applying the full output guards. |

The complete report also checks reconstructed AP1 containment with a normalized
`8e-6` endpoint-rounding allowance. This is distinct from the isolated guard's
exact native `[0,1024]` assertion. The scalar Tone reference test separates
float64 function parity (`rtol=2e-9, atol=2e-10`) from the quantized total Tone
stage's `1e-4` normalized limit and the table's stricter `1e-5` limit.

Full Shader and Compositor graphs also have a separate `<1000` expanded-node
cost gate. It is not an accuracy metric. Reports keep numerical and node-budget
results separate.

For a Color substage, let `C_i` be its input opponent magnitude, `C_ref` the
reference output magnitude, and `E_i`, `E_ref` the input and reference output
signed energies. The documented conditioned scales are:

```
S_C = 1 + C_i + C_ref
S_E = 1 + abs(E_i) + abs(E_ref) + 66*(C_i + C_ref)
S_H = 1 + sqrt(abs(E_i) + 66*C_i) + sqrt(abs(E_ref) + 66*C_ref)
```

The substage reports `abs(delta_H)/S_H`, Euclidean opponent error divided by
`S_C`, and `abs(delta_E)/S_E`. Absolute and relative energy errors are retained
as diagnostics. Energy sign agreement is checked when
`abs(E_ref) > 1e-5*S_E`. The values are compared at the same float32 state,
rather than after different upstream errors have accumulated.

## What the evidence says about downstream effects

The current evidence contains both amplification mechanisms and cases where a
later check observes a different aspect of the result. These observations
motivate measuring downstream impact; they do not justify comparing independent
worst-case maxima as though they were one causal sample.

- `COLOR_TABLES.md` records a Web sector-seam witness where absolute radial
  log-scale error reached `1.73e-5` despite passing the conditioned field gate.
  Because that value is exponentiated and participates in the quartic radial
  toe, separate interpolation budgets were added. The same document records
  that a conventional expanded quintic's float32 cancellation was amplified by
  a 32-stop log-gain difference; the equivalent positive polynomial form
  removes that cancellation path.
- The same field specification reports a compact Adaptance coordinate witness
  at height `47.1189113567`: log-gain error `2.67e-6` for the compact map and
  `6.44e-8` for the linear-height interior map. The native Adaptance stage is
  independently tested because its calibrated response transform can amplify
  field error. The current evidence records an 8192-cell compact candidate
  failing the native local opponent gate at `1.07903e-5`.
- The current local Color report records a maximum conditioned local error of
  `8.98040924e-6`; separate accumulated raw reports record maxima as high as
  `2.58054474e-4` opponent error for Linear + Tone + Color. These are different
  summaries and do not identify a same-pixel, same-control propagation path.
  Their size difference alone cannot prove amplification, cancellation, or
  suppression by any particular later stage.
- `BOUNDARY.md` documents a near-white GPU power-rounding defect caught by the
  isolated boundary-radius gate even though the complete RGB gate passed. This
  demonstrates that final RGB acceptance alone can miss an internal boundary
  defect; it does not quantify the defect's induced RGB delta.
- The field-bound analysis in `COLOR_TABLES.md` establishes that a large source
  chroma ratio suppresses Adaptance reach. This is a model sensitivity relation,
  not evidence that an observed numerical residual was suppressed in a paired
  final-output sample.

The completed [coherent sensitivity report](../../../../buck-out/persistent-grade-evidence/gate-sensitivity-accepted/report.json)
supersedes the earlier generic output. Its [README](../../../../buck-out/persistent-grade-evidence/gate-sensitivity-accepted/README.md)
records the key correction: every modified handoff restores
`H = signed_hk(sign(E)*sqrt(abs(E)), hypot(a,b))`; H perturbations use a stable
signed-energy inverse. The [Markdown summary](../../../../buck-out/persistent-grade-evidence/gate-sensitivity-accepted/report.md)
covers 24 grade/space baselines (eight cases × three spaces), 1,024 pixels each
and 4,656 perturbation rows. Baselines match the full oracle exactly and source
identities stayed stable during the run. The report SHA-256 is
`d48469455cbb0f0458f44b38fcb4162e8085b54960fbfc5c9b6a05608a50ad34`.
All 1,008 H-dose records satisfy the conditioned float64 epsilon bound; maximum
realization error is `4.04310e-16` in conditioned H units, and the largest
residual/bound ratio is `0.0144346`.

Reproduction uses the gate-sensitivity target with the coherent source snapshot:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:gate_sensitivity -- \
  --output-dir buck-out/persistent-grade-evidence/gate-sensitivity-accepted \
  --samples 1024 \
  --spaces 'Linear Rec.709' 'Linear Rec.2020' ACEScg
```

The earlier generic H-only rows must not be interpreted as cancellation or guard
masking. They changed H while leaving carried energy unchanged, producing
incoherent states; later handoffs correctly treat carried signed energy as
authoritative and reconstruct H from it and chroma. The coherent run removes
that artifact. It also retains the required limitations: controlled reference
perturbations do not certify attainable native texture errors or authorize
relaxing any gate; uniform Web parameter/toe injections are propagation probes,
not texture interpolation replacements. The native lower-size field failure
smoke remains diagnostic. The complete scalar field audit and focused native
Web candidate experiment are now source-stable and complete, as recorded below.
The broader
interrupted run is retained separately in
`buck-out/persistent-grade-evidence/field-effects-all-roles-partial/` and is not a
completed candidate acceptance receipt.

The coherent report includes legal, nonblack, nonwhite, unprojected witnesses
where large local changes induce small final changes. For example,
`web_alternating_extremes` in Linear Rec.709, a coherent Color-terms H decrease
of `0.01` at sample 236 has local error `0.022520157115009053` and added final
RGB delta `1.5925748270213376e-10` against the paired unperturbed baseline;
its expected/perturbed H values are
`2.201091371598225` and `2.1468765590680805`, with the same opponent coordinates
and carried energy recomputed by the H–K identity. This is a controlled
reference sensitivity witness, not an attainable native texture-error receipt.
For the same case and space, sample 885's returned boundary-radius perturbation
of `+0.01` has local radius error `0.010000000000000096` and added final RGB
delta `7.533920075187585e-6` against the paired unperturbed baseline. It remains
legal, nonblack, nonwhite and unprojected in both branches, and decodes without
a second boundary guard. This is a
per-sample final effect; neither witness asserts that every sample tolerates the
same dose.

The active contract explicitly says accumulated raw Color error is reported
separately and that output guards must not conceal a failed local gate. Thus the
current 1e-5 substage limits are independent acceptance requirements, not
diagnostic thresholds that can be ignored when final RGB passes.

## Measuring a proposed final-impact policy

If acceptance is changed so a large intermediate residual may pass when its
downstream effect is small, record that effect using paired, source-bound
counterfactuals rather than comparing unrelated maxima:

1. Retain each corpus sample's settings, input, float32 handoff, backend/context,
   saturation/validity state, and source/resource identities.
2. For one stage at a time, branch from the identical frozen input state. Feed
   the reference stage result and its coherently perturbed counterpart through
   the same exact downstream reference stages and guards; compare the paired
   final RGB outputs with the complete-output metric. This estimates sensitivity
   to that stage residual under the reference downstream path.
3. Also retain full native-versus-reference final error. The one-stage
   counterfactuals do not sum to the full error: stages interact, and their
   residuals can reinforce or cancel. Report stage-local error beside its
   paired induced-final distribution and worst sample identity.
4. Keep structural validity, finiteness, significant sign, alpha, and actual
   AP1 containment checks visible as their own invariants. A small RGB delta
   does not establish that these properties hold.

The final-output-only option would make the paired induced-final result the
approximation-accuracy acceptance measure and retain intermediate error as a
diagnostic. The present contract instead gates both local behavior and final
behavior. This note leaves that policy choice explicit; it does not reclassify
an existing failure. This reference sensitivity measurement is not a native
implementation test; it does not establish that native texture interpolation
attains the injected residual.

## Historical evidence status before the HDR layout-admission policies

The local-stage and boundary witnesses above retain their 2026-10-29 scope. The
accepted sensitivity report was source-stable against that run's producer
(`d7269a85060d86c13e7db062fe3fc8cb2253ddd74780af6156976c90c81e0da2`) and
leaves all production gates unchanged. The separate [full CPU rerun](../../../../buck-out/persistent-grade-evidence/full-cpu-rerun/report.json)
contains 102 case/context/space rows of 1,024 samples, has stable sources and
passes numerically (`2.6288837137644723e-5` worst normalized RGB), but still
fails the original node-budget gate. Its SHA-256 is
`f92fa8f9a1ed6833b32d7898da96832bdc755be6312a810dc61600c145e29785`.
That independent native maximum is not a causal comparison with any sensitivity
maximum. Preserve the distinct local, induced-final and full end-to-end metrics
without merging independent maxima.

The [fresh scalar field audit](../../../../buck-out/persistent-grade-evidence/field-audit-rerun/report.json)
passes over the complete retained 149-case corpus, with resolution selection
performed and stable source/resource identities. Its SHA-256 is
`4786fd6b5d069d3e4c74e16502877576e7476d4eff100219ab9a79b660971419`.
The run checks 32 distinct Tone configurations and selects the first passing
supported scalar resolution for each Color-field role. Every smaller attempted
candidate's failure witness is retained. This is a finite-corpus result, not an
exhaustive bound over continuous controls.

| Field | Scalar-selected cells | Historical runtime cells | Distinct functions | Historical scalar result |
|---|---:|---:|---:|---|
| Color coefficients | 131,072 | 131,072 | 78 | Runtime passes; every smaller supported candidate fails |
| Web parameters | 32,768 | 32,768 | 19 | Runtime passes; every smaller supported candidate fails |
| Web toes | 524,288 | 524,288 | 16 | Runtime passes; every smaller supported candidate fails |
| Adaptance parameters | 8,192 | 16,384 | 11 | Both selected and runtime capacities pass scalar gates |
| Adaptance interior parameters | 2,048 | 65,536 | 11 | Both selected and runtime capacities pass scalar gates |

The audit correctly reports `minimal_runtime_layout=false`: the Adaptance
runtime capacities exceed their scalar minima. Historical native admission in
[EVIDENCE.md](EVIDENCE.md) records compact 8,192 failing the native local
opponent gate at `1.07903e-5`, and interior candidates through 32,768 failing
native admission despite scalar passes. That history explains why scalar
selection alone could not reduce those 16,384/65,536 capacities under the earlier
policy. Compact Adaptance now uses 8,192 cells under the authorized HDR admission
rule; Interior Adaptance retains 65,536. The older report is not reclassified
as a new native rerun.

Reproduce the scalar selection separately from runtime preparation:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:audit_fields -- \
  --output-dir buck-out/persistent-grade-evidence/field-audit-rerun
```

The [completed native Web candidate report](../../../../buck-out/persistent-grade-evidence/field-effects-web-final/report.json)
contains 48 candidate rows and 12 fixed-layout baselines on Buck-launched
Blender 5.2.2 CPU. It covers `all_active` and `web_alternating_extremes`, three
scene spaces, Shader and Compositor, and two sizes for each Web field. All
candidate and baseline final RGB comparisons pass `1e-4`; sources/resources
were stable, and no sample changed validity or saturation state. Its SHA-256 is
`eeab609bfc8d8c8161ef878eba83afaaa2e4eccd111ff49167181cf447948c3a`.

The paired delta below is
`max(abs(candidate-native_baseline))/(1+max(abs(float64_reference)))` for the
same sample and controls. It is separate from candidate-versus-reference final
accuracy. Each row summarizes 12 candidate comparisons; the field gate includes
the separate scalar interpolation requirements.

| Field | Candidate cells | RGBA32F bytes | Largest paired final delta | Field gate over both selected cases | Final RGB gate |
|---|---:|---:|---:|---|---|
| Web parameters | 2,048 | 1,049,088 | `3.97334580e-5` | Fails alternating extremes | Pass |
| Web parameters | 16,384 | 8,389,632 | `4.38231171e-6` | Fails alternating extremes | Pass |
| Web toes | 2,048 | 32,784 | `1.22384012e-5` | Fails both cases | Pass |
| Web toes | 262,144 | 4,194,816 | `1.82053651e-7` | Fails alternating extremes | Pass |

Thus 30 candidate rows fail a scalar field gate while passing final RGB in this
native finite corpus. At 16,384 Web-parameter cells, alternating extremes retain
an absolute interpolation witness of `5.53339179e-6` against `3e-6`; at 262,144
toe cells they retain a relative witness of `1.42033061e-6` against `1e-6`.
Those scalar witnesses are coordinates in the field and are not identified as
the same RGB input pixels that produce the final-delta maxima. Audits that stop
on failure retain a failure witness rather than a global field-error maximum.

This demonstrates an observed difference between field-gate acceptance and final
RGB behavior for actual sampled native candidates. It does not certify a
continuous setting/input domain, the independent local native-stage gates, or
the absence of a worse result at a scalar witness not visited by these pixels.
All existing gates and runtime layouts remain unchanged; the final pass does not
reclassify the smaller fields as accepted under the present contract. The
2,048-cell candidates also exceed the diagnostic `1e-5` added-delta reference
level in their worst samples, while remaining within the `1e-4` final RGB gate.

The [run README](../../../../buck-out/persistent-grade-evidence/field-effects-web-final/README.md)
records eight-CPU affinity because unrestricted scheduling inflated native
construction time in a smoke run. Reproduce the completed diagnostic with:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-7 buck2 run //products/perceptual-grade-next-blender/tools/reports:field_effects -- \
  --output-dir buck-out/persistent-grade-evidence/field-effects-web-final \
  --audit-report buck-out/persistent-grade-evidence/field-audit-rerun/report.json \
  --samples 1024 --fields 'Web parameters' 'Web toes' --coarse
```

Its specialized graph construction and EXR timings are diagnostic costs, not
persistent interaction latency. The partial all-role run and initial smoke runs
remain separate from this completed native Web receipt.

## Historical prepared texture payload and host preparation time

The source-stable [fixed-field preparation report](../../../../buck-out/persistent-grade-evidence/preparation-costs-final/report.json)
and [summary](../../../../buck-out/persistent-grade-evidence/preparation-costs-final/report.md)
retain the original 524,288-cell toe layout. The promoted-layout report is
linked above. This earlier run measured all resident fixed fields, including fields inactive in the authored
case. The five-repeat run covers reset, all-active, alternating Web extremes,
and maximum controls with active Adaptance tail. It uses eight-CPU affinity
(`0–7`), pinned Python 3.13.6 and one-thread OpenBLAS/OpenMP. Report SHA-256:
`92cfedbfc9f8d8714c363c483d4ea3d62538f8f1d498744fa3086769a5406b6c`.

The resident RGBA32F pixel payload is **33,325,744 bytes**: Tone 16,384;
Color coefficients 4,194,816; Web parameters 16,779,264; Web toes 8,389,632;
compact Adaptance 262,176; interior Adaptance 1,048,704; boundary geometry
2,634,768 bytes. First boundary load measured `0.036106` seconds and was reused
for the cases.

| Case | Complete preparation median (s) | Web parameter generation median (s) | Web toe generation median (s) |
|---|---:|---:|---:|
| Reset | 0.876255 | 0.096053 | 0.691719 |
| All active | 0.859065 | 0.097300 | 0.673016 |
| Web alternating extremes | 0.867279 | 0.099962 | 0.668457 |
| All families, active tail | 0.866781 | 0.095774 | 0.672285 |

Component-generation timings and uninstrumented complete-preparation timings
are separate measurements and must not be added. The run performs no dense
audit or resolution search and times no Blender graph construction, image
upload/packing, render, or interaction. These are portable preparation costs,
not native texture allocation/VRAM or persistent edit-to-draw latency. With
current sources, reproduce the promoted layout into a fresh directory with:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-7 \
  buck2 run //products/perceptual-grade-next-blender/tools/reports:preparation_costs -- \
  --output-dir buck-out/persistent-grade-evidence/toe-hdr-005/preparation-costs-reproduced \
  --repeats 5
```

## Case-specific Web-toe sizing study

The user authorized `1e-4` for both scalar Web-toe errors in
`web_alternating_extremes`: conditioned field error and relative interpolation
error. Ordinary controls retain `1e-5` conditioned / `1e-6` relative limits.
At that stage of the study, other fields and native substage gates retained
their original limits; the later parameter/local policy is recorded below. This is
an explicit exception for the retained extreme-control case, not acceptance
derived solely from final RGB.

The case alternates radial controls across both six cyclic handles and four
tonal rows: `log_chroma[row,col] = 16*(-1)**(row+col)` and
`log_scale[row,col] = 8*(-1)**(row+col)`. All hue offsets are zero. Adjacent
handles move to opposite radial extremes; the pattern reverses at the next
tonal row. This forces steep transitions between the smallest and largest
authored radial gains.

The [65,536-cell complete audit](../../../../buck-out/persistent-grade-evidence/toe-65536-full-audit/report.json)
first established relative error `2.1737792569177916e-5` and conditioned error
`8.901001452626625e-6`. The subsequent [complete smaller-grid sweep](../../../../buck-out/persistent-grade-evidence/toe-limit-1e4/report.json)
retains full maxima and witnesses, including float32 coordinate rounding-bin
boundaries. Neither audit stops at its first failing witness.

| Cells | Unique height samples | Maximum relative error | Maximum conditioned error | Both authorized limits |
|---|---:|---:|---:|---|
| 65,536 | 65,537 | `2.17377926e-5` | `8.90100145e-6` | Pass |
| 32,768 | 32,769 | `8.67450479e-5` | `3.55143191e-5` | Pass |
| 16,384 | 16,385 | `3.46727218e-4` | `1.41895704e-4` | Fail |
| 8,192 | 8,193 | `1.37040750e-3` | `5.60683680e-4` | Fail |
| 4,096 | 4,097 | `5.15128796e-3` | `2.10366290e-3` | Fail |
| 2,048 | 2,049 | `2.08167435e-2` | `8.51725985e-3` | Fail |

Thus **32,768 cells is the smallest passing supported scalar grid**. It uses
86.745% of the authorized relative-error budget. At its worst relative witness,
`scale_toe` channel 2 has exact value `0.6926066862639909` and sampled value
`0.6925466060638428` at normalized coordinate `0.19361876696348193` (the exact
function uses the represented float32 coordinate).

The [combined policy receipt](../../../../buck-out/persistent-grade-evidence/toe-limit-1e4/acceptance.json)
also verifies all other 15 distinct toe functions from the source-identical
149-case audit. At 32,768 cells these complete rows pass the original limits:
maximum conditioned error `1.42445154e-7`, relative error `2.05186189e-7`.
The receipt covers all 16 distinct functions, verifies current source/resource
and script hashes, and preserves the original-gate rejection statuses.
This is finite-corpus scalar selection within the supported power-of-two grids,
not a proof over all controls or arbitrary intermediate cell counts.

The [native 32,768-cell report](../../../../buck-out/persistent-grade-evidence/field-effects-toe-32768/report.md)
contains 12 candidates and 12 baselines: two retained cases, three scene spaces
and both CPU contexts, with 1,024 pixels per comparison. All final RGB checks
pass and no validity or saturation flags change. The largest paired normalized
RGB delta is `2.2740272507015577e-7`, for alternating extremes in the Rec.709
Compositor. Image readback verifies the candidate pixels and dimensions. The
harness still reports the original scalar failures; use the complete scalar
policy receipt for the authorized exception. Three existing all-active Shader
node-budget failures remain. Independent local-stage/persistent/GPU acceptance
was not rerun for this candidate.

The [paired timing report](../../../../buck-out/persistent-grade-evidence/toe-32768-costs/report.md)
contains 40 measurements: five alternating-order pairs across four retained
cases. It ran after native work ended, on CPUs 0–7 with one OpenBLAS/OpenMP/MKL
thread and Buck-pinned Python. Every unrelated field is asserted byte-identical.

| Case | Candidate toe median (ms) | Current toe median (ms) | Candidate complete preparation (ms) | Current complete preparation (ms) |
|---|---:|---:|---:|---:|
| Reset | 36.523 | 669.592 | 224.279 | 860.029 |
| All active | 36.312 | 669.420 | 220.823 | 857.788 |
| Alternating extremes | 36.313 | 666.573 | 229.459 | 862.516 |
| All families, active tail | 36.180 | 666.649 | 228.279 | 860.852 |

The toe payload falls from 8,389,632 to 524,352 bytes (8,193 × 4 RGBA32F texels).
This saves 7,865,280 bytes, or 93.75% of the toe payload. Total resident payload
would fall from 33,325,744 to 25,460,464 bytes. Toe generation is about 18.4×
faster and complete preparation about 3.8× faster in this paired run. Isolated
and complete timings are independent and must not be added. Native image
upload/packing, graph construction, render and interaction are outside scope.
Runtime still uses 524,288 toe cells; these reports use explicit process-local
candidate overrides.

The [full candidate texture breakdown](../../../../buck-out/persistent-grade-evidence/preparation-costs-toe-32768/report.md)
measures every resident field under the same 32,768-cell process-local override:

| Texture | Cells | Width × height | Candidate RGBA32F bytes |
|---|---:|---:|---:|
| Tone | 512 | 512 × 2 | 16,384 |
| Color coefficients | 131,072 | 8,193 × 32 | 4,194,816 |
| Web parameters | 32,768 | 8,193 × 128 | 16,779,264 |
| Web toes | 32,768 | 8,193 × 4 | 524,352 |
| Compact Adaptance | 16,384 | 8,193 × 2 | 262,176 |
| Interior Adaptance | 65,536 | 8,193 × 8 | 1,048,704 |
| Output boundary | Fixed | 513 × 321 | 2,634,768 |

The candidate total is 25,460,464 bytes (24.281 MiB), versus 33,325,744 bytes
(31.782 MiB) at the checked-in layout. The full breakdown's all-field generation
medians for the four cases are: Color coefficients `66.996–73.167` ms, Web
parameters `95.118–97.502` ms, Web toes `36.239–36.616` ms, compact Adaptance
`4.270–4.384` ms and interior Adaptance `7.902–8.104` ms. Tone is `0.947–1.244`
ms. Complete preparation is `224.870–231.119` ms. The report retains all 20
measurements, settings, phase timings, payload shapes and source identities;
its JSON SHA-256 is `ece0733a2c3f9f6dee48a5a418b1adcddbc5465e304febe2f134d77fdcdf9a11`.

Receipt SHA-256 values (also retained in the rerun manifest):

- Smaller-grid scalar sweep: `816e0311f4357d4cc52ec9552d5d34a6f4e8cc245de22f7a3a4814689d0e9b22`.
- Combined scalar policy receipt: `6aea09742a589de39c1a96ed0e1f62881ac0c5682c90f10cbc33dc87ebcc0699`.
- Native candidate report: `a87cdc2e24ad9b3a62e930bd0232cedbaa6c99f2af1e78090d287680ff66e564`.
- Paired preparation timing: `7d3a2a5e1cfcabd8b0dfe3f705f7737c3b2353260634588acc4353741dccffb2`.

## Case-specific Web-parameter sizing study

The executable development policy in [gate_policy.py](tools/gate_policy.py)
applies `1e-4` to both conditioned and absolute radial-log parameter error,
both conditioned and relative toe error, and native Web H/opponent/energy and
returned-scale accuracy for the exact alternating-extreme Web case. It also
recognizes the equivalent uniform 0°/±360° seam rotations. Compound Color
controls and other Web settings retain the original limits. The extreme
midpoint log-scale assertion uses the same budget. Terms, Adaptance, final
scale multiplication, sign, saturation, finiteness, validity, alpha, final RGB,
boundary containment and node-budget checks remain unchanged.

The scalar error here is the absolute error in the natural logarithm of a
radial gain coefficient, at the represented float32 lookup coordinate. It is
not PQ signal error. Before subsequent operations, a `1e-4` log error gives a
gain ratio within `exp(±1e-4)`, approximately 0.01% relative gain error. The
independent native checks measure the resulting state and returned scale.

The [complete scalar sweep](../../../../buck-out/persistent-grade-evidence/web-parameters-limit-1e4/report.json)
and [combined receipt](../../../../buck-out/persistent-grade-evidence/web-parameters-limit-1e4/acceptance.json)
cover all 19 distinct parameter functions in the retained 149-case corpus.
The other 18 functions pass their original gates even at 2,048 cells.

| Parameter cells | Extreme conditioned error | Extreme absolute log error | Both ≤ 1e-4 |
|---:|---:|---:|---|
| 32,768 | `3.4985e-7` | `1.4407e-6` | Pass |
| 16,384 | `9.7425e-7` | `5.5334e-6` | Pass |
| 8,192 | `3.4692e-6` | `2.2129e-5` | Pass |
| 4,096 | `1.3184e-5` | `8.6731e-5` | Pass |
| 2,048 | `4.4678e-5` | `3.2860e-4` | Fail |

The [combined native diagnostic](../../../../buck-out/persistent-grade-evidence/web-parameters-native-local/README.md)
compares current, 4,096/32,768 and 2,048/32,768 parameter/toe layouts. It covers
36 local comparisons and 18 final comparisons: 1,024-pixel handoffs in three
scene spaces, both CPU contexts, and seam rotations with scalar-witness heights.

| Worst local/seam metric | Parameters 4,096 / toes 32,768 | Parameters 2,048 / toes 32,768 |
|---|---:|---:|
| Conditioned opponent error | `3.2964e-5` | `1.2756e-4` |
| Conditioned energy error | `2.6594e-5` | `9.6949e-5` |
| Relative returned-scale error | `7.2778e-5` | `2.6512e-4` |
| Authorized local gates | Pass | Fail |
| Final RGB checks | Pass | Pass |

The 4,096/32,768 pair passes all 12 local and six final comparisons, with no
validity or saturation changes. Its worst paired final RGB delta is `1.0357e-5`.
The larger handoff corpus also exposes current-layout opponent error `1.5413e-5`
and energy error `1.2054e-5`, above the old local limit but within the authorized
one. This new coverage does not rewrite the historical 256-sample receipts.

The parameter candidate uses 2,097,664 bytes (4,097 × 32 RGBA32F texels), down
from 16,779,264. Combined with the toe candidate, resident payload would be
10,778,864 bytes (10.280 MiB). This establishes the smallest passing tested
supported sizes, not a minimum over arbitrary cell counts or all controls.
Runtime remains 32,768 parameters and 524,288 toes; this task changes development
gate policy, not installed dimensions or full persistent/GPU candidate acceptance.

The scalar and native studies completed with stable sources before the policy
implementation. Their original source identities are preserved. The policy-aware
tools now force complete audits for exceptional rows, refuse partial acceptance,
split deduplicated functions across distinct policies, and report effective limits.
The legacy generic `audit_color(select=True)` search retains its strict defaults.

Receipt SHA-256 values:

- Parameter sweep: `c5b4350c5fee01cb5a6b2c6326eceb89baa1a931e2d1c9067b00dcbe45db6083`.
- Combined 19-function receipt: `e797f352daa8fc20c0ee0e711dd066a2a7aa98ae78965d13e6b36f48cd3eecd6`.
- Native local/final diagnostic: `bbbf03715dac8b15a2d17c1350850fbc59513a1b1a25f4b46fc2f303bf038a2c`.

After implementation, the policy-aware [149-case parameter audit](../../../../buck-out/persistent-grade-evidence/web-policy-parameter-audit/report.json)
again selects 4,096 and rejects 2,048, with stable sources and all 19 functions
checked. Its SHA-256 is `cd7a65b84e52139915ff53dd12696d04f1837bfc7f2e9824c8c94d2e3cafb8f9`.
The [combined candidate timing](../../../../buck-out/persistent-grade-evidence/preparation-costs-web-4096-toe-32768/report.md)
measures 11.526 ms Web parameters, 35.905 ms toes and 132.149 ms complete
preparation for all-active controls; across four cases complete preparation is
132.149–150.108 ms. It contains 20 uncontended measurements, all resident fields,
stable source identities and process-local overrides. Its SHA-256 is
`a31818267fb7cd31c72a52ba71327d6e0a567ff05b11daa781282cfaa0c297c0`.
