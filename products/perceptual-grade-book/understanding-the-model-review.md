# "Understanding the model" vs `perceptual-grade-reference`

Scope: the seven chapters of PART "Understanding the model"
(`docs/book/src/theory/*.md`) plus the guide chapters and
`development/forward-inverse-math.md` sections that state the same equations.
Reference baseline: `libraries/perceptual-grade-reference` at 2026-10-28
(rev 11), the authoritative analytic model.

Verdicts: **matches** · **stale** (true of 1.23.2, not the reference) ·
**contradicts** (asserted as the model, false for the reference) ·
**absent** (reference behaviour the part does not describe).

---

## 1. The structural divergence: Stage 3 is a different design

This is the finding that matters. It is not a set of stale constants; the
reference replaced the whole Stage-3 operator set.

| Book location | Book says | Reference does | Verdict |
|---|---|---|---|
| `theory/color.md:44-53`, `forward-inverse-math.md:457-473` (§6.3) | Hue Concentration: two-component control in a disk of radius 0.6, `w = tanh(‖v‖/.6)/(‖v‖/.6)·v·C²/(C²+4)`, Möbius circle map | No Concentration. `ColorSettings` (`grading.py:34-50`) has no concentration field; `src/README.md:1691` — "remains in DCTL only" | **stale** |
| `theory/color.md:56-64`, §6.4 | Adaptance strength `α ∈ [0,1]`, `r(C)=.25+.75/(1+(C/30)²)`, `f=H/100·αr/(1-α+αr)` | Selective cone Adaptance: direct neutral a/b destinations (4×2), `adaptance_half_saturation ∈ [.05,1]` default `.25` (`selective_adaptance.py:98-107`), cone-gain response law | **stale** |
| `theory/color.md:70-80`, §6.4 | Hue = tonal Hue curve `θ₀(H)` + global low/high-chroma hue `θ_ℓ,θ_h` | Web `hue_degrees` 4×6 corner field, quintic Bézier sectors, `S₅ = 6t⁵−15t⁴+10t³` (`src/README.md` §"Corner targets…") | **absent** |
| `theory/color.md` (whole gain section), §6.2/6.4 | Chroma = `2^(g+Δlog₂C)` from four tone rows | Web `log_chroma` 4×6 with radial law `A(C)=(1+(C/τ)^4)^-1/4`, `F(C)=C[g+(1-g)A(C)]` | **absent** |
| `theory/color.md:83-86` | `u₃ = f·A(H₂) + 2^{g+Δlog₂C} R_θ u_f`; ends at Adaptance | + final positive scale λ (`log_scale` 4×6), applied after Adaptance: a/b ×λ, energy ×λ² (`src/README.md` §"Geometry, controls and evaluation order") | **absent** |
| `theory/color.md:86` | "The defined composition applies concentration, radial gain and rotation, then adds Adaptance" | lightness/chroma → web hue warp + radial chroma → selective Adaptance → final λ | **contradicts** |
| `theory/color.md:31` (fix this) | carried from encoder through Tone | additionally `E₀ = J_A|J_A|`, `h = √(|E₀|+66C)` frozen post-Tone for web and Adaptance | **absent** |

Consequence for anyone reading the part: they cannot implement the
reference's Stage 3 from it, and the controls they would build
(Concentration, Adaptance strength, global low/high Hue) do not exist in
`ColorSettings`.

Controls that do survive unchanged: `lightness` (4×4), `chroma` (4×4),
`lightness_fit`, `chroma_fit`, `global_gain`, and the tonal coefficient
curve machinery itself.

---

## 2. Sign conventions and the driver law

