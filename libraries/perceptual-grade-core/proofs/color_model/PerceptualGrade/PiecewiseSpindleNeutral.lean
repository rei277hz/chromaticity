import PerceptualGrade.PiecewiseSpindleInverse
import PerceptualGrade.PoleSpindleNeutral

namespace PerceptualGrade
noncomputable section
open Set Filter Asymptotics
open scoped Topology

/-- The actual release has a cubic remainder uniformly bounded independently of k. -/
theorem piecewise_spindle_release_neutral_bound (eps k y : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) (hy : 0 ≤ y) (hy1 : y ≤ 1/2) :
    |piecewiseSpindleRelease eps k y-y| ≤ (4/9)*y^3 := by
  obtain ⟨ha, _, hab⟩ := piecewise_spindle_coefficient_bounds eps k he hk
  have hjoin : y ≤ 3/4 := by linarith
  simp only [piecewiseSpindleRelease, joined, hjoin, ite_true, piecewiseSpindleCore]
  rw [add_sub_cancel_left, abs_of_nonneg (mul_nonneg ha (pow_nonneg hy 3))]
  exact mul_le_mul_of_nonneg_right hab (pow_nonneg hy 3)

/-- The actual compressor uses its explicit core branch throughout a neutral ball. -/
theorem piecewise_spindle_compress_neutral_bound (eps k y : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) (hy : 0 ≤ y) (hy1 : y ≤ 1/2) :
    |piecewiseSpindleCompress eps k y-y| ≤ (4/9)*y^3 := by
  by_cases hk1 : k=1
  · simp [piecewiseSpindleCompress, hk1]
    positivity
  obtain ⟨ha, _, hab⟩ := piecewise_spindle_coefficient_bounds eps k he hk
  have hjoin : y ≤ piecewiseSpindleRs (piecewiseSpindleA eps k) := by
    unfold piecewiseSpindleRs
    nlinarith
  simp only [piecewiseSpindleCompress, hk1, ite_false, hjoin, ite_true]
  let x := piecewiseCoreInverse (piecewiseSpindleA eps k) y
  have hx : 0 ≤ x := by
    dsimp [x, piecewiseCoreInverse]
    positivity
  have hroot : x+piecewiseSpindleA eps k*x^3=y :=
    piecewise_core_inverse_root (piecewiseSpindleA eps k) y ha
  have hxy : x ≤ y := by nlinarith [mul_nonneg ha (pow_nonneg hx 3)]
  change |x-y| ≤ (4/9)*y^3
  rw [abs_of_nonpos (sub_nonpos.mpr hxy)]
  have hp := pow_le_pow_left₀ hx hxy 3
  have hpA := mul_le_mul_of_nonneg_left hp ha
  have hpB := mul_le_mul_of_nonneg_right hab (pow_nonneg hy 3)
  nlinarith

variable {E : Type*} [NormedAddCommGroup E] [NormedSpace ℝ E]

/-- Cartesian radial lift of the complete physical release, preserving hue. -/
def piecewiseSpindleCartesian (B eps : ℝ) (k : E → ℝ) (v : E) : E :=
  if ‖v‖=0 then 0 else (B*piecewiseSpindleRelease eps (k v) (‖v‖/B)/‖v‖) • v

/-- Cartesian radial lift of the actual closed-form compressor. -/
def piecewiseSpindleCartesianInverse (B eps : ℝ) (k : E → ℝ) (v : E) : E :=
  if ‖v‖=0 then 0 else (B*piecewiseSpindleCompress eps (k v) (‖v‖/B)/‖v‖) • v

