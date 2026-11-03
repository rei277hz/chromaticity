# Native Color parameter fields

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

The [independent absolute HDR report](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/absolute-hdr-validation.md)
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

The fresh [scalar audit](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/scalar-fixed/report.json)
passes all **31 distinct Tone functions**, with maximum conditioned error
**3.0973854e-6** against `1e-5`, and all **19 Web-parameter functions** under
their scoped policy. Raw Color, toe and Compact precision diagnostics remain
visible: **7 / 78**, **16 / 16** and **3 / 11** functions fail their raw
scalar limits. Their existing HDR admission policies remain in place; this
absolute-error report does not claim fresh admission against the historical
frozen baselines. The [combined regression receipt](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/tests.json)
passes **86 test methods across nine Buck2 targets**: 40 layout, 30 tool and
16 native/persistent/gate-policy methods.

The preceding schema-4 generation, complete-preparation and prepared-edit
timings remain historical measurements; they are not current schema-5 costs.
Accuracy-run durations are not performance evidence.

`color_prepare.py` prepares the reference Color schema without importing the old
Grade core, a product, Blender, or the reference package. The reference remains
an independent test dependency. The low/high split uses
`r=(35/75)*abs(J_A)` and frozen post-Tone selectors. Color fits retain `[-2,6]`;
the separate Tone table uses Fit `[-2,2]` and the 256-cell Quintic field.

These are parameter fields, not an RGB grading LUT. Pixel-dependent drivers,
signed energy, radial maps, response transforms and export guards are evaluated
by native nodes. Preparation provides exact host functions `terms(H)`,
`web_parameters(H)`, `web_toes(H)` and `adaptation_parameters(H)` for validation.

## Historical schema-4 layout reduction study

These retained results describe the preceding schema-4 sources and layouts.
They are not current schema-5 timing or combined-layout acceptance evidence.

Twelve independent reductions were measured from the fixed schema-4
Compact-only layouts. All other fields retain their current sizes for each
comparison; there is no Interior field and no runtime promotion. The full CPU
study has **149 cases × 1,024 inputs × three spaces × two contexts**:
**894 baseline + 10,728 candidate rows**, independently reconciled by
**75,983,224 assertions**. Generation is the fresh all-active median.

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

HDR compares the reference, current native graph and reduced native graph after the pinned ACES 2.0 HDR-1000 Rec.2020 view with Rec.2100-PQ applied once, yielding fractional full-range 10-bit RGB codes. Signed added error is the per-pixel peak absolute candidate/reference error minus the current/reference error. Percent divides by the reference pixel peak, excluding denominators below one code. Code and percentage maxima can select different pixels. Movement and absolute reference error remain separate metrics.

Fresh pure-generation timing is uncontended, with OpenBLAS/OMP fixed to one thread: **four cases × five repetitions, 300 component samples**, source identities stable and runtime layout unchanged. Tone times `_build_table`; Color fields time `_generate_field`. Parameter preparation, dense scalar audits, hashing, native upload and grading are excluded. The table uses all-active medians; JSON also retains per-case minima/maxima and worst-case medians. Color 16,384 has a worst-case median of **9.114 ms**, with one sample reaching **10.049 ms**. Boundary rows report exact resident bytes only; offline geometry generation is not UI preparation. Independent generation reconciliation passes **2,949 assertions**, including 60 payload hash replays and isolation-order checks.

Complete all-active host preparation remains the separately measured **37.885 ms** from the source-matching current Compact-only receipt. Its retained Tone component of **1.180 ms** includes parameter preparation plus table generation, unlike the fresh pure-generation column. Component medians must not be added to estimate complete preparation. Boundary first host loading took **34.488 ms**, then its data are reused. This is resource loading rather than per-edit generation.

The [combined report](../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/breakdown.md)
and [EVIDENCE.md](EVIDENCE.md) retain exact source-bound metrics, failure
witnesses, full current inventory and prepared-edit phases. Older large-field
sensitivity denominators remain historical.

## Current layouts and admission

