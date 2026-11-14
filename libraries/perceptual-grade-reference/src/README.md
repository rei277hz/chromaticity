# Independent mathematical reference

The standalone package is `color_tools.perceptual_grade_reference`, built by
`//libraries/perceptual-grade-reference:runtime`. Its JSON CLI is
`//libraries/perceptual-grade-reference:evaluate`.

The reference retains its Colour-based appearance adapters and independent
production-correspondence equations. Shared portable kernels have one canonical
home in `color_tools.perceptual_grade_core.model`; both models import those
kernels normally. They are not duplicated or rebased into another package.
Agreement on a shared algorithm is not independent evidence of its correctness:
properties, external mathematical anchors and scoped proofs provide additional
evidence. The reference passes its own appearance encoder and response semantics
explicitly to shared tonal-web and selective-adaptance kernels.

No Blender package is required by the reference target. GPU experiments can
inject `BakeStack(..., program_factory=...)`; without a factory, GPU preparation
uses the optional reference-owned Blender adapter. Host GPU imports are lazy.
The reference owns the CPU kernel and forward/inverse/boundary shader builders.
CPU evaluation and the CLI do not load a host or discover another product.

## Current Warp ordering (2026-11-11)

The reference evaluates J/C edits → Warp hue/chroma → selective Adaptance →
H–K repair → common positive J_A/chroma Scale. The repair uses frozen
post-Tone reference energy. Scale is still selected from the web state before
Adaptance; moving repair does not change that selector. RGB export applies
only cube containment. Appearance handoffs already include repair and Scale,
and inverse searches evaluate this same complete forward map.

For a repaired point with energy E and chroma C, Scale k>0 sends
(a,b,E) to (ka,kb,k²E). Its compact pad coordinate
(a,b)/sqrt(C²+|E|) therefore stays fixed. With E,C≥0, its H–K height is
sqrt(k²E+66kC), which increases strictly for every nonblack point. The
nonnegative-H repair branch has E≥0, including zero-reference degeneracies;
H>0 and positive reference energy imply E>0. H<0 retains the existing bypass
and black RGB export policy, so positivity is not asserted for that branch.
Cube projection can change chroma after these appearance-space guarantees.

`Model.grade_state` returns a plain `State` after this Stage 3 sequence.
`release_state(state, guard=True)` adds cube containment only, with no saved
reference-energy parameter. `pre_repair_warp_state` and
`pre_repair_warp_targets` expose the signed request after Adaptance and before
repair/Scale for diagnostics. `warp_state`, `warp_targets` and their
`guarded_warp_*` aliases return the corrected final appearance without a second
repair. `hk_guard=False` remains an explicit unrepaired diagnostic mode.

The frozen `products/perceptual-grade-blender` implementation retains its
historical Scale-before-repair behavior and UI compensation described below.
`products/perceptual-grade-next-blender` has not implemented Warp yet; its
future implementation should follow this corrected reference. DCTL and shared
production kernels retain their existing contracts. Historical step reports
and validation records below describe their original implementations.

## Analytic Stage 3 J_A/C crossover (2026-10-28)

The analytic reference's low/high chroma drivers use raw post-Tone coordinates
with `r = (35/75)*abs(J_A)`. Their visibility is `V = C²/(C²+4)` and their
responses are `low = V*r²/(C²+r²)`, `high = V*C²/(C²+r²)`. Ratios are scaled
before squaring. Neutral and black drivers are zero; chromatic `J_A=0` has
`low=0, high=V`. The 50/50 crossover is `C=(35/75)|J_A|`, independent of hue,
RGB gamut, viewing-boundary capacity and achromatic sign. Opponent drivers
remain `(a,b)/hypot(C,2)`; all four drivers are sampled once after Tone.

The available historical 1.23.2 source confirms the remembered 35/75 ratio.
That source uses `max(J_A,0)`; this reference deliberately uses `abs(J_A)` for
signed symmetry. `drivers(q, ja)` has no capacity argument. Float64, scaled
arithmetic, analytic Model/inverse/Stack and CLI follow this law.

Shared production CPU/GLSL kernels and the frozen Blender/DCTL products
retain `.4*U(J_A,h)` membership. Reference-owned `BakeStack` kernels use the
35/75 law in CPU and GLSL, including nonzero low/high lightness and chroma
controls. Explicit legacy-capacity adapters exist only in verification support
for retained-product tests and offline analysis.

The new crossover is checked by its direct algebra and numerical tests. The
existing `.4U` Lean driver theorems certify the retained production law; they
do not formalize the new 35/75 law. Stage 1/2 and the general reference Fit
domain remain unchanged. The separate native node runtime uses the supported
fixed D65 / 203-nit viewing context, accepts Tone Fit `[-2, 2]` and uses its
current 256-cell table (layout schema 5, packed in a 512 × 1 RGBA32F image);
its Color lightness/chroma Fits remain `[-2, 6]`.
These operational limits do not restrict the analytic reference's finite-Fit
mathematical domain.

## Warp and selective Adaptance

The reference and frozen Blender product use tonal-web geometry with one
Adaptance center and six Rec.709 corners. Blender exposes it as **Warp / 塑形**. DCTL
retains its existing controls, translation envelope and equations; its separate
oracle is `tests/support/dctl_reference.py`. The retained production low/high
crossover is ρ=0.4 of AP1 cube capacity; the analytic reference uses the J_A/C
law above. Visibility remains 4 in both. Lean and mathlib
remain pinned to 4.35.0.

### Geometry, controls and evaluation order

The six source vertices are the actual Rec.709 R/Y/G/C/B/M RGB rays, each
scaled to the four output-tone J_HK anchors: Shadows, Midtones, White and
Highlights (approximately 19.599678, 51.351504, 100 and 183.748822 at defaults).
Source RGB is nonnegative with unrestricted exposure. Between anchors, angles
interpolate directly and radii in log space. Anchor contours are solved
directly from Rec.709.

`ColorSettings` retains lightness/chroma drivers, their Fit controls, global
chroma gain and Adaptance (4×2). Those eight Adaptance values now store direct
neutral a/b destinations. `adaptance_half_saturation` replaces nonlinear `adaptance_reach` in
the reference and Blender; it directly denotes C/|J_A| at half influence, with range [0.05,1] and default 0.25. There is
no legacy-grade conversion. Blender Grade/Stack schemas and math/cache keys
are bumped so old settings and baked results are not silently reinterpreted.
`WebSettings` retains three finite 4×6 arrays, all zero at reset:

| Field | Meaning |
| --- | --- |
| `log_chroma` | log₂ of target radius / source radius, before Adaptance and scale |
| `hue_degrees` | Unwrapped target hue displacement in degrees |
| `log_scale` | log₂ of the final positive J_A/chroma scale at each corner |

Freeze post-tone C₀, signed energy E₀=J_A|J_A| and
h=√(|E₀|+66C₀). Retained J/C drivers and the web read those original selectors.
The evaluation order is:

1. Retained lightness/chroma operations.
2. Web hue warp and radial chroma edit at fixed signed J_HK, carrying energy.
3. Selective cone-derived Adaptance, changing a/b and signed achromatic energy.
4. H–K repair with frozen post-Tone reference energy, on the nonnegative-H branch.
5. The web's final positive scale λ, selected from the pre-Adaptance web state.
   Multiply a/b by λ and energy by λ², preserving C/|J_A| where defined.

Appearance Stack handoffs include repair and Scale while bypassing RGB cube
containment. RGB export applies AP1 cube containment only. The complete grade
inverse uses its existing joint iterative solve; no nested per-pixel Adaptance
or H–K solver is added.

### Direct neutral targets and half-influence saturation

For each positive neutral anchor hᵢ, set
A₀=A_w(hᵢ/100)^(1/γ), r₀=A₀/3.05. Decode the requested neutral a/b destination
at that same A₀ through modCAM16's eccentricity and inverse opponent matrix to
obtain three target responses rᵢ*. Each must be strictly between 0 and 400.
Calibrate positive response gains with

```text
mᵢ = rᵢ* (400 − r₀) / [r₀ (400 − rᵢ*)]
gᵢ = mᵢ^(1/0.42)
```

Here gᵢ is the corresponding linear cone gain. Quintic cardinal weights
interpolate log(m) between anchors with constant tails. These are local
cone-derived gains, rather than a change of viewing white or a full CAT16
adaptation. CAT16 provides the cone basis; selective masking and normalization
are additional creative grading choices.

The half-influence control directly sets source saturation R=C/|J_A| at v=1/2. The frozen mask is

```text
v = R⁴ E₀² / (R⁴ E₀² + C₀⁴)
```

Bounded normalized powers avoid overflow. Neutrals have v=1; a nonneutral
with E₀=0 has v=0. Exact black remains unchanged. At C₀/|J_A|=R, v=1/2.
Thus the control changes how far the tint extends into saturated colors, without
moving any of the four calibrated center destinations. Values below 0.05 are
not exposed because they make the tint region unnecessarily narrow.

For each pixel, reconstruct actual responses from the carried energy and
opponent coordinates, not from a subtraction involving H². Apply

```text
rᵢ' = k(h)^v T_exp(v log(mᵢ(h)))(rᵢ)
```

Compute k at every tone from a hypothetical neutral with the same frozen h:
Qᵢ=T_mᵢ(r₀)/r₀, Qᵢ(0)=mᵢ, and k=3.05/(2Q_R+Q_G+0.05Q_B).
This common normalization preserves the original neutral's J_A at every tone,
including between anchors and on the signed neutral branch. The neutral may
acquire chroma, so its J_HK changes. Signed response symmetry does not imply
odd a/b coordinates: hue eccentricity differs at opposite angles.

### Total response law, inverse and export

For |r|≤400 the response operation is the exact compression-conjugated cone
gain:

```text
T_m(r) = m r / [1 + (m−1)|r|/400]
```

To support intermediate signed states beyond the physical response range,
use an algebraic exterior continuation. For |r|>400 define

```text
y = |r|/400 − 1
u = 2y / [sqrt(1+4y) + 1]
T_m(r) = sign(r) 400 [1 + u/m + (u/m)²]
```

For positive m this total map is strictly increasing, has the reciprocal
inverse T_(1/m), and composes as T_n∘T_m=T_(nm). It joins with matching value,
slope and curvature at ±400. It is generally only C¹ at zero; the complete
grade is not claimed globally C². With original selectors supplied, Adaptance
itself has an explicit inverse: divide responses by k^v, then apply reciprocal
gains. Recovering unknown selectors remains part of the full grade's existing
joint solve.

Responses outside ±400 are algebraic intermediate coordinates. They are never
sent directly to physical cone uncompression. After H–K repair, the cube guard
checks the strict decoder response domain and AP1 RGB [0,1024], reducing
chroma at the repaired J_A and hue as necessary. This export projection is
lossy; neither it nor extreme creative warps guarantee a unique inverse.

### Corner targets, tonal interpolation and web laws

A corner drag stores the underlying web target while retaining its final
positive scale. With active Adaptance, a local damped 2D Newton solve recovers
that target from the requested final a/b position. It uses frozen source
corner selectors, the carried fixed-J_HK web energy, finite-difference local
Jacobians and backtracking. Failed, singular, folded or crossed targets are
rejected and Blender keeps the previous valid target. This is control
preparation only, never a solver inside forward pixel evaluation. Center
dragging stores and validates a direct neutral destination and retains all
corner coefficients.

Adjacent tonal rows use S₅(t)=6t⁵−15t⁴+10t³, with constant tails and matching
first/second derivatives at anchors. Hue uses unwrapped angles and positive
gains interpolate logarithmically. The resulting Adaptance center positions
between anchors follow the cone law and neutral normalization, rather than
linear interpolation of a/b destinations.

For source radius R and target T, the radial web law is

```text
A(C) = (1 + (C/τ)^4)^(-1/4)
g = (T/R − A(R)) / (1 − A(R))
F(C) = C [g + (1−g) A(C)]
F'(C) = g + (1−g) (1 + (C/τ)^4)^(-5/4) > 0
```

The first radial field calibrates R→T, the scale field T→λT. Coefficients
interpolate logarithmically between destination hues. Positive hue-independent
toe widths use (Σv^(-8))^(-1/8) over 2 and 0.1 times the relevant six radii.
Chroma toe is independent of scale. Near neutral F(C)=C+O(C⁵); factorized
evaluation of 1−A avoids cancellation.

For source hue-sector width w, destination endpoints φ₀,φ₁ and slope
m=(φ₁−φ₀)/w, use shared vertex derivative
d=(0.5(m_left^(-4)+m_right^(-4)))^(-1/4). Quintic Bézier controls are

```text
[φ₀, φ₀+w*d₀/5, φ₀+2w*d₀/5, φ₁−2w*d₁/5, φ₁−w*d₁/5, φ₁]
```

Periodic sectors have positive hue derivative, shared first derivatives and
zero second derivatives at each vertex. Apply
h+S₅(min(C/τθ,1))(warp(h)−h); the angular toe uses default radii.
Constituent monotonicity does not prove global injectivity of the complete
selective, source-dependent grade, nor an identity neutral a/b Jacobian.

### Reference saturation pad

Evaluate Warp hue/chroma, selective Adaptance, H–K repair and then final Scale.
Project the resulting `(a,b,E)` directly as p=(a,b)/sqrt(C²+|E|), with horizontal
−p_b and vertical +p_a. Handles and contours share this state; there is no
second display repair. Cube projection is excluded from the pad calculation.

Scale multiplies a/b by k and carried energy by k², so both compact Cartesian
coordinates and the radius stay fixed for every k>0. For a nonblack repaired
state on the nonnegative-energy branch, H(k)=sqrt(k²E+66kC) strictly increases.
The contextual E=0 rim comes from the request after Adaptance and before repair
and Scale, so its repaired pad radius is also independent of Scale. Exported
RGB samples are projected from their output coordinates without another repair.

### Historical frozen Blender pad and controls (Step 5.73)

This subsection records the frozen Blender implementation. Its final guard
and paired Scale compensation are not the corrected reference order. The
reference uses the same compact chart on its already repaired, scaled state;
changing Scale preserves that point's Cartesian pad coordinates and radius.
Future next-Blender Warp should consume that corrected state directly.

Warp has a square centered **guarded bounded saturation pad**. First evaluate
Warp, selective Adaptance and final Scale in raw signed appearance coordinates;
then apply the existing H–K guard with each original source point's carried
reference energy. For the resulting guarded `(a,b,E)`, display
p=(a,b)/sqrt(C²+|E|), with horizontal −p_b and vertical +p_a. This compacts
linear saturation s=C/|J_A| to r=s/sqrt(1+s²). The unit disk is retained in the
view, but its circle is not drawn permanently. With positive source reference
energy, raw E=0 maps strictly inside this disk after H–K repair.

Modified handles, spokes and contours all use this once-guarded geometry.
The cube guard is not part of the pad geometry; the pad describes the page's
appearance request after H–K repair, rather than a final RGB gamut guarantee.
Exported RGB sample clouds and external references already include their output
processing and are projected directly without a second H–K guard. Selected-tone
samples are blue and external reference samples red. Fixed Rec.709 reference
targets stay in place; only modified contours are drawn in the UI, with dimmer
inner rings. Final Scale preserves raw saturation but can move the guarded
marker because the guard keeps the original reference energy.

S/M/W/H sits inside the top-left and the half-influence slider at top-right.
Only the selected outer vertex has an unlabeled thin neutral vertical Scale
rail; the center has none. Its displayed range is −1…+1 stops, while relative
dragging continues to stored limits −8…+8. The thumb pins at either rail end
and the signed readout retains the actual value with two decimal places.
Dragging one full rail height changes Scale by one stop. No ramp LUTs are
required. Rail placement and view
bounds stay fixed throughout the gesture, including pauses, and refit only on
mouse release or cancel. Captured dragging may pass beneath the controls or
beyond the view. Screen position never rejects an otherwise valid edit.

