# Active delivery: implement Perceptual Grade Next

Last updated: 2026-11-01

The selected next milestone is
[trustworthy readiness and recovery](READINESS_RECOVERY_STEP.md):
one arbitrary-owner readiness decision, validated native manifests, retained
recovery debt and saved-interruption acceptance through actual output admission.
The mandatory unbounded kernel proof now passes. Production record conversion,
durable commit/cleanup and the full installed interruption matrix remain open.
**The milestone is partially implemented and unfinished. This update records
the audit and stops without implementation changes.** The broader Next delivery
and its remaining work below stay open.

**Status: implementation underway.** Packaged Linux/Blender 5.2.2 acceptance now
covers direct Image and UV Shader Bake, Compositor Bake, package save/reopen,
idle and fault-retried Restart, modified-Image Save diagnostics, Render receipt
handling, and viewport capture with histogram, waveform and vectorscope data.
Focused tests also cover owner readiness for five Blender-backed owners and
Scope transfer when the selected viewport is removed. Installed Scope acceptance
now covers stopped-frame recapture with a keyframed Shader RGB input, no
acquisition/publication during playback, and capture of the latest frame after
stopping. Coherent scope batches, native reader/fault interleavings, active-work
Restart, broader crash/autosave/Undo acceptance and the complete Linux workflow matrix
remain open. The
[canonical state-machine design](STATE_MACHINE_DESIGN.md)
defines the core properties and acceptance contract. The Next pair now has
independent settings and numerical modules, preparation/Bake readiness and
eligibility policies, a native Grade graph adapter, Stack 33³/65³ lattice and
Blender datablock adapters, independent package ownership gates, and reference-
parity tests. Static Grade and Stack controls now queue coalesced immutable
settings and generate fields/LUTs off Blender's UI thread. Grade edits apply to
its fixed tree with packed-field/binding readback and rollback; Stack edits
replace the immutable lookup graph after candidate validation. Failed preparation
preserves the prior output when compensation succeeds and offers local Retry;
failed-compensation repair debt remains incomplete. These components
are not the complete product: scope identity/barrier handling and native
viewport-pixel capture are composed into Blender, with finite scene-linear RGB
statistics and histogram/waveform/vectorscope pages. Stopped-frame and playback
pause/resume behavior pass installed acceptance, including changed pixel
statistics from the animated scene input. Scope source identity now excludes
inactive studio-light controls according to shading mode; coherent
primary/reference batches and broader dynamic-input behavior remain open.
Animated Grade/Stack controls remain deferred.
Viewport choice uses the last observed draw area per window, with largest-area
fallback; true focus tracking and camera-only capture remain unsupported.
Checked project/output receipts are composed with a Blender-backed
owner-readiness adapter. Packaged tests now exercise registered Bake operator
poll/execute for Shader UV and Compositor Grade capture, including UV/material
isolation, frozen-input cancellation, alpha and Image publication. Shader Bake
also removes implicit target Images after preflight/admitted failures while
preserving an explicit target. Native reader retirement, concurrent destination
ordering and broader cancellation interleavings remain open. The agreed
File/Render menu entries and matching user
shortcuts route through the owned gate, while direct native operator/script calls
can bypass it. Earlier focused installed acceptance passed; the latest smoke
target fails during Stack setup/reopen, and the full installed workflow matrix
remains open.
Crash recovery now restores interrupted packed Grade-field and Image publication
transactions, removes orphan candidate resources, and requeues fresh
static preparation; explicit Bake and Save/Render operations are discarded on
reopen. An extension-lifetime Restart action drains known scope, update and
output obligations before recovery. Installed idle Restart and retry after an
injected recovery failure pass; active native-work and late-handle acceptance
remain open. An installed Undo probe did not establish a valid undo baseline and
was removed; Undo/Redo behavior remains unverified.