The user-directed schema-5 Compact-only implementation uses Tone **256**,
Color coefficients **8,192**, Web parameters **4,096**, Web toes **1,536**
and Compact Adaptance **3,072** cells. It has no Interior table. The actual
RGBA32F payload is **5,076,560 bytes**, or **2,441,792 without the fixed
boundary**. Runtime Tone is packed at 512 × 1 (8,192 bytes); the schema-4
sensitivity candidate used a different diagnostic 257 × 1 packing.

These image dimensions are fixed for the lifetime of a prepared tree.
Rebuild schema-4 trees. Immutable preparation rejects obsolete Tone sizes,
Color capacities and layout schemas; matching schema-5 payloads are reused.
The Tone control domain is now `[-2,2]`; Color fits retain `[-2,6]`.

The user-authorized maximum signed HDR worsening of **0.05 fractional 10-bit
codes** admits Color coefficients and Compact Adaptance, as well as the
separately scoped existing Web-toe policy. For those roles, scalar and local
precision remain measured diagnostics with their original raw limits and
pass/fail values. Safety, finiteness, significant sign, final RGB, containment,
validity/saturation flags and the original node budget remain requirements.
Other field roles retain their scalar/local admission policies. HDR uses the
pinned ACES 2.0 HDR-1000 / Rec.2100-PQ view with PQ once; signed worsening is
`max(abs(candidate-reference)) - max(abs(baseline-reference))` per pixel.

Both native graph builders use Compact Adaptance for all three calibrated
log gains and `log(k)`, for every authored adjustment and tonal height.
There is no gain threshold, Interior coordinate map or representation fallback.
The compact endpoint retains the analytic exterior normalization limit.
All-active preparation and persistent initialization allocate one Adaptance image.

## Historical schema-4 Compact-only comparison

The earlier schema-4 implementation used Tone 512, Color 16,384 and Compact
8,192. It stored 5,428,848 bytes and passed its separate 90 regression checks,
894-row CPU comparison and 36-row GPU strong-control comparison. That receipt
remains linked from [EVIDENCE.md](EVIDENCE.md); it does not certify schema 5.
Its complete preparation and prepared-edit times are historical.

## Packing and coordinate maps

Each immutable `ColorTable` has RGBA32F pixels, named field locations and a logical
cell count. Runtime tables leave audit errors unset and probe counts zero;
explicit development audits attach measured validation metadata. Compositor fields use native
bilinear sampling. Shader fields fetch nearest level-zero texels and interpolate
explicitly with native nodes: two fetches for each 1D field. The separate output
boundary geometry uses four texel fetches for a 2D sample; it is not a Color/Web
parameter field.
Implicit Shader image mipmaps can average unrelated parameter rows on GPU, so
ordinary image linear filtering does not preserve the parameter-field contract.

- Color coefficients: two semantic rows containing four lightness and four
  chroma coefficients. Coordinate is `clamp(H/high,0,1)*cells`.
- Web: 29 semantic rows. Rows 0–1 contain six source angles; rows 2–3 contain
  six target angles; row 4 is reserved padding. Starting at
  row 5, each source sector has two rows of angular quintic coefficients.
  Starting at row 17, each target sector has two rows of radial log coefficients.
  Selecting a sector changes the texture row, avoiding six-way socket selection.
  Each radial left endpoint has a constant per-handle whole-turn shift toward
  the principal angle range; native wrapping of `out_angle-left` preserves the
  periodic field while avoiding a large lift followed by subtraction. A wrapped
  difference just below a full turn, caused by endpoint rounding, selects the
  nearby left endpoint rather than the opposite end of the sector.
  Coordinate is `clamp(H/high,0,1)*cells`.
- Web toes: a separate one-row positive RGB field stores angular, chroma and
  scale toes at the same normalized height. It can use more cells without
  duplicating the 29-row angular/radial atlas. One logical toe sample uses two
  nearest texel fetches in Shader or one bilinear Map UV operation in Compositor,
  with no exponential decoding.
- Adaptance: one row contains three calibrated log gains and `log(k)`. Set
  `s=sqrt(aw/(3.05*400))*(H/100)**(1/(2*gamma))`; coordinate is
  `s/(1+s)*cells`. The endpoint at compact infinity uses the exact exterior
  normalization limit. It does not freeze normalization above the last anchor.