Inside the raw physical region, corners follow the guarded display destination
at 0.5× mouse speed and the center at 0.2×. When a corner crosses raw carried
energy E=J_A|J_A|=0, the same gesture switches to **Chroma Stops**. Radial travel
of 40 UI-scaled pixels adds one stop to the existing pre-Adaptance `web_chroma`
target, so its requested radius doubles. This is not a promise that final
postguard chroma or saturation doubles. Hue follows the virtual cursor's
direction through an adapted-hue solve. The actual marker always shows the
guarded output; the virtual cursor remains independent. Existing ±16 chroma
stop limits still apply. Crossing inward resumes positional dragging, consuming
the remainder of the same pointer event. R rebases the gesture after reset;
Esc restores the original settings. Rejected edits change neither controls nor
transient gesture state.

Scale uses one paired edit transaction for the pad and native sidebar. On an
upward Scale request, negative-energy corners reduce their stored Chroma Stops
as needed to stay at or before the raw H–K Scale-ray turning point, retaining
the height already reached along that frozen starting ray. Accepted Chroma
Stops reductions persist after release; lowering Scale later does not restore
them. For a current corner with C>0 and negative carried energy E, an additional
positive Scale factor k gives the raw H–K height

```text
H(k) = 2 sqrt(66 C k) − sqrt(66 C k + |E| k²),  k > 0
k_peak = 33 sqrt(3) C / |E|
```

The equivalent acceptance test on the final corner is E′≥0 or
|E′|≤33√3 C′, with a small floating-point margin before the turning point.
The complete candidate and its float32 stored values are validated; an
unreachable request keeps the last accepted settings. Paired editing preserves
stored hue, although Adaptance may change the displayed hue. It does not alter
the grading law: Scale alone still preserves raw C/|J_A|, whereas reducing
Chroma Stops is a separate accepted control change. The frozen starting pair
makes split pointer events and reversal deterministic; Esc restores that pair,
and R during Scale dragging resets Scale without resetting independent Chroma.

Scale-down edits leave Chroma Stops unchanged instead of compensating to keep
a marker at its old radius.
The selected handle remains movable near neutral using a 16 UI-scaled-pixel
virtual lever for Chroma Stops interaction only; its true guarded marker and
the grading calculation are not displaced by that lever.

The Warp sidebar shows all four tonal groups at once, without Center/S/M/W/H
selectors. Each group exposes center a/b plus all six vertices' Chroma Stops,
absolute pre-Adaptance Hue and Scale. The pad retains its own tone and vertex
selection. Absolute Hue is the source Rec.709 hue plus the stored hue warp,
wrapped to one turn; edits are converted back to the nearest stored angular
offset while retaining valid hue ordering. Sidebar Scale uses the same −1…+1
display range and two-decimal precision. UI adapters preserve the saved raw
fields and animation paths; loading, animation and exact undo restoration do
not trigger paired Scale compensation.

Only during the selected corner's active exterior drag is its contextual H–K
rim shown. Construct raw C₀=H²/66, E=0 at its current raw H, apply H–K repair
with that corner's source reference energy, then project to get the rim radius.
This local circle depends on tone, source energy and current Scale/Adaptance;
it is neither the unit disk rim nor the earlier onset of H–K repair. It vanishes
on inward exit, release, cancel, selection mismatch or editor/target teardown.

Existing linear-saturation APIs and statistics retain their meaning. Worker
publications carry separate immutable compact coordinates, preserving chromatic
E=0 samples. The robust-center cross and 95% ellipse are magnified 5× in linear
coordinates and then projected pointwise. DetMCD has no arithmetic-mean marker
or center dot; the cross spans 10 UI-scaled pixels and the ellipse retains its
minimum display radius.

DetMCD selects up to 512 distinct pixels from the active hard tone's Stage 2
input in the captured scope grid (at most 256×192), requiring finite linear
appearance saturation C/|J_A| < 0.1. Neutral black qualifies; chromatic E=0 does
not. Signed nonzero energy uses sqrt(|E|). This filter does not cull the tone's
displayed point cloud. A fixed SplitMix64 hash of original raster IDs scatters
the sample: equal alpha takes the highest integer hashes, while varying alpha
uses log(-log(u))-log(alpha) priorities, with original IDs breaking ties. No
pixel repeats; if at most 512 qualify, each contributes once. IDs are cached
with Stage 2 input across Stage 3 edits and view changes. Source-white dragging
keeps its separate weighted sampler.

Changed Stage 3 output still gets a new six-start DetMCD fit, with 75% raw
support and the existing corrections and convergence. The helper GPU gathers
at most 512 output saturation pairs (4,096 bytes) for its CPU fit, reusing the
group's gather textures. Only the three fitted arrays (80 bytes) reach the UI;
the previous ellipse and cross remain available through the publication
automaton until replaced. Qn index and normal-score tables use bounded eight-
entry immutable caches, while pairwise differences remain fresh for every fit.
The old branch-local linear inverse remains available. The new guarded corner
adapter solves a local two-coordinate residual and holds final Scale fixed.
At microscopic zero-energy folds caused by cone Adaptance, it may restart from
a continuation seed whose projected displacement is within the existing
2×10⁻⁵ saved-control display tolerance, then applies the usual local Jacobian
and residual checks. This is a numerical branch policy, not an injectivity
claim;
nonfinite, ill-conditioned or invalid hue-order requests retain the last valid
edit. Center targets retain the explicit inverse a/b=h·p/sqrt(1−|p|²).

The earlier Step 5.73 checks covered both the reference display and the
then-current Blender implementation. Those product results describe the frozen
historical behavior; they are not validation of the corrected reference.

`//libraries/perceptual-grade-reference:tonal_web` emits `tonal-web.png`, `tonal-web-reset.png`, report/summary and
reset/mixed JSON settings. Review PNG copies live in the project root. The
analysis plots include original/current boundaries and targets for comparison;
Blender's compact pad omits the original contours. Custom fixtures:
`buck2 run //libraries/perceptual-grade-reference:tonal_web_tool -- --settings /absolute/settings.json --output-dir
/absolute/output`. JSON accepts `web`, `adaptance` and `adaptance_half_saturation`.

Numerical checks cover direct centers, frozen masks, signed neutral energy,
physical cone equivalence, extended response round trips, ±400 boundary jets,
scaled arithmetic, combined corner dragging, paired Scale compensation,
low-Scale outward dragging, all-tone sidebar exposure and absolute hue,
final saturation, inverse residuals, CPU/GLSL agreement and Blender lifecycle.
Lean proves exact-real
response algebra, boundary jets, calibration/normalization, half-influence mask properties
and signed final scaling. `linear_saturation_scale` and `linear_saturation_center_target` retain the
linear solver guarantees. The bounded-saturation theorems prove radius bounds,
the zero-energy circle, hue collinearity, positive Scale invariance on either
energy branch, and the open-disk inverse. These apply to raw projection, not
the source-energy-dependent guard. `WarpGuardChart.lean` additionally proves
carried-zero/negative threshold invariance under positive Scale, compact hue
and radius properties, and that the ideal repair-formula image of the raw E=0
rim lies strictly inside the display disk for positive repaired energy.
Applying that rim claim to executable repair requires H≥0; X=H²>0 alone does
not exclude the negative-H bypass.
`WarpScaleRay.lean` links the historical unrepaired negative-energy Scale ray
to `signedHK`, proves its derivative and unique turning point, and shows that
its increasing branch remains positive only before k|E|=198C. These diagnostic
facts do not constrain the corrected repaired Scale or guarantee positive
height over every interpolated contour.
`WarpRepairedScale.lean` supplies the current reference result: repair first
keeps energy nonnegative under positive Scale, keeps the compact pad fixed,
and makes H increase strictly on every repaired nonblack ray. The old negative
ray proofs remain diagnostic and impose no Scale ceiling on this ordering.
The older translation-envelope proofs remain scoped to the retained
DCTL/historical design. Exact-real theorems do not establish floating-point
correctness or global inverse convergence.

## Fresh LUT bake timing reports (Step 5.64)

The retained bake timing report measures the historical reference CPU and GLSL
bakers with H–K repair disabled and enabled. It is not a current ordering
benchmark. The fixture mixes tone, retained J/C, tonal web hue/radius/scale and
selective Adaptance edits; source fingerprints include the shared web and
response implementations.
Each invocation recalculates every vertex; timing reports are runtime outputs,
not cached build artifacts. The default report is
`buck-out/bake-time-breakdown/summary.md`, with all trials and provenance in
`report.json` beside it. Rerun after source or machine changes to obtain a
current measurement. Reports record timestamps, source/resource fingerprints,
settings, numerical policy, machine and backend versions.

Defaults are the production-shaped 65³ lattice (274,625 vertices), four CPU
workers with 65,536-row chunks, and llvmpipe software GPU. The mixed fixture
uses active tone and creative adjustments. Forward A has global gain 0.15;
inverse B retains those controls with gain 0.10, preventing cancellation in
the A→inverse-B Stack. That historical Stack passed raw appearance and bypassed
H–K export repair. The current reference Stack carries repaired Stage 3 state;
the separate-RGB-LUT row adds independently measured forward
and inverse regular-grid bakes (549,250 total vertices); it is the cost of
building two reusable LUTs, not a composite `inverse(forward(lattice))` bake.

The report retains the initial bake for every workload/backend/mode, followed
by three uninstrumented trials with alternating H–K order. Each trial creates
fresh grade state and inverse-tone tables; immutable lookup and shader setup
are reported separately. Grade setup, tone-table preparation (a subset of
setup), bake, and setup-plus-bake totals stay distinct. Each phase profile is
an additional bake whose output must match the ordinary bake byte-for-byte;
its elapsed time is reported separately and includes instrumentation overhead.
CPU worker intervals can overlap, so only the finishing-worker phases plus
host/idle form an additive wall-time breakdown. GPU phases are host API
intervals through synchronous readback, not timings of individual mathematical
operations inside the fused shader or physical-GPU performance.

Use `--output-dir`, `--size`, `--repeats`, or `--cpu-only` to change reporting
options; a smaller lattice is suitable for a smoke check. Durations are
observations, with no historical baseline, acceptance threshold, or performance
regression gate. Inverse approximations and raw-solve counts explain workload
cost and do not by themselves fail the report. Buck build time, UI scheduling,
LUT packing/publication, compositor rendering and report writing are outside
the core bake timings. DCTL retains its separate production equations.

## Reference H–K repair before Scale

The reference repairs the H–K deficit after selective Adaptance and before
Warp's final positive Scale. Frozen post-Tone selectors supply the reference
energy. `grade_state` returns the repaired, scaled appearance; a forward→inverse
Stack handoff includes that state and bypasses only cube containment. Matching
pairs still cancel as an explicit Stack optimization. `release_state(...,
guard=False)` decodes its supplied state directly; `guard=True` adds only the
validated AP1 cube guard.

For requested H≥0 and chroma C, the repair uses

```text
X = H²; D = X − 66C
E0 = max(post-tone signed energy, 0)
delta = E0 X / (E0 + X), with zero denominator giving zero
E = D                                      if D >= delta
E = delta / (1 + 4t + 10t²)^(1/4)          if D < delta and delta > 0
    t = (delta − D) / delta
E = 0                                      otherwise
Z = max(E − D, 0); L = 0.44X
G = L Z / hypot(2L, Z), with zero denominator giving zero
Hg = sqrt(X + G); Cg = clamp((X + G − E)/66, 0, C)
```

Scale the opponent pair by Cg/C, with an explicit neutral case, and carry E
through final Warp Scale into the cube guard and decoder. The H–K repair itself
preserves hue, never increases chroma, and lifts positive H by at most 20%;
the subsequent common Scale preserves its compact pad coordinates. Repair is
identity above the knee.
For positive H and positive E0 it can rescue an H²<66C request instead of
immediately exporting black. Negative H bypasses this repair; the existing
cube guard handles its signed energy. The cube guard remains the final
containment authority, so the complete export can further reduce chroma and H.

The positivity composition is machine-checked for the ideal exact-real guards.
For every requested H>0 with saved reference energy E0>0, the H–K formula
produces strictly positive carried energy for every signed raw deficit D;
therefore the repaired J_A is positive. A radial cube guard that reduces only
chroma preserves J_A and hue, so an exactly decoded legal nonnegative RGB
cannot be black when black encodes zero achromatic energy. Positive luminance
weights then give Y>0. The full ideal cube guard has an additional white branch:
at or above its positive white endpoint W it returns the W neutral, which is
also nonblack. The proof assumes legality and the local exact RGB/energy
encoding relation for the guarded output; it does not certify the numerical
capacity fit or finite-precision decoded containment. A stronger radial-guard
corollary derives output legality from nonnegative capacity and a certificate
that every chroma in its cube-ray prefix decodes inside the cube. With E0=0 the implication
fails: H=1, C=1 repairs to zero energy and the ideal cube guard returns black.

D is evaluated from authoritative signed energy without subtracting nearly
equal H² and 66C. Let b=sqrt(66C) and
`u = E_signed / (hypot(sqrt(abs(E_signed)), b) + b)`. Then D=E_signed on the
positive branch and D=E_signed+2u² on the negative branch. This is the
historical deficit in both cases, including below the reflected H–K boundary.
The scaled reference uses the same equations with integer exponents.

The reference now returns plain `State(q, energy)` after repair and Scale.
It no longer carries a second export reference in `GradedState`, and
`release_state` has no reference-energy argument. Explicit mathematical repair
probes call `hk_guard.guard` or `guard_scaled` directly. Repair does not mutate
the input state. It is applied once during Stage 3: the smooth H–K repair itself
is **not idempotent**, so reapplying it at export would reintroduce Scale-dependent
pad movement. Reset remains unchanged on ordinary entered RGB states.

The independent RGB inverse evaluates this complete forward export for each
candidate, obtaining that candidate’s own post-tone E0. There is no nested
H–K inverse and no H–K lookup table. The optional `hk_guard.inverse` helper is
a standalone fixed-reference mathematical probe with a bounded scalar
bisection and measured forward residual. It reports degenerate cases explicitly;
it is not used to undo a many-to-one final cube projection.

Reference CPU/GLSL kernels enable `hk_guard=True` by default and repair inside
Stage 3 before Scale. Shared production kernels keep their existing default
and ordering. Parameter slot 115 carries this mode to the shader.
As of Step 5.65, RGB inverse baking uses only its existing raw-appearance
search (up to eight iterations), or analytic candidates for simple controls.
The additional 24-iteration complete-forward RGB refinement is removed.
Candidate ranking and reported acceptance still measure the full guarded
forward reproduction, using each candidate's post-tone reference energy.
When no candidate meets the tolerance, the best validated approximation and
its actual residual are returned. Raw appearance inversion retains its
original solve. These finite searches do not guarantee global convergence
or unique RGB preimages; the independent float64 inverse oracle and standalone
fixed-reference H–K inverse probe retain their separate solvers.
The frozen Blender product retains export-time repair. DCTL retains its previous behavior;
its comparison oracle explicitly disables H–K repair.

Reference validation targets are `//libraries/perceptual-grade-reference/tests:hk_guard`,
`//libraries/perceptual-grade-reference/tests:hk_baking` and
`//libraries/perceptual-grade-reference/proofs:color_model`, run through Buck2
with `--remote-only`. Lean/mathlib remain 4.35.0. The following counts describe
the historical Step 5.63 implementation, not validation of the new ordering.
The H–K suites passed 11 independent-reference and 6 portable-CPU tests; the
21-test inverse software-GLSL suite passes on llvmpipe LLVM 19.1.7, alongside
the production shader/baking/Stack suites. The proof build and its checker
pass with 422 theorems in 22 modules, including 52 H–K theorems. These cover
the scalar energy knee's C² join, energy and projection bounds, hue preservation,
and fixed-positive-reference inverse existence, uniqueness, bracket and
roundtrips on the stated active domain. Only the allowed axioms
`Classical.choice`, `Quot.sound` and `propext` are used.

## Raw-coordinate grading baseline (Step 5.62)

