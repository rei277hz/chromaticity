import PerceptualGrade.CartesianNeutral

namespace PerceptualGrade
open Set Filter Asymptotics
open scoped Topology

theorem visibility_bounds (C : ℝ) : 0 ≤ visibility C ∧ visibility C < 1 := by
  have hp : 0 < C^2+4 := by positivity
  constructor
  · exact div_nonneg (sq_nonneg C) (le_of_lt hp)
  · exact (div_lt_one hp).2 (by linarith)

theorem drivers_complement (U C : ℝ) (h : C^2 + ((2/5 : ℝ)*U)^2 ≠ 0) :
    lowDriver U C + highDriver U C = visibility C := by
  unfold lowDriver highDriver membership
  rw [← mul_add, ← add_div, add_comm]
  rw [div_self h, mul_one]

theorem membership_bounds (U C : ℝ) : 0 ≤ membership U C ∧ membership U C ≤ 1 := by
  unfold membership
  constructor
  · positivity
  · by_cases h : C^2+((2/5 : ℝ)*U)^2 = 0
    · simp [h]
    · apply (div_le_one (lt_of_le_of_ne (by positivity) (Ne.symm h))).2
      nlinarith [sq_nonneg ((2/5 : ℝ)*U)]

theorem membership_scale (U C k : ℝ) (hk : k ≠ 0) : membership (k*U) (k*C) = membership U C := by
  unfold membership
  have eq : (k*C)^2+((2/5 : ℝ)*(k*U))^2 = k^2*(C^2+((2/5 : ℝ)*U)^2) := by ring
  rw [eq, mul_pow]
  simp [mul_div_mul_left, hk]

theorem driver_black : lowDriver 0 0 = 0 ∧ highDriver 0 0 = 0 := by norm_num [lowDriver, highDriver, membership, visibility]

theorem membership_crossover (U : ℝ) (hU : U ≠ 0) : membership U ((2/5 : ℝ)*U) = 1/2 := by
  unfold membership
  field_simp
  ring

/-- Every neutral has zero low/high response, including degenerate cube tips. -/
theorem driver_neutral (U : ℝ) : lowDriver U 0 = 0 ∧ highDriver U 0 = 0 := by
  simp [lowDriver, highDriver, visibility]

/-- The definitions are total on ℝ; physical cube capacities are nonnegative. -/
theorem membership_abs_crossover (U : ℝ) (hU : U ≠ 0) :
    membership U ((2/5 : ℝ)*|U|) = 1/2 := by
  simpa only [membership, mul_pow, sq_abs] using membership_crossover U hU

/-- The shared visibility law does not move the equal-response crossover. -/
theorem drivers_crossover (U : ℝ) (hU : U ≠ 0) :
    lowDriver U ((2/5 : ℝ)*|U|) = visibility ((2/5 : ℝ)*|U|)/2 ∧
    highDriver U ((2/5 : ℝ)*|U|) = visibility ((2/5 : ℝ)*|U|)/2 := by
  have hhigh : highDriver U ((2/5 : ℝ)*|U|) = visibility ((2/5 : ℝ)*|U|)/2 := by
    rw [highDriver, membership_abs_crossover U hU]
    ring
  have hden : ((2/5 : ℝ)*|U|)^2 + ((2/5 : ℝ)*U)^2 ≠ 0 := by
    have hpos : 0 < |U| := abs_pos.mpr hU
    positivity
  have hsum := drivers_complement U ((2/5 : ℝ)*|U|) hden
  constructor
  · linarith
  · exact hhigh

/-- At positive chroma, low dominates exactly below the adopted crossover. -/
theorem low_driver_gt_high_iff (U C : ℝ) (hC : 0 < C) :
    highDriver U C < lowDriver U C ↔ C < (2/5 : ℝ)*|U| := by
  have hv : 0 < visibility C := by unfold visibility; positivity
  have hd : 0 < C^2 + ((2/5 : ℝ)*U)^2 := by positivity
  unfold highDriver lowDriver membership
  rw [mul_lt_mul_iff_right₀ hv, div_lt_div_iff_of_pos_right hd]
  have hs : ((2/5 : ℝ)*U)^2 = ((2/5 : ℝ)*|U|)^2 := by
    simp only [mul_pow, sq_abs]
  rw [hs]
  exact sq_lt_sq₀ (le_of_lt hC) (by positivity)

/-- At an interior physical capacity, low dominates below rho times U. -/
theorem capacity_low_driver_gt_high_iff (U C : ℝ) (hU : 0 ≤ U) (hC : 0 < C) :
    highDriver U C < lowDriver U C ↔ C < (2/5 : ℝ)*U := by
  simpa only [abs_of_nonneg hU] using low_driver_gt_high_iff U C hC

/-- Chromatic values at a zero-capacity tip select only high response. -/
theorem driver_zero_capacity (C : ℝ) (hC : C ≠ 0) :
    lowDriver 0 C = 0 ∧ highDriver 0 C = visibility C := by
  have hs : C^2 ≠ 0 := pow_ne_zero 2 hC
  simp [lowDriver, highDriver, membership, hs]

