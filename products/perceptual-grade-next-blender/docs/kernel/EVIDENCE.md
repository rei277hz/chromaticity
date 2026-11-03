# Audit follow-up and fixed-field cost rerun — 2026-10-30

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

## Historical schema-4 sensitivity and generation study

This section retains the preceding schema-4 source/layout identities. Its
preparation and software-GPU edit times do not measure schema 5.

The schema-4 Compact-only baseline used Tone 512, Color 16,384, Web
parameters 4,096, toes 1,536, Compact 8,192 and boundary 513 × 321. Payload is
**5,428,848 RGBA32F bytes** (2,794,080 without boundary); there is no Interior
image. Each candidate changes one current field only. The runtime promotes none.

The full **149-case × 1,024-input × three-space × two-context CPU corpus** has
**894 baseline + 10,728 candidate rows**, independently reconciled by
**75,983,224 assertions** over retained arrays, reference/HDR processors,
source identities, actual dimensions/bytes, final RGB and semantic flags.
Candidate generation is the fresh all-active pure-generation median.

| Texture | Current → reduced | Candidate bytes | Saved bytes | Pure generation median | Max added HDR codes | Max added % reference peak | Final RGB failed rows |
|---|---|---:|---:|---:|---:|---:|---:|
| Tone | 512 → 256 | 4,112 | 12,272 | 0.791 ms | 0.0172103494 | 0.00848011155% | 0 |
| Tone | 512 → 128 | 2,064 | 14,320 | 0.691 ms | 0.0241768062 | 0.155205109% | 0 |
| Color coefficients | 16,384 → 8,192 | 262,176 | 262,176 | 4.191 ms | 0.0195181312 | 0.0114327747% | 0 |
| Color coefficients | 16,384 → 4,096 | 131,104 | 393,248 | 2.379 ms | 0.0805258378 | 0.0428828312% | 0 |
| Web parameters | 4,096 → 2,048 | 1,049,088 | 1,048,576 | 6.172 ms | 0.0410032002 | 0.299332338% | 0 |
| Web toes | 1,536 → 1,280 | 20,496 | 4,096 | 1.695 ms | 0.0262652189 | 0.0671117274% | 0 |
| Web toes | 1,536 → 1,024 | 16,400 | 8,192 | 1.415 ms | 0.0643901825 | 0.144407494% | 0 |
| Web toes | 1,536 → 768 | 12,304 | 12,288 | 1.129 ms | 0.132499874 | 0.341672703% | 4 |
| Compact Adaptance | 8,192 → 4,096 | 65,552 | 65,536 | 1.259 ms | 0.00694359094 | 0.000999819409% | 0 |
| Compact Adaptance | 8,192 → 2,048 | 32,784 | 98,304 | 0.775 ms | 0.0243597329 | 0.00721933915% | 0 |
| Output boundary | 513 × 321 → 257 × 161 | 662,032 | 1,972,736 | Shared resource | 0.142031591 | 0.0205077539% | 2 |
| Output boundary | 513 × 321 → 129 × 81 | 167,184 | 2,467,584 | Shared resource | 0.267553098 | 0.0348158859% | 6 |

All current CPU baseline rows pass final RGB. Toe 768 introduces **four** failed rows at alternating Web extremes in Rec.2020 and ACEScg, both contexts. Boundary 257 × 161 introduces **two** failed rows at `adaptance_half_1.0` in ACEScg, both contexts. Boundary 129 × 81 introduces **six** failed rows: that case in both ACEScg and Rec.2020, plus `exposure_0_6` in ACEScg, both contexts. All candidate rows remain finite and pass containment/alpha checks, with exactly zero validity/saturation flag changes.

The reduced Tone tables retain required scalar failures despite passing CPU final RGB: **12 rows at 256 cells** (maximum conditioned field error `1.2040514515e-5`) and **48 rows at 128 cells** (`4.7585139199e-4`), against `1e-5`; both remain monotone. Both reduced boundaries fail their required `2e-5` corrected-radius gate in all 894 CPU rows, with maxima `7.96938434e-5` and `3.46626417e-4`. These scalar values precede Color/view/PQ and are not HDR code errors.

The **0.05-code value is a diagnostic comparison in this study**. Tone, Web parameters and boundary retain their own scalar/local requirements. Existing Color, toe and Compact admission policies—including their explicitly frozen historical baselines—remain unchanged. This report promotes no candidate; runtime sizes stay fixed. Reduced Color-field scalar/local audits are not rerun by this HDR sweep, so absent scalar failures there do not certify scalar accuracy.

HDR compares the reference, current native graph and reduced native graph after the pinned ACES 2.0 HDR-1000 Rec.2020 view with Rec.2100-PQ applied once, yielding fractional full-range 10-bit RGB codes. Signed added error is the per-pixel peak absolute candidate/reference error minus the current/reference error. Percent divides by the reference pixel peak, excluding denominators below one code. Code and percentage maxima can select different pixels. Movement and absolute reference error remain separate metrics.

The software-GPU subset contains **17 selected controls × 1,024 inputs × three spaces × both contexts**, including representative/extreme controls and every CPU added-code/percentage worst-case control. It has **102 current-baseline and 1,224 candidate rows**, independently reconciled by **8,989,366 assertions**. Shader uses llvmpipe/EEVEE; Compositor uses FULL GPU precision. This subset does not establish full 149-case GPU coverage.

The **current-size GPU baseline already fails six final-RGB rows**, all at `web_alternating_extremes`, across all three spaces and both contexts. Its maximum absolute reference error is **337.422683787852 codes** on the nearly neutral ACEScg Compositor input `(0.180000007, 0.180000007, 0.180000097)`: reference scene-linear RGB is about `4.46e-6`, while native RGB is about `0.18`. The reference pixel peak is only `0.000866371` code, so its percentage is excluded by the below-one-code denominator rule; its absolute error remains reported. Small added errors below describe changes relative to this already failing baseline.

Both reduced boundaries introduce additional GPU final-RGB failures: **two** for 257 × 161 and **four** for 129 × 81. Every other candidate adds **zero** failed rows, while retaining the same six baseline failures. No candidate recovers a baseline failure. Every row remains finite and passes alpha/containment checks, with exactly zero validity/saturation flag changes. Passing independent reconciliation verifies these measurements; the retained numerical failures remain open.

| Texture | Current → reduced | Max added HDR codes | Max added % reference peak | Final RGB failed rows | Additional failed rows |
|---|---|---:|---:|---:|---:|
| Tone | 512 → 256 | 0.0303963125 | 0.00450657654% | 6 | 0 |
| Tone | 512 → 128 | 0.0244207084 | 0.14374937% | 6 | 0 |
| Color coefficients | 16,384 → 8,192 | 0.0497331843 | 0.00681642963% | 6 | 0 |
| Color coefficients | 16,384 → 4,096 | 0.0715929195 | 0.0387224933% | 6 | 0 |
| Web parameters | 4,096 → 2,048 | 0.0410127277 | 0.299400817% | 6 | 0 |
| Web toes | 1,536 → 1,280 | 0.026249975 | 0.0671690117% | 6 | 0 |
| Web toes | 1,536 → 1,024 | 0.0640853047 | 0.144523831% | 6 | 0 |
| Web toes | 1,536 → 768 | 0.132377923 | 0.342014868% | 6 | 0 |
| Compact Adaptance | 8,192 → 4,096 | 0.00587651879 | 0.00223647398% | 6 | 0 |
| Compact Adaptance | 8,192 → 2,048 | 0.0236280262 | 0.00700248792% | 6 | 0 |
| Output boundary | 513 × 321 → 257 × 161 | 0.301310688 | 0.0393333101% | 8 | 2 |
| Output boundary | 513 × 321 → 129 × 81 | 0.311112508 | 0.0406128466% | 10 | 4 |

Fresh pure-generation timing is uncontended, with OpenBLAS/OMP fixed to one thread: **four cases × five repetitions, 300 component samples**, source identities stable and runtime layout unchanged. Tone times `_build_table`; Color fields time `_generate_field`. Parameter preparation, dense scalar audits, hashing, native upload and grading are excluded. The table uses all-active medians; JSON also retains per-case minima/maxima and worst-case medians. Color 16,384 has a worst-case median of **9.114 ms**, with one sample reaching **10.049 ms**. Boundary rows report exact resident bytes only; offline geometry generation is not UI preparation. Independent generation reconciliation passes **2,949 assertions**, including 60 payload hash replays and isolation-order checks.

Complete all-active host preparation remains the separately measured **37.885 ms** from the source-matching current Compact-only receipt. Its retained Tone component of **1.180 ms** includes parameter preparation plus table generation, unlike the fresh pure-generation column. Component medians must not be added to estimate complete preparation. Boundary first host loading took **34.488 ms**, then its data are reused. This is resource loading rather than per-edit generation.

The unchanged-runtime prepared-edit receipt is still **16² software GPU**,
with 254 requested logical CPUs, two repeated updates per edit/context.
Exposure end-to-end is **470.200 ms Shader / 93.847 ms Compositor**; these
include fixture evaluation/transport and do not isolate Grade-only frame cost
or full-resolution preview latency. The graph retains 1,445 / 1,382 nodes,
above its original cap. Next integration remains separate.

Receipts: [combined breakdown](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/breakdown.md),
[CPU reconciliation](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/independent-validation.md),
[GPU reconciliation](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/independent-gpu-validation.md),
[GPU failure witness](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/independent-gpu-failure-comparison.json),
[pure-generation costs](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/generation-costs/report.md),
[timing identity retention](../../../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/timing-retention.json).

## Historical schema-4 Compact-only Adaptance implementation and evaluation

The user explicitly requested the Compact representation for every Adaptance
adjustment. The active change removes the Interior field, its preparation and
both graph builders' representation choices, retaining Compact at **8,192
cells**. Reference equations and authored controls are unchanged. Layout
schema 4 requires rebuilding preceding persistent trees and rejects old
preparation reuse.

The following fixed inventory is checked against image dimensions. Byte
counts do not establish preparation or rendering time:

| Compact-only field | Cells | Width × height | RGBA32F bytes |
|---|---:|---|---:|
| Tone | 512 | 512 × 2 | 16,384 |
| Color coefficients | 16,384 | 8,193 × 4 | 524,352 |
| Web parameters | 4,096 | 4,097 × 32 | 2,097,664 |
| Web toes | 1,536 | 1,537 × 1 | 24,592 |
| Compact Adaptance | 8,192 | 8,193 × 1 | 131,088 |
| Output boundary | Fixed | 513 × 321 | 2,634,768 |
| **Total** | | | **5,428,848** |
| **Without fixed boundary** | | | **2,794,080** |

Removing Interior saves **1,048,704 bytes (16.19%)** against the preceding
6,477,552-byte inventory. It does not establish generation or evaluation
savings by subtraction. The runtime change, regression, independently
validated full matched CPU comparison, targeted software-GPU strong-control
evaluation and uncontended preparation/edit timing are complete. The existing
0.05-code Compact HDR admission rule applies, with raw
scalar/local errors retained as diagnostics and safety, final RGB, containment
and semantic flags still required. Evidence is recorded under
`buck-out/persistent-grade-evidence/compact-only-adaptance-20261030`.

The CPU comparison contains **894 matched case/space/context rows**: 149 cases
× 1,024 inputs × three spaces × Shader/Compositor CPU, using prepared-tree
updates. The preceding implementation was frozen before changes and remains
the explicit dual-table baseline. All required output/safety gates pass for
both paths, with zero validity/saturation flag changes.

| Current comparison | Maximum added HDR codes | Maximum added error (% reference peak) |
|---|---:|---:|
| Frozen dual table → always Compact 8,192 | 0.0000304877758026 | 0.0000156437480543% |

The [independent validator](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/independent-validation.md)
passes **32,668,186 assertions**, reconstructs all 894 paired rows and replays
447 independent float64 oracle outputs. It checks raw per-channel errors,
signed worsening, reference-peak percentages, witnesses, alpha, semantic flags,
final RGB and containment, plus frozen/current sources, boundary resource,
native harness and archives. Maximum HDR movement is **0.0000914633274078
codes**, distinct from the smaller signed worsening above.

The maximum added error occurs in the saturation case, Linear Rec.709 Shader.
The maximum absolute reference error remains **7.985666599444812 codes** in
both baseline and current path, at the inherited `source_boundary_0` ACEScg
Shader witness. Added error is distinct from absolute error; code/percentage
maxima can select different pixels. Percentage denominators below one
reference code remain excluded. These accuracy-job durations are not timing
evidence.

The separate [software-GPU strong-control comparison](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/hdr-software-gpu/)
contains **36 matched rows**, all passing, on Mesa 25.0.7 llvmpipe / LLVM
19.1.7, Eevee Shader and full-precision GPU Compositor. It adds at most
**0.0000304877758026 HDR codes / 0.0000208583307391% reference peak** and changes
no validity/saturation flags. Code and percentage maxima can occur at
different pixels. This targeted strong-control check does not replace the
retained extreme-Web software-GPU finding or claim a new full GPU corpus.

The current [regression receipt](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/test-summary.json)
passes all **90 tests across eight Buck2 targets**. Both native local-stage
suites retain 12 raw Compact precision-failure rows each under the existing
diagnostic policy. Their worst normalized H/opponent/energy errors are
`5.18723906e-4` / `1.34718606e-4` / `1.19917385e-3`; required precision, sign
and safety checks pass. The complete [fixed scalar audit](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/scalar-fixed/report.json)
covers Color 78 functions (two raw failures), Web parameters 19 (all pass),
toes 16 (all 16 raw failures), Compact 11 (all pass), and Tone 32 (all pass).
Color/toe/Compact raw precision remains diagnostic within the authorized role
scope, not a claim that every scalar/local gate passes.

Resident images fall from seven to **six**. Expanded nodes fall from
1,468 Shader / 1,399 Compositor to **1,445 / 1,382**. The original `<1000`
cap remains unmet; this change introduces no new node-budget failure.

The source-stable [preparation report](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/preparation-costs/report.md)
has 20 uncontended complete preparations over four cases × five repetitions.
All-active generation and complete preparation are measured separately; they
must not be added. These host timings exclude native construction, image
upload and rendering. Boundary data are loaded once and reused.

| Field | All-active generation median (ms) | Four-case median range (ms) |
|---|---:|---:|
| Tone | 1.180 | 0.918–1.180 |
| Color coefficients | 8.135 | 8.135–9.094 |
| Web parameters | 13.782 | 11.438–13.782 |
| Web toes | 2.014 | 1.992–2.014 |
| Compact Adaptance | 2.225 | 2.221–2.230 |
| Output boundary | cached; first load 34.488 | loaded once |
| **Complete preparation** | **37.885** | **36.121–38.266** |

All-active Linear preparation is 0.495 ms and Color-parameter preparation is
9.318 ms in their separate phase measurements. Color generation medians
remain below 10 ms, but its maximum individual sample is **10.190 ms**; this
is a median result, not an every-sample bound.

The source-stable [prepared-edit timing report](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/prepared-edit-costs/report.md)
has 30 rows at **16 × 16 pixels**, one scenario entry and two repeated edits
per family/context, requesting all **254** available logical CPUs. Shader
uses Eevee on llvmpipe; Compositor uses full-precision software-GPU evaluation.
The following phase medians come from JSON `repeated_updates`, excluding entry:

| Context / edit | Prepare (ms) | Apply wall (ms) | Fixture evaluation (ms) | Readback (ms) | End-to-end (ms) |
|---|---:|---:|---:|---:|---:|
| Shader Exposure | 0.695 | 25.973 | 436.964 | 6.560 | 470.200 |
| Shader Tone fit | 1.496 | 15.181 | 439.952 | 6.988 | 463.626 |
| Shader Web chroma | 17.098 | 10.378 | 435.519 | 6.532 | 469.534 |
| Shader Web scale | 16.562 | 10.563 | 435.957 | 6.583 | 469.672 |
| Shader all-active Exposure | 0.731 | 24.893 | 484.249 | 6.875 | 516.755 |
| Compositor Exposure | 0.664 | 24.710 | 65.413 | 3.055 | 93.847 |
| Compositor Tone fit | 1.271 | 14.939 | 74.831 | 3.065 | 94.111 |
| Compositor Web chroma | 18.540 | 9.525 | 64.711 | 3.405 | 96.187 |
| Compositor Web scale | 17.133 | 9.859 | 73.425 | 3.688 | 104.111 |
| Compositor all-active Exposure | 0.857 | 24.667 | 84.829 | 4.032 | 114.391 |

