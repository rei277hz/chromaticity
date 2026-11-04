import PerceptualGrade.PoleSpindleInverse
import Mathlib.Analysis.Calculus.InverseFunctionTheorem.Deriv

namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped Topology ContDiff

/-- Closed-form signed compression is C2 at every represented radius. -/
theorem pole_spindle_signed_inverse_c2 (k x : ℝ) (hk : 1 ≤ k)
    (hp : x^2 < poleSpindleP) :
    ContDiffAt ℝ 2 (poleSpindleSignedCompress k) (poleSpindleRelease k x) := by
  have hc := pole_spindle_c2_at k x hk hp
  have hd := pole_spindle_release_derivative k x hk hp
  have hn : poleSpindleSlope k x ≠ 0 := ne_of_gt (lt_of_lt_of_le (by norm_num)
    (pole_spindle_slope_ge_one k x hk hp))
  have hs := hc.hasStrictDerivAt' hd (by norm_num)
  let e := (hs.hasStrictFDerivAt_equiv hn).toOpenPartialHomeomorph (poleSpindleRelease k)
  have hx : x ∈ e.source := (hs.hasStrictFDerivAt_equiv hn).mem_toOpenPartialHomeomorph_source
  have hy : poleSpindleRelease k x ∈ e.target := e.map_source hx
  have he : e.symm (poleSpindleRelease k x) = x := e.left_inv hx
  have hcs : ContDiffAt ℝ 2 e.symm (poleSpindleRelease k x) := by
    apply e.contDiffAt_symm_deriv hn hy
    · simpa only [he] using (show HasDerivAt e (poleSpindleSlope k x) x from hd)
    · simpa only [he] using (show ContDiffAt ℝ 2 e x from hc)
  have hg : ∀ᶠ z in 𝓝 x, poleSpindleSignedCompress k (poleSpindleRelease k z) = z := by
    filter_upwards [((continuous_id.pow 2).continuousAt.eventually_lt_const hp)] with z hz
    exact pole_spindle_signed_compress_release k z hk hz
  have hu := (hs.hasStrictFDerivAt_equiv hn).localInverse_unique hg
  exact hcs.congr_of_eventuallyEq hu

/-- On its nonnegative physical domain, the radius compressor is C2 including neutral. -/
theorem pole_spindle_compress_c2_on (k : ℝ) (hk : 1 ≤ k) :
    ContDiffOn ℝ 2 (poleSpindleCompress k) (Icc 0 k) := by
  intro y hy
  have hi := pole_spindle_release_compress k y hk hy
  have hx := hi.1
  have hp : (poleSpindleCompress k y)^2 < poleSpindleP := by
    have := pole_spindle_P_bounds.1
    nlinarith [hx.1, hx.2]
  have hc := pole_spindle_signed_inverse_c2 k (poleSpindleCompress k y) hk hp
  rw [hi.2] at hc
  apply hc.contDiffWithinAt.congr
  · intro z hz
    simp [poleSpindleSignedCompress, hz.1]
  · simp [poleSpindleSignedCompress, hy.1]

/-- The numerically stable closed form has the same C2 physical radius map. -/
theorem pole_spindle_stable_compress_c2_on (k : ℝ) (hk : 1 ≤ k) :
    ContDiffOn ℝ 2 (poleSpindleCompressStable k) (Icc 0 k) := by
  apply (pole_spindle_compress_c2_on k hk).congr
  intro y hy
  exact pole_spindle_compress_stable_eq k y hk hy.1

