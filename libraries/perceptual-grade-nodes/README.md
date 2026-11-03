# Perceptual Grade native nodes

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

## Historical schema-4 sensitivity and Compact-only timing

The following results retain their schema-4 source/layout identities and do
not measure the current schema-5 layout.

**The preceding sensitivity and timing study is complete.** The schema-4 Compact-only
baseline used Tone 512, Color 16,384, Web parameters 4,096, toes 1,536,
Compact 8,192 and boundary 513 × 321. Twelve independent reductions were
measured; no runtime size or admission policy changes. The full CPU study has
**894 baselines + 10,728 candidate rows**, independently reconciled by
**75,983,224 assertions**. A separate 17-control software-GPU subset has
**102 + 1,224 rows** and **8,989,366 reconciliation assertions**.

The [combined breakdown](../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/breakdown.md)
and [complete tables](EVIDENCE.md) report current-to-smaller bytes, pure
generation, added HDR codes and percent of reference peak. Current all-active
pure generation is **0.936 / 8.099 / 11.481 / 1.977 / 2.212 ms** for Tone /
Color / Web parameters / toes / Compact. Complete preparation stays the
separately measured **37.885 ms**. Current payload is **5,428,848 bytes**.

Numerical failures remain visible: CPU toe 768 and reduced boundaries add
4 / 2 / 6 final-RGB failed rows; Tone reductions retain required scalar
failures. The current software-GPU baseline already fails six alternating-Web
rows, with maximum absolute reference error **337.422683788 HDR codes** on a
nearly neutral input. Reduced boundaries add 2 / 4 GPU failing rows; the other
candidates add zero. All candidate rows remain finite and pass alpha/containment,
with unchanged validity/saturation flags. A small added error does not admit a
candidate or resolve the retained GPU failure. Fresh generation is source-stable;
the unchanged-runtime software-GPU edit receipt retains its 16² diagnostic scope.

**Historical schema-4 Compact-only implementation.** Every adjustment used
the fixed **8,192-cell Compact table** in both specialized and persistent
graphs. Interior storage and the gain-dependent representation choice have been
removed. Layout schema 4 keeps Color coefficients at 16,384 cells, Web
parameters at 4,096 and Web toes at 1,536. The fixed payload is
**5,428,848 RGBA32F bytes**, including the 2,634,768-byte output boundary, or
**2,794,080 bytes without it**. This saves 1,048,704 bytes (16.19%) relative to
the preceding dual-table graph. Existing persistent trees must be rebuilt.
All 90 regression checks across eight Buck2 targets pass. Independent CPU
validation passes 32,668,186 assertions over the full matched corpus, and all
36 software-GPU strong-control rows pass. Fresh uncontended preparation and
software-GPU edit timing are complete; earlier receipts below retain their
historical scope.
The existing 0.05-code maximum HDR-worsening policy and its retained safety,
final RGB, containment and semantic-flag gates remain the Compact contract.
The original full-grade node budget and Next product integration remain open.

This standalone library constructs native Blender Shader and Compositor graphs
for Linear → signed appearance → Tone → Color → H–K repair → AP1 output boundary.
The [goal](../../products/perceptual-grade-next-blender/GOAL.md), [checklist](../../products/perceptual-grade-next-blender/CHECKLIST.md) and
[evidence](EVIDENCE.md) distinguish current work from accepted historical results.
The 2026-10-30 [audit follow-up](GATE_REVIEW.md) records the field-size policy
and downstream sensitivity. Compact-only payload consists of Tone 16,384;
Color coefficients 524,352; Web parameters 2,097,664; Web toes 24,592;
Compact Adaptance 131,088; and output boundary 2,634,768 bytes. No Interior
texture is part of this inventory.