The 2026-10-31 audit added persistent structural replacement backing: an
owner-referenced ledger retains real prior/candidate node trees, external links,
socket defaults and preparation/evaluator metadata until a replacement is
verified. Field and structural ledgers survive Blender library write/load in
focused tests. The follow-up recovery fix now blocks new work while any
unresolved owner ledger is retained and reconstructs field transaction identity
from its persistent ledger when the redundant JSON marker is absent. The
earlier regressions passed in `recovery`; the latest expanded target has two
failures. See the
[implementation handoff](CHECKLIST.md#current-audit-handoff-2026-11-01) for exact
acceptance receipts and remaining crash/Undo gaps.

The latest 2026-11-01 audit confirms that Grade uses persistent write-ahead
backing; complete crash recovery is still unfinished. Grade and Stack now reject
both JSON and retained-pointer transaction debt. Their accepted manifests bind
graph and image contents; ordinary admission compares current contents with
the accepted record. Production readiness uses the unbounded kernel for every
owner count. Remaining confirmed defects include partial backup deletion that
strands later recovery, incomplete structural/Grade snapshot inventories, no
durable committed marker for in-place Grade fields, and duplicate Stack Image
disposal. The native Stack test omits owner schema; the installed Stack fixture
loses its unreferenced host on reopen. The handoff distinguishes these fixture
defects from runtime failures. Earlier binding-only Grade crash/reopen evidence
and the Grade boundaries reached by the latest run do not establish the full
saved-interruption matrix or recovery from interrupted file serialization.

The [proof coverage inventory](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
maps every canonical scope/project/preparation/recovery family to the current
checked functions and remaining claims. The ninth target,
`project_unbounded_proof`, passes 170 obligations and 4 mutation checks in build
`e458d854-a0f2-474f-9ee4-e903e6da13b7`. It proves the arbitrary-length kernel in
`project_unbounded.py`; the owner/evaluator/artifact alignment in production
`project.py` remains outside that proof. The legacy four-slot proof does not
establish that correspondence either. There are ten `.inv` inventories but only
nine proof targets: `scope_view.inv` has five properties, no Buck proof target
and no required nonempty `invariants` declaration. The canonical crosswalk still
has 60 IDs: 43 partial, 11 adapter premises, 6 open and 0 proved. Induction over
the empty list and an arbitrary one-element extension establishes every finite
length; production source mapping and actual admission remain separate work.
Preparation, recovery-policy and composed proofs still check reduced models
with no production call sites, rather than the Blender adapters.
Foreground and Restart adapters use their proved transitions; project completion
uses proved receipt predicates from the prior bounded kernel. These checks do
not certify the full production owner worklist, Scope/view joint transition,
native statistics/batch/resource protocols or installed crash boundaries.

The latest focused audit passes Invariant 57, core workflow 75, project readiness
11, native Grade 8, Bake lifecycle 20, output operators 19 and inventory 6 tests.
Recovery ran 34 tests with 2 failures; native Stack ran 9 with 1 failure.
Installed smoke reached Grade boundaries but failed during Stack setup/reopen.
There is no fresh passing aggregate proof/package receipt closing this milestone.

Earlier focused evidence records recovery 30, Scope runtime 24 and Bake lifecycle
20 tests passing in Build `1cea63c9-dc36-4c93-b33c-4c3d6d7c387f`; native Grade
6, installed Bake and installed Compositor capture pass in Build
`19a7a923-33c1-4f48-acc5-062509ce7f0f`. These precede the unbounded-proof gate
and do not establish that the current aggregate passes.

Earlier focused evidence includes recovery 27 tests, native Stack 9, native
Grade 6, core numerical/workflow 70, invariant 53, composition trace 5, Restart
10, Bake lifecycle 20, scope runtime 24, scope UI 2, output operators 19, project
readiness 10 and extension packaging 4. The focused 12-target Buck run passed;
recovery, project readiness and Scope targets were rerun after adapter changes. Six
installed Blender 5.2.2 targets passed at that earlier baseline: smoke/save-reopen, idle and fault-retried
Restart, Shader Image/UV Bake, Compositor Bake, modified-Image Save diagnostics,
Render receipt handling, and viewport capture. `installed_save` also verifies
that a failed native Save As releases its project hold and leaves the prior
saved project intact. The installed Undo probe failed
to establish a valid fixture undo baseline and does not count as passing
evidence. The eight previously passing Next proof targets report 493 obligations
and 27 detected/replayed mutations; these are historical counts and exclude the
new unbounded target. The canonical inventory validator passes its six
consistency tests (Build ID `980c3184-ac08-4aa6-9abe-cb5fa9793d68`); this verifies
references, not theorems. The combined `buck2 build` (Build ID
`5d874421-237c-4540-9721-a2a38d5bd791`)
`//:verify_next //:perceptual_grade_next //:verify //:perceptual_grade
//:hdr_color_picker //:dctl` passed. This is build/proof/package evidence; it
predates the unbounded target and does not close the complete Linux/Blender
installed acceptance in the checklist. Earlier Next package/proof build
`d2d4b73f-a869-4607-9bab-88dad11710b3` also passed
`buck2 build //:verify_next //:perceptual_grade_next`. There is no passing
aggregate proof/package build after adding `project_unbounded_proof`.
The delivery scope is Linux/Blender; macOS/Metal and physical HDR acceptance
remain separate. The native node-count and extreme-Web GPU findings remain
deferred and unresolved.

Implementation ownership:

| Directory | Python package | Responsibility |
| --- | --- | --- |
| `libraries/perceptual-grade-next-core` | `perceptual_grade_next_core` | Portable numerical behavior, workflow machines and source-bound requirements |
| `products/perceptual-grade-next-blender` | `perceptual_grade_next_blender` | Blender adapters, UI, application composition, packaging and native acceptance |

Preserve the old core/product source, Buck targets, tests and root aliases.
DCTL and reference consumers stay on `perceptual-grade-core`. The independent
`//:perceptual_grade_next` and `//:verify_next` targets are now present; never
redirect `//:perceptual_grade` or `//:verify`. The new pair must not import the
old core/product runtime or inherit its workflow authority. Shared Invariant, Blender runtime
and color-core remain reusable dependencies; changes to their shared source can
affect both pairs. No generic runtime rewrite is planned.
Pin any new library or tool dependency through Buck2.

Retain extension identity `perceptual_grade`; test old and new versions in
separate Blender profiles/processes. Distinct internal Python packages provide
build ownership, not simultaneous native registration. Coexistence is not a
feature of this handoff.

Grade/Stack controls and prepared transforms remain static. Grade keyframing,
auto-keying, dependency drivers, copied animation Actions, per-frame texture
banks and separate Exact LUT workflows are deferred. Do not implement scene-range
Grade preparation or per-frame LUT timelines. Inputs and scenes can still animate:
automatic scopes refresh after frame changes and acknowledged native evaluation.
Playback retains the prior display and pauses acquisition/publication; stop
refreshes the latest frame after native completion. Native animation rendering
and movie output remain supported with static grading.

One global Gizmo `ScopeActor` per App owns demand, attempts, analysis and display.
Foreground `ViewAuthority` and the native/UI gateway remain outside the actor.
X closes and revokes the view independently of actor, worker or recovery progress.
Exact view/occurrence/attempt identities govern publication; cancelled attempts
never revive, and late receipts can retire only their original work.

A merged `project_workflow` owns explicit Image Bake, static final preparation,
output and recovery relationships. Scheduler resource leases do not grant domain
permission. An extension-lifetime Restart supervisor fences failed Apps and
retains cleanup debt until exact retirement receipts permit fresh ownership.
Local failures offer explicit local Retry without restarting unrelated work.

Static preparation publishes complete kernels per owner. Grade uses its installed
native node tree as the single grading path; it has no separate preview LUT or
alternate preview evaluator. Grade Stack uses a 33³ intermediate preview and a
65³ final LUT. The 33³ lattice reuses every second 65³ vertex exactly; only the
accepted 65³ result is final output. Retain matching matrices, packed resources
and bindings under the existing preparation/publication contract. Use current
Grade schema 5: Tone 256, Color coefficients 8,192, Web parameters 4,096, Web
toes 1,536, Compact Adaptance 3,072 and the fixed 513 × 321 boundary.

The new reference model owns Next math. Grade nodes implement its forward path.
Stack entries implement both FORWARD and INVERSE directions, ordered raw
appearance handoffs, stage endpoint matrices and reference inverse residual
semantics. In particular, new Stack math uses the reference's
`(35/75) * abs(J_A)` low/high crossover, not the retained `.4 * capacity`
production law. `perceptual_grade_reference` is an oracle, not a Next runtime
dependency; Next core owns its portable implementation.
Preserve the native Grade's signed-input contract without adding LUT input
repair. Stack retains its separate AP1 input repair, raw-handoff and export
rules. Reference comparisons must match those entry contracts rather than
assume the public Model wrapper is identical for every signed input. Inverse
reproduction residuals remain explicit; the reference search promises neither
a unique preimage nor proof that a target is unreachable.

Grade Bake evaluates the installed Grade node-tree output for the admitted,
frozen input. Grade Stack Bake samples the accepted 65³ LUT using the same
shaper, interpolation and endpoint matrices as the installed Stack. No custom
GPU helper may directly grade Bake pixels. A GPU helper may generate the Stack
LUT, provided that complete LUT is validated and is the only grading source
for Stack Bake. A helper process may host Blender's native evaluator and return
its output; the prohibited path is a separate analytic/custom-GPU pixel grader.
Preserve existing Bake route eligibility, cancellation,
destination and publication rules.

The Next UI follows the full reference control schema. Tone Fit is `[-2, 2]`;
Color lightness/chroma Fits are `[-2, 6]`. The supported grading appearance
context is D65 / 203 nits; do not expose unsupported grading-white or reference-
nits choices. Source-white adjustment and the supported working RGB spaces are
separate controls. Other existing authored control
ranges, defaults, labels and units remain unless the reference contract defines
them. Preserve the user's no-animation policy.

The standalone native graph's unmet expanded-node budget and known extreme-Web
software-GPU error remain explicitly deferred separate findings. They do not
block this Next implementation or delivery, are not resolved by this handoff, and must
not be reported as passing. Retain real persistent references to prior/candidate
resources until verified installation, readback and publication receipts establish
completion. Failed compensation retains affected-owner repair debt; Save/Render
requires every required owner ready. A partial asset set or saved COMPLETE marker
cannot grant readiness. On reopen, the
`.blend` or recovered autosave is the sole authority: validate the actual packed
derived set and rebuild missing or invalid preparation from current static
settings. No unsaved recovery journal supplies authority; explicit Image Bakes
never resume automatically. Preserve authored Images, committed Bake results and
new-format save/Undo behavior without historical compatibility or migration.

Save owns its confirmation before preparation, then invokes native Save `EXEC`
exactly once after readiness. Cancelling destination/confirmation leaves Bakes
untouched and does not start the Save gate; ordinary background preparation remains
independent. Accepted Save cancels unfinished explicit Image Bakes, resolves
their required retirement/compensation and saves committed Images and prepared
static assets. The chosen compression must be honored; Blender's remembered
default may differ until reopening. This difference is accepted without a workaround.
Render likewise prepares once and invokes native work once, holding Image
publication through the whole operation, including every animation frame. A
per-frame callback cannot release that hold.

Scopes follow the last-used viewport's effective lighting/framing. Label authored
World **Scene World**, distinct from studio lighting. Keep coherent primary/
reference samples, compatible progressive publication, semantic Bake preflight,
real native readiness, defined localized outcomes and diagnostic logs. New bake
Images receive no automatic fake user.

[CHECKLIST.md](CHECKLIST.md) orders implementation through isolation, models/proofs,
adapters, capture/preflight, static persistence, Save/Render/Undo/Restart and
acceptance. Remaining implementation tasks stay unchecked. State desired
end-to-end properties first, then derive machine boundaries and exact receipts.
Existing coordinator/regular-machine labels do not constrain the design.

Old lighting, cancellation/reopen, obsolete-completion and preflight regressions
motivate this work; documentation does not repair them. The exact pencil-only
global-hang sequence remains unconfirmed. The supplied `train-model.blend` stays
read-only evidence, not a fixture; its recorded SHA256 is
`81d89bbddaaffb153652aaef3787fcede987a941841e1dbddcde92f592c24dcd`.

The new pair requires its own source-bound properties, witnesses, mutations,
adapter tests, package receipts and installed acceptance. Numerical acceptance
must compare Next Grade/Stack results and Bakes to the current independent
reference, including both Stack directions; old proofs, test counts, archives
and native results do not transfer. Keep mathematical claims, native premises
and deferred platform findings explicit.

All delivery records below describe native-library experiments or the preserved
old pair at their recorded revisions.
Their current/accepted language, animation features and recovery rules do not
override this handoff. Historical content and evidence are preserved unchanged.

---

# Completed native grading development and historical deliveries

Last updated: 2026-10-30

## Completed layout promotion and absolute HDR reassessment — 2026-10-30

The native runtime now uses Tone **256**, Color coefficients **8,192** and
Compact Adaptance **3,072** cells together. Web parameters remain **4,096**, Web
toes **1,536** and the fixed output boundary **513 × 321**. Layout schema is
**5**: existing persistent trees must be rebuilt, and immutable preparation
rejects obsolete Tone and Color payload reuse. Tone Fit accepts **[-2, 2]**,
as corrected by the user; Color fits retain [-2, 6]. The current 148-case
corpus replaces Tone fit-3 stress cases with fit 2 and removes the separate
fit-3 endpoint. Historical fit-3 receipts retain their original scope.

The [absolute HDR report](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/absolute-hdr-validation.md)
compares the combined runtime against 444 fresh float64 reference replays
through the pinned ACES 2.0 HDR-1000 Rec.2020 view and Rec.2100-PQ once.
Both CPU and software GPU cover all 148 cases, three spaces and two contexts,
with 1,024 pixels per row and persistent trees/images through control edits.
Software GPU uses llvmpipe / EEVEE Shader and FULL GPU Compositor.

Excluding `web_alternating_extremes`, each backend has 903,168 pixel samples
over 147 cases. Values below are fractional full-range 10-bit RGB codes;
percentiles and mean use the largest absolute channel error at each pixel.

| Absolute HDR error | CPU | Software GPU |
|---|---:|---:|
| Maximum | 7.98566660 | 8.34962157 |
| p99 | 0.00879572 | 0.00896341 |
| p99.9 | 0.10509517 | 0.10648491 |
| Mean pixel peak | 0.00069342 | 0.00070073 |
| Channel RMSE | 0.01007132 | 0.01028189 |

The worst ordinary witness remains `source_boundary_0`, ACEScg, pixel 537,
green, in both contexts: the reference channel is almost zero and PQ
amplifies the small scene-linear residual. Including all cases, the CPU
maximum is unchanged and the GPU maximum is the existing **337.422684-code**
alternating-extremes finding. CPU final-RGB checks pass all 888 rows; GPU has
only the six alternating-extremes failures. Finiteness, containment, alpha
and reference validity pass; CPU/GPU validity and saturation flags match.
Independent reconciliation passes **16,940,389 assertions**; this validates
the measurements without relabeling the retained numerical failures.

Tone's 31 distinct scalar functions pass the unchanged required gate, with
maximum conditioned error **3.0973854e-6**. Web parameters pass all 19 scalar
functions under the existing scoped alternating-extremes allowance. Raw
diagnostic failures remain visible for Color (7/78), toes (16/16) and Compact
Adaptance (3/11); the scalar audit retains its failing raw status. No gate was
relaxed for this promotion. All **86 regression methods across nine Buck2
targets pass**; the [completion receipt](../../buck-out/persistent-grade-evidence/layout-256-8192-3072-fit2-20261030/completion.json)
binds tests, source identities and evidence.

Resident RGBA32F payload is **5,076,560 bytes**, or **2,441,792 bytes** excluding
the shared fixed boundary. Tone256 retains production packing at 512 × 1
(8,192 bytes). This reassessment measures accuracy; preceding schema-4
generation/edit timings are historical and were not rerun here.

## Historical schema-4 sensitivity report — 2026-10-30

Measure independent texture reductions from the current schema-4 Compact-only
baseline: Tone 512, Color coefficients 16,384, Web parameters 4,096, Web toes
1,536, Compact Adaptance 8,192 and output boundary 513 × 321. All other fields
remain at these current sizes for each comparison. Do not use the older larger
layouts as sensitivity denominators and do not promote a reduced runtime size
as part of this report.

Use the real persistent native graph, matched reference grading and pinned
ACES 2.0 HDR-1000 Rec.2020/PQ fractional 10-bit RGB. Report maximum signed added
HDR codes, added percent of reference peak, final RGB/containment/semantic
checks, actual candidate payload and generation cost. Exercise the full
149-case, three-space, two-context CPU corpus, then check representative
ordinary/extreme controls on software GPU. Preserve raw failures and existing
admission rules. Run generation timing without concurrent accuracy work;
retain the current source-stable software-GPU edit timing with its scope.

The current-to-smaller study is complete without changing runtime sizes. Its
12 independent reductions cover **10,728 candidate and 894 baseline CPU rows**
(149 cases × three spaces × two contexts × 1,024 inputs). Independent
reconciliation passes **75,983,224 assertions**. Software GPU checks cover
17 representative/extreme/CPU-witness controls in all six context/space
combinations, with **8,989,366 independent assertions**.

For example, Color 16,384 → 8,192 adds at most **0.0195181 CPU / 0.0497332
GPU HDR codes**; Web parameters 4,096 → 2,048 adds **0.0410032 / 0.0410127**;
Compact 8,192 → 2,048 adds **0.0243597 / 0.0236280**. These are signed
per-pixel error increases relative to the current baseline, not automatic
admission against the historical frozen-baseline policies.

Both smaller Tone grids retain required scalar failures. Toe 768 has four
CPU final-RGB failure rows. The two reduced boundary grids fail the radius
gate and introduce two/six CPU and two/four additional GPU final-RGB failures.
All containment and alpha checks pass; validity and saturation flags do not
change. The existing GPU alternating-extremes failure remains in six baseline
rows, with **337.422684 codes** maximum absolute reference error. The CPU
baseline maximum absolute error is **7.98566660 codes**. Added-error metrics
do not erase these absolute errors.

Fresh, uncontended pure table-generation timing covers **300 samples** over
four cases and five repeats. All-active current Color/Web/toe/Compact costs
are **8.099 / 11.481 / 1.977 / 2.212 ms**; pure Tone generation is **0.936 ms**.
Current payload remains **5,428,848 bytes**, or **2,794,080 without boundary**.
The source-identical complete-preparation and software-GPU prepared-edit
receipts remain separately scoped: **37.885 ms** complete all-active
preparation and **470.200 / 93.847 ms** repeated Exposure end-to-end for the
16² Shader/Compositor diagnostic, including fixture transport.

All six new candidate-helper checks pass through Buck2. The
[combined breakdown](../../buck-out/persistent-grade-evidence/current-texture-sensitivity-20261030/breakdown.md)
records current payloads, all reduced costs, CPU/GPU added codes and reference
peak percentages, required failures and source identities.

**Status: documents, native CPU/software-GPU evaluation, independent
reconciliation, isolated generation timing and report are complete. Runtime
layout schema 4 and all production texture sizes are unchanged.**

## Completed Compact-only Adaptance implementation — 2026-10-30

Every Adaptance adjustment now uses the **8,192-cell Compact table** in both
specialized and persistent graphs. Interior generation, storage, update slots,
sampling and the calibrated-gain/tail choice between representations are
removed. Compact retains its full-range coordinate map and analytic tail;
reference equations and authored center semantics remain unchanged.

Layout schema **4** rejects obsolete preparation/tree reuse. Rebuild existing
persistent trees. Six native images hold **5,428,848 RGBA32F bytes**, including
the 2,634,768-byte fixed boundary, or **2,794,080 bytes without it**. This saves
**1,048,704 bytes (16.19%)** against the frozen preceding dual-table path.

All **894 matched CPU rows** pass: 149 cases × three spaces × two contexts ×
1,024 samples, with the same prepared tree/images retained across every edit.
Maximum signed HDR worsening is **0.0000304877758 fractional 10-bit codes** /
**0.0000156437481% of reference peak**; final RGB, containment, alpha and semantic
flags pass. Independent reconciliation passes **32,668,186 assertions** and
447 float64 reference replays. The unchanged worst absolute reference error is
7.98566659944 codes. The additional six-case, 36-row software-GPU strong-control
study passes on llvmpipe / EEVEE and FULL GPU Compositor, with maximum added
error **0.0000304877758 codes / 0.0000208583307%** and no flag changes.

All **90 regression checks across eight Buck2 targets** pass. Raw scalar and
local precision diagnostics remain visible: both local suites retain 12 raw
Compact failures under the existing 0.05-code HDR admission policy; required
precision, finiteness and significant-sign checks pass. The complete scalar
receipt covers Color 78, Web parameters 19, toes 16, Compact 11 and Tone 32
functions, with the retained Color/toe raw failures separately recorded.

Fresh, uncontended preparation over 20 runs measures **37.885 ms** all-active,
versus the preceding 43.838 ms receipt; Compact generation is **2.225 ms**.
Software-GPU prepared-edit timing uses the same 16² diagnostic and 254 requested
threads: repeated Exposure end-to-end is **470.200 ms Shader / 93.847 ms
Compositor**. This includes fixture evaluation and transport, and is not
Grade-only per-frame render time or a full-resolution preview benchmark.

The [current breakdown](../../buck-out/persistent-grade-evidence/compact-only-adaptance-20261030/breakdown.md)
contains all texture, generation, edit-phase and HDR results. The persistent
graph now has **1,445 Shader / 1,382 Compositor nodes**, down from 1,468 / 1,399
but still above the original <1,000-node goal. The historical software-GPU
extreme-Web finding and Next product integration retain their separate scope.

**Status: implementation, migration, full CPU and targeted software-GPU
validation, regression, preparation and prepared-edit reports are complete.**

## Historical completed Color-coefficient and Compact Adaptance reduction — 2026-10-30

The runtime now uses **16,384 Color coefficient cells and 8,192 Compact
Adaptance cells**, with Web parameters/toes at 4,096 / 1,536 and Interior
Adaptance at 65,536. Layout schema 3 fixes total RGBA32F payload at
**6,477,552 bytes**, down 3,801,552 bytes (36.98%) from the preceding runtime.
Color payload falls 87.5%; Compact payload falls 50%. Existing fixed-layout
trees must be rebuilt; immutable preparation rejects obsolete dimensions and
preserves exact matching-layout reuse.

| Promoted layout | RGBA32F bytes | Fresh all-active generation median | Current persistent CPU maximum added HDR error |
|---|---:|---:|---:|
| Color coefficients / 16,384 | 524,352 | 8.146 ms | 0.0115159237 codes / 0.00529889482% reference peak |
| Compact Adaptance / 8,192 | 131,088 | 2.232 ms | 0.00128048658 codes / 0.000361764104% reference peak |
| Both promoted together | — | — | 0.0115159237 codes / 0.00529889482% reference peak |

The current [breakdown](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/breakdown.md)
combines texture payload, current preparation, current persistent HDR and
current 16² software-GPU prepared-edit phases. Its unchanged-field sensitivity
and full-resolution preview rows retain their historical source/layout scopes.

The independent [persistent HDR validator](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/hdr-validation.md)
passes all 1,204,923 assertions across 40 source files. The run has all 149
cases × 1,024 samples × three spaces × two CPU contexts: **894 baselines and
2,682 measured candidate rows**, with no inactive or failed rows. The explicit
baseline uses Color 131,072 / Compact 16,384 and current Web 4,096 / toe
1,536. Color, Compact and combined all pass the authorized **0.05-code**
layout budget, final RGB, containment and unchanged validity/saturation flags.
Baseline and combined maximum absolute reference error both remain
**7.98566659944 codes**. Color and combined retain 18 raw scalar-failure rows;
Compact has none. Scalar/local precision is diagnostic only for the authorized
roles; safety, final RGB, containment, flags and construction remain active.

The new persistent result supersedes the old specialized full-field Compact
zero-movement result for this path. The persistent graph samples Compact for
all four values when `max(abs(log_gains)) <= 1`; the specialized full-field
builder can mask Compact effects through Interior Adaptance. The separate
[local study](../../buck-out/persistent-grade-evidence/color-field-local-20261030-rerun/report.md)
retains the pre-display/PQ opponent precision maximum `1.22195872e-5` versus
its raw `1e-5` diagnostic limit.

The fresh [host-preparation report](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/preparation-costs/report.md)
has 20 preparations over four cases. Complete all-active preparation is
**43.838 ms**, with four-case medians 43.838–45.719 ms. Color generation
medians are **8.146–9.136 ms**, with individual samples up to 11.786 ms;
this supports the median target rather than an every-sample time bound.
Component and complete measurements are separate and must not be added;
they exclude graph construction, upload and render. The isolated candidate
study's all-20-samples-below-10-ms observation retains its separate scope.

The fresh [prepared-edit report](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/prepared-edit-costs/report.md)
uses Mesa llvmpipe / Eevee and full-precision GPU Compositor with all 254
logical CPUs requested. Thirty **16 × 16** rows retain entry separately from
two repeated edits per family/context. Repeated end-to-end medians range
**432.831–499.226 ms Shader / 85.511–113.567 ms Compositor**; Exposure is
433.792 / 103.226 ms. These exclude initialization, GUI scheduling, preview
upload and display and do not isolate Grade-only per-frame render cost.
The previous 1,024² preview report retains its older Color/Compact layout scope.

All **87 checks across eight Buck2 targets** pass: 63 runtime checks and 24
synthetic HDR runner/admission/merge checks. The runtime receipt verifies
obsolete-layout reuse, finite output, black, sign and saturation behavior while
retaining authorized raw scalar/local diagnostics. Local tests isolate toes
at 524,288 cells and remain distinct from current-layout HDR acceptance.
The current [complete scalar audit](../../buck-out/persistent-grade-evidence/color-compact-promotion-20261030/scalar-fixed/report.json)
covers Color 78, Web parameters 19, Web toes 16, Compact 11, Interior 11 and
Tone 32 distinct functions. Only Color's two and all 16 toe functions retain raw
precision failures, diagnostic under their authorized HDR policies.

**Status: the reduction, runtime promotion, migration checks, independent CPU
HDR validation, regression and fresh preparation/prepared-edit reports are
complete.** Full-grade construction remains over budget: baseline and Color
have 1,475 Shader / 1,406 Compositor expanded nodes; Compact and combined
remove seven, leaving **1,468 / 1,399**, with no new budget-failure rows.
The historical software-GPU extreme-Web numerical finding and Next product
integration remain open separately. Current receipts are under
`buck-out/persistent-grade-evidence/color-compact-promotion-20261030`.

## Historical completed Web-parameter promotion — 2026-10-30

This completed report scope uses 131,072 Color coefficient cells and 16,384
Compact Adaptance cells. Its source hashes, byte totals and timing values do
not certify the subsequent Color/Compact promotion.

Promote the fixed runtime Web-parameter layout from 32,768 to **4,096 cells**
as authorized. Keep the current 1,536-cell Web toe and existing numerical,
containment, semantic flag and construction gates. The new parameter image is
4,097 × 32 RGBA32F (`2,097,664` bytes); total resident field payload becomes
`10,279,104` bytes. Old persistent trees must be rebuilt to adopt fixed image
dimensions; immutable preparation reuse must reject the obsolete layout.

Rerun native regression/evaluation and the matched HDR comparison against an
explicit 32,768-parameter / 1,536-toe baseline, measuring the 4,096-parameter /
1,536-toe candidate on all 149 cases, three scene spaces and both contexts.
Record software-GPU evaluation separately from CPU acceptance and retain the
known extreme-Web findings. Report both maximum signed added fractional
10-bit HDR codes and percentage of reference peak, excluding percentage
denominators below one code. Correct the earlier table's missing toe percentage
from retained raw metrics: 524,288 → 1,536 toes adds at most **0.151449259%**
of reference peak; its maximum added code error is **0.0393597186** at a
different pixel. Interior Adaptance 65,536 → 32,768 adds **0.0000114329 codes**;
the earlier `0.000152439` figure was movement, not signed worsening.

Refresh the texture/preparation and prepared-edit/software-GPU timing receipts
after correctness work, without overlapping heavy work with measured timings.
Earlier receipts below retain their measured 32,768-parameter layout and
source hashes; they do not certify the promoted layout.

**Status: the promotion, migration checks, CPU/software-GPU HDR comparisons and
all four timing families are complete and source-stable. Each HDR backend has
894 baselines, 90 measured candidate rows and 804 inactive rows. CPU passes
final RGB and containment; software GPU retains six extreme-Web failures in
both baseline and candidate. With toes held at 1,536 cells, reducing parameters
adds at most **0.0404496565 HDR codes / 0.122978849%** on CPU and
**0.00974084437 codes / 0.122460364%** on software GPU. Both backends retain
21 baseline node-budget failures. The strict expanded-node cap and Next product
integration remain open.** Current receipts are recorded
in the [native library evidence](../../libraries/perceptual-grade-nodes/EVIDENCE.md).

The [promoted-layout timing aggregate](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/timings/aggregate.md)
validates 960 matching 1024² preview draws, 120 superseded occurrences, no
missing draws, 30 prepared-edit rows, 18 benchmark processes / 144 renders,
and 20 host-preparation measurements. Parameter generation falls from 96.09
to 11.84 ms, complete all-active preparation from 184.76 to 102.35 ms, and
resident payload from 24,960,704 to 10,279,104 bytes. Repeated Exposure GUI
p50 / p95 is 738 / 768 ms Shader and 229 / 243 ms Compositor. The same 60
extreme-Web GUI probes retain their numerical failures. The
[HDR summary](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/hdr-summary.md)
and [test receipt](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/tests.json)
retain separate gates; all 78 checks across nine Buck2 targets pass.
The complete [texture/time and sensitivity breakdown](../../buck-out/persistent-grade-evidence/web-parameters-4096-20261030/breakdown.md)
includes the formerly omitted percentage maxima.

## Historical software-GPU timing rerun — 32,768 parameters

The [validated aggregate](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/aggregate.md)
binds the completed reports to current evaluator, reference, resource and tool
hashes. Pinned Blender 5.2.2 uses Mesa 25.0.7 llvmpipe: Eevee for Shader and
the GPU Compositor for Compositor. Blender render threads, OpenMP and
`LP_NUM_THREADS` request all 254 available logical CPUs; actual llvmpipe raster
pools contain 32 workers, Mesa's per-pool cap. OpenBLAS stays single-threaded.

The [1024×1024 GUI report](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/gui-1024-final/report.md)
covers all 16 scenarios, three fresh sessions per context and ten steps per
scenario. All 960 matching preview draws and 120 superseded burst occurrences
are accounted for, with zero missing draws. Repeated edit-to-matching-draw
sample quantiles include preparation, persistent apply, render, Viewer
readback, preview texture publication and matched framebuffer readback:

| Edit | Shader p50 / p95 | Compositor p50 / p95 |
|---|---:|---:|
| Exposure | 693 / 748 ms | 206 / 220 ms |
| Web chroma | 814 / 843 ms | 400 / 419 ms |
| Web scale | 811 / 839 ms | 421 / 449 ms |
| Exposure with all families active | 744 / 779 ms | 442 / 465 ms |
| Color with all families active | 753 / 783 ms | 445 / 459 ms |
| Alternating reset / active | 2,164 / 2,325 ms | 2,128 / 3,514 ms |

Scenario entry and first activation are retained separately. For example,
all-active Exposure entry p50 is 2.329 s Shader and 4.580 s Compositor, while
the recurring edits above reuse the initialized graph. Shader includes the
fixture's split-float AOV reconstruction before Viewer. These are synthetic
software-rendered preview timings; automatic viewport scheduling, Next UI and
physical display latency require separate measurements.

The [persistent prepared-edit report](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/prepared-edit-costs/report.md)
has all 30 rows at 16×16 pixels. Exposure phase medians are 0.668 ms preparation,
26.182 ms apply, 396.396 ms evaluation and 6.567 ms readback for Shader;
Compositor records 0.653, 26.162, 70.818 and 2.859 ms respectively. Web chroma
preparation is 109.740 / 105.227 ms, with 25.928 / 28.032 ms apply. Entry and
repeated edits remain separate; independently measured phase medians must not
be added to claim an end-to-end median.

The [image-sized native benchmark](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/benchmark/report.md)
has all 18 fresh processes and 144 renders, covering passthrough, Linear + Tone
and full guarded Grade in both contexts. Warm render medians are 0.687 / 0.720 /
0.798 s Shader and 0.097 / 0.145 / 0.403 s Compositor. Including EXR transport
and readback, warm fixture medians are 2.587 / 2.613 / 2.736 s and 0.864 / 0.910 /
1.185 s respectively. This specialized evaluator benchmark is separate from
persistent edits and displayed previews; passthrough subtraction does not
establish isolated Grade cost.

The separately run [host preparation refresh](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/preparation-costs/report.md)
retains 20 measurements, stable sources and 24,960,704 resident RGBA32F bytes.
Complete preparation medians are 184.764–195.257 ms across four cases; all-active
Web parameters take 96.087 ms and Web toes 2.165 ms. No native upload, graph
construction or rendering is included in those host costs.

Numerical acceptance remains **failed**: 60 of 960 checked draws, exclusively
`web_stress`, exceed the unchanged `1e-4` normalized RGB limit. The worst error
is `1.9390252628269624e-4`. The [same-input isolation](../../buck-out/persistent-grade-evidence/software-gpu-timings-20261030/web-stress-diagnostic/report.json)
holds the Cycles engine, 1024² pixels, settings, graph and source revisions
fixed while switching the Compositor from CPU to GPU. At the exact 32 GUI probe
pixels, CPU peaks at `9.59719435e-5` (under the gate) and GPU at `1.93317162e-4`
(over it). The Compositor GPU path therefore reproduces the failure without
Eevee or any Color AOV. Switching the Web-toe back to its original 524,288-cell
layout leaves both probe maxima unchanged, so the 1,536-cell runtime toe did not
cause this gate result. EXR/readback/reconstruction comparisons are bit-identical
within each path.

The same diagnostic includes an unmasked exploratory scan over all 1,048,576
pixels, beyond the existing 32-probe gate. Its raw normalized maxima are
`0.0300431` CPU at pixel 9,478 and `0.1799924` GPU at pixel 210; the worst GPU
pixel is a near-neutral `[0.18, 0.18, 0.18]` input that returns approximately
`0.18` versus the reference's `6.68e-6`. These are unmasked diagnostic maxima,
not a newly accepted correctness gate. Independent scalar and batch reference
recomputation confirms all 35 retained worst/probe witnesses are valid and
well-conditioned; reference margins at the two maxima are approximately 342.80
and 399.93. The current 32 probes therefore do not certify the whole image.
Focused Buck2 GUI-summary, native-fixture and persistent-lifecycle tests pass
(15 tests). Runtime equations, layouts, gates and dependencies were unchanged
by the timing work.

## Active Web-toe reduction: HDR admission

The user authorized selecting the fixed runtime Web-toe layout by a maximum
signed HDR worsening of **0.05 fractional 10-bit codes** against the original
524,288-cell toe. Use the pinned ACES HDR-1000 / Rec.2100-PQ pipeline and
`max(abs(candidate-reference)) - max(abs(baseline-reference))` per pixel.
Measure every supported candidate from 256 through 2,048 cells in 256-cell
steps over all 149 cases, 1,024 pixels, three spaces and both CPU contexts;
select the smallest passing candidate, without assuming monotonic errors.

For this toe-layout admission only, scalar interpolation and local Web-state /
returned-scale errors remain truthful diagnostics rather than size blockers.
Preserve finiteness, significant-sign, validity, saturation, containment and
final scene-linear checks. Require zero candidate-versus-baseline validity or
saturation flag changes. Other fields retain their existing accuracy gates;
the inherited expanded-node-budget failure remains separate.

Keep the 524,288-cell comparison baseline explicit in source-bound reports even
after promoting the smaller fixed layout. Retain complete scalar maxima and
witnesses for every distinct toe function, local/seam diagnostics, native image
readback and lower-candidate rejection reasons. Runtime preparation still
performs no accuracy search. Rebuild persistent graphs to adopt the new fixed
dimensions; an update must never resize an existing image. Preparation reuse
must reject obsolete table dimensions. Re-run the four-case, five-repeat
texture/preparation report without concurrent heavy work after promotion.

The source-stable [toe sweep](../../buck-out/persistent-grade-evidence/toe-hdr-005/sweep-merged/report.md)
selects **1,536 cells**: maximum signed worsening is `0.0393597186` codes;
1,280 cells reaches `0.0506249517` and is rejected. Independent artifact
validation confirms 894 baselines and 7,152 candidate rows, including 720
measured rows, with no generation, render or nonfinite failures. The runtime
now uses a `1,537 × 1` RGBA32F toe texture (`24,592` bytes).
The [local/seam diagnostics](../../buck-out/persistent-grade-evidence/toe-hdr-005/local/report.md)
record zero safety failures and retain 16 raw precision failures across 112
comparisons. The [promoted-layout verification](../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-merged/report.md)
repeats all 894 baselines and 894 candidate rows (90 measured, 804 inactive)
with the same maximum worsening, no validity/saturation changes and all retained
final-output/containment checks passing. Its [independent validation](../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-validation.json)
confirms the receipt. The final [selected-layout local diagnostics](../../buck-out/persistent-grade-evidence/toe-hdr-005/promoted-local-final/report.md)
have zero safety failures and two raw precision failures across 14 comparisons.
All 11 focused Buck2 targets pass, including specialized and persistent Color
stages, guarded full Grade and persistent update/rollback/save/reopen.

The isolated [texture-size and preparation-cost rerun](../../buck-out/persistent-grade-evidence/toe-hdr-005/preparation-costs-final/report.md)
records 20 measurements with stable sources. The toe saves **8,365,040 bytes
(99.7069%)**; total resident RGBA32F payload is **24,960,704 bytes**.
Toe-generation medians are **2.122–2.149 ms** and complete portable preparation
medians are **186.180–192.829 ms** across the four cases. These exclude native
upload, construction, rendering and interaction latency. The [aggregate receipt](../../buck-out/persistent-grade-evidence/toe-hdr-005/summary.md)
links the complete sweep, diagnostics, promoted verification, tests and clean
timing. The inherited expanded-node cap remains open. Earlier receipts below
retain their original layouts and policies.

## Measured HDR end-to-end RGB sensitivity report

The source-stable [HDR report](../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/report.md)
compares the independent reference model, the current native node tree and
reduced helper-texture candidates after the pinned Blender OCIO view
`ACES 2.0 - HDR 1000 nits` on `Rec.2100-PQ`. The view performs PQ encoding once. Values
are fractional full-range 10-bit codes (`encoded * 1023`), with no clipping or
integer quantization.

It covers all 149 retained cases, three scene spaces, both Shader and
Compositor CPU contexts, and all 34 candidate layouts. The merged receipt has
894 baselines and 30,396 candidate rows: 8,286 measured candidates, 22,110
explicitly inactive (`not_sampled`) rows, and no generation, render or
nonfinite failures. Eight parallel case shards were merged only after exact
case, row, journal, checkpoint and source-identity validation.

The worst current-layout error is **7.9856666 codes**; 24 of 915,456 baseline
pixel samples exceed one code and four exceed two. All baselines pass the
scene-linear output gate; 21 retain the existing expanded-node-budget failure.
Among measured candidate rows, 256 fail the scene-linear output gate, 678 fail
the inherited node-budget gate and 3,744 fail scalar-field gates; containment
remained within the report's `8e-6` allowance. The largest measured candidate
worsening is **186.780493 codes** at
Tone/32. Web parameters/4096 and the combined 4,096-parameter/32,768-toe
candidate have no scalar-field failures in measured rows; Web parameters/2048
has six and the smaller Web toes candidates retain their scalar witnesses.
These are sensitivity results and do not waive intermediate gates or change
shipped layouts.

The [sensitivity table](../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/sensitivity.md)
also reports percentage worsening relative to each reference pixel's peak code.
The combined Web candidate worsens error by at most **0.0404497 codes**, or
**0.145225%** of the reference peak; the two maxima can occur at different pixels.
The 32,768-cell toe alone adds at most **0.000701219 codes** or **0.00148168%**.

The [summary](../../buck-out/persistent-grade-evidence/hdr-end-to-end-20261030/summary.json)
contains gate counts and candidate maxima. Report JSON SHA-256 is
`41692459fffffa36b2c99eeeef9b3810da1818a7740376abe2a4ea920466a856`; summary
JSON SHA-256 is `0a553d30d7f426f4091f286744f82ed90e1e181bb7f958ce57583fdcd8884398`.
Near-black percentage denominators, complete worst-pixel witnesses and OCIO
processor identities remain in the JSON; no per-pixel archive is stored.

## Audit follow-up — 2026-10-30

The latest fixed-field audit was rerun against the complete 149-case corpus with
stable source identities. Under the original scalar gates, it passes and retains the selected runtime minima:
Color coefficients `131072` cells, Web parameters `32768` cells and Web toes
`524288` cells. Smaller candidates remain recorded as failure witnesses; the
scalar audit's smaller Adaptance selections do not replace the larger runtime
layouts while native local gates are the authority for those fields.

The source-stable native Web candidate run covers 48 comparisons. Candidate
local field failures remain visible, while every completed candidate comparison
passes the final RGB check. This is evidence about the field-size tradeoff and
does not waive local gates or the strict expanded-node cap. The full 102-row CPU
rerun passes its numerical gate (`2.6288837137644723e-5` worst normalized RGB)
and fails the existing node-budget gate. The coherent sensitivity report covers
4,656 perturbation rows and leaves all production gates unchanged. Receipts and
the policy analysis are in [EVIDENCE.md](../../libraries/perceptual-grade-nodes/EVIDENCE.md)
and [GATE_REVIEW.md](../../libraries/perceptual-grade-nodes/GATE_REVIEW.md).

The clean fixed-layout preparation-cost rerun is complete and source-stable:
20 measurements (five repetitions across four cases) report 33,325,744 resident
RGBA32F payload bytes. Complete preparation medians range from 0.859065 to
0.876255 seconds; Web-toe generation medians range from 0.668457 to 0.691719
seconds. These are host preparation costs. The [report](../../buck-out/persistent-grade-evidence/preparation-costs-final/report.md)
retains measurement scope and the [raw JSON](../../buck-out/persistent-grade-evidence/preparation-costs-final/report.json)
has SHA-256 `92cfedbfc9f8d8714c363c483d4ea3d62538f8f1d498744fa3086769a5406b6c`.

The user subsequently authorized `1e-4` for both the conditioned and relative
Web-toe scalar errors in `web_alternating_extremes`. This case-specific sizing
study retains the original gates for ordinary controls and all other fields.
Its complete sweep selects `32768` cells (`32769` unique height points) as the
smallest passing supported grid; `16384` and every smaller supported grid fail
both limits. The [combined scalar receipt](../../buck-out/persistent-grade-evidence/toe-limit-1e4/acceptance.json)
covers all 16 distinct toe functions in the retained 149-case corpus. The
[native candidate report](../../buck-out/persistent-grade-evidence/field-effects-toe-32768/report.md)
passes all 12 final RGB comparisons, with no validity or saturation changes.

The [paired preparation report](../../buck-out/persistent-grade-evidence/toe-32768-costs/report.md)
measures about 36 ms of toe generation and 221–229 ms of complete preparation
at the candidate size, versus 667–670 ms and 858–863 ms at the current size.
The toe payload would fall from 8,389,632 to 524,352 bytes and total resident
payload from 33,325,744 to 25,460,464 bytes. Runtime remains `524288` cells;
these receipts establish the requested sizing experiment, not a changed runtime
layout or renewed full local-stage/persistent/GPU acceptance.
The [full candidate texture breakdown](../../buck-out/persistent-grade-evidence/preparation-costs-toe-32768/report.md)
reports all resident fields, 20 measurements and the process-local layout
override; its JSON SHA-256 is
`ece0733a2c3f9f6dee48a5a418b1adcddbc5465e304febe2f134d77fdcdf9a11`.

Under the subsequent user-authorized case-specific Web policy, the combined
4,096-parameter / 32,768-toe candidate would use 10,778,864 resident RGBA32F
bytes (10.280 MiB), while the checked-in runtime still uses 33,325,744 bytes.
The [separately measured candidate breakdown](../../buck-out/persistent-grade-evidence/preparation-costs-web-4096-toe-32768/report.md)
records 132–150 ms complete portable preparation across the four cases.

The follow-up audit now has an executable, narrow exception for the exact
`web_alternating_extremes` checkerboard. Its Web-parameter conditioned and
radial-log scalar limits, Web-toe conditioned and relative limits, and native
Web local/returned-scale limits are `1e-4`. Ordinary controls, non-Web stages,
finiteness, validity, sign/saturation, final RGB, boundary and node-budget
gates remain unchanged. Complete source-stable receipts show 4,096 parameter
cells plus 32,768 toe cells is the smallest tested pair passing all of these
Web gates; 2,048 parameter cells fails scalar absolute log and native local /
scale checks. The checked-in runtime layout remains 32,768 parameters and
524,288 toes. See [GATE_REVIEW.md](../../libraries/perceptual-grade-nodes/GATE_REVIEW.md)
and the [scalar](../../buck-out/persistent-grade-evidence/web-parameters-limit-1e4/acceptance.json)
and [native](../../buck-out/persistent-grade-evidence/web-parameters-native-local/report.json)
receipts.

## Persistent lifecycle contract

Production preparation must generate one fixed, development-audited layout per
helper-field role.
Resolution search and dense reference-accuracy gates belong only to explicit
development audits. Certify the smallest passing supported resolution across
the retained corpus, keep lower-candidate failure witnesses, and preserve all
local/native accuracy and containment gates except for the explicitly authorized
Web-toe HDR admission above. Existing selected-size maxima are
starting candidates, not minimality certificates. Keep coefficient-generation
operations needed for monotonicity and cheap input/geometry/finite checks.

Initialize every Linear, Tone and Color path, optional Color family, precision
alternative, sampler and fixed-size helper image once. A persistent Grade keeps
its native tree, node and image identities and image dimensions throughout
edits. Bypass neutral stages through links, including diagnostic links; do not
delete dormant nodes or lazily create a family's nodes on first activation.
Dragging one stage preserves every other authored non-neutral stage. Retain
the output guards and frozen post-Tone selectors. All resident nodes count
toward the original strict full-graph cap, including disconnected paths.

Prepare only changed dependencies. Linear-only edits update matrices and reuse
Tone/Color fields; a Tone change invalidates Color only when its derived inputs
change. Generate changed fields once, then apply values and links under native
reader exclusion to the same tree. Reject stale revisions, retain prior data
for rollback, and publish only after complete verified application. Failure to
restore an affected owner retains repair debt. Next core remains portable;
Next Blender owns admission, native updates, persistence and publication.

Report initialization separately from interaction. In an already initialized
scene/tree, measure accepted parameter sample to the first matching evaluated
preview draw, including waits, coefficient generation, upload/packing,
rewiring and any native compilation/evaluation. Use occurrence/revision
identities, retain first activation and superseded/undrawn samples, and report
raw timings plus p50/p95 without an invented speed threshold. A redraw request
is not draw completion. Record exact backend/device and separate standalone
GUI-preview evidence from eventual Next product acceptance.

The original node-budget requirement and temporary oversized admission remain.
Do not narrow settings, weaken gates or restore 2D Web to obtain a pass. Prior
2.1-second/75–80-second preparation measurements include adaptive audit work;
prior construction measurements include fixture setup. They do not predict
fixed-layout drag latency. Current implementation receipts belong in the
library evidence. Earlier deliveries below retain their recorded source scope.

---

# Previous handoff: build-time boundary resource and 1D-only Web

Last updated: 2026-10-29

**Status: the two requested changes are implemented and the handoff is ready. Full 1D node-budget acceptance remains open.**
The immediate delivery moves fixed output-boundary preparation to Buck2 and
removes the 2D Web preparation/evaluation path. Another developer will finish
1D graph optimization and final acceptance. Current receipts and the remaining
work belong to [the handoff evidence](../../libraries/perceptual-grade-nodes/EVIDENCE.md);
the earlier 2D-enabled delivery below is a historical baseline. The 57 current
tests and all six CPU/UI/available-GPU numerical reports pass. The UI sweep
reaches 1083 Shader / 1025 Compositor nodes. The updated 18-process / 144-render
benchmark is recorded; combined full-grade acceptance fails solely on the
original node budget. The fixed boundary loads in about 27 ms in that CPU
fixture, while full grade-dependent preparation takes about 2.1 seconds and
construction about 10 seconds. The evidence records timing scope and host I/O
limitations; these are not interactive-latency guarantees.

The user explicitly authorized oversized complete graphs temporarily so the
remaining 1D implementation can be evaluated. `build_group` must construct them
without an atlas retry. The original requirement remains **fewer than 1000
expanded nodes**, counting every nested occurrence, sampler, adapter, interface,
alpha and diagnostic. Reports separate `numerical_passed` from
`node_budget_passed`; combined `passed` requires both. Record exact counts and
`nodes_over_budget = max(0, expanded_nodes - 999)`. A budget-only failure must not
prevent numerical evaluation of the same grade, or silently count as complete
acceptance. Restore strict construction enforcement after the 1D path meets the
cap. The isolated raw Linear/Tone cap remains 300 throughout.

Build `//libraries/perceptual-grade-nodes:boundary_resource` to produce the
versioned, deterministic `output_boundary.npz` and its validation report. The
acyclic dependency chain is portable `:code`, `:boundary_generator`,
`:boundary_resource`, then packaged `:runtime`. The generator owns the expensive
geometry solve and dense accuracy gate. Runtime `prepare_boundary(fl, aw, gamma)`
loads and validates immutable packaged data; missing, corrupt, incompatible or
context-mismatched data fails explicitly, with no runtime regeneration fallback.
The 513 × 321 RGBA32F seed, native correction and actual-decoder containment
check remain unchanged. Generation is fixed work for the supported D65/203-nit
AP1 `[0,1024]` context. Callers may share loaded host geometry across grades;
each native group still owns its packed image. This change does not introduce a
global cache, shared Blender-image owner, or compact-NPZ boundary evaluator.

Web uses the existing 1D sector coefficients and toe fields only. Remove
`WebMap`, `prepare_web_map`, `prepare(..., web_atlas=...)`, the prepared atlas
fields, native atlas branches and automatic node-budget retry. Keep generic 2D
sampling for the independent output-boundary seed. No hidden compatibility
switch or replacement RGB grading LUT belongs to this change.

Keep the float64 reference and grading model unchanged: frozen post-Tone
selectors, `r=(35/75)*abs(J_A)`, Tone Quintic 512 / Fit `[-2,3]`, and Color Fit
`[-2,6]`. No input RGB repair is allowed. Preserve signed float32 saturation and
its explicit diagnostic without flagging inactive branches. Retain the `1e-5`
parameter-field and per-Color-substage gates at identical float32 inputs,
reporting accumulated raw Color error separately. Boundary radius remains
`2e-5` plus actual native containment; complete guarded RGB remains `1e-4`,
including saturation and signed-HDR cases through ±1024. Neither output guard
may conceal a failed local gate. Consult the user before any model change.

The handoff must preserve every numerical case, source-bind receipts to the
packaged boundary asset as well as code, and distinguish build-time generation,
runtime loading, grade-dependent preparation and native construction/evaluation
costs. Keep numerical failures visible; do not reduce coverage or weaken gates
while optimizing node count. Linux software OpenGL acceptance does not certify
physical GPUs or Metal. Next integration and old products remain unchanged.

Remaining delivery: reduce complete 1D Shader/Compositor graphs below the cap,
restore rejection of oversized construction, rerun complete numerical/resource
and performance acceptance, and record any further preparation/storage tradeoffs.
Current implementation checks, exact over-budget cases, resource identities and
reproduction commands are recorded in the evidence. Full grading acceptance
remains incomplete until its original cost and numerical requirements pass.

---

# Historical delivery: native grading with the 2D Web option

Last updated: 2026-10-29

**Status: complete; numerical/native acceptance passes and image-sized costs are recorded.**
All 53 library tests and six end-to-end reports pass. Measured maxima are 998
Shader / 946 Compositor expanded nodes, `8.98041e-6` local Color error and
`4.49071e-5` guarded RGB error. Timings, source receipts and platform limits are
in [the evidence](../../libraries/perceptual-grade-nodes/EVIDENCE.md). Next integration
remains deferred.

Extend `libraries/perceptual-grade-nodes` with the complete reference Color stage,
including the tonal web, selective Adaptance, H–K repair and the native AP1
`[0,1024]` output boundary. Keep the float64 reference equations and accepted
settings unchanged. Use the current `C=(35/75)*abs(J_A)` crossover and frozen
post-Tone selectors. No input RGB repair or 3D RGB grading LUT belongs to this path.

Packed 1D/2D helper textures are permitted. Native arithmetic first uses stable
norms, ratios and energy carry; unavoidable overflow saturates to signed float32
limits and is reported separately. This is a native representation policy, not
a change to the reference. Inactive branches must not report saturation. NaNs
are failures, not invented zero results. No new reference control/input admission
policy is authorized.

The fully active Shader and Compositor groups must each contain fewer than 1000
expanded nodes, including every nested occurrence, sampler, adapter, alpha and
diagnostic. Retain the isolated Linear/Tone cap of 300 and its Quintic 512 / Fit
−2…3 contract. Color Fit remains independently −2…6. Optimize actual native
evaluation as well as node count, and measure preparation, graph construction,
cold evaluation and repeated image-sized warm evaluation separately.

Keep independent `1e-5` coefficient and unsaturated local-stage accuracy gates,
with conditioned signed-energy error reported alongside absolute/sign errors.
The user clarified that Color's internal acceptance applies to each substage at
identical float32 input states and frozen selectors. Accumulated raw Color error
is measured and reported separately; it is not another `1e-5` gate. Strong final
scale can amplify a preceding local error. The reference and final RGB gate remain
unchanged; intermediate saturation is not an excuse to skip unsaturated pixels.
The corrected boundary radius has a `2e-5` normalized gate plus actual AP1
containment. The complete guarded RGB gate remains
`max(abs(actual-reference))/(1+max(abs(reference))) <= 1e-4`, including saturation
cases in the practical signed-HDR corpus through ±1024. Saturated raw states
cannot claim unchanged-reference internal parity; report their discrepancies.
Neither saturation nor output projection may hide an ordinary internal failure.

Expose portable Color/Web settings and preparation, reusable stage builders,
carried appearance state and a guarded RGB wrapper, with explicit raw export for
regression/composition. Preserve alpha, ownership, rollback and packed persistence.
Reference/old-core code remains a development oracle, never a nodes runtime
dependency. Next core stays host-independent and future Next Blender composes
the native builders. This task does not implement Next product workflows.

Require pinned Blender CPU acceptance and exercise the available GPU runners;
report exact platform coverage, source identities, failures and measured costs.
Keep this document, CHECKLIST and library/API/evidence documentation current.
Do not claim completion before accuracy, containment, ownership and node-budget
gates pass. Consult the user before any additional grading-model change. Preserve
existing products, historical delivery evidence, the supplied project and Git.

---

# Completed delivery: reference Stage 3 saturation crossover

Last updated: 2026-10-28

**Status: complete; affected reference/product checks pass.** The analytic reference's low/high
chroma membership uses `r = (35/75)*abs(J_A)`, `V = C²/(C²+4)`,
`low = V*r²/(C²+r²)`, and `high = V*C²/(C²+r²)`. Neutral/black drivers
are zero; chromatic `J_A=0` is all high. Evaluate stable ratios in float64 and
scaled-number paths, using frozen post-Tone inputs. Opponent drivers, energy
carry, web, Adaptance, gamut guards and Stage 1/2 remain unchanged.

The available historical 1.23.2 source confirms the 35/75 ratio. Its negative
`J_A` clamp is deliberately replaced by signed symmetry through `abs(J_A)`.
Membership must not depend on hue, RGB gamut or boundary capacity. Analytic
Model, inverse, Stack and CLI inherit this law without a settings mode.

Reference BakeStack must reject any nonzero low/high lightness or chroma control
before accelerated preparation, including matching forward/inverse pairs.
Unaffected controls remain supported. Shared CPU/GPU kernels and current
Blender/DCTL production behavior stay capacity-based. Explicit verification-only
legacy adapters preserve their numerical tests and offline analysis tools;
these adapters must not enter runtime/extension bundles.

Acceptance covers midpoint/sign/hue/neutral laws, scalar/vector/scaled agreement,
frozen drivers, analytic inverse/Stack/CLI, accelerated rejection and supported
controls, legacy product parity, and Linear + Tone native regressions. Control
acceptance cases stay within UI ranges; numerical representation stress cases
are separate. Update active reference plots/formulas and label retained .4U
proofs and experiments as production/historical, not evidence for the new law.

Leave Git untouched. Stage 3 native nodes and accelerated support for the new
crossover are deferred. The standalone experiment's Fit maximum 3 / Quintic 512
does not constrain the general reference model. Its completed evidence below
remains tied to the source hashes recorded at that delivery.

Acceptance evidence and exact build IDs are recorded in
[`libraries/perceptual-grade-reference/CROSSOVER_EVIDENCE.md`](../../libraries/perceptual-grade-reference/CROSSOVER_EVIDENCE.md).
Reference equations, inverse/Stack/CLI, accelerated rejection, product CPU/DCTL,
23 GPU inverse cases, both changed GPU oracle cases, native Linear + Tone,
architecture and root verification pass. The broader GPU baking suite retains
one unrelated stale `sampling.sample_image` test failure; it is documented and
does not certify an all-green GPU suite. Five updated analysis targets build;
the driver equation checks report zero discrepancy across 274,625 samples.

---

# Completed delivery: native Linear + Tone node experiment

Last updated: 2026-10-28

**Status: implemented; Linear + Tone numerical/native acceptance passes.** Build
an independent reusable library at
[`libraries/perceptual-grade-nodes`](../../libraries/perceptual-grade-nodes/README.md),
with Python package `color_tools.perceptual_grade_nodes`. This experiment is the
completed work. The audited Next handoff below is retained for later implementation;
this experiment does not complete its workflow or product milestones.

**Settled numerical decision (2026-10-28): maximum Fit is 3 for this standalone
path, using Quintic 512.** The coefficient layout samples normalized source
position uniformly through `1 + 32 * width`, then retains the analytic linear
tail. The measured Fit-3 corpus has 932 dense comparisons across 233 distinct
UI-valid anchor sets and all four peaks, with worst normalized scalar error
`8.2532e-6`; Fit 4 fails at `1.0127e-5` in the minimum-gap sweep. Keep the
`1e-5` per-curve gate, and reject out-of-range Fit values explicitly. The
existing extension controls remain untouched; the experiment tests their allowed
domain intersected with its new Fit limit. Final CPU, UI-boundary and optional
GPU reports pass with matching source hashes; details are in
`libraries/perceptual-grade-nodes/EVIDENCE.md`.

Evidence: `buck-out/nodes-fit512-analysis/dense-boundaries.md` and
`buck-out/nodes-fit512-analysis/fit3-dense.json`. These finite sweeps support a
practical limit, not an exhaustive guarantee over all possible UI combinations;
per-curve coefficient validation remains active.

Implement forward Linear and Tone as native Blender Shader and Compositor node
trees without a 65³ RGB LUT. Keep preparation host-independent, expose reusable
stage builders and post-Tone appearance sockets, and provide an RGB-in/RGB-out
wrapper. Full immutable linear/tone settings follow the reference schema,
including exposure, source xy, directional balance/spread/heading, and optional
authoritative XYZ matrix. A future UI adapter owns the existing Grade balance
sign conversion. D65/203-nit grading in Linear Rec.709, Linear Rec.2020 and
Bradford-adapted ACEScg is the v1 comparison contract.

The **complete future three-stage graph must contain fewer than 1000 nodes**.
Linear + Tone, including conversions, coefficient sampling, alpha and decode
diagnostics, has a **300-node cap and a 200-node optimization goal**. Count every
nested group occurrence and its internal nodes; grouping does not hide cost.
Stage 3 consumes the existing appearance state before RGB decode and is deferred.

Use the current reference's signed appearance/Tone equations. Do not transplant
the historical neutral-lift/subtract or input-fallback semantics. Precompute
parameter-only expressions, combine constant matrices, reuse intermediate values,
use vector operations and the exact compact hue-eccentricity polynomial. No
pixel evaluation runs in Python. Tone uses a shared-jet quintic residual table
and an analytic linear tail. Select 512 cells only when deterministic dense
float32 scalar checks meet normalized error <=1e-5 and monotonicity. Otherwise
fail preparation explicitly; do not relax the gate. Coefficients are packed
float32 Non-Color/channel-packed images with nearest sampling, 512-wide packing
and half precision disabled.

Compare raw Linear -> signed appearance -> Tone -> RGB with
`libraries/perceptual-grade-reference`, with input repair and export guards off.
Reference and Blender fixtures are evaluation/test dependencies, never runtime
dependencies. The final per-pixel RGB gate is
`max(abs(actual-reference)) / (1 + max(abs(reference))) <= 1e-4` where all reference
decoded response magnitudes are <=300. Report valid near-pole cases between 300
and 400 separately, including stage errors, validity disagreements and finite
output. The wrapper exposes Decode Valid and Pole Margin; an invalid decode
returns finite black while post-Tone appearance remains available. Test signed
HDR through +/-1024, all linear controls, tone anchors/plateaus/tails, narrow
intervals, fit -2..3, peak settings, exact reset/black and unchanged alpha.

Use the existing Buck component/bundle conventions with new library-local tests
and reproducible JSON/Markdown reports. Require pinned Blender 5.2.2 Cycles CPU
and full-precision Compositor CPU acceptance; exercise Eevee/Compositor GPU when
the configured runner supports them and record actual coverage. Verify packed
save/reopen without extension registration. Reports include expanded node counts,
table choices/memory, absolute/normalized/percentile/near-black errors, invalid
cases, preparation time and cold/warm native evaluation timings.

The synchronous builders return caller-owned native resources and clean up
partial construction failures. They introduce no App, actor, Machine, global
cache, timer, handler, UI or Gizmo. Invariant verifies discrete workflow policies,
not floating-point shader accuracy; it does not certify this numerical experiment.
The library remains standalone: future Next core supplies portable settings and
policies, and Next Blender composes the native builders. Do not add native
responsibilities to Next core.

Leave Git untouched. Preserve existing core/product sources, Buck aliases,
extension packaging and the supplied project. No Stage 3, inverse grading,
input/export guard, product integration or workflow implementation is included.
Stage 3 remains deferred; its fit within the remaining graph budget is untested.
The historical evidence below does not certify this experiment; the new tests
and reports in the linked evidence close only this Linear + Tone scope.

---

# Previous delivery: Bake input interruption and saved editor controls

Last updated: 2026-10-27

**Status: complete; verification and installed acceptance pass.** This contract
supersedes older frozen-Bake and native-wrapper restoration behavior below.

Every unfinished Bake observes its own effective input dependencies. Changing the
selected Grade, Grade/Stack parameters, a relevant upstream input or its source
interrupts that request, preserves the previous baked Image, and requires another
explicit Bake click. Upstream nodes do not enumerate or cancel downstream Bakes.
Unrelated work, node layout/selection/names and generated LUT updates do not revoke
a request. Fresh mesh/UV observations include semantic attributes while excluding
selection/display fields; bulk reads avoid per-element RNA traversal. Logical
cancellation retains physical helper/queue leases until retirement.

New saves preserve the custom Grade/Stack controls through portable native wrapper
serialization. Explicit saved wrapper metadata restores the editor type and original
dependency-driver mute state during bounded, source-bound recovery. Restoring the
wrapper preserves selected Grade/Image pointers, sockets, links and adopted output;
it does not regenerate or certify numerical output. Historical empty-node repair
and inferred datablock assignments are outside this task.

Validation is complete: 23 unique test targets cover 263 distinct Python cases.
Final installed checks cover Shader/Compositor controls, selections and tooltips
through save/reopen, Grade-change interruption, previous-image preservation,
Undo/Redo, playback, output resources, crash/restart and native-copy interruption.
Root `//:verify //:perceptual_grade //:hdr_color_picker` passes in build
`5ce714b7-822b-44aa-9947-7466dcda94e5`; all 24 source-bound machine proofs pass
2,702 obligations, 215 mandatory properties, 68 witnesses and 72 replayed mutations.
The retained Lean color-model checks also pass. Generic Invariant sources are unchanged.

Final ZIP: `buck-out/bake-controls-validation/perceptual_grade.zip`.
SHA256: `1cbeac27cd9b6c89a399cb97fcad0adebc972ec0741cdd9aa0eb7f2481a1cba6`.
Exact build/test identities, source and archive hashes, package/proof reports and
installed JSON reports are in `buck-out/bake-controls-validation/summary.json`
and `validation-index.json`. Counts exclude repeated runs and subtest variants.
Installed acceptance used Linux Blender 5.2.2 with virtual GUI/software rendering;
macOS/Metal is not claimed. The supplied `train-model.blend` remains unchanged:
`51f761e91dc23b1bfab8225b1842b27f54e52bcaf6670e3706565b92802be789`.

---

# Previous delivery: automatic scopes and predictable Blender controls

Last updated: 2026-10-26

**Status: complete; verification and installed acceptance pass.** This contract supersedes
older manual refresh, playback publication and node migration behavior below.

Bake uses Blender's native Image selector for creation, selection, renaming and
unlinking, with `+ New` only when empty and Bake on the next row. The public shader
coordinate input is `Vector`. Grade and Grade Stack expose only public sockets in
both editors; matrix, selector and intermediate LUT routing stay private. Save and
native wrapper restoration preserve socket visibility and the selected Image.

Scopes update automatically on first open, meaningful source changes and frame
changes. There is no Refresh Scope control. Playback retains the accepted display
and suspends acquisition/publication; stop resumes only after native evaluation
finishes. One immutable active acquisition and one newest pending demand prevent
starvation during edits. Compatible completed captures publish progressively using
latest analytical parameters, with frozen upstream Grade payloads and coherent
primary/reference source snapshots. UI/name/layout changes and unrelated graph
edits do not trigger new captures. Frame labels identify the accepted samples.

Unavailable Bake routes are disabled with localized corrective hover text: destination
domain mismatch, Eevee UV baking, Shader to RGB, unsupported sources and unfinished
native evaluation. Scheduled preflight keeps expensive validation out of draw/poll;
execution rechecks admission. The extension never silently changes the scene engine.
Unexpected public-callback failures produce localized inline status and retain
technical diagnostics in logs. Current-format load/Undo recovery remains; historical
migration and compatibility repair paths are removed.

Validation is complete: 42 targeted suites cover 622 distinct Python test cases,
with no unresolved failures. Final installed acceptance includes Shader/Compositor
Bake, all three scope pages, playback stop, native capture, save/Undo, crash/restart
and 12 actual native-copy interruption checkpoints. The root build
`//:verify //:perceptual_grade //:hdr_color_picker` passes in
`129fe117-c091-4faa-ae7e-5334c01a03bb`. All 24 source-bound machine proofs pass
2,674 obligations, 213 mandatory properties, 67 witnesses and 71 replayed mutations;
the retained Lean color-model checks also pass.

Final ZIP: `buck-out/automatic-scope-validation/perceptual_grade.zip`.
SHA256: `41b66a53404ebf0be99229012fb81f59ef060bce43faf66cfd4b34cd988c0cf6`.
Evidence, exact test/build identities, package/proof reports and installed JSON
reports are in `buck-out/automatic-scope-validation/summary.json` and
`validation-index.json`. Counts exclude repeated runs and subtest variants; the
Bake suite's final coverage combines 56 cases with its focused native replay case.
Native acceptance used Linux Blender 5.2.2 with virtual GUI/software rendering;
macOS/Metal is not claimed. The supplied `train-model.blend` remains unchanged:
`4a6fa6569398d058dab073eaa254c8701409f71d68cefd08acbbeaf83053dd79`.

---

# Previous delivery: native evaluation readiness and release-to-activate scope refresh

Last updated: 2026-10-26

**Status: complete; proofs, tests, installed acceptance and root verification pass.**

Bake admission, operator polling and drawing now share the native-reader boundary
for Shader and Compositor Grade/Stack. Timeline stop does not release evaluation
leases. Pending observations, active evaluations, native jobs/locks and unsettled
actor outcomes keep Bake disabled. Localized hover help explains the wait without
an inline status row. Transient race clicks create no request or snapshot and do
not report the former native-evaluation error.

The shared `blender_runtime.policies.native_evaluation` policy owns an unbounded immutable
ledger of exact leases, generation and observation revision. Callbacks latch scalar
observations without waiting on actors. Foreground processing validates exact
append/removal and publishes acknowledged immutable state; admission rechecks the
revision after native job observations. Render leases span init through complete
or cancel, independently of per-frame posts. Recovery and fenced cleanup drain
observations before waiting, and background explicit effects can acknowledge
completion without a UI timer. Native replacement alone may retire old leases.

The source-bound proof passes 129 obligations, 16 mandatory properties, four
positive witnesses and six detected/replayed mutations. Generic Invariant sources
are unchanged. Blender callback pairing and native job observations remain
integration-tested premises; synthetic IDs do not manufacture native operation IDs.

Refresh Scope Inputs now arms on press and authorizes once on release inside the
same button, target and editor/group occurrence. Motion cannot enter chart-drag
math. Outside release, Escape/right-click, focus/context changes and lifecycle
settlement cancel without capture, grading changes, autokey or an Undo entry.
Release uses current input values; pending captures reject duplicate authorization.

All 373 cases across 20 targets pass, including installed Shader/Compositor Bake
and native-reader acceptance. Installed Gizmo acceptance against the delivery ZIP
passes six editor/page combinations, actual pointer motion and cancellation,
exactly-once capture, passive zero-authority behavior and clean teardown (Buck
build `7c947dbe-558a-42e1-b3a3-a687e08f9fb2`). Root
`//:verify //:perceptual_grade //:hdr_color_picker` passes in build
`24ffc02a-4a2c-4083-8465-28df4143a12c`. Validation is Linux Blender 5.2.2 with
virtual GUI/software rendering; macOS/Metal is not claimed.

Archive: `buck-out/native-readiness-validation/perceptual_grade.zip`.
SHA256: `cc7811cae688eeb6dc6779c0edeeac987274bef1607d99f61e3ad29fe6706ed2`.
This is Buck extension artifact `de3061a1d71b781a`, identical to the final root
build output. `summary.json`, logs, structured native reports, proof/package
reports and archive identity are retained in the same evidence directory.
The supplied `train-model.blend` remains unchanged during this implementation:
`4a6fa6569398d058dab073eaa254c8701409f71d68cefd08acbbeaf83053dd79`.

---

# Previous delivery: shader/image baking, shared readers and playback cancellation

Last updated: 2026-10-26

**Status: complete — Shading UI corrections verified.** The earlier worker/API
acceptance missed the Add menu and Shader draw callbacks. The corrected Add Bake
command accepts editable local Material/World root trees; Shader Grade/Stack
draw the flat route preview without exceptions. Route labels explain Image or
UV selection, and existing UV destinations display their actual dimensions.

Any explicit source Image Texture Vector link still selects UV to preserve
mapping. An unconnected ordinary still Image with pointwise grading uses Image
baking in Eevee as well as Cycles. Existing UV destinations retain their domain
until cleared/replaced. The selector keeps its managed-Image eligibility and
temporarily disables during native operations with a waiting explanation.

Baked Vector help explains sampling the stored image in both domains, its
active-UV fallback, and independence from live grading and bake-target UVs.
Standalone-reader binding now updates its Image property/kernel together without
appending Grade-only sockets. Coordinate synchronization runs on guarded timers
and recognizes saved native wrappers; node draws do not alter graph links.

The explicit Bake product now extends from
Compositor Grade/Stack nodes to Shader Grade/Stack nodes while preserving the
existing actor-owned queue, immutable worker inputs, guarded publication,
per-destination ordering, Undo/Redo and physical retirement.

The Bake action auto-selects one of two source domains. A supported ordinary
still Image plus the approved pointwise color/alpha graph uses a full-resolution
image-domain bake; the packed float RGBA result is shareable between Shader and
Compositor readers. Surface-dependent graphs use a Cycles UV bake on the active
mesh and are Shader-only. Shader Grade/Stack expose Baked Color and Baked Alpha,
and their shader-only Baked Vector input falls back to UV when unconnected.
Standalone Shader and Compositor Bake readers are manually placeable; no graph
is rewired automatically.

UDIM, Alembic-dependent geometry, movie/image-sequence inputs and texture-range
bakes are explicitly unsupported and recommend the 65³ LUT workflow. Shader to
RGB remains unsupported until Eevee provides a suitable UV-bake API. UV baking
requires Cycles, one active mesh target, a valid single-tile UV map and a
user-selected or newly sized destination Image. Image baking retains the source
Image dimensions and preserves the terminal Shader Alpha signal in the same
RGBA artifact as graded RGB.

Starting timeline playback cancels every unfinished explicit Bake, including
freezing, queued, running and ready-to-publish requests, even if playback stops
before the next timer tick. Native playback callbacks only latch the event;
helper cancellation and publication cleanup run later on Blender's ordinary
timer/modal path. The initiating nodes retain their previous Images, show a
per-node interruption status, and keep physical helper/queue leases until
retirement. A race-click during playback creates no request or snapshot, and a
Bake already committed before playback remains published. Automatic scopes and
LUT production continue.

The implementation adds route-aware native worker handling, persistent
reader/kernel ABI registration, append-only output-resource migration for old
Shader kernels, source-bound image/UV eligibility tests, shared Image behavior,
and playback cancellation. Existing compositor baking remains compatible.

Correction validation passes all 126 cases across seven targets: Bake 52,
routes 15, native Shader worker 12, source readers 17, recovery 23, locales 5
and extension packaging 2 (build `f41a1eb0-78b2-4799-b373-052cbcdf97da`).
Installed Shader GUI acceptance passes in build
`a99c5ba6-2a93-4231-a24c-8c7064465d3f`: real Material/World Add Bake operators,
successful production UILayout draws for Grade/Stack, Eevee Image baking,
reader/Grade coordinate edits and packed save/reopen. Cross-page selector
acceptance exercises native RNA search and assignment using a valid packed
Compositor-shaped fixture; it does not automate mouse selection in the popup.
Installed Compositor acceptance passes in build
`12f94d29-a792-466f-98bb-1f9a4257b75a`, including shared-image updates,
Undo/Redo, playback cancellation and helper retirement on Blender 5.2.2.

Root `//:verify` and `//:perceptual_grade` pass in build
`0f9f93ab-e461-454a-9693-fa44c5336a98`; final package build is
`7eb49366-2d83-425c-b05a-b54d0fa48fc4`. Archive:
`buck-out/shader-ui-validation/perceptual_grade.zip` (copy of Buck extension
artifact `539701086c808e74`), SHA256
`62996495e5d4f1255ca4e2ea3dabe849e394e9039319ae54c93cec969b1da335`.

---

# Previous delivery: playback, parallel baking and Undo responsiveness

Last updated: 2026-10-26

**Status: complete.** Continuous scope acquisition/publication during compositor
playback, independent parallel Bake requests and structural Undo recovery are
implemented and verified. The new `train-model.blend` remains unchanged (SHA256
`cf52d5f8e5d12df89fb9e56f3bd29928e35a40cff20681eaec3b756fff0a8647`).

The accepted scope model is one active immutable acquisition/analysis cycle and
one newest pending request. Completed compatible results remain visible during
playback. Stored Image data decodes in an isolated source-only helper; native
output writes and unsaved resident-buffer snapshots retain their guards.

Bakes use two independent workers. Other nodes can queue requests immediately;
requests sharing a destination run in click order, with click-time inputs frozen.
Keep per-target status, separate publication Undo steps and physical retirement.

The current approved Undo implementation establishes validity by producer structure
and source-bound machine proofs. Restored native output is adopted without pixel
readback, hashing, repair or automatic recomputation. Adoption has unknown numerical
provenance; the next actual Grade/Stack intent change resumes managed production.
A bounded recovery coordinator tracks retirement, discovery, per-owner adoption,
Image reconciliation and terminal success/failure. Retry preserves current-generation
debt. Save/render preserve unchanged adopted output, and downstream adopted sources
require explicit native scope capture. See the current recovery section in CHECKLIST.md.

Final ZIP: `buck-out/state-recovery-validation/perceptual_grade.zip`.
SHA256: `ed64a7f8fd79b193e35789eaacb9f247d78ebe16e8cc9b2ccea55b06a4727ec5`.
Root verification/package build: `034cac79-bc4f-462d-a0a6-b5a9e8d2217c`.
The five affected source-bound proofs pass 800 obligations and detect/replay all
21 mutations. Integration and native acceptance cover continuous playback,
save/reopen animation, two Bake workers, same-destination ordering, separate Undo,
native reader exclusion, output preservation and recovery failure/retry.

A quiet paired run on unchanged `train-model.blend` measured 12 Undo/Redo
boundaries per package with the same instrumented driver. Median time from native
pre-handler entry through runtime recovery completion fell from **1.651 s to
0.594 s** (2.78 times faster); recovery performs zero output pixel reads/hashes.
This includes deferred recovery and excludes the driver's subsequent fixed UI
waits. Acceptance used Linux Blender 5.2.2 with OpenGL llvmpipe; macOS/Metal is not
covered by this run. Evidence and exact measurements are in
`buck-out/state-recovery-validation/summary.json` and `undo-summary.json`.

Earlier baseline evidence remains in `buck-out/playback-diagnosis/`,
`buck-out/undo-latency-steady-20261025/` and
`buck-out/bake-undo-latency-20261025/`. Earlier playback/Bake validation remains in
`buck-out/responsiveness-fix-20261025/`.

---

# Completed fix: Gizmo context regression

Last updated: 2026-10-25

**Status: complete.** All 8 affected targets (127 test cases), root verification,
extension packaging and native GUI interaction acceptance pass. The full scope
suite passes 71 cases in build `820684bf-cfa8-4390-9561-c47cff2e2e54`.

The reported Blender 5.2 Gizmo hover/close crash is corrected in the scope
adapter. `bpy.types.Context` exposes `keys` but does not support IDProperty
membership; testing `'consumer' in context` raised `TypeError` before pointer
routing could finish. `sampling.channel` now distinguishes `Mapping` descriptors
from live contexts, forwards the supplied editor context to consumer discovery,
and uses that same editor for the unresolved fallback. Frozen descriptors,
read-only mappings, detached consumers and channel-key shapes are preserved.

Real-context regressions cover descriptor parity, two editors, a supplied
nonambient context, discovery failure and passive hover on all three pages.
A fresh installed Blender GUI test uses native pointer events to hover, close,
reopen and switch tabs on Linear, Tone and Color. It passes with zero native
descriptions or capture authorizations and clean teardown. The same test fails
against the previously delivered ZIP with the exact reported TypeError.

This is an adapter correction: state machines, `.inv` properties and generic
Invariant code are unchanged. Root verification and packaging pass, including
the existing 150 scope-input and 207 channel proof obligations. Linux Blender
5.2.2 virtual-GUI acceptance is recorded; this does not claim macOS/Metal testing.

Corrected ZIP: `buck-out/gizmo-context-fix/perceptual_grade.zip`.
SHA256: `1a6bbc4f2fb591ecc5282115313056dba093b9fa47354191d89b75f197256b71`.
Root verification/package build: `36c884b8-f474-4b39-a793-4342e12e3b10`.
Installed GUI build: `7cf2f47c-2ee5-418e-be02-33c667b3910c`.
The evidence report and exact target list are retained in
`buck-out/gizmo-context-fix/report.md` and `summary.json`. The redesign archive and
performance measurements below are historical and retain their original hashes.

---

# Completed goal: source-aware scope acquisition and latency redesign

Last updated: 2026-10-25

**Status: complete.** Root verification, extension packaging, all 29 affected
test targets (435 unittest cases) and 12 clean fresh GUI processes pass.
Automatic source acquisition, explicit native authority, weighted UDIM/reference
grids and playback coalescing are implemented. Twelve clean fresh GUI processes
passed all automatic/manual acquisition assertions in both saved workspaces and
both page orders. [CHECKLIST.md](CHECKLIST.md) records the current implementation,
source map and explicit reader boundaries.

The core `scope_input` coordinator is actor-owned and source-bound to its `.inv`:
150 obligations, 15 required properties, four witnesses and seven detected and
Python-replayed mutations. `channel.inv` now checks compatible historical-frame
publication, request epochs and preservation of newer failures, while retaining
final 65³ provenance and owner/session/signal fences. Actual Cube provenance is
validated before reusable active-source registration. Generic Invariant sources
and their upstream manifest remain unchanged.

The GUI benchmark uses the installed ZIP, generated temporary edits and ordinary
production callbacks. Median first matching Linear draw changed from **10.695 s
to 3.581 s in Shading**, and **3.332 s to 2.178 s in Compositing**. Selected Grade
edits measured 1.590 s and 1.310 s respectively. The automatic routes produced
zero native requests, scene fingerprints, snapshots or capture submissions.
Manual native click-to-draw medians were 7.606 s and 3.228 s; these begin after the
automatic page sequence and are not cold numerical-helper comparisons.

Color-first medians were 4.106 s Shading and 2.643 s Compositing. The report also
contains upstream edits, Image replacement/restoration, Transform bypass and
explicit stale-native retention. Periodic 0.5-second source probes remain active:
selected-only edit intervals usually included one decode even though the edit
itself did not force acquisition. No claim of zero total reads during those
intervals or a one-second latency guarantee is made.

Full timing ranges, exact measured archive/source hashes, excluded contended
runs and reproduction commands are in
`buck-out/scope-redesign-acceptance/report.md`. The manual blend remains unchanged
at SHA256 `bcd29253c2f5291a4feecfbc81b251cc92ef8317977c3fe7e795e805a460e7cb`.
The measurements are Linux virtual-GUI/software-rendering evidence, not physical
scanout or macOS/Metal acceptance.

Final root verification/package build: `76b5272d-a865-4b3f-8cbc-80483a72a5a8`.
Final consolidated test build: `16dcebbb-e64b-4b54-aeac-13a25b724ade`, including
68 scope, 51 capture, 17 Image-reader and 16 source-route cases, CPU/GPU numerical
checks, lifecycle/recovery, packaging and installed native/movie/Bake acceptance.
All 164 recorded runtime/proof inputs stayed unchanged during final testing;
all 20 baseline Invariant framework files remain unchanged.

Final ZIP SHA256:
`6f9c0bf7db1f47e1f75a2c99efd21f6c3365865b22607b631d4d0b9bbdb6f82e`.
The archive, package report, exact target list, source manifests and test/build
logs are retained in `buck-out/scope-redesign-validation/`; `summary.json` indexes
the evidence. The GUI report binds its measured ZIP separately. The final ZIP
adds only a native preflight rejection for unsupported edited/generated
multi-buffer Images; the final installed suite verifies ordinary native capture.
No timing is silently attributed to a different archive.

Explicit limits remain: movie decoding requires a visible Blender window;
squeezed stereo eyes use native-matching reconstruction. Save unsaved painted
UDIM and dirty animated multiview Images first. Static dirty multiview export
requires an initialized eye; tiled multilayer/multiview combinations fail
explicitly. Native snapshots reject edited/generated multi-buffer resources they
cannot preserve. Manual painted-eye, macOS/Metal and physical-display acceptance
remain separate boundaries, along with the pre-existing USD/Alembic reader gap.

## Accepted behavior

Scope acquisition has two explicit routes:

1. **Automatic Image route.** A simple Image/Image Texture source feeding a
   Grade is sampled without Blender scene capture. The original Image pixels are
   the scope input, independent of mesh, lighting, UV placement, viewport
   framing, occlusion and scene render state. The automatic route resolves
   reroutes, muted bypasses, exact nested group occurrences and upstream
   Perceptual Grade/Grade Stack models through their existing analytical/Stack
   evaluation. The automatic compositor Transform case keeps the original Image
   semantics and ignores placement/resampling. A simple
   movie or image-sequence source must resolve its current frame and update
   automatically; it must not be routed to native capture merely because its
   pixels are time-dependent.

2. **Manual native route.** A graph containing arbitrary Blender processing,
   Render Layers, shader surface evaluation or another source that cannot be
   represented by the automatic route is evaluated by Blender's native
   pipeline. This route supports HSL, RGB Curves, Color Balance, Transform and
   future native nodes without reimplementing each node in Python. It captures
   the complete processed input, including spatial operations.

Native capture is never automatic, including the first display. **Refresh Scope
Inputs** is exposed only as a button in the drawn Gizmo. It is hidden for an
automatic route. One click authorizes one exact Grade/editor/group occurrence
and its primary/reference inputs; later source changes revoke that authority and
leave the old result visibly stale until another click. The selected Grade's
own controls are downstream of its captured input and rerun analysis without
recapturing pixels. An upstream change in a frozen arbitrary native graph needs
another click. An upstream analytical Perceptual Grade change in the automatic
route recomputes its chain without rereading the Image.

Source samples and grading analysis have separate data/model cache identities.
Editor/Gizmo ownership is carried by a publication ticket, not by those cache
keys. Shared upstream Grade occurrences and reference inputs remain real
dependencies; excluding the selected terminal transform does not exclude every
use of its GradeData.

The capture redesign must preserve immutable worker inputs, stale-result fences,
physical helper retirement, shared-image bake isolation, Undo/Redo recovery and
load/disable generation barriers. It must not add a persistent node-tree index:
simple routes need a short occurrence-aware walk, while a local incoming-link
index is sufficient during an explicitly authorized complex description.

## Original motivation and baseline

The final observer-only measurements for `train-model.blend` showed that the
latency is structural rather than a single slow numerical scope calculation:

- Median first Linear draw: **10.695 s** in Shading and **3.332 s** in
  Compositing. Tone and Color usually reuse the first shared input, so their
  lower times are not like-for-like cold costs; a Tone-first run moved the cold
  capture cost to Tone.
- Shading performed 57 foreground descriptions before its first draw, about
  **5.6 s** of repeated graph/dependency and resource/scene revision work. Its
  native render took **4.87–5.15 s**, even though the final sample grid was
  bounded to 256×84.
- Compositing evaluated the full 2126×1418 image (about 46 MiB of RGBA data)
  before reducing it to approximately 256×171 samples. Native evaluation was
  about 0.27–0.28 s, with helper/readback and startup costs around it.
- Median **Capture dispatch → completion received** was 5.632 s in Shading and
  0.674 s in Compositing. These intervals include helper work, native evaluation,
  serialization/transport and foreground receipt polling; helper readiness
  before dispatch is measured separately.
- A real Shading Grade exposure edit unnecessarily changed the native capture
  identity even though the captured source RGBA and coverage arrays were
  bit-identical. The redesign must separate source pixels from selected Grade
  analysis identity.

The complete per-run report is
`buck-out/train-model-scope-latency-evidence-20261025/report.md`. Its phase
totals overlap the end-to-end timeline and must not be added as if they were
serial. The supplied `train-model.blend` remains unchanged.

---

# Completed goal: Correct viewport scopes and per-node bake destinations

Last updated: 2026-10-25

The orthographic viewport scope failure and compositor bake targeting are fixed.
Shading/Compositing latency has been measured and explained; no performance
optimization was included.

The accepted behavior is:

- Shader capture preserves the frozen viewport's complete projection and depth
  interval. A visible material must not disappear behind the helper camera's
  near plane. Perspective and scene-camera fallback remain supported.
- Compositor Grade and Grade Stack nodes have a searchable Bake Image selector
  that accepts only Images previously baked by Perceptual Grade. An empty
  selection creates and binds a new packed float Image on successful Bake.
  Clearing the selection unbinds without deleting the Image.
- A Bake button captures only its own node and publishes only to its frozen
  selected Image. Progress and errors belong to the initiating node. Explicit
  sharing of one Image still updates all consumers of that Image, without
  triggering other Grade bakes. Existing saved bindings remain authoritative.
- Keep actor-owned state, exact identity fences, guarded publication, rollback,
  packed-pixel Undo/Redo and physical snapshot retirement. No generic Invariant
  framework or machine-policy changes were needed.
- Measure context/fingerprint work, waits, snapshot/resource preparation,
  helper startup/load, native evaluation, pixel readback, analysis, adoption and
  first matching GUI draw. Separate Shading/Compositing, cold/warm runs and
  headless-current/GUI-draw timing; identify repeated and superseded captures.

The saved Shading view is orthographic. The former helper matched XY framing but
put visible geometry behind its near plane, producing "no visible samples".
The helper now derives the complete depth interval from the frozen projection
and shifts the camera origin while preserving the effective projection. The
isolated planning experiment changed coverage from zero to 8,024 samples; the
final installed extension completes all three scope pages in the actual project.

The two compositor Grades already had distinct Images and private kernels; the
global status made both display Baking. Each node now derives its searchable
selection from the existing embedded Image binding, with no second persisted
pointer. Selection accepts local packed float Perceptual Grade compositor bakes;
invalid or dirty destinations fail before capture. Status/errors are specific
to the initiating node; global single-bake admission remains. Native acceptance
verifies another destination's pixels, packed bytes and metadata remain unchanged,
as well as deliberate sharing, cancellation, rollback, Undo/Redo and save/reopen.

Final measurements use three fresh Blender processes per saved workspace. The
probe observes production GUI draws and published results without issuing extra
GUI scope requests. Each stage starts at overlay enable/page selection after
file loading and recovery. Median first matching draw times are:

| Operation | Shading | Compositing |
| --- | ---: | ---: |
| First Linear scope | 10.695 s | 3.332 s |
| Switch to Tone | 2.969 s | 1.606 s |
| Switch to Color | 3.223 s | 1.668 s |
| Grade exposure edit | 8.888 s | 1.325 s |
| Explicit warm refresh | 7.984 s | 1.835 s |
| Upstream Transform edit | — | 1.970 s |

Shading's first draw includes 57 foreground descriptions averaging about 99 ms
each: 5.59–5.66 s of repeated main-thread work, mostly graph/dependency and
resource/scene revision checks. Native rendering takes 4.87–5.15 s. Snapshot
admission takes about 0.34 s, including serialization of a 156.8 MB scene with
17 packed Images and hashing. Capture-helper readiness takes about 1.30 s;
after capture adoption, Linear-helper readiness adds about 1.11 s, analysis
dispatch-to-receipt about 0.62 s, and receipt-to-draw about 0.20 s. Foreground work
overlaps helper execution: these numbers are not additive or promised savings.

Compositing's descriptions total 0.48–0.64 s before the first draw, snapshot
admission takes 0.25–0.27 s, and native evaluation takes 0.27–0.28 s. Capture and
Linear helper readiness each cost about 0.64–0.71 s. The first process has a
0.89 s readback/sampling outlier versus 0.054 s in the other two; the trace
localizes it without establishing its internal cause. No external resources
needed separate copying in either workspace. Both paths also debounce, revalidate,
load/verify the snapshot, read pixels, analyze and publish before drawing.

Each full run creates/submits/adopts exactly three captures with no supersession,
rejection, failure or retry. Tone/Color reuse the initial capture. Compositor
Grade edits reuse input samples; Shading Grade edits eventually recapture the
settled scene-shading revision. The other captures are explicit refresh and,
for Compositing, the upstream Transform edit. All six GUI processes exit cleanly.
These Linux software-rendering measurements include diagnostics overhead and
warm OS/Mesa caches; "cold" means process/session cold. They do not establish
macOS/Metal or physical display latency. Earlier request-driven GUI probes are
excluded from final claims. Headless-current smoke remains separate evidence.

Root `//:verify` and `//:perceptual_grade` pass
(`12c59a03-3cbc-4e41-98a8-5ff83e688390`). Fifteen affected test targets pass 253
unittest cases: 41 capture, four camera, eight context, 28 bake, three diagnostic,
and 169 across scope/scheduler/lifecycle/recovery, packaging/architecture and
installed acceptance. The installed scope case covers 20 generated scenarios.
Final acceptance build is `09d2bab4-5b8a-4c84-8b8f-7e1d205887a2`; focused builds
are `0ab735c6-11a0-4135-b6ba-83d113fbcd44`,
`fcdc1a26-c796-41f6-a793-2fb50c54d770` and
`39c98b9d-0fd1-4dd8-9088-46980a0d1869`. Diagnostic regressions cover immutable
helper timing values and preservation of submitted snapshot leases when optional
metadata reads fail. Existing handwritten policies and Invariant sources remain
unchanged; the package remains proof-gated.

Final ZIP SHA256:
`374c1ea63323a7be8899f0f542834f05143507eaef941f63ae71e1ff640d11e9`.
The archive and test log are retained under
`buck-out/viewport-bake-validation-20261025/`. Detailed timing breakdown,
per-run values, identities, limitations and reproduction commands are in
`buck-out/train-model-scope-latency-evidence-20261025/report.md`; raw final runs
are under `buck-out/train-model-latency-{shading,compositing}-observer-20261025/`.

Permanent tests use generated scenes. `train-model.blend` remains an unchanged
manual input, never a Buck fixture or shipped artifact. Its before/after SHA256 is
`bcd29253c2f5291a4feecfbc81b251cc92ef8317977c3fe7e795e805a460e7cb`.
Planning evidence is under `buck-out/train-model-plan-inspect-20261025/` and
`buck-out/train-model-scope-cause-20261025/`. Product README/ARCHITECTURE document
the behavior and diagnostic CLI. CHECKLIST.md marks this work complete and keeps
the independent deferred work open.

---

# Completed goal: Flatten Blender source and archive layouts

Last updated: 2026-10-24

Grade implementation files now live directly in
`products/perceptual-grade-blender/src/`; `entrypoint.py` supplies the thin ZIP
root bootstrap. Both Blender ZIPs place intact component packages directly
beneath the extension root, without `_vendor`. Buck preserves the development
`color_tools.<component>` namespace. Runtime behavior, node IDs, persisted
schemas and strict module ownership are unchanged.

All 79 moved Grade implementation files remain byte-identical. Archive comparison
accounts for every member: the generated `_vendor/__init__.py` is removed, the
root entrypoints use direct component imports, and the helper bootstrap has one
comment correction with identical executable AST. Every other retained member
has identical bytes after path relocation. Grade now has 221 members; HDR has 75.
All 18 generic framework files still match upstream and UPSTREAM.json.

Root `//:verify` and both packages pass
(`5984e4d6-e02b-44c6-9613-a9c8051ab516`). Grade's 19 machine proof records and HDR's
eight retain identical source, requirements, validator, report, receipt and input
closure hashes. Package bindings use exact new paths and preserve the two-file
solver-free runtime-contract allowlist. New negative cases reject stale legacy
manifest paths and noncanonical binder paths; archive tests verify exact bytes
and deterministic repackaging.

All 19 test targets pass 125 unittest cases, with a further 33-case
lifecycle rerun after completing a synthetic Undo interval in its test fixture.
Coverage includes both products' package/architecture gates, helper namespace
isolation, strict foreign-module ownership, independent extension shutdown and
reload, HDR native and 12 viewport scenarios, Grade CPU/GPU helpers, analytic
baking, 14 native scope scenarios, save behavior and two GUI Undo/Redo cycles.
Shared-Image rebaking with both same and changed dimensions retains exact pixels
through native Undo/Redo; helpers retire cleanly.

An isolated old-ZIP process saved Grade/Stack analytic bakes and four standalone
consumers. A fresh new-ZIP process reopened the project with unchanged settings,
socket IDs, links, shared GradeData, packed Images and metadata. All six native
consumer renders matched exactly; rebaking through the new helper layout reused
the same shared Image. No recapture was needed on reopen.

Final Grade ZIP SHA256:
`2d89765036407f73ca232843b1b9acfcde21c152368b5beaa078089cb7efe58e`.
Final HDR ZIP SHA256:
`b1e6c60c4645ef0e4354c530f51e15ee0e5f703a347a44f2f1608fb2a0c44709`.
Build/test logs, exact input hashes, proof/source relocation audits, baseline and
final ZIP snapshots, and the reproducible save/reopen diagnostic are retained in
`buck-out/layout-flatten-validation-20261024/`; `summary.json` indexes the evidence.
Earlier GUI50 and latency measurements below remain bound to their original
artifacts, and the deferred platform/native-reader boundaries remain open.

Disable the old extension before replacing it across this layout change, then
restart Blender before enabling the new version. No legacy import aliases or
weakened ownership checks are introduced. CHECKLIST.md contains only remaining
independent and deferred work.

---

# Completed goal: Shared Invariant framework and actor-owned Blender runtime

Last updated: 2026-10-24

Adopt the shared `Machine`, `Store`, `ActorSystem`, and source-bound `.inv`/Z3
verification architecture from `~/workspace/invariant-framework`. Improve reusable
framework code upstream first, then sync identical generic sources into this
checkout with a content-hashed provenance manifest. Builds must not depend on
the sibling checkout. Upstream product implementations are not migration inputs.

This checkout's functionality is the compatibility baseline: analytic input-pixel
baking, shared packed Images and native Undo/Redo recovery, arbitrary compositor
scope capture, real-scene shader scopes, exact output, and physical retirement.
Preserve all existing twelve leaf policies, their domains and queries. Translate
the bake proof's 43 obligations, 16 witnesses and 10 replayed mutation controls
into `.inv`; add checked workflow coordinators adapted to these capabilities.

Common Blender host services move into a narrow `libraries/blender-runtime`
adapter consumed by Grade and HDR Color Picker. Each Session owns its own actor
system; shared framework Stores own state and transitions. Native work remains
on the Blender main thread. Rejected admission remains noncommitting; uncertain
admission must be reconciled before retry or rollback. Logical cancellation does
not release physical leases or clear repair debt.

Extend the shared verifier soundly for tagged identities, arbitrary finite tuples,
guarded exceptions and source-bound loop induction. Keep handwritten automata;
generated code supplies runtime contracts only. Proof and artifact gates bind
exact source, requirements, checker, solver and generated validator bytes. Ship
only solver-free runtime contract support, never the checker or Z3.

Image Workbench import is deferred. Its existing upstream tests remain useful
regressions for generic framework changes. CHECKLIST.md records unfinished work;
the completed deliveries below remain acceptance requirements.

The migration, final Linux native/artifact acceptance and requested latency
measurements are complete. CHECKLIST.md retains only deferred work and the
independent native/platform boundaries below.
Both Blender products use the shared actor-owned Stores and the narrow
`libraries/blender-runtime` adapter. The bespoke bake checker is removed. All
18 generic framework source/requirements/test/README files match upstream and
[UPSTREAM.json](../../libraries/invariant/UPSTREAM.json) byte for byte. The generic
verifier passes 50 tests; upstream Image Workbench retains its proof, 19
integration/TUI and nine Rust tests. Bake correspondence checks all six
entrypoints over 8,960 typed pairs (`ea6f85e7-068e-452d-a0c1-037d1c7e819d`).

Final `//:verify` and both ZIPs pass (`558877c2-4cc0-47e3-8d84-3eb56f923164`).
Grade binds 19 machines, 2,046 obligations, 170 named properties, 59 witnesses
and 40 replayed controls; HDR binds its eight-machine subset. The bake-image
requirements retain 43 named claims, 16 witnesses and ten replayed mutations.
Archive/architecture gates pass (`f14750ae-2b8a-45f0-909e-db162e7b53de`).
The final Grade archive SHA256 is
`c62f7a0c1540e9c006c0144be1b0f710069517d4338dd0c98fa0882ac489c0c8`;
HDR is `4136a7c6c3e1dcb50dd2a61651bbad7e0b8816f96270dfe58444992586247397`.

Native graph fingerprints, input dependencies, group-instance discovery and
referenced-scene walks now use explicit stacks. Deep fingerprint hashing also
avoids recursion while preserving the previous representation bytes. Temporary
native indexes and frames are released on both normal and exceptional exits;
GC-disabled regressions check their lifetime. The walkers index incoming links
once per tree and omit only unused extension settings and UI display aliases.
Saved controls, operations, native values, topology and resources remain checked.
Baked Color and Alpha dependencies follow their actual output, including native
muted bypasses and exact shared-group occurrences. Rebaking invalidates the
Image-based source without requiring an unused live grading model or LUT.

App, ownership, execution, scheduling, recovery, bake/output/LUT, HDR native and
viewport checks pass. Installed analytic baking, native scope capture, output
resources and save/reopen also pass. The full GUI stress test passed 50 cycles,
110 Undo/55 Redo pairs, 25 pending-worker/GC-deferred cases and clean teardown
(`f6ad0743-5efb-4e42-9a01-3c5df249770d`). Its tested artifact is preserved
separately: this run preceded the final iterative scope-adapter changes. The
final artifact passes 39 capture, 64 scope and eight context cases, installed
scope/bake/two-cycle GUI acceptance, and the native-reader regression. In total,
13 final targets pass 131 cases; a further 39-case rerun verifies clean fake-worker
retirement before App teardown. The installed native-reader regression uses a bounded
worker/main-thread handshake and verifies real render-job and light-bake
exclusion; it does not establish coverage of every Blender reader.

A fresh 650-file source-only checkout, without copied build outputs or a remote
action cache, completed a cold root verification/package build
(`20e755f4-8dc5-43e6-91e6-dcfab686b55d`). Lean compiled 30 project modules and checked 571 theorems, with only
`Classical.choice`, `Quot.sound` and `propext` in the transitive axiom audit.
The final adapter delta has been reconciled into that checkout; its rebuilt
ZIPs are byte-identical to the main checkout. The final source-only build and all
native acceptance targets pass. Results and exact input inventories are retained in
`buck-out/framework-validation-20261024/source-only/`.

The isolated measurement of the final Grade ZIP used the same generated
material/Grade scene, Blender 5.2.2, OpenGL llvmpipe and Intel Xeon 6530. Setup
completion to first scope draw took 25.40 seconds. Three real grading edits took
1.73–1.78 seconds from mouse event to current preview draw, or 1.50–1.54 seconds
from the actual control commit. Release to settled full scope took 13.92–14.73
seconds; final LUT readiness took 1.11–1.25 seconds. Analytic visual computation
itself took 24–37 ms. These measurements validate current parameters, accepted
publication/request keys and actual raster-draw calls, not physical scanout.
The ZIP hash was checked before launch, and all three helpers retired cleanly.

The one-second end-to-end expectation is not met. The final iterative version's
edit feedback is slower than the pre-iterative 1.37–1.47-second baseline. Average
capture-description time rose from about 63 to 89 ms, while graph-walk time was
roughly unchanged; the additional foreground cost has not been isolated further.
Native source submission-to-adoption still took about 10–19 seconds, including
queueing, startup, scene load, rendering, return and polling. These observations
must not be confused with the individual fingerprint-call maximum of about
127 ms. Final reproduction inputs and results are retained in
`buck-out/framework-validation-20261024/scope-latency-isolated-20261024T105453Z/`;
version-bound native reports, proof bundles and package hashes are in
`buck-out/framework-validation-20261024/evidence/`.

macOS/Metal and physical HDR/manual-painting acceptance remain platform-specific.
The USD/Alembic export-startup reader exclusion gap requires a native capability
that the current exposed job/lock observations do not provide. Keep
`coverage_complete=false`; passing protocol proofs or known-reader tests cannot
establish that missing native premise. Image Workbench import remains deferred.

---

# Completed goal: Source-bound Z3 verification of bake-image recovery

Last updated: 2026-10-24

The bake-image policy's manual exhaustive safety checker has been replaced by
Z3 proofs derived from its actual Python source. Runtime behavior and native
integration coverage are preserved. Root `//:verify` and Grade extension packaging
require the proof, bound to the exact shipped policy and checker inputs; all
solver/proof dependencies remain outside the runtime ZIP. Only `bake_image` has
migrated; other policies and native adapter protocols retain their current checks.

The checker establishes 43 named obligations, 16 positive witnesses and 10
source-mutated counterexamples replayed through ordinary Python. Nine translator
tests compare all six entrypoints with Python, including all 8,960 typed
state/event combinations. Semantic strings are restricted to ASCII identifiers
to exclude Z3/Python differences in escaped Unicode labels. Final focused Buck
validation passes all five targets / 38 cases, including this regression
(build `cfbb9807-39f7-4ef6-a5ce-133bead2ed95`).

Six native/archive/architecture targets pass all 33 cases (build
`a26f9b06-5374-498a-a009-8ded8561f64c`), including all 20 native bake tests and
installed Blender 5.2.2 analytic bake/Undo/Redo/failure-retry acceptance. The
proof-gated ZIP has the same 184 entries and SHA256 as the previously accepted
runtime artifact: `8deae7dfa778aed7647bf7734902a8be64e15b5452862ec03e3c228e3e54c7a7`.
Its external package report records the accepted proof, policy and closure hashes.

The final root `//:verify` and `//:perceptual_grade` builds pass (build
`2a990e33-1453-4f07-9bc1-2c47ee23176e`). The fresh retained Lean run compiled all
30 modules and checked 571 theorems, with only `Classical.choice`, `Quot.sound`
and `propext` in the transitive axiom audit. Its cold-build ID is
`3bc001e9-6124-4f26-80c0-610e61367922`. This completes the previously outstanding
fresh Lean validation gate.

The accepted proof boundary is the restricted Python AST interpreter plus pinned
Z3, conditional on truthful native observations. CHECKLIST.md tracks the remaining
independent acceptance work. All 11 selected targets / 71 test cases pass.
Evidence in `buck-out/bake-z3-validation-20261024/` includes both proof reports,
112 SMT queries, ten replayed counterexamples, the package report and unchanged
ZIP, installed native report, source hashes, summary and build/test logs.

---

# Completed goal: Analytic compositor image baking

Last updated: 2026-10-24

## Accepted bake contract

Bake captures full-resolution pixels entering the selected Compositor Grade or
Grade Stack at the current frame and native input domain. It evaluates the
selected grading model directly with the production kernels used to calculate
33³/65³ LUT samples, without LUT interpolation for that selected node. Frozen
Stage 1 and color-space endpoint matrices are applied exactly once; alpha is
preserved. Upstream graph operations still use Blender's native evaluation.

Each Grade/Stack keeps its live Color output and gains Baked Color, backed by a
packed float RGBA Image. Existing Color connections stay unchanged. The first
bake creates an Image; rebaking overwrites the same Image, so standalone Bake
nodes and other consumers sharing it update together. Baked Color is transparent
black before a successful bake, then remains a static snapshot until rebaked.
The standalone Perceptual Grade Bake node can select the same Image.

The completed publication, pixels, metadata, and node binding form one undo
action. Redo restores the packed result without another capture or evaluation.
Native publication remains guarded; cancellation or failure must preserve the
previous shared Image. Snapshot files remain leased until physical retirement.

The result is a finite current-frame raster: downstream spatial operations may
differ when the original graph used off-canvas values. Shader and arbitrary-node
baking, automatic rewiring, and graph-preserving raster replacement are deferred.
`train-model.blend` remains a temporary manual input, never a regression fixture,
Buck resource, or shipped artifact. Acceptance scenes are generated.

## Current status

The analytic evaluator, full-resolution native input capture, Baked Color
outputs, shared-Image rebaking, and retirement cleanup are implemented.
Production-kernel raster tests pass all six cases; capture identity and lease
coverage passes 28 cases. The selected node no longer depends on a completed
LUT, and upstream preparation follows the connected input dependencies.

Installed Blender acceptance passes analytic Grade/Stack and rebake pixels with
zero maximum error against direct production-kernel evaluation. Off-grid inputs
show measurable differences from the live LUT output. Source Baked Color and two
standalone nodes share one Image across same-size and changed-size rebakes;
native Undo/Redo restores packed pixels, dimensions, metadata and bindings
without recomputation. Persistence, cancellation, pending load and active disable
also pass (Buck bcd23dd4-b924-4abf-8d4b-d057178f67fd).

Native testing exposed Blender reusing the newer compositor image buffer after
restoring older packed bytes during undo. Recovery now invalidates buffers when
the packed revision changes, while preserving externally edited buffers during
unrelated undo. All 20 focused bake tests pass, including a failed rollback
crossing an actual Blender load, superseded readback receipts, repeated native
pre-handlers, failed verification retry, and preservation of edits made after an
invalidation. The revision recovery protocol now uses an explicit finite
automaton. Nine policy tests check its initializer and all 1,320 admitted
state/event pairs, establishing inductive safety for arbitrary transition
sequences. The check includes independent relational properties and an unsafe
reset negative control. Its claims are conditional on the adapter's revision
observations and verified readback; Blender buffer semantics remain native-test
evidence. Final frozen-source regression and artifact checks pass. Evidence is
retained under `buck-out/analytic-bake-validation-20261024/`.

## Final validation

- All 25 Buck test targets pass, comprising 400 unittest cases. The main run
  covers analytic raster (6), image policy (9), native bake (20), capture (28),
  context (7), lifecycle (31), ownership (11), output packing (16), runtime (18),
  scheduler (25), scopes (63), framework execution/physical ownership and package
  integrity. Build: `17c5d9ba-f1f6-4d19-a901-0f009eaa07f2`.
- Existing output, Stack, recovery and recovery-retry compatibility tests also
  pass, including repeated LUT publication and rollback. Build:
  `bfa5da15-7aab-4203-9ed9-7f4b0e3853a2`.
- Installed analytic bake acceptance passes on pinned Linux Blender 5.2.2.
  Grade/Stack and both rebake sizes have zero maximum error. Real rendered-image
  Undo failure retains recovery debt; retry restores the old image without
  recapture, and Redo restores the new image. Unrelated dirty pixels survive
  failure, retry and Redo. Build: `bcd23dd4-b924-4abf-8d4b-d057178f67fd`.
- Installed native scope capture passes all 14 compositor/shader scenarios.
  Build: `7991de80-cc92-43e9-927d-c8dc2046cd8a`.
- The root extension artifact, source tree and package inventory build and match
  the retained ZIP. Its 184 entries contain the declared sources and catalogs,
  with no `.blend` fixtures. SHA256:
  `8deae7dfa778aed7647bf7734902a8be64e15b5452862ec03e3c228e3e54c7a7`.
  Build: `c84b0be7-4ec4-4fd4-b26c-ee11ed83553e`.
- Retained evidence includes `summary.json`, `source-hashes.json`,
  `package-report.json`, `perceptual_grade.zip`, both installed reports and the
  corresponding build/test logs. Independent platform and native-reader
  validation boundaries remain in CHECKLIST.md. The later Z3 migration above
  supersedes the manual automaton check and completes fresh Lean validation;
  neither check revives or relies on historical machine-proof receipts.

---

# Completed goal: General native scope capture

Last updated: 2026-10-24

## Completed implementation

Perceptual Grade now uses native Blender evaluation for scene-backed upstream
sampling. It captures the Color input to a Grade in its real scene/view context,
then retains the host-free numerical scope analysis and Grade stages.

The chosen behavior is:

- Shader scopes follow the last active 3D view in the same window, with the
  active scene camera as fallback. Use the scene's render engine, lighting,
  frame and view layer. Include all visible users of the selected material and
  visible World output; Light trees have no camera-pixel sampling domain.
- Compositor scopes capture the selected Grade's upstream input at actual
  compositor resolution/domain. The result represents the Grade stages, not
  the final downstream composite.
- Automatically debounce/coalesce relevant source edits, render an isolated
  snapshot as needed, retain the last coherent scope during refresh, and never
  substitute another renderer or synthesize missing values.
- Native Blender work stays in the product adapter/helper. Only immutable
  captured arrays and value identities cross to the existing analysis worker.

## Diagnosis and feasibility

`train-model.blend` is a temporary manual probe input, not a regression fixture
or product artifact. Persistent acceptance cases create generated Blender scenes
in their test runners.

`train-model.blend` connects `Image -> Transform -> Grade -> Alpha Over`.
Blender 5.2.2 runtime checks confirmed that the former full and linear source
descriptions rejected `CompositorNodeTransform` before creating a job; the UI then
reported the absent job state as `preparing`. Its image is packed. The direct
Transform bypass was an in-memory diagnostic only and was never saved.

Pinned Blender 5.2.2 probes verified signed HDR Color AOV output in Eevee and
Cycles, plus a separate coverage AOV; compositor-only evaluation also produced
the expected native transformed pixels without rendering scene geometry when
the graph had no scene-render inputs. A private camera can reproduce perspective
and orthographic viewport matrices. Minimal Grade/Stack node registration can
load and evaluate an isolated `.blend` snapshot without starting the extension
lifecycle. Installed product regressions now cover the implemented capture path.

## Implementation status

Implementation and Linux native integration are complete. Product documents
describe the capture contract and its tested boundaries. The final installed
suite passes all 14 scenarios, including external-scene, alternate-view-layer
and reference-input cases; the foreground capture target passes all 12
lifecycle/revision cases.

## Validation results

- The repeatable Buck `project_probe --mode scopes` run on `train-model.blend`
  completed Linear, Tone and Color scopes through the existing Transform at
  frame 25. The actual 2126 x 1418 input domain was sampled at 256 x 171; all
  states reached `current`. Grade exposure reused the capture. A Transform
  position edit retained the previous display as `updating`, then published
  changed samples as `current`. Live links and the saved file were unchanged;
  snapshot leases were released and disable completed.
- The blend SHA256 remained
  `60f7a6f5b3c98e34081e11154488d7c32ba722f9fce115d165ac11726a39285f`.
  Latest evidence: `buck-out/train-native-verified-20261024/report.json`,
  `launch.json`, `source_hashes.json` and `native.log`.
- The frozen-source combined run passes lifecycle (30 cases), ownership (11),
  runtime (18), packaging architecture (3), component boundaries (5), archive
  verification (2), native context (7), scheduler (25) and scopes (63). The final
  native capture lifecycle/revision target passes all 12 cases, including a
  silent volatile-image edit during the probe interval. Evidence:
  `buck-out/native-scope-validation-20261024/regressions.log`, `capture.log`
  and `summary.json`.
- The installed native capture suite now passes Transform, Mix, Blur, exact
  nested-group occurrence, alpha, byte sRGB conversion, and input domains that
  differ from the scene canvas. A private File Output tap preserves the actual
  input domain; all user File Output nodes are removed in the helper snapshot.
- Installed Eevee/Cycles checks pass for signed HDR material and World values,
  two visible material users, coverage masks, unchanged live graph/settings,
  snapshot release, and native helper shutdown.
- The installed target passes 14 native scenarios: nine compositor cases,
  Material/World in both engines, and an explicit no-visible-material error.
  These include alternate-view-layer and external-scene Render Layers plus an
  explicit reference input with a different aspect ratio. External-scene Render
  Layers follows Blender's owning-compositor canvas; ordinary Image inputs keep
  their native domain. Explicit reference captures match the primary analysis
  grid. Evidence: `buck-out/native-scope-validation-20261024/installed.log`
  and `installed-report.json`.
- The final extension ZIP, root `perceptual_grade` artifact, project-probe tool
  and pinned native Blender target build successfully. Evidence:
  `buck-out/native-scope-validation-20261024/artifacts.log`.
- A cold `buck2 build //:perceptual_grade //:verify` was stopped after about five
  minutes of Mathlib compilation to unblock product regressions. It reported no
  proof failure, but did not produce a fresh theorem verification result.
- macOS/Metal and the carried-over validation boundaries remain separate
  acceptance work. Changes after validation require revalidation.

## Acceptance

- `train-model.blend` samples through its Transform and finishes scope analysis.
- Eevee/Cycles material AOVs retain signed HDR input and use coverage correctly;
  World captures background pixels; multiple visible users are included.
- Compositor Transform, Mix, Blur, nested groups, alpha, actual pixel domains,
  and reference inputs are captured before the selected Grade is applied once.
- View/projection, frame, engine, scene, graph, images and source revisions fence
  cache reuse; stale captures cannot publish.
- Undo/load/disable/cancellation retain snapshot files until physical helper
  retirement and leave the saved project/live node graphs unchanged.
- Buck scope/runtime/ownership and installed native tests pass; the extension
  archive matches declared sources. macOS/Metal remains a separate acceptance
  gate.
