# Perceptual Grade Next architecture

Last updated: 2026-11-01

**Status: initial product composition is implemented, with focused installed
Shader Image/UV and Compositor Bake, scope chart, Save/Render and recovery
acceptance. Readiness/content validation, compensation and production proof
gaps remain; the active delivery is incomplete.** Independent Next
core/product packages, numerical
models, a native Grade insertion adapter, Stack LUT/datablock preparation,
package ownership gates, static edit-triggered preparation, exact project
receipts, and a Blender-backed owner-readiness adapter now exist. The
standalone Grade graph's node-count target and known
extreme-Web software-GPU error remain explicitly deferred findings, not gates
for beginning or completing this Next integration. The
[state-machine design](STATE_MACHINE_DESIGN.md) is authoritative for properties,
transitions, receipts, proof boundaries and acceptance. [GOAL.md](GOAL.md)
and [CHECKLIST.md](CHECKLIST.md) track the remaining work. This architecture
continues to define the required complete scope/project workflows, native Bake,
Save/Render integration, recovery, and acceptance. The current project adapter
observes packed Grade/Stack owners and feeds evaluator/manifest receipts
into the portable gate; source-conversion proof and recovery gaps below prevent a claim of
complete admission correctness. `output_gateway.py` owns frozen-source capture and
Bake-stage receipts, including transactional Image publication. Owned
Save/Render operators provide confirmation, readiness continuation and one-shot
native invocation. `scope_runtime.py` owns the singleton actor/view/Gizmo
composition and Blender source/barrier observations. `scope_capture.py` captures
visible viewport pixels through a non-destructive GPUOffScreen and reports
scene-linear statistics and histogram, waveform and vectorscope pages. Matching
user keymap actions and the four agreed File/Render menu entries route through
reversible owned redirects when supported;
direct native operator/script calls remain outside the gate. The registered Bake
operator supports Shader Image/UV and Compositor capture and binds Grade/Stack
capture to the accepted native evaluator. Coherent primary/reference/environment
batches and broader native lifetime interleavings remain unfinished.
Persistent load/Undo/Redo
recovery validates Stack payloads, rebuilds Grade controllers, restores
interrupted packed Grade-field, structural replacement and Image publication
transactions, removes orphan candidate resources, and discards transient output
operations. A failed structural compensation retains its ledger and both tree
references as repair debt. Field recovery now blocks new work while any ledger is
retained and restores by transaction/slot metadata without the JSON marker. The
remaining readiness, compensation and serialization gaps are documented in the
[handoff](CHECKLIST.md#current-audit-handoff-2026-11-01). This documentation
pass records those issues and stops without runtime or proof changes.

The next bounded implementation is
[trustworthy readiness and recovery](READINESS_RECOVERY_STEP.md), covering this
preparation-to-admission boundary. The step specification fixes the acceptance
scope and separates stable Stack recipe identity from the final native-content
manifest. The milestone remains incomplete; a passing kernel proof does not
close its native recovery and acceptance gaps.

## Source ownership

The independent `libraries/perceptual-grade-next-core` library owns
host-independent grading mathematics, identities, immutable descriptions and
checked workflow policies under `perceptual_grade_next_core`. This product
owns Blender graph/UI integration, native observation and effects, capture,
publication, lifecycle composition and packaging under
`perceptual_grade_next_blender`.

The separate [native grading library](../../libraries/perceptual-grade-nodes/README.md)
owns native graph construction and its versioned helper fields and generated
boundary asset. Next core stays independent of Blender and owns its portable
implementation of the current reference semantics; the independent reference
is a numerical oracle, not a runtime dependency. Product installation,
publication and recovery belong here.

Neither new runtime package depends on `perceptual_grade_core` or
`perceptual_grade_blender`. The preserved implementation is reference material,
not a second runtime authority. Reuse the generic `invariant`, `blender-runtime`
and `color-core` libraries through explicit dependencies. The design does not
authorize a broad rewrite of those libraries or changes to the old product's
behavior. Any necessary shared interface addition must preserve its existing
callers. Shared source changes require explicit impact assessment and validation
of affected preserved consumers; private installed copies do not provide source
isolation. Coordinator/regular-machine labels do not create a new ownership
boundary in the generic runtime.
All library/tool dependencies and generated assets remain explicit Buck2
dependencies with pinned external versions; a helper process does not bypass
the build dependency contract.

Preserve existing core/product sources, Buck targets, tests and aliases;
DCTL/reference consumers remain on the old core. Next uses the additive targets
`//:perceptual_grade_next` and `//:verify_next`, while `//:perceptual_grade` and
`//:verify` continue to select the preserved implementation. New packages have
independent source, package and proof inventories and cannot inherit the old
product's workflow state or proof authority.

The `project_unbounded_proof` kernel now passes 170 obligations and 4 mutation
checks in build `e458d854-a0f2-474f-9ee4-e903e6da13b7`. The proof does not cover
production `project.py` owner/evaluator/artifact conversion or native admission;
there is no fresh aggregate receipt after this audit. The joint
`scope_view.inv` has five proposed properties and no target, and lacks the
required nonempty `invariants` mapping. The
[coverage inventory](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
distinguishes proved production helpers from smaller specification models and
remaining native claims. Test old and new extensions in separate Blender
profiles/processes; concurrent enablement and compatibility conversion are not
features of this work. The
Blender extension identity remains `perceptual_grade` despite distinct Python
package namespaces: those namespaces do not isolate global RNA classes and
operators in one Blender process.

## Authority and effects

One actor-owned scope workflow per App owns demand, acquisition, analysis,
cancellation and display acceptance. Foreground view authority and the effect
gateway live outside the computational App. They revoke the single global Gizmo
immediately, including when the actor has failed, without waiting for worker or
recovery progress. Scope results retain exact
request, submission, owner and view identities; cancellation cannot revive an
attempt or settle its successor. Late receipts retain their original owner and
cannot advance, publish into or fail a successor.

One project workflow owns explicit Bake, static Grade/Stack preparation,
Save/Render admission, publication and normal recovery relationships. A separate
extension-lifetime Restart supervisor remains available after an App fault and
retains cleanup obligations until exact terminal receipts permit replacement.
Scheduler leases do not grant domain permission. Local failure handling must
offer explicit Retry and preserve previous results.

`ScopeActor`, `ViewAuthority` and `RestartSupervisor` call the production
source-bound scope, foreground and Restart policies. Foreground closure advances
the view epoch immediately; display adoption consumes one matching issued
receipt. Scope admission blocks playback, outstanding physical debt and repeated
starts for one demand. Restart accepts its bounded cleanup categories in any
receipt order and retains unresolved obligations on failure. These local proofs
do not establish native capture, resource/service ownership or installed teardown.

Actors authorize exact operations; foreground adapters perform short native
effects and return matching receipts. Start grants establish in-flight
obligations, while foreground gates can still abort a body whose live
prerequisites changed. Logical cancellation never substitutes for worker,
reader, borrow or native-effect retirement. Checked production helpers establish
local composition properties; cross-family grant transport and native effects
retain explicit external premises and integration tests.

Required scope behavior includes coherent primary/reference capture, compatible
progressive publication and exact native readiness. Bake admission requires
semantic preflight. Public callbacks must report defined localized failures and
logs rather than let exceptions escape. The unfinished native correspondence and
capture batches remain acceptance gaps, as recorded above.

## Static preparation and dynamic sources

Grade/Stack parameters and prepared transforms are static. The new pair will
omit Grade animation, auto-keying, dependency drivers, copied animation Actions,
per-frame texture banks, per-frame LUT controllers and separate Exact LUT actions;
it does not prepare a scene-range Grade/LUT timeline. Manual edits must invalidate
the relevant preparation and interrupt unfinished Bakes.
This does not freeze source images, scene inputs or scopes. Frame changes request
new measurements; playback retains the accepted display and pauses acquisition
and publication until playback has stopped and native evaluation has completed.
Material capture follows the last-used viewport's effective lighting and framing
in the same window; authored World scopes are labeled **Scene World**, distinct
from studio lighting.

Prepare each owner's complete immutable candidate values and resource payloads
with matching endpoint matrices and bindings. Grade is forward-only and uses
one native node tree, including packed coefficient/geometry fields; it has no
separate preview transform or Grade LUT. Initialize all stage and Color-family
nodes and fixed-size helper images once, then update values and neutral-stage
bypass links in the same tree. Native reader exclusion is required for the
complete mutation/readback/rollback interval. Reader/writer admission now covers
update installation and owned Scope/Bake readers, with focused deferral and
release tests; complete native retirement/exclusion acceptance remains open.
Fixed field layouts are selected and
verified by development audits; runtime does not search resolutions or run dense
reference gates. The [standalone graph handoff](../../libraries/perceptual-grade-nodes/EVIDENCE.md)
provides the numerical backend; its under-1,000-node target and known
extreme-Web software-GPU error remain deferred and are reported without being
claimed as resolved. Standalone lifecycle, numerical and timing receipts retain
their recorded source/layout scope; the standalone GUI fixture and earlier
2D-enabled acceptance/performance receipts do not establish Next product
acceptance.

Grade Stack is a separate ordered LUT backend with Shader/RGBE Compositor
transport. Its installed 33³ preview is sampled from the even coordinates of
the 65³ final lattice and those vertices are reused exactly during background
refinement. Candidate installation replaces the preview evaluator only after
the packed 65³ image and its native binding validate. Only the completed 65³
LUT is final-quality output; Save/Render admission now waits through the owned
operator continuation. The agreed File/Render menu and keymap redirects are
installed; direct native operator/script calls remain outside this gate.
Stack entries support reference-compatible FORWARD and INVERSE directions,
including the 35/75 `abs(J_A)` low/high crossover, raw appearance handoffs,
endpoint matrices, nonlinear-pair cancellation and explicit finite inverse-search
residual/status semantics. Final readiness must bind the ordered entries,
reference recipe, endpoint matrices and quality tier. Grade's signed-input path
and Stack's AP1 input repair remain distinct numerical contracts. The old
capacity-based `.4*U` accelerated kernel is not a Next numerical authority.
Existing production Lean driver proofs retain that capacity-based scope and do
not certify the current reference equation. A GPU helper may
generate the Stack LUT only when its payload conforms to the current reference.

Grade Bake evaluates the accepted installed Grade node-tree output on its frozen
input samples. Stack Bake samples the accepted 65³ LUT using its shaper,
tetrahedral interpolation, endpoint matrices and decoded transport values. The
33³ preview is never a Bake source, and no per-pixel custom GPU helper may grade
Bake inputs. A helper may host Blender's native evaluator. Immutable source
identity and matching publication receipts must bind that evaluator to the
request. The required immutable manifest binds the backend, settings,
schema, quality tier, matrices, field contents/layouts and native bindings.
Current readiness rejects both JSON and retained-pointer transaction debt for
Grade and Stack. Grade admission compares the installed graph and image-content
records with its accepted manifest; acceptance with a live controller also checks
prepared field pixels. A built group or generated LUT alone is not a readiness
receipt.

Next UI maps the complete reference Grade/Stack settings, labels, units, defaults
and categorical choices within the supported fixed D65 / 203-nit viewing
context. Source-white adjustment and supported working RGB spaces remain
separate controls. Tone Fit is `[-2, 2]`; Color lightness/chroma Fits are `[-2, 6]`.
For other controls without a reference-defined UI limit, retain the current product's
declared range. Preserve prior payloads and exact native ownership,
install under native admission and verify readback before accepting publication.
Failure must retain repair obligations and quarantine an unverifiable owner;
the cleanup and snapshot gaps below still violate that requirement.
Independent owners need not update simultaneously, but project output readiness
requires every required owner to match the current intent.

`preparation_ledger.py` supplies durable backing before native publication.
Ordinary Grade field updates retain packed float32 copies and digest-checked
target/backup Image references plus native binding/default, metadata and host
link/default snapshots. A binding-only update also retains this ledger. Stack
or necessary Grade tree replacement uses a separate recovery NodeTree rooted by
the owner's serialized controls. It holds
real prior/candidate tree references, external link descriptors, input defaults
and the prior preparation/evaluator metadata. Installation verifies the candidate
binding and links before recording commitment. An uncommitted swap restores the
snapshot; a matching committed candidate survives recovery. Failed compensation
keeps the ledger and both trees as owner-local repair debt. Orphan cleanup cannot
discard a ledger still referenced by an owner, and never recreates a deleted owner.

Native tests exercise actual `.blend` library serialization for tree and field
backing, including recovery without a redundant owner-ID marker in the tested
structural/owner-ID route. These tests establish saved-reference and payload
retention in those routes. The focused Grade edit/recovery defects are fixed:
`mark_node_dirty()` blocks retained backing, and field restoration uses the
persistent ledger's transaction/slot metadata without the JSON marker.

Recovery still has confirmed gaps. Partial backup deletion followed by
ledger-retirement failure can strand restoration; structural and Grade snapshot
validators accept incomplete inventories; and in-place Grade field publication
lacks a durable committed marker. Stack candidate cleanup double-removes Images.
The native Stack fixture lacks owner schema. The focused recovery target has 2
failures in 34 tests, native Stack has 1 failure in 9, and installed smoke fails
during Stack setup/reopen because its fixture saves an unreferenced host tree.
Details and required regressions are in the
[handoff](CHECKLIST.md#current-audit-handoff-2026-11-01).

Packaged Blender 5.2.2 acceptance saves a partial binding-only transaction with
absent JSON and owner state `PENDING`, terminates with `os._exit(99)`, and verifies
rollback on reopening. It proves that saved fixture's recovery, not interrupted
texture uploads, `READY` with absent JSON, every swap/ledger-retirement point,
interrupted Blender serialization, power-loss durability or unsaved edits.

The reopened `.blend` or autosave is the authority after a crash. Validate actual
saved data and reconstruct unfinished derived preparations using fresh requests;
do not restore unsaved edits or replay old handles. Unsaved recovery journals
supply no authority. Preserve authored Images, committed Bakes and new-format
Undo. Explicit Image/UV Bake never
resumes automatically and retains its previous committed Image. Recovery does
not reopen the Gizmo or replay Save/Render. New bake Images receive no forced
fake user; historical data migration is outside scope.

## Native output and evidence

Accepted Save cancels unfinished explicit Bakes, resolves required physical
obligations and saves committed Images after static preparation. Cancelling the
destination/confirmation phase before acceptance does not cancel Bake or start
the Save gate; independent background preparation remains allowed. Accepted owned
confirmation enters the gate and invokes native Save `EXEC_DEFAULT` once after
preparation. The written file honors
the chosen compression value; Blender's remembered checkbox/default may differ
until reopen. No default tracking or workaround is planned.

Render invokes Blender once and holds committed Image contents/bindings for the
whole native operation, including animation-frame gaps. Dynamic input changes
still interrupt affected Bakes. Native scene animation and movie output do not
require animated Grade parameters or per-frame extension rendering.

Implementation gates progress through isolation, source-bound models/proofs,
foreground adapters, capture/preflight, static persistence,
Save/Render/Undo/Restart and installed acceptance. Independent proof gates must
bind the new source, requirements, mandatory claims, generated contracts and
shipped bytes.

Implementation must establish source-bound claims, positive witnesses, replayed
mutations, deterministic receipt interleavings and installed native acceptance.
Historical proof/test counts from the preserved product do not certify this
design. Native numerical behavior, physical completion, serialization and
grant-delivery premises must remain distinct from proved policy properties. The
eight earlier Next targets, including bounded Restart/composition ledgers,
reported 493 obligations and 27 mutations; the
unbounded kernel adds a passing receipt of 170 obligations and 4 mutations, but
production conversion correspondence and complete acceptance remain open. See
[PROOF_COVERAGE.md](../../libraries/perceptual-grade-next-core/PROOF_COVERAGE.md)
for exact boundaries and the
[handoff checklist](CHECKLIST.md#current-audit-handoff-2026-11-01) for
the passing build/test receipts and unfinished Linux/Blender acceptance.

The preserved implementation's separate scope/Bake/output/recovery machines and
Exact animation policies remain historical baseline facts, not Next features.
Historical INVARIANT/Rocq material in the sibling repository `perceptual-grade-proof-archive`
also supplies no Next acceptance; retained evidence applies only to its recorded
source and premises.
