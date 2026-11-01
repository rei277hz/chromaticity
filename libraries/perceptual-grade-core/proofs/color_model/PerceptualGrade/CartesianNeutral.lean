import PerceptualGrade.Basic

namespace PerceptualGrade
noncomputable section
open Set Filter Asymptotics
open scoped Topology

variable {E : Type*} [NormedAddCommGroup E] [NormedSpace ℝ E]

/-- A uniform cubic remainder establishes a genuine Fréchet derivative. -/
theorem cartesian_neutral_of_cubic_bound (M : E → E) (A δ : ℝ)
    (hδ : 0 < δ) (hzero : M 0 = 0)
    (hbound : ∀ v, ‖v‖ < δ → ‖M v - v‖ ≤ A * ‖v‖ ^ 3) :
    HasFDerivAt M (ContinuousLinearMap.id ℝ E) 0 := by
  have hbig : (fun v => M v - v) =O[𝓝 0] (fun v => ‖v‖ ^ 3) := by
    apply IsBigO.of_bound A
    filter_upwards [Metric.ball_mem_nhds (0 : E) hδ] with v hv
    have hv' : ‖v‖ < δ := by simpa [Metric.mem_ball, dist_zero_right] using hv
    simpa only [Real.norm_eq_abs, abs_of_nonneg (pow_nonneg (norm_nonneg v) 3)] using hbound v hv'
  have hsmall := hbig.trans_isLittleO (isLittleO_norm_pow_id (E' := E) (show 1 < 3 by norm_num))
  apply HasFDerivAt.of_isLittleO
  simpa [hzero] using hsmall

/-- The inverse of a cubic-close expanding map has the same neutral derivative.
No regularity of the directional capacity is assumed. -/
theorem cartesian_inverse_neutral_of_cubic_bound (M N : E → E) (A δ : ℝ)
    (hA : 0 ≤ A) (hδ : 0 < δ) (hzero : N 0 = 0)
    (hbound : ∀ v, ‖v‖ < δ → ‖M v - v‖ ≤ A * ‖v‖ ^ 3)
    (hinverse : ∀ v, ‖v‖ < δ → M (N v) = v)
    (hcontract : ∀ v, ‖v‖ < δ → ‖N v‖ ≤ ‖v‖) :
    HasFDerivAt N (ContinuousLinearMap.id ℝ E) 0 := by
  apply cartesian_neutral_of_cubic_bound N A δ hδ hzero
  intro v hv
  have hn := hcontract v hv
  calc
    ‖N v - v‖ = ‖M (N v) - N v‖ := by rw [hinverse v hv, norm_sub_rev]
    _ ≤ A * ‖N v‖ ^ 3 := hbound (N v) (lt_of_le_of_lt hn hv)
    _ ≤ A * ‖v‖ ^ 3 := mul_le_mul_of_nonneg_left (pow_le_pow_left₀ (norm_nonneg _) hn 3) hA


end
end PerceptualGrade
