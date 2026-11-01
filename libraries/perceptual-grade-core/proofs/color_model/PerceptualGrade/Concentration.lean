import PerceptualGrade.Drivers

namespace PerceptualGrade
noncomputable section

def diskMap (w z : ℂ) : ℂ := (z+w)/(1+star w*z)
def concentrationVector (v : ℂ) (C : ℝ) : ℂ :=
  if v = 0 then 0 else ((3/5 : ℝ)*Real.tanh (‖v‖/(3/5))*visibility C/‖v‖) • v

theorem concentration_vector_bound (v : ℂ) (C : ℝ) : ‖concentrationVector v C‖ < 1 := by
  by_cases hv : v = 0
  · simp [concentrationVector, hv]
  have hn : ‖v‖ ≠ 0 := norm_ne_zero_iff.mpr hv
  have hb := visibility_bounds C
  have ht := Real.abs_tanh_lt_one (‖v‖/(3/5))
  have hfade : |Real.tanh (‖v‖/(3/5))| * visibility C ≤ |Real.tanh (‖v‖/(3/5))| :=
    mul_le_of_le_one_right (abs_nonneg _) (le_of_lt hb.2)
  rw [concentrationVector, ite_eq_right hv, norm_smul, Real.norm_eq_abs, abs_div, abs_mul, abs_mul,
    abs_of_nonneg hb.1, abs_norm, div_mul_cancel₀ _ hn]
  norm_num
  nlinarith

theorem disk_denominator_nonzero (w z : ℂ) (hw : ‖w‖ < 1) (hz : ‖z‖ = 1) :
    1+star w*z ≠ 0 := by
  intro h
  have heq : star w*z = -1 := by linear_combination h
  have hn := congrArg norm heq
  simp only [norm_mul, norm_star, hz, mul_one, norm_neg, norm_one] at hn
  linarith

theorem disk_inverse (w z : ℂ) (hw : ‖w‖ < 1) (hz : ‖z‖ = 1) :
    diskMap (-w) (diskMap w z) = z := by
  have hd := disk_denominator_nonzero w z hw hz
  have hn : 1-star w*w ≠ 0 := by
    intro h
    have heq : star w*w = 1 := by linear_combination -h
    have hnorm := congrArg norm heq
    simp only [norm_mul, norm_star, norm_one] at hnorm
    have hp : 0 ≤ ‖w‖ := norm_nonneg w
    nlinarith
  unfold diskMap
  simp only [star_neg]
  have he : 1 + -star w * ((z+w)/(1+star w*z)) = (1-star w*w)/(1+star w*z) := by
    field_simp
    ring
  rw [he]
  have hnum : (z+w)/(1+star w*z)-w = z*(1-star w*w)/(1+star w*z) := by
    apply (eq_div_iff hd).2
    rw [sub_mul, div_mul_cancel₀ _ hd]
    ring
  rw [← sub_eq_add_neg, hnum, div_div_div_cancel_right₀ hd, mul_div_cancel_right₀ z hn]

theorem disk_radius (w z : ℂ) (hw : ‖w‖ < 1) (hz : ‖z‖ = 1) :
    ‖diskMap w z‖ = 1 := by
  have hd := disk_denominator_nonzero w z hw hz
  have hz2 : Complex.normSq z = 1 := by
    rw [← Complex.sq_norm, hz]
    norm_num
  have hs : Complex.normSq (z+w) = Complex.normSq (1+star w*z) := by
    simp only [Complex.star_def, Complex.normSq_apply, Complex.add_re, Complex.add_im, Complex.mul_re,
      Complex.mul_im, Complex.one_re, Complex.one_im, Complex.conj_re, Complex.conj_im] at *
    linear_combination (1-w.re^2-w.im^2)*hz2
  have hn : ‖z+w‖ = ‖1+star w*z‖ := by
    have hn2 : ‖z+w‖^2 = ‖1+star w*z‖^2 := by simpa [Complex.sq_norm] using hs
    nlinarith [norm_nonneg (z+w), norm_nonneg (1+star w*z)]
  rw [diskMap, norm_div, hn]
  exact div_self (norm_ne_zero_iff.mpr hd)

theorem concentration_scale_bound (t : ℝ) (ht : 0 ≤ t) :
    0 ≤ (Real.exp (2*t)-1)/(Real.exp (2*t)+1) ∧
      (Real.exp (2*t)-1)/(Real.exp (2*t)+1) < 1 := by
  have he : 1 ≤ Real.exp (2*t) := by simpa using Real.exp_le_exp.mpr (show 0 ≤ 2*t by linarith)
  have hd : 0 < Real.exp (2*t)+1 := by positivity
  exact ⟨div_nonneg (by linarith) (le_of_lt hd), (div_lt_one hd).2 (by linarith)⟩

theorem circle_orientation_positive (w z : ℂ) (hw : ‖w‖ < 1) (hz : ‖z‖ = 1) :
    0 < (1-‖w‖^2)/‖1+star w*z‖^2 := by
  have hp : 0 ≤ ‖w‖ := norm_nonneg w
  have hn : 0 < ‖1+star w*z‖ := norm_pos_iff.mpr (disk_denominator_nonzero w z hw hz)
  apply div_pos
  · nlinarith
  · positivity

def diskDerivative (w z : ℂ) : ℂ := (1-star w*w)/(1+star w*z)^2

theorem disk_derivative (w z : ℂ) (hw : ‖w‖ < 1) (hz : ‖z‖ = 1) :
    HasDerivAt (diskMap w) (diskDerivative w z) z := by
  have h := ((hasDerivAt_id z).add_const w).div
    (((hasDerivAt_id z).const_mul (star w)).const_add 1) (disk_denominator_nonzero w z hw hz)
  convert h using 1
  · rfl
  · simp only [diskDerivative, id_eq, mul_one, one_mul]
    congr 1
    ring

theorem circle_angular_derivative (w z : ℂ) (hw : ‖w‖ < 1) (hz : ‖z‖ = 1) :
    z*diskDerivative w z = (((1-‖w‖^2)/‖1+star w*z‖^2 : ℝ) : ℂ)*diskMap w z := by
  have hd := disk_denominator_nonzero w z hw hz
  have hwprod : star w*w = (‖w‖^2 : ℂ) := by
    simpa only [Complex.star_def] using Complex.conj_mul' w
  have hzprod : z*star z = 1 := by
    simpa only [Complex.star_def, hz, one_pow, Complex.ofReal_one] using Complex.mul_conj' z
  have hdprod : (1+star w*z)*star (1+star w*z) = (‖1+star w*z‖^2 : ℂ) := by
    simpa only [Complex.star_def] using Complex.mul_conj' (1+star w*z)
  have he : star (1+star w*z)*z = z+w := by
    simp only [star_add, star_one, star_mul, star_star]
    linear_combination w*hzprod
  rw [Complex.ofReal_div, Complex.ofReal_sub, Complex.ofReal_one, Complex.ofReal_pow,
    Complex.ofReal_pow, ← hwprod, ← hdprod]
  unfold diskDerivative diskMap
  have hc : star (1+star w*z) ≠ 0 := star_ne_zero.mpr hd
  rw [← he, ← mul_div_mul_comm]
  rw [show (1-star w*w)*(star (1+star w*z)*z) = star (1+star w*z)*(z*(1-star w*w)) by ring,
      show ((1+star w*z)*star (1+star w*z))*(1+star w*z) = star (1+star w*z)*(1+star w*z)^2 by ring,
      mul_div_mul_left _ _ hc, mul_div_assoc]

end
end PerceptualGrade
