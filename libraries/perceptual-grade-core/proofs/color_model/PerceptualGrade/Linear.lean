import PerceptualGrade.Basic

namespace PerceptualGrade
open Matrix

theorem matrix_inverse_composition (M : Matrix (Fin 3) (Fin 3) ℝ) (h : M.det ≠ 0) :
    M⁻¹ * M = 1 ∧ M * M⁻¹ = 1 := by
  exact ⟨M.nonsing_inv_mul (isUnit_iff_ne_zero.mpr h), M.mul_nonsing_inv (isUnit_iff_ne_zero.mpr h)⟩

theorem diagonal_adaptation_white (source destination : Fin 3 → ℝ)
    (h : ∀ i, source i ≠ 0) :
    (diagonal (fun i => destination i / source i)).mulVec source = destination := by
  ext i
  rw [mulVec_diagonal]
  exact div_mul_cancel₀ (destination i) (h i)

theorem exposure_positive (e : ℝ) : 0 < (2 : ℝ)^e := by positivity

theorem linear_identity (v : Fin 3 → ℝ) : (1 : Matrix (Fin 3) (Fin 3) ℝ).mulVec v = v := by simp

theorem linear_white (D C : Matrix (Fin 3) (Fin 3) ℝ) (source white : Fin 3 → ℝ)
    (hC : C.mulVec source = white) (hD : D.mulVec white = white) (e : ℝ) :
    (((2 : ℝ)^e) • (D*C)).mulVec source = ((2 : ℝ)^e) • white := by
  have hs : (((2 : ℝ)^e) • (D*C)).mulVec source = ((2 : ℝ)^e) • ((D*C).mulVec source) :=
    smul_mulVec _ _ _
  rw [hs, ← mulVec_mulVec, hC, hD]

theorem exposure_commutes (M : Matrix (Fin 3) (Fin 3) ℝ) (v : Fin 3 → ℝ) (a : ℝ) :
    M.mulVec (a • v) = a • M.mulVec v := by simp [mulVec_smul]

end PerceptualGrade