The Compact-only CPU comparison covers 149 cases × 1,024 inputs × three
spaces × both contexts, using prepared-tree updates and a frozen preceding
dual-table baseline. Maximum added HDR error is **0.0000304877758 codes**,
or **0.0000156437481% of reference peak**; validity/saturation flags do not
change. Maximum absolute reference error remains **7.98566659944 codes** in
both paths. Native node counts fall from 1,468 / 1,399 to **1,445 Shader /
1,382 Compositor**, with six resident images instead of seven; the original
node cap remains unmet. The [independent validator](../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/independent-validation.md)
replays 447 float64 references and reconciles all 894 paired rows. The separate
36-row llvmpipe/Eevee and full-precision GPU Compositor strong-control check
adds at most the same code error, or **0.0000208583307% reference peak**,
with unchanged flags. That targeted check does not replace the retained
software-GPU extreme-Web finding.

The fresh [preparation report](../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/preparation-costs/report.md)
has 20 source-stable preparations over four cases. All-active preparation is
**37.885 ms**, with **2.225 ms** Compact generation. Color generation medians
are 8.135–9.094 ms; the largest individual Color sample is 10.190 ms. The
[prepared-edit report](../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/prepared-edit-costs/report.md)
uses a 16² software-GPU fixture and requests all 254 available logical CPUs.
Repeated end-to-end edits span **463.626–516.755 ms Shader /
93.847–114.391 ms Compositor**. Exposure is 470.200 / 93.847 ms. These costs
include fixture evaluation and EXR readback and do not isolate per-frame
Grade-only rendering or full-resolution preview latency. The [combined breakdown](../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/breakdown.md)
and [EVIDENCE.md](EVIDENCE.md) retain phase details and raw precision diagnostics.

## Historical dual-table Color/Compact promotion

The receipts in this section use the preceding layout schema 3, including a
65,536-cell Interior table, and total **6,477,552 RGBA32F bytes**. They retain
their measured source identities and do not establish strong-control accuracy
or timing for the Compact-only implementation. The earlier
[`web-parameters-4096-20261030`](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/)
regression, GPU and timing reports measured 131,072 Color cells and 16,384
Compact Adaptance cells. They are historical and do not certify the promoted
source's hashes, payload or performance. The preceding [breakdown](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/breakdown.md)
includes source-bound texture, preparation, persistent HDR and software-GPU
prepared-edit reports. The [runtime regression receipt](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/tests/summary.md)
passes all 63 checks across seven targets and verifies obsolete/current layout
reuse; a separate 24-check receipt covers the HDR runner.

The independent [persistent HDR validator](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/hdr-validation.md)
passes 894 baselines and 2,682 measured candidate rows across all 149 cases,
three spaces and both CPU contexts. Maximum added error is **0.0115159237
codes / 0.00529889482%** for Color, **0.00128048658 codes /
0.000361764104%** for Compact, and the Color maximum for their combined
promotion. All pass the 0.05-code layout budget, final RGB, containment and
unchanged validity/saturation checks. Maximum absolute reference error is
7.9856666 codes in both baseline and combined candidate. The Compact promotion
removes seven expanded nodes, leaving 1,468 Shader / 1,399 Compositor; the
original node cap remains failed separately.

The historical CPU comparison passes final RGB and containment. Its software-GPU HDR run
has six baseline and six candidate failures, all on the near-neutral
alternating-Web witness. The refreshed software-GPU GUI report also records
**60 of 960** extreme-Web numerical failures, with maximum normalized
scene-linear error `0.000193902526` against `1e-4`. Timing coverage does not
establish numerical acceptance. The retained 1,536-cell toe sweep adds at most
**0.03935971856 fractional 10-bit codes**, or
**0.1514492587%** of the reference pixel peak, against its explicit 524,288-cell
baseline; 1,280 cells exceeds the 0.05-code ceiling.

The separate isolated Color/Compact candidate study measures Color 16,384 at
8.091 ms generation all-active, with every sample in that harness below 10 ms.
The current full-preparation run records Color medians below 10 ms but has
individual samples above it. Compact 8,192 halves its stored bytes. Its
isolated normalized opponent error is `1.22195872e-5` versus
the raw `1e-5` limit before display/PQ; this remains diagnostic under the
authorized HDR admission policy. The older specialized full-field HDR corpus
has zero Compact movement because its Interior lookup can mask Compact
effects. The new persistent report measures the common-control Compact path
and observes nonzero sensitivity. [EVIDENCE.md](EVIDENCE.md) preserves both scopes.