Runtime uses the per-role constants in `layouts.FIELD_CELLS`; it never selects a
resolution while preparing a user's edit. The `:audit_fields` development tool
searches the role's supported lattice (2048 through 524288 in powers of two,
plus Compact-only 3072 and toe-only grids from 256 through 2048 in steps of 256) and retains each
smaller candidate's failure witness. Its finite retained corpus certifies a
layout only within that corpus, not all possible control combinations. Current
selection receipts and unresolved gates are recorded in [EVIDENCE.md](EVIDENCE.md).
Physical segments contain at most 8192
cells and both endpoints. For semantic row `r` and floating logical coordinate
`p`, use:

```
segment = min(floor(p / segment_cells), segments - 1)
pixel_x = p - segment * segment_cells
pixel_y = r * segments + segment
```

Duplicated segment endpoints prevent linear interpolation across unrelated
rows. Physical height is padded to a power of two; the Web's 29 semantic rows
therefore occupy 32 row slots per segment. Integer row centers then have exact
binary normalized Y coordinates. A native regression found errors up to
`2.13e-5` from neighboring-row leakage without this padding, and bit-exact row
selection on both CPU contexts with it. `semantic_rows` excludes padding from
the host evaluator. A nonsegmented table needs no extra segment addressing. All textures are
caller-owned packed Non-Color/channel-packed float images; no global cache is
introduced.

Adaptance's calibrated response transform can amplify small parameter
interpolation errors. Independent native-stage measurements remain necessary
alongside parameter-field diagnostics; field accuracy alone cannot describe a
smaller resolution. Compact Adaptance admission follows the authorized HDR
rule above. Strong controls must be measured on the same Compact path as
ordinary controls; there is no second field whose samples can mask its error.

Historically, the dual-table implementation selected a linear-height Interior
field for calibrated log gains above one in magnitude. At frozen height
`47.1189113567`, its compact coordinate alone produced a log-gain error of
`2.67e-6`; linear height reduced that coordinate error to `6.44e-8`. These
retained observations describe why the former path existed, not a live schema
choice. Earlier specialized full-field reports could hide Compact sensitivity
because Interior supplied the three gains, even for smaller controls. Their
reported zero Compact movement is not evidence for the Compact-only runtime.

Web uses the 1D coefficient and toe fields above exclusively. The optional
H/hue atlas, its preparation API and native evaluation branch have been removed;
there is no automatic fallback when a complete graph exceeds the node budget.
During the handoff, oversized complete graphs may be constructed and evaluated,
but reports retain the original `<1000` requirement as a separate failed gate.
Optimizing the remaining 1D graph is pending. Generic 2D sampling stays available
for the independent fixed output-boundary seed.

## Internal accuracy contract

The table gate is `1e-5` for each channel:

```
abs(sampled - exact) / max(1 + abs(exact), conditioning_scale) <= 1e-5
```

The fixed scales depend on authored parameters, independently of validation
probes. They account for cancellation in signed fields:

| Field | Conditioning scale |
| --- | --- |
| Each lightness/chroma column | `1 + max(abs(authored four tonal values))` |
| Each web radial log coefficient | `1 + ln(2)*max(abs(authored handle stops)) + ln(1/.9)` |
| Each Adaptance log gain | `1 + max(abs(four calibrated log gains for that cone))` |
| Adaptance log normalization | `1 + 2*max(abs(calibrated log gains))` |
| Angles, quintic coefficients, toes and padding | 1; ordinary pointwise normalization |

The web coefficient bound follows from a toe no larger than one tenth of either
calibration radius. Physical and exterior response-ratio bounds give the
Adaptance normalization scale.

Pointwise normalization alone is unattainable near some valid signed-coefficient
zero crossings. At Fit 6, a maximal alternating lightness case has a high-driver
coefficient `0.01058139238` at normalized height `0.6306918561458589`. Rounding
only that coordinate to float32, then evaluating the exact function, changes
the coefficient by `0.00012795760`, a pointwise normalized error `1.26618e-4`.
Increasing texture resolution cannot remove this coordinate rounding floor.
The preparation test retains this regression explicitly.