End-to-end and each phase are separately measured; phase medians must not be
added. Fixture evaluation includes render/EXR work, with EXR readback separate.
Scenario entry remains separate: all-active entry is 3.895 s Shader / 4.042 s
Compositor. It follows the preceding scenario and is not necessarily first
activation. Initialization, GUI scheduling, preview upload/draw and physical
presentation are excluded. This fixture does not isolate Grade-only per-frame
render cost, nor does it refresh the historical 1,024² preview report.

The [combined breakdown](../../../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/breakdown.md)
collects the current payload, timing and sensitivity scopes. The original node
budget, retained extreme-Web GPU finding and future product integration remain
open separately.

The read-only [switching-plane analysis](../../../../buck-out/persistent-grade-evidence/adaptance-switch-plane-20261030/report.md)
describes the removed selector under default D65/203-nit/1000-nit anchors. It
does not certify Compact-only accuracy. The reference Rec.709 outline there is
the actual UI's free-exposure fixed-source-H contour, not an RGB cube slice.

## Historical completed Color coefficient and Compact Adaptance promotion

This section retains the preceding dual-table layout schema 3, including
Interior Adaptance. Its source-bound receipts do not certify the Compact-only
implementation above; uses of "current" below refer to that completed study.

The checked-in source now uses 16,384 Color coefficient cells and 8,192 Compact
Adaptance cells, with Web parameters/toes at 4,096 / 1,536. Total fixed
RGBA32F payload is **6,477,552 bytes**, down 3,801,552 bytes (37.0%) from the
pre-promotion 10,279,104 bytes. The user authorized these two layouts under the
0.05-code HDR admission rule. Current-source regression, independently validated
persistent CPU HDR and software-GPU prepared-edit timing are complete. All
87 checks across eight Buck2 targets pass. The combined [breakdown](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/breakdown.md)
keeps current measurements distinct from retained historical reports. The
candidate study remains recorded under
[`color-adaptance-sizing-20261030`](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/).

| Current field | Cells | Width × height | RGBA32F bytes |
|---|---:|---|---:|
| Tone | 512 | 512 × 2 | 16,384 |
| Color coefficients | 16,384 | 8,193 × 4 | 524,352 |
| Web parameters | 4,096 | 4,097 × 32 | 2,097,664 |
| Web toes | 1,536 | 1,537 × 1 | 24,592 |
| Compact Adaptance | 8,192 | 8,193 × 1 | 131,088 |
| Interior Adaptance | 65,536 | 8,193 × 8 | 1,048,704 |
| Output boundary | Fixed | 513 × 321 | 2,634,768 |

The layout schema is 3. The promotion's fresh receipts are recorded under
`buck-out/persistent-grade-evidence/color-compact-promotion-20261030`; candidate
and earlier Web-promotion hashes below retain their original source scope.

The fresh source-stable [host-preparation report](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/preparation-costs/report.md)
contains 20 complete preparations over four cases with five repetitions each.
The table gives each field's all-active generation median and the range of its
four case medians. Complete preparation is separately timed and must not be
added to the component times. It excludes graph construction, upload and render;
the first output-boundary load is measured separately.

| Field | All-active median (ms) | Four-case median range (ms) |
|---|---:|---:|
| Tone | 1.191 | 0.919–1.214 |
| Color coefficients | 8.146 | 8.146–9.136 |
| Web parameters | 11.905 | 11.386–11.905 |
| Web toes | 2.025 | 1.997–2.025 |
| Compact Adaptance | 2.232 | 2.217–2.233 |
| Interior Adaptance | 7.945 | 7.847–7.945 |
| Output boundary | cached; first load 34.546 | loaded once |
| **Complete preparation** | **43.838** | **43.838–45.719** |

The current payload is **6,477,552 RGBA32F bytes** as shown in the inventory
above. Color generation medians are below 10 ms in every measured case, but
individual samples reach 11.786 ms in all-active and 10.767 ms for alternating
Web extremes. This finite run supports the median target, not a per-sample or
cross-host time bound. The separate [candidate generation study](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/costs/report.md)
measured `_generate_field` in an isolated harness and observed all 20 Color
16,384 samples below 10 ms; its scope is not interchangeable with the current
full-preparation timing.

The fresh [runtime regression receipt](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/tests/summary.md)
passes all **63 checks across seven Buck2 targets**. It verifies obsolete
Color 131,072 / Compact 16,384 / Web 32,768 / toe 1,280 preparation rejection,
replacement equality to current pixels and exact matching-layout reuse. Both
native Color-stage suites measure 50 local rows and retain four raw
Compact-sampled opponent precision failures each: `adaptance` and `all_active`
in Shader/Compositor, maximum `1.22195872e-5` against `1e-5`. These are authorized
diagnostics. All strict-required precision, sign, finite-output, black and
overflow/saturation checks pass. Thirteen production scalar rows are complete;
one Color Fit-6 absolute interpolation error is `3.02598931e-6` versus `3e-6`,
also diagnostic. The local regression tests isolate toes at 524,288 cells and
do not establish current-layout end-to-end HDR acceptance.

The separate [HDR runner test receipt](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/tests/hdr-report-summary.json)
passes all **24 synthetic tests** for runner, admission and merge behavior.
Neither synthetic tests nor CPU regression durations are timing measurements.

The source-stable [complete fixed-layout scalar audit](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/scalar-fixed/report.json)
traverses every distinct production function: Color 78 (two raw failures),
Web parameters 19 (all pass), Web toes 16 (16 raw failures), Compact Adaptance
11 (all pass), Interior Adaptance 11 (all pass), and Tone 32 (all pass).
Color/toe raw precision failures remain diagnostics under their separately
authorized HDR admission policies. This full audit is distinct from the
13 representative production scalar rows printed by the regression suite.

The current [persistent HDR report](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/hdr-persistent-cpu/report.md)
uses explicit Color 131,072 / Compact 16,384 baselines with Web 4,096 / toe
1,536, all 149 cases, 1,024 inputs, three spaces and both CPU contexts. It has
**894 baselines and 2,682 measured candidate rows**, with no inactive,
generation-failed, render-failed or nonfinite rows. All final-RGB, containment
and unchanged validity/saturation checks pass. The [independent validator](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/hdr-validation.md)
passes 1,204,923 assertions, checks 40 source files, exact native image content,
display transform, sample counts, witnesses and layout-dependent topology.

| Current persistent reduction | Maximum added HDR codes | Maximum added error (% reference peak) | Layout admission |
|---|---:|---:|---|
| Color coefficients: 131,072 → 16,384 | 0.0115159236593 | 0.00529889482163% | Pass |
| Compact Adaptance: 16,384 → 8,192 | 0.00128048658371 | 0.000361764104394% | Pass |
| Combined Color / Compact reduction | 0.0115159236593 | 0.00529889482163% | Pass |

All pass the **0.05-code** layout budget. Maximum absolute reference error is
**7.98566659944 codes** in both baseline and combined candidate; it is separate
from maximum signed worsening. Color and combined retain 18 raw scalar-failure
rows each; Compact has none. Code/percentage maxima can occur at different
pixels; percentage denominators below one reference code are excluded.
The persistent common-control Compact path has nonzero sensitivity; the old
specialized full-field zero movement below was not used for this admission.

The original expanded-node cap remains failed on all 894 baselines and each
candidate set. Baseline and Color-only have **1,475 Shader / 1,406 Compositor**
nodes. Compact and combined remove exactly seven nodes through the
single-segment table, leaving **1,468 / 1,399**, with zero new node-budget
failure rows. The separately recorded software-GPU extreme-Web finding is
unchanged by CPU layout admission.

The fresh [software-GPU prepared-edit diagnostic](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/prepared-edit-costs/report.md)
contains 30 rows at **16 × 16 pixels**, Mesa 25.0.7 llvmpipe with Eevee Shader
and full-precision GPU Compositor, requesting all 254 available logical CPUs.
Each context/family has one entry and two repeated updates. Exposure repeated
end-to-end medians are **433.792 ms Shader / 103.226 ms Compositor**; all-family
ranges are 432.831–499.226 / 85.511–113.567 ms. Entry may activate new branches
and remains separate. Initialization, GUI scheduling, preview upload and
display are excluded. This diagnostic does not isolate Grade-only per-frame
cost or replace the historical 1,024² matching-preview report. The combined
breakdown retains its phase table and exact measurement scope.

The machine [summary](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/summary.json)
and [completion receipt](../../../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/completion.json)
reconcile the current source/resource identities and retained receipt hashes.

### Historical candidate study

The user authorizes maximum signed HDR worsening of **0.05 fractional 10-bit
codes** for these two roles. Scalar and local precision remain diagnostics for
Color coefficients and Compact Adaptance only. Safety, final-RGB, containment,
semantic-flag and node-budget gates remain active; the Web-toe rule is unchanged.
The existing software-GPU extreme-Web finding also remains separate.

The clean [generation-cost report](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/costs/report.md)
has 200 component measurements: six Color grids and four Compact grids across
four cases and five repetitions. It times `_generate_field` only, excluding
parameter preparation, audit, hashing, graph construction, upload and evaluation.
The values below compare layouts measured in that same run:

| Field | Pre-promotion → source cells | Pre-promotion → source bytes | All-active candidate generation median | Worst case candidate median |
|---|---:|---:|---:|---:|
| Color coefficients | 131,072 → 16,384 | 4,194,816 → 524,352 | 66.044 → 8.091 ms | 9.176 ms |
| Compact Adaptance | 16,384 → 8,192 | 262,176 → 131,088 | 4.163 → 2.225 ms | 2.225 ms |

Color 16,384 is the largest tested grid meeting the less-than-10-ms target:
all 20 measurements are below 10 ms, including a 9.957-ms maximum. Color
32,768 has a worst case median of 18.004 ms. The 16,384 candidate image is
8,193 × 4 RGBA32F and saves 87.5% of Color payload. Compact 8,192 is
8,193 × 1 and saves 50%. These finite host measurements do not establish an
execution-time bound on other hosts or a whole-preparation time.

The complete source-stable [Color scalar audit](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/scalar-color/report.json)
traverses all 78 distinct functions at 8,192 and 16,384 cells. At 16,384, two
functions fail: `chroma_fit_6`, and the shared `all_families_max` /
`all_families_max_active_tail` function. Maximum absolute interpolation errors
are `7.55635576e-5` and `3.05880872e-6` against the existing `3e-6` limit;
conditioned errors remain below `1e-5`. Unlike the earlier early-stopped
witness, these are complete diagnostics. The [Compact scalar audit](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/scalar-compact/report.json)
traverses all 11 functions at 2,048 / 4,096 / 8,192 cells. All 11 pass at
8,192; the two smaller grids fail five and three functions respectively.

The source-stable [local-stage rerun](../../../../buck-out/persistent-grade-evidence/color-field-local-20261030-rerun/report.md)
uses identical float32 handoffs, 256 inputs, three spaces and both CPU contexts
over nine cases. Its 54 measured baseline rows all pass; inactive/not-sampled
rows remain explicit. Color 16,384 has 36 measured rows, zero local precision
failures and 18 scalar-fail rows. Color 8,192 has four local failures in
`lightness_fit_6`, so further reducing the table adds a local-stage issue.

Compact 8,192 has **8 local precision failures among 18 measured rows**, despite
passing its scalar gate. This is normalized opponent-state error before the
display transform and PQ encoding, not an HDR code-value error. Its metric is
`hypot(delta_a, delta_b) / (1 + C_input + C_reference)`. It reaches
`1.22195872e-5` against the unchanged raw `1e-5` precision limit: all six
`adaptance` context/space rows fail, along with `all_active`
in Linear Rec.709 for Shader (`1.07903393e-5`) and Compositor
(`1.08831125e-5`). This includes ordinary controls. Compact 4,096 / 2,048 have
10 / 12 local failures and peak opponent errors `4.08600999e-5` /
`1.04668352e-4`. These raw precision failures remain diagnostics under the
authorized 0.05-code HDR admission policy. All local safety, sign, exact-black
and saturation checks pass.

The pre-promotion [matched HDR report](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/hdr-cpu/report.md)
holds Web 4,096 / 1,536 fields fixed while comparing against Color 131,072 /
Compact 16,384. It covers all 149 cases × 1,024 inputs × three spaces
× two CPU contexts: 894 baselines, 534 measured candidate rows and 3,042
inactive candidate rows. All baseline/candidate final-RGB and containment
checks pass; no validity or saturation pixels change. Node-budget failures
remain separate: 15 baseline rows, 15 measured Color rows and nine rows for
each Compact candidate.

| Candidate | Measured / inactive rows | Maximum added HDR codes | Maximum added error (% reference peak) | Scalar-fail rows |
|---|---:|---:|---:|---:|
| Color coefficients / 16,384 | 444 / 450 | 0.0115159237 | 0.00529889482% | 18 |
| Compact Adaptance / 8,192 | 30 / 864 | 0 | 0% | 0 |
| Compact Adaptance / 4,096 | 30 / 864 | 0 | 0% | 6 |
| Compact Adaptance / 2,048 | 30 / 864 | 0 | 0% | 30 |

Added error is the per-pixel signed increase in peak absolute reference error
after the pinned ACES 2.0 HDR-1000 / Rec.2100-PQ view. Codes stay fractional;
percentages exclude reference peaks below one code. Percentage/code maxima
can occur at different pixels. The full-field HDR corpus includes the
interior-Adaptance lookup, which may mask Compact interpolation differences.
Its zero prepared-tree HDR movement does not mean the isolated Compact path
has zero local impact. That path is covered by the ordinary identical-handoff
local rows above. The [historical raw-row reaggregation](../../../../buck-out/persistent-grade-evidence/color-adaptance-sizing-20261030/retained-hdr.md)
separately labels its older Web 32,768 / toe 524,288 scope.

The HDR and local reports in this candidate-study subsection are pre-promotion
evidence and do not certify current-source identities or software-GPU behavior.
The current persistent report above measures Compact's common-control path
and supersedes this specialized report's zero movement for current admission.

Source-stable JSON receipts have SHA-256:

| Receipt | SHA-256 |
|---|---|
| Generation costs | `6c8b10ddbda96260ca96ae1cb60fd9d8341475a1a27c3cc2d741702c34862e7e` |
| Complete Color scalar audit | `6370d0a6acb080bb58fae13d17528acd8082198c79cb0072aa2a3db46a21b213` |
| Complete Compact scalar audit | `539a3976efc7f451b616c1050f3209d0924c4416eeb47ad9cf38a33a19e4fee7` |
| Matched CPU HDR | `97c0f5649e8aadb54f5316d9c7b5fbcbb22452979d9c59a75933014298b6fbd5` |
| Identical-handoff local stages | `323a0e6b7cac2a60f88aaab2345fa11032cd68f8c507bdf66ba1ecf713a8c647` |

<a id="historical-web-parameter-promotion-4096"></a>
<a id="current-web-parameter-promotion-4096"></a>

## Historical Web-parameter promotion baseline: 4,096 parameters / 1,536 toes

The 2026-10-30 Web promotion and its full CPU/software-GPU HDR, focused native
tests and timing refresh were measured with **4,096 Web-parameter cells,
1,536 Web-toe cells, 131,072 Color-coefficient cells and 16,384 Compact
Adaptance cells**. Its full fixed-field payload was **10,279,104 RGBA32F
bytes**. This source scope is historical after the Color/Compact promotion;
those reports do not certify the current 6,477,552-byte source. The receipts
are retained under
[`web-parameters-4096-20261030`](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/).
The combined [texture/time and sensitivity table](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/breakdown.md)
includes each field's payload and generation time, prepared-tree edit phases,
1024² matching-draw latency and every part's retained percentage sensitivity.
The fixed payload is 58.82% smaller than the former 32,768-parameter layout.
Migration checks confirm that preparation reuse rejects obsolete parameter
dimensions and reuses matching current dimensions.

| Field | Cells | Width × height | RGBA32F bytes |
|---|---:|---|---:|
| Tone | 512 | 512 × 2 | 16,384 |
| Color coefficients | 131,072 | 8,193 × 32 | 4,194,816 |
| Web parameters | 4,096 | 4,097 × 32 | 2,097,664 |
| Web toes | 1,536 | 1,537 × 1 | 24,592 |
| Compact Adaptance | 16,384 | 8,193 × 2 | 262,176 |
| Interior Adaptance | 65,536 | 8,193 × 8 | 1,048,704 |
| Output boundary | Fixed | 513 × 321 | 2,634,768 |