| Book location | Book says | Reference does | Verdict |
|---|---|---|---|
| `theory/color.md:26` | `q_s = C²/(C²+(35/75)²J_A²)` | `CHROMA_CROSSOVER=35./75.` (`grading.py:19`), `r=CHROMA_CROSSOVER·abs(ja)` (`:264`) | **matches** in the squared form, but silent on the sign |
| `forward-inverse-math.md:400-425` (§6.2) | "For \(J>0\) define ω…"; crossover derivation assumes positive `J` | `abs(J_A)` deliberately, for signed symmetry; 1.23.2 used `max(J_A,0)` (`src/README.md` §"Analytic Stage 3 J_A/C crossover", `generators/legacy/model/color.py:69`) | **contradicts** by omission — the two conventions differ for `J_A<0` |
| `theory/structure.md:18` | `H = J_HK = √(J_A²+66C)` unconditionally | `signed_hk` (`responses.py:49-57`): for `J_A<0`, `H = 2√(66C) − hypot(J_A, √(66C))` | **contradicts** |
| `theory/color.md:26` (`V=C²/(C²+4)`), `:28` opponent terms | visibility `V=(C/hypot(C,2))²`, `(a,b)/hypot(C,2)` | identical (`grading.py:242-256`) | **matches** |

Recommended text: state `r = (35/75)·|J_A|` explicitly, note that the
1.23.2 DCTL and shared production kernels still use `0.4·U(J_A,h)` and that
the reference rejects nonzero low/high controls (see §4 below), and qualify
`H²=J_A²+66C` to `J_A ≥ 0` with the signed reflection given.

---

## 3. Numbers and constants

| Book location | Book says | Reference does | Verdict |
|---|---|---|---|
| `theory/tone.md` (Tone), `forward-inverse-math.md:290` | Shadows target `ν(.037153526983·R_w)` → 7.542 nits | `LOW_Y = 0.015507796089266005` (`grading.py:17`) → 3.148 nits | **stale** |
| `forward-inverse-math.md:164-176` (§4.1) | `R_w = max(48, min(1000, ⌊R+.5⌋))` | `smooth_cap(smooth_floor(R,48),1000)` (`grading.py:155`) — continuous, no rounding | **contradicts** |
| same | `P_w = max(2R_w, min(10000, ⌊P+.5⌋))` | `smooth_cap(smooth_floor(P, 2R_w), 10000)` (`:156`) | **contradicts** |
| `theory/structure.md:28` | "background luminance 20.3 nits" | `Y_b = 10.` (`appearance.py:26`) | **contradicts** |
| `theory/structure.md:28` | `c = 0.525`, `N_c = 0.8`, `−0.1475 sin h` | Hellwig-2022 dark surround + `eccentricity_factor` (`responses.py:6`) | **matches** |
| `forward-inverse-math.md:181-190` | `γ = .943019577159`, `A_w = 3.05ρ(1)`, pole at 400 | `GAMMA = c·(1.48+√.1)` = 0.94301957715884, `B = 400.` (`responses.py:20-22`) | **matches** |
| `theory/lut.md:7-18` | input domain `0…128`, `R=128`, `A=ln(1+R/κ)`, `κ=.01` | `MAXIMUM=1024`, `KAPPA=.01` in core (`lut.py:25-26`), next (`kernel/lut.py:15-16`), and the export guard (`cube_guard.py:12`) | **stale** |
| `theory/lut.md:7` | "64 positive intervals", `65³`, `33³` preview | unchanged (`lut.py:18-19`) | **matches** |
| `theory/lut.md:61-70` | tetrahedral difference form `v₀+f₁(v₁−v₀)+…` | same difference form, fused multiply-adds | **matches** |
| `theory/lut.md` (end) | "Direct uses 2048 intervals per tonal basis curve" | `MAX_CELLS=2048` (`tone_table.py:12`) is a refinement **cap**, not a stored count; observed tables are 4–67 cells. No Stage-3 basis table ships at all | **stale** — corrected in the chapter |

Recomputing the address curve: with `MAXIMUM=1024`, `κ=.01`,
`A = ln(1+1024/.01) = ln(102401) ≈ 11.53645`, and
`x_i = κ·(e^{A·i/64} − 1)`. The chapter's formula shape is right; only the
bound changes.

---

## 4. Missing mechanisms