Entry encodes repaired AP1 RGB directly into modCAM16 appearance coordinates.
Tone and creative grading use raw J_HK, J_A and C. Cube→spindle compression
and spindle→cube release are retired from every active forward, prepared,
scaled and Stack path. Historical maps, resources, proofs and comparisons
below are retained as earlier design studies.

Step 5.62 selected the capacity-based law retained by existing products:
at the post-tone/pre-color state, let U(J_A,h) be fitted AP1 [0,1024]³ chroma
capacity and r=0.4U. This historical production contract samples drivers once:

```text
V = C²/(C²+4)
low = V r²/(C²+r²)
high = V C²/(C²+r²)
opponent = (a,b)/hypot(C,2)
```

For C>0, low=high at C=0.4U; low dominates below it and high above it.
Both vanish at neutral. U=0 gives low=0 and high=V for chromatic states.
Visibility remains 4 and opponent normalization remains 2. The crossover
depends on hue through U, while the color coordinates retain their
original modCAM16 meaning. The current analytic reference instead uses
`r=(35/75)|J_A|`, as described above. Tone samples raw appearance lightness. Hue
rotation no longer expands chroma according to destination gamut capacity.

Before the Step 5.63 H–K addition, forward RGB export preserved interior J_A
and hue and reduced chroma only
when the actual decoder returns an illegal AP1 color. At the cube guard input, energy E≤0
exports black; E≥W² exports cube white. For an escape, fitted capacity seeds
a bounded radial refinement (24 binary32 or 56 binary64 rounds, stopping on
stagnation). Every accepted radius has a finite decoded RGB inside the cube;
export returns that saved RGB. Unsafe response-pole trials are rejected.
J_HK can decrease during projection. The fit is a guard accelerator and,
for retained products only, a selector scale; it is never a containment
certificate. Reset is exact through its direct
repair route; matching Stack pairs still cancel and carry signed appearance
without an intermediate guard.

Active resource format 16 contains cube faces, creases, constants and native
adapters, with profile and spindle-guard fields removed. Buck2 derives it with
`//libraries/perceptual-grade-core:d65_cube` from the retained format-15 source archive `//libraries/perceptual-grade-core:d65_boundary`.
Reference bundles the active `d65_cube.npz` plus the historical archive;
Blender installs the active resource at its existing `model/d65_boundary.npz`
path. Cache signatures invalidate earlier grading results.

Lean checks the retained production law's exact ρ=2/5 driver bounds,
complement, crossover and quadratic neutral behavior. These driver theorems
do not formalize the new reference 35/75 law. Exact-capacity guard theorems are conditional on true
capacity; tested-RGB guard theorems require legal accepted candidates and do
not assume fitted-capacity accuracy. `//libraries/perceptual-grade-reference:cube_face_certificate` checks
outward real cube-ray geometry for binary64 and binary32-rounded adapter
constants. It does not prove shader/libm execution or inverse convergence.
The piecewise cube boundary has face/crease derivative changes; no global
C2 claim is made. Lean/mathlib remain pinned at 4.35.0.

`//libraries/perceptual-grade-reference:spindle_shape` and `//libraries/perceptual-grade-reference:rec709_cube_ja_sections` retain their target and PNG
names while plotting raw cube geometry and the reference's hue-independent
`C=(35/75)|J_A|` crossover. Physical gamut curves remain hue-dependent; the
reference crossover may extend beyond them.
Calibration `//libraries/perceptual-grade-reference:driver_raw_capacity_calibration` retains the old compressed
0.3J_A baseline and the historical capacity candidates explicitly for comparison.
Its ρ=0.4 case describes retained production, not the current analytic reference.
Counts describe sampled LUT
vertices rather than image pixel frequencies.

## Interactive scheduling

Interactive publication is distinct from numerical grading. Grade and Grade
Stack keep one active 33³ snapshot and one replaceable pending request during
continuous edits. A started preview finishes and can display older settings;
obsolete 65³ refinement is cancelled, while current requests refine without
a settle delay. Final rendering requires the exact current 65³ result.
Installed LUTs, compositor frames and backend choices remain available to
diagnostics without routine status text in nodes, sidebars or gizmos. Genuine
configuration/bake failures appear in nodes and sidebars only. Bake failures
do not disable grading controls and clear after a successful current result;
superseded-job failures cannot replace current error state. GPU-to-CPU recovery
is logged without a routine UI notification. Gizmos retain interaction and
comparison hints.

Regular Grade's Stage 1 vectorscope has an independent matrix-only path over
cached upstream samples: current matrix, signed Rec.709 projection and
histogram. Its calculation does not depend on the Grade's nonlinear LUT or
Stage 2/3 analysis. The Stack editor retains its whole-Stack output scope.
Both use the existing sampling density; source changes invalidate their
snapshots. Numerical work runs in reusable helper processes: a reserved Stage-1
CPU lane, a bulk CPU lane, and one GPU lane. The GPU helper owns its Programs,
preparation, dispatch/readback and atlas packing on its own main thread. Live
image capture, publication and drawing remain on foreground Blender's main
thread. Cancellation retains a lane until physical work stops; retries and GPU
fallback use fresh attempt identities.

File offers **Save with Exact LUTs** and **Save As with Exact LUTs**; Render
offers **Render with Exact LUTs** and **Render Image Sequence with Exact LUTs**.
Each command prepares and validates current final LUTs before invoking native
output. Image sequences repeat this for each frame and stop on failure or
cancellation. Movie assembly is outside the guarded sequence workflow. Ordinary
Blender commands still run compatibility handlers, but Blender does not abort
native Save/Render when a handler raises. Use the guarded commands when output
must stop if preparation fails; there is no separate preflight action.

An enabled runtime durably records an unclean session before accepting work and
marks it clean only after successful teardown and confirmed helper exits.
Session leases prevent another Blender instance from reclaiming live files.
After an abandoned session, loading validates saved output manifests and repairs
invalid outputs from saved settings. This cannot recover unsaved edits.

`buck2 test --remote-only //products/perceptual-grade-blender/tests/installed:standalone` tests the assembled extension ZIP in
checksum-pinned native Blender 5.3.0 on Linux x64 or macOS ARM64, with the
installed LTS sibling covering Blender 5.2.4, including child
processes, CPU/GPU conformance, cold/warm blue Warp timings and a GPU-only retry
probe. The macOS distribution is copied from its pinned DMG through an owned,
read-only temporary mount. `buck2 test //products/perceptual-grade-blender/tests/gpu/macos:metal` runs the shared
forward, inverse and Stack contracts on actual Metal, including the three-ULP
power bound and cube-crease root-selection regression. The shared power shader
retains GLSL `precise` outside Metal and uses function-scoped Metal safe math
with contraction disabled. Unknown/ignored pragmas fail compilation: acceptance
must use Blender's actual MSL 2.2 compilation mode. Linux success does not certify
that Metal gate or visible macOS interaction. The
`//products/perceptual-grade-blender/tests/installed:crash` target kills native Blender during CPU/GPU execution,
publication, repair and shutdown, then verifies leased-resource protection and
recovery from saved pending output. Scheduling, execution and ownership policies
are directly maintained Python using the
[Invariant framework](../../invariant/README.md). Ordinary policy and native
tests provide regression coverage. Packaging checks the final ZIP inventory and
exact bytes against declared sources; it does not certify machine correctness.
The former machine proofs and source/effect reports are historical material in
the external `perceptual-grade-proof-archive` directory beside the repository.
Native coverage remains incomplete (`coverage_complete=false`), including the
asynchronous export-startup reader gap described in the
[product architecture](../../../products/perceptual-grade-blender/ARCHITECTURE.md).

The fast ownership tests use pinned Python without Blender, numerical resource
generation or helper processes:

```sh
buck2 test //libraries/blender-runtime/tests:physical_ownership //libraries/blender-runtime/tests:app
```

Short native premises run with
`buck2 test //products/perceptual-grade-blender/tests/installed:undo_contract //products/perceptual-grade-blender/tests/blender:ownership_premises`.
Routine recursive tests exclude long acceptance histories explicitly:
`buck2 test //libraries/... //products/... --exclude acceptance --always-exclude`. Repeated
conversion/save/disable scenarios remain available as
`buck2 test //products/perceptual-grade-blender/tests/blender:ownership_acceptance`; they and the GUI undo target
carry the `acceptance` label. Native fault tests remain in the routine suite to
exercise adapter failure and cleanup behavior.

`buck2 test //products/perceptual-grade-blender/tests/installed:gui_undo` runs on Linux x64 and macOS ARM64. macOS
requires a logged-in desktop; Linux uses a private Xvfb fixture whose Debian
packages are version- and SHA-256-pinned in Buck2, without host installation.
It opens the pinned native Blender with an isolated configuration and drives real
blue Warp mouse events followed by Ctrl-Z / Ctrl-Shift-Z. Fifty cycles alternate
pending and completed LUTs; pending cases pause the owned helpers until undo has
returned and defer cyclic garbage collection until after native undo. The test
requires a dispatched LUT attempt and an observed scope wait, counts native
undo/redo receipts, and checks recovery at the immediate post-handler boundary.
It reacquires restored nodes, validates each final output and confirms clean
helper shutdown. It does not call the drag operator or undo handlers directly.
Linux GUI results exercise native undo but do not establish macOS
crash acceptance. `buck2 test //tools/blender-build/tests:xvfb_distribution` checks fixture
extraction and the guarded relocation of its keyboard compiler path.

Capture the native acceptance receipts and diagnostics on macOS with:

```sh
buck2 test //products/perceptual-grade-blender/tests/gpu/macos:metal //products/perceptual-grade-blender/tests/installed:standalone //products/perceptual-grade-blender/tests/installed:gui_undo > macos-repair-acceptance.log 2>&1
```

Installed acceptance records the Blender build, selected backend, helper PID,
cold/warm duration and conformance result. A CPU fallback fails GPU acceptance.
In normal use, a GPU failure keeps CPU grading available and shows Details/Retry;
Retry starts a fresh GPU helper and must pass an uncached conformance job before
ordinary GPU work resumes. Details retain the traceback and helper-log location.

`buck2 run //products/perceptual-grade-blender:interactive_grade_profile -- --output-dir buck-out/interactive-grade`
measures scope publication and 33³/65³ installation under isolated edits and
continuous dragging. First-use setup and source capture are separate, and
headless installation does not establish visible-frame latency.

## Production integration

Blender regular Grade remains forward-only. Grade Stack now packages the same
portable `StackKernel`, forward/inverse CPU and GLSL kernels and prepared tone
inverse used by the legacy-capacity verification `BakeStack`; settings and matrix adapters remain separate from
the Colour-backed independent oracle. The first forward and last inverse
Stage 1 matrices remain outside the LUT. Forward-to-inverse carries raw
appearance and signed energy, matching nonlinear pairs cancel, and other
transitions exchange RGB with repair at the receiver. There is no extra final
stack guard. The scheduler retains progressive 33³/65³, latest-request
cancellation, CPU fallback and worker-side preparation/packing.