The complete matched HDR report uses an explicit 32,768-parameter / 1,536-toe
baseline and the 4,096-parameter / 1,536-toe runtime candidate. It covers all
149 cases, 1,024 inputs, three scene spaces and both contexts: 894 baselines and
894 candidate rows per backend, with 90 measured and 804 explicitly inactive
candidate rows. All evaluator, reference, resource and HDR-tool hashes match;
all measured native candidate images match the audited 4,097 × 32 RGBA32F image.
The independent [HDR validator](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/hdr-validation.json)
checks exact coverage, sources, dimensions, texture contents and separate gate
counts. Its [summary](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/hdr-summary.md)
reports signed worsening relative to the explicit baseline:

| Backend | Context | Maximum added error (codes) | Maximum added error (% reference peak) | Final RGB failures | Scalar failures |
|---|---|---:|---:|---:|---:|
| CPU | Shader | 0.0237575993 | 0.122978849% | 0 | 0 |
| CPU | Compositor | 0.0404496565 | 0.122978849% | 0 | 0 |
| Software GPU | Shader | 0.00675304234 | 0.122460364% | 3 | 0 |
| Software GPU | Compositor | 0.00974084437 | 0.122460364% | 3 | 0 |

The code and percentage maxima can occur at different pixels. Percentages
exclude reference peaks below one code. The fixed view is ACES 2.0 HDR 1000 nits
on Rec.2100-PQ; the view performs PQ encoding once, and reported code values
remain fractional and unclipped.

CPU baseline and candidate rows all pass scene-linear/final-RGB and containment
checks. Software GPU retains six baseline and six candidate final-RGB failures,
all in `web_alternating_extremes` across the three spaces and two contexts. The
near-neutral witness is unchanged by the reduced parameter image; maximum
software-GPU baseline error is 337.422684 codes. These rows also exceed the
existing normalized scene-linear limit. The reduced field has zero scalar
failures on the measured HDR corpus for both backends; neither validity nor
saturation flags change, and no containment failures occur. The inherited
expanded-node budget fails on 21 baseline and 15 candidate rows for both
backends. A complete report with no generation/render/nonfinite failures is not
the same as a numerical pass.

The migration, scalar, full-grade, persistent lifecycle and persistent Color
stage regressions pass **78 checks across nine Buck2 targets**. The complete
[test receipt](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/tests.json)
shows each target and the two long-running persistent suites' successful reruns.
The inherited full-grade expanded-node cap remains open.

The clean [timing aggregate](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/timings/aggregate.md)
uses software Eevee for Shader, the full-precision GPU Compositor and Mesa
25.0.7 llvmpipe. All 254 available logical CPUs are requested; Mesa caps each
llvmpipe pool at 32 workers. The 1024² GUI corpus records 960 matching draws,
120 superseded occurrences and no missing draws. Its numerical gate still
fails on the same 60 `web_stress` probes, with maximum normalized error
`0.000193902526` against `1e-4`. Persistent graphs retain 10,279,104 texture
bytes and contain 1,475 / 1,406 expanded Shader / Compositor nodes. Exposure
edit-to-draw p50 / p95 is 738 / 768 ms Shader and 229 / 243 ms Compositor.

The clean 16² prepared-edit report has 30 rows. Repeated Exposure end-to-end
medians are 474 ms Shader and 91 ms Compositor; repeated Web chroma edits are
459 ms and 86 ms. The 1024² full-grade image benchmark records 18 processes and
144 renders, with warm render medians of 841 ms Shader and 488 ms Compositor.
The Shader full graph remains over budget at 1,002 nodes; Compositor has 947.
These specialized fixture times and the interactive GUI draw measurements are
different workflows.

The host-only [preparation report](../../../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/timings/preparation-costs/report.md)
has 20 measurements across four cases and five repetitions. Web parameter
generation is 11.65–12.09 ms (11.84 ms all-active), versus 96.09 ms previously.
Complete all-active preparation is 102.35 ms, versus 184.76 ms previously.
Component generation and whole-preparation medians are separately measured and
must not be added. The full RGBA32F payload is 10,279,104 bytes (9.803 MiB),
down 14,681,600 bytes (58.82%).

All 32,768-parameter timing and acceptance receipts below retain their
historical source/layout scope. Their historical source-match statements are
not claims that those hashes match the promoted runtime. The old software-GPU
extreme-Web failures remain open, alongside the original full-grade node cap
and deferred Next integration.

<a id="latest-software-gpu-timing-rerun-2026-10-30"></a>

## Historical software-GPU timing rerun (2026-10-30; 32,768 parameters)

The [validated aggregate](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/aggregate.md) and [raw aggregate](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/aggregate.json)
record a completed rerun using pinned Blender 5.2.2, Mesa 25.0.7 llvmpipe
(LLVM 19.1.7), OpenGL 4.5 and the Buck2-pinned software-Xvfb fixture. Shader
uses Eevee; Compositor uses the full-precision GPU Compositor. All 254 available
logical CPUs remain in process affinity. Blender's fixed render thread count,
`OMP_NUM_THREADS` and `LP_NUM_THREADS` are requested at 254; Mesa caps each
llvmpipe raster/compute pool at 32 and the native reports observe 32 raster
workers. Process thread counts do not establish 254-way GPU execution.
OpenBLAS stays single-threaded. The host-only preparation rerun also uses one
OpenMP thread. Runtime equations, helper layouts and product integration did
not change during that run; no dependency was added, and existing libraries/tools
remain pinned by Buck2.

The [sequential launcher](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/launcher.json) records successful exit code 0
for the prepared-edit, image benchmark and preparation phases, after the GUI
run completed. All four report families have stable source identities. The
aggregate validated the GUI's 45 source/resource identities against the files
at that run; each prepared-edit, benchmark and host-preparation receipt also
matched all 25 evaluator, ten reference and one generated-resource hash at
that point. Native thread settings and software-renderer worker environments are
checked, along with resident texture bytes. The 20 host-preparation rows retain
the historical 32,768-parameter / 1,536-toe layouts and 24,960,704-byte payload.
Seven evidence-local positive/negative checks accept the actual receipts and reject altered source
hashes, thread settings, worker environments or texture bytes.
Complete timing coverage does **not** imply numerical
acceptance: 60 of 960 GUI probe comparisons fail, all in `web_stress`, at a
maximum normalized scene-linear error of `0.000193902526` against `1e-4`.
The other 900 comparisons pass.

The separate [same-input Web-stress diagnostic](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/report.md)
and [raw diagnostic](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/report.json)
reproduce GUI `web_stress` index 0 with identical controls, source hashes and
1,048,576 input pixels. Both fixtures use the **Cycles scene engine** and an
image-only native Compositor graph; only the Compositor device changes. This
comparison uses no Eevee, rendered scene geometry or Color AOV transport.
The original toe layout is an evidence-only override.

| Compositor device | Web toe cells | GUI 32-probe maximum | Full-image unmasked maximum | Pixels above `1e-4` |
|---|---:|---:|---:|---:|
| CPU | 1,536 | `9.597194349e-5` | `0.0300431291` | 760 |
| GPU | 1,536 | `0.000193317162` | `0.1799923519` | 3,605 |
| CPU | 524,288 | `9.597194349e-5` | `0.0300431291` | 694 |
| GPU | 524,288 | `0.000193317162` | `0.1799923519` | 3,537 |

Errors here are per-pixel `max(abs(native-reference)) / (1 + max(abs(reference)))`
in scene-linear RGB, **not HDR/PQ code values**. The GPU Compositor reproduces
the GUI probe failure without Eevee or AOV transport. CPU passes those 32
probes, while the exploratory unmasked scan exposes larger CPU errors that
the GUI probes miss. Restoring the original 524,288-cell toe leaves the GUI
and full-image maxima unchanged but changes the counts above the threshold;
the reduced toe does not cause these particular maxima.

GPU's maximum is pixel 210, input
`[0.18000000715255737, 0.18000000715255737, 0.18000009655952454]`:
native RGB is `[0.1800002157688141, 0.18000023066997528, 0.18000023066997528]`,
versus reference `[6.67695265657454e-6, 6.676952656574523e-6, 6.676956826379873e-6]`.
CPU's unmasked maximum is pixel 9,478, input
`[126.13583374023438, 142.6147918701172, 87.88966369628906]`:
native RGB is `[45.86500549316406, 97.63179016113281, -13.385369300842285]`,
versus reference `[44.5603204392352, 94.75501003272281, -12.992334130560423]`.
Both worst native witnesses report valid output and positive pole margins,
approximately 394.86 GPU and 342.18 CPU.

The independent [35-witness reference review](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/reference-review.json)
checks all 32 GUI probes plus the full-image normalized/absolute worst pixels.
Every reviewed reference is valid and well-conditioned, including both maxima;
the corresponding reference margins are 399.9283 and 342.7952. Scalar and
small-batch evaluations reproduce the retained chunked reference with maximum
absolute differences `2.58922e-9` and `2.67619e-9`. File output, Viewer and NumPy
reconstruction agree exactly in all four native rows. These checks confirm
the reported witnesses but do not provide a full-image validity-mask audit or
new numerical admission. The timed GUI retains only its 32 reference probes
per draw. The exact failing arithmetic operation and the separate Eevee
Shader path remain unlocalized by this diagnostic.

### Initialized 1024² Grade edit through matching displayed preview

The [GUI report](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/gui-1024-final/report.md) and
[complete GUI receipt](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/gui-1024-final/report.json) cover three fresh
sessions per context and all 16 scenarios. There are 1,080 accepted occurrences:
960 receive matching revision/token, native output and an actual preview draw;
120 burst occurrences are explicitly superseded; none are missing. Each
scenario/context has 30 matching draws. The table reports **milliseconds,
p50 / p95**, for the 27 repeated draws per scenario/context, excluding the
three scenario-entry draws. The burst row counts only its final accepted
occurrence; its other acceptances remain recorded as superseded. p95 uses
nearest rank and these descriptive quantiles impose no latency threshold.

| Scenario | Eevee Shader, repeated p50 / p95 (ms) | GPU Compositor, repeated p50 / p95 (ms) |
|---|---:|---:|
| Reset | 649.5 / 689.5 | 170.6 / 177.9 |
| Exposure | 693.3 / 748.3 | 205.7 / 220.0 |
| Tone fit | 706.4 / 751.6 | 306.1 / 315.3 |
| Lightness | 779.6 / 801.8 | 325.0 / 342.9 |
| Chroma | 784.6 / 804.6 | 324.0 / 352.1 |
| Global gain | 714.6 / 733.0 | 219.2 / 229.5 |
| Web chroma | 813.7 / 843.3 | 400.0 / 418.8 |
| Web hue | 811.2 / 847.2 | 399.5 / 412.3 |
| Web scale | 811.5 / 838.6 | 420.6 / 448.9 |
| Adaptance | 729.3 / 747.7 | 300.0 / 309.5 |
| All-active exposure | 744.3 / 778.7 | 442.3 / 465.3 |
| All-active Color | 752.6 / 782.6 | 444.7 / 458.6 |
| Alternating Web stress | 816.9 / 842.6 | 427.7 / 438.3 |
| Reset ↔ active | 2163.5 / 2324.9 | 2128.3 / 3514.3 |
| A → B → A exposure | 695.8 / 721.4 | 207.6 / 216.8 |
| Burst exposure | 704.9 / 743.4 | 209.6 / 224.4 |

These intervals begin when a setting is accepted and include immutable
preparation, native image/binding publication, synchronous native render,
in-memory Viewer readback, preview texture upload and the first matching
`POST_PIXEL` framebuffer draw. Independent reference probe generation happens
before acceptance; its comparison and pixel hashing occur during readback.
Shader's split high/residual/exponent AOVs are reconstructed in the
full-precision Compositor before Viewer and their cost is included. No EXR
files are written in the GUI timing path. The evaluated image is 1024 × 1024;
the preview is 777 × 777 in a 1280 × 960 Blender window. The experiment covers
the standalone synthetic displayed preview, with Next UI scheduling,
automatic Shader viewport updates and physical frame presentation outside its
scope.

Scenario entry follows the preceding scenario and can include activation or
rewiring. First activation is tracked separately for each actually active
family, once per session, and reuses the prebuilt graph/images. Its three-sample
p50 / p95 values are:

| First active family | Eevee Shader (ms) | GPU Compositor (ms) |
|---|---:|---:|
| Linear (Exposure) | 697.6 / 700.2 | 210.0 / 216.3 |
| Tone | 1495.5 / 1598.7 | 1754.9 / 2550.4 |
| Lightness | 2034.6 / 2768.0 | 2657.1 / 2703.2 |
| Chroma | 958.4 / 961.7 | 1195.9 / 1221.1 |
| Global gain | 824.5 / 832.8 | 558.9 / 581.8 |
| Web chroma | 1796.5 / 2041.4 | 2442.2 / 2497.3 |
| Web hue | 1492.0 / 1664.5 | 1788.3 / 2483.5 |
| Web scale | 1379.4 / 1482.3 | 1435.8 / 1702.6 |
| Adaptance | 1443.4 / 1560.7 | 2189.1 / 2390.0 |

Combined transitions have their own scenario entries: all-active Exposure
p50 / p95 is 2,328.9 / 2,606.4 ms Shader and 4,580.3 / 4,740.2 ms Compositor;
Web stress is 2,010.9 / 2,118.8 ms and 2,774.8 / 2,878.5 ms. They do not define
another first activation of already visited families. Reset ↔ active continues
to include rewiring on repeated rows. Initialization remains outside every
accepted-setting interval:

| Context | Fixed preparation (ms) | Scene/input (ms) | Grade graph (ms) | Cold evaluation → draw (ms) | Total initialization (ms) |
|---|---:|---:|---:|---:|---:|
| Shader | 210.2 / 213.0 | 84.7 / 88.2 | 21204.9 / 23428.7 | 1237.8 / 1247.9 | 23578.6 / 25815.0 |
| Compositor | 209.1 / 213.6 | 86.0 / 86.1 | 26607.7 / 26664.0 | 365.4 / 366.0 | 28032.7 / 28099.7 |

On all 30 Exposure rows, including entry, preparation/native-install/native-
evaluation/Viewer-readback/preview-upload/draw medians are
0.580 / 27.806 / 561.766 / 17.726 / 25.846 / 4.146 ms Shader and
0.567 / 25.973 / 84.823 / 18.421 / 27.742 / 3.391 ms Compositor. They are
independent phase medians and must not be added to reconstruct the end-to-end
median. Exposure reuses helper images; it updates bindings and triggers a
complete fixture evaluation. This explains why sub-millisecond host
preparation does not yield a sub-100 ms matching displayed preview here.
The resident persistent graphs contain 1,492 / 1,423 expanded Shader/Compositor
nodes and 32 / 16 texture nodes, retaining 24,960,704 pixel bytes each. The
original `<1000` expanded-node requirement remains open.

### Prepared persistent-tree edit phases, 16² diagnostic

The [prepared-edit report](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/prepared-edit-costs/report.md) and
[raw prepared-edit receipt](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/prepared-edit-costs/report.json) contain
30 rows: five edit families × two contexts × three rows, using **16 × 16
pixels / 256 deterministic inputs**. The graph already exists. Phase columns
below are all-three-row medians in milliseconds; entry end-to-end covers
ordinal 0 and repeated end-to-end is the median of ordinals 1–2. Entry follows
the preceding edit family and need not be first activation. `all_active`
changes Exposure while Tone and Color remain at fixed active settings; its
entry activates the complete grade.

