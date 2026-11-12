import PerceptualGrade.HKGuard
import PerceptualGrade.SelectiveAdaptance

/- The Warp pad uses a compact saturation chart after H–K repair and Scale.
   Its squared radius is C²/(C²+|E|). The carried energy, rather than a
   subtraction of rounded appearance coordinates, controls the raw rim.
   Common positive Scale preserves both Cartesian coordinates after repair.
   This does not assert invariance through the subsequent RGB cube guard. -/
namespace PerceptualGrade
noncomputable section

def warpCompactRadiusSq (C E : ℝ) : ℝ := C^2/(C^2+|E|)

/-- Both Cartesian pad coordinates are invariant under common positive Scale,
    including their totalized neutral/black extension. -/
theorem warp_compact_coordinates_scale (a b C E k : ℝ) (hk : 0 < k) :
    (boundedSaturationCoordinate (k*a) (k*C) (k^2*E),
      boundedSaturationCoordinate (k*b) (k*C) (k^2*E)) =
    (boundedSaturationCoordinate a C E, boundedSaturationCoordinate b C E) := by
  rw [bounded_saturation_scale a C E k hk, bounded_saturation_scale b C E k hk]

theorem warp_compact_radius_scale (C E k : ℝ) (hk : 0 < k) :
    warpCompactRadiusSq (k*C) (k^2*E) = warpCompactRadiusSq C E := by
  unfold warpCompactRadiusSq
  rw [abs_mul, abs_of_nonneg (sq_nonneg k), mul_pow,
    show k^2*C^2+k^2*|E| = k^2*(C^2+|E|) by ring]
  exact mul_div_mul_left _ _ (pow_ne_zero 2 (ne_of_gt hk))

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
    zero-energy chromatic state strictly inside the ideal repair-formula rim.
    Application to executable repair additionally requires H≥0; H<0 bypasses
    repair, which cannot be inferred from X=H² alone. This is why the Chroma
    Stops threshold uses raw carried energy before repair rather than detecting
    a crossing in the repaired pad coordinate. -/
theorem warp_guarded_raw_rim_moves_interior
    (E0 X Craw Cguard : ℝ) (h0 : 0 < E0) (hx : 0 < X) (hc : Craw ≠ 0) :
    warpCompactRadiusSq Craw 0 = 1 ∧
      warpCompactRadiusSq Cguard (hkGuardEnergy (hkGuardDelta E0 X) 0) < 1 := by
  constructor
  · exact warp_compact_radius_on_raw_rim Craw hc
  · exact warp_compact_radius_strict_interior Cguard _
      (ne_of_gt (hk_guard_energy_positive _ _ (hk_guard_delta_positive E0 X h0 hx)))

/-- The same ideal repair-formula conclusion holds for any raw signed-energy
    request. Executable application requires H≥0; the H<0 bypass is excluded.
    Subsequent common positive Scale preserves this repaired radius. -/
theorem warp_guarded_chart_interior
    (E0 X C D : ℝ) (h0 : 0 < E0) (hx : 0 < X) :
    warpCompactRadiusSq C (hkGuardEnergy (hkGuardDelta E0 X) D) < 1 := by
  exact warp_compact_radius_strict_interior C _
    (ne_of_gt (hk_guard_energy_positive _ _ (hk_guard_delta_positive E0 X h0 hx)))

end
end PerceptualGrade