/-- The inverse slope is the reciprocal release slope at corresponding radii. -/
theorem pole_spindle_signed_inverse_derivative (k x : ℝ) (hk : 1 ≤ k)
    (hp : x^2 < poleSpindleP) :
    HasDerivAt (poleSpindleSignedCompress k) (poleSpindleSlope k x)⁻¹
      (poleSpindleRelease k x) := by
  have hc := pole_spindle_c2_at k x hk hp
  have hd := pole_spindle_release_derivative k x hk hp
  have hn : poleSpindleSlope k x ≠ 0 := ne_of_gt (lt_of_lt_of_le (by norm_num)
    (pole_spindle_slope_ge_one k x hk hp))
  have hs := hc.hasStrictDerivAt' hd (by norm_num)
  apply (hs.to_local_left_inverse hn ?_).hasDerivAt
  filter_upwards [((continuous_id.pow 2).continuousAt.eventually_lt_const hp)] with z hz
  exact pole_spindle_signed_compress_release k z hk hz

/-- Signed extension makes the inverse's neutral derivative two-sided. -/
theorem pole_spindle_inverse_neutral_derivative (k : ℝ) (hk : 1 ≤ k) :
    HasDerivAt (poleSpindleSignedCompress k) 1 0 := by
  have h := pole_spindle_signed_inverse_derivative k 0 hk (by norm_num [poleSpindleP])
  simpa [poleSpindleRelease, poleSpindleSlope, poleSpindleF] using h

/-- The unsigned physical radius has the same one-sided neutral derivative. -/
theorem pole_spindle_compress_neutral_derivative (k : ℝ) (hk : 1 ≤ k) :
    HasDerivWithinAt (poleSpindleCompress k) 1 (Ici 0) 0 := by
  apply (pole_spindle_inverse_neutral_derivative k hk).hasDerivWithinAt.congr
  · intro y hy
    simp [poleSpindleSignedCompress, show 0 ≤ y from hy]
  · simp [poleSpindleSignedCompress]

/-- Vanishing second derivative at neutral also holds for the actual closed inverse. -/
theorem pole_spindle_inverse_neutral_second_derivative (k : ℝ) (hk : 1 ≤ k) :
    HasDerivAt (deriv (poleSpindleSignedCompress k)) 0 0 := by
  have hc : ContDiffAt ℝ 2 (poleSpindleSignedCompress k) 0 := by
    simpa [poleSpindleRelease] using
      pole_spindle_signed_inverse_c2 k 0 hk (by norm_num [poleSpindleP])
  have hdg : DifferentiableAt ℝ (deriv (poleSpindleSignedCompress k)) 0 :=
    (hc.derivWithin (m := 1) (by norm_num)).differentiableAt (by norm_num)
  have hdg' : HasDerivAt (deriv (poleSpindleSignedCompress k))
      (deriv (deriv (poleSpindleSignedCompress k)) 0) (poleSpindleRelease k 0) := by
    simpa [poleSpindleRelease] using hdg.hasDerivAt
  have hcomp := hdg'.comp 0 (pole_spindle_neutral_derivative k hk)
  have hfzero : deriv (poleSpindleRelease k) 0 = 1 := (pole_spindle_neutral_derivative k hk).deriv
  have hinv : HasDerivAt (fun x => (deriv (poleSpindleRelease k) x)⁻¹) 0 0 := by
    convert (pole_spindle_neutral_second_derivative k hk).inv (by rw [hfzero]; norm_num) using 1
    simp
  have he : (fun x => deriv (poleSpindleSignedCompress k) (poleSpindleRelease k x)) =ᶠ[𝓝 0]
      (fun x => (deriv (poleSpindleRelease k) x)⁻¹) := by
    filter_upwards [((continuous_id.pow 2).continuousAt.eventually_lt_const
      (show (0:ℝ)^2 < poleSpindleP by norm_num [poleSpindleP]))] with x hx
    rw [(pole_spindle_signed_inverse_derivative k x hk hx).deriv,
      (pole_spindle_release_derivative k x hk hx).deriv]
  have heq := (hcomp.congr_of_eventuallyEq he.symm).unique hinv
  have hz : deriv (deriv (poleSpindleSignedCompress k)) 0 = 0 := by simpa using heq
  simpa only [hz] using hdg.hasDerivAt

end
end PerceptualGrade