| Context | Edit | Prepare (ms) | Apply wall (ms) | Render (ms) | EXR readback (ms) | Entry end-to-end (ms) | Repeated end-to-end (ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| Shader | exposure | 0.668 | 26.182 | 396.396 | 6.567 | 452.765 | 417.729 |
| Shader | tone_fit | 1.181 | 19.935 | 414.002 | 6.624 | 446.642 | 450.142 |
| Shader | web_chroma | 109.740 | 25.928 | 425.033 | 7.962 | 1241.341 | 571.604 |
| Shader | web_scale | 108.253 | 25.076 | 442.340 | 7.355 | 1284.102 | 580.975 |
| Shader | all_active | 0.719 | 25.396 | 450.508 | 7.259 | 2010.925 | 483.843 |
| Compositor | exposure | 0.653 | 26.162 | 70.818 | 2.859 | 98.291 | 101.528 |
| Compositor | tone_fit | 1.199 | 20.626 | 73.608 | 2.958 | 103.463 | 89.301 |
| Compositor | web_chroma | 105.227 | 28.032 | 78.005 | 4.037 | 2651.324 | 219.530 |
| Compositor | web_scale | 115.532 | 28.062 | 74.814 | 3.906 | 1531.002 | 211.864 |
| Compositor | all_active | 1.051 | 28.766 | 108.630 | 5.265 | 4758.618 | 135.095 |

Apply wall time includes image upload/packing/readback, binding writes and
publication. End-to-end is measured independently and includes preparation,
apply, render and EXR readback; component medians must not be added. Base
preparation, boundary load, graph construction and the initial warm render are
outside edit timing. GUI event scheduling, preview upload and display are also
outside this small fixture. Its finite-output and preserved-identity checks
do not certify independent-reference accuracy or 1024² performance.

### Fresh-process 1024² image benchmark

The [image benchmark report](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/benchmark/report.md) and
[raw image benchmark receipt](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/benchmark/report.json) contain 18 fresh
processes and 144 renders: three processes × two contexts × three variants,
each with one cold render and seven warm renders. Each table row has three
cold and 21 warm observations. The graph is the specialized `build_group`
fixture, distinct from the persistent GUI/edit graph.

| Context | Work | Cold fixture p50 (ms) | Cold render p50 (ms) | Warm fixture p50 (ms) | Warm render p50 (ms) |
|---|---|---:|---:|---:|---:|
| Shader | passthrough | 3266.3 | 1265.4 | 2587.2 | 687.0 |
| Shader | linear_tone | 3282.1 | 1332.5 | 2612.8 | 720.0 |
| Shader | full | 3504.3 | 1475.9 | 2735.8 | 798.1 |
| Compositor | passthrough | 885.7 | 100.5 | 864.0 | 96.9 |
| Compositor | linear_tone | 1557.5 | 782.1 | 910.1 | 144.8 |
| Compositor | full | 4008.8 | 3210.6 | 1185.5 | 403.0 |

Fixture wall time includes render and Python EXR readback; the render interval
includes AOV/Compositor work and uncompressed RGBA32F EXR writes. The fixed
transport is seven files / 117,559,834 bytes per Shader run and three files /
50,382,786 bytes per Compositor run. The median paired fixture-minus-render
time is 1,901.6–1,919.2 ms warm across Shader variants and 763.7–779.8 ms
across Compositor variants; this includes Python EXR readback and fixture/timer
overhead, not an isolated readback measurement. This transport explains much
of the difference between fixture and render columns. Identical pixels are
republished before each run to invalidate cached image evaluation, with
publication untimed. Scene/input, graph building,
image packing, output-fixture setup and boundary loading are recorded
separately. Neither timing column isolates Grade node cost, and subtracting
passthrough does not establish an isolated grading speedup or per-frame cost.
The Shader full graph is 1,019 expanded nodes and retains its node-budget
failure; Compositor full is 964 nodes and passes that construction cap. Finite
outputs and transport checks pass; graded reference accuracy is outside this
benchmark's acceptance scope.

### Historical fixed-field texture and preparation breakdown

The [preparation report](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/preparation-costs/report.md) and
[raw preparation receipt](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/preparation-costs/report.json) contain 20
measurements, four cases × five repetitions, after all native timing work
finished. Host preparation uses the full CPU affinity with pinned Python 3.13.6
and one OpenBLAS/OpenMP thread; software GPU affects native evaluation, while
these functions continue to run on the host. At the historical
32,768-parameter / 1,536-toe layout, the resident RGBA32F payload is
**24,960,704 bytes (23.804 MiB)**. All-active generation medians are:

| Field | Cells | Width × height | RGBA32F bytes | Generation median (ms) |
|---|---:|---|---:|---:|
| Tone | 512 | 512 × 2 | 16,384 | 1.250 |
| Color coefficients | 131,072 | 8,193 × 32 | 4,194,816 | 61.542 |
| Web parameters | 32,768 | 8,193 × 128 | 16,779,264 | 96.087 |
| Web toes | 1,536 | 1,537 × 1 | 24,592 | 2.165 |
| Compact Adaptance | 16,384 | 8,193 × 2 | 262,176 | 4.316 |
| Interior Adaptance | 65,536 | 8,193 × 8 | 1,048,704 | 8.039 |
| Output boundary | Fixed | 513 × 321 | 2,634,768 | 35.078 initial load, reused |

Complete preparation is timed independently: reset **190.707 ms**, all-active
**184.764 ms**, alternating Web extremes **188.034 ms**, and all-families active
tail **195.257 ms**. Component and complete-preparation medians must not be
added. This scope excludes dense audits/searches, native image packing/upload,
graph construction, rendering and displayed-preview latency. Payload bytes
exclude Python, Blender, allocator and driver overhead. Web parameters remain
the largest field and the slowest all-active generator.

### Receipt identities

The aggregate retains input-artifact manifests, source comparisons from that run,
every failing GUI row and the 25 worst passing rows. The GUI receipt preserves
settings, phases, reference indices, revision/sample identities and native
image hashes; it records maxima over 32 probes per displayed image rather than
full per-pixel reference/native archives. The dedicated accuracy diagnostic is
separate from these timing measurements.

| Receipt | JSON SHA-256 |
|---|---|
| [Validated aggregate](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/aggregate.json) | `09cc1792158ec2a9cebabf8c6ac33588cd1aa5bc39612a92b665d8bc98391fb6` |
| [Sequential launcher](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/launcher.json) | `50f362b5be2044ee95107a826075ed771b9ce92cdfec472b4a19cfc3a0890746` |
| [GUI](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/gui-1024-final/report.json) | `2abdd245fa379e3c68665e0c43b8f8b3dacb23857d30d491203ff07433522158` |
| [Prepared edits](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/prepared-edit-costs/report.json) | `c24d7f24ee4164406300227451ca6336cc3c17e8ff6ca04cee1ad9da808970e7` |
| [Image benchmark](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/benchmark/report.json) | `816b01f508530b5f6256b9752f0514c9df3e200f02b9f9a947d7abaa5f62e003` |
| [Fixed-field preparation](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/preparation-costs/report.json) | `e9e6a1dd2b6d26b3a2e16e4eb40b9e11550ddaced18898814a1b4b469046d167` |
| [Web-stress diagnostic JSON](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/report.json) | `f830956cf8775a647ebb3d19235fe56c086c62df2d02f9f459e5ff08c4be3a78` |
| [Web-stress diagnostic Markdown](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/report.md) | `250dc4740681afdc5dc1e1843172b3d762bad84ebf89365f930155838a3b7f4f` |
| [Reference witness review](../../../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/reference-review.json) | `47a5e48929066a191a91e1f7a342265241ed31a2892a51631adc4a69c6ef2745` |

The aggregate helper SHA-256 is
`d7ea4dc7fe708d158078385a8b0cf1acb477cfeccd91eeacddc390c6fc881141`.
The sections below preserve earlier CPU, layout-admission and sizing evidence
under their recorded source and execution scopes. Their timing values are
historical; the completed software-GPU rerun above measured the prior
32,768-parameter layout. The promoted-layout evaluation is recorded above.

## Retained Web-toe admission and historical CPU preparation receipt

The fixed runtime Web-toe layout is now **1,536 cells** (`1,537 × 1` RGBA32F,
`24,592` bytes). The source-stable [HDR admission receipt](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/sweep-merged/report.md)
measured all 149 cases, three scene spaces, both CPU contexts and all eight
toe candidates with 32,768 Web parameters against an explicit 524,288-cell toe
baseline. It selects 1,536 at maximum signed worsening `0.03935971856` codes
and maximum percentage worsening `0.1514492587%`; 1,280 is rejected at
`0.05062495172` codes, with percentage maximum `0.1030944414%`. The
[retained percentage summary](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/sensitivity-percentages.md)
derives those percentages from the original measurement rows. Code and
percentage maxima can occur at different pixels; percentages exclude reference
peaks below one code while retaining their absolute errors. The
[independent validator](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/sweep-validation.json)
matches the selection. Scalar/local precision remains diagnostic for this
layout policy, while the retained final-output, containment, validity,
saturation, sign and finiteness checks remain visible. The [local/seam receipt](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/local/report.md)
has zero safety failures and 16 raw precision failures across 112 comparisons.
The original 524,288-cell texture remains the comparison and strict arithmetic
regression baseline. The [aggregate receipt](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/summary.md)
and [machine-readable acceptance](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/acceptance.json)
bind the evidence and final artifact checksums.

The [verification after promotion](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-merged/report.md)
repeats all 894 baselines and 894 candidate rows (90 measured, 804 explicitly
inactive) against the original toe, with identical maximum worsening. All
selected final scene-linear, containment, validity and saturation checks pass;
21 inherited baseline/candidate node-budget failures remain separate. The
[independent validation](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-validation.json)
checks exact coverage, journals, native image readback and artifact identities.
The sweep JSON SHA-256 is
`b0ecdcfcb07d6c251cd0ad0541ce3494a16ed71865624017b20089028758bea6`;
the promoted JSON SHA-256 is
`a88998093aac15fb25ee93739edcfa0d50f40ba2f3756fe2d5973d6d8175fc84`.

The [complete scalar diagnostics](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-scalar/report.json)
traverse all eight grids and all 16 distinct toe functions in the 149-case
corpus. At 1,536 cells, maximum conditioned error is `0.0142855202` and maximum
relative interpolation error is `0.0349361292`; raw precision acceptance remains
failed. The [final selected local/seam report](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-local-final/report.md)
has 14 comparisons, zero safety failures and two raw precision failures.
Maximum conditioned H/opponent/energy errors are `0`, `1.82384229e-5` and
`1.37323377e-5`; maximum returned-scale relative error is `0.000369151463`.
These failures remain diagnostics under the authorized toe HDR policy.

At that historical 32,768-parameter / 1,536-toe layout, all **80 checks across
11 Buck2 targets** pass, including preparation/reuse,
policy/report, saturation/guards, full guarded Grade, persistent lifecycle and
both specialized and persistent local Color stages. The [initial regression log](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-tests.log)
records two helper integration failures; the [corrected regression log](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/corrected-stage-tests.log)
passes both affected suites plus four local diagnostic checks. The fixes
preserve absent-toe preparations and patch the extracted fixture's graph class
for persistent tests. Source identities are stable during both final stage suites.
No new dependency was added; existing dependencies remain pinned through Buck2.

The earlier isolated [preparation report](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/preparation-costs-final/report.md)
contains 20 measurements (four cases × five repetitions), stable sources,
CPUs 0–7 and one OpenBLAS/OpenMP thread, after heavy tests and builds completed.
Its historical 32,768-parameter / 1,536-toe resident RGBA32F payload is
**24,960,704 bytes (23.804 MiB)**.
The toe saves **8,365,040 bytes (99.7069%)** versus the original 8,389,632 bytes.
All-active component medians are:

| Field | Cells | Width × height | RGBA32F bytes | Generation median |
|---|---:|---|---:|---:|
| Tone | 512 | 512 × 2 | 16,384 | 1.256 ms |
| Color coefficients | 131,072 | 8,193 × 32 | 4,194,816 | 61.471 ms |
| Web parameters | 32,768 | 8,193 × 128 | 16,779,264 | 96.489 ms |
| Web toes | 1,536 | 1,537 × 1 | 24,592 | 2.122 ms |
| Compact Adaptance | 16,384 | 8,193 × 2 | 262,176 | 4.379 ms |
| Interior Adaptance | 65,536 | 8,193 × 8 | 1,048,704 | 7.970 ms |
| Output boundary | Fixed | 513 × 321 | 2,634,768 | 36.914 ms initial load, reused |

Complete preparation medians are 192.829 ms reset, 186.180 ms all-active,
190.037 ms alternating Web extremes and 191.773 ms all-families active tail.
Toe generation medians range from 2.122 to 2.149 ms. Component and complete
preparation are independent measurements and must not be added. These exclude
dense audits, native upload/packing, graph construction, render and interaction
latency; pixel payload excludes allocator, driver and cache overhead.
Timing JSON SHA-256 is
`cbc240a1226fb77444e95705f5c16a4102ad31c6515d5c828c74a98aaf4003fd`.
The preliminary `toe-hdr-005/preparation-costs/` run overlapped tests and is
superseded for timing.

## Earlier audit and sizing receipts

The sections below retain their original layouts, policies and source scope.
Their references to unchanged runtime layouts describe those earlier runs.

The measured [HDR end-to-end code-value sensitivity report](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/report.md)
uses the pinned Buck2 Blender/OCIO configuration, fractional full-range 10-bit
values, the full retained corpus, all three scene spaces and both native CPU
contexts. It contains 894 baselines and 30,396 candidate rows across 34
layouts: 8,286 measured candidates and 22,110 explicit inactive-texture rows,
with no generation, render or nonfinite failures. The source-stable JSON
receipt is SHA-256
`41692459fffffa36b2c99eeeef9b3810da1818a7740376abe2a4ea920466a856`; its
[gate summary](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/summary.json)
is SHA-256
`0a553d30d7f426f4091f286744f82ed90e1e181bb7f958ce57583fdcd8884398`.

The worst historical-baseline error is **7.9856666 codes**. Of 915,456 baseline
pixel samples, 24 exceed one code and four exceed two. All baselines pass the
scene-linear output gate; 21 retain the original expanded-node-budget failure.
Measured candidates
have 256 final scene-linear failures, 678 node-budget failures and 3,744
scalar-field failures; containment remains within `8e-6`. Tone/32 produces the
largest signed worsening, **186.780493 codes**, while Web parameters/4096 and
the combined Web candidate have no scalar-field failures in measured rows.
That historical experiment left runtime layouts and acceptance gates unchanged; Tone and
boundary reductions are diagnostic candidates only. Complete witnesses,
near-black denominator accounting, OCIO processor identities and all source
hashes remain in the JSON; no per-pixel archive is stored.

The historical [sensitivity table](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/sensitivity.md)
reports code and percentage worsening for every candidate. Its baseline has
**32,768 Web-parameter and 524,288 Web-toe cells**. The table below retains one
example per texture role; the 1,536-toe row comes from the later
[toe HDR sweep](../../../../buck-out/persistent-grade-evidence/toe-hdr-005/sensitivity-percentages.md)
with the same explicit baseline dimensions. It does not measure the combined
current 4,096/1,536 runtime.

| Historical candidate | Maximum added error (codes) | Maximum added error (% reference peak) |
|---|---:|---:|
| Tone/256 | `0.0172103494` | `0.00848011155%` |
| Color coefficients/65,536 | `0.00978657603` | `0.00177673041%` |
| Web parameters/4,096 | `0.0404496565` | `0.145224804%` |
| Web toes/1,536 | `0.03935971856` | `0.1514492587%` |
| Compact Adaptance parameters/8,192 | `0` | `0%` |
| Interior Adaptance parameters/16,384 | `4.57316637e-05` | `4.34075537e-05%` |
| Output boundary/257 × 161 | `0.142031591` | `0.0205077539%` |

Added error is the signed increase in per-pixel peak absolute reference error.
Interior Adaptance/16,384 has maximum **movement `0.00147865713` codes**, while
its maximum **added error is `4.57316637e-05` codes**. Movement and worsening
are distinct measurements. The historical combined Web 4,096/32,768 row adds
`0.0404496565` codes with maximum percentage worsening `0.145224804%`;
Web toes/32,768 adds `0.000701218843` codes and `0.00148167956%`.
Code and percentage maxima can occur at separate pixels. Percentages exclude
reference peaks below one code; those pixels retain their absolute errors.
These values are downstream diagnostics, not scalar/local gate admission for
the other reduced textures.

The worst historical-baseline witness is `source_boundary_0`, ACEScg, Shader,
pixel 537: the reference green channel is `0.000747754` codes and the native
green channel is `7.98641435` codes. Their scene-linear green values are about
`1.30e-15` and `1.50e-5`. The display/PQ comparison exposes this residual near
a zero channel even though the existing scene-linear output gate passes.

The [validation receipt](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/validation.json)
rechecks that run's source/resource and OCIO identities, exact row coverage and
artifact checksums. All 678 candidate node-budget failures share baselines that
already fail that gate. All 41 focused Buck2 tests pass: five HDR metric,
seven report/shard, 14 preparation, six boundary-resource and nine Color
preparation tests. The [preparation test receipt](../../../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/preparation-tests.json)
records the latter suites. Dependencies remain in the existing pinned Buck2 closure.

The exact alternating-extreme Web case now has a case-scoped development gate
policy: Web parameter conditioned and absolute radial-log errors, Web toe
conditioned and relative errors, and local Web/returned-scale errors use `1e-4`.
Other controls and non-Web gates remain at their existing limits. The complete
parameter sweep and native local/seam receipts select 4,096 parameter cells
with 32,768 toe cells; 2,048 parameters fail both scalar absolute-log and native
local/scale acceptance. Runtime at that audit still used 32,768 parameters and
524,288 toes; the current promoted layout is listed above. Full details and checksums are in the
[case-specific gate review](GATE_REVIEW.md#case-specific-web-parameter-sizing-study).

The new policy-aware [Web-parameter audit](../../../../buck-out/persistent-grade-evidence/web-policy-parameter-audit/report.json)
rechecks all 149 cases / 19 distinct functions, selects 4,096 cells, rejects
2,048 and separately passes the then-installed 32,768-cell layout. Every accepted
row has a complete audit and explicit effective limits. Sources are stable;
JSON SHA-256 `cd7a65b84e52139915ff53dd12696d04f1837bfc7f2e9824c8c94d2e3cafb8f9`.

All 27 affected checks pass: four focused policy tests, nine Color preparation
tests, seven specialized Color-stage tests and seven inherited persistent
Color-stage tests. Logs are [policy](../../../../buck-out/persistent-grade-evidence/web-policy-tests-final.log),
[preparation](../../../../buck-out/persistent-grade-evidence/web-policy-portable-tests.log)
and [native](../../../../buck-out/persistent-grade-evidence/web-policy-native-tests.log).
Both native suites record stable source and test identities. The three tool
targets build. A [tool integration receipt](../../../../buck-out/persistent-grade-evidence/web-policy-tool-integration/report.json)
checks policy-separated function deduplication, complete candidate audits and
four full-native comparisons at the smaller layouts. All numerical checks pass;
the existing all-active Shader node-budget failure remains. This does not
replace full candidate persistent-lifecycle or physical-GPU acceptance.

The uncontended [combined candidate preparation report](../../../../buck-out/persistent-grade-evidence/preparation-costs-web-4096-toe-32768/report.md)
records 20 measurements (four cases × five repetitions) with pinned Buck Python
and dependencies, CPUs 0–7, one OpenBLAS/OpenMP/MKL thread, stable sources and
no concurrent build/audit/native work. Resident payload is **10,778,864 bytes
(10.280 MiB)**. All-active medians are:

| Field | RGBA32F bytes | Generation median |
|---|---:|---:|
| Tone | 16,384 | 1.249 ms |
| Color coefficients | 4,194,816 | 61.261 ms |
| Web parameters, 4,096 cells | 2,097,664 | 11.526 ms |
| Web toes, 32,768 cells | 524,352 | 35.905 ms |
| Compact Adaptance | 262,176 | 4.276 ms |
| Interior Adaptance | 1,048,704 | 7.855 ms |
| Output boundary | 2,634,768 | 36.125 ms initial load, reused |

Complete preparation is measured independently: 132.149 ms all-active and
132.149–150.108 ms across the four cases. That experiment left runtime layouts unchanged;
these figures use explicit process-local overrides. They exclude dense audits,
native upload, packing, graph construction, render and interaction latency.
Timing JSON SHA-256 `a31818267fb7cd31c72a52ba71327d6e0a567ff05b11daa781282cfaa0c297c0`.

The fresh 149-case scalar audit passes with stable source/resource identities.
Under the original scalar gates, the then-current Color, Web-parameter and Web-toe
sizes remain the smallest passing supported grids across this retained corpus.
The later user-authorized Web studies select smaller experimental grids.
That original-gate rerun changed no production dimensions, grading equations
or acceptance gates; the scoped development policy was implemented afterward.
That receipt leaves the original expanded-node cap open; current full acceptance
remains limited by the retained software-GPU failures; the promoted-layout rerun is recorded above.
The old core/product and future Next
scaffold are outside this audit follow-up.

The [rerun manifest](../../../../buck-out/persistent-grade-evidence/rerun-manifest.json)
preserves each audit's source/resource hashes, report checksums, test logs and the pinned
Linux ABI receipt. Its [policy-update receipt](../../../../buck-out/persistent-grade-evidence/web-policy-update/report.json)
separately verifies that policy revision's sources and all 27 affected tests, preserving the
older reports' historical source identities. The [gate review](GATE_REVIEW.md) explains independent field,
local-stage and complete-output gates and the paired downstream experiments.

## Historical Web-toe candidate under the authorized extreme-control limits

The user permits `1e-4` for both conditioned and relative toe scalar errors in
`web_alternating_extremes`. The [complete sweep](../../../../buck-out/persistent-grade-evidence/toe-limit-1e4/report.md)
passes at 32,768 cells: relative `8.67450479e-5`, conditioned `3.55143191e-5`.
The next supported size, 16,384, fails both at `3.46727218e-4` and
`1.41895704e-4`; every smaller supported size also fails. The
[combined scalar receipt](../../../../buck-out/persistent-grade-evidence/toe-limit-1e4/acceptance.json)
binds this completed extreme row to all other 15 complete toe-function rows in
the retained 149-case audit. Ordinary cases pass unchanged `1e-5` conditioned
and `1e-6` relative gates. Original failure statuses remain explicit.

The [native candidate report](../../../../buck-out/persistent-grade-evidence/field-effects-toe-32768/report.md)
passes all 12 final RGB comparisons with a maximum paired normalized delta of
`2.27402725e-7` and no validity/saturation changes. It covers two cases, three
spaces and both CPU contexts at 1,024 pixels per comparison. Three original
all-active Shader node-budget failures persist. Candidate native-image payloads
are verified. This final-RGB diagnostic does not certify independent local
substage or full persistent/GPU acceptance.

The [paired preparation run](../../../../buck-out/persistent-grade-evidence/toe-32768-costs/report.md)
records 40 measurements with stable sources and no concurrent native/audit work.
Toe generation falls from 666.6–669.6 ms to 36.2–36.5 ms; complete preparation
falls from 857.8–862.5 ms to 220.8–229.5 ms across four cases. Other field pixels
are asserted byte-identical. Toe payload is 524,352 bytes instead of 8,389,632;
total resident payload would be **25,460,464 bytes (24.281 MiB)** instead of
33,325,744. The [gate review](GATE_REVIEW.md#case-specific-web-toe-sizing-study)
records witnesses, per-case timings and checksums. These candidate studies use
process-local overrides; runtime at that point still used 524,288 toe cells.

The [full candidate texture report](../../../../buck-out/persistent-grade-evidence/preparation-costs-toe-32768/report.md)
retains the complete all-field breakdown under that same process-local override:
Tone 16,384; Color coefficients 4,194,816; Web parameters 16,779,264; Web toes
524,352; compact Adaptance 262,176; interior Adaptance 1,048,704; and output
boundary 2,634,768 RGBA32F bytes. It records 20 measurements and complete
preparation medians of 0.224870–0.231119 seconds. JSON SHA-256:
`ece0733a2c3f9f6dee48a5a418b1adcddbc5465e304febe2f134d77fdcdf9a11`.

## Historical texture size and preparation time

The [clean preparation report](../../../../buck-out/persistent-grade-evidence/preparation-costs-final/report.md)
and [raw repetitions](../../../../buck-out/persistent-grade-evidence/preparation-costs-final/report.json)
retain the original 524,288-cell toe layout. The later historical
32,768-parameter / 1,536-toe report is linked above. This earlier run measured
every resident fixed field, including neutral ones, on Linux x86_64
with pinned Python 3.13.6. Five repetitions of each of four retained grades ran
after the audit, native candidates and build dependencies finished. Process
affinity was CPUs 0–7; OpenBLAS and OpenMP were set to one thread. The report
records these execution settings and stable sources. Its SHA-256 is
`92cfedbfc9f8d8714c363c483d4ea3d62538f8f1d498744fa3086769a5406b6c`.

| Field | Cells | Width × height | RGBA32F bytes | All-active generation median |
|---|---:|---|---:|---:|
| Tone | 512 | 512 × 2 | 16,384 | 0.001220 s |
| Color coefficients | 131,072 | 8,193 × 32 | 4,194,816 | 0.061737 s |
| Web parameters | 32,768 | 8,193 × 128 | 16,779,264 | 0.097300 s |
| Web toes | 524,288 | 8,193 × 64 | 8,389,632 | 0.673016 s |
| Compact Adaptance | 16,384 | 8,193 × 2 | 262,176 | 0.004383 s |
| Interior Adaptance | 65,536 | 8,193 × 8 | 1,048,704 | 0.007895 s |
| Output boundary | Fixed | 513 × 321 | 2,634,768 | Loaded once, 0.036106 s |

Total resident RGBA32F payload is **33,325,744 bytes (31.782 MiB)**. Web's
parameter channels occupy many padded rows, so its lower cell count uses twice
the pixel storage of the toe field. Web toes dominate generation, using
0.668–0.692 s across the four cases, roughly 79% of their measured Color-field
generation. Complete uninstrumented preparation medians are 0.876255 s reset,
0.859065 s all-active, 0.867279 s alternating Web extremes and 0.866781 s
all-families active tail. Component timings and complete preparation are
separate measurements and must not be added.

These are portable preparation costs. They exclude dense audit/search, Blender
image upload/packing, graph construction and native evaluation/display. Pixel
payload is not Python allocation, packed-file size, Blender allocation or VRAM.
The earlier `preparation-costs/` run overlapped the long audit and is superseded
for timing. The 2026-10-29 GUI receipts below retain their historical scope and
are not a new matching-preview latency measurement.

## Audit and native follow-up

- [Scalar audit](../../../../buck-out/persistent-grade-evidence/field-audit-rerun/report.json):
  complete retained 149-case corpus, 32 distinct Tone configurations, stable
  sources and `passed=true`. Color/Web/toe scalar minima are
  131,072/32,768/524,288 cells; every smaller tested grid has a failure witness.
  `minimal_runtime_layout=false` is retained: scalar Adaptance minima are
  8,192/2,048, while runtime remains 16,384/65,536 because existing native local
  admission rejects smaller candidates. The historical native admission below
  has not been replaced by scalar-only acceptance.
- [Native Web candidate report](../../../../buck-out/persistent-grade-evidence/field-effects-web-final/report.md):
  48 candidates plus 12 baselines, 1,024 pixels per case, both CPU contexts and
  all three scene spaces, with stable sources. All final RGB checks pass, with
  no changed validity or saturation flags; 30 candidate rows still fail scalar
  field gates. At half runtime size, maximum paired normalized RGB delta is
  `4.38231171e-6` for parameters and `1.82053651e-7` for toes. At 2,048 cells,
  maxima rise to `3.97334580e-5` and `1.22384012e-5`. These finite input pixels
  do not necessarily visit each scalar failure coordinate and do not certify a
  smaller field under the retained gates. The broad all-role and unrestricted
  partial runs are marked incomplete; this completed Web receipt supersedes them.
- [Controlled coherent sensitivity](../../../../buck-out/persistent-grade-evidence/gate-sensitivity-accepted/report.md):
  24 exact baselines and 4,656 perturbation rows across ten handoffs. All 1,008
  H-dose realization checks pass; changed handoffs restore the signed H–K
  identity. Both small downstream effects and amplification occur. These are
  controlled reference perturbations, not attainable native texture errors or
  authorization to relax gates.
- [Full CPU rerun](../../../../buck-out/persistent-grade-evidence/full-cpu-rerun/report.md):
  102 comparisons, 1,024 pixels each, stable sources and numerical pass.
  Worst normalized RGB error is `2.62888371e-5` against `1e-4`. Nine comparisons
  fail the original `<1000` expanded-node gate, so combined acceptance remains
  failed. This uses specialized graphs; the persistent graph counts below remain
  a separate open constraint. The extended UI-boundary and GPU reports were not
  rerun as part of this audit follow-up.

The [portable regression log](../../../../buck-out/persistent-grade-evidence/portable-rerun.log)
passes 13 preparation and nine Color-preparation tests. The
[native stage/guard log](../../../../buck-out/persistent-grade-evidence/native-stage-rerun.log)
passes two stage and five guard tests. The
[tool checks](../../../../buck-out/persistent-grade-evidence/audit-tools-checks.log)
pass two architecture and four timing-summary tests. All three new tool targets
build; changed Python files pass syntax and whitespace checks. These scoped
checks do not replace the historical full lifecycle/local-stage acceptance.

## Buck2 native dependencies and reproduction

[third_party/BUCK](../../third_party/BUCK) now pins 17 Debian 13 amd64 packages by
URL/SHA-256 and exposes their X11/GL loader libraries through the Linux `bpy`
dependency. [The extractor](../../tools/blender-build/unpack_native_libraries.py)
validates the required sonames and writes hashes for the actual shared-library
payloads. Native CPU evaluation runs through Buck without a manually supplied
library path. The ABI manifest SHA-256 is
`946f54ec512f73ea42fa31fe104b80fac4068849102b80c3ae7acd838c979495`.
The pinned closure requires glibc 2.38 or newer (verified ELF symbol versions);
this run uses glibc 2.41. Libc and graphics drivers remain platform dependencies.
This is Debian 13 CPU coverage, not physical GPU/Metal or older Linux acceptance.

Run the accuracy work separately from timing:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:audit_fields -- \
  --output-dir buck-out/persistent-grade-evidence/field-audit-rerun
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-7 \
  buck2 run //products/perceptual-grade-next-blender/tools/reports:field_effects -- \
  --output-dir buck-out/persistent-grade-evidence/field-effects-web-final \
  --audit-report buck-out/persistent-grade-evidence/field-audit-rerun/report.json \
  --samples 1024 --fields 'Web parameters' 'Web toes' --coarse
buck2 run //products/perceptual-grade-next-blender/tools/reports:gate_sensitivity -- \
  --output-dir buck-out/persistent-grade-evidence/gate-sensitivity-accepted \
  --samples 1024 --spaces 'Linear Rec.709' 'Linear Rec.2020' ACEScg
buck2 run //products/perceptual-grade-next-blender/tools/reports:full_evaluate -- \
  --output-dir buck-out/persistent-grade-evidence/full-cpu-rerun --jobs 3
# Run after the above commands finish; full_evaluate exits nonzero on node budget.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-7 \
  buck2 run //products/perceptual-grade-next-blender/tools/reports:preparation_costs -- \
  --output-dir buck-out/persistent-grade-evidence/preparation-costs-final --repeats 5
```

Choose eight available CPUs on a host with a different affinity mask and retain
that mask in the timing report. Native fixture construction timings in the
correctness reports are diagnostic. The affinity smoke found large host
scheduling overhead with unrestricted CPUs; it is not an interactive benchmark.

---

# Historical persistent grading and fixed layouts — 2026-10-29

This section preserves the original 32,768-parameter / 524,288-toe source scope.
Its source-match and passing statements describe those receipts. The completed
promoted-layout evaluation and later software-GPU extreme-Web failures are
recorded separately above.

Persistent lifecycle, numerical and matching-preview timing checks pass on
Linux Blender 5.2.2. The strict full-graph node cap and Next product integration
remain open. `prepare(full_fields=True)` and
`build_persistent` initialize all three stages, every optional Color family,
precision alternatives and seven packed images. `prepare_update` reuses unchanged
fields; `PersistentGrade.apply` writes changed fields/constants/links to the same
native objects, verifies readback, rejects stale revisions and restores prior
state on failure. Failed restoration sets `valid=False` for owner recovery.
Native-reader exclusion remains the caller's responsibility.

Neutral stages bypass their existing nodes through links, including diagnostics.
A topology test checks that reset output reachability excludes Tone/Color helper
samplers, Tone-only includes only Tone, and returning to reset restores the
original reachable image set. Stage activation allocates no nodes or images.
All dormant paths count toward the original `<1000` node gate, which remains
unmet. Temporary oversized admission continues; implementation completion is
not full grading acceptance or Next product integration.

Production preparation now generates fixed fields without adaptive sizing or
dense reference probes. The separate development audit retains the scalar and
local-stage gates and lower-size failure witnesses. Initialization and cold
native evaluation/display are separated from accepted-settings-to-matching-draw
latency. Historical preparation includes dense audit work, and historical
construction includes scene/fixture setup; neither predicts current drag cost.

### Implementation and validation receipts

The final layout has 512 Tone cells; Color coefficient/Web/toe capacities are
131072/32768/524288 cells. Compact/interior Adaptance use 16384/65536 cells.
The [field-layout receipt](../../../../buck-out/persistent-grade-evidence/field-layout-acceptance.json)
passes. It combines the 149-case scalar audit with native Adaptance admission,
including lower-size failure witnesses and exact source/artifact hashes. Lower
compact 8192 fails the native local gate (`1.07903e-5` opponent error), and interior
sizes through 32768 have retained native failures even where scalar interpolation
alone passes. The selected compact/interior pair passes eight local cases in
both CPU contexts, and compact 16384 passes all 11 distinct scalar functions.
The final 13 preparation and 9 Color-preparation tests pass unchanged accuracy
thresholds at these fixed sizes.

The original [scalar audit](../../../../buck-out/persistent-grade-evidence/field-audit-exploratory/report.json)
remains marked `passed=false` because unrelated graph/evaluator files changed
during its 27.6-minute run. The combined receipt does not rewrite that result:
it independently verifies the exact preparation/corpus/audit source closure,
retains the original artifact checksum and binds the additional compact 16384
scalar/native runs and final manifest. Its scope is the retained finite corpus,
not an exhaustive proof over continuously varying settings. Runtime performs
none of these dense tests.

Portable preparation, resource loading, architecture and timing-summary checks
passed in [portable-tests.log](../../../../buck-out/persistent-grade-evidence/portable-tests.log).
The initial native regression run passed 23 tests covering reference, raw native
stages, guards, saturation and full specialized groups; its log is
[native-regressions.log](../../../../buck-out/persistent-grade-evidence/native-regressions.log).
The compact field was reduced afterward, so final affected native acceptance
uses the separate final receipts. The seven numerical persistent Color tests
initially passed with worst local error `8.98040924e-6`, but that first run failed
source-stability teardown because controller/evaluator sources changed during
execution; [the log](../../../../buck-out/persistent-grade-evidence/persistent-color-stages.log)
is exploratory and is not a final pass.

Final native acceptance at the selected layouts passes:

- [Persistent lifecycle/transition receipt](../../../../buck-out/persistent-grade-evidence/persistent-final.json):
  seven tests, zero failures/errors, stable source and packaged-asset hashes.
  Twenty grades plus reset are applied to each of six existing context/space
  trees, covering 126 transition states and six further Linear edits with active
  downstream stages. Native topology, identities/dimensions, stale revision
  rejection, partial image writes, failed restoration and active packed reopen
  are checked. The [runner](../../../../buck-out/persistent-grade-evidence/run_persistent_final.py)
  and [log](../../../../buck-out/persistent-grade-evidence/persistent-final.log) retain
  exact reproduction and outputs.
- [Persistent local Color suite](../../../../buck-out/persistent-grade-evidence/persistent-color-stages-final.log):
  all seven tests pass in 595.833 seconds with stable source hashes. It reuses
  the independent local-stage oracle at identical float32 handoffs, including
  48 substage/context cases, raw accumulated error, saturation, sharp controls and
  sector seams. Maximum gated local error is `8.98040924e-6` against `1e-5`.
- [Specialized full-group regression](../../../../buck-out/persistent-grade-evidence/full-final.log):
  four tests pass at the selected layout, including all three spaces, both CPU
  contexts, construction cleanup and packed reopen. These tests certify the
  separate specialized builder; they do not supply persistent-graph timing.

These test execution durations include concurrent correctness work and are not
interactive performance. No physical GPU or Metal acceptance is established by
these CPU tests.

### Historical CPU initialized GUI timing acceptance

The final [1024×1024 session report](../../../../buck-out/persistent-grade-evidence/gui-1024-final/report.md)
and [raw report](../../../../buck-out/persistent-grade-evidence/gui-1024-final/report.json)
cover three fresh Shader and three fresh Compositor sessions, each exercising
all 16 scenarios. The independent [audit](../../../../buck-out/persistent-grade-evidence/gui-1024-final/audit.json)
recomputes the quantiles and validates current source hashes, sample/draw
identities and framebuffer witnesses. Report SHA-256 is
`400b79b43d1bcbf6ecf589f1a679ee52106ca2ebfbfbd028fb667481e85f07d5`.
The four [summary regression tests](../../../../buck-out/persistent-grade-evidence/gui-summary-tests-final.log)
also pass, covering missing/superseded occurrences, stale or unverified draws
and nearest-rank quantiles.

All 45 recorded source/resource hashes match the current inputs. Across both
contexts, the harness accepted 1,080 occurrences: 960 received the exact
matching revision/token and preview draw, 120 were explicitly superseded by the
burst scenario, and none were unaccounted for. Native graph, node and image
inventories stayed stable; identical settings produced identical native pixel
hashes. Maximum reference-probe error is `9.72108e-5` against `1e-4`; maximum
framebuffer witness error is `3.66822e-8`.

Initialization is reported outside accepted-setting-to-matching-draw latency.
The entries below are p50/p95 seconds from three sessions per context; p95 is
nearest-rank and these small-sample quantiles are descriptive, with no speed
threshold. Scene/input setup, full grade-graph construction and first cold
evaluation/draw remain separate:

| Context | Fixed preparation | Scene/input | Grade graph | Cold evaluation → draw | Total initialization |
|---|---:|---:|---:|---:|---:|
| Shader | 0.789 / 0.826 | 0.090 / 0.091 | 18.768 / 20.072 | 0.463 / 0.482 | 20.979 / 22.202 |
| Compositor | 0.777 / 0.782 | 0.089 / 0.090 | 21.227 / 21.504 | 0.230 / 0.245 | 23.105 / 23.404 |

Each subsequent scenario row measures accepted settings through its first
matching displayed-preview draw, including preparation, native writes and link
rewiring, native evaluation/readback, preview upload, and framebuffer readback.
Representative repeated-update p50/p95 seconds are shown below. Each row has
27 repeated samples per context, excluding the three scenario-entry samples:

| Scenario | Shader | Compositor |
|---|---:|---:|
| Exposure | 0.402 / 0.445 | 0.189 / 0.221 |
| Tone fit | 0.407 / 0.427 | 0.208 / 0.242 |
| Lightness | 0.454 / 0.493 | 0.259 / 0.280 |
| Web chroma | 1.388 / 1.439 | 1.125 / 1.165 |
| Web scale | 1.347 / 1.401 | 1.126 / 1.148 |
| All-active exposure | 0.521 / 0.631 | 0.218 / 0.225 |
| Reset ↔ active | 2.561 / 2.705 | 2.752 / 13.754 |

The full report includes all 16 scenarios, phase timings and first activation
by family. First stage activation reuses the prebuilt nodes/images but still
includes field preparation and rewiring: Tone p50 is 2.002s Shader / 2.044s
Compositor, and Lightness p50 is 2.581s / 2.756s. Repeated Web field generation
is approximately 0.91–0.93s of preparation; reset/active transitions have
roughly 1.0s of preparation plus 1.1–1.5s of native binding work. The
13.754-second Compositor reset/active p95 is retained: several samples spent
9–12s in preparation, while evaluation and display remained below 0.1s each.
Host memory pressure also rose during the run, but the report does not establish
causality for the preparation tail.

The resident Shader graph has 1,499 expanded nodes and 32 texture nodes; the
Compositor graph has 1,430 expanded nodes and 16 texture nodes. Each retains
33,325,744 helper-image pixel bytes. Both exceed the original `<1000` expanded
node requirement, which remains an open acceptance gate. Evaluation used Cycles
CPU at one sample for Shader and full-precision CPU Compositor; display used
llvmpipe software OpenGL with a 777×777 preview of the 1024×1024 evaluated image
in a 1280×960 Blender window.
This is a synthetic displayed preview, not automatic Shader viewport
evaluation, Next UI scheduling, physical GPU/Metal performance or physical
frame presentation.

Reproduce with the pinned Blender and Xvfb distributions built by Buck2:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:gui_drag -- \
  --output-dir buck-out/persistent-grade-evidence/gui-1024-final \
  --blender buck-out/persistent-grade/art/root/a8ac7ec86a6bee54/third_party/__blender_linux__/output \
  --xvfb buck-out/persistent-grade/art/root/a8ac7ec86a6bee54/third_party/__xvfb_linux__/output \
  --size 1024 --sessions 3 --samples 10 --contexts shader compositor --timeout 7200
```

Use the corresponding build-output paths for another Buck isolation directory.
Each raw session retains its exact command and configuration. The earlier
1024 warm-up attempt failed because its display probe landed on a nearest-texel
boundary. Choosing an interior texel and a nonzero warm-up token fixed the
fixture; the [probe run](../../../../buck-out/persistent-grade-evidence/gui-1024-probe/report.json)
and final run pass without relaxing numerical or framebuffer tolerances.

The updated report schema was exercised by a small passthrough
[benchmark smoke](../../../../buck-out/persistent-grade-evidence/benchmark-schema-smoke/report.md).
It separates scene/input, Grade graph and output-fixture initialization. Those
16×16 results verify report generation only and are not grading performance
evidence. The specialized headless evaluator/benchmark still uses `build_group`;
persistent-graph acceptance belongs to the explicit persistent tests and GUI
fixture.

---

# Previous build-time boundary and 1D-only Web handoff — 2026-10-29

The following handoff receipts are historical. Their references to current
sources, acceptance and layouts describe that 2026-10-29 revision.

**The two-change handoff is ready: all 57 tests and all six numerical reports
pass, and the updated benchmark is recorded. The original full-grade node budget
remains unmet. The earlier 2D-enabled successful delivery below is historical.** This handoff moves
fixed boundary generation into Buck2 and deletes the optional 2D Web path. It
does not change the reference equations, native correction, H–K guard, numerical
gates or input domain. The user explicitly authorized oversized complete graphs
temporarily so the 1D implementation remains evaluable for the next developer.

## Resource and API changes

`//products/perceptual-grade-next-blender:boundary_resource` produces
`output_boundary.npz` and its generation/validation report. Portable `:code`
feeds `:boundary_generator`; packaged `:runtime` depends on the resulting asset.
Runtime `prepare_boundary(fl, aw, gamma)` loads immutable geometry and validates
its resource contract. It never regenerates a missing/incompatible asset or runs
the dense generation gate. The generated asset's checksum is part of current
numerical evidence. Geometry remains 513 × 321 RGBA32F, **2,634,768 pixel bytes**;
resource file size, native image allocation and pixel payload are distinct.

`prepare(..., web_atlas=...)`, `prepare_web_map`, prepared Web maps and the native
2D branches/retry have been removed. All active Web evaluation uses the retained
1D coefficient/toe fields. Generic 2D sampling remains necessary for the fixed
output-boundary seed. Host geometry can be reused across grades, but each native
group still owns its independently packed image.

## Acceptance and reproduction

Current full reports expose `numerical_passed`, `node_budget_passed` and combined
`passed`. The node gate remains `<1000`; excess is `max(0, expanded_nodes - 999)`.
The builder temporarily permits oversized graphs, and every such case still
receives full numerical evaluation. Combined acceptance and the full-report CLI
remain unsuccessful if either numerical or cost requirements fail. The explicit
raw Stage 1–2 budget is unchanged.

Use the packaged runtime and preserve report output even when the budget gate
fails:

```sh
buck2 build //products/perceptual-grade-next-blender:boundary_resource --show-output
buck2 test //products/perceptual-grade-next-blender/tests:preparation //products/perceptual-grade-next-blender/tests:color_preparation //products/perceptual-grade-next-blender/tests:boundary_resource //products/perceptual-grade-next-blender/tests:architecture
buck2 test //products/perceptual-grade-next-blender/tests:color_stages //products/perceptual-grade-next-blender/tests:guards //products/perceptual-grade-next-blender/tests:saturation //products/perceptual-grade-next-blender/tests:full -- --timeout 1800
buck2 run //products/perceptual-grade-next-blender/tools/reports:full_evaluate -- --output-dir buck-out/nodes-1d-handoff/full-cpu --jobs 3
buck2 run //products/perceptual-grade-next-blender/tools/reports:full_evaluate -- --output-dir buck-out/nodes-1d-handoff/full-ui --ui-boundaries --warm-runs 0 --jobs 3
buck2 build //third_party:xvfb_linux --show-output
buck2 build //products/perceptual-grade-next-blender/tools/reports:benchmark_report --show-output
```

On Linux, replace `/path/to/built/xvfb` below with the directory printed by the
Xvfb build above, then run the GPU evaluator directly:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:gpu_evaluate -- --full --output-dir buck-out/nodes-1d-handoff/full-gpu --xvfb /path/to/built/xvfb
```

The `:full_report`, `:full_ui_report` and `:full_gpu_report` generation targets
currently fail by design because combined acceptance includes the unmet node
budget; Buck may not publish their declared outputs. Direct evaluator commands
also return nonzero on that budget failure, but their explicit output directories
retain the complete receipts. Current exact launcher commands, including the
resolved Xvfb path, are recorded in the report-run artifacts.

Current artifacts belong under `buck-out/nodes-1d-handoff/`. This checkout used
`buck2 --isolation-dir nodes-handoff ...` after the existing default daemon
stalled while initializing its materializer; no repository configuration was
changed. The commands above use the normal default isolation directory; add that
option to reproduce that build cache. The final portable resource/architecture
checks used the independent `nodes-boundary-portable` isolation directory.
The numerical/native checks and benchmark below are complete. Do not substitute the historical
53-test/six-report result or 998-node maximum below for current receipts.

The current boundary generation report **passes**. Its seven producer-source
identities were stable throughout generation and match the current files. Build
`3d695fd7-9268-4ce1-af0a-d10a441c3587` produced this report while running the five
portable resource tests, which pass in 9.687 seconds. The exact producer command
and source/stable artifact mapping are in the [provenance receipt](../../../../buck-out/nodes-1d-handoff/boundary/provenance.json).

| Generated resource measurement | Value |
| --- | ---: |
| Archive bytes | 1,632,257 |
| RGBA32F pixel bytes | 2,634,768 |
| Build-time geometry generation and gate | 8.04786 s |
| Validation probes | 183,680 |
| Corrected-radius maximum / limit | `1.06238660e-5` / `2e-5` |
| Seed maximum error | `5.82131852e-8` |

Asset SHA256:
`40b78e6864e8b5bab92dad3dd12ab886ff22c9064b8f1a8b4b503a01b66df04c`.
See the [generated asset](../../../../buck-out/nodes-1d-handoff/boundary/output_boundary.npz),
[generation report](../../../../buck-out/nodes-1d-handoff/boundary/report.json) and
[portable resource test log](../../../../buck-out/nodes-1d-handoff/boundary-portable-tests.log).
The 8.05-second generation ran alongside other build work and is not an isolated
performance benchmark. An earlier source-current report measured 5.58748 seconds
and is archived separately; both generated identical asset bytes. The
[initial build log](../../../../buck-out/nodes-1d-handoff/boundary-build-isolated.log)
records an earlier generator revision with identical asset bytes and no generation
timer; it is not the producer receipt for either timed report.

The **seven portable tests pass**: five `tests:boundary_resource` checks in the
producer build above and two `tests:architecture` checks in build
`7ca4cf36-6556-4bfd-8fc3-0a182378a9c3`. They cover deterministic generation,
invalid-resource rejection, immutable data, package ownership, private relocation
and loading without Blender. The [portable test receipt](../../../../buck-out/nodes-1d-handoff/portable-tests.json)
records exact test/log/source hashes and the separate earlier visibility failure
and queued cancellation; neither earlier attempt is counted as the final pass.

Native checks encountered cold-start filesystem waits and host I/O contention;
these delays do not measure node evaluation cost. The
[I/O observation receipt](../../../../buck-out/nodes-1d-handoff/io-observations.json)
records observed worker progress, device activity and diagnostic limits. Run the
image-sized benchmark after owned correctness jobs finish, and do not infer that
external host activity was absent merely because those jobs have stopped.

## Current unit and internal acceptance

**57 tests across 11 targets pass, with no failures or timeouts.** The nine-target
batch contains 50 tests, build `1dc2c830-48a8-4ea4-b558-5dc2d21db82d`; the seven
portable tests above complete the total. See the [test receipt](../../../../buck-out/nodes-1d-handoff/tests-summary.json)
and [batch log](../../../../buck-out/nodes-1d-handoff/tests.log) for exact commands,
target counts, test source hashes and prior-attempt distinctions. General test
source receipts were captured after completion against the coordinator's frozen
sources; the Color suite additionally records matching start/end identities for
21 runtime/tool files, ten reference files, its test source and the boundary asset.

The [current Color metrics](../../../../buck-out/nodes-1d-handoff/color-metrics.json)
cover **48 local comparisons / 12,280 unsaturated sample comparisons**. All
conditioned local errors pass `1e-5`; the maximum is **`8.98040924e-6`** in Web
signed energy, with returned Web scale error `5.40427597e-6`. Significant energy
sign mismatches are zero. Six sector-seam comparisons cover 1,944 samples, with
maximum opponent error `1.37143482e-6`, energy error `1.00262570e-6`, and scale
error `1.07313415e-6`.

Accumulated raw error remains a separate diagnostic, as agreed. The following
maxima exclude flagged saturation rows; they are not an additional `1e-5` gate:

| Accumulated path | H | Opponent | Signed energy |
| --- | ---: | ---: | ---: |
| Isolated Color from float32 appearance | `1.15856521e-5` | `6.77020219e-6` | `2.31098883e-5` |
| Linear + Tone + Color | `6.28358143e-5` | `2.58054474e-4` | `1.25356323e-4` |

The tests verify the newly authorized ability to construct oversized graphs;
their passing status does not certify the original full-graph cost requirement.
The current CPU/UI inventory below records the remaining cost failures;
current evaluation timings are reported separately.

## Current end-to-end acceptance

All six reports **pass numerically**, preserving the full historical case corpus,
authored settings and input-pixel identities. The three complete-grade reports
**fail combined acceptance solely on the original node budget**; their numerical
work is complete. The raw Stage 1–2 reports pass both numerical and cost gates.

| Report | Cases × samples | Worst normalized RGB error | Numerical | Original node budget |
| --- | ---: | ---: | --- | --- |
| Raw CPU | 42 × 1024 | `7.74309230e-6` | Pass | Pass |
| Raw CPU UI sweep | 348 × 1024 | `4.52214746e-5` | Pass | Pass |
| Raw available GPU | 42 × 256 | `3.56356686e-6` | Pass | Pass |
| Full CPU | 102 × 1024 | `2.62888371e-5` | Pass | Fail: 6 rows |
| Full CPU UI sweep | 894 × 1024 | `4.49071091e-5` | Pass | Fail: 18 rows |
| Full available GPU | 102 × 256 | `2.70419144e-5` | Pass | Fail: 6 rows |

The [six-report audit](../../../../buck-out/nodes-1d-handoff/reports-summary.json)
records each report's exact SHA256, graph/resource inventory, worst pixel,
coverage and source identities; the [audit log](../../../../buck-out/nodes-1d-handoff/reports-audit.log)
passes. All 21 runtime/tool source identities, ten reference identities and the
boundary asset match current files. The reference files are unchanged from the
historical delivery. Full reports check identities at start and finish; raw
reports capture completion identities. Source/asset matching alone does not turn
the raw receipts into start/end checks.

Full reports have zero invalid outputs, validity mismatches or nonfinite rows.
Raw pole-stress cases retain expected reference/native invalid agreement: 510
case-sample events in each CPU report and 144 in the GPU report. They remain
separate from the raw ordinary-response acceptance domain. CPU alpha is exact;
GPU reconstructed alpha differs by at most `1.78814e-7`. Full CPU/UI include 42
saturation events each and full GPU includes 24; all remain in the guarded RGB
gate. Isolated native guards preserve actual AP1 `[0,1024]` containment.

Available GPU coverage uses **Mesa llvmpipe software OpenGL**, not physical GPU
hardware or Metal. The current [GPU sampling checks](../../../../buck-out/nodes-1d-handoff/full-gpu/sampling.json)
and [independent GPU guard checks](../../../../buck-out/nodes-1d-handoff/full-gpu/guard-internal.json)
pass. One earlier raw GPU startup timed out waiting for Xvfb before evaluating
pixels; the unchanged-source retry supplies the final report. Commands and
attempt outcomes are retained in [report runs](../../../../buck-out/nodes-1d-handoff/report-runs.json).
The abandoned direct-overlay attempt produced no final acceptance cases; the
final reports use the current Buck-built launchers.

## Current 1D graph inventory

The full CPU report covers 102 case/context/space combinations and passes every
numerical gate; its maximum counts are 1051 Shader / 996 Compositor. The full UI
sweep covers 894 combinations and also passes numerically, with worst guarded RGB
error **`4.49071091e-5`**. Its original node-budget gate fails for 12 Shader and
six Compositor rows. These represent the following four grades in all three
scene spaces:

| Grade case | Shader nodes / excess | Compositor nodes / excess | Bound pixel bytes |
| --- | ---: | ---: | ---: |
| `all_active` | 1000 / 1 | 945 / 0 | 4,355,696 |
| `all_active_saturation` | 1051 / 52 | 996 / 0 | 5,142,224 |
| `all_families_max` | 1060 / 61 | 1005 / 6 | 6,059,824 |
| `all_families_max_active_tail` | **1083 / 84** | **1025 / 26** | 7,108,528 |

Excess is relative to the largest admissible count, 999. A graph of exactly
1000 therefore fails the original strict cap. Sampler maxima are 32 Shader /
16 Compositor. None of these failures suppresses numerical evaluation. The
[full CPU report](../../../../buck-out/nodes-1d-handoff/full-cpu/report.json) and
[full UI report](../../../../buck-out/nodes-1d-handoff/full-ui/report.json) retain all
rows, source/asset identities and separate acceptance statuses.

**1D Web does not imply a 4.15 MiB upper storage bound.** That is the representative
`all_active` grade. The UI storage maximum is **27,803,664 bytes (26.516 MiB)** for
`web_alternating_extremes`: 16,779,264 bytes of Web coefficients at 32,768 logical
cells, 8,389,632 bytes of toes at 524,288 cells, plus 2,634,768 boundary bytes.
That storage-heavy Shader graph has 637 nodes; the storage and node maxima are
different cases. Payload counts bound RGBA32F pixels, not measured driver/VRAM
allocation or the compressed boundary archive.

For a focused optimization loop, retain the complete corpus for final acceptance
but reproduce these cost failures with:

```sh
buck2 run //products/perceptual-grade-next-blender/tools/reports:full_evaluate -- --output-dir buck-out/nodes-1d-handoff/budget-recheck --ui-boundaries --cases all_active all_active_saturation all_families_max all_families_max_active_tail --warm-runs 0
```

The current expected result is numerical pass and combined acceptance failure
with nonzero exit status. Current unit and CPU/GPU numerical results do not
certify physical GPUs, Metal, interactive latency or final node-budget completion.

## Remaining implementation

Reduce the complete 1D graphs below 1000 expanded nodes, preserving every
accepted setting and numerical gate; then restore strict construction rejection
and its cleanup coverage. Keep all numerical cases, including oversized grades,
saturation, sector seams and boundary stress. Any model simplification requires
consultation. Complete acceptance must bind the packaged boundary asset as well
as code, and actual native evaluation speed must be measured alongside node count.

The present change retains the sampled boundary seed. Compact boundary
coefficients from the historical `d65_boundary.npz`, shared native-image storage,
incremental grade-dependent preparation, physical GPU/Metal validation, and Next
product integration remain separate work. A small archive does not by itself
establish a low-cost native evaluator.

## Current image-sized performance

The [benchmark audit](../../../../buck-out/nodes-1d-handoff/benchmark-summary.json)
passes: **18 fresh processes / 144 renders**, 1024 × 1024 pixels, three processes
per variant/context and seven warm renders per process. It uses Cycles CPU for
Shader and full-precision CPU Compositor on the Linux host with 128 logical CPUs.
All source/reference/asset identities match numerical acceptance, including the
benchmark's own source identity. Outputs are deterministic within and across
processes. Every render writes exactly **50,382,786 bytes** across three
uncompressed 32-bit RGBA EXRs.

Fixture wall time includes render, diagnostics, EXR writes and Python readback;
render time excludes Python readback. Input pixels are republished outside the
timed interval to invalidate cached image results. Neither metric isolates node
evaluation. All figures below are seconds; warm entries are median / median
absolute deviation (MAD) across 21 measurements.

| Context | Work | Cold fixture median [min, max] | Warm fixture median / MAD | Warm render median / MAD |
| --- | --- | ---: | ---: | ---: |
| Shader | Passthrough | 1.119 [1.037, 23.725] | 1.088 / 0.087 | 0.205 / 0.024 |
| Shader | Linear + Tone | 1.277 [1.172, 1.378] | 1.125 / 0.099 | 0.240 / 0.024 |
| Shader | Full, 1D Web | 2.131 [1.457, 2.342] | 1.308 / 0.122 | 0.386 / 0.027 |
| Compositor | Passthrough | 1.914 [0.935, 2.520] | 0.998 / 0.114 | 0.088 / 0.003 |
| Compositor | Linear + Tone | 0.819 [0.780, 1.945] | 0.822 / 0.021 | 0.095 / 0.010 |
| Compositor | Full, 1D Web | 0.922 [0.877, 1.070] | 1.124 / 0.167 | 0.142 / 0.008 |

| Context | Work | Boundary load | Grade preparation | Construction | Nodes / bound pixel bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| Shader | Passthrough | 0 | 0.0011 | 0.057 | 2 / 0 |
| Shader | Linear + Tone | 0 | 0.0139 | 0.527 | 217 / 16,384 |
| Shader | Full, 1D Web | **0.02715** | **2.096** | **10.161** | 1000 / 4,355,696 |
| Compositor | Passthrough | 0 | 0.0011 | 0.055 | 3 / 0 |
| Compositor | Linear + Tone | 0 | 0.0140 | 0.592 | 220 / 16,384 |
| Compositor | Full, 1D Web | **0.02719** | **2.064** | **10.540** | 945 / 4,355,696 |

The boundary's dense generation/validation occurs only in its Buck target;
runtime loads its packaged data in about 27 ms in this fixture. Grade preparation
retains the field generation and accuracy gates. Construction includes native
image creation/packing and the complete fixture. These are separate medians,
not a median total. The full Shader benchmark is still one node over the strict
budget; successful benchmark execution does not certify full cost acceptance.

Owned correctness workers had finished before the benchmark, but external host
filesystem/page I/O pressure remained high. The first worker waited about five
minutes on file pages before rendering; this lies outside the measured fixture
interval. Its first cold fixture then took 23.725 seconds, retained above rather
than discarded. Warm full-fixture ranges are 1.067–3.136 seconds for Shader and
0.852–2.098 seconds for Compositor. Preserve this variability; do not subtract
passthrough times or claim an isolated-node, viewport, hardware-GPU, old-LUT, or
historical-run speedup from these fixtures.

The [benchmark JSON](../../../../buck-out/nodes-1d-handoff/benchmark/report.json),
[Markdown](../../../../buck-out/nodes-1d-handoff/benchmark/report.md),
[audit log](../../../../buck-out/nodes-1d-handoff/benchmark-audit.log) and
[summary](../../../../buck-out/nodes-1d-handoff/benchmark-summary.json) retain commands,
individual process receipts, exact hashes, timing distributions and host I/O
observations. Report SHA256:
`374e6c03c2943c2f6c45844aa3835002b7b65061a4a6fdcecb916e1637d5bd09`.

---

# Historical 2D-enabled Linear + Tone + Color acceptance — 2026-10-29

All 53 library tests and six end-to-end reports pass on pinned Blender 5.2.2.
The image-sized benchmark is complete, with its costs and limitations below. The runtime
implements Linear, Tone, Color, H–K repair and the native AP1 output boundary;
there is no input RGB repair or 3D RGB grading LUT. The agreed float64 reference
and low/high chroma law are unchanged. Next integration remains future work.

## End-to-end acceptance

| Evaluation | Cases × pixels | Worst normalized RGB error | Result |
| --- | ---: | ---: | --- |
| Full Cycles Shader + Compositor CPU | 102 × 1024 | `2.62888e-5` | Pass |
| Full CPU UI-boundary/control sweep | 894 × 1024 | `4.49071e-5` | Pass |
| Full Eevee + Compositor GPU | 102 × 256 | `2.70419e-5` | Pass |
| Raw Linear + Tone CPU regression | 42 × 1024 | `7.74310e-6` | Pass |
| Raw Linear + Tone UI regression | 348 × 1024 | `4.52215e-5` | Pass |
| Raw Linear + Tone GPU regression | 42 × 256 | `3.56357e-6` | Pass |

The full RGB metric is `max(abs(actual-reference))/(1+max(abs(reference)))`.
Every sample remains subject to `1e-4`, including saturation and boundary
projection; there is no near-pole exclusion. The unchanged float64 oracle composes
Linear, signed appearance, Tone, Color, H–K repair and cube projection explicitly,
without the reference input repair. The raw Stage 1–2 regression retains its
separate response-magnitude ≤300 contract and reports pole stress separately.

The worst full UI result is `web_log_scale_+1`, Linear Rec.709, Shader, pixel 865.
Full reports contain zero reference/native invalid outputs, validity disagreements
or nonfinite rows. CPU alpha is exact; GPU alpha reconstruction differs by at
most `1.78814e-7`. CPU main/UI each include 42 saturated case-sample events; GPU
includes 24. All remain inside the RGB gate. Reconstructing scene output into AP1
has maximum normalized containment discrepancy `1.16217e-7`, below its `8e-6`
endpoint-rounding allowance. Isolated guard tests check actual native AP1 sockets
and have exact `[0,1024]` containment.

GPU coverage uses Xvfb and Mesa llvmpipe software OpenGL. Eevee readback
reconstructs float32 from mantissa/residual/exponent AOVs; ordinary AOV storage
would quantize to float16. Physical GPU drivers and Metal need separate acceptance.
Shader helper fields interpolate explicit nearest texels to prevent implicit
mip filtering from blending unrelated parameter entries. Six permanent GPU
sampling/saturation checks pass, with maximum sampling error `1.87266e-6` and
correct overflow flags; the overflow primitive maximum is `1.78814e-7`.

## Internal acceptance

Cycles Shader CPU and full-precision Compositor CPU pass the agreed `1e-5` gate
for each Color substage at identical float32 states and frozen selector inputs.
These are conditioned state errors, as specified in [COLOR_TABLES.md](COLOR_TABLES.md).
The source-bound rerun covers 54 local comparisons and 13,816 unsaturated pixel
comparisons; all pass.

| Local substage | H error | Opponent error | Signed-energy error |
| --- | ---: | ---: | ---: |
| Lightness/chroma terms | `4.55290e-7` | `2.34282e-6` | `2.01412e-6` |
| Tonal Web | `0` | `7.62354e-6` | `8.98041e-6` |
| Selective Adaptance | `2.85022e-6` | `2.78361e-6` | `5.68257e-6` |
| Final scale | `1.26651e-7` | `5.46062e-8` | `1.18247e-7` |

Returned Web scale has maximum relative error `5.40428e-6`. The 2D representation
used by the largest graphs also passes: opponent `4.51058e-6`, energy `1.46020e-6`,
returned scale `3.69592e-6`. Significant energy-sign mismatches are zero. The
1,944 seam probes include exact/adjacent float32 inputs, tonal anchors and
midpoints, tails, alternating ±16/±8 radial controls, and −360/0/+360 rotations.
Their largest opponent/scale errors are `1.37143e-6` / `1.07313e-6`. Ordinary and
representable terms/Web/scale cases explicitly reject false saturation flags.

Helper fields retain the `1e-5` authored-conditioning gate, with additional
`3e-6` absolute interpolation gates for chroma and Web-log coefficients and
`1e-6` relative interpolation for positive Web toes. A positive-term form of the
same quintic polynomial avoids endpoint cancellation. Pointwise-normalized diagnostics without authored scaling
are reported separately: coefficient coordinate-rounding and pointwise errors
reach `1.2681e-4` and `1.7456e-4` in the UI sweep. They are not the authored gate
or native substage metric. See [COLOR_TABLES.md](COLOR_TABLES.md) for definitions,
packing, resolutions and conservative bounds that omit unnecessary overflow nodes.

Accumulated unsaturated raw errors are informational, as explicitly agreed:

| Accumulated path | H error | Opponent error | Signed-energy error |
| --- | ---: | ---: | ---: |
| Color from float32 appearance inputs | `1.15857e-5` | `1.08887e-5` | `2.31099e-5` |
| Linear + Tone + Color from RGB | `6.28358e-5` | `2.58054e-4` | `1.25356e-4` |

Strong scale and near-pole response transforms amplify earlier rounding; these
are neither final RGB errors nor additional `1e-5` local gates. Absolute and
relative energy errors, worst inputs and every local/raw comparison are retained
in [color-metrics.json](../../../../buck-out/nodes-stage3-final/color-metrics.json).
Saturated raw states deliberately differ from the unchanged float64 reference:
four constructed cases have energies near `1.63e40`, `2.27e39`, `−2.87e40` and
`−1.23e40`; native energy is signed `FLT_MAX` with explicit flags. They still
pass the full guarded RGB gate.

All five CPU guard tests and 14 GPU guard cases pass independently:

| Guard check | Gate | CPU maximum | Available GPU maximum |
| --- | ---: | ---: | ---: |
| H–K coordinates | `1e-5` | `2.02935e-7` | `3.53562e-7` |
| H–K carried energy | `1e-5` | `2.44019e-6` | `2.44019e-6` |
| Returned boundary radius | `2e-5` | `1.57196e-5` | `1.62929e-5` |
| Isolated guarded RGB | `1e-4` | `2.44202e-5` | `2.48430e-5` |

The geometry field passes 183,680 independent preparation probes with radius
error `1.06239e-5`. Native radius and Pole Margin describe the returned result,
including neutral fallback. See [BOUNDARY.md](BOUNDARY.md) and the GPU
[guard receipt](../../../../buck-out/nodes-stage3-final/full-gpu/guard-internal.json).

## Node and resource costs

These are actual expanded counts, including nested occurrences, interfaces,
samplers, endpoint adapters, alpha and diagnostics:

| Graph | Shader nodes | Compositor nodes |
| --- | ---: | ---: |
| Guarded reset | 440 | 429 |
| All active | 915 | 866 |
| All active with saturation stress | 966 | 917 |
| Maximum controls, zero Adaptance tail | 975 | 926 |
| Maximum controls, active Adaptance tail | **998** | **946** |
| Raw Linear + Tone regression maximum | 218 | 221 |

The strict `<1000` complete-graph and `≤300` raw-stage caps pass. The earlier
200-node raw-stage optimization goal remains unreached. Full reports reuse
immutable preparation selected by Shader for Compositor, including a 2D Web
atlas where needed. The separate benchmark builds each context independently
and records the default representation it actually selects.

Maximum bound helper payload is **39,663,040 bytes (37.83 MiB)**, with at most
24 Shader / 10 Compositor sampler nodes. Payload means image width × height ×
16 bytes for RGBA32F; it is not measured Blender allocation or VRAM. Prepared
host tables can also retain an unbound alternate representation. The boundary
field alone is 2,634,768 bytes; active Tone uses 16,384 bytes. Each returned group
owns independent packed Non-Color/channel-packed images with half precision off.

A default graph starts with 1D Web coefficients and retries once with a validated
2D H/hue parameter field if needed for the budget. The fallback changes sampling,
preparation and storage cost, not the grading equations. Over-budget candidates
release their resources; a second failure raises explicitly. Finite sweeps do
not prove every continuous control combination, and the builder enforces the
budget on every graph it returns.

## Tests and source receipts

Nine Buck targets pass 46 tests in build
`86dbf585-3cb5-420a-b50b-33950c977fa9`: preparation (11), color_preparation (10),
reference (5), native (4), stages (2), guards (5), saturation (3), full (4), and
architecture (2). The concurrent Color target hit the external runner's default
600-second timeout during its final seam test, after six tests passed. Its
seven-test direct rerun against the same pinned Buck-built dependencies passed
in 619.584 seconds, with matching start/end runtime, oracle and test-source
hashes. This completes **53 tests**; no numerical gate changed. The
[direct log](../../../../buck-out/nodes-stage3-final/color-tests-direct.log) and
[color metrics](../../../../buck-out/nodes-stage3-final/color-metrics.json) retain the
exact command, interpreter/launcher identities and archive hashes. This rerun
does not claim a new Buck build ID. Future Buck reproduction can use
`buck2 test //products/perceptual-grade-next-blender/tests:color_stages -- --timeout 1800`.

Tests cover stage handoffs, significant energy signs, false saturation, exact
reset/black and alpha, all scene spaces, maximum controls with active tails,
strict node budgets, resource independence, retry/failure cleanup, parameter-row
isolation, private package boundaries and packed save/reopen without registration.
The reference target also checks that every UI settings record is JSON serializable.

All six reports are from build `56e0c120-2ec1-4409-b8ba-220a642e5462`. They share
21 runtime/evaluator source hashes and 10 oracle hashes, all matching the checkout.
Oracle hashes also match the initial development baseline. All recorded identities match the checkout.
Full reports and GPU guard receipts also pass start/end source checks. The
[report summary](../../../../buck-out/nodes-stage3-final/reports-summary.json) records
canonical paths, stable copies, complete identities, errors, resource costs and
individual report SHA256 digests. Stable reports are:

- [Full CPU](../../../../buck-out/nodes-stage3-final/full-cpu/report.json),
  [full UI](../../../../buck-out/nodes-stage3-final/full-ui/report.json), and
  [full GPU](../../../../buck-out/nodes-stage3-final/full-gpu/report.json).
- [Raw CPU](../../../../buck-out/nodes-stage3-final/raw-cpu/report.json),
  [raw UI](../../../../buck-out/nodes-stage3-final/raw-ui/report.json), and
  [raw GPU](../../../../buck-out/nodes-stage3-final/raw-gpu/report.json).
- [GPU sampling checks](../../../../buck-out/nodes-stage3-final/full-gpu/sampling.json)
  and [GPU internal guards](../../../../buck-out/nodes-stage3-final/full-gpu/guard-internal.json).

Earlier failed/interrupted runs are retained under the development directory and
`pre-json-fix/`, `full-ui-json-failure/`, and earlier sampler archives. They do not
replace the final source-bound receipts above. Historical Stage 1–2 evidence
below retains its original source scope.

## Image-sized evaluation cost

Benchmark build `5e4aef70-a5ce-45b3-acd2-74cfd1205cd3` passes: **24 fresh
processes / 192 renders**, 1024 × 1024 pixels, three processes per variant/context
and seven warm evaluations per process. It ran sequentially after all accuracy
jobs finished, on Linux with two Intel Xeon Gold 6530 CPUs (128 logical CPUs).
All process outputs are deterministic; the benchmark shares the acceptance source
identities and passes its own start/end source check, including `benchmark.py`.

Outputs use uncompressed 32-bit EXR to remove output-entropy compression bias.
Every render wrote exactly 50,382,786 bytes across three files. Identical input
pixels are republished outside the timed interval to prevent unchanged-image
cache hits. **Fixture time includes rendering, diagnostics, EXR writes and
readback. Render time includes EXR writes but excludes Python readback.** Neither
isolates shader cost. All figures below are seconds; warm entries are median
and median absolute deviation (MAD) across 21 measurements.

| Context | Work | Web | Cold fixture median | Warm fixture median / MAD | Warm render median / MAD |
| --- | --- | --- | ---: | ---: | ---: |
| Shader | Passthrough | none | 1.643 | 1.598 / 0.613 | 0.240 / 0.016 |
| Shader | Linear + Tone | none | 0.924 | 1.086 / 0.144 | 0.240 / 0.030 |
| Shader | Full, default | 2d | 1.237 | 1.298 / 0.086 | 0.395 / 0.014 |
| Shader | Full, explicit 2D | 2d | 1.598 | 1.683 / 0.435 | 0.411 / 0.021 |
| Compositor | Passthrough | none | 1.123 | 1.338 / 0.289 | 0.075 / 0.005 |
| Compositor | Linear + Tone | none | 1.132 | 1.074 / 0.254 | 0.099 / 0.018 |
| Compositor | Full, default | 1d | 1.774 | 1.817 / 0.404 | 0.145 / 0.010 |
| Compositor | Full, explicit 2D | 2d | 1.366 | 1.476 / 0.201 | 0.141 / 0.010 |

| Context | Work | Preparation median | Construction median | Nodes | Bound RGBA32F bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| Shader | Passthrough | 0.001 | 0.058 | 2 | 0 |
| Shader | Linear + Tone | 0.014 | 0.525 | 217 | 16,384 |
| Shader | Full, default | 6.507 | 33.737 | 915 | 36,910,208 |
| Shader | Full, explicit 2D | 22.924 | 8.825 | 915 | 36,910,208 |
| Compositor | Passthrough | 0.001 | 0.056 | 3 | 0 |
| Compositor | Linear + Tone | 0.014 | 0.591 | 220 | 16,384 |
| Compositor | Full, default | 9.900 | 10.131 | 945 | 4,355,696 |
| Compositor | Full, explicit 2D | 22.115 | 9.073 | 866 | 36,910,208 |

Preparation includes fresh boundary geometry, which callers can retain and reuse.
Construction includes the fixture and, for default Shader, the failed 1D candidate
and subsequent 2D preparation/rebuild. Explicit atlas preparation moves that work
into preparation. These columns are separate medians, not a median total.

Both Shader full variants select the same 915-node 2D graph, so their timing
difference is variability, not a strategy speedup. Fresh Compositor default
preparation retains 1D Web fields: 945 nodes and 4,355,696 pixel bytes. Explicit 2D
uses 866 nodes and 36,910,208 bytes. Its 0.141-second warm render median versus
0.145 seconds for 1D differs by less than the roughly 0.010-second MAD of either
variant. **The 2D option reduces node count but this run does not establish a
native evaluation speedup.** It costs more preparation and storage. The default
1D path remains useful whenever it fits the node budget.

Total fixture timings show substantial process/readback variability; the JSON
retains every measurement, per-process medians, percentiles and extrema. No
baseline subtraction, isolated-shader timing, hardware-GPU timing or product
latency claim is made. The earlier ZIP run is archived as a partial diagnostic
and is not mixed into these results.

[Benchmark JSON](../../../../buck-out/nodes-stage3-final/benchmark/report.json),
[summary](../../../../buck-out/nodes-stage3-final/benchmark-summary.json),
[host/provenance](../../../../buck-out/nodes-stage3-final/benchmark-host.json), and
[individual processes](../../../../buck-out/nodes-stage3-final/benchmark/processes/)
contain the complete receipts. The final benchmark JSON SHA256 is
`20deba473bda998e4762d83774beca936b77f9dfaa5ff7aa6d24b7c5d7754309`.

---

# Historical Linear + Tone acceptance — 2026-10-28

Artifact links in this section preserve the original report/build paths. Some
historical files are absent from this checkout, so those links cannot currently
be used to reverify their receipts. They have not been replaced with current
artifacts, whose source scope and implementation differ. Current handoff
validation is recorded at the top of this document.

The standalone Fit −2…3 / Quintic 512 implementation passes its required
Blender 5.2.2 CPU acceptance. The final reports share the same nine runtime and
evaluation source hashes and five reference source hashes; these match the
evaluated checkout. Existing products, root aliases and Git state were not
modified by this experiment.

| Evaluation | Cases × pixels | Worst normalized RGB error | Result |
| --- | ---: | ---: | --- |
| Cycles Shader + full-precision Compositor CPU | 42 × 1024 | 7.7431e-6 | Pass |
| CPU with UI boundaries and minimum-gap anchors | 348 × 1024 | 5.0531e-5 | Pass |
| Eevee + full-precision Compositor GPU, software OpenGL | 42 × 256 | 3.5636e-6 | Pass |

The RGB gate is `max(abs(actual-reference))/(1+max(abs(reference))) <= 1e-4`
where reference decoder response magnitudes are at most 300. The main and UI
CPU reports separately measure 300 valid near-pole samples: worst normalized
error `1.3453e-4`. All reports have zero validity disagreements and finite
outputs. The 510 invalid CPU samples return exact black. CPU alpha is unchanged;
Eevee reconstructed alpha differs by at most `1.7882e-7`. The CPU near-black
maximum absolute RGB error is `1.3509e-8`.

The UI corpus uses all three scene spaces, signed HDR through ±1024, the
extension's control ranges intersected with Fit −2…3, source-white polygon
boundaries, all four peak presets, exact minimum neighboring-anchor distances,
and simultaneous minimum-gap anchors. Arbitrary matrix overrides and invalid
API values are tested separately from this precision corpus.

Active wrappers have at most 261 Shader or 264 Compositor expanded nodes,
including interface nodes, texture sampling, adapters, alpha and diagnostics.
Reset wrappers use 31/33 nodes; linear-only wrappers use 39/41. A packed active
Tone texture occupies 16 KiB. The 300-node cap passes; the aspirational 200-node
target is not reached. The worst wrapper leaves 735 additional nodes while
keeping a future complete graph below 1000. At that delivery, Stage 3's actual
fit was untested; the current complete-stage evidence above supersedes that scope.

The UI report's largest preparation scalar error is `7.1370e-6`. Independent
Fit-3 analysis covers 233 distinct anchor sets × four peaks: 932 comparisons and
157,644,572 scalar probes, with maximum `8.2532e-6`. Additional float32 rounding
boundary probes on the worst cases reach `8.7256e-6`, below the `1e-5` gate.
Preparation retains per-curve validation; finite sweeps do not establish a bound
over every possible setting. Fit 4 is rejected by the public API, and a private
table-construction regression verifies that the strengthened probes catch its
former sparse-probe false pass.

All 23 tests across five library-local Buck targets pass:

| Target | Tests | Buck build ID |
| --- | ---: | --- |
| `tests:preparation` | 11 | `774e461f-3f7b-4374-be25-82d78897fd76` |
| `tests:reference` | 4 | `774e461f-3f7b-4374-be25-82d78897fd76` |
| `tests:architecture` | 2 | `ab6537a0-92c1-487f-8d68-31f8b33dcb34` |
| `tests:native` | 4 | `ca0c6c22-5153-4a59-8c7b-d9e004892683` |
| `tests:stages` | 2 | `fb5be773-93e2-498a-9e8f-76c3dd5e2573` |

Native tests cover primitive stage handoffs, generic decoding, exact reset,
black/neutral behavior, alpha, singular authored matrices, independent resources,
partial-construction cleanup, and packed save/reopen without registration.
The runtime manifest owns exactly `kernel` and its declared `color_core`
dependency. The reference and Blender fixtures are development-only.

The CPU/UI reports were built with IDs
`0938989b-08ce-4ca8-b4fa-1d55c81ea1d9` and
`fa19b584-257d-4cb6-bad8-dda5420b77ec`. The GPU report also belongs to the former
build. Those Buck outputs are not retained in this checkout; the measurements,
build IDs, and digests below are the historical record. Recreate reports with
the current commands in [README.md](README.md).

The three final JSON SHA256 digests, in CPU/UI/GPU order, are:

```text
8adedf5625a5714315c385a2a43f200a27060bd789c92a7483e74ae735186b9d
1a64e2ac413264c941aeb56fe6687cc3889738e39b4c207fc64b95f166ac9f75
43d5d90447969c32605cb71ab2d110068e48aeef0c3dd5dfef76fb2100a5bb5e
```

Main-report active-case median preparation time is 16.1 ms. Median cold/warm
native evaluation is 20.8/17.7 ms for Shader and 10.1/9.1 ms for Compositor on
these 1024-pixel fixtures. They are fixture timings, not interactive product or
full-resolution rendering benchmarks.

GPU coverage uses OpenGL / Mesa llvmpipe, with Eevee values reconstructed from
mantissa/residual/exponent AOVs to avoid its float16 buffer quantization. This
checks compiled shader arithmetic; ordinary Eevee AOV storage is still float16.
Physical GPU drivers, Metal, product integration and the Color stage remain
outside this delivery.