/-- Transfer a uniform scalar cubic bound to a Cartesian radial map. -/
theorem piecewise_spindle_radial_cubic_bound (B : ℝ) (k : E → ℝ)
    (g : ℝ → ℝ → ℝ) (hB : 0 < B) (hk : ∀ v, 1 ≤ k v)
    (hg : ∀ κ y, 1 ≤ κ → 0 ≤ y → y ≤ 1/2 → |g κ y-y| ≤ (4/9)*y^3)
    (v : E) (hv : ‖v‖ < B/2) :
    ‖poleSpindleCartesianInverse B k g v-v‖ ≤ (4/(9*B^2))*‖v‖^3 := by
  by_cases hn : ‖v‖=0
  · have hv0 : v=0 := norm_eq_zero.mp hn
    simp [hv0, poleSpindleCartesianInverse]
  have hnpos : 0 < ‖v‖ := lt_of_le_of_ne (norm_nonneg _) (Ne.symm hn)
  have hBn : B ≠ 0 := ne_of_gt hB
  have hy : ‖v‖/B ≤ 1/2 := (div_le_iff₀ hB).2 (by linarith)
  have hbound := hg (k v) (‖v‖/B) (hk v) (by positivity) hy
  calc
    ‖poleSpindleCartesianInverse B k g v-v‖ = |B*g (k v) (‖v‖/B)/‖v‖-1| * ‖v‖ := by
      simp only [poleSpindleCartesianInverse, hn, ↓reduceIte]
      rw [show (B*g (k v) (‖v‖/B)/‖v‖) • v-v =
        (B*g (k v) (‖v‖/B)/‖v‖-1) • v by rw [sub_smul, one_smul]]
      rw [norm_smul, Real.norm_eq_abs]
    _ = B*|g (k v) (‖v‖/B)-‖v‖/B| := by
      rw [show B*g (k v) (‖v‖/B)/‖v‖-1 =
        (B/‖v‖)*(g (k v) (‖v‖/B)-‖v‖/B) by field_simp]
      rw [abs_mul, abs_of_nonneg (show 0 ≤ B/‖v‖ by positivity)]
      field_simp
    _ ≤ B*((4/9)*(‖v‖/B)^3) := mul_le_mul_of_nonneg_left hbound hB.le
    _ = (4/(9*B^2))*‖v‖^3 := by field_simp

/-- No continuity or upper bound on the hue-dependent capacity is needed. -/
theorem piecewise_spindle_cartesian_cubic_bound (B eps : ℝ) (k : E → ℝ)
    (hB : 0 < B) (he : eps ∈ Icc 0 (1/4)) (hk : ∀ v, 1 ≤ k v)
    (v : E) (hv : ‖v‖ < B/2) :
    ‖piecewiseSpindleCartesian B eps k v-v‖ ≤ (4/(9*B^2))*‖v‖^3 := by
  exact piecewise_spindle_radial_cubic_bound B k (piecewiseSpindleRelease eps) hB hk
    (fun κ y hκ hy hy1 => piecewise_spindle_release_neutral_bound eps κ y he hκ hy hy1) v hv

theorem piecewise_spindle_cartesian_inverse_cubic_bound (B eps : ℝ) (k : E → ℝ)
    (hB : 0 < B) (he : eps ∈ Icc 0 (1/4)) (hk : ∀ v, 1 ≤ k v)
    (v : E) (hv : ‖v‖ < B/2) :
    ‖piecewiseSpindleCartesianInverse B eps k v-v‖ ≤ (4/(9*B^2))*‖v‖^3 := by
  exact piecewise_spindle_radial_cubic_bound B k (piecewiseSpindleCompress eps) hB hk
    (fun κ y hκ hy hy1 => piecewise_spindle_compress_neutral_bound eps κ y he hκ hy hy1) v hv

/-- The actual release has the identity Frechet derivative at neutral for arbitrary hue capacities. -/
theorem piecewise_spindle_cartesian_neutral_derivative (B eps : ℝ) (k : E → ℝ)
    (hB : 0 < B) (he : eps ∈ Icc 0 (1/4)) (hk : ∀ v, 1 ≤ k v) :
    HasFDerivAt (piecewiseSpindleCartesian B eps k) (ContinuousLinearMap.id ℝ E) 0 := by
  exact cartesian_neutral_of_cubic_bound _ (4/(9*B^2)) (B/2) (by positivity)
    (by simp [piecewiseSpindleCartesian])
    (piecewise_spindle_cartesian_cubic_bound B eps k hB he hk)

/-- The implemented inverse has the same full Cartesian derivative, not only radial derivatives. -/
theorem piecewise_spindle_cartesian_inverse_neutral_derivative (B eps : ℝ) (k : E → ℝ)
    (hB : 0 < B) (he : eps ∈ Icc 0 (1/4)) (hk : ∀ v, 1 ≤ k v) :
    HasFDerivAt (piecewiseSpindleCartesianInverse B eps k) (ContinuousLinearMap.id ℝ E) 0 := by
  exact cartesian_neutral_of_cubic_bound _ (4/(9*B^2)) (B/2) (by positivity)
    (by simp [piecewiseSpindleCartesianInverse])
    (piecewise_spindle_cartesian_inverse_cubic_bound B eps k hB he hk)

end
end PerceptualGrade