| Location | Missing | Reference | Verdict |
|---|---|---|---|
| `theory/hk-guard.md` §"Carry energy into decoding", end | **export cube guard**: fixed-`J_A`, fixed-hue projection onto native AP1 `[0,1024]³`, real decoder validation, `FLOAT64_STEPS=56` | `release_state(guard=True)` = H–K repair **then** `cube_guard` (`model.py:223-233`, `cube_guard.py:12-13`) | **absent** |
| same | A LUT samples the *complete guarded transform*; the cube guard is not part of the pad geometry | `src/README.md` §"Blender pad, plots and verification" | **absent** |
| `theory/color.md` | the reference rejects nonzero low/high lightness/chroma controls in `BakeStack` before preparation | `src/README.md` §"Analytic Stage 3 J_A/C crossover" | **absent** |
| `theory/structure.md` (scope) | the analytic reference accepts **only** `white='D65'` and `reference_nits=203` (`model.py:129-131`); eight whites are a product/core feature | `model.py:129-131` | **absent** |
| `theory/structure.md` (viewing) | reference `L_A = .1·R_w`, `Y_b=10`, `XYZ_w=100·white`, `discount_illuminant=True` | `appearance.py:24-27` | **matches** (already correct in §4.1) |

---

## 5. Editorial defects

| Location | Defect | Fix |
|---|---|---|
| `theory/hk-guard.md:58` | cites `src/dctl/hk_guard.dctlh`, `src/blender/model/color.py`, `src/blender/graph/color.py` — none exist. DCTL src is `boundary/core/foundation/inverse/math/overlay`; Blender `src/model/` holds only `bake_gpu.py` | point at `libraries/perceptual-grade-reference/src/{responses,hk_guard*}` and the current DCTL/Blender module paths; or drop paths and cite the library |
| `theory/evaluation.md` (9 lines) | no equations; only forwards to the guard and LUT chapters | supply the chain: Stage 3 → H–K repair → cube guard → sampled/baked evaluation, with the "sampler agreement ≠ analytic approval" distinction |
| `forward-inverse-math.md:12-24` (§1) | source contract lists legacy `model/*.py` and `graph/*` paths as the inspected source | add a line that the reference library supersedes these for the model equations |
| `theory/color.md:1-11` | presents the coefficient matrix as *the* Stage-3 design | reframe: coefficient curves + drivers are shared; the receivers are the web and selective Adaptance |
| `zh-Hans/theory/{linear,structure,tone,color,hk-guard,evaluation}.md` | one line each — heading only. `tools/site.py:370` forbids English fallback, so the shipped zh edition has six heading-only chapters in this part | translate after the English is settled |

---

## 6. Verified correct (do not "fix" these)

Checked by arithmetic, not by reading:

- **Tone saturation preservation is exact.** Book: `J_{A,2}=√(H₂²+(33k)²)−33k`,
  `C₂=kJ_{A,2}`. Reference `Tone.apply`: `gain = 2h²/(hypot(66C, 2J_A·h)+66C)`.
  Agreement ≤1.8e-14 across `(J_A,C) ∈ {(50,20),(10,40),(100,60),(5,1)}` ×
  `H₂ ∈ {20,50,100}`. Two different algebraic forms of the same rationalized root.
- **Tonal coefficient curves.** `knots = smoother(target/target[-1])`, width
  `.05·2^-Fit`, sequential `min(previous, clamp(U,0,1))`, Adaptance taking
  `U₀−U₁` and fading at black — all present verbatim in
  `grading.py:131-151`.
- **H–K guard.** `theory/hk-guard.md`'s worked example reproduces exactly
  (requested H=50, C=80, reference H=50 C=20 → H=58.188, C=48.142) from
  `LIFT=.20`, `ALLOCATION=.44`, `delta/(1+4t+10t²)^{1/4}`. The archived 1.4.0
  table in the same chapter reproduces the *older* `p=1` retain-C branch
  (58.020, 50.527) and is correctly labelled historical.
- **Stage 1.** `M_CAT = A⁻¹diag(AW_d/AW_s)A` is algebraically the reference's
  `I + A⁻¹diag(ratios−1)A`; the 30%-of-displacement Rec.709 anchors,
  `2^{-balance}` gain and white-fixing basis `[W_d V_r V_b]` all match
  `model.py:linear_matrix`.
- **Appearance encoding.** `H²=J_A²+66C` on the nonnegative branch, `C=√(a²+b²)`,
  `h=atan2(b,a)`, `1204·eccentricity/aw`, the `−.1475 sin h` term, and the
  400-pole response all match.

---

## 7. Recommended disposition

The part is a correct account of the **1.23.2 production model** and a
partly-incorrect account of the **reference model**. Rather than rewrite the
part wholesale, split it:

