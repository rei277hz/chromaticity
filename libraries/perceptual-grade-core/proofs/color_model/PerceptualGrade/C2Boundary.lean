import PerceptualGrade.ContinuousGuard

namespace PerceptualGrade
noncomputable section
open Set
open scoped ContDiff

def positiveCubic : ℝ → ℝ := joined 0 (fun _ => 0) (fun x => x^3)

theorem positive_cubic_c2 : ContDiff ℝ 2 positiveCubic := by
  have d : deriv (fun x : ℝ => x^3) = fun x => 3*x^2 := by
    funext x; simp
  have dd : deriv (fun x : ℝ => 3*x^2) = fun x => 6*x := by
    funext x
    convert (((hasDerivAt_id x).pow 2).const_mul 3).deriv using 1 <;> simp; ring
  apply joined_c2 _ _ _ contDiff_const (by fun_prop) <;> norm_num [d, dd]

theorem positive_cubic_nonpositive (x : ℝ) (hx : x ≤ 0) : positiveCubic x = 0 := by
  simp [positiveCubic, joined, hx]

theorem positive_cubic_nonnegative (x : ℝ) (hx : 0 ≤ x) : positiveCubic x = x^3 := by
  by_cases h : x ≤ 0
  · have : x = 0 := le_antisymm h hx
    simp [this, positiveCubic, joined]
  · simp [positiveCubic, joined, h]

def roundedHinge (x : ℝ) : ℝ :=
  (positiveCubic (x+1)-2*positiveCubic x+positiveCubic (x-1))/6

theorem rounded_hinge_c2 : ContDiff ℝ 2 roundedHinge := by
  have hl : ContDiff ℝ 2 (fun x : ℝ => positiveCubic (x+1)) :=
    positive_cubic_c2.comp (by fun_prop)
  have hr : ContDiff ℝ 2 (fun x : ℝ => positiveCubic (x-1)) :=
    positive_cubic_c2.comp (by fun_prop)
  exact ((hl.sub (contDiff_const.mul positive_cubic_c2)).add hr).div_const 6


theorem rounded_hinge_left (x : ℝ) (ha : -1 ≤ x) (hb : x ≤ 0) :
    roundedHinge x = (x+1)^3/6 := by
  rw [roundedHinge, positive_cubic_nonnegative _ (by linarith),
    positive_cubic_nonpositive _ hb, positive_cubic_nonpositive _ (by linarith)]
  ring

theorem rounded_hinge_right (x : ℝ) (ha : 0 ≤ x) (hb : x ≤ 1) :
    roundedHinge x = x+(1-x)^3/6 := by
  rw [roundedHinge, positive_cubic_nonnegative _ (by linarith),
    positive_cubic_nonnegative _ ha, positive_cubic_nonpositive _ (by linarith)]
  ring

theorem rounded_hinge_before (x : ℝ) (hx : x ≤ -1) : roundedHinge x = 0 := by
  rw [roundedHinge, positive_cubic_nonpositive _ (by linarith),
    positive_cubic_nonpositive _ (by linarith), positive_cubic_nonpositive _ (by linarith)]
  norm_num

theorem rounded_hinge_after (x : ℝ) (hx : 1 ≤ x) : roundedHinge x = x := by
  rw [roundedHinge, positive_cubic_nonnegative _ (by linarith),
    positive_cubic_nonnegative _ (by linarith), positive_cubic_nonnegative _ (by linarith)]
  ring

def roundedCorner (y ml mr radius x : ℝ) : ℝ :=
  y+ml*x+(mr-ml)*radius*roundedHinge (x/radius)

theorem rounded_corner_c2 (y ml mr radius : ℝ) :
    ContDiff ℝ 2 (roundedCorner y ml mr radius) := by
  unfold roundedCorner
  have hc : ContDiff ℝ 2 (fun x : ℝ => roundedHinge (x/radius)) :=
    rounded_hinge_c2.comp (by fun_prop)
  exact (by fun_prop : ContDiff ℝ 2 (fun x : ℝ => y+ml*x)).add
    (contDiff_const.mul hc)


theorem corner_left_cubic (y ml mr r t : ℝ) (hr : r ≠ 0) (ht : t ∈ Icc 0 1) :
    roundedCorner y ml mr r (r*(t-1)) = y-r*ml+r*(ml*t+(mr-ml)/6*t^3) := by
  have he : r*(t-1)/r = t-1 := by field_simp
  unfold roundedCorner
  rw [he, rounded_hinge_left _ (by linarith [ht.1]) (by linarith [ht.2])]
  ring

theorem corner_cubic_monotone (a b : ℝ) (ha : 0 < a) (hb : -a/6 ≤ b) :
    StrictMonoOn (fun t : ℝ => a*t+b*t^3) (Icc 0 1) := by
  intro x hx y hy hxy
  have hxx : 0 ≤ x*x := mul_nonneg hx.1 hx.1
  have hyy : 0 ≤ y*y := mul_nonneg hy.1 hy.1
  have hxy0 : 0 ≤ x*y := mul_nonneg hx.1 hy.1
  have hxx1 : x*x ≤ 1 := by nlinarith [mul_le_mul_of_nonneg_left hx.2 hx.1, hx.2]
  have hyy1 : y*y ≤ 1 := by nlinarith [mul_le_mul_of_nonneg_left hy.2 hy.1, hy.2]
  have hxy1 : x*y ≤ 1 := by nlinarith [mul_le_mul_of_nonneg_left hx.2 hy.1, hy.2]
  have hs : x*x+x*y+y*y ≤ 3 := by linarith
  have hs0 : 0 ≤ x*x+x*y+y*y := by linarith
  have hp : 0 < a+b*(x*x+x*y+y*y) := by
    have hprod := mul_le_mul_of_nonneg_right hb hs0
    have hprod2 := mul_le_mul_of_nonneg_left hs (le_of_lt ha)
    nlinarith
  have pos := mul_pos (sub_pos.mpr hxy) hp
  nlinarith

theorem corner_cubic_inverse_unique (a b x y : ℝ) (ha : 0 < a) (hb : -a/6 ≤ b)
    (hx : x ∈ Icc 0 1) (hy : y ∈ Icc 0 1)
    (he : a*x+b*x^3 = a*y+b*y^3) : x = y :=
  (corner_cubic_monotone a b ha hb).injOn hx hy he


end
end PerceptualGrade