/-- Visibility uniformly bounds both responses, regardless of capacity or hue. -/
theorem driver_bounds (U C : ℝ) :
    (0 ≤ lowDriver U C ∧ lowDriver U C ≤ visibility C) ∧
    (0 ≤ highDriver U C ∧ highDriver U C ≤ visibility C) := by
  have hv := (visibility_bounds C).1
  have hd : 0 ≤ C^2 + ((2/5 : ℝ)*U)^2 := by positivity
  have hl : ((2/5 : ℝ)*U)^2 / (C^2 + ((2/5 : ℝ)*U)^2) ≤ 1 := by
    by_cases hz : C^2 + ((2/5 : ℝ)*U)^2 = 0
    · simp [hz]
    · apply (div_le_one (lt_of_le_of_ne hd (Ne.symm hz))).2
      nlinarith [sq_nonneg C]
  constructor
  · constructor
    · unfold lowDriver; positivity
    · exact mul_le_of_le_one_right hv hl
  · constructor
    · unfold highDriver; exact mul_nonneg hv (membership_bounds U C).1
    · exact mul_le_of_le_one_right hv (membership_bounds U C).2

/-- Both hue-dependent selectors vanish at least quadratically near neutral. -/
theorem driver_neutral_quadratic_bound (U C : ℝ) :
    lowDriver U C ≤ C^2/4 ∧ highDriver U C ≤ C^2/4 := by
  have hv : visibility C ≤ C^2/4 := by
    unfold visibility
    apply (div_le_div_iff₀ (by positivity) (by norm_num)).2
    nlinarith [sq_nonneg C, sq_nonneg (C^2)]
  exact ⟨(driver_bounds U C).1.2.trans hv, (driver_bounds U C).2.2.trans hv⟩

/-- A uniform quadratic scalar response has a zero Fréchet derivative. -/
theorem scalar_neutral_of_quadratic_bound {E : Type*}
    [NormedAddCommGroup E] [NormedSpace ℝ E] (f : E → ℝ)
    (hzero : f 0 = 0) (hbound : ∀ v, |f v| ≤ (1/4 : ℝ)*‖v‖^2) :
    HasFDerivAt f (0 : E →L[ℝ] ℝ) 0 := by
  have hbig : f =O[𝓝 0] (fun v => ‖v‖^2) := by
    apply IsBigO.of_bound (1/4 : ℝ)
    filter_upwards [] with v
    simpa only [Real.norm_eq_abs, abs_of_nonneg (sq_nonneg ‖v‖)] using hbound v
  have hsmall := hbig.trans_isLittleO
    (Asymptotics.isLittleO_norm_pow_id (E' := E) (show 1 < 2 by norm_num))
  apply HasFDerivAt.of_isLittleO
  simpa [hzero] using hsmall

/-- Hue-dependent capacity may be discontinuous: visibility still gives both
scalar drivers the same zero near-neutral derivative in every direction. -/
theorem capacity_drivers_neutral_derivative {E : Type*}
    [NormedAddCommGroup E] [NormedSpace ℝ E] (U : E → ℝ) :
    HasFDerivAt (fun v => lowDriver (U v) ‖v‖) (0 : E →L[ℝ] ℝ) 0 ∧
    HasFDerivAt (fun v => highDriver (U v) ‖v‖) (0 : E →L[ℝ] ℝ) 0 := by
  constructor
  · apply scalar_neutral_of_quadratic_bound
    · simp [lowDriver, visibility]
    · intro v
      rw [abs_of_nonneg (driver_bounds (U v) ‖v‖).1.1]
      simpa only [div_eq_mul_inv, one_mul, mul_comm] using (driver_neutral_quadratic_bound (U v) ‖v‖).1
  · apply scalar_neutral_of_quadratic_bound
    · simp [highDriver, visibility]
    · intro v
      rw [abs_of_nonneg (driver_bounds (U v) ‖v‖).2.1]
      simpa only [div_eq_mul_inv, one_mul, mul_comm] using (driver_neutral_quadratic_bound (U v) ‖v‖).2

/- The remaining envelope lemmas concern the legacy fixed-H a/b translation,
   not the selective cone-derived response transform and quartic Reach mask. -/
theorem adaptance_rate_bounds (C : ℝ) : 0 < adaptanceRate C ∧ adaptanceRate C ≤ 1 := by
  have hd : 0 < 1+(C/30)^2 := by positivity
  have hdiv : (3/4 : ℝ)/(1+(C/30)^2) ≤ 3/4 := by
    apply (div_le_iff₀ hd).2
    nlinarith [sq_nonneg (C/30)]
  constructor
  · unfold adaptanceRate
    positivity
  · unfold adaptanceRate
    linarith

theorem adaptance_denominator_pos (C a : ℝ) (ha : 0 ≤ a) (ha1 : a ≤ 1) :
    0 < 1-a+a*adaptanceRate C := by
  have hr := (adaptance_rate_bounds C).1
  by_cases h : a = 1
  · simp [h, hr]
  · have hlt : a < 1 := lt_of_le_of_ne ha1 h
    nlinarith

theorem adaptance_bounds (H C a : ℝ) (ha : 0 ≤ a) (ha1 : a ≤ 1) :
    0 ≤ adaptanceEnvelope H C a ∧ adaptanceEnvelope H C a ≤ max H 0 / 100 := by
  have hd := adaptance_denominator_pos C a ha ha1
  have hr := (adaptance_rate_bounds C).1
  have hq : a*adaptanceRate C/(1-a+a*adaptanceRate C) ≤ 1 := by
    apply (div_le_one hd).2
    linarith
  constructor
  · unfold adaptanceEnvelope
    positivity
  · unfold adaptanceEnvelope
    rw [mul_div_assoc]
    exact mul_le_of_le_one_right (by positivity) hq

theorem adaptance_zero (H C : ℝ) : adaptanceEnvelope H C 0 = 0 := by simp [adaptanceEnvelope]

theorem adaptance_one (H C : ℝ) : adaptanceEnvelope H C 1 = max H 0 / 100 := by
  have h := ne_of_gt (adaptance_rate_bounds C).1
  simp [adaptanceEnvelope, h]

end PerceptualGrade