1. Keep `structure.md`, `tone.md`, `hk-guard.md`, `lut.md` — they are right
   about shared machinery and need only the constant/sign corrections in §3,
   the `H` reflection in §2, and the cube guard in §4.
2. Rewrite `color.md` around the reference's Tonal Web + selective Adaptance +
   final scale, and demote Concentration / Adaptance-strength / global
   low-high Hue to an explicit "1.23.2 DCTL controls" subsection.
3. Fill `evaluation.md`.
4. Move `forward-inverse-math.md` §4.1, §5.1, §6.3, §6.4 in lockstep — they are
   the deep-math counterpart and will otherwise contradict the part.
5. Translate the six stub Chinese chapters.

Add one paragraph at the top of `structure.md` naming which model the part
describes and where it departs from 1.23.2, so an intentional legacy
statement is never mistaken for a stale one.

---

## 8. What was applied

All items in §7 are done in this working copy:

| File | Change |
|---|---|
| `docs/book/src/theory/structure.md` | Scope paragraph naming the model and the 1.23.2 departures; `H²=J_A²+66C` qualified to `J_A≥0` with the `2b−√(J_A²+b²)` reflection; `Y_b=10` corrected; D65/203 reference scope added; the two lightness coordinates separated |
| `docs/book/src/theory/tone.md` | Gain form `g=2H₂²/(hypot(66C,2J_A H₂)+66C)` added alongside the quadratic root; `Λ_low=0.015507796089266005` (3.148 nits) with the 1.23.2 value named; smooth `floor`/`cap` effective reference and peak replacing integer rounding |
| `docs/book/src/theory/color.md` | Rewritten: `(35/75)|J_A|` with the sign convention and the 1.23.2 `max(J_A,0)` contrast; direct lightness/chroma rows; tonal web radial and angular laws; selective Adaptance with neutral destinations and half-influence mask; final scale; four-step evaluation order; legacy controls section retaining Concentration, Adaptance strength and global low/high hue, with the concentration figure |
| `docs/book/src/theory/hk-guard.md` | Dead source paths replaced; export cube-guard section added (H–K repair → decode → AP1 `[0,1024]³` bisection with capacity seed); explicit non-invertibility of the projection |
| `docs/book/src/theory/lut.md` | Domain `0…128` → `0…1024`, `A≈11.536652`, halfway-address figures, 207,872 nits at 1024; study reframed as a recorded measurement rather than the current table |
| `docs/book/src/theory/evaluation.md` | Filled: four distinct steps after the coefficients, the model-versus-approximation split, current-parameters and stale-table rules |
| `docs/book/src/development/forward-inverse-math.md` | §4.1 smooth effective reference/peak; §5.1 `Λ_low`; §6.2 `|J|` in the classifier with the convention warning; §6.3 relabelled as the 1.23.2 path (sections 10–18 invert it); new §6.5 giving the reference stage equations |
| `docs/book/src/development/contributing-model.md` | Two model homes named; §6.3/6.4 versus §6.5 identified |
| `docs/book/zh-Hans/theory/*.md` | All six heading-only chapters written; `lut.md` domain corrected. Numeric tokens now match the English chapter in every theory page |

Not done, and why:

- `docs/book/zh-Hans/development/forward-inverse-math.md` (163 lines) and
  `testing.md` still describe the 1.23.2 stage and are not reconciled with §6.5.
- `guide/color.md` continues to teach the 1.23.2 controls. That is correct for a
  1.23.2 handbook but now sits across a scope note from the rewritten part.
- `docs/book/src/development/forward-inverse-math.md` §10–18 invert the 1.23.2
  stage only; a reference-model inverse section is not written.
- The Lean theorem count discrepancy noted while reviewing (`proofs/README.md`
  says 571; a direct count gives 572) is unverified and untouched.

Verification performed: every numeric example recomputed with `python3 -I`
(H–K worked example, the archived 1.4.0 table, the tone quadratic versus the
gain form, `A` and the vertex addresses, `1024×203`, both Shadows constants);
`$$` delimiter balance checked in all edited chapters; English and Chinese
chapters compared token-by-token for matching numbers. No test, proof, lint or
format run, per `AGENTS.md`.