Audit metadata preserves the fixed per-channel scales, each channel's conditioned
error, worst pointwise error and worst exact-function error from coordinate
rounding. Validation probes cells, tonal anchors, compact response transitions,
endpoints and float32 rounding-bin boundaries. Failure at the maximum resolution
is explicit in development acceptance. Production does not repeat these dense
probes or weaken their thresholds. It retains coefficient-generation operations
needed for monotonicity and cheap input, geometry and finite-value checks.

Sensitive downstream operations have additional interpolation budgets at the
represented float32 coordinate: chroma coefficient channels and Web radial log
coefficients have a `3e-6` absolute budget, and positive Web toes have a `1e-6`
relative budget. A native sector-seam regression exposed a `1.73e-5` absolute
log-scale error at an alternating-control zero crossing despite passing the
conditioned field gate; the additional budget retains accuracy after exponentiation. These
keep exponentiation and the quartic radial toe from amplifying otherwise small
field errors. Metadata reports these interpolation errors and relative mapper
errors separately; the original conditioned `1e-5` gate still includes input
coordinate rounding. Neither supplementary budget replaces the native substage
gate at identical float32 handoffs.

The user-authorized policy permits `1e-4` for both Web-parameter scalar
errors (conditioned and absolute radial-log interpolation), both Web-toe scalar
errors (conditioned and relative), and native Web local H/opponent/energy and
returned-scale accuracy for the exact `web_alternating_extremes` checkerboard.
The policy matches the settings pattern and uniform 0/±360° seam rotations.
Ordinary Web functions, terms, Adaptance, final-scale multiplication, boundary,
RGB, validity, saturation and node-budget gates retain their original limits.
The [case-specific studies](GATE_REVIEW.md#case-specific-web-parameter-sizing-study)
select 4,096 Web-parameter cells with 32,768 Web toes within the supported grids,
with complete lower-size failure witnesses and native local/seam validation.
That scalar/local study retained 32,768 parameter and 524,288 toe cells.
The subsequent [HDR toe admission](GATE_REVIEW.md#authorized-web-toe-hdr-admission)
promotes 1,536 toe cells with maximum signed worsening `0.0393597186` codes
against the original toe. Toe scalar/local precision is now diagnostic for
layout admission; other roles' gates and the retained safety/final-output
checks still apply. Development audits
and tests use the centralized `tools/gate_policy.py` policy; runtime preparation
still generates its fixed layout without a dense audit or case-name heuristic.
The legacy generic `audit_color(select=True)` search retains strict defaults;
use the policy-aware `:audit_fields` tool for corpus selection.

Native quintic blending evaluates the equivalent positive expression
`t³ * (1 + (1-t)*(3 + 6*(1-t)))`. This avoids cancellation near `t=1`
without changing the reference polynomial. At extreme opposite Web controls,
the conventional expanded polynomial's float32 error was amplified by the
32-stop log-gain difference. Sector-seam tests include adjacent float32 inputs
and common full-turn hue rotations.

These field metrics do not replace native raw-stage measurements or end-to-end
RGB gates. For Color coefficients, Compact Adaptance and Web toes, the raw
scalar/local limits remain diagnostic under the authorized HDR admission rule.
Saturated native states must be reported against the unchanged float64 reference;
final output guards cannot certify raw-stage precision.

Each unsaturated Color substage is also evaluated independently against the
reference at identical float32 input states and frozen post-Tone selectors.
Let `C_i` be input opponent magnitude and `C_ref` the reference output magnitude;
`E_i` and `E_ref` are their carried signed energies. The fixed comparison scales
for that sample are:

```
S_C = 1 + C_i + C_ref
S_E = 1 + abs(E_i) + abs(E_ref) + 66*(C_i + C_ref)
S_H = 1 + sqrt(abs(E_i) + 66*C_i) + sqrt(abs(E_ref) + 66*C_ref)
```

For strict native arithmetic regressions with the legacy fine toe, the maximum
`abs(delta_H)/S_H`, Euclidean opponent error
`hypot(delta_a, delta_b)/S_C`, and `abs(delta_E)/S_E` must each be at most `1e-5`.
Energy signs must agree wherever `abs(E_ref) > 1e-5*S_E`. Absolute energy error
and `abs(delta_E)/(1+abs(E_ref))` are additional diagnostics. Returned Web scale
has its own relative `1e-5` gate. These definitions are implemented by the
development oracle's `state_metrics`; they do not replace the unchanged grading
equations. Accumulated raw errors across substages are reported separately,
as agreed, and every complete guarded sample retains the `1e-4` RGB gate.

The alternating maximum Web chroma/scale regression exercises the dense toe
path. The original 524288-cell, 8389632-byte layout is retained for strict
arithmetic regressions and HDR comparison. Runtime allocates 1536 cells,
1537 unique height samples and 24592 bytes independently of the angular/radial
table. Its scalar/local precision is reported under the authorized HDR toe
policy rather than admitted by the strict precision thresholds above.
Selected resolutions, per-field errors, preparation
time and owned RGBA32F pixel bytes are retained in the full evaluation report.
Pixel bytes exclude driver allocation and cache overhead.
Runtime preparation generates these fixed layouts once for each changed
dependency. Development resolution sweeps and dense numerical audits have their
own timing fields; neither belongs to production drag preparation.

The removed 2D Web option and its earlier storage/preparation measurements are
preserved only in the historical section of [EVIDENCE.md](EVIDENCE.md). They do
not describe the current runtime. Specialized-builder receipts identify active
Web as `1d` or `none`. Persistent graphs retain all 1D Web resources even while
their stage is bypassed, and report their full resident payload without an
alternate atlas.

`PreparedColor.finite_bounds(H_bound)` is a conservative optimization aid.
Failure to establish a small range leaves native saturation operations enabled;
it does not reject controls, change equations, or alter the reference model.

Here `H_bound` bounds the post-Tone **magnitude**
`M=sqrt(abs(E0)+66*C0)`, including negative carried energy. Consequently
`abs(J_A0)<=M`, `C0<=M²/66` and `abs(H0)<=M` hold on both signed branches.
The proof partitions the entire source ratio `u=C0/abs(J_A0)` into intervals,
including zero and the unbounded tail. Within `[l,r]`,
`C0<=min(r*M,M²/66)`, the low-chroma membership lies between its two monotone
endpoint values, and Adaptance reach is at most
`half⁴/(half⁴+l⁴)`. The zero origin is covered separately by the same envelope.
Taking the largest absolute tonal coefficient combination at the membership
endpoints bounds each interval's lightness/chroma change. Hue directions have
unit norm, visibility is at most one, and tonal interpolation is convex.

For resulting bounds `abs(H)<=h` and `C<=c`, signed energy obeys
`abs(E)<=(h+sqrt(66*c))*(h+3*sqrt(66*c))`. Triangle bounds on inverse opponent
rows then bound every incoming cone response. An interior response remains
within 400 and can grow by at most its positive gain; an exterior response can
grow by at most the inverse square of its gain. Applying each interval's reach
to the stored log-gain/log-normalization hulls preserves the correlation that
a large source chroma ratio suppresses Adaptance. Maximizing these envelopes
over all intervals is a domain bound, independent of test pixels.

Native arithmetic uses stricter thresholds than the representable limit:
the general `2^120` pruning threshold leaves approximately 256-fold headroom
below float32 maximum; squared intermediates require lower thresholds.
These margins accommodate floating-point rounding and keep an inconclusive
bound on the protected path. They do not certify numerical accuracy, which
remains subject to the independent internal and end-to-end gates.

There is a separate float32 proof for `sqrt(abs(E)+66*C)` at finite native
energy handoffs. If both pre-Adaptance and final chroma bounds are below `2^96`,
then `66*C < 2^103`, half the spacing at float32 maximum. Adding it to any finite
`abs(E)` therefore rounds to a finite value, including when `E` has saturated
to float32 maximum. This permits the direct expression instead of a scaled norm
without admitting infinities or changing the signed-energy saturation policy.
