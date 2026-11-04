import PerceptualGrade.Spindle
import Mathlib.Analysis.SpecialFunctions.Arsinh

namespace PerceptualGrade
noncomputable section
open Set
open scoped ContDiff

/-- The ordinary hyperbolic inverse, with the linear case made explicit. -/
def finiteSpindleCompressDirect (k y : ℝ) : ℝ :=
  if k = 1 then y else
    2 * Real.sinh (Real.arsinh ((3/2)*y*Real.sqrt (3*(k-1))) / 3) /
      Real.sqrt (3*(k-1))

/-- Production's stable hyperbolic evaluation, including its exact zero argument branch. -/
def finiteSpindleCompress (k y : ℝ) : ℝ :=
  let t := (3/2)*y*Real.sqrt (3*(k-1))
  if t = 0 then y else y * (3*Real.sinh (Real.arsinh t / 3) / t)

theorem finite_spindle_compress_zero (k : ℝ) : finiteSpindleCompress k 0 = 0 := by
  simp [finiteSpindleCompress]

theorem finite_spindle_compress_identity (y : ℝ) : finiteSpindleCompress 1 y = y := by
  simp [finiteSpindleCompress]

/-- The stable production expression equals the ordinary hyperbolic inverse. -/
theorem finite_spindle_compress_stable_eq (k y : ℝ) (hk : 1 ≤ k) :
    finiteSpindleCompress k y = finiteSpindleCompressDirect k y := by
  by_cases hk1 : k = 1
  · simp [hk1, finiteSpindleCompress, finiteSpindleCompressDirect]
  have hkpos : 1 < k := lt_of_le_of_ne hk (Ne.symm hk1)
  have hs : Real.sqrt (3*(k-1)) ≠ 0 :=
    ne_of_gt (Real.sqrt_pos.2 (by linarith))
  by_cases hy : y = 0
  · simp [hy, finiteSpindleCompress, finiteSpindleCompressDirect, hk1]
  have ht : (3/2:ℝ)*y*Real.sqrt (3*(k-1)) ≠ 0 :=
    mul_ne_zero (mul_ne_zero (by norm_num) hy) hs
  simp only [finiteSpindleCompress, finiteSpindleCompressDirect, hk1, ht, ite_false]
  field_simp [hs, hy]

/-- The explicit hyperbolic formula solves the release cubic exactly. -/
theorem finite_spindle_direct_inverse_root (k y : ℝ) (hk : 1 ≤ k) :
    finiteSpindleRelease k (finiteSpindleCompressDirect k y) = y := by
  by_cases hk1 : k = 1
  · simp [hk1, finiteSpindleCompressDirect, finiteSpindleRelease]
  have hkpos : 1 < k := lt_of_le_of_ne hk (Ne.symm hk1)
  let s := Real.sqrt (3*(k-1))
  let u := Real.sinh (Real.arsinh ((3/2)*y*s) / 3)
  have hs : 0 < s := Real.sqrt_pos.2 (by linarith)
  have hs0 : s ≠ 0 := ne_of_gt hs
  have hs2 : s^2 = 3*(k-1) := Real.sq_sqrt (by linarith)
  have hc : k-1 = s^2/3 := by nlinarith
  have ht : 4*u^3+3*u = (3/2)*y*s := by
    have he := Real.sinh_three_mul (Real.arsinh ((3/2)*y*s) / 3)
    rw [show 3*(Real.arsinh ((3/2)*y*s)/3) = Real.arsinh ((3/2)*y*s) by ring,
      Real.sinh_arsinh] at he
    exact he.symm
  simp only [finiteSpindleCompressDirect, hk1, ite_false, finiteSpindleRelease]
  change 2*u/s+(k-1)*(2*u/s)^3 = y
  calc
    2*u/s+(k-1)*(2*u/s)^3 = (2/(3*s))*(4*u^3+3*u) := by
      rw [hc]
      field_simp [hs0]
      ring
    _ = y := by rw [ht]; field_simp [hs0]

theorem finite_spindle_release_compress (k y : ℝ) (hk : 1 ≤ k) :
    finiteSpindleRelease k (finiteSpindleCompress k y) = y := by
  rw [finite_spindle_compress_stable_eq k y hk]
  exact finite_spindle_direct_inverse_root k y hk

/-- Positive linear coefficient makes the cubic injective on the whole real line. -/
theorem finite_spindle_injective (k : ℝ) (hk : 1 ≤ k) :
    Function.Injective (finiteSpindleRelease k) := by
  intro x y hxy
  have hq : 0 ≤ x^2+x*y+y^2 := by nlinarith [sq_nonneg (x+y),sq_nonneg x,sq_nonneg y]
  have hk0 : 0 ≤ k-1 := sub_nonneg.mpr hk
  have hf : 0 < 1+(k-1)*(x^2+x*y+y^2) := by positivity
  have he : (x-y)*(1+(k-1)*(x^2+x*y+y^2)) = 0 := by
    unfold finiteSpindleRelease at hxy
    nlinarith [hxy]
  exact sub_eq_zero.mp ((mul_eq_zero.mp he).resolve_right (ne_of_gt hf))

theorem finite_spindle_compress_release (k x : ℝ) (hk : 1 ≤ k) :
    finiteSpindleCompress k (finiteSpindleRelease k x) = x := by
  apply finite_spindle_injective k hk
  exact finite_spindle_release_compress k (finiteSpindleRelease k x) hk

/-- A nonnegative cube radius compresses to a nonnegative, no larger radius. -/
theorem finite_spindle_compress_bounds (k y : ℝ) (hk : 1 ≤ k) (hy : 0 ≤ y) :
    0 ≤ finiteSpindleCompress k y ∧ finiteSpindleCompress k y ≤ y := by
  have hn : 0 ≤ finiteSpindleCompress k y := by
    rw [finite_spindle_compress_stable_eq k y hk]
    unfold finiteSpindleCompressDirect
    split_ifs
    · exact hy
    · apply div_nonneg
      · apply mul_nonneg (by norm_num)
        apply Real.sinh_nonneg_iff.2
        apply div_nonneg
        · apply Real.arsinh_nonneg_iff.2
          positivity
        · norm_num
      · exact Real.sqrt_nonneg _
  have hi := finite_spindle_release_compress k y hk
  unfold finiteSpindleRelease at hi
  exact ⟨hn, by nlinarith [mul_nonneg (show 0 ≤ k-1 by linarith) (pow_nonneg hn 3)]⟩

/-- Both formula branches define the same smooth scalar inverse, also at neutral. -/
theorem finite_spindle_compress_c2 (k : ℝ) (hk : 1 ≤ k) :
    ContDiff ℝ 2 (finiteSpindleCompress k) := by
  have he : finiteSpindleCompress k = finiteSpindleCompressDirect k := by
    funext y
    exact finite_spindle_compress_stable_eq k y hk
  rw [he]
  unfold finiteSpindleCompressDirect
  by_cases hk1 : k = 1
  · simp only [hk1, ite_true]
    fun_prop
  · simp only [hk1, ite_false]
    exact ((contDiff_const.mul (((contDiff_const.mul contDiff_id).mul
      contDiff_const).arsinh.div_const 3).sinh).div_const _)

end
end PerceptualGrade
