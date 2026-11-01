import PerceptualGrade.HKGuard

/- The Warp pad uses a compact saturation chart after export H–K repair.
   Its squared radius is C²/(C²+|E|). The carried energy, rather than a
   subtraction of rounded appearance coordinates, controls the raw rim.
   The proof concerns this display chart, not global invertibility of grading
   or invariance of the final-scale edit under the nonlinear guard. -/
namespace PerceptualGrade
noncomputable section

def warpCompactRadiusSq (C E : ℝ) : ℝ := C^2/(C^2+|E|)

theorem warp_carried_zero_threshold (J : ℝ) : J*|J| = 0 ↔ J = 0 := by
  constructor
  · intro hz
    rcases mul_eq_zero.mp hz with h | h
    · exact h
    · exact abs_eq_zero.mp h
  · intro hz
    simp [hz]

theorem warp_carried_negative_threshold (J : ℝ) : J*|J| < 0 ↔ J < 0 := by
  constructor
  · intro hn
    by_contra hj
    have hj0 : 0 ≤ J := le_of_not_gt hj
    have hp := mul_nonneg hj0 (abs_nonneg J)
    linarith
  · intro hj
    exact mul_neg_of_neg_of_pos hj (abs_pos.mpr (ne_of_lt hj))

/-- Compact projection uses one common positive divisor for a and b, so
    it changes radius without introducing any additional hue rotation. -/
theorem warp_compact_hue_preserved (a b d : ℝ) (hd : d ≠ 0) :
    (a/d)*b-(b/d)*a = 0 := by
  field_simp
  ring

theorem warp_compact_radius_bounds (C E : ℝ) :
    0 ≤ warpCompactRadiusSq C E ∧ warpCompactRadiusSq C E ≤ 1 := by
  by_cases hc : C = 0
  · simp [warpCompactRadiusSq, hc]
  · have hden : 0 < C^2+|E| := by
      have hsq : 0 < C^2 := sq_pos_of_ne_zero hc
      nlinarith [abs_nonneg E]
    constructor
    · exact div_nonneg (sq_nonneg C) hden.le
    · exact (div_le_one hden).2 (by nlinarith [abs_nonneg E])

theorem warp_compact_radius_on_raw_rim (C : ℝ) (hc : C ≠ 0) :
    warpCompactRadiusSq C 0 = 1 := by
  have hsq : C^2 ≠ 0 := pow_ne_zero 2 hc
  simp [warpCompactRadiusSq, hsq]

theorem warp_compact_radius_strict_interior (C E : ℝ) (he : E ≠ 0) :
    warpCompactRadiusSq C E < 1 := by
  by_cases hc : C = 0
  · simp [warpCompactRadiusSq, hc]
  · have heabs : 0 < |E| := abs_pos.mpr he
    have hden : 0 < C^2+|E| := by
      nlinarith [sq_nonneg C]
    unfold warpCompactRadiusSq
    exact (div_lt_one hden).2 (by linarith)

/-- Positive fixed reference energy and positive H² move every finite raw
    zero-energy chromatic state strictly inside the guarded unit rim. This is
    why the Chroma Stops threshold must use the raw carried energy, before
    repair, rather than detecting a crossing in the guarded pad coordinate. -/
theorem warp_guarded_raw_rim_moves_interior
    (E0 X Craw Cguard : ℝ) (h0 : 0 < E0) (hx : 0 < X) (hc : Craw ≠ 0) :
    warpCompactRadiusSq Craw 0 = 1 ∧
      warpCompactRadiusSq Cguard (hkGuardEnergy (hkGuardDelta E0 X) 0) < 1 := by
  constructor
  · exact warp_compact_radius_on_raw_rim Craw hc
  · exact warp_compact_radius_strict_interior Cguard _
      (ne_of_gt (hk_guard_energy_positive _ _ (hk_guard_delta_positive E0 X h0 hx)))

/-- The same strict interior conclusion holds for any raw signed-energy
    request. It says nothing about position or scale invariance after repair. -/
theorem warp_guarded_chart_interior
    (E0 X C D : ℝ) (h0 : 0 < E0) (hx : 0 < X) :
    warpCompactRadiusSq C (hkGuardEnergy (hkGuardDelta E0 X) D) < 1 := by
  exact warp_compact_radius_strict_interior C _
    (ne_of_gt (hk_guard_energy_positive _ _ (hk_guard_delta_positive E0 X h0 hx)))

end
end PerceptualGrade
