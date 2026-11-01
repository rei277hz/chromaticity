# Next proof coverage and adapter boundaries

Updated: 2026-11-01

The canonical requirements are in
[STATE_MACHINE_DESIGN.md](../../products/perceptual-grade-next-blender/STATE_MACHINE_DESIGN.md#13-expressible-proof-obligations-and-external-premises).
This inventory records their implementation boundary. A passing proof target
certifies its named source functions and assertions, not every canonical family
whose subject resembles that model. Native observations, resource contents and
Blender serialization remain adapter evidence.

`//:verify_next` includes `:verify_extended`, the canonical inventory validator
and the Next extension package. `project_unbounded_proof` is wired into the core
runtime's generated contracts and verification dependencies and now passes
**170 obligations and 4 mutation checks**, build
`e458d854-a0f2-474f-9ee4-e903e6da13b7`. This certifies `project_unbounded.py`;
production record alignment/conversion in `project.py:251–318` is outside that
proof. No fresh passing aggregate proof/package receipt is recorded. The
preparation/recovery policies and `composed.py` remain smaller specification
models with no production call sites: their historical proofs do not establish
adapter equivalence or actual production composition.

The canonical inventory contains **60 IDs: 43 partial, 11 adapter premises and
6 open, 0 proved**. Six inventory tests passed in the latest audit, as well as
the earlier build `980c3184-ac08-4aa6-9abe-cb5fa9793d68`. They check exact ID coverage, property and
target references, evidence paths and explicit gap declarations. They are
consistency tests, not proof-result validation. Ten `.inv` files exist but only
nine proof targets; the orphan `scope_view.inv` remains invalid and unproved.

The previously reported **493 obligations and 27 detected/replayed mutations
are historical, not current aggregate coverage**. Source and inventory changes
require fresh receipts. Except for the unbounded kernel row, the counts below
identify earlier evidence; they must not be summed into a claim that the current
checkout passes aggregate verification.

| Target | Obligations | Mutations |
| --- | ---: | ---: |
| preflight | 87 | 3 |
| scope | 77 | 4 |
| project owner/readiness and receipt predicates | 93 | 9 |
| unbounded project owner/readiness kernel (fresh receipt above) | 170 | 4 |
| foreground | 41 | 3 |
| preparation policy | 60 | 1 |
| recovery policy | 37 | 1 |
| Restart | 43 | 3 |
| composition | 55 | 3 |

The historical preserved-core output proof separately reports 287 obligations
and 5 mutation controls; it is not part of the Next aggregate and does not
certify Next adapters.

## Canonical scope inventory

| ID | Checked implementation boundary | Remaining requirement |
| --- | --- | --- |
| S01 | Foreground close hides, advances epoch and revokes issued display; `ViewAuthority` uses the proved transition | Installed close during native faults |
| S02 | Cancelled completion cannot replace accepted input | Full resource/service cancellation protocol |
| S03 | Scope receipts bind generation, owner and submission; adapter freezes original submission identity | Every native request/resource incarnation and grant |
| S04 | Begin requires current demand, a fresh submission, no cancellation and no playback | Late native read grants and pre-granted work |
| S05 | Matching physical retirement consumes debt once | Producer terminal-read-once protocol |
| S06 | Foreground display adoption consumes an issued receipt once | Preview input occurrence consumption |
| S07 | Begin cannot repeat an already begun demand | Native control-acknowledgement protocol |
| S08 | Scope issue/application requires current accepted input; foreground separately requires exact view/token receipt | Complete staged analysis/visual/native adoption composition |
| S09 | Installed Scope capture exercises histogram, waveform and vectorscope payloads from one viewport sample set | A canonical exact statistics-to-visual payload equality property |
| S10 | Not represented by scalar scope/view models | Primary/reference/environment batch coherence |
| S11 | New demand retains old physical debt; old completion cannot accept new input | Complete delayed native batch settlement |
| S12 | Cancellation retains physical retirement debt | Handles returned during cancelled submission |
| S13 | Close distinguishes no physical work from retirement | All native resource and reader obligations |
| S14 | Not represented by scalar scope/view models | Retained older batch references |
| S15 | Playback blocks demand/begin/display and revokes old display tokens; installed acceptance observes a keyframed Shader RGB input, no acquisition/publication during playback and a fresh visual for the final stopped frame | Animated Grade-control evaluation and broader playback/resource interleavings |
| S16 | Not represented by scalar scope/view models | Complete live-service/wait/failure reasons |
| S17 | Failure binds exact physical submission | Per-component failure isolation |
| S18 | Not represented by scalar scope/view models | Compatible progressive batches versus newer demand |
| S19 | Not represented by scalar scope/view models | Native service-incarnation failure identity |

The mandatory `scope_proof` and `foreground_proof` inventories name the exact
assertions above. Descriptive helper names deliberately avoid assigning S09 or
S10 to token/owner checks, which do not prove statistics or batch coherence.

`requirements/scope_view.inv` proposes five joint scope/view properties for
rejection, issue, apply, close and transfer. It has no Buck proof target and no
proof receipt. It also omits the required `invariants` key;
`validate_requirements` requires a nonempty invariants mapping, so merely adding
a target would still leave this inventory invalid. Its proposed joint-policy
checks do not yet prove the production adapter's analysis/visual association or
native resource transport.

## Project, preparation and recovery inventory

| IDs | Checked implementation boundary | Remaining requirement |
| --- | --- | --- |
| J01–J03 | Project tests exercise Save/Bake exclusion and Render holds; proved production predicates require invoked Save/Render and exact terminal receipts | Whole production project transition proof and native ticket transport |
| J04–J06 | Project/publication tests exercise destination ordering, cancellation, packed Image rollback and cleanup after injected recovery-Image pack failure | Complete physical lease conservation and native partial-effect interleavings |
| J07 | Unbounded kernel proves repair-debt exclusion; Grade/Stack admission rejects both retained-ledger forms | Checked production conversion, complete native admission and recovery interleavings |
| J08 | Four-slot project predicates reject stale Bake/Save/Render completion and receipt reuse | Exact adapter operation identities and native retirement remain external premises |
| T01 | Arbitrary-length owner coverage is proved in `project_unbounded_proof`; production calls the kernel for every owner count | Checked conversion of production records and Blender source projection |
| T02 | Unbounded revision/evaluator properties pass; native accepted manifests bind graph/image content | Production conversion and complete descriptor/manifest-to-native correspondence |
| T03 | Project readiness validates current owners; preparation policy proves staged candidates cannot be ready before commit | Source-bound matrix and binding/content completeness |
| T04–T06 | Product tests cover changed revisions, immutable payload reuse and static controls; policy rejects stale revisions | Complete reuse/fresh-authority/static-frame composition proof |
| T07–T08 | Packed Grade-field and Image backups retain real ID references and digest readback; readiness and edits reject retained debt | Partial cleanup can lose required backups; snapshot inventories and the durable in-place commit marker remain incomplete; broader crash/autosave acceptance is open |
| T09 | Grade adapter uses one complete forward native graph and fixed helper fields; native Grade tests cover installation | Formal descriptor-to-graph/content correspondence |
| T10 | Stack tests cover 33³/65³ quality and exact even-vertex reuse | Formal numerical lattice/content proof |
| T11 | Independent reference tests cover directed Stack equations and endpoint order | Formal numerical inverse/recipe proof |
| F01–F03 | Project receipt predicates distinguish invoked/committed output; packed readback validates actual assets | Full asset/output/serialization boundary composition; flags never prove disk serialization |
| F04–F06 | Recovery tests cover authored reconstruction, false-ready/missing metadata, invalid backing and fresh queueing; policy proves fresh generation/no replay | Installed crash/Undo/load idempotence and exact resource ownership |
| F07–F08 | Recovery discards explicit operations; packaged UV and Compositor tests exercise registered Bake poll/execute with the native Grade evaluator; Shader failure tests remove implicit targets and preserve selected targets | Native reader retirement, concurrent destination ordering and whole workflow proof |
| R01–R04 | Production Restart uses proved generation/phase/cleanup ledger; reverse-order adapter traces, failed receipt/retry tests, installed idle Restart and injected recovery-failure retry pass | Installed preservation during active work, detach/replacement and late native handles across failure |
| B01–B07 | Preflight proves exact active-check completion, closed-owner fencing, failed-source Retry and equal-observation stability | Complete native route/source readiness and monotonic-attempt composition |
| B08 | Project/readiness tests reject Stack preview for Bake/final admission | Source-bound production owner-artifact worklist proof |
| U01–U02 | Settings/control tests compare reference metadata and supported Fit domains | Formal UI/native persistence correspondence and installed acceptance |

The local preparation and recovery assertions use descriptive names rather
than canonical T/F IDs. A distinct candidate identity does not establish a
forward Grade graph, an opaque validation flag does not establish 33³/65³
content, and a queued recovery does not establish a completed publication.
Structural replacement backing has real prior/candidate tree references and a
serialized snapshot of external links, defaults and metadata; native tests
cover restoration, committed-candidate retention, failed compensation, and
library write/load. Grade-field backing also survives library serialization.
Recovery regressions cover unresolved-ledger edit blocking and restoration when
the redundant JSON marker is missing. The previously reported `recovery` run
passed 26 tests; that count is historical. The latest run has 2 failures among
34 tests, native Stack has 1 failure among 9, and installed smoke fails during
Stack setup/reopen. Grade boundaries reached before that failure do not make
the whole installed target pass. See the
[audit handoff](../../products/perceptual-grade-next-blender/CHECKLIST.md#current-audit-handoff-2026-11-01) for runtime
defects, Stack fixture corrections and the remaining saved-interruption matrix.

The historical four-slot project proof reports 93 obligations and 9 detected/replayed
mutations. It includes the exact `bake_completion_matches`,
`save_completion_matches` and `render_completion_matches` predicates called by
the production project transition. It also proves owner admission and readiness
for an ordered scalar-slot worklist of at most four owners. The proof state has
four fixed readiness/artifact slots; unused slots are padded empty, and
evaluator/manifest identities are represented by presence bits. Exact identity
binding remains enforced by the production artifact matcher, outside this
kernel. Four owners are a legacy proof-model limit, not a product owner-count
limit. Production `project_ready` now calls the unbounded kernel for every
owner count; `project_proof_state` remains a separate legacy projection.
`project_unbounded_proof` establishes all-owner coverage, current artifact
revision/evaluator identity and repair-debt exclusion for its arbitrary-length
input. Production `_all_owners_ready_unbounded` validates and aligns the source
records before constructing that input; its `align`/`align_ids` logic and tuple
conversion are not covered by the proof target. A five-owner Blender regression
provides adapter evidence, not that missing correspondence theorem. Blender
discovery, native content and actual admission also remain outside the kernel.
Neither project model proves the entire preparation, destination or recovery
workflow.

The historical bounded owner worklist assertions require an accepted open to preserve the
exact owner and evaluator slot order and validate each owner/evaluator pair;
duplicate, empty, unsupported, unpaired or over-bound worklists cannot be
accepted by the bounded model. Readiness requires one current artifact per
required owner, matching evaluator, nonempty evaluator and manifest identities,
and no repair debt. Save and Render start assertions require that complete
readiness. These are source-bound kernel results, not proof of the Blender
adapter's extraction and projection.

The proved unbounded `ReadinessState` kernel is separate from the historical
four-slot `ProjectState` projection. Its canonical mapping is:

| Canonical ID | Passing kernel property in `project_unbounded_proof` |
| --- | --- |
| T01 | `T01_unbounded_worklist_covers_every_owner` |
| T02 | `T02_unbounded_artifacts_match_revision_and_evaluator` |
| T02 | `T03_unbounded_artifact_evaluator_matches_required_owner` |
| J07 | `J07_unbounded_repair_debt_blocks_readiness` |

The property named `T03_unbounded_artifact_evaluator_matches_required_owner`
supports canonical T02's evaluator binding; it does not prove canonical T03's
staged-candidate publication rule. The crosswalk retains T01, T02 and J07 as
partial canonical coverage because production record conversion, Blender owner
discovery, native payload correspondence and Save/Render/Bake admission are not
proved by this kernel.

The earlier quantified-summary, lookup-precondition and circular-mutation
blockers were repaired for this kernel. The fresh receipt discharges 170
obligations and 4 independent mutation checks; Invariant's 57 focused tests also
pass. A complete fresh preserved/Next aggregate receipt after the shared verifier
changes remains required.

Induction is sufficient for an arbitrary finite owner list. The passing kernel
uses this argument; production conversion needs its own checked correspondence:

1. Establish the exact verified-prefix invariant at cursor 0, including the
   empty worklist case and all admitted tuple-shape/uniqueness premises.
2. Prove one iteration preserves it when advancing from cursor `k` to `k + 1`,
   with helper results scoped to that iteration and all helper preconditions
   discharged.
3. At loop exit, derive that the verified prefix is the entire worklist and
   gives exact owner/revision/evaluator/artifact/manifest coverage. Mutations
   must be checked against independent assertions of that rule.
4. Prove termination using the nonnegative decreasing measure `n - k`.

Production now uses one arbitrary-length readiness predicate for all owner
counts. Proving the projection from immutable production records to its input
remains open. The four-slot path may retain historical evidence but must not
become a separate authority whose correspondence is assumed. Compose
the actual production scope/view/gateway and project admission transitions for
cross-machine claims; a reduced illustrative machine alone cannot establish
their behavior.

The Blender readiness adapter now rejects both ledger forms for Grade and Stack
and compares actual graph/image records with accepted manifests. Grade acceptance
also compares field pixels with the live controller's prepared contents. Ordinary
admission checks the accepted record without regenerating the reference model.
These changes retire the earlier JSON-only and identity-only findings. Complete
production correspondence and installed coverage remain open. Partial backup
deletion, incomplete recovery snapshot inventories, missing in-place commit
markers and Stack duplicate disposal are concrete implementation defects; they
cannot be treated as external premises that are assumed correct.

## Selected readiness and recovery milestone

The [implementation step](../../products/perceptual-grade-next-blender/READINESS_RECOVERY_STEP.md)
selects recoverable Grade/Stack preparation and trustworthy admission as one
complete delivery. The following acceptance requirements remain binding. The
kernel portion now passes; the production correspondence and complete native
acceptance portions remain unfinished. Next Blender temporarily opts into
[`unsafe_runtime` for development](../../products/perceptual-grade-next-blender/README.md#temporary-development-build);
restore the normal core dependency before treating a package as satisfying the
proof gate below. Full verification still includes the unbounded proof.

- Keep the unbounded proof and generated validators mandatory in runtime,
  package and verification dependencies. Reject summarized or loop-lowered
  helper calls beneath `forall_range`, `exists_range` and `sum_range`, including
  indirect calls and nested binders, unless their binder scope is soundly
  represented. Preserve directly inlined loop-free helpers and their safety
  obligations. No binder-dependent helper or arithmetic assumption may escape
  its quantifier. Regression evidence must include the shared verifier and
  affected preserved proofs.
- Retain an arbitrary-length `ReadinessState` contract and prove one production
  readiness path for every finite owner count. Use total first-match lookup,
  direct quantified field relations and a decreasing prefix proof; establish
  the conversion from immutable production owner/evaluator/artifact records.
  Cover empty, reordered, duplicate, missing and malformed worklists. The
  historical four-slot model must not remain a second admission authority.
- State expected owner coverage, revision/evaluator equality, nonempty artifact
  and manifest identities, and repair-debt exclusion independently of the
  helpers under mutation. Require non-vacuous witnesses and detected mutations
  replayed in ordinary Python; neither a shared weakened helper nor additional
  solver time supplies the intended theorem.
- Connect the decision to actual Grade/Stack creation, updates, recovery,
  Save/Render admission and native Bake binding. Native texture/graph inspection
  and Blender serialization remain explicit adapter evidence. Required tests
  cover retained backing despite absent JSON or `READY`, unchanged IDs with
  changed contents/bindings, failed compensation, malformed snapshots and the
  named saved crash/reopen boundaries. Keep Stack's stable recipe identity
  separate from the exact final LUT/graph manifest so preview refinement can
  preserve a waiting request while capture still requires current 65³ output.

A passing helper proof alone does not complete this milestone. It requires the
production correspondence, adapter and installed Linux/Blender evidence named
in the implementation step, followed by fresh proof/package receipts. It does
not certify complete Scope/view/statistics transport, Restart under every
interleaving, native reader retirement or the reduced `composed.py` model's
correspondence to all production transitions. Those broader requirements remain
open in this inventory.

## Composition and external premises

The composed model checks generation fences, independent view closure,
publication holds, physical retirement and Restart cleanup. Runtime adapter
traces independently exercise the same relationships. Neither substitutes for
authentic Blender operation IDs, native completion, serialized ID retention or
evaluated pixel correctness. Restart has at most four cleanup categories in the
current adapter (scope, preparation updates, Bake, output); its proof uses that
explicit bound and accepts receipts in any order.

Native scope capture now has installed viewport-pixel statistics and
histogram/waveform/vectorscope pages. Installed frame acceptance verifies that
a keyframed Shader RGB input changes captured statistics, then verifies a
stopped-frame recapture, no new acquisition or visual adoption while playback
runs, and a fresh visual for the final stopped frame. Scope selects a
last-observed VIEW_3D area per window with a largest-area fallback and fences old
captures after transfer. Viewport source identity normalizes inactive studio
lighting controls by shading mode; full immutable environment snapshots and
coherent primary/reference batches and installed close-during-fault acceptance
remain open. Installed Shader UV and Compositor Bake exercise the registered
operator's poll/execute and check native output/publication, but reader retirement,
concurrent destination ordering and broader route interleavings remain open.
Broader crash/Restart interleavings remain open beyond the recorded Grade
forced-exit/reopen and injected recovery-failure retry cases. The four agreed
File/Render menu entries are intercepted; direct native operator/script calls
remain outside the gate. Required claims in those
areas remain required; they are not certified by the aggregate build or by old
implementation evidence. The active worklist, exact current checks, recovery
status and chosen Linux/Blender delivery boundary are recorded in the root
[CHECKLIST handoff](../../products/perceptual-grade-next-blender/CHECKLIST.md#current-audit-handoff-2026-11-01).
