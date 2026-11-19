# Testing and measurements

> **Version scope:** the current Next validation section below describes the current implementation. The remaining sections retain historical runtime layouts and versioned measurements. For current development commands and supported behavior, also use the product READMEs in [chromaticity](https://github.com/rei277hz/chromaticity).

Choose validation around the behavior you changed. Numerical tests isolate equations and invariants; DCTL parity tests compare the analytic reference; native-render tests check the graph actually evaluated by Blender. Packaging and documentation tests cover the artifacts readers and users receive. The [build chapter](building.md#run-tests) lists the targets.

A failing reproduction should identify the host version, input interpretation, grade, render method and device. Run the focused gate first, then the related integration gates. Report measured results with their workload and settings, so another contributor can reproduce them.

## Main CI follow-up after Stage 3

[GitHub run `44146241261`](https://github.com/rei277hz/chromaticity/actions/runs/44146241261)
tested merged commit `5a2cf26636c1`. Lint and both selected build targets
passed, while the test inventory reported 62/66 passing targets. The four
remaining targets represent three failing test processes and one dependency
build failure:

| Target | Observed failure | Repair boundary |
|---|---|---|
| `color_stages`, `persistent_color_stages` | The shared isolated appearance fixture omitted `J_A`, producing 174 repeated `AttributeError` reports before numerical comparison. | Derive the fixture's `J_A` from its carried float32 signed energy. |
| `installed` | An unbound shared node retained `web_hue_1_0 = 15` after its settings callback should have restored neutral controls. | Reset explicit backing keys for custom hue and Adaptance properties. |
| `handbook_audit` | Diagram Chromium aborted with `Socket path too long`; the audit process never started. | Give the browser a private short temporary directory. |

The isolated Color handoff carries unscaled `E` in alpha. Its achromatic
coordinate is `sign(E) * sqrt(abs(E))`, matching the independent reference
state. Recovering it from rounded H and chroma would discard energy that the
fixture intentionally carries separately. Both generic and persistent suites
use this handoff; their unguarded Terms → Web → Adaptance → Scale comparisons
retain their original precision, finiteness, saturation, and signed-energy
checks. Production H–K-before-Scale evaluation is a separate gate.

The installed failure also identifies a user-visible Reset defect. In pinned
Blender 5.3, registering custom float getters/setters clears `PROP_IDPROPERTY`
([`rna_define.cc`](https://github.com/blender/blender/blob/02f0899d78e3/source/blender/makesrna/intern/rna_define.cc#L3362)).
For those properties, `is_property_set()` does not describe the manually
stored key, and `property_unset()` does not remove it
([`rna_access.cc`](https://github.com/blender/blender/blob/02f0899d78e3/source/blender/makesrna/intern/rna_access.cc#L7149)).
The storage adapter therefore checks key presence and explicitly removes the
24 hue and eight Adaptance axis backing values. Other Color properties retain
native RNA reset behavior. Authoring rollback uses the same presence contract
so a failed edit restores both values and the distinction between an absent
key and an explicitly stored default. Installed regressions cover unbound
neutrality, complete and family resets, unrelated settings and claims, and
rollback after a failure following value writes.

The browser failure depended on the execution path: GitHub's inherited
`/workspace/buck-out/ci/tmp/.../book_generate/assets` directory plus Chromium's
generated `SingletonSocket` exceeded the Linux Unix-socket path limit. Earlier
remote workers used shorter temporary roots. The browser adapter supplies a
private `/tmp/pg-d2-*` directory through the child environment while preserving
pinned fonts and libraries. `packaging/test_handbook_browser.py` exercises real
Chromium font/geometry checks with a deliberately long inherited path and
checks private-directory isolation and cleanup, including launch failure.
It runs within the existing Next `handbook_audit` target.

The broader repair run exposed another installed-fixture ordering defect.
`conversion_checks.py:_adaptance_limits` changes settings that schedule
asynchronous kernel preparation, then asks its supplied callback to assert
current output. The standalone `conversion_runner.py` callback drains that
preparation first; the full installed runner's callback only asserts readiness.
The shared check now explicitly drains and checks preparation failures before
asserting readiness, so both callers test the same completed publication.

That parallel run also timed out the live compositor-carrier process after
four of its 18 rows, all in the GPU/AUTO workload. The incomplete report does
not establish a shutdown defect or prove worker contention as the cause.
The harness now caps Blender at two threads and llvmpipe's separate pool with
`LP_NUM_THREADS=2`, while retaining the existing one-thread OpenMP and BLAS
limits. All 18 tasks, the 40-second task threshold, the 240-second process
threshold, numerical acceptance, and normal process-exit requirement remain.
A timeout includes the saved partial report for diagnosis. The revised probe
passed all 18 rows in 116.475 seconds with normal exit. This establishes
acceptance of the bounded-thread fixture, not a controlled measurement of the
earlier timeout's cause.

The 62/66 result is the pre-repair GitHub record. Repair validation on
2026-11-18 used Buck2 `--remote-only` and the unchanged explicit 66-target Next
selection. The first broad pass (`75d35ef8`) passed 64/66 and exposed the two
additional fixture issues above. After their repair, build
`c405df87-03b7-4b4b-9b76-8820b4c26e5f` passed all 66 distinct test targets,
reusing unchanged passing results and executing the affected targets remotely.
It recorded seven remote commands and zero local commands. This is remote
workspace acceptance; a subsequent GitHub run is a separate receipt.

| Acceptance scope | Receipt | Result |
|---|---|---|
| Isolated Color, generic and persistent | `5becb784` | Nine methods each, 252.426 / 1099.117 seconds; 54 remote commands, zero local. |
| Complete installed suite, Blender 5.3 / 5.2.4 | `c7beb653` (shared execution with `c405df87`) | 153.036 / 148.730 seconds, including all new custom-storage checks. |
| Current/LTS animation and GUI undo | `f8629308` | Four lifecycle targets passed; animation bodies 82.534 / 78.107 seconds, undo 16.997 / 17.061 seconds. This earlier command's installed targets failed before the conversion-fixture repair. |
| Policy proofs and extension build | `54a93cce` | Both selected builds passed; 27 remote commands, zero local. |
| Technical Report and handbook artifacts | `c405df87` | 15 report checks and five handbook checks, including real Chromium geometry under long inherited temporary paths. |
| Changed Next BUCK formatting | `7cec7ad1` | Pinned buildifier 10.2.0 passed remotely; the temporary validation target was removed. |

No numerical tolerance, timeout, normal-exit requirement, or selected target
was removed or relaxed by these repairs.

## Current Next Color authoring validation

Color authoring has separate ownership, numerical, and native host contracts.
The synchronous `color_authoring` policy admits scalar capture/clear effects;
the runtime composes reversible six-handle edits; `color_resolution` supplies
evaluation-only hue projection and radial Adaptance limits. Their focused gates
are:

```sh
buck2 build --remote-only \
  //products/perceptual-grade-next-blender:proof_color_authoring
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:color_authoring \
  //products/perceptual-grade-next-blender/tests:color_resolution
```

The scalar proof checks owner identity, same-owner baseline retention, takeover,
manual detachment, blocked return, and exact-owner baseline release. Its
reachability witness and three mutations exercise those decisions. It does not
prove float equality, the geometric solver, or Blender rollback. Runtime tests
cover both edit directions and the cyclic seam, transitive pushes, simultaneous
constrained restoration, blocked claims, takeover, idempotence, and real
Peak-dependent geometry. Numerical tests use independent normal-cone
certificates for closest-angle projection and check the radial response domain,
float32 storage, nonfinite rejection, and unchanged authored animation samples.
The public hue gap is 4°; invalid-row repair reserves 4.0001° before storage
and checks the resulting float32 gaps against 4°.

The follow-up scalar proof passed in remote build `18f94c3f` with one remote
command and zero local commands. Final runtime/package build
`de327672-c1bb-4b60-8eef-e19f7f8a728f` passed all nine resolution checks
(0.219 s), 14 authoring checks (0.405 s), three package checks (0.314 s),
125 preparation-runtime checks (2.067 s), the bake-route gate, and one native
undo method (11.514 s), using 25 remote commands and zero local commands.
The authoring cases include all six edited handles, the supported Peak values,
hard offset bounds, and float32 restoration near the minimum gap. These timings
measure correctness workloads rather than interactive response.

Installed animation and conversion fixtures cover the remaining Blender
adapters: typed fractional precision and soft ranges, node-owned versus shared
claims, same-time versus actual frame/subframe changes, copy/reset/conversion,
saved metadata, undo, and effective sampled settings without keyframe writes.
The independent native undo fixture
`installed/gesture_undo_runner.py` also detaches a hue claim by editing its
unchanged numeric value. It requires an undo state that restores only the
provenance while leaving the mathematical signature and effective hues unchanged,
then another undo that restores the original transform and empty claims.

Final current-Blender build `be62f7db` passed one conversion method in about
31 s and two animation methods in about 64.4 s, including extreme Adaptance
and the 0.01 drag-increment contract. LTS build `5bb89482` passed conversion
in about 31 s and both animation methods in about 60.9 s. LTS native undo
passed in two consecutive isolated runs, `26f53c9b` (11.523 s) and
`3622ae9a` (11.099 s), with normal native process exit. Three preceding LTS
runs crashed in native code during the existing exposure-undo case, before
the hue assertions; the passing reruns followed no production fix. Those
historical retries do not close the defect; the subsequent diagnosis and
authorized lifetime repair are recorded below. The fixture retains
faulthandler and native crash-report output and continues to require successful
Blender exit. These results are separate from the initial Stage 3 timings below.

The first follow-up documentation build `d1fff95f-6075-457e-86d7-e2d88c2343bc`
passed all 15 report traceability checks (0.244 s) and all three handbook
artifact checks (9.098 s), including the new sequence's label geometry, site,
deployment ZIP, bilingual manuals, and report exports. Its fresh isolation
rebuilt dependencies with 872 remote commands and zero local commands. The
legacy ZIP remains and animated images are excluded from published artifacts.

## LTS undo fallback-lifetime repair

The later reproduction builds `d215a97d`, `0c52be78`, and `69116c83` reproduce
the native crash during the second exposure undo, before the new hue
assertions. Isolated build `7056eb87` passes the same pre-repair workload.
That intermittent success is not repair evidence.

The crash stack repeatedly enters the address near `0x96b5cc`, resolved against
the pinned Blender 5.2.4 binary to
`NodeTreeMainUpdater::make_node_previews_dirty`. This establishes recursive
node-tree traversal and stack exhaustion. Source review at Blender commit
[`cd5dc428cce1`](https://github.com/blender/blender/tree/cd5dc428cce1) finds
raw ID addresses in [`writefile.cc` lines 835–840](https://github.com/blender/blender/blob/cd5dc428cce1/source/blender/blenloader/intern/writefile.cc#L835-L840),
undo restoration in [`readfile.cc` around
read_libblock_undo_restore_at_old_address`](https://github.com/blender/blender/blob/cd5dc428cce1/source/blender/blenloader/intern/readfile.cc#L3367-L3390),
later library linking in [`readfile.cc` lines 4620 onward](https://github.com/blender/blender/blob/cd5dc428cce1/source/blender/blenloader/intern/readfile.cc#L4620),
full-ID swapping in [`lib_id.cc` lines 979–993](https://github.com/blender/blender/blob/cd5dc428cce1/source/blender/blenkernel/intern/lib_id.cc#L979-L993),
and recursive preview traversal in [`node_tree_update.cc` lines
923–934](https://github.com/blender/blender/blob/cd5dc428cce1/source/blender/blenkernel/intern/node_tree_update.cc#L923-L934).
A freed historical fallback's address could be reused by a temporary parent ID,
then cause a restored child pointer to map to that parent itself. This is the
source-supported mechanism being removed; the specific allocation-address
collision has not been captured directly.
The diagnosis must not be presented as a captured collision or a new hue
authoring failure.

The accepted fix is the
[six-variant persistent fallback pool](next-policies.md#persistent-fallback-lifetime-and-undo).
The existing resource policy authorizes retention through its `retain` effect;
the consumer applies fake-user protection. Current `ID.users` is not an undo
lifetime proof. The pool validates against the exact shipped manifest receipt
on every acquisition, scans current datablocks without retaining RNA wrappers,
and preserves published, legacy, and invalid historical fallback IDs while
leaving invalid ones unused. Failed unpublished candidates remain reclaimable.

The self-contained native fixture checks repeated reconciliation without new
fallback allocation, shared readers and removal, stable pending→live→pending
identity, save/load retention, and acyclic nested groups after undo and load.
Template and resource-policy tests additionally cover every mode/host/interface
variant, corrupted topology and receipt rejection, retained historical groups,
and failure cleanup. It uses no user-provided `.blend` fixture. The eight
resource-policy checks passed in remote build `57b31729` with five remote
commands and zero local commands. A separate explicit Buck2 build of
`proof_resources[report]`, `76919d83-f191-48a1-9b1a-cf7276cc6c97`, passed
with seven remote commands and zero local. The report records `ok=true`,
all ten required properties including both undo-retention properties, two
witnesses, and two mutations. A `buck2 test` invocation does not build a proof
target's `DefaultInfo`; its test result must not substitute for this proof-build
receipt. Additional repair receipts are:

| Scope | Remote build | Passing checks and body duration | Commands, remote/local |
| --- | --- | --- | --- |
| Preparation runtime | `6816f1ad` | 126 checks, 2.157 s | 53 / 0 |
| Node templates | `cb0091e5` | 15 methods, 39.627 s | 49 / 0 |
| GUI undo and drag | `c97eb4e1` | Current undo 12.271 s; LTS undo 12.822 s; LTS drag 16.567 s | 63 / 0 |
| Package, architecture, LTS animation | `9a6f09dd` | Three + two + two methods; animation 60.715 s | 11 / 0 |
| Native pool matrices and LTS templates | `f126a588` | Pool: six current and six LTS methods, 1.758/1.733 s; LTS templates: 15 methods, 40.731 s | 87 / 0 |

Three concurrent LTS undo runs—`b8ae8c9d`, `16f3fe6b`, and `d91cbf63`—also
passed in 15.060, 15.029, and 15.009 s. Distinct test environment labels
required three actual remote executions. These runs retain normal Blender
process exit and the pool identity, sharing, lifecycle, save/load, and acyclic
graph assertions; they do not simply accept a report from a crashed process.

`native/test_fallback_pool.py` supplies the additional six-variant matrix:
preferred/scanned reuse without ID growth, policy-authorized retention,
invalid-mode and topology replacement while preserving old IDs, legacy-marker
retention, rejection of linked fallbacks in favor of local instances, and full
cleanup after failed unpublished validation. The Next targets `:fallback_pool`
and `:fallback_pool_lts` are in the explicit CI inventory and both pass in
`f126a588`. Their LTS host took 4.323 s for the 1.733 s pool body; the native
LTS template host took 43.368 s for its 40.731 s body. Final documentation
artifact acceptance is recorded separately below. Normal process exit remains
required; do not replace these contracts with a retry-only gate.

The final legacy-marker edge checks marker presence rather than truthiness:
historical groups remain retained when their marker value is `0` or `False`.
Build `f62b7ffd-cda9-47d5-90b3-ab5838e81307` passed the expanded current/LTS
six-variant matrices (six methods each, 1.635/1.702 s bodies; LTS host 4.333 s)
and all 15 report checks (0.229 s), with seven remote commands and zero local.
Final LTS undo build `f8a97062-b32d-4cdb-a781-0f4ec0589b66` passed in
12.315 s with three remote commands and zero local.

Documentation build `2900ea1c-c400-41b6-a9bf-80a8de4bb9d5` passed all
15 report checks (0.235 s) and all three handbook artifact checks (7.289 s).
It validates updated D2 geometry, site and deployment ZIP, bilingual manual
PDF/EPUB, and report PDF/EPUB, using 872 remote commands and zero local.

## Current Next native parameter validation

The fixed Grade graph uses complete Linear, Tone, and Stage 3 parameter bundles.
Five native targets check its evaluation and update behavior:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:stage2 \
  //products/perceptual-grade-next-blender/tests:stage2_shader \
  //products/perceptual-grade-next-blender/tests:stage2_compositor \
  //products/perceptual-grade-next-blender/tests:stage2_extreme \
  //products/perceptual-grade-next-blender/tests:stage2_updates
```

The retained `stage2` target name runs two interface/allocation methods.
`stage2_shader` and `stage2_compositor` each run the basic guarded-parity
method for their own context, retaining both Linear Rec.709 and ACEScg cases,
signed/HDR inputs, alpha, and independent-reference checks. `stage2_extreme`
runs the remaining extreme Tone method. Stage 3 is included in all of them;
their names do not limit evaluation to Stage 2.

These four static targets use `native/test_stage2.py`. `PG_STAGE2_SECTION`
accepts only `interface`, `shader`, `compositor`, or `extreme`. The module's
`load_tests` checks the exact union of current Stage 3 method names; the guarded method
is intentionally shared by its two context sections. The default section is
`interface`, so a default module load alone runs only its two methods. CI
enumerates all four static Buck targets explicitly.

The basic guarded case requires the fixed tree's maximum normalized RGB error
against the independent oracle to be at most `1e-4`, and its parity with the
generic graph to be at most `3e-6` (3 ppm). The extended extreme case combines
the two Tone extremes with active Color, Adaptance, and non-unit Scale. It
independently gates three outputs—the generic graph, a protected generic graph,
and the fixed parameter graph—against the oracle at `1e-4`. Its `5e-6` (5 ppm)
binding-parity gate compares the fixed tree with the protected generic baseline,
which uses the same protected arithmetic and scaled energy carrier while
retaining separate parameter and field reads. Exact validity, saturation,
alpha, and embedded-alpha comparisons remain.

An earlier extreme candidate passed the independent RGB gate (about `2.33e-5`)
but differed from the specialized generic graph by about `2.2e-5`. Those two
graphs used different arithmetic and energy carriers, so that comparison did
not isolate parameter binding. The equivalent-arithmetic baseline preserves
the current extreme test's 5 ppm binding gate and adds its own independent
oracle gate. That revision passed in remote build
`82e081c4-17e1-4921-a756-8daa18cfbd14`: the extreme action took 390.0 s
(386.689 s test body), and the basic Compositor action took 303.4 s
(300.043 s test body). The batch ran four remote commands and zero local
commands. These results precede the later GPU Auto boundary-retry and fused
scene-decode candidate; they do not certify that candidate's live precision.
This extended active-Color test replaces the older achromatic-only diagnostic, whose parity limit
was 3 ppm. The current basic guarded test retains its separate 3 ppm limit.

The accepted production-Compositor candidate also passed the two affected
static targets in build `931037c4-2077-4e08-9fd9-e864f7e3412d`: basic
Compositor took 281.0 s per action and the extended extreme case took 423.3 s
(420.004 s test body), retaining the same independent and binding-parity gates.
The batch ran four remote commands and zero local commands.

`stage2_updates` repeatedly publishes complete parameter bundles, including
active Stage 3 settings, while checking native output against the independent
oracle. It verifies that group and Image identities, links, socket defaults,
bank bindings, and the active selector remain fixed. A save/reload case checks
packed role payloads and identical rendered output after restoration.

The targets run in separate test processes because even an earlier three-method
basic section reached the 600-second per-process limit; repeated publication
and save/reload renders already have their own process. Splitting the current
Stage 3 suite preserves its methods, subcases, corpus, and acceptance limits;
that claim does not equate the extended Color test with its older achromatic
predecessor. Individual test
durations remain correctness workload measurements, not Blender interaction
latency claims.

Complete Grade acceptance is also divided by host evaluation context:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:full \
  //products/perceptual-grade-next-blender/tests:full_compositor
```

Both targets use `native/test_full.py`. `full` selects Shader evaluation and
`full_compositor` selects Compositor evaluation through the validated
`PG_FULL_CONTEXT` setting. Together they retain the complete corpus across
working spaces, extreme controls, field-row isolation, alpha and diagnostic
checks, construction cleanup, and packed save/reload without add-on
registration. The split bounds each process separately by the same 600-second
limit; the acceptance thresholds and selected cases remain unchanged. These
cases exercise the source-emitted native graph.

The shipped fixed Grade templates have separate numerical gates:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:color_templates \
  //products/perceptual-grade-next-blender/tests:color_templates_compositor
```

They instantiate the bundled `.blend` Grade, bind complete runtime parameter
images, and evaluate six active/extreme configurations in all three working
spaces. Both use the unchanged `1e-4` normalized RGB gate, require finite
output, preserve alpha exactly, and keep black exactly black. The Compositor
gate also checks embedded alpha. This covers the fixed production topology
independently of source-emitted graph acceptance.

On 2026-11-17, remote batch `516be663-3d88-41c7-9cfd-9230ce1021b8`
passed 35 preparation checks, five full-Grade test methods per context, and
all 18 production-template configurations per context. The Compositor template
gate additionally checked nonfinite routing. The source-emitted Shader and
Compositor test bodies took about 407 s and 417 s; these are correctness-workload
durations, not interactive latency. Subsequent unused-branch hardening passed
the shipped-template gates and exact template receipt checks in both bpy and
native Blender. Before the later identity-carrier repair, hardened source-emitted
acceptance also passed in remote build `dfa03f20-5e0d-4ccc-8c64-d833b9ebf06d`:
five Shader methods in 381.625 s
and five Compositor methods in 384.276 s, with two remote commands and zero
local commands. The semantic-carrier static run subsequently passed the
interface, Shader, Compositor, and publication/save-load sections; the revised
extreme gate passed in the separate equivalent-arithmetic build recorded above.
Final source-emitted full-Grade acceptance passed in build
`d1006e84-e3fb-4683-aa36-d9ededfe5d21`: five Shader methods in 423.640 s and
five Compositor methods in 422.974 s. All five Stack GPU checks also passed in
190.122 s. The later optional production-Compositor projection refinements do
not affect these default full-Grade and Stack paths. Final shipped-template
numerical and receipt checks have separate results below; none of these timings is
an interaction-latency claim.

The installed save/recovery fixture `:image_save_gui` passed in remote build
`d06c154f-a5f9-4957-94cf-d60ec941beea`: one test body in 33.338 s, one remote
command, zero local commands, and a successful native Blender exit. It retains
real packing failures, five-role bundles, reload, dirty user Images, and
transaction rollback. The same fixture previously timed out at 300 s with
stacks in repeated RNA `socket.links` scans; validation now constructs a fresh
link index per call. Live compositor refresh advances after the later host
invalidation repair; its numerical acceptance is tracked separately below.

A live reset-Color diagnostic localizes that Auto discrepancy to an unnecessary
signed-energy/J_A round trip: the same neutral pixel changes from J_A 522 after
Tone to 521.5 after Color, with about 1.308% normalized RGB error. The first
frozen-J_A carrier probe passed `:compositor_carriers` in build
`f5c24a36-41b7-4ec7-a57e-f30b357fe352` (164.3 s). Its 18 real live evaluations
span GPU Auto, GPU Full, and CPU Full. Tone/Color J_A handoff matches exactly;
the largest neutral Auto output improved from 89.3125 to 89.875 against
90.509666 (about 0.00694 normalized error), and Full modes pass `1e-4`.

This is intermediate-source evidence. Equality of stored energy alone is
unsafe when the carrier underflows to zero and Scale changes. The semantic
hardening carries J_A explicitly through disabled stages and inactive H–K repair
and multiplies it by positive Scale. The intermediate build's shipped
`:compositor_gui` still failed exposure/GPU Auto at 0.01068249 against the
unchanged 0.01 limit; that result does not describe the final accepted candidate.

Final live acceptance passed in remote build
`252b9488-83c2-49de-8943-8f509bc7e8f0`. The installed `:compositor_gui` fixture
took 61.382 s and retained all 16 exercise frames and 12 automatic updates,
signed/HDR/nonfinite input colors, exact alpha checks, two reload-repair frames,
and normal exit. Auto retains its 0.01 normalized RGB limit; Full retains
`1e-4`. The source `:compositor_carriers` gate passed all 18 live evaluations
in 226.453 s across GPU Auto, GPU Full, and CPU Full, including exact
Tone/Color J_A handoff. All five transport checks passed. The complete batch
ran four remote commands and zero local commands.

The accepted production-Compositor path retains Tone's raw response basis only
when Color and H–K are semantic identities, composes uniform output conversion
before spatial decode, and attempts a smaller radius only after a primary
decode is illegal. The retry must pass actual decoded legality. These changes
address extra half-image round trips and boundary rounding without modifying
the generic full-Grade or Stack defaults, the numerical limits, or publication
policy ownership.

Final frozen-asset build `40fc9dd3-66b5-452b-9bbb-cf052870b80e` passed all five
asset gates: shipped Shader Color (one method, 26.850 s), shipped Compositor
Color (one method, 27.219 s), template behavior (13 methods, 43.297 s), bpy
receipt schema (three methods, 56.718 s), and native executable receipts
(three methods, 62.664 s, plus one build-only check in 65.173 s). Both numerical
gates retain `1e-4`; exact append/binding receipts cover all 12 groups. The
remotely materialized final assets contain a 3,688,385-byte `.blend`, a
9,464-byte runtime manifest, and a 67,226-byte Stack shader. The 7,896,941-byte
structure report remains a build diagnostic outside the extension ZIP.

The link-index repair also reduced the installed ownership setup phase from
397.139 s to 58.886 s in recorded fixture runs. The latter still records 33 tree
builds totaling 30.379 s and cumulative preparation-drain measurements of
39.679 s; those phase totals are not additive wall times or interactive latency
guarantees. A separate removed-primary-Image repair makes role enumeration
tolerate an externally deleted native wrapper; all 125 preparation-runtime
checks pass.

The complete installed suite subsequently passed with the semantic J_A carrier
in remote build `2e322f99-3ca6-4d12-b4d1-fcf598568d3f`: 223.659 s on Blender
5.3 and 224.968 s on LTS, including normal native exit. It retains every
installed section, removed-primary-Image recovery, and the strict check that
recovery requires only one preparation. Its recorded section durations are:

| Installed section | Blender 5.3 | LTS |
|---|---:|---:|
| Node and ownership setup | 58.685 s | 58.281 s |
| Parameter publication and save/load recovery | 66.785 s | 67.273 s |
| Stack and gestures | 15.521 s | 15.476 s |
| Concurrency and failure | 57.261 s | 56.470 s |
| Undo and teardown | 21.935 s | 23.469 s |

These five sections exclude extension startup and other harness overhead, so
their sum does not equal the complete test duration. They measure the installed
correctness fixture, not interactive latency. Live compositor precision remains
a separate acceptance gate.

Installed node-owned Stage 3 animation passed in build
`8429ee5b-7fc8-48b4-b24d-ca6a24daf230`: the two background/GUI methods took
68.866 s on Blender 5.3 and 68.087 s on LTS. They retain animated Web and
Adaptance values, complete helper-role publication, persistence, per-frame
preflight, the 300-second process limit, and normal native exit. The batch ran
59 remote commands and zero local commands.

Real window drag and undo gesture gates also passed in build
`77704df5-bbed-45ae-818f-a1864ff82ab2`: `:gesture_drag_gui` took 17.075 s and
`:gesture_undo_gui` took 11.832 s per test body, with six remote commands and
zero local commands for the batch. Their passing gesture scope does not imply
that the separate live GPU Auto gate has passed.

CI enumerates both native acceptance halves and all five parameterized graph
targets, together with the production-template, Color transport, receipt, and
installed animation gates. Its explicit Next inventory also includes
`handbook_audit`, which checks the completed site, deployment archive, and
print artifacts for animation exclusion and the retained legacy ZIP link.
The book toolchain is a declared dependency of that Next audit.

The template receipt gates run the same append and binding cases through two
Blender hosts:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:template_receipts \
  //products/perceptual-grade-next-blender/tests:template_receipts_blender
```

`template_receipts` uses the bpy 5.3 wheel; `template_receipts_blender` uses the
pinned native Blender 5.3 executable. Both compare all 12 appended groups with
the generator's exact structure receipts, check Grade bindings in Shader and
Compositor for Linear Rec.709, Linear Rec.2020, and ACEScg, and reject effective
float32 subnormal socket literals. This catches host-specific literal changes
without weakening the runtime structure contract. Detailed receipt payloads
are test diagnostics from `node_templates[report]`, rather than extra shipped
manifest data.

The finite-output router has focused gates separate from Grade accuracy:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:compositor_validity \
  //products/perceptual-grade-next-blender/tests:compositor_validity_blender
```

The first checks CPU Full; the native Blender gate also requests GPU Full and
GPU Auto. Final rendering promotes the requested Auto mode to effective Full,
so these checks do not establish half-precision materialization safety.
They inject NaN and positive/negative infinity into projected RGB
and into observed state whose projection is finite, then require magenta and
exact alpha preservation. These cases validate routing at the observed graph
boundary. They do not establish every finite intermediate's accuracy or
replace production-template and `compositor_gui` live-Viewer acceptance.

## Shared Grade regression checks

Run the ownership and real undo/redo fixtures with:

```sh
buck2 test //:blender_test_shared_grades //:blender_test_shared_grade_undo
```

These tests use real Blender RNA and native evaluation graphs. They cover empty selectors, lazy allocation and cancelled drags, cross-editor propagation, local Render Method and handle focus, independent copies, renaming, unlinking, retained unused data, Grade-owned keyframes, current-format node ownership, and save/load/disable/re-enable. The undo fixture exercises Blender's undo stack for shared edits, allocation, copies and unlinking.

`//:blender_test_white_and_render_ui` renders a Grade shared between Shader and Compositor users, then compares output with the extension disabled. The existing render fixtures also check native save/reload and packed LUT persistence. Selector draw tests validate the `template_ID` binding; interactive desktop operation and GPU rendering still require a desktop check.

## Grade and Stack editing regressions

Run the current authoring regressions through the same isolated Blender runner:

```sh
buck2 test //:blender_test_stack_editing //:blender_test_grade_stack \
  //:blender_test_working_white //:blender_test_shared_grade_undo
```

`test_stack_editing.py` invokes 53 pytest cases under `tests/blender/stack_editing/`.
Pytest and its exact development dependencies are pinned in `third_party`; they
are not part of the installed extension. The cases exercise compact controls,
shared ownership, enable/inverse state, Grade-node pencils, one active pencil
across multiple Grade and Stack nodes in both editor types, sidebar and close-button
synchronization, explicit pencil activation, occurrence
tracking during reorder, disabled editing, handle gestures and cancellation,
installed-LUT-only scopes, rejection of outdated bakes, native Shader/Compositor
CPU output, and current-format save/load/undo/disable/re-enable.

The original Stack and working-white fixtures continue to cover scheduling,
shared animation, signed RGB, alpha and coordinate invariance. Their inverse
operations now use single-entry Stacks. The ordinary Grade remains forward
with an independent Render Method. The undo fixture also covers entry bypass.
`inverse_reference.py` is a test-only Stage 2+3 adapter used by numerical solver
checks and historical precision studies; it does not provide an inverse node.

[The merged-source validation record](../downloads/grade-stack-ui-validation.json)
separates actual authoring runs from the Buck2 release gate and desktop/GPU checks.

## Progressive Stack bake measurements

The 1.18.0 regression gates are:

```sh
buck2 test //:numerical_test_progressive_lut //:numerical_test_cube_native \
  //:blender_test_stack_editing //:blender_test_grade_stack
```

They check nested-grid identity, exactly 274,625 total analytic samples for a settled preview/refinement pair, bit-for-bit common-vertex reuse, inverse diagnostic counts, cancellation and native sampling at both resolutions. The Blender cases cover preview publication, scope cache refresh, coalescing during continuous drags, deleted nodes, and final-render synchronization.

Three fresh numerical runs per case on Python 3.13.15 / NumPy 2.5.3, with one BLAS thread, produced these median times:

| Workload | Independent 65³ bake | First 33³ preview | Refinement only | Progressive total |
|---|---:|---:|---:|---:|
| Three forward Grades | 1.016 s | 0.121 s | 0.860 s | 0.979 s |
| One inverse Grade | 4.247 s | 0.996 s | 3.766 s | 4.830 s |
| Forward → inverse → forward | 4.693 s | 1.090 s | 4.192 s | 5.282 s |

Medians are taken separately, so columns need not add exactly. Timings exclude imports, scheduling delays, Blender image publication and rendering. They are numerical measurements on this host, not an interactive frame-rate or deadline guarantee. Two solver phases can add overhead even though the vertex count is unchanged; preview latency is the benefit. These measurements do not establish a sub-five-second final bake for all Stacks.

All nine refined 65³ tables were bit-for-bit identical to independent full bakes with the same parameters. This checks that refinement preserves final values for these workloads; 33³ previews still have coarser interpolation and are replaced before final rendering/saving. This timing run does not repeat the photographic display-error study.

[JSON with Grade parameters, environment and all runs](../downloads/progressive-bake-performance.json) / [CSV timings](../downloads/progressive-bake-performance.csv).

To repeat the timing measurement in an already prepared test tree:

```sh
python tools/testing/run_fixture.py --authoring-preview --tree . \
  --script tests/blender/benchmark_progressive.py \
  --output-dir /absolute/path/to/results --capture tests/blender/reports
```

Use the same generated inputs and environment described below. The timing script uses three repetitions by default and never reuses completed cube caches. This explicit authoring runner does not replace the Buck2 gate.

## CPU solver optimization and GPU exploration (1.22.0)

The installed CPU inverse now measures an analytic regular-system Jacobian,
including the reference-dependent H–K inverse. It reuses coefficient work,
skips inactive families and solves the two-variable normal step explicitly.
Its accepted forward function, iteration limits, candidate thresholds and
diagnostic tolerance are unchanged. The [math specification](forward-inverse-math.md#analytic-regular-jacobian)
defines these derivatives and their numerical branches.

Three interleaved fresh runs compared the supplied 1.21.0 solver with the
optimized solver on the current AP1 grid, using Python 3.13.15, NumPy 2.5.3
and one BLAS/OMP thread:

| Workload | Baseline 65³ | Optimized 65³ | Ratio |
|---|---:|---:|---:|
| One inverse Grade | 6.177 s | 4.425 s | 1.40× |
| Forward → inverse → forward | 5.230 s | 4.514 s | 1.16× |
| Three forward Grades | 2.236 s | 2.206 s | 1.01× |

This host showed substantial timing variation; retain every run rather than
interpreting the ratios as a workstation guarantee. Across the nine table
comparisons, the mixed/forward results were bit-for-bit identical and the
largest inverse table change was \(1.49\times10^{-8}\) in absolute RGB.
Every progressive table matched its independent full bake exactly, with all
common vertices reused. The 80 before/after accuracy checks cover 2,114
photographic/signed/HDR/neutral inputs per case, four whites and four Grade
configurations. The largest per-sample reproduction increase was
\(7.21\times10^{-10}\). Existing best-effort failures remain visible in the
data; this is not a proof of invertibility for arbitrary grades.

[CPU timings JSON](../downloads/cpu-solver-performance.json),
[CSV](../downloads/cpu-solver-performance.csv),
[accuracy JSON](../downloads/cpu-solver-accuracy.json), and
[derivative checks](../downloads/inverse-jacobian.json) retain parameters,
fixtures, environment and source fingerprints. Frozen baseline code lives
only in test fixtures and is excluded from the installed extension.

```sh
buck2 test //:numerical_test_inverse_jacobian //:numerical_test_cpu_solver_accuracy \
  //:numerical_test_inverse_solver //:numerical_test_inverse_math \
  //:numerical_test_progressive_lut //:blender_test_grade_stack \
  //:blender_test_stack_editing
buck2 build //:cpu_solver_benchmark --show-full-output
```

A cached Buck build result is an earlier timing sample. To collect fresh runs
in a prepared tree, use the explicit authoring runner:

```sh
python tools/testing/run_fixture.py --authoring-preview --tree . \
  --script tests/blender/benchmark_cpu_solver.py \
  --output-dir /absolute/path/to/fresh-results --capture tests/blender/reports
```

### GPU experiment (1.22.0 historical record)

The 1.22.0 frozen sources formed a developer experiment. Blender compiled its
Python-contained compute shader at runtime through
`GPUShaderCreateInfo`; no external GPU package or precompiled binary is installed.
Each invocation evaluates one vertex. It keeps the full Grade sequence,
regular two-variable inverse, scalar H–K/Tone inverses, and full-forward RGB
Broyden recovery on the device. Parameters use a fixed-capacity texture so
ordinary edits/short Stack changes can reuse the program and sampler layout.
The final table is read once per phase. A nested bake evaluates exactly
274,625 vertices, copying all 33³ common values into the final 65³ table.

The portable experiment uses float32. Its RGB stopping scale is
\(\max(10^{-12},\lVert y\rVert_\infty)\), with device cutoff
\(3\times10^{-6}\). Preserving relative accuracy in dark colors matters:
using the CPU's \(1+\lVert y\rVert_\infty\) normalization with a float32-sized
cutoff skipped small but visible dark adjustments. The fixed-reference guard
and tone Newton policies also use float32-sized thresholds. The installed
float64 CPU policy is unchanged. GPU audit fields count vertices needing RGB
recovery and those still above the device cutoff; they do not assert the CPU's
\(2\times10^{-8}\) diagnostic accuracy.

The full-grid software-renderer result and the independent photographic RGB/
four-output ACES comparison are in the [GPU exploration report](../downloads/gpu-solver-exploration.md),
with [JSON](../downloads/gpu-solver-performance.json),
[timing CSV](../downloads/gpu-solver-performance.csv), and
[photographic error CSV](../downloads/gpu-solver-photographic-errors.csv).
The report distinguishes warm bakes, driver compilation/first use and CPU repair.
Software-renderer timings cannot establish physical-GPU/Metal/Vulkan performance.
GPU baking was not selected by installed 1.22.0 nodes. The current source tools
now measure the installed implementation below; the downloadable 1.22.0
results retain their original source fingerprints and scope.

Run the opt-in arithmetic checks and a small context/dispatch probe with:

```sh
buck2 test //:gpu_solver_math
buck2 build //:gpu_solver_smoke --show-full-output
```

Run a fresh full measurement in a chosen desktop Blender:

```sh
buck2 run //:gpu_solver_benchmark -- \
  --blender /absolute/path/to/blender \
  --output /absolute/path/to/gpu-results/gpu-solver-performance.json \
  --full-grid --progressive --repeats 3 --repair
```

For photographic ACES metrics, also pass `--fixture-samples 2048` and
`--analysis-pythonpath /absolute/path/to/locked-analysis-wheels`. This directory
must supply the pinned test-only PyOpenColorIO wheel matching Blender's Python.
The wrapper enables Blender's explicit system-Python-path option for this run.
It uses factory startup and a private copy of the source tree. The same wrapper
can be invoked from source with `python tools/experiments/run_gpu_solver.py`.
No extension installation or existing project is needed. By default it rejects
software devices; `--allow-software` records a software correctness run explicitly.

The output includes shader/first-layout warm-up costs, every timing repetition,
complete Grade parameters, source/fixture/OCIO fingerprints, full-grid status,
device metadata, audit counts, separate scene/display eligibility counts,
JSON/CSV distributions and snapshots of evaluated code. Absolute RGB uses the
Rec.2020/D65 [0,10] input cube; ACES-rendered metrics use the AP1/ACES [0,128]
input cube. These independent masks are fixed at exact Stack input; pixels
outside both are excluded. GPU arithmetic, CPU LUT, and GPU LUT errors against
the complete float64 reference are separate measurements. Final render/save
publication and interactive scheduling are excluded from numerical timings.

These fixtures were executed with the pinned authoring-preview runtime.
Buck2 was unavailable on this host; its dependency/build gate and physical-GPU
desktop integration remain to be run on a supported workstation.

## Complete Metal matrix update fix (1.23.2)

The next Mac log showed one shader failure followed by CPU fallback, confirming
the 1.23.1 error policy. Compilation still rejected the `mat2` and `mat3`
rank-one matrices divided by a scalar. Both complete updates now operate on
vector columns before constructing a matrix; the solver equations and policy
are unchanged.

The arithmetic fixture reads every updated column for nonzero asymmetric
Jacobians and signed vectors. It checks the actual squared displacement and
small/large denominators, plus the two- and three-dimensional secant conditions.
The installed fixture retains the plain compiler/dispatch exception tests and
once-per-context fallback. Run the same `//:gpu_solver_math` and `//:gpu_baking`
targets below. [Validation data](../downloads/gpu-metal-matrix-fix.json) records
the current checks, source fingerprints and software-renderer scope. These
runs establish software OpenGL correctness, not native Metal compilation or a
new hardware performance measurement.

## Metal shader startup fix (1.23.1)

A supplied Mac log showed the compute shader failing on undeclared
`outerProduct`, followed by a plain `Exception: Shader Compile Error` escaping
the draw callback and triggering compilation on every redraw. The shader now
uses explicit column constructors for both Broyden rank-one updates. GPU
acquisition and dispatch catch ordinary exceptions, log/cache the failure once
per context, and let the timer publish the current CPU result.

The arithmetic fixture additionally checks both helpers with asymmetric signed
vectors. The installed fixture injects a plain compiler exception, checks the
single attempt and traceback, confirms that Preparing is cleared, and verifies
the current CPU LUT. Its dispatch-error injection also uses plain `Exception`.
Run the same `//:gpu_solver_math` and `//:gpu_baking` targets below.
[The fix validation](../downloads/gpu-metal-startup-fix.json) retains counts,
source fingerprints and the software-renderer scope. Physical Metal startup
and performance still require a Mac run. The 1.23.0 timing/photographic tables
below retain their original source snapshots; they are not new 1.23.1 timing
measurements. Current helper lifecycle and failure handling are documented in
the [Next policy chapter](next-policies.md#next-policy.helper).

## Installed GPU baking (1.23.0)

The installed implementation is `model/gpu.py`, `model/gpu_shader.py`,
`graph/gpu.py` and `graph/lut.py`. It automatically uses a physical graphics
device for nonlinear LUT work and reports the backend in the sidebar.
`tools/experiments/gpu_solver.py` is now a thin workstation-measurement adapter,
with an optional strict whole-grid CPU repair probe that is not installed.
The current [render and bake guide](https://rei277hz.github.io/perceptual-grade/manual/en/guide/render-methods.html)
describes Next's supported bake routes and render readiness.

```sh
buck2 test //:gpu_solver_math //:gpu_baking
buck2 build //:gpu_solver_smoke --show-full-output
buck2 run //:gpu_solver_benchmark -- \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --output /absolute/path/to/results/gpu-solver-performance.json \
  --full-grid --progressive --repeats 3 \
  --fixture-samples 2048 \
  --analysis-pythonpath /absolute/path/to/locked-analysis-wheels
```

`--repeats 3` performs three fresh timed bakes for each workload; it does not
change inverse iterations or quality. The default workloads are one inverse,
forward → inverse → forward, and three forward Grades. Shader creation and
first-layout/driver warm-up are reported separately. Final numerical bake time
includes bounded dispatches, texture upload/readback, flagged CPU recovery,
coordinate conversions and float32 storage. Flagged vertices share one CPU
recovery pool per preview/refinement phase. It excludes UI debounce, editor
frame gaps, image packing/publication, imports and render time. `--repair`
adds a separate strict whole-grid verification experiment, not the production
flag-only repair policy. Buck's cached build output is an earlier timing sample.

The arithmetic fixture checks all eight whites, curve Fits, signed/HDR/dark
inputs and independent float64 forward reproduction. The installed fixture
uses actual Blender GPU objects to check automatic acquisition, context safety,
nested exact reuse, worker rejection, flagged recovery, cancellation,
draw/timer publication, edit coalescing, fallback, native output and cleanup.
Its software-renderer opt-in is fixture-local; installed users keep automatic
physical-device selection.

[The integration report](../downloads/gpu-baking-validation.md),
[checks and native measurements](../downloads/gpu-baking.json),
[fresh full-grid JSON](../downloads/gpu-baking-performance.json),
[timing CSV](../downloads/gpu-baking-performance.csv) and
[photographic distributions](../downloads/gpu-baking-photographic-errors.csv)
record the actual validation scope. Photographic masks, four ACES outputs and
reference semantics remain those of the earlier study. Current GPU LUT results
include device-flagged CPU repair; GPU arithmetic-only results measure the shader
without LUT interpolation. Float32 audit thresholds do not establish the CPU
residual tolerance for every unflagged vertex.

This host has a software graphics device. These authoring-preview checks do
not establish physical GPU/Metal speed, a tenfold gain, interactive desktop
behavior or the Buck2 release gate. Repeat the workload on the target Mac and
retain its device, cold costs and every warm run when assessing those goals.

## Measure render methods

Run the benchmark on the workstation whose results you want to publish. It uses your desktop Blender with a built extension, factory startup, a deterministic signed/HDR texture, fixed nonzero Tone/Color adjustments and identical render settings for both methods. Six cases cover Shader small/full and Compositor full with Baked LUT and Direct. Preparation includes graph setup, coefficient data and LUT completion; one warm-up precedes repeated render timings. Retain the complete JSON, rather than a single summary value.

Example on macOS, using Metal for Cycles and GPU compositing:

``` sh
buck2 run //:benchmark -- \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --backend METAL --compositor-device GPU \
  --width 1920 --height 1080 --samples 64 --trials 5 \
  --output /absolute/path/to/perceptual-grade/docs/data/benchmark.json
```

For Linux, point `--blender` to a full desktop binary and choose CPU, CUDA, OPTIX, HIP or ONEAPI as available. Record the actual selected GPU and desktop build. The worker reports the compositor device separately. The small material occupies approximately 12.25% of the frame; both shader cases use an emissive surface to isolate repeated material grading from complex lighting variation.

The checked-in `benchmark.json` is explicitly **illustrative**. A real run emits `status: measured` and device/version/settings metadata. In the current book build, replacing `products/perceptual-grade-book/docs/data/benchmark.json` and building `//products/perceptual-grade-book/generators:figures` updates the labelled chart and Markdown table together. The historical `//:documentation_benchmark` target used six tiny native CPU cases to verify the runner; its timings are validation data, not publication measurements.

![Workload and preparation comparison](../assets/figures/render-benchmark.svg)

<p class="figure-caption">The supplied dataset is illustrative. Replacing it with workstation measurements updates this chart and table.</p>

{{#include ../assets/fragments/benchmark.md}}

[Download the benchmark data](../downloads/benchmark.json).

## Explicit authoring preview

Buck2 remains the release build/test gate. On a host where Buck cannot launch,
`tools/testing/run_fixture.py --authoring-preview --tree <prepared-test-tree>
--script tests/blender/test_chroma_drivers.py` runs the same fixture in an isolated
copy. Supply the pinned CPython/wheels, compiled catalogs, generated artwork,
localized DCTL/UI metadata and C++ host declared by `//:test_tree`. The runner
sets `PG_AUTHORING_PREVIEW`, never `PG_BUCK_TEST`, and labels the execution.
This mode does not validate Buck dependency resolution or satisfy its release gate.

The p=2 regression fixtures live in `tests/blender/fixtures/p2`. Their generator
is `tools/testing/freeze_p2.py`; it writes to a separate output directory for
review. Its independent long-double driver formula is in `tests/blender/p2_oracle.py`.
Historical fixture files and hashes are retained. Guard/grid checks still compare
the old baselines for grades with inactive low/high controls. The new baselines
cover intentional classifier changes at the original numerical tolerances.

`test_forward_inverse.py` validates the documented regular inverse on 48 mixed
grades' input samples and 2400 guard probes. It is a solver demonstration, not a
production inverse baker or a convergence guarantee for arbitrary grades.

## Working-white validation

`//:blender_test_working_white` checks all eight Grade whites, all three supported scene RGB spaces, matrix rebasing and decomposition, matrix-owned animation, both Add-menu entries, scopes, current-format save/load and reuse of ordinary/Stack LUTs after scene-space changes. It includes 24 native CPU renders across Shader/Compositor and Direct/Forward LUT/single-inverse Stack/mixed Stack paths. The 1.15.0 run passed 102 checks. [Download the native measurements](../downloads/working-white-native.json).

Working-space invariance and LUT approximation are separate tests: unchanged LUT coordinates preserve the same sampled function across scene spaces, but do not make that sampled function exact.

## Inverse and Stack precision

Run `//:numerical_test_inverse_math`, `//:numerical_test_inverse_solver`, `//:blender_test_grade_stack` and `//:blender_test_shared_grade_undo` for inverse equations, node behavior, native rendering, persistence and undo. `tests/blender/evaluate_working_white_precision.py` measures the current fixed LUT boundaries, with D65, ACES and D50 Grades in a Forward → Inverse → Forward sequence.

The earlier 1.15.0 Rec.709 report used 2,048 sampled pixels from each IMG_* fixture, converted from their original linear Rec.2020 coordinates without clipping. Mixed Stack p99 normalized RGB error is 0.000371–0.001575, lower than three separate LUTs in all four samples. Individual errors can be much larger: IMG_0472 has a Stack maximum of 0.082083 and ordinary inverse maximum of 0.206524. Extreme signed colors and extrapolation also have substantial errors. One cube removes intermediate interpolation but does not guarantee higher accuracy for every pixel.

Normalization is max absolute RGB error divided by 1 + max absolute reference RGB; it is not perceptual ΔE or percent brightness. The ordinary inverse bake reports 174 approximate vertices out of 274,625; the mixed Stack reports 130. These are solver reproduction diagnostics before LUT storage/interpolation. [Download the historical 1.15.0 measurements and Grade settings](../downloads/working-white-precision.json). The implementation includes `docs/engineering/working-white-validation.md` with complete tables and validation scope. Native CPU lookup tests, inverse solving and interpolation measurements remain separate; GPU/Metal results are not claimed.

That historical precision run took 4.08 seconds for the ordinary inverse, 5.13 seconds for the mixed-white Stack and 1.05 seconds for a forward Stack. These are single-run numerical bake measurements excluding Blender publication and the edit debounce. They do not guarantee a deadline for every grade or machine.

## LUT sampling and ACES 2.0 display error

Version 1.16.0 replaces the previous Rec.709 LUT with **fixed linear Rec.2020/D65, −4…+64, 16 negative / 48 positive cells and positive asinh κ = 0.001** for every Blender working space. The selection study compared 50 configurations, including fixed Rec.2020/D65, smaller negative ranges and four shaper families. It evaluates all 338,688 stored pixels from the four IMG_* fixtures for ten finalists, with four finalists also checked at −2 and +2 stops of input exposure. The stored fixtures sample every twelfth row and column of the original EXRs; this is not a full-resolution original-image evaluation.

The study retains scene-RGB errors and adds absolute-light ΔE_ITP after the actual OCIO ACES 2.0 transforms: SDR 100 nits Rec.709, SDR 100 nits P3-D65, HDR 1000 nits P3-D65, and HDR 1000 nits Rec.2020, all with D65 creative white. Luminance error in nits, encoded-channel errors and fractions above ΔE_ITP 1/2/5 are also recorded. These display measures complement RGB error because the view transform changes the visibility of scene-linear differences.

Each value below is the largest per-case p99 ΔE_ITP across four images and five ordinary/Stack workloads, using all stored pixels at original exposure. It is not a pooled percentile or a maximum-pixel error.

| ACES 2.0 output | Previous Rec.709 | Selected Rec.2020 |
| --- | ---: | ---: |
| SDR 100 nits Rec.709 | 3.308 | 1.510 |
| SDR 100 nits P3-D65 | 3.683 | 1.617 |
| HDR 1000 nits P3-D65 | 3.938 | 1.726 |
| HDR 1000 nits Rec.2020 | 4.105 | 1.823 |

At input exposure −2 / 0 / +2 stops, the worst p99 across all outputs is 1.374 / 1.823 / 2.086 for the selected grid, versus 2.998 / 4.105 / 6.385 previously. At +2 stops, five pixels in an 84,672-pixel case exceed the −4 bound (0.00591%). The largest original-exposure error remains 11.738 ΔE_ITP; this is not a visually lossless transform. ΔE_ITP 1 is a sensitivity reference, not a universal visibility threshold.

The historical production measurements used `tests/blender/run_lut_study.py evaluate_lut_sampling --production --mode full --ocio-config /path/config.ocio --output /fresh/results`. The current `--production` option follows the current policy and does not recreate the historical selected grid. The display comparison requires Blender's OCIO 2.5.0 ACES 2.0 implementation for this comparison. [Download production per-case measurements and metadata](../downloads/rec2020-production.json). The full forward/inverse math and explicit sampling-basis equations are maintained [in this handbook](forward-inverse-math.md).

The selected Rec.2020 configuration with range −4…+64, 16 negative cells and positive asinh κ = 0.001 reduces the worst per-case p99 ΔE_ITP from 4.105 to 1.823 at original exposure, although normalized scene-RGB p99 rises from 0.003427 to 0.004296. It also increases the worst fraction above ΔE_ITP 1 from 4.55% to 6.46%. The 12-negative-cell alternative has fewer moderate errors but a worse p99 at +2 stops. Smaller negative bounds reduce coverage; extrapolation remains possible. No configuration improves every metric. The choice prioritizes the worst p99 across the tested outputs and input exposures, while retaining the moderate-error fractions and domain exits in the report.

That historical 1.16.0 Rec.2020 boundary was fixed across Blender scene spaces. Surrounding gamut/Bradford matrices convert to and from it; each Grade retains its own white and grading function. Changing the LUT basis must not change the model's primaries, anchors or Grade interpretation.

The source tools are `tests/blender/run_lut_study.py`, `evaluate_lut_sampling.py`, `lut_sampling.py`, `aces_metrics.py`, `test_lut_study.py` and `report_lut_sampling.py`. The 123 focused checks cover the sampler, extrapolation, scene-space covariance, independent ITP/PQ calculations and OCIO output-path agreement. OCIO, Colour and Matplotlib are analysis dependencies only. The historical production `Baker`/`Cube` evaluation reproduced the 1.16.0 selected experiment’s original-exposure summary values. The independent sampler checks, frozen analytic fixtures, native Shader/Compositor tests and working-space invariance checks cover integration. These results are not a native GPU test or a completed Buck2 release gate. [Read the original selection report with figures and reproduction commands](../downloads/lut-sampling-report.zip) or [download the summary data](../downloads/lut-sampling-summary.json).

The historical 1.14.1 [precision](../downloads/inverse-stack-precision.json) and [performance](../downloads/inverse-bake-performance.json) data remain available. Those measurements use a different RGB basis and Grade-white setup, so their errors are not a direct comparison with 1.15.0. `tests/blender/benchmark_inverse.py` measures repeated fresh numerical bakes; the older engineering report describes the Python-only solver redesign.


## Reproducible LUT shaper experiment

The subsequent [+128 domain study](lut-domain-study.md) uses independent scene-RGB and ACES-rendered-RGB masks, adds native ACEScg/ACES white and fixed-primary AP1/D65 sampling, and extends the photographic exposure sweep. Its specifications, Buck2 targets and result tables are separate from the historical −2…+64 study below.

Version 1.20.0 adds a declared Buck2 comparison of **82 grids** for the requested −2…+64 domain. The previous −4…+64 production grid remains a measurement baseline. The specification is `tests/blender/experiments/lut-shaper.json`: it contains the exact photographic fixture paths and SHA-256 hashes, three complete shared Grade definitions (matrices, whites and Tone/Color parameters), five workloads, exposure offsets, seed, shaper families/scales, negative allocations, output transforms and selection rule. `lut-shaper-matched.json`, `lut-shaper-negative.json` and `lut-shaper-refinement.json` record the three authoring batches. Editing the main specification invalidates its Buck2 input and recomputes the comparison.

```sh
buck2 build //:lut_shaper_evaluation //:lut_shaper_report --show-full-output
buck2 test //:lut_shaper_experiment_test
buck2 test //:lut_shaper_full_result_test
buck2 build '//:lut_shaper_evaluation[selection]' \
  '//:lut_shaper_evaluation[metrics]' '//:lut_shaper_evaluation[metadata]' \
  '//:lut_shaper_evaluation[full]' --show-full-output
```

The smoke test runs a small photographic subset and verifies the artifact contract. The full-result test depends on the full experiment and independently reconstructs the selection from the per-case metrics. The full comparison takes substantially longer than an individual LUT bake because it renders millions of pixel comparisons through four ACES transforms for every candidate. Buck2 caches results when declared inputs remain unchanged.

The evaluator uses the pinned development `bpy` wheel to extract the **complete stock Blender OCIO configuration and resources**, and the pinned PyOpenColorIO 2.5.0 CPU implementation. No installed desktop Blender path or ambient `OCIO` environment variable is needed. `bpy`, PyOpenColorIO, Colour and Matplotlib are development dependencies; PyOpenColorIO is absent from the installed extension. The source inventory, dependency locks, configuration/resource fingerprints, model source fingerprints and numerical parameters are captured in the result metadata. Numerical metrics are the reproducibility contract; elapsed times and platform metadata vary between runs. BLAS/OMP threads are fixed to one before loading NumPy.

### Inputs and analytic reference

The four IMG_* fixtures contain **338,688 stored pixels**, sampled every twelfth original EXR row and column. Every stored pixel is tested at −2, 0 and +2 stops, giving 1,016,064 inputs per workload. Signed inputs are retained. Forward Grade, whole-Grade inverse, inverse round trip, three-forward-Grade Stack and forward/inverse/forward Stack are separate workloads. Stage 1 stays outside the ordinary forward cube and is included in every Stack cube, including the single-entry inverse. All three Grades use their recorded working whites and the current Bradford connections.

Each cube stores float32 values calculated directly from the float64 analytic Grade/Stack path, including bounded selected-inverse root solving. Between vertices, the independent prototype locates cells with `searchsorted` and performs tetrahedral interpolation using **physical linear-RGB distances**. The production sampler is checked against that prototype separately. Solver diagnostics and vertex hashes are recorded. The inverse reference is the selected analytic/numerical inverse function; it is not an assumption that all grades have an exact round trip.

A deterministic screening subset uses 2,048 pixels per fixture. The four best balanced candidates, two best display candidates, two best absolute-RGB-p99 candidates, the baseline and explicit mandatory candidates enter full validation. Repeated choices count once. Every stored pixel is included in full validation; screening-excluded heldout distributions are also recorded. “Best” means best among that fully validated shortlist, rather than a proven optimum over every possible shaper or grade.

### Metrics and ranking

For a reference RGB \(\mathbf r\) and sampled RGB \(\hat{\mathbf r}\), the per-pixel absolute scene error is

$$
e_{\mathrm{RGB}}=\max_{j\in\{R,G,B\}}|\hat r_j-r_j|.
$$

It is measured separately in Linear Rec.709, Linear Rec.2020 and ACEScg, using the stock OCIO conversions. Normalized error \(e_{\mathrm{RGB}}/(1+\max_j|r_j|)\) and relative error with a 0.001 denominator floor are also retained. Absolute RGB RMS is \(\sqrt{\operatorname{mean}(e_{\mathrm{RGB}}^2)}\): it is the RMS of the per-pixel maximum-channel error, not an RMS pooled over channels.

The four output transforms are SDR 100 nits Rec.709/BT.1886, SDR 100 nits P3-D65/sRGB, HDR 1000 nits P3-D65/PQ and HDR 1000 nits Rec.2020/PQ, with D65 creative white and no additional look or view exposure. The P3 HDR path uses the same OCIO ACES 2.0 output built-in even though stock Blender does not list that display pairing in its UI. Rendered differences include absolute-light ΔE_ITP, luminance nits, encoded-channel error, display-linear RGB nits and fractions above ΔE_ITP 1, 2 and 5.

Each statistic is computed **per fixture × exposure × workload**, then the worst case is taken. Percentiles are not pooled across fixtures. The predeclared balanced objective minimizes the largest ratio to the previous grid across **ten terms**: four worst per-case rendered p99 ΔE_ITP values, three absolute scene-RGB p99 values and three absolute scene-RGB RMS values. All terms have equal standing in this minimax rule; a ratio above one identifies a regression. Ties use the worst rendered p99 and then the grid name. The rule requires a nonzero baseline error, so an identity-only grade is unsuitable for this ratio objective. Maxima and all other statistics remain in the tables even though they do not determine the ranking.

### Outputs and authoring execution

`metadata.json` stores inputs, model/configuration versions and fingerprints; `selection.json` identifies the selected grid and objective; `screen-ranking.json` and `full-ranking.json` contain rankings. Per-grid `screen/` and `full/` JSON files retain every case, heldout distribution, worst-pixel coordinate, domain exit, RGB/display metric and solve diagnostic. `metrics.csv` and `ranking.csv` provide flattened tables. `manifest.json` fingerprints every non-cache output. The report target produces two scientific figures and `report.md`. Numerical cache files are build intermediates and are excluded from the downloadable report.

The evaluator can also run as an explicitly labeled authoring check, with the pinned analysis dependencies available:

```sh
python -m tools.experiments.ocio_snapshot --output-dir /fresh/ocio
python -m tools.experiments.lut_shaper --tree . \
  --spec tests/blender/experiments/lut-shaper.json \
  --ocio-config /fresh/ocio/colormanagement/config.ocio \
  --output-dir /fresh/results
python -m tools.experiments.check_lut_result --results /fresh/results
python -m tools.experiments.report_lut_shaper --results /fresh/results \
  --output-dir /fresh/report
```

The bundled authoring measurements were produced in three candidate batches, with identical fixtures, Grades, outputs, seed, screening samples and objective. Their input metadata is retained, and the exact global shortlist is reconstructed. They are not labeled as Buck2 execution: Buck2 cannot start in the authoring environment because `/proc/self/exe` is unavailable. The declaration/input audits, generator entry points, numerical checks and artifact verifier passed; the native Buck2 build/test gate still needs a normal supported host.


### Recorded 1.20.0 comparison

The 82-grid screen selected 12 full finalists. The measured balanced winner in the requested range is **Rec.2020/D65 −2…64, signed log1p, 20 negative / 44 positive cells, positive κ = 0.003**, with slope-matched negative κ = 0.0019620422371104795. The table retains the previous grid and the best full-finalist display-p99 alternative.

| Worst per-case metric | Previous −4 / 16 asinh .001 | Selected −2 / 20 log1p .003 | Display alternative −2 / 16 log1p .001 |
|---|---:|---:|---:|
| SDR100_Rec709 p99 ΔE_ITP | 1.847365 | 2.183193 | 1.706017 |
| SDR100_P3D65 p99 ΔE_ITP | 1.871935 | 2.245625 | 1.827746 |
| HDR1000_P3D65 p99 ΔE_ITP | 2.075527 | 2.501072 | 1.922715 |
| HDR1000_Rec2020 p99 ΔE_ITP | 2.085620 | 2.514019 | 2.063685 |
| Linear Rec.709 absolute RGB p99 | 0.03051798 | 0.02558292 | 0.02650314 |
| Linear Rec.709 absolute RGB RMS | 0.01025971 | 0.01265570 | 0.01359318 |
| Linear Rec.2020 absolute RGB p99 | 0.02595036 | 0.02195883 | 0.02310018 |
| Linear Rec.2020 absolute RGB RMS | 0.00865254 | 0.01107384 | 0.01191678 |
| ACEScg absolute RGB p99 | 0.02521603 | 0.02129752 | 0.02237522 |
| ACEScg absolute RGB RMS | 0.00842654 | 0.01074439 | 0.01156180 |
| Balanced ratio to previous grid | 1.000000 | 1.279837 | 1.377258 |
| Worst fraction outside cube | 0.005905% | 0.184240% | 0.184240% |

The selected curve reduces the worst absolute RGB p99 from 0.030518 to 0.025583 (about 16.2%), but worst rendered p99 increases from 2.085620 to 2.514019 (about 20.5%), and worst absolute RGB RMS increases from 0.010260 to 0.012656 (about 23.4%). Its minimax ratio is 1.279837: **the previous wider grid is still better on the joint objective**. Under the mandatory −2 lower bound, this is the best tested balanced finalist. If displayed p99 alone is the goal, the 16-negative-cell log1p .001 variant is preferable, with larger RGB RMS. Ordinary forward Grade errors improve for the selected curve; Stack/inverse cases determine the overall tradeoff.

The ACEScg nonnegative [0,64]³ corner calculation agrees with the proposed negative bound to stock-processor precision: minimum blue ≈ −1.939416. It also produces positive blue ≈ +65.939415, so +64 is not complete source-cube coverage. More significantly, the stored signed fixture inputs at +2 stops reach −4.902344 at a Stack LUT boundary; 137 pixels in that case lie below −2, compared with five below −4. The worst outside fraction across all workloads is 0.184240% for −2 versus 0.005905% for −4. These pixels are included in every percentile, RMS and display calculation and use continuous boundary-cell extrapolation. None is silently clipped or discarded. A source conversion bound therefore does not establish that −2 improves grading accuracy.

![Full-finalist display and RGB error tradeoffs](../assets/illustrations/lut-shaper-errors.svg)

![Previous and selected sample placement](../assets/illustrations/lut-shaper-placement.svg)

{{#include ../assets/fragments/lut-shaper-key.md}}

These vector redraws use the recorded finalist scores and exact sampling axes in the original shaper report archive. No measurements are rerun to produce them. [Download the chart sources and plotted data](../downloads/chart-sources.zip).

[Download the selected grid and scores](../downloads/lut-shaper-selection.json) or [the complete recorded JSON/CSV results, figures, input metadata and current-source confirmation](../downloads/lut-shaper-report.zip). The source package contains every referenced fixture and specification. Native CPU Shader/Compositor sampling, 33/65 nesting and half-buffer transport are validated separately from these float64-reference interpolation errors. GPU/Metal precision is not claimed.

## Native AP1 production LUT (1.21.0)

Production now uses **native ACEScg/ACES white, bound 1024, 64 positive intervals, plain log1p κ = 0.01**. The shaper and sampling space were selected by the domain study among its +128 finalists; the bound was raised afterwards, so the selection evidence covers the shaper rather than the 1024 domain. [The domain study](lut-domain-study.md#adopted-production-choice) records why this display-linear/peak-nits choice differs from the encoded-RGB winner. Historical comparisons above retain their original parameters.

```sh
buck2 test //:numerical_test_cube_math //:numerical_test_cube_native \
  //:numerical_test_progressive_lut //:numerical_test_lut_grid_regression \
  //:numerical_test_hk_fixture_regression
buck2 test //:renders_blender_cube_test //:blender_test_working_white \
  //:blender_test_grade_stack //:blender_test_stack_editing \
  //:blender_blender_half_precision_test
```

The independent AP1 oracle reconstructs primary matrices, Bradford adaptation, the axis and physical interpolation separately. Analytic fixtures remain frozen. Tests retain signed/HDR extrapolation, all eight Grade whites and three scene spaces, Shader/Compositor rendering, alpha, current-format save/load/undo, shared Grades, and exact 33³/65³ vertex reuse. The half-float buffer test covers the single-image base/edge encoding; Shader retains raw vertices. Native CPU and buffer-emulator checks are distinct from GPU/Metal acceptance.
