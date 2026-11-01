import PerceptualGrade.SpindleInverse
import PerceptualGrade.CartesianNeutral

namespace PerceptualGrade
noncomputable section
open Set Filter Asymptotics
open scoped Topology

/-- Uniform cubic error for the actual closed-form compressor. -/
theorem finite_spindle_compress_cubic_bound (k K y : ℝ) (hk : 1 ≤ k)
    (hK : k ≤ K) (hy : 0 ≤ y) :
    |finiteSpindleCompress k y-y| ≤ (K-1)*y^3 := by
  obtain ⟨hx, hxy⟩ := finite_spindle_compress_bounds k y hk hy
  have hi := finite_spindle_release_compress k y hk
  unfold finiteSpindleRelease at hi
  rw [abs_of_nonpos (sub_nonpos.mpr hxy)]
  have hp := pow_le_pow_left₀ hx hxy 3
  have hm := mul_le_mul_of_nonneg_left hp (show 0 ≤ k-1 by linarith)
  have hM := mul_le_mul_of_nonneg_right (show k-1 ≤ K-1 by linarith) (pow_nonneg hy 3)
  nlinarith

variable {E : Type*} [NormedAddCommGroup E] [NormedSpace ℝ E]

/-- Cartesian release at a fixed interior achromatic height, before endpoint clipping. -/
def finiteSpindleCartesian (B : ℝ) (k : E → ℝ) (v : E) : E :=
  (1+(k v-1)*‖v‖^2/B^2) • v

/-- Cartesian lift of production's closed-form scalar compressor. -/
def finiteSpindleCartesianInverse (B : ℝ) (k : E → ℝ) (v : E) : E :=
  if ‖v‖=0 then 0 else (B*finiteSpindleCompress (k v) (‖v‖/B)/‖v‖) • v

/-- Bounded directional capacities suffice; no hue regularity is assumed. -/
theorem finite_spindle_cartesian_cubic_bound (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) (v : E) :
    ‖finiteSpindleCartesian B k v-v‖ ≤ ((K-1)/B^2)*‖v‖^3 := by
  have hB2 : 0 ≤ B^2 := (sq_pos_of_pos hB).le
  have hcoef : 0 ≤ k v-1 := by linarith [(hk v).1]
  have hf : (k v-1)*‖v‖^2/B^2 ≤ (K-1)*‖v‖^2/B^2 := by
    apply div_le_div_of_nonneg_right _ hB2
    exact mul_le_mul_of_nonneg_right (by linarith [(hk v).2]) (sq_nonneg _)
  calc
    ‖finiteSpindleCartesian B k v-v‖ = ((k v-1)*‖v‖^2/B^2)*‖v‖ := by
      unfold finiteSpindleCartesian
      rw [show (1+(k v-1)*‖v‖^2/B^2) • v-v =
          ((k v-1)*‖v‖^2/B^2) • v by rw [add_smul, one_smul, add_sub_cancel_left]]
      rw [norm_smul, Real.norm_eq_abs, abs_of_nonneg (by positivity)]
    _ ≤ ((K-1)*‖v‖^2/B^2)*‖v‖ := mul_le_mul_of_nonneg_right hf (norm_nonneg v)
    _ = ((K-1)/B^2)*‖v‖^3 := by ring

/-- The actual closed inverse has the same uniform cubic remainder. -/
theorem finite_spindle_cartesian_inverse_cubic_bound (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) (v : E) :
    ‖finiteSpindleCartesianInverse B k v-v‖ ≤ ((K-1)/B^2)*‖v‖^3 := by
  by_cases hn : ‖v‖=0
  · have hv0 : v=0 := norm_eq_zero.mp hn
    simp [hv0, finiteSpindleCartesianInverse]
  have hnpos : 0 < ‖v‖ := lt_of_le_of_ne (norm_nonneg _) (Ne.symm hn)
  have hBn : B ≠ 0 := ne_of_gt hB
  have hbound := finite_spindle_compress_cubic_bound (k v) K (‖v‖/B)
    (hk v).1 (hk v).2 (by positivity)
  calc
    ‖finiteSpindleCartesianInverse B k v-v‖ =
        |B*finiteSpindleCompress (k v) (‖v‖/B)/‖v‖-1| * ‖v‖ := by
      simp only [finiteSpindleCartesianInverse, hn, ↓reduceIte]
      rw [show (B*finiteSpindleCompress (k v) (‖v‖/B)/‖v‖) • v-v =
        (B*finiteSpindleCompress (k v) (‖v‖/B)/‖v‖-1) • v by rw [sub_smul, one_smul]]
      rw [norm_smul, Real.norm_eq_abs]
    _ = B*|finiteSpindleCompress (k v) (‖v‖/B)-‖v‖/B| := by
      rw [show B*finiteSpindleCompress (k v) (‖v‖/B)/‖v‖-1 =
        (B/‖v‖)*(finiteSpindleCompress (k v) (‖v‖/B)-‖v‖/B) by field_simp]
      rw [abs_mul, abs_of_nonneg (show 0 ≤ B/‖v‖ by positivity)]
      field_simp
    _ ≤ B*((K-1)*(‖v‖/B)^3) := mul_le_mul_of_nonneg_left hbound hB.le
    _ = ((K-1)/B^2)*‖v‖^3 := by field_simp

/-- Full Cartesian identity derivative, uniformly over all bounded hue capacities. -/
theorem finite_spindle_cartesian_neutral_derivative (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) :
    HasFDerivAt (finiteSpindleCartesian B k) (ContinuousLinearMap.id ℝ E) 0 := by
  exact cartesian_neutral_of_cubic_bound _ ((K-1)/B^2) B hB
    (by simp [finiteSpindleCartesian])
    (fun v _ => finite_spindle_cartesian_cubic_bound B K k hB hk v)

/-- Production's actual inverse has the same hue-independent Cartesian derivative. -/
theorem finite_spindle_cartesian_inverse_neutral_derivative (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) :
    HasFDerivAt (finiteSpindleCartesianInverse B k) (ContinuousLinearMap.id ℝ E) 0 := by
  exact cartesian_neutral_of_cubic_bound _ ((K-1)/B^2) B hB
    (by simp [finiteSpindleCartesianInverse])
    (fun v _ => finite_spindle_cartesian_inverse_cubic_bound B K k hB hk v)

end
end PerceptualGrade