The fresh [host-only preparation report](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/preparation-costs/report.md)
has 20 runs with stable sources. It measures **8.146 ms** all-active Color
generation, **2.232 ms** Compact generation and **43.838 ms** complete
all-active preparation. Four-case Color generation medians are 8.146–9.136 ms;
individual samples reach 11.786 ms. Component generation and complete
preparation are separate measurements and must not be added. These costs
exclude graph construction, upload and evaluation.

The pre-promotion host-only preparation report has 20 rows and records
**10,279,104 resident bytes**, **11.84 ms** all-active Web parameter generation
and **102.35 ms** complete preparation. It used the prior 131,072-cell Color
and 16,384-cell Compact layouts. The previous 32,768-parameter report records
24,960,704 bytes, 96.09 ms parameter generation and 184.76 ms complete
preparation. These earlier measurements retain their historical source scope.

The historical [Web sizing studies](GATE_REVIEW.md#case-specific-web-parameter-sizing-study)
measured a 4,096-parameter / 32,768-toe candidate under the case-specific
alternating-extreme scalar/local policy. Its [cost receipt](../../buck-out/persistent-grade-evidence/preparation-costs-web-4096-toe-32768/report.md)
retains that old experimental layout and is separate from the current
4,096-parameter / 1,536-toe runtime.

Historical downstream sensitivity is retained below. These rows use the old
32,768-parameter / 524,288-toe comparison baseline, and code and percentage
maxima can occur at separate pixels; they remain distinct from the new matched
32,768-parameter / 1,536-toe baseline.

| Historical part | Maximum added error (codes) | Maximum added error (% reference peak) |
| --- | ---: | ---: |
| Interior Adaptance parameters/16,384 | `4.57316637e-05` | `4.34075537e-05%` |
| Web parameters/4,096 | `0.0404496565` | `0.145224804%` |
| Web toes/1,536 | `0.03935971856` | `0.1514492587%` |

The interior Adaptance row's `0.00147865713` value is movement; its added-error
maximum is `4.57316637e-05` codes. The Adaptance and Web-parameter rows are from
the historical [HDR end-to-end report](../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/sensitivity.md);
the 1,536-toe row is from the retained
[toe HDR sweep](../../buck-out/persistent-grade-evidence/toe-hdr-005/sensitivity-percentages.md).
Percentages exclude reference peaks below one code; absolute errors remain
recorded for those pixels. [EVIDENCE.md](EVIDENCE.md) retains examples for every
texture role and the separate scalar/local failures.

The float64 [`perceptual-grade-reference`](../perceptual-grade-reference/README.md)
is the independent development oracle. Runtime code depends only on `color-core`
and NumPy; Blender evaluates the pixels. There is no input RGB repair, 3D RGB
grading LUT, Python pixel evaluator, inverse grade, UI or product registration.
The old `perceptual-grade-core` and Blender extension remain preserved. The
rebuilt Blender product composes portable settings/preparation from this
component and owns native graph installation, publication, persistence, and its
state-machine policies.

## Numerical path

Linear supports exposure, source white, reference-convention balance, spread,
heading and an authoritative XYZ matrix override. The context is D65/203 nits,
with scene endpoints in Linear Rec.709, Linear Rec.2020 or Bradford-adapted ACEScg.
The appearance encoder retains signed energy and stable opponent differences.
Tone uses the user-directed Quintic 256 coefficient field and independent Fit
range `[-2,2]`. Exact reset Tone bypasses its computation; persistent graphs
retain the initialized coefficient image and nodes.

Color has four tonal rows of low/high chroma and opponent lightness/chroma
controls, global chroma gain, the six-handle tonal web, selective Adaptance and
web final scale. Color Fit remains `[-2,6]`. Selectors are frozen from the original
post-Tone state: `r=(35/75)*abs(J_A)`, visibility `C²/(C²+4)`, and low/high shares
`r²/(C²+r²)` and `C²/(C²+r²)`. Signed energy is carried independently, preserving
negative and cancellation-sensitive states. The [field specification](COLOR_TABLES.md)
records parameter packing, coordinate maps and independent acceptance gates.

Adaptance uses the 3,072-cell Compact field for all adjustments, including
strong centers. The same four stored functions supply both graph builders:
three internal response log gains and log normalization. Its bounded
coordinate map covers the full tonal range and retains the analytic exterior
tail. Authored center positions and reference calibration equations are
unchanged. No Interior texture or gain-dependent texture route remains.

H–K repair runs once at export; it is not idempotent. The boundary guard preserves
legal decoded values and otherwise projects at fixed achromatic energy and hue
using packed geometry seeds, native decoder corrections and a decoded legality
check. The [boundary specification](BOUNDARY.md) records the seed, safeguarded
Halley correction and independent native radius/containment gates. Containment is in the reference's Bradford-native AP1 `[0,1024]` cube.
Scene-space RGB can legitimately be negative after its endpoint adapter. Black
and white energy endpoints have explicit behavior. No ordinary RGB clipping
substitutes for the projection.

Stable norms, ratios and response differences precede float32 overflow handling.
Unavoidable overflowing native results saturate to signed `FLT_MAX` and set the
`Saturated` diagnostic; an unused branch does not set that diagnostic. The
reference remains float64 and unchanged. Saturated raw states cannot claim
internal parity. NaNs remain failures. Conservative preparation bounds select
precision routes; persistent graphs retain every alternative. Those bounds do
not reject authored controls.

## API and ownership

Importing `color_tools.perceptual_grade_nodes`, including preparation, does not
import Blender. Construct graphs only inside the supported Blender host:

```python
from color_tools.perceptual_grade_nodes import (
    LinearSettings, ToneSettings, ColorSettings, WebSettings, prepare,
)
from color_tools.perceptual_grade_nodes.graph import build_group

prepared = prepare(
    LinearSettings(exposure=.7),
    ToneSettings(input_nits=(0., 8., 40., 235., 1150.), fit=0),
    'Linear Rec.709',
    color=ColorSettings(global_gain=.2,
                        adaptance=((2., -1.), (0., 0.), (0., 0.), (0., 0.))),
)
built = build_group(prepared, 'ShaderNodeTree')  # or 'CompositorNodeTree'
```

For interactive edits, initialize one persistent group with every stage and
optional Color path present, including currently bypassed fields:

```python
from dataclasses import replace
from color_tools.perceptual_grade_nodes import Settings, prepare_update
from color_tools.perceptual_grade_nodes.persistent import build_persistent

settings = Settings()
prepared = prepare(full_fields=True)
built = build_persistent(prepared, 'ShaderNodeTree')

settings = replace(settings, linear=replace(settings.linear, exposure=.7))
candidate = prepare_update(settings, built.prepared)
# The host must exclude every native reader for this synchronous mutation.
receipt = built.apply(candidate, expected_revision=built.revision)
```

`Settings` is a complete authored snapshot: preserve other active stages when
replacing one control. `prepare_update` reuses unchanged immutable fields;
Linear edits do not regenerate Tone/Color payloads. A Tone change regenerates
Color fields only when the derived Color inputs change. Production preparation
generates one fixed layout per field, with no resolution search or dense oracle
gate. Runtime Tone construction retains its monotonicity certification;
`:audit_fields` performs the dense accuracy and layout checks separately.

`PersistentGrade.apply` preserves native trees, nodes, images and image dimensions.
It changes constants, changed image pixels and bypass links, rejects stale
revisions, and publishes its next revision after binding and changed-image
readback. The returned receipt separates upload, packing, image readback,
binding and commit times. A failed write
restores prior fields and links; failed restoration sets `.valid=False` and
requires owner recovery. The caller owns reader exclusion, scheduling and
publication; the library does not acquire a Blender workflow lock. Packed saved
graphs evaluate without the Python controller. Reattaching an editable controller
after reopening remains a future host lifecycle responsibility.

`build_group(..., export=True)` is the complete guarded path. `export=False`
explicitly skips both output guards; with reset Color it retains the original
raw Linear/Tone behavior, including exact reset bypass and invalid-decode black.
Full reset still performs export projection, so signed/out-of-cube inputs need
not pass through unchanged.

`LinearSettings.balance` uses reference gain `2**(-balance)`. A future adapter
for the old UI must negate its convention. `matrix` replaces the derived XYZ
transform and may be singular. `ToneSettings` has five `input_nits`, `fit`,
`reference_nits` and `peak_nits`.

`project_source_white` moves an xy pair to the nearest CAT16-positive point.
`project_source_white_component(point, axis)` clamps one coordinate while
holding the other fixed, for independent x/y controls.

`ColorSettings.lightness` and `.chroma` each have four tonal rows and four
columns ordered low chroma, high chroma, opponent a, opponent b. `.adaptance`
has four two-component rows. Independent `.lightness_fit`, `.chroma_fit`,
`.global_gain` and `.adaptance_half_saturation` match the reference schema.
`WebSettings.log_chroma`, `.hue_degrees` and `.log_scale` are four-by-six arrays
in cyclic Rec.709 handle order. Preparation retains the reference's geometry
validation; it never silently changes settings to make a table pass.

`PreparedGrade` exposes `.linear`, `.tone`, `.color`, `.space`, `.table`,
`.full_fields` and optional `.boundary`. `prepare_linear`, `prepare_tone` and `prepare_color` are
also available independently. Prepared host functions are analysis tools, not a
runtime pixel-grading path. To reuse fixed boundary geometry across edits:

```python
from color_tools.perceptual_grade_nodes.boundary import prepare_boundary
geometry = prepare_boundary(prepared.fl, prepared.aw, prepared.gamma)
prepared = prepare(color=ColorSettings(global_gain=.3), boundary=geometry)
```

`prepare_boundary` loads the versioned asset generated by
`//libraries/perceptual-grade-nodes:boundary_resource`; it no longer solves or
validates a dense geometry grid during runtime preparation. The context must
match exactly. Missing, corrupt or incompatible packaged data raises explicitly;
there is no runtime generation fallback. Retain the returned immutable object to
reuse host geometry across grades and edits. Omitting `boundary` loads the asset
when constructing an export guard. Each group still creates and owns its packed
native image; host-data reuse does not imply shared Blender-image storage.

Web uses 1D sector coefficients and toe fields exclusively. The `web_atlas`
argument, `prepare_web_map` and automatic 2D retry have been removed. The
output-boundary seed remains a separate 2D geometry resource; generic 2D sampling
has not been removed. No global image/cache authority is introduced.

During this handoff, both builders temporarily return complete graphs even when
they exceed the original `<1000` expanded-node requirement. `.stats` retains the
actual count. Numerical and node-budget results are reported separately, and an
oversized graph is not full acceptance. The next developer must optimize the 1D
path and restore strict admission; no grading-model change is authorized. Count
all dormant nodes and precision alternatives in a persistent graph.

`Graph(tree, prepared)` appends reusable `linear`, `encode`, `tone`, `color`,
`hk_guard`, `output_guard`, `decode` and `decode_coordinates` stages. Appearance
and Color sockets expose `H`, `a`, `b`, `J_A`, `energy`, `chroma` and `q`; Color
also retains original post-Tone selectors, reference energy and saturation.
Read desired lazy socket properties before finalizing/counting the tree. A
handoff avoids decoding/re-encoding between stages. Sockets from another Graph
are rejected. `Graph.color` expects the state produced by `encode` → `tone`
under the same prepared configuration. Its static magnitude bounds rely on
that handoff; manually constructed states with unrelated magnitudes are not an
unrestricted input API.

`Graph.decode` accepts the appearance state from `encode` or `tone`. To decode
raw Color output, use `decode_coordinates(state.J_A, state.a, state.b)`.
`hk_guard` consumes the Color state, including its frozen reference energy;
call `Graph.color` even when Color settings are reset before applying the guards.

The convenience group exposes Color, Alpha, Decode Valid, Pole Margin and
Saturated outputs. Shader has a separate Alpha input; Compositor preserves the
incoming color alpha. `BuiltGrade` exposes `.tree`, `.images`, `.helper_groups`,
`.prepared` and `.stats`. Construction failure releases resources it created.
There are no fake users or registration side effects. Connect/retain the group
before saving; after removing its users, call `built.dispose()`. Disposal rejects
live users unless explicitly called with `unlink=True`.

See [the complete example](examples/full_grade.py) and the explicit
[raw Linear/Tone example](examples/linear_tone.py). Both create detached groups
without replacing the active scene/material.

## Accuracy and cost gates

The final requirement is **below 1000 expanded nodes** per complete graph,
counting nested occurrences, group interfaces, samplers, adapters, alpha and
diagnostics. Oversized complete graphs are temporarily permitted for the 1D
handoff and remain budget failures in reports. The isolated raw Linear/Tone
wrapper retains its 300-node cap. Nesting alone does not reduce these counts.
Native evaluation speed and packed field storage are measured separately; node
count does not establish performance.

The practical signed-HDR corpus extends through ±1024 and includes near-neutral,
black/white, boundary, negative-energy and saturation cases in all three spaces.
Control cases cover the existing UI ranges and ordered Tone anchors, with Tone
Fit capped at 2 and Color Fit through 6. This finite corpus is not a proof over
all possible control combinations or all finite float64 inputs.

| Gate | Limit |
| --- | --- |
| Quintic 256 scalar error | `1e-5` normalized; monotonicity checked |
| Color parameter fields | `1e-5` with fixed authored conditioning scales; Web-toe layout admission uses the authorized HDR worsening budget, with raw scalar results retained |
| Unsaturated isolated Color substages | `1e-5` conditioned H/opponent/energy error at identical float32 inputs; promoted Web-toe diagnostics retain raw failures and enforce safety/final-output checks |
| Corrected boundary radius | `2e-5` normalized, plus native AP1 containment |
| Full guarded RGB, including saturation | `max(abs(actual-reference))/(1+max(abs(reference))) <= 1e-4` |
| Full expanded node count | `<1000`; original acceptance requirement, temporarily not enforced at construction |

Field metadata also reports unconditioned pointwise and coordinate-rounding
errors. Internal checks report energy absolute error and significant sign
mismatches. The exact `web_alternating_extremes` case has its authorized `1e-4`
Web-parameter and local Web/returned-scale policy; the table's ordinary-case
limits remain unchanged. As explicitly agreed, each Color substage receives identical float32
state/frozen-selector inputs for its local gate. Accumulated raw Color error is
reported separately: large final scale can amplify an earlier accepted local
error. Guarded output cannot certify a failing local substage; the separate
Web-toe HDR admission is the explicit layout-sizing exception and does not
rewrite the strict local arithmetic regression. The old raw
Linear/Tone RGB gate separately excludes ill-conditioned decoder responses above
300, reporting those as pole stress; the complete guarded path has no such
exclusion.

## Build and evidence

From the repository root:

```sh
buck2 build //libraries/perceptual-grade-nodes:boundary_resource --show-output
buck2 test //libraries/perceptual-grade-nodes/tests:preparation //libraries/perceptual-grade-nodes/tests:color_preparation
buck2 test //libraries/perceptual-grade-nodes/tests:reference //libraries/perceptual-grade-nodes/tests:native //libraries/perceptual-grade-nodes/tests:stages
buck2 test //libraries/perceptual-grade-nodes/tests:color_stages //libraries/perceptual-grade-nodes/tests:guards //libraries/perceptual-grade-nodes/tests:saturation //libraries/perceptual-grade-nodes/tests:full -- --timeout 1800
buck2 test //libraries/perceptual-grade-nodes/tests:boundary_resource //libraries/perceptual-grade-nodes/tests:architecture
buck2 test //libraries/perceptual-grade-nodes/tests:persistent //libraries/perceptual-grade-nodes/tests:persistent_color_stages -- --timeout 3600
buck2 test //libraries/perceptual-grade-nodes/tests:gui_drag_report
buck2 run //libraries/perceptual-grade-nodes:audit_fields -- --output-dir buck-out/persistent-grade-evidence/field-audit
buck2 run //libraries/perceptual-grade-nodes:full_evaluate -- --output-dir buck-out/nodes-1d-handoff/full-cpu --jobs 3
buck2 run //libraries/perceptual-grade-nodes:full_evaluate -- --output-dir buck-out/nodes-1d-handoff/full-ui --ui-boundaries --warm-runs 0 --jobs 3
buck2 build //third_party:xvfb_linux --show-output
buck2 build //libraries/perceptual-grade-nodes:benchmark_report --show-output
```

On Linux, use the Xvfb directory printed by its build for an explicit-output GPU
run:

```sh
buck2 run //libraries/perceptual-grade-nodes:gpu_evaluate -- --full --output-dir buck-out/nodes-1d-handoff/full-gpu --xvfb /path/to/built/xvfb
```

The `:full_report`, `:full_ui_report` and `:full_gpu_report` generation targets
return failure when a numerical or node-budget gate fails; the original node
budget remains unmet and Buck may not publish their outputs. Direct evaluator
commands preserve complete reports in the requested directory even when their
combined acceptance returns a nonzero status. The benchmark target completes
independently of cost acceptance.

The preserved `:report`, `:ui_report` and `:gpu_report` evaluate the explicit raw
Stage 1–2 path. Full reports use direct float64 reference stage composition,
excluding its input repair. They record source/pixel hashes, control values,
errors and worst pixels, saturation, containment, graph/image costs and timing.
They also bind the packaged boundary asset checksum. Full reports expose
`numerical_passed`, `node_budget_passed`, and combined `passed`; a budget failure
retains numerical results and makes combined acceptance unsuccessful. The full
report CLI still exits unsuccessfully after writing its report when either gate
fails. For a persistent handoff output directory, run `:full_evaluate` directly
with `--output-dir buck-out/nodes-1d-handoff/full-cpu`. Runtime boundary loading
is measured separately from grade-dependent preparation; expensive boundary
generation belongs to the Buck resource build.
The benchmark uses image-sized inputs, fresh processes, repeated evaluation and
an identical passthrough transport baseline. Benchmark-only uncompressed 32-bit
EXR removes output-entropy compression bias. EXR/render overhead remains included;
these measurements are not isolated shader timings or product latency claims.
The native Color stress suite can exceed the test runner's default 600-second
limit when other acceptance jobs run concurrently; the command above allows
1800 seconds without changing any numerical gate. Run the benchmark after
accuracy jobs finish.

Measure initialized-tree interaction separately using the GUI fixture:

```sh
buck2 run //libraries/perceptual-grade-nodes:gui_drag -- --blender /path/to/pinned/blender --xvfb /path/to/built/xvfb --output-dir buck-out/persistent-grade-evidence/gui-drag --backend software-gpu --size 1024 --sessions 3 --samples 10
```

The fixture initializes the scene, every native stage/image, and the first native
evaluation/display before accepting samples. Each update is timed from accepted
settings through preparation, native apply, evaluation, preview upload and the
first framebuffer-verified matching GUI draw. Reports retain raw occurrences,
revisions, superseded samples, initialization phases and descriptive p50/p95;
there is no latency threshold. `--backend software-gpu` selects Eevee for Shader
and the GPU Compositor for Compositor; `--threads` defaults to the available CPU
affinity. The prepared-edit and image-sized benchmark tools accept the same
backend/thread options. The latest run requested 254 threads and observed
Mesa's cap of 32 workers per llvmpipe pool. This synthetic preview includes
synchronous readback overhead and does not certify Next UI or automatic viewport
latency. Scene construction and initialization are never reported as drag cost.

Linux GPU checks use pinned Xvfb and software OpenGL llvmpipe. Eevee AOV readback
reconstructs float32 values from mantissa/residual/exponent channels, avoiding its
float16 storage limit. Those fixture nodes are outside the Grade group, and their
reconstruction work is included in the Shader fixture's render/preview timing.
Cycles Color AOVs use float32 render-buffer channels. The Compositor grading
path evaluates directly and needs no AOV transport.
Physical GPU drivers and Metal require separate acceptance. Refer to
[EVIDENCE.md](EVIDENCE.md) for what has actually passed on the current sources.
The promoted 4,096/1,536 software-GPU corpus has all 960 matching draws and
120 superseded samples accounted for; its 60 extreme-Web numerical failures
remain explicit alongside the completed CPU and software-GPU HDR comparisons.