DCTL uses direct per-pixel Forward/Inverse evaluation with fixed D65/203-nit
context and XYZ I/O. It evaluates the original compact face splines and crease
curves, rather than Blender's expanded uint16 face atlas. Declared constant
arrays, each padded to 16-byte alignment, total 60,128 bytes. Dynamic DCTL tone
inversion uses bounded Newton/bisection with at most 80 curve evaluations;
Blender instead prepares a tone table once per distinct active inverse tone.
Separate DCTL nodes exchange RGB and cannot cancel raw appearance like a
matching Blender Stack pair. Invalid adaptation or singular inverse Stage 1
produces a visible error diagnostic; invertible orientation reversal is valid.
Generated DCTLs reserve `transform(...)` for the public seven-argument RGB
entry point. Internal evaluation uses `pg_apply_pixel`; a both-locale regression
checks that even a substring search finds only the public entry. This removes
the helper-name ambiguity implicated by the reported Resolve loader error.
The entry uses one explicit `return make_float3(...)`, including its diagnostic
path, and helper parameters/locals cannot reuse UI identifiers. These avoid
source patterns independently reported to trigger Resolve's misleading
float3-return error ([reproduction tests](https://github.com/mvarge/davinci-scripts/blob/main/tests/test_make_dctls.py)).
Generated-source checks cover both editions; host/OpenCL compilation and
numerical tests do not substitute for loading the result in Resolve.
Input repair's one-float-step inward rounding uses native `nextafter` on
Metal/OpenCL and `nextafterf` on CUDA through `pg_next_down`. `_nextafterf`
is not a DCTL intrinsic; test shims must not supply it. An intrinsic-name
regression checks the used underscore functions against the
[DCTL Developer reference, section 8](https://github.com/thatcherfreeman/utility-dctls/blob/main/Documentation/DCTL%20Documentation.txt).
Numerical checks compare float32 predecessors bit-for-bit and cover repair's
cube identity, bounds and idempotence.
Apple specifies native `nextafter` from Metal 3.1 onward; the reported Resolve
compiler explicitly exposes it ([Metal language specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)).
DCTL exposes paired signed a→J/b→J and a→C/b→C coefficients directly in
all four tones. J coefficients range from −50 to 50; C coefficients from
−4 to 4. Shadows/Midtones/White use float steps 0.1 for J and 0.01 for C.
All Highlight Low/High/a/b→J/C sliders retain their original integer step 1;
the resulting DCTL uses 62 of its 64 floating point sliders. The former
angle/length UI and conversion are removed. Blender keeps its existing UI.
Cross-platform comparisons use controls representable by the selected platform
before evaluating the expected model.

`buck2 run //products/perceptual-grade-blender:production_stack -- --output-dir buck-out/production-stack`
checks actual production CPU/GLSL progressive LUTs on the four photographic
fixtures, deliberately exercising the inverse instead of matching-pair
cancellation. It uses the unchanged physical-RGB interpolation and pinned
ACES 2 views, with SDR <0.1 and HDR <0.4 code-value limits. This study excludes
compositor transport rounding; real graph tests separately cover transport.
`buck2 run //products/perceptual-grade-dctl:quality -- --output-dir buck-out/dctl-quality` compares the
compiled direct DCTL with the compact reference, adopted atlas and independent
geometric oracle. Compiler portability does not certify Resolve/CUDA/Metal
execution. The existing D65 resource is reused without regeneration.

The adopted uint16 surface retains its documented approximation; the active
export guard validates decoded RGB against the actual AP1 cube. Solver
reproduction, source-root agreement, boundary approximation and photographic
render error are distinct measurements. Historical studies below describe
earlier implementations where their production-status statements differ.

## Fixed-grid input-shaper experiment

`buck2 run //products/perceptual-grade-blender:grade_shaper_error -- --output-dir buck-out/grade-shaper-error`
compares 83 initial linear, log, centered-tanh and log-then-tanh input grids,
then refines each nonlinear family's best parameters once. The grid stays
65³ and interpolation retains physical linear-RGB fractions and four reads.
Each candidate has a private row cache; production baseline cubes must match
bit-for-bit. CPU screens cover all eight grades and four sampled photographs;
the baseline and family winners also use actual llvmpipe GLSL. No extension
default, grading equation, RGBE representation or D65 resource changes.

Ranking minimizes the worst maximum-error ratio to log κ=.01 across the six
nontrivial grades and two display views, then geometric-mean p99 ratios. Reports
retain absolute errors and individual grade regressions, without importing the
paired-stack acceptance gate. Fixed float64 ideals and direct backend images
are reused. Finalists include cubes, axes, native/encoded arrays, PNGs, error
images and worst-pixel vertex audits. Numerical float64 LUT addressing excludes
Blender graph/FMA and RGBE transport; float32 shaper conditioning is reported
separately. Fresh bake timings use empty row caches, with immutable D65 setup
and shader creation recorded separately.

`--resume` verifies numerical-source/resource provenance and a freshly reproduced
baseline before reusing completed screens. `--report-only` rewrites the summary
without calculation. `buck2 test //products/perceptual-grade-blender/tests/reference_integration:lut_shapers` checks axes,
analytic round trips, physical interpolation and experiment isolation.

`buck2 run //products/perceptual-grade-blender:shaper_performance -- --output-dir buck-out/shaper-performance`
compares the current log κ=.01 with the selected log-then-tanh candidate
(κ=.01, strength=2, center=.25). Five fresh-process trials measure CPU and
llvmpipe 65³ baking with progressive 33³ output and actual RGBE packing.
Each grade has an empty row cache; a trial's six grades share immutable D65
and GPU program setup, which are timed separately. Each process has a new
isolated Mesa shader cache.

The runner also measures first actual Blender final renders of the baked
mixed-tone LUT at 1920×1080, using repeated prepared photographic samples.
An analysis-only address graph preserves four nearest RGBE reads, physical
RGB tetrahedral interpolation and linear output. The complete rendered frame
is checked against the matching numerical lookup, including exact black and
alpha. Graph/image preparation, blocking render, EXR write and readback have
separate timings. If compositor callbacks are absent, their interval is null;
the render-call time includes common engine overhead, characterized by a
separate pass-through control. Final AUTO rendering uses full precision.
This measures the LUT core, excluding the complete Grade wrapper's input
repair and matrices; software-GPU results do not predict physical-GPU speed.
`--summarize-only` rewrites the report without repeating measurements.

## Regular Grade photographic LUT experiment

`buck2 run //products/perceptual-grade-blender:grade_photo_error -- --output-dir buck-out/grade-photo-error`
measures the actual regular Grade CPU and llvmpipe GLSL 65³ bakers on all four
packaged photographic samples and eight forward grades. The ideal is direct
float64 grading with the adopted D65 boundary cache. A direct float32 per-pixel
arm separates implementation error from LUT interpolation error. Stage 1 stays
outside the cube; the numerical AP1 adapter applies it before input repair.
Tiny float32 repair overshoots are reported before address-only bounding.

Pinned ACES 2.0 SDR 100-nit sRGB and HDR 1000-nit Rec.2020 PQ views produce
encoded errors before clipping or quantization, in 255/1023 code units.
Reports include distributions, worst expected/actual pixels, CPU/GPU differences,
native/encoded arrays, rendered PNGs, error heatmaps and enlarged crops.
`--case NAME`, `--cpu-only` and `--report-only` select cases, omit GPU or audit
worst-pixel corners and rewrite the summary from saved measurements. The corner
audit compares stored vertices with fresh CPU and cached-float64 evaluations,
and reconstructs their convex blend without rebaking. Native cube range escapes
are reported separately. GPU failures never substitute CPU results.
`buck2 test //products/perceptual-grade-blender/tests/reference_integration:photo_grade` checks settings conversion, Stage 1
placement, signed-input repair, black/cube endpoints and metric thresholds.

The current boundary fit is part of the chosen ideal. These are 338,688 spatial
samples, not full-resolution photographs. Compositor matrix/FMA rounding,
RGBE/half-float transport and the older Grade Stack baker are excluded.
No production math changes or single-forward error threshold are adopted by
this experiment; the earlier paired-stack recovery limits remain separate.

## Photographic forward–inverse experiment

`buck2 run //products/perceptual-grade-blender:stack_photo_error -- --output-dir buck-out/stack-photo-error-chroma-toe`
evaluates four packaged photographic spatial samples through eight matching
forward/inverse pairs on the reference CPU and actual GLSL software GPU. This
diagnostic disables matching-pair cancellation, retains raw appearance handoff,
and compares direct execution and a combined 65³ LUT with the repair-aware
original `M^-1 P(Mx)`. Endpoint matrices stay outside the LUT. It uses the existing
D65 cache and inverse policy; it changes no production rendering behavior.

The pinned Blender OCIO configuration produces sRGB encoded SDR 100-nit and
Rec.2020 PQ encoded HDR 1000-nit outputs. Reports measure floating encoded RGB
before file quantization; SDR/HDR nominal code units are 1/255 and 1/1023.
JSON and Markdown include per-image/case/backend errors, raw residuals, worst
pixels and CPU/GPU differences. Native and encoded arrays, tagged display PNGs,
error heatmaps and enlarged crops accompany them. The source fixtures are
every-12th-row/column samples, not full-resolution photographs. `--case NAME`
selects a case and `--cpu-only` omits GPU evaluation.
Add `--report-only` to audit the saved LUT vertices and rewrite the report
without rebaking or rendering. Each worst-pixel audit attributes the error to
its four interpolation corners and distinguishes failed inverse vertices from
interpolation of accurate samples.

`buck2 test //products/perceptual-grade-blender/tests/reference_integration:photo_stack //products/perceptual-grade-blender/tests/reference_integration:photo_io
//products/perceptual-grade-blender/tests/reference_integration:photo_metrics` checks the photographic metrics and
interpolation contract. The adopted tuning gate
for the combined 65³ LUT is a strict maximum below 0.1 SDR code and 0.4 HDR
code on every case, photograph and backend. Direct-solver measurements remain
diagnostic; they have no separate display-error acceptance threshold.
The known original is a valid recovery target, without asserting inverse
uniqueness. Direct recovery includes preparation error; distributions from
different comparison arms are not additive. Compositor RGBE/half-float image
transport and Blender Extension adoption remain separate work.

`buck2 run //products/perceptual-grade-blender:inverse_tuning -- --output-dir buck-out/inverse-tuning/screen --screen`
runs the bounded CPU search: 24 stopping/round combinations, followed by raw
acceptance and inverse-tone-table accuracy around the three fastest passing
candidates. It writes compact rendered metrics and worst-pixel witnesses.
`--policy rounds,stopping,raw,tone` validates a specific policy across all eight
grades on CPU/llvmpipe; repeat the option to compare policies. `--timing` runs
five interleaved fresh CPU trials for tone/mixed/mixed-tone paired and single
inverse bakes, with all trials retained and immutable lookup setup separate.
Policies are scoped to the study and restored afterwards. With no explicit
policy, this tool uses the pre-tuning baseline (40,1e-6,1e-4,2e-6).

Internal Stage 3 stopping, raw acceptance and scalar tone accuracy use different
units. They do not establish independent per-stage RGB guarantees. RGB-route
acceptance is unchanged; standalone inverse-LUT interpolation fixes remain
deferred. D65, the C2 chroma coordinate and the central search start are fixed.
`buck2 test //products/perceptual-grade-blender/tests/reference_integration:inverse_tuning` checks strict gate equality and
scoped numerical policies, including nested restoration and tone preparation.

## Historical D65 spindle and uint16 CPU/GPU baking (format 15)

The remainder of this section records the pre-Step-5.62 implementation and
measurements. References here to an active spindle, its entry/release maps,
format-15 runtime resource, older cache schemas, and compressed diagnostic
plots describe that historical version. The current behavior and artifacts
are specified in the active raw-coordinate section above.

Normal builds reuse the canonical cached NPZ; `buck2 build //libraries/perceptual-grade-core:d65_boundary
//libraries/perceptual-grade-reference:spindle_quality` does not regenerate it. Explicit regeneration uses
`buck2 build //libraries/perceptual-grade-reference:rebuild_d65_boundary --show-output`; copy its `d65_boundary.npz`
to `libraries/perceptual-grade-core/src/perceptual_grade_core/model/d65_boundary.npz` when adopting a rebuilt resource.
Its primitive tests are `buck2 test
//libraries/perceptual-grade-reference/tests:spindle`; exact-real scalar proofs use `//libraries/perceptual-grade-reference/proofs:color_model`.
The NumPy float64 model retains independent grading equations and Colour
conversion. `tools/build/boundary_oracle.py` provides independent geometric
solves for audits. Regular Grade nodes remain forward-only; Stack occurrences may be
forward or inverse. First forward Stage 1 runs natively before repair and LUT
entry; final inverse Stage 1 runs natively after the LUT. Internal matrices are
baked. Ending inverse RGB is signed/unbounded by the cube; no additional Stack
export repair or compression is applied. Regular Grade LUTs use shared float32
NumPy/GLSL math. The reference also provides float32 CPU/GLSL Stack inverse
baking; integration of that backend into the extension scheduler is separate.
The installed extension still uses its existing float64 Stack inverse.
DCTL reference adoption remains deferred.

Forward-to-inverse transfers raw Stage 3 coordinates and authoritative signed
energy, without hard guarding, decoding or re-encoding the handoff. All other
transitions exchange RGB: a forward sender guards, releases and decodes; a
forward receiver applies Stage 1 before repairing and entering its nonlinear
stages. An inverse RGB receiver repairs before undoing nonlinear stages.
Each forward RGB export performs its own cube guard, including the final forward.

Matching adjacent nonlinear forward/inverse settings are compiled away. Their
result is M_inverse^-1(repair(M_forward(x))). This exact program cancellation
also covers folding maps and black plateaus; it does not claim such maps have
unique mathematical inverses. Entry/release cancel with the nonlinear pair.
Regular nonlinear reset and empty Stacks retain the same repair policy.
Scaled exponents retain recoverable values below float64 during entry.
Blender RNA stores tone defaults as binary32; the reader restores an exact
declared default only when its stored value is that default's binary32 image.
Nearby edited values remain edits.

Interactive scheduling keeps the installed image while one progressive 65³
job calculates the 33³ subset first, then continues the remaining vertices
without waiting for publication or a settling delay. A newer nonlinear edit
replaces the one pending request; a started preview can finish before obsolete
refinement is cancelled. Final publication requires the current request.
Current compositor frames finish before image commits; the ready 33³ preview
and final 65³ retain separate commits and internal completed-frame tracking.
Headless/inactive paths do not require display callbacks; full renders force
the current final LUT. The first-preview launch interval remains 40 ms.
Model/LUT/Stack schemas 9/24/6 reject obsolete kernels and images. Auto selects
a GPU only after actual shader compilation and a numerical conformance probe.
GPU dispatch runs on Blender's main thread in bounded batches; RGBE preparation
runs on a worker. CPU numerical work also runs on workers. A device failure
restarts the whole job with the same float32 CPU equations, retaining the last
installed image. Cache keys include the resource, lattice, backend and relevant
tone/fit constants; shared fixed-work caches stay within 32 MiB.

Entry and release keep J_A and modCAM hue fixed. They recompute
J_HK=sqrt(J_A²+66C). This replaces the rejected fixed-J_HK cube rays, whose
disconnected intersections lost valid yellow and green colors. Let W be
neutral cube white's J_A, r_w its offset-free cone response, γ the appearance
exponent, and t=(J_A/W)^(1/γ). The true native AP1 chroma capacity is U(J_A,h).
The round spindle radius is B=W*t*(1-t)*g(t), where g is a compact positive
C2 rounded-linear profile. Analytic normalized limits at t=0 and t=1 avoid
subtracting nearly equal cube coordinates. C2 refers to this normalized
profile and the full radial curve; it does not assert bounded second J_A
derivatives at the degenerate black tip.

### Historical production cubic (Step 5.57)

The independent float64/scaled reference, Blender, DCTL and portable float32
bake kernels use the same cubic radial map. For x=C_spindle/B, y=C_cube/B
and k=U/B>=1:

```text
y = R_k(x) = x+(k-1)x³
u = (3/2)*y*sqrt(3*(k-1))
x = y * 3*sinh(asinh(u)/3)/u             (u != 0)
x = y                                   (u = 0)
```

Both directions are closed form without iteration. The reference reuses its
independent `depressed_root` implementation. The ratio form preserves the
linear limit; subnormal normalized chroma retains unit gain, and Scaled
handling preserves chroma below the float64 range. Public maps retain exact
B↔U endpoints, physical clipping and roundoff containment. The spindle body,
D65 resource and hard guard are unchanged. The release slope is
`1+3*(k-1)*x²`, with unit slope and zero curvature at neutral and boundary
slope `3k-2`. For k>1 every positive physical radius is compressed.

At fixed interior J_A, write v for the two Cartesian chroma coordinates.
If B>0 and 1<=k(v)<=K uniformly over hue, release is
`M(v)=(1+(k(v)-1)*||v||²/B²)*v`. For both release and its closed inverse,
`||M(v)-v|| <= (K-1)*||v||³/B²`. This establishes the full Fréchet derivative
at neutral as the identity, even if k varies with hue. Bounded capacity is
an explicit theorem hypothesis. The result excludes the degenerate B=0 tips
and does not assert global Cartesian C2 across cube-face or fitted-table
creases. Scalar release remains polynomial and its scalar inverse is smooth.

Verification in Step 5.57 passed 100 focused numerical cases, four archived
pole cases and all three proof-checker tests through Buck2. That historical Lean
audit covered 329 theorems in 20 modules, including both Cartesian
neutral identity derivatives, with only Classical.choice, Quot.sound and
propext. Exact-geometry reset witnesses have maximum absolute RGB error
1.345e-10 on the [0,1024] cube, within the tightened 2e-10 test budget.
The separate fitted-capacity acceleration certificate remains unfinished.

`buck2 build //libraries/perceptual-grade-reference:rec709_cube_ja_sections //libraries/perceptual-grade-reference:spindle_shape --show-output`
generates the two current Matplotlib PNGs. Six polar sections keep J_A fixed
and show raw Rec.709/AP1 boundaries, samples and the 35/75 crossover circle.
The shape plot shows raw C_max ranges over 1,440 hues and the straight
`C=(35/75)|J_A|` guide. Both source cubes use [0,1024]³. Its right panels
retain the production 65³ lattice's nonnegative Rec.709/Rec.2020 subsets
without an upper channel limit, plotting `C/|J_A|` and half-opaque histograms
with a common absolute-count axis. Only histograms exclude input luminance
above 10,000 nits.

### Historical low/high crossover (Step 5.60)

At Step 5.60 the reference, Blender and DCTL used k=3/10=0.3 with visibility v=4. Equal
low/high membership is at C=0.3|J_A|, equivalent to saturation s=22.5 under
s=75C/|J_A|. Forward/inverse CPU and GLSL baking used the same crossover;
Blender's scope helper followed it too. Saved grades with active low/high
controls changed response at that revision. Mathematical LUT signature schema
26 invalidated earlier baked LUTs so they rebuilt automatically.

Lean proves neutral zero response, equal drivers at the physical crossover,
and low/high ordering on either side using exact 3/10. The historical Step 5.60
kernel/axiom audit covered 333 theorems in 20 modules, with only
Classical.choice, Quot.sound and propext.

Buck2 validation covers the reference and scaled drivers, production parity,
HK-coordinate scope crossover, reachable folded inverse, CPU/GLSL baking,
saved-LUT rebuilding, DCTL and packaging. The crossover change exposed a
one-ULP batch-size dependency in the portable float32 tone matvec. Tone now
uses a fixed per-row reduction, and a regression checks batch sizes 1–8;
stored inverse residuals still match recomputation exactly. Existing numerical
tolerances remain unchanged.

At that revision, `spindle_shape` rendered the 0.3 J_A crossover with
4/15,5/15,6/15 comparison guides. That target now shows the raw geometry and
35/75 reference crossover described above. Historical sensitivity PNGs remain
reproducible as Buck2 outputs of the targets below.

### Crossover comparison at visibility 4 (Step 5.59)

`buck2 build //libraries/perceptual-grade-reference:driver_crossover_comparison --show-output` compares k=0.3 and
k=1/3 with visibility fixed at v=4. Its overview places the two 2x2 groups
side by side. Within each group, rows show Rec.709/Rec.2020 and columns show
the low/high drivers. Sampling, shared symlog axes, contours and per-driver,
per-crossover normalization follow the sensitivity sweep below.

The target emits `driver-sensitivity-k0p3-v4.png`,
`driver-sensitivity-k1-3-v4.png`, `driver-sensitivity-overview.png`, and
`report.json`. The build's reported output directory contains the overview
and both individual plots. The original visibility sweep remains available
under its own target; project-root sensitivity PNG copies were removed when
adopting the selected crossover in Step 5.60.

Both targets build successfully. The comparison passes the driver and
population checks described below; its k=1/3,v=4 individual PNG matches the
original sweep byte-for-byte. All three comparison PNGs were visually
inspected during Step 5.59.

### Relative driver sensitivity sweep (Step 5.58)

`buck2 build //libraries/perceptual-grade-reference:driver_visibility_sweep --show-output` compares plotting-only
crossover ratios k=1/3 and 0.4 with visibility values v=0.25,1,4,16. It emits
eight 2x2 PNG groups, `driver-sensitivity-overview.png`, and `report.json`.
Within each group, rows are Rec.709/Rec.2020 and columns are low/high drivers.
The sampled colors are the existing production-shaped 65³ AP1 lattice after
cubic compression, accepting nonnegative source-space RGB without an upper
channel limit. The diagnostic retains all scatter samples, with no luminance
cutoff. Its axes are preserved J_A and compressed C, both symlog (linear
thresholds 1 and 0.25 respectively) to resolve the visibility changes near
C=sqrt(v). Production model parameters are not changed.

For each (k,v), low and high are independently divided by their maximum over
the union of both displayed gamut subsets. The same maximum is used in both
gamut rows, and the report records these raw normalization values. Colors
show relative driver sensitivity before the output guard, independently of
an overall handle multiplier. They do not measure the final guarded RGB
change or relative strength between the low and high controls. Normalizers
are recomputed for each parameter combination to compare response shapes.
The opaque points use a common 0..1 color scale; analytic 10%,50%,90% contours
inside the spindle are response guides, not sampled gamut boundaries.

The verified build retains 22,164 Rec.709 and 93,118 Rec.2020 vertices,
including 5,476 and 23,349 above 10,000 nits. The historical k=0.3,v=4
equations remain local to the diagnostic. A separate equation check compares
k=35/75,v=4 against the current reference on all 274,625 coordinates, without
claiming that historical compressed inputs are the current entry path.
Embedded checks also cover neutral zero response,
crossover equality, low+high=V, finite normalized ranges and subset counts.
Build the target to regenerate all eight individual PNGs and its overview
inside buck-out; this diagnostic does not write copies to the project root.
Individual files are named `driver-sensitivity-k{k}-v{v}.png`, with k slugs
`1-3` / `0p4` and v slugs `0p25` / `1` / `4` / `16`.

### Historical pole experiment (Steps 5.51–5.54)

Step 5.57 retires this map from the active reference. `pole_spindle.py`
preserves the following equations for reproducible historical diagnostics;
`Model` and its Scaled path use the cubic above.
For x=C_spindle/B, y=C_cube/B, k=U/B>=1, p=1001/1000, P=p² and c=1,
the boundary-profile derivative is d=20 and the blend weight is w=(d-1)(P-1)=0.038019:

```text
a = P+1-2w = 1925963/1000000
b = P-3+2w = -1921961/1000000
F(z) = z(a+bz) / ((1+z)(P-z))
y = R_k(x) = x sqrt(1+(k²-1)F(x²))
```

For numerical stability, release evaluates the same profile as the convex blend
`(1-w)*(z+z*(1-z)²/((1+z)*(P-z))) + w*(P-1)*z/(P-z)`.
This avoids subtracting nearly equal numerator terms near the boundary.
The denominator uses `(P-1)+(1-z)` with the exact rational gap
`P-1=2001/1000000` rounded directly, avoiding cancellation in that constant.
Moving the pole alone leaves the old endpoint slope unchanged; d raises it
independently while preserving the neutral derivative and the cubic inverse.

The inverse uses r=y/k and t=1/k². Its squared output z=x² satisfies

```text
a3 = -t + (1-t)b
a2 = t(P-c) + (1-t)a + r²
a1 = tcP - r²(P-c)
a0 = -r²cP
a3 z³ + a2 z² + a1 z + a0 = 0
```

With u=a2/a3, v=a1/a3, w=a0/a3 and delta=u²-3v, compute

```text
theta = acos((-2u³+9uv-27w)/(2 delta^(3/2))) / 3
L = (-u+2 sqrt(delta) cos(theta)) / 3
q = -w/L
s = (q-v)/L
H = sqrt(s²-4q)
z = -2q/(H+s) if s>=0, else (H-s)/2
C_spindle = B sqrt(z)
```

L is the largest root, above P; the positive residual quadratic root is the
physical root in [0,P). On cube inputs it lies in [0,1]. The two quadratic
expressions are algebraically identical; the branch prevents cancellation,
not a geometric curve join. The implementation factors r out of sqrt(z) on
the neutral branch to avoid losing tiny chroma when r² underflows. It handles
k=1 and zero explicitly. In float64, the implementation evaluates the same
trigonometric angle through the positive and negative extrema of the cubic H,
using `atan2(2*sqrt(Hmax)*sqrt(-Hmin), Hmax+Hmin)/3`. The extrema use factored
positive sums; this avoids loss of precision in the acos invariant when the
roots approach the tighter pole. Both directions are explicit and use no
root-search iterations or extended-precision arithmetic.

The analytic release has unit neutral slope, zero neutral curvature, endpoint
slope 21k-20/k, R(0)=0 and R(1)=k. It changes every positive radius for k>1.
The previous p=1.01, d=6 curve had endpoint slope 7k-6/k. The new slope is
approximately three times as large when k is large, and both give slope one at k=1.
The pole is on the spindle side at x=p, where release tends to infinity;
inverse compression tends to p as raw chroma grows. At k=1 the map is identity
and the pole disappears. Public physical mappings clamp float64 roundoff to B
or U and clip at their physical endpoint; the analytical continuation is
exposed only by internal normalized helpers. This clamp is not part of the C2
curve claim.

At fixed interior height, bounded hue-dependent capacity gives the Cartesian
neutral derivative equal to the identity. Cube-face changes may still cause
angular derivative kinks away from neutral. The shoulder refers to the release
curvature beginning to increase again, not a constant piecewise knee location
or a universal strength guarantee. Selecting p=1.001 and d=20 moves this
measured location to about 0.91B; it does not retain the earlier 0.8B placement.

`buck2 build //libraries/perceptual-grade-reference:radial_map_quality --show-output` regenerates the historical
pole diagnostic JSON and Markdown through Buck2. Its retained sample has
116,081 capacities with k=1.0015993…17.209697. Seven sampled capacity quantiles
put the outer curvature minimum at x=0.9061…0.9102 (grid resolution 0.0001).
The maximum sampled relative roundtrip error is 5.71e-16. These measurements
do not certify a uniform shoulder or the fitted capacity geometry. The `//libraries/perceptual-grade-reference:spindle_quality` report evaluates the active production cubic and
cross-implementation parity; it does not evaluate this historical pole map.

Boundary slope alone does not determine radial headroom for the same raw
cube color. With the new pole and d together, at the largest sampled k,
0.9U compresses to 0.94478B (previously 0.96115B). Release sensitivity at the
boundary increases from 120.12 to 360.24; B still maps exactly to U.
The exact-geometry reset witnesses show maximum RGB absolute error 2.65e-10
on the [0,1024] cube. A few ulps in the hard guard's reconstructed energy are
amplified by the steeper boundary, so that combined witness test uses a 4e-10
budget (below 4e-13 of cube white); isolated radial tests retain their stricter
Decimal and roundtrip budgets.

`buck2 build //libraries/perceptual-grade-reference:spindle_release_curve --show-output` generates the standalone
Matplotlib `spindle-release-curve.png` from those capacity quantiles. Both axes
normalize chroma by B. The left panel shows the physical 0<=C_spindle/B<=1
range on linear axes; the right panel shows the analytic continuation to
p=1.001 on a logarithmic output axis. Faint dotted curves show the previous
p=1.01, d=6 release for comparison. Public physical release still clamps at
the spindle boundary. The measured shoulder band is read from the report;
it denotes the seven sampled curvature minima, not a piecewise curve join.

### Historical pole map versus Blender cubic (Step 5.56)

`buck2 build //libraries/perceptual-grade-reference:spindle_blender_comparison --show-output` compares the archived
pole helpers and actual Blender radial helpers using the same seven capacity quantiles.
It generates a four-panel Matplotlib PNG, a JSON audit and a Markdown summary;
the rendered PNG is copied to `perceptual-grade/spindle-blender-comparison.png`.
Solid curves denote the historical p=1.001,d=20 map; dashed curves denote
Blender's current cubic. The panels show release, slope with a near-boundary
inset, compression, and remaining radial margin near cube capacity.

Blender's release is R(x)=x+(k-1)x³, with boundary slope 3k-2 and a closed-form
hyperbolic cubic inverse. Its float64 radial helper, portable CPU bake and GLSL
bake all use this equation, as does the restored active reference. The
historical experiment uses the rational pole
profile above, with boundary slope 21k-20/k and explicit cubic/quadratic
inverse. Both have unit neutral derivative, zero neutral second derivative
and exact B↔U endpoints, and preserve J_A and hue. The nonlinear cubic term
near neutral differs: it is k-1 for Blender, and approximately
.9610584*(k²-1) for the reference. Matching the neutral derivative does not
mean finite low-chroma colors have the same compressed position.

The historical pole map compresses most cube radii farther inward, but the ordering
reverses very close to cube capacity. At the largest sampled k≈17.209697,
.9U maps to .944784B versus Blender's .964074B; .99U maps to .999182B versus
.996520B. The curves cross at about .962311U. Historical pole boundary slope is
about 360.24 versus 49.63, concentrated in a narrow region immediately below B.

The reported margin 1-C_spindle/B is measured on a fixed-J_A ray. It is not a
complete prediction of grading behavior: the grade can change J_A/J_HK and
the guard intersects at fixed J_HK. Both physical wrappers constrain the
output at B; the historical exterior pole supplies no extra physical margin.
This diagnostic changes neither mapping, and does not measure float32/LUT
error or runtime performance.

The Buck2 comparison validates 265,104 roundtrips over twelve capacity ratios,
including k=1 and near-identity cases. The largest normalized errors are
4.44e-16 B for release/entry and 6.22e-15 U for entry/release. Analytic slopes
agree with centered/one-sided five-point differences to a maximum scaled
error of 3.54e-8. These sample checks accompany the fifteen existing spindle
regression tests; they do not constitute a new exact-real proof.

### Piecewise shoulder comparison (Step 5.55, set aside)

`piecewise_spindle.py` evaluates an experimental normalized radial pair beside
the archived pole map. `Model`, its scaled path, Blender and DCTL do not
select this candidate. The user preferred the preceding non-piecewise map;
this candidate is retained as an experiment. The original final combined Lean
audit was interrupted; Step 5.57 subsequently passed the complete checker and
transitive axiom audit, including these retained sources. Build the comparison with
`buck2 build //libraries/perceptual-grade-reference:piecewise_spindle_comparison --show-output`; its PNG, JSON and
Markdown use the seven existing capacity quantiles without refitting D65.
The PNG is also copied to `perceptual-grade/piecewise-spindle-comparison.png`.

For x=C_spindle/B and k=U/B, choose s=3/4 and a=14. The inner-lift control
epsilon is compared at .05, .1 and .25, with .1 the diagnostic default:

```text
A = epsilon*(k-1)/(k*s²)
R(x) = x+A*x³                                           (0 <= x <= s)
rs = s+A*s³; m = 1+3*A*s²; Q = 3*A*s
H = 1072*(k-1) - (1827/2)*A
R(s+t) = rs+m*t+(Q*t²+H*t³)/(1+14*t+196*t²)               (0 <= t <= 1/4)
```

The rational segment matches the inner value, slope and second derivative,
and maps x=1 exactly to k. Its denominator is at least 3/4 for every real t.
For the allowed epsilon range (0,.25], the physical release is increasing
and convex. The bend starts at .75B; near .8B its slope has acquired about
half its boundary increase at large k. This is a slope diagnostic, distinct
from the adopted curve's curvature minimum. Inner release gain at the join
is exactly `1+epsilon*(1-1/k)`. Near neutral the correction is cubic, keeping
unit hue-independent Cartesian derivative for bounded hue-dependent capacity.
This does not remove angular kinks where the active cube face changes.

The compression inverse of the inner branch uses real cube roots. Set
`b=(3/2)*y*sqrt(3*A)` and `u=cbrt(b+sqrt(1+b²))`; then
`x=3*y/(u²+1+1/u²)`. This rationalization retains tiny and subnormal inputs.
For the shoulder, let v=y-rs and solve the unique real cubic:

```text
c3 = 196*m+H; c2 = 14*m+Q-196*v; c1 = m-14*v
c3*t³+c2*t²+c1*t-v = 0
h = c2/(3*c3); p = c1/c3-3*h²; q = (v/c3+h³+p*h)/2
u = cbrt(q+copysign(sqrt(q²+(p/3)³),q))
z = u-p/(3*u)
t = v/(c3*(z²+z*h+h²+p)); x = s+t
```

The final expression is an exact factorization of Cardano's root, avoiding
cancellation near the join. It is not an iterative refinement. All physical
branches use only arithmetic, square roots and real cube roots.

An independent exterior continuation attaches at x=1. Let M=R'(1),
E=R''(1)/2, delta=pole-1, and u=x-1:

```text
R(1+u) = k+M*u+E*u²/(1-u/delta)                         (0 <= u < delta)
Delta = y-k
u = 2*delta*Delta / (M*delta+Delta
                    +sqrt((Delta-M*delta)²+4*E*delta²*Delta))
```

This matches value, slope and curvature, and has a simple pole for k>1.
The implementation scales the inverse quadratic to avoid squaring large
values. At k=1 all branches are exactly identity, with no pole. A finite
inverse too close to represent below the pole returns its float predecessor.
The diagnostic compares poles 1.001, 1.01, 1.025 and 1.05; they produce the
same curve throughout the physical interval. A narrow exterior gap still
concentrates its unavoidable divergence close to the pole, independently of
the newly broadened physical shoulder.

The comparison includes release, its slope, inner lift, exterior continuation,
compression and grading headroom. At the largest sampled k, the default
candidate maps .9U to about .98008B, versus .94478B for the historical pole map.
This lower headroom is a design tradeoff, not a roundtrip error. The candidate
has no new guard or appearance-pipeline integration in this comparison step.
`buck2 test //libraries/perceptual-grade-reference/tests:piecewise_spindle` checks Decimal anchors, both
joins, derivatives, convexity, pole limits, neutral behavior and inverse
roundtrips, including near-identity capacities and subnormal radii.
The experimental float64 helpers accept capacity ratios through 1e8, the
stress-test limit; actual sampled model ratios are below 18. This numerical
qualification limit is not a change to the exact-real curve's k>=1 domain.

The hard guard retains positive J_HK and hue by intersecting the round
spindle at that height. The certificate checks that sqrt(J_A²+66B(J_A))
increases strictly, so this intersection is unique. It leaves interior
coordinates unchanged, projects exterior coordinates onto the surface,
maps J_HK<=0 to black and J_HK>=W to neutral cube white. Projection is
continuous and idempotent, with an intentional derivative kink. Signed
carried energy remains available during grading; guard output has positive
energy before release and decode. Scaled-exponent paths evaluate the same
equations for extreme values.

U uses a crease-selected fitted boundary. Twelve cubic edge traces store hue
and reciprocal normalized radius versus neutral response height. At each
height, hue comparisons select one of the six physical cube faces before
radius lookup. The selected face's affine uint16 table supplies curvature
between its shared edge traces using bilinear interpolation. At setup, each
257 × 257 table samples the original compact tensor-product spline; the old
face polynomials are discarded after sampling. Here u=U/(r_w*t*(1-t)) is normalized capacity:

```text
1/u = (1-s) R_left + s R_right + s(1-s) Q_face(t,s)
```

The correction vanishes at either edge. Adjacent faces therefore meet
continuously while retaining the physical crease's derivative discontinuity;
there is no face mask or maximum of separately evaluated face fields.
A separate one-dimensional spline gives the hard guard's height intersection.
The archive also retains the original 44 float64 profile knots/values, W, f_L,
A_w, both adapter matrices and topology/version/certification metadata.
The adopted NPZ is 61,390 bytes; its decoded numeric fields total 63,214 bytes.
Both fit the 65,536-byte source-resource budget. The six runtime face tables
use 792,588 bytes plus 96 bytes of per-face bounds, offsets and scales. Complete
GPU boundary storage is 1,046,540 bytes, within the adopted 1 MiB budget.
Both CPU and GPU copies count toward the shared 32 MiB math-cache budget.
Blender uploads normalized uint16 codes to one R16 texture (257 × 1542).
Explicit texel fetches recover exact codes with round(value × 65535), then
interpolate codes in float32 before applying the per-face affine decode.
This retains the CPU operation order and avoids filtering across creases.
Cubic edge, guard and profile coefficients remain in the RGBA32F lookup.
Float64 analytic paths use the same codes; the geometric oracle stays separate.

Seven open height bands and eight vertex-tie rows replace the twelve-slot
search. Uniform edge intervals use arithmetic addressing with stored-knot
corrections, and only the selected pair's reciprocal radii are evaluated.
A 7 x 64 x 128 byte table shortlists candidate **edges**, not face IDs. It is
derived at load time from restricted cubic Bernstein bounds with float32
padding. Actual edge curves still decide which face wins. At vertices and for
large unreduced hues, all candidates in the height ring are compared. Cell
seams, hue wrap, sharp creases and exact vertex ties have explicit regressions.
The compact stored resource and its fitted values are unchanged.

The float32 CPU selector collects rows with additional candidate edges once;
subsequent comparisons scan that compact list in the original slot order.
Each row retains its own edge calculations and tie decisions. Large NumPy
arrays and GLSL wrap values in [-4π,4π) using exact additions/subtractions of
the stored float32 2π. CPU arrays of at most 16,384 elements use NumPy remainder:
one C ufunc costs less than the bounded expression's many array operations
on concurrent bake chunks. CPU also uses remainder outside that interval.
These paths are bit-identical, including batch-size changes. GLSL reduces the binary
significand by the exact integer modulus there, since its ordinary `mod`
loses precision for very large angles. This finite bit reduction is not an
equation solver. Distances retain the original unreduced hue and operation
order, including seam rounding. No lookup arrays or numerical mapping change;
LUT schema 24 remains valid. General finite-hue and seam tests cover both paths.


The round-profile certificate remains valid. The adopted bilinear face
approximation is continuous but not C1/C2 within faces, and is not a strict
cube-containment mapping. The user adopted its measured accuracy/range tradeoff:
over 3,525,880 grade evaluations the uint16 experiment reached 0.672894%
maximum above-floor relative RGB error, with RGB extrema -3.281738 and
1024.604126. These are sampled observations, not global bounds. Exact black
and finite output remain required; CPU/GLSL parity still uses 0.1% relative
error with a 1e-7 absolute floor. Production keeps the actual sampled outputs,
records extrema and out-of-cube counts in LUT diagnostics, and adds no final
RGB repair, inward reserve, cone-response guard or machine-range compression.
Format 15 records `profile_certified=true` and `certified=false`; its historical
source-fit audits do not certify the newly sampled field. The strict
`//products/perceptual-grade-blender:bake_check` oracle audit deliberately continues reporting these deviations.

Runtime metadata matching allows platform rounding within
64 float64 epsilons times (1 + abs(cached value)). Exact adapter matches win;
otherwise the closest certified adapter is selected. The loaded context uses
the stored f_L, A_w and adapter for response encoding and RGB decoding, with
immutable arrays. This tolerance identifies
the same D65 context; it does not expand its certified domain or permit another
working white/reference luminance. Format, certification, size and metadata
failures have separate error messages.

The directed face certificate covers each cube face with two triangles.
For cone encoding f and response r, a constant-J_A ray has response velocity
proportional to r-r_neutral. Applying f inverse gives cone velocity
(r-r_neutral)/f'(cone); the native matrix then gives the outward RGB
velocity. Its active-face component is strictly outward on all six faces.
The positive inverse native matrix keeps cones strictly inside their
physical response domain on nondegenerate cube faces. A ray starts at an
interior neutral and cannot re-enter: re-entry would require a non-outward
boundary crossing. Transverse crossings vary continuously by the implicit
function theorem; at face changes the local capacity is the minimum of the
incident face capacities. Normalized black/white limits cover both tips.
This establishes the connected radial interval targeted by the fitted boundary;
bisection is retained only in offline generation and test oracles.

Profile containment uses directed t/hue intervals, tightened by analytic
hue derivatives. Retention uses certified outside points on selected hue
rays; the selected hues are witnesses, not an assumption about the global
minimum. Interval rational powers are checked with scaled integer-power
inequalities; their NumPy seeds need no assumed libm accuracy bound. The
height derivative is checked separately. Positive normalized inverse native
rows put cube cones in [0,1024], whose monotone base encoding stays below
400; a separate cone-response compression is therefore unnecessary for
guarded spindle handoffs and release.

The retained production Lean results check the cubic's derivatives, bounds, inverse existence and
uniqueness, projection/reset properties and conditional cube/cone bounds.
The face/topology argument and directed numerical certificate are separate
from Lean, and neither is a proof of Python's floating-point execution.
The geometric oracle uses an interior reserve of 32 float64 epsilons times
the transformed cone norm. The fitted resource adds its own approximation
reserve. Decode near white uses cone deficits; a projected float32 state uses
its known unit spindle radius instead of reconstructing it from a difference
of nearly equal lightnesses. These are stable evaluations of the mathematical
boundary, not RGB repairs. Sampled full-grade acceptance requires finite,
strict [0,1024] output, exact black, and per-pixel RGB error no greater than
max(0.001 * oracle peak, 1e-7 ACEScg). Exact nonlinear reset bypasses the fitted
round trip. Exact primitive reset tests use the independent geometric oracle;
fitted boundary round trips and boundary inverse results use the RGB tolerance.
The quality report adds two 65³ grids, prior failure witnesses, radial
prefixes, derivative convergence, full-RGB Jacobians, extreme coordinate
requests, existing LUT interpolation and measured CPU cost. Complete graded-stack, Compositor and lifecycle regressions are separate Buck2
tests; adoption measurements are recorded in the workspace checklist.

The round profile retains 44 knots. The previous format-13 profile-only
context used 881 numeric bytes and a 2,097-byte archive; the adopted resource
adds acceleration data within the same aggregate 64 KiB budget. Current
boundary accuracy measurements are in `//libraries/perceptual-grade-reference:boundary_acceleration_audit`.
Sampled round-radius retention is
99.696032%–99.848594% against the fitted boundary. Maximum sampled scalar release slope is 46.417;
full-RGB inverse amplification reaches 71.70 on 128 probes, so the inverse
is not uniformly well conditioned. `//libraries/perceptual-grade-reference:spindle_quality` records distributions,
1,875,321 radial-prefix checks, derivative convergence, LUT errors and CPU
cost. These measured maxima are not universal machine-error bounds.

The oracle is an independent implementation of the complete grade in NumPy
float64, using Colour for the appearance model, colour spaces and adaptation.
It imports no Blender/DCTL mathematics, old reference code, solver or fixtures.
Blender float64 grading implements the same equations independently. The
portable float32 CPU/GLSL bake kernels share source/coefficient data and are
checked against float64 grading with independent geometric solves. DCTL
adoption remains a later migration step.

From the repository root:

```sh
buck2 build //libraries/perceptual-grade-reference:evaluate //libraries/perceptual-grade-reference:documentation '//libraries/perceptual-grade-reference/proofs:color_model[report]'
buck2 test //libraries/perceptual-grade-reference/tests: //libraries/perceptual-grade-reference/tests/proofs:color_model -- --timeout 3600
echo '{"values":[[0.18,0.18,0.18]],"linear":{"exposure":1}}' | buck2 run //libraries/perceptual-grade-reference:evaluate
echo '{"operation":"inverse","values":[[0.36,0.36,0.36]],"linear":{"exposure":1}}' | buck2 run //libraries/perceptual-grade-reference:evaluate
```

The CLI accepts `values` with a final dimension of three, `operation` (`forward`
or `inverse`), `space`, `white`, and `linear`, `tone`, `color` settings objects.
It writes JSON containing `value`, plus inverse `residual` and `status`.
The Python API exposes `Model.forward`, `forward_xyz`, `inverse`, `inverse_xyz`,
and component evaluators. Batches preserve their leading dimensions.

### Iteration-free boundary evaluation

Build its resource with `buck2 build //libraries/perceptual-grade-core:d65_boundary`, run its boundary
audit with `buck2 build //libraries/perceptual-grade-reference:boundary_acceleration_audit`, and check its
regressions with `buck2 test //libraries/perceptual-grade-core/tests/numerical:boundary_acceleration`.
Runtime boundary evaluation never solves iteratively, including scaled paths.
Direct uniform or fixed binary addressing chooses polynomial cells; spline degree and Horner
evaluation have fixed costs. The former format-14 series evaluator, dormant
old-model GPU implementation and unfinished acceleration-certificate helpers
have been removed with the user's approval. The working geometric oracle and
profile/cone certificates remain.

`//libraries/perceptual-grade-reference:rebuild_d65_boundary` explicitly fits new edge/face/guard tables from the
stored D65 profile. It does not invoke the expensive `//libraries/perceptual-grade-reference:spindle_profile`
generator. Ordinary builds, tests and packaging reuse the adopted NPZ.
Full-grade/device audits, uncached lookup timing and actual installation
with empty per-lattice caches are separate:

```sh
buck2 run //products/perceptual-grade-blender:bake_check -- --candidate libraries/perceptual-grade-core/src/perceptual_grade_core/model/d65_boundary.npz --output-dir buck-out/bake-check --size 65
buck2 run //products/perceptual-grade-blender:boundary_gpu_check -- --candidate libraries/perceptual-grade-core/src/perceptual_grade_core/model/d65_boundary.npz --output-dir buck-out/boundary-gpu-check
buck2 run //products/perceptual-grade-blender:boundary_benchmark -- --candidate libraries/perceptual-grade-core/src/perceptual_grade_core/model/d65_boundary.npz --output-dir buck-out/boundary-benchmark
buck2 run //products/perceptual-grade-blender:grade_bake_profile -- --output-dir buck-out/grade-bake-profile --repeats 3 --uncached --details
buck2 test //products/perceptual-grade-blender/tests/reference_integration:baking //products/perceptual-grade-blender/tests/gpu:baking
```

These require the pinned dependencies. llvmpipe verifies actual GLSL execution
on machines without a physical GPU. Software GPU timing does not establish
physical GPU, native Metal or visible compositor-frame performance.
The audit temporarily installs the old solvers only to time the baseline,
then restores the adopted runtime. Neither iterative oracles nor certificate
tools are included in the extension.

Named RGB inputs use their declared white exactly: XYZ = G*white +
matrix*(RGB-G*[1,1,1]). The linear stage is evaluated as a neutral contribution
plus its complete difference. This is an equivalent real-arithmetic expression
of the RGB primary matrix, and avoids amplifying white-row-sum roundoff into
visible chroma at extreme gains. It has no gray tolerance, pixel cutoff or
output repair; intentional differences from neutral still pass through grading.

## Coordinates and domain

RGB spaces are Linear Rec.709, Linear Rec.2020 and ACEScg; the grading white is
D65 only in this packaged context. XYZ and white XYZ use Y=1 units;
Colour receives values multiplied by 100. The viewing profile is Dark,
Y_b=10, L_A=0.1R, full illuminant discounting. Packaged grading fixes R=203 nits; peak P is bounded to [2R,10000]. There is no whole-nit rounding.
The one-nit transitions use p(t)=6t³−8t⁴+3t⁵: a floor at l is l below l,
l+p(x−l) on [l,l+1], and x above l+1; the upper cap is the reflected profile.
The joins are C2, and the old integer anchor values are unchanged.

Normalize signed CAT16 cones by grading-white cones and compress them without
changing their signs. Let A be the achromatic response, A_w its white value,
γ=Dark.c*(1.48+sqrt(.1)), C=hypot(a,b), and B=sqrt(66C):

```text
J_A = 100 sign(A) |A/A_w|^γ
M = hypot(J_A,B)
H = M             if J_A >= 0
H = 2B-M          if J_A < 0
u = H-B
E = u (|u|+2B) = J_A |J_A|
J_A = sign(E) sqrt(|E|)
```

This signed H–K coordinate agrees with the former H on the positive side,
is continuous across A=0, and has a unique inverse at every real H and C>=0.
Signed neutrals have C=0 and H=J_A. At A=0 with C>0, H=B and the signed
appearance record is nonblack; H=0 is also not a stage-2 black test. Only M=0
identifies stage-2 black. Interior export keeps J_A and hue while reducing C
when the actual decoder escapes the native AP1 cube; J_HK then follows from
the new C. Signed energy E<=0 exports black and E>=W² exports cube white.
Either achromatic sign may still cross zero during grading; export is the
point where negative achromatic/cone responses are eliminated.
Carry signed energy separately so tiny achromatic values survive when rounded
H equals B. Negative H and negative energy are valid. Malformed/nonfinite
records are errors. Low-level appearance helpers take an effective viewing
reference in [48,1000]. The cube export guard rejects response-pole trials
and saves only decoded, finite AP1 RGB inside [0,1024]³.

Forward input must contain finite triples. Controls must be finite, directional
axes have length two, and color tables have four tonal rows. Lightness/chroma
rows have columns low, high, a, b; Adaptance has two columns. The tonal web has
six columns for each of its three fields. Production-compatible settings also
retain their two-column concentration table.
Fits are finite continuous values. Tone input levels have length five and negative
nits map to zero. An explicit finite 3×3 XYZ matrix replaces all linear control
construction and may be singular. The web additionally requires ordered hue
targets and finite positive geometry coefficients; invalid targets are errors.
Every finite scene RGB triple with accepted controls completes the full
forward grade with finite RGB.
The export bound is native ACEScg [0,1024]^3. There is no float32 machine-range
compression. Grading intermediates may require scaled exponents; guarded RGB handoffs are bounded.
The DCTL uses the same raw-coordinate design and float32 cube export search.
Unknown categorical identifiers, invalid shapes and
NaN/Inf input or controls are errors.

## Linear stage

Colour supplies normalised primary matrices and CAT16 adaptation. Source xy
is clamped to [0,.9]² and projected onto the nearest boundary of the CAT16
positive polygon. Its halfplanes require y≥.002 and a .002 xy margin from
each cone-zero line. Nonfinite xy is an error. This is Euclidean projection in xy.

The directional basis comprises the grading white and adapted Rec.709 red/blue
xy anchors, each moved to 30% of its distance from white. Heading rotates
an anchor around white; spread scales that vector by 1+spread/100, and target
y is floored at .01. Balance scales its target XYZ by 2^(-balance).
The directional matrix maps the three source basis vectors to these targets.
The complete matrix is 2^exposure times directional times CAT16 adaptation.
Equal whites and zero directional controls produce the identity exactly.
Heading is reduced periodically before trigonometric evaluation. Scaled
mantissas/exponents keep exposure, balance and directional targets representable
internally for extreme finite controls. An unrepresentable complete matrix is
retained as scaled entries rather than replaced with an earlier-stage matrix.

## Tone and coefficient curves

Write σ(x)=exp(x)/(1+exp(x)), φ(x)=log(1+exp(x)). The exact interval kernel is

```text
K(t;l,r,w) = w[φ((t-l)/w)-φ(-l/w)-φ((t-r)/w)+φ(-r/w)]
K'(t) = σ((t-l)/w)-σ((t-r)/w)
w = .05 * 2^(-fit)
```

The implementation evaluates an independently derived log-domain expression
for this integral, including negative t. It uses no runtime quadrature or table.
For l<r,w>0, K is strictly increasing, K(0)=0 and K(1)>0.
Width remains a positive scaled value at extreme fits. Normalized quotients
are evaluated directly, including their rounded narrow/wide-width limits,
so a tiny or huge width does not introduce a 0/0 normalizer.

Neutral appearance values convert five input/output nits anchors to J_A/100.
Output anchors are 0, .015507796089266005R, .18R, R, P; the Shadows ratio is
derived by `buck2 build //libraries/perceptual-grade-core:shadow_anchor`. At the fixed R=203/P=1000-nit
calibration, it minimizes squared logarithmic errors of the four consecutive
J_A gaps against a fitted geometric progression. The other fixed landmarks
prevent an exact progression. The target emits the independent 80-digit
derivation, neutral inverse and unique-minimum bound in `report.json` and
`summary.md`; production uses the derived literal directly. Normalized black and
white are pinned to 0 and 1. Input appearance anchors receive sequential
.001 spacing. Normalize the input knots by black b and span s. The tone curve is

```text
t = max(0, (M/100-b)/s)
m = min_i Δtarget_i/Δknot_i
r_i = max(0, Δtarget_i-m Δknot_i)
T(M) = 100 [m t + Σ_i r_i K(t;k_i,k_(i+1),w)/K(1;k_i,k_(i+1),w)]
```

Its positive baseline gives a strictly increasing nonblack branch and linear
positive tail; black is a plateau. The upper anchor is pinned exactly in float64.
An exactly identical source/target curve is the identity; there is no reset
tolerance. There is no extra cone-response guard. The response encoding's
400 asymptote and the decoder's explicit pole-domain check remain part of
modCAM16 itself. Raw graded appearance can cross that response domain; only
the cube guard accepts decoded RGB and returns its saved legal candidate.
For stage 2, the positive quadratic gain
g=2T²/(hypot(66C,2J_A T)+66C) scales both a,b and J_A. It solves
J_A²g²+66Cg=T², preserving the sign of J_A and C/|J_A| when defined.
Recompute signed H from the scaled J_A,a,b. The black plateau can map a
nonzero magnitude to zero; there is no sign clipping or failed-fit passthrough.

Coefficient curves use the clamped quintic q(t)=t³(10-15t+6t²), interval kernels
on the smoother output knots, and cumulative minima after clipping to [0,1].
Writing these ordered transitions u0≥u1≥u2≥u3≥0, J/C tonal weights are
(1-u1,u1-u2,u2-u3,u3). Warp/Adaptance instead use the cardinal S₅ weights
described above. Tables use Shadows, Midtones, White, Highlights order.

## Creative stage

Retained lightness/chroma drivers sample stage-2 appearance once. The web
then reads its input hue, followed by selective cone-derived Adaptance, H–K
repair and final saturation Scale; see the current-order section above.
Coefficient weights and Adaptance log gains use magnitude M, so negative
achromatic colors receive the same tonal weighting as their positive-magnitude
counterparts. Let

```text
V = C²/(C²+4),  k = 35/75 = 7/15,  r = k |J_A|
low = V r²/(C²+r²)
high = V C²/(C²+r²)
opponent drivers = (a,b)/hypot(C,2)
```

Neutral uses zero drivers. Low+high=V, with equal membership at C=(35/75)|J_A|.
For C>0, low>high exactly below this crossover; both equal V/2 on it.
At J_A=0,C>0, low=0 and high=V. Membership is invariant under common nonzero
scaling of C and J_A; visibility is not. Membership depends on neither hue nor
boundary capacity and is symmetric in the sign of J_A. A creative chroma gain can fold this response, so a full inverse is not
globally unique even on ordinary positive inputs.

Chroma gain is 2^(global_gain+dot(chroma coefficients,drivers)). Lightness
adds the analogous driver-weighted coefficient sum to signed H. Both directions
of achromatic sign crossing are allowed. In the corrected reference, the
adapted request then passes through H–K repair before the web's final positive
Scale; the frozen Blender product retains its historical export-time repair.

The following hue formula remains in DCTL only; its test oracle is
`tests/support/dctl_reference.py`. For interpolated concentration
v=(v_a+i v_b), t=|v|/.6 and
w=V v tanh(t)/t (the t=0 ratio is one). Thus |w|<.6<1. At C>0 let
z=(a+ib)/C and apply C(z+w)/(1+conj(w)z). This preserves C, is inverted
by -w and preserves circle orientation. Hue then rotates by the interpolated
hue plus the two global hue controls weighted by low/high drivers.

Adaptance adds the interpolated two-component vector times

```text
r(C) = 1/4 + (3/4)/(1+(C/30)²)
A(M,C,a) = M/100 * a r(C)/(1-a+a r(C)),  a=clip(strength,0,1)
```

A is between zero and M/100. Only M=0 bypasses creative changes.

## Historical signed coordinate inverse and carried energy

Every creative request (H,a,b) determines signed energy with the equations
above. Decode its achromatic response as
A=A_w sign(E)|E|^(1/(2γ))/100^(1/γ), then solve the linear response equations.
Changing H through B crosses achromatic zero continuously, without replacing
an invalid request or falling back to an earlier stage. The standalone
raw-coordinate decoder has no H–K guard or scalar inverse. The corrected
complete grade applies H–K repair inside Stage 3 and RGB inverse baking
validates candidates against that complete map plus cube containment, without
an additional RGB fit. The fixed-reference scalar inverse remains a
mathematical probe, not the inverse of the full nonlinear grade.

For a stage-2 anchor J0,H0,C0, carry E0=J0|J0|. Compute the small coordinate
gap without subtracting nearly equal M and B:

```text
B0 = sqrt(66C0),  B = sqrt(66C)
u0 = E0/(hypot(J0,B0)+B0)             (zero at the origin)
ΔB = 66(C-C0)/(B+B0)                 (zero when B=B0=0)
Δu = (H-H0)-ΔB,  u = u0+Δu
slope = |u|+|u0|                    if u*u0 >= 0
slope = (u²+u0²)/(|u|+|u0|)          otherwise
ΔE = Δu (slope+2B)+2u0 ΔB
```

Use E0+ΔE for small relative changes and u(|u|+2B) for large changes; these
are the same exact equation. At unchanged coordinates ΔE=0, preserving signed
energy even if H0 rounds to B0. Decode achromatic changes with sign-aware
relative powers when source/target energies share a sign, and the direct
signed expression when crossing zero. No epsilon-based sign or cone snapping
is used.

## Input projection and LUT transport

Repair input in native AP1 before every CPU/Shader/Compositor/scopes lookup,
including the pending path. In-domain input is exactly unchanged. Otherwise,
with positive unit-sum AP1 luminance weights,

```text
Y = dot(weights, RGB); k = max(0,-min(RGB))
v = Y/(Y+k)*(RGB+k*[1,1,1])                   k>0 and Y>0
v = black                                    k>0 and Y<=0
v = RGB                                      k=0
input = v*1024/max(1024,max(v))
```

Normalized intermediates avoid overflow. This continuous, idempotent map is
noninvertible. The lower repair preserves positive luminance until the upper
common scaling becomes active; the latter preserves linear RGB ratios.
Tetrahedral fractions are in [0,1], with no extrapolation. Preview uses a 33^3
grid (35,937 vertices); the final LUT uses 65^3. Preview vertices lie at every
second final grid coordinate and are reused exactly during refinement.
The log1p kappa=.01 shaper and atlas layout are unchanged.
An empty Stack bakes the identity directly in native AP1, preserving exact
cube edges without a matrix round trip.

Inputs are repaired into [0,1024]^3; the adopted sampled boundary can export
slightly outside that cube, as measured above. Compositor keeps
the RGBE base plus three edge-difference planes and four texture reads.
There is no post-lookup RGB repair. Convex interpolation stays within the
sampled values' convex hull; it cannot remove existing sample overshoot.
RGBE/half packing, float32 evaluation and adapters can introduce additional
excursions. Those are measured, rather than claimed to be exact machine-level
bounds. Model/LUT schemas are 10/27; older images and kernels are rejected
and rebuilt.
A valid native AP1 result can contain negative Rec.709 scene components.

## Signed extension and arithmetic

The complete nonlinear grade acts on signed normalized cones through Stage 3,
where H–K repair follows Adaptance and precedes Warp Scale. It returns a repaired
appearance state. Stack handoffs carry that state and skip only RGB cube
containment; RGB export applies cube containment without another H–K repair.
There is no paired neutral lift/subtraction, full/tone/linear retry, invalid
zero placeholder or fallback-level API. The final cube guard maps nonpositive
post-repair E to black and E>=W² to cube white. On the nonnegative-H branch,
H–K repair can rescue negative raw energy before Warp Scale; negative-H
requests bypass repair and retain the black export policy. Low-level `appearance.decode`
retains signed mathematical decoding with explicit pole-domain errors.
Matrix conversions use neutral plus chromatic differences to preserve neutral
rays without a tolerance boundary.

`scaled.py` uses Float64 mantissas and Python integer binary exponents. It
extends exponent range without adding arbitrary-precision real arithmetic.
Vector and scaled paths evaluate the same grading, in-Stage-3 H–K repair and
cube guard equations;
white-distance decoding avoids upper-face cancellation. Tests compare their
overlapping domains and extreme finite control inputs.
All such arithmetic still rounds at float64 mantissas; the proofs concern the
exact equations and do not assert IEEE-level continuity or correct rounding.

## Complete inverse contract

The nonlinear forward map is not globally invertible: input repair, cube export,
and creative controls can merge distinct source colors. Every inverse is therefore
a finite found-root search. It reports the actual forward reproduction residual;
a result above the acceptance limit is an approximation, not evidence that the
target is unreachable. Matching forward/inverse Stack stages can pass raw signed
appearance coordinates directly and cancel exactly.

`reference.stack.nonlinear_inverse` is the independent float64 oracle. It searches
legal AP1 input RGB with multiple starts and at most 128 damped least-squares
iterations per start. Raw handoffs compare `(H, J_A, a, b)` before export; RGB
requests compare the complete exported result in canonical Rec.709. Its root
threshold is `2e-10`. Among found roots it chooses squared asinh distance to the
identity prior in canonical RGB, then lexicographic RGB. Otherwise it chooses
lowest measured residual before distance. This oracle does not share the portable
inverse's reduced search. There is no global root enumeration, convergence proof,
or guarantee of a unique preimage.

## Retained production inverse used by Stack baking

The shared portable inverse evaluates repaired native AP1 lattice samples on
CPU or Blender's real GLSL compute path. Public
`reference.stack_bake.BakeStack` exposes it only for settings with zero low/high
lightness/chroma coefficients; other settings raise `NotImplementedError`.
Product tests and analysis use an explicit legacy-capacity adapter for full
production grades. The equations below describe that retained production
solver, including its capacity-based selector. `bake_native` returns
RGB plus a diagnostic residual; `apply_native` also applies input preparation
and the two endpoint matrices. The DCTL inverse uses the same finite search
shape. Inverse root ranking occurs before inverse Stage 1, allowing endpoint
matrix edits to reuse the nonlinear LUT. Candidate input RGB is constrained to
`[0,1024]^3`; this is a search constraint, not an output repair.

The inverse first validates the repaired identity prior. If necessary it also
checks black and one reconstructed candidate, then returns the best validated
choice. There is no later RGB refinement. A simple tone/global-chroma-gain
family obtains the reconstructed candidate by direct tone and gain inversion.
Its feasibility check decodes the resulting raw appearance to actual AP1 RGB
and tests finite in-cube channels; fitted capacity alone cannot certify it.
The tone inverse uses a prepared lookup table, so it solves no per-pixel tone
root. A general creative grade uses the following three-coordinate reduced
search instead of analytically reversing hue:

```text
x = (log J_A, ψ(C) a/C, ψ(C) b/C),       C = hypot(a,b), J_A > 0
u = C/τ
ψ(C) = 2u - u²/2                       0 <= u <= 1
     = 1.5 + log u                       u > 1
C(x_radius) = τ·2x_radius/(2+sqrt(4-2x_radius))   x_radius <= 1.5
            = exp(x_radius-1.5+log τ)              x_radius > 1.5
```

At `C=0`, both Cartesian coordinates are exactly zero. The per-target toe width
`τ` lies in `[2^-126,2]`, using capped target H, energy and opponent magnitude.
The scalar coordinate and its explicit inverse join with two derivatives at
`C=τ`. This describes the search coordinate, not a global smoothness claim for
the capacity fit, cube seams, or complete forward map.

For each trial `x`, decode Cartesian opponents and reconstruct the raw state
`(sqrt(J_A²+66C), a, b, J_A²)`. Run that state through the actual forward grade,
including `U(J_A,hue)` and the low/high driver membership. The residual is
normalized H error plus the two encoded opponent errors. Hue-dependent capacity
makes a two-variable analytical hue reversal circular when low and high hue
handles differ; the third Cartesian coordinate resolves that dependency. The
search uses a three-by-three damped Cholesky step, centered probes, Broyden
updates, three trial step lengths, and at most eight iterations. It retains
per-pixel bounds, active-lane identities and the last tested candidate.

Every reconstructed candidate passes tone inversion, AP1 RGB construction,
and a complete forward reproduction check. Raw handoffs accept normalized
component errors at most `1e-4`, dividing each `(H,J_A,a,b)` error by one plus
the target component's magnitude. RGB requests use an inclusive canonical
Rec.709 criterion before inverse Stage 1:

```text
max(abs(forward(candidate)-target))
    <= max(0.0001*max(abs(target)), 0.00003)
```

The absolute RGB allowance dominates when the target peak is below `0.3`.
Reported RGB errors divide by `max(max(abs(target)),1e-4)`; the threshold is
converted to those diagnostic units. Accepted candidates rank by squared
asinh distance to the identity prior and then lexicographic RGB. Otherwise
lower actual residual wins. The searched candidate is exported using the
current decoded-AP1 cube guard. The guard retains the last tested-valid RGB;
its fitted capacity lookup is a seed, not a legality certificate. Approximate
results keep their measured residual instead of silently claiming success.

The active CPU/GLSL inverse checks include unequal low/high hue handles,
neutral and toe behavior, signed raw requests, tone tables, and actual llvmpipe
compute. The DCTL interface checks also cover unequal hue handles. These
sampled checks do not prove universal inversion or source-root agreement.

### Historical inverse studies

Earlier two-variable spindle inverses, their closed-form entry/release, and
stage-specific boundary feasibility are historical. Their performance and
selection studies remain in `buck-out/inverse-selective-decode/`,
`buck-out/stack-photo-error-chroma-toe/`, `buck-out/inverse-chroma-toe-profile/`,
`buck-out/inverse-tone-lookup-only/`, and `buck-out/inverse-seed-study/`.
Those saved counts and timings do not describe the active raw-coordinate
inverse. The current tone table retains the prepared normalized inverse
coordinate and analytic high tail; its preparation occurs once for each
active inverse tone curve, before worker execution.

### Benchmark commands and archived tuning policies

Run the computation benchmark with
`buck2 run //products/perceptual-grade-blender:inverse_bake_profile -- --output-dir buck-out/inverse-bake-profile`.
It computes a fresh 65³ LUT for every trial, reports CPU and software-GPU
timings, setup, residuals and worst device disagreement, and does not include
UI scheduling, texture installation, RGBE packing or compositor rendering.
The CPU benchmark defaults to four workers with 65,536-row batches; use
`--cpu-chunk 4096` to measure smaller batches. Shader dispatch/readback uses
4,096 rows. Approximate counts indicate residuals above the applicable
per-pixel acceptance limit, not proof of unreachability. Saved baseline arrays
are reclassified with the current rule when reporting roots gained or lost;
the original baseline report retains its historical acceptance counts.

The profiler can temporarily override RGB acceptance and the Stage 3 cap with
`--rgb-relative-tolerance 0.00001 --rgb-absolute-tolerance 0.000003
--stage3-iterations 80`. It also accepts `--raw-tolerance`,
`--stage3-stopping-tolerance` and `--tone-table-tolerance`. These study settings
apply to both CPU and compiled GLSL; omitted settings inherit current defaults,
and every override is restored after the study. Current studies use at most
80 rounds; 160-round results remain historical experiments. Direct
tone-only inversion has no iterative search. First-dispatch shader/driver
costs remain in the recorded trials; report them separately from medians.

For accumulated errors, run
`buck2 run //products/perceptual-grade-blender:inverse_tolerance_chain -- --output-dir buck-out/inverse-tolerance-chains`.
It compares fixed acceptance policies on 17³ sources through
one, two and four explicit RGB forward/inverse handoffs. Source reconstruction
and forward reproduction are separate: guards can lose information even when
an inverse reproduces the target. Targets are reused between policies only
to isolate numerical changes; this is an accuracy study, not a timing test.
The historical `baseline40` uses relative .001 and absolute .0003;
`strict40` retains the historical 40-round cap with relative .0001 and absolute
.00003. Those RGB tolerances remain current, while production uses eight rounds.
Use `--policy strict100_40 --policy strict100_80` for relative .00001 and
absolute .000003 (100× tighter than the historical baseline, 10× tighter
than the adopted default). Default chain experiments stop
at 80 rounds; historical `strict160` is available only by explicit selection.

For CPU phase timing, use
`buck2 run //products/perceptual-grade-blender:inverse_bake_profile -- --output-dir buck-out/inverse-candidate-profile --case tone --case mixed_tone --repeats 3 --breakdown`.
`mixed` retains the prior neutral-tone creative controls; `mixed_tone` adds
tone input anchors `(0, 7, 45, 203, 1000)`. The optional profiler wraps the
existing functions and verifies bit-identical results against an additional
uninstrumented CPU bake. It separates Stage 3 inverse solving, Stage 2 tone
undo, candidate RGB construction and complete forward validation. Route counts
record accepted priors, direct/solved candidates, remaining approximations
and the number of tone lookups and complete forward evaluations. Compare against a saved report with
`--baseline-dir`; saved outputs are used only for accuracy comparison, never
to calculate the current LUT. General RGB refinement was removed after the
Step 5.29 profile; the independent float64 oracle retains its separate search
implementation. The extension now shares the portable solver.

To isolate software-GPU startup, run
`buck2 run //products/perceptual-grade-blender:inverse_gpu_startup -- --output-dir buck-out/inverse-gpu-startup`.
It uses an empty isolated Mesa driver-cache directory, traces actual Blender
GPU calls and retains two complete fresh-grade bakes. The first dispatch can
include deferred driver compilation. Native texture reads synchronize results;
dispatch/read times do not independently measure shader arithmetic. The trace
includes Blender import/GPU initialization, but not earlier Python/module startup.

Phase timings are exclusive elapsed intervals on the worker finishing last;
host/idle time completes that measured job timeline. Other workers overlap
it. Separate sums across workers are also reported and must not be interpreted
as bake latency. One instrumented full-grid trace is added per selected case;
wrapper overhead and scheduling variation can change its elapsed duration.
GPU totals use the fused production shader; CPU phases are not GPU timings.

The historical initial full-grid audit did **not** certify device agreement.
Reset and the tested raw forward/inverse gain pair passed, but guarded RGB inverse root
selection is unstable near hard projection: 169 chroma, 160 mixed-control,
194 tone and 17,031 reduced-chroma vertices fail the 0.1%/1e-7 device tolerance.
Some select substantially different preimages with almost identical forward
reproduction errors. Root selection and unreachable-target approximation need
further work before that backend could replace the extension's inverse. Those
spindle-era counts do not characterize the current raw-coordinate implementation;
small oracle/regression tests still do not substitute for a fresh full-grid audit.

## Dependency provenance

Primary sources: [Colour Hellwig implementation](https://github.com/colour-science/colour/blob/v0.4.7/colour/appearance/hellwig2022.py),
[ACEScg specification](https://docs.acescentral.com/encodings/acescg/),
[Lean release](https://github.com/leanprover/lean4/releases/tag/v4.35.0),
[mathlib manifest](https://github.com/leanprover-community/mathlib4/blob/56a005855ea17e0b0958f73ec801ae140b0a1679/lake-manifest.json).
The stimulus and AP1 chromaticities are external anchors; grading equations and profile
choices are this project's mathematical specification, not external colorimetric
ground truth.

NumPy 2.5.3, Colour 0.4.7, CPython 3.13.6, Lean 4.35.0 and mathlib revision
56a005855ea17e0b0958f73ec801ae140b0a1679 are pinned in Buck2. The eight mathlib
dependencies are commit/hash-pinned in `third_party/proof_sources.bzl` and built
from sources via local Lake paths. No host Lean/elan, git fetch, cache server,
npm or pip resolution is required. Pinned zstandard unpacks the Lean archive.
The DCTL host and portability checks use bundled Clang 23.1.0 with hash-pinned
matching OpenCL headers. Buck2 and the native OS SDK/graphics runtime are host
prerequisites; the tested Buck2 revision is recorded in the workspace checklist.

## Machine-checked theorem correspondence

Lean checks real-valued equations; it does not execute or verify Python/NumPy.
Directed interval certificates cover the retained profile and cube-ray geometry;
the new acceleration certificate remains unfinished. Independent Decimal and
numerical tests check implementations. The corrected reference repairs
appearance before Scale and uses the validated cube guard at RGB export.
Historical cubic, pole and piecewise mapping theorem families remain audited
separately.

| Contract | Representative theorems |
| --- | --- |
| Selective cone action and fixed-selector inverse | `selective_physical_cone_equivalence`, `selective_signed_group`, `selective_signed_inverse`, `selective_signed_strict_mono`, `selective_normalized_inverse` |
| Response joins at ±400 (endpoint jets) | `selective_boundary_value_and_slope`, `selective_boundary_second_jet`, `selective_negative_boundary_jets` |
| Direct neutral calibration and normalization | `selective_calibration_positive`, `selective_calibration_target`, `selective_normalization_neutral` |
| Frozen half-influence mask | `selective_reach_bounds`, `selective_reach_half`, `selective_reach_scale`, `selective_reach_neutral_derivative`, `selective_reach_high_chroma_limit` |
| Repaired Warp chart and Scale invariants | `warp_compact_coordinates_scale`, `warp_compact_radius_scale` in `WarpGuardChart.lean`; `warp_scale_energy`, `warp_scale_pad_invariant`, `warp_scale_radius_invariant`, `warp_positive_scale_signed_hk`, `warp_positive_scale_height_monotone`, `warp_positive_scale_height_strict_mono`, `warp_positive_scale_height_black`, `warp_repaired_scale_ja_nonnegative`, `warp_repaired_scale_ja_positive`, `warp_repaired_scale_energy`, `warp_repaired_scale_energy_nonnegative`, `warp_repaired_scale_energy_positive`, `warp_repaired_scale_pad_invariant`, `warp_repaired_scale_height_strict_mono` in `WarpRepairedScale.lean` |
| Guarded Warp display | `warp_carried_zero_threshold`, `warp_carried_negative_threshold`, `warp_compact_hue_preserved`, `warp_compact_radius_bounds`, `warp_compact_radius_on_raw_rim`, `warp_compact_radius_strict_interior`, `warp_guarded_raw_rim_moves_interior`, `warp_guarded_chart_interior` in `WarpGuardChart.lean` |
| Historical unrepaired negative-energy Warp Scale diagnostic | `web_negative_scale_signed_hk`, `web_negative_scale_height_positive_iff`, `web_negative_scale_height_derivative`, `web_negative_scale_slope_nonnegative_iff`, `web_negative_scale_slope_zero_iff`, `web_negative_scale_increasing_positive`, `web_negative_scale_physical_ceiling`, `web_negative_scale_turning_point`, `web_negative_scale_final_state_ceiling` in `WarpScaleRay.lean` |
| Positive luminance after H–K repair and ideal cube guard | `hk_repaired_energy_nonnegative`, `hk_repaired_ray_ja_nonnegative`, `hk_repaired_energy_positive`, `hk_repaired_ray_energy`, `hk_repaired_ray_ja_positive`, `hk_repaired_coordinates_energy`, `hk_repaired_ray_chroma_bounds`, `encoded_positive_energy_nonblack`, `encoded_positive_energy_luminance`, `hk_ideal_cube_positive_luminance`, `hk_cube_ray_guard_positive_luminance`, `hk_cube_ray_guard_positive_luminance_from_prefix`, `cube_guard_positive_energy`, `hk_cube_guard_positive_luminance`, `hk_repaired_zero_reference_counterexample`, `hk_zero_reference_cube_black` in `HKCubeLuminance.lean` |
| Linear solver and bounded saturation display | `linear_saturation_scale`, `linear_saturation_center_target`, bounded-saturation lemmas in `SelectiveAdaptance.lean`, `web_signed_saturation_scale` |
| Tonal web radial calibration, monotonicity and C² | `web_radial_calibrates`, `web_radial_derivative`, `web_radial_strict_mono`, `web_radial_c2` |
| Cardinal tone weights and actual hue sectors | `web_blend_anchors`, `web_s5_clamped_c2`, `web_hue_sector_slope_positive`, `web_hue_join_c2` |
| Web scale and fixed-tone geometry | `web_signed_saturation_scale`, `web_staged_jacobian_positive`, `web_full_neutral_derivative` |
| Tone and retained production drivers | `kernel_strictMono`, `tone_strictMono`, `drivers_complement` |
| Retained production 0.4U crossover and driver regions | `membership_bounds`, `membership_scale`, `membership_abs_crossover`, `drivers_crossover`, `capacity_low_driver_gt_high_iff`, `driver_neutral`, `driver_bounds` |
| Retained production quadratic response and hue-independent neutral derivative | `driver_neutral_quadratic_bound`, `capacity_drivers_neutral_derivative` |
| Actual-cube projection | `cube_guard_identity`, `cube_guard_idempotent`, `cube_guard_preserves_ja_hue`, `cube_guard_chroma_nonincrease`, `cube_guard_containment` |
| Saved tested-RGB projection | `validated_cube_guard_identity`, `validated_cube_guard_idempotent`, `validated_cube_guard_preserves_ja_hue`, `validated_cube_guard_nonincrease`, `validated_cube_guard_containment` |
| Signed appearance and carried energy | `signed_hk_unique`, `hk_coordinate_inverse`, `carried_energy_reset`, `signed_compression_inverse` |
| H–K knee and reset | `hk_guard_delta_bounds`, `hk_guard_energy_identity`, `hk_guard_energy_positive`, `hk_guard_energy_above_request`, `hk_guard_energy_c2`, `hk_guard_normalized_knee_jets`, `hk_guard_reset_energy`, `hk_guard_neutral_energy` |
| Bounded H–K repair and hue | `hk_guard_allocation_bounds`, `hk_guard_projection_energy`, `hk_guard_projection_chroma_bounds`, `hk_guard_projection_lightness_bounds`, `hk_guard_hue_preserved` |
| Fixed-positive-reference H–K inverse | `hk_guard_inverse_parameter`, `hk_guard_inverse_energy_roundtrip`, `hk_guard_inverse_request_roundtrip`, `hk_guard_forward_inverse_residual`, `hk_guard_inverse_residual_strict_mono`, `hk_guard_inverse_exists`, `hk_guard_inverse_unique`, `hk_guard_inverse_bracket`, `hk_guard_active_branch_separation` |
| Signed-to-legacy energy conversion | `hk_guard_signed_deficit_nonnegative_branch`, `hk_guard_signed_deficit_negative_branch` |
| Input repair | `input_repair_bounds`, `input_repair_identity`, `input_repair_idempotent`, `input_repair_continuous` |
| C2 profile | `rounded_hinge_c2`, `rounded_corner_c2` |
| Historical cubic mapping | `finite_spindle_c2`, `finite_spindle_slope_bounds`, `finite_spindle_inverse_exists`, `finite_spindle_inverse_unique` |
| Historical cubic closed inverse | `finite_spindle_compress_stable_eq`, `finite_spindle_direct_inverse_root`, `finite_spindle_release_compress`, `finite_spindle_compress_release`, `finite_spindle_compress_bounds`, `finite_spindle_compress_c2` |
| Cubic hue-independent Cartesian neutral derivatives | `finite_spindle_cartesian_cubic_bound`, `finite_spindle_cartesian_inverse_cubic_bound`, `finite_spindle_cartesian_neutral_derivative`, `finite_spindle_cartesian_inverse_neutral_derivative` |
| Historical pole-map domains and C2 | `pole_spindle_denominator_pos`, `pole_spindle_radicand_pos`, `pole_spindle_c2` |
| Steeper profile and stable evaluation | `pole_spindle_profile_endpoints`, `pole_spindle_blend_eq_profile` |
| Historical pole derivatives and monotonicity | `pole_spindle_neutral_derivative`, `pole_spindle_neutral_second_derivative`, `pole_spindle_endpoint_derivative`, `pole_spindle_slope_ge_one`, `pole_spindle_global_compression` |
| Historical pole | `pole_spindle_release_tendsto_pole`, `pole_spindle_compress_tendsto_pole` |
| Concrete closed inverse | `pole_cubic_largest_correct`, `pole_cubic_middle_correct`, `pole_spindle_inverse_square_correct`, `pole_spindle_compress_release`, `pole_spindle_release_compress`, `pole_spindle_factored_sqrt`, `pole_spindle_compress_stable_eq` |
| Inverse smoothness and neutral derivatives | `pole_spindle_signed_inverse_c2`, `pole_spindle_compress_c2_on`, `pole_spindle_inverse_neutral_derivative`, `pole_spindle_inverse_neutral_second_derivative` |
| Historical pole Cartesian neutral derivative | `pole_spindle_cartesian_neutral_derivative`, `pole_spindle_closed_inverse_cartesian_neutral_derivative` |
| Candidate physical shoulder and coefficients | `piecewise_spindle_parameters_safe`, `piecewise_spindle_c2`, `piecewise_spindle_extended_c2`, `piecewise_spindle_join_jets`, `piecewise_spindle_endpoints` |
| Candidate derivatives and monotonicity | `piecewise_spindle_core_neutral`, `piecewise_spindle_tail_derivative`, `piecewise_spindle_tail_second_derivative`, `piecewise_spindle_tail_strict_mono`, `piecewise_spindle_tail_curvature_nonneg` |
| Candidate closed inverse | `piecewise_cardano_root`, `piecewise_core_inverse_roundtrip`, `piecewise_tail_discriminant_positive`, `piecewise_tail_inverse_roundtrip_admissible` |
| Candidate physical roundtrips | `piecewise_spindle_compress_release`, `piecewise_spindle_release_compress`, `piecewise_spindle_reset` |
| Candidate hue-independent neutral derivatives | `piecewise_spindle_cartesian_cubic_bound`, `piecewise_spindle_cartesian_inverse_cubic_bound`, `piecewise_spindle_cartesian_neutral_derivative`, `piecewise_spindle_cartesian_inverse_neutral_derivative` |
| Candidate exterior join, inverse and pole | `piecewise_spindle_exterior_join_jets`, `piecewise_exterior_inverse_bounds`, `piecewise_exterior_release_inverse`, `piecewise_spindle_exterior_tendsto_pole` |
| Historical pole reset | `pole_spindle_reset` |
| Guard and reset | `hard_spindle_idempotent`, `hard_spindle_continuous`, `finite_spindle_reset`, `linear_first_reset` |
| Appearance pairs | `appearance_pair_roundtrip`, `matching_stack_pair_result`, `matching_stack_pair_reset` |
| Conditional decode domain | `spindle_release_cube`, `normalized_cone_bounds`, `guarded_response_domain` |

Profile containment and retained capacity have directed certificates. Containment
of the adopted fixed-expression exporter is checked numerically while its
continuous acceleration certificate remains unfinished. The complete floating-point pipeline and inverse solver have no
formal correctness or global convergence proof. Hard projection and cube-face
changes retain derivative kinks. Historical release conditioning was measured separately from a complete
graded-stack Jacobian. Active reset uses direct repair. The historical
linear-first reset composition assumed cube containment of input repair,
guard identity on entered cube states, and entry/release inversion;
it does not prove Python's matrix arithmetic or the unfinished acceleration
certificate. Independent numerical checks exercise repaired linear results,
signed/HDR inputs and the actual native-node/LUT composition.
Blender tests quantify LUT/Float32/RGBE approximation separately.
