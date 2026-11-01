import PerceptualGrade.SignedAppearance

/- Input-only native AP1 projection. -/
namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped Topology

def rgbMinimum (r : Fin 3 → ℝ) : ℝ := min (r 0) (min (r 1) (r 2))
def rgbY (w r : Fin 3 → ℝ) : ℝ := w 0*r 0+w 1*r 1+w 2*r 2
def rgbN (w r : Fin 3 → ℝ) : ℝ := max (rgbY w r) 0
def rgbK (r : Fin 3 → ℝ) : ℝ := max 0 (-rgbMinimum r)
def inputLift (w r : Fin 3 → ℝ) (i : Fin 3) : ℝ :=
  rgbN w r/(rgbN w r+rgbK r)*(r i+rgbK r)

theorem rgb_minimum_le (r : Fin 3 → ℝ) (i : Fin 3) : rgbMinimum r ≤ r i := by
  fin_cases i <;> simp only [rgbMinimum]
  · exact min_le_left _ _
  · exact le_trans (min_le_right _ _) (min_le_left _ _)
  · exact le_trans (min_le_right _ _) (min_le_right _ _)

theorem input_lift_nonnegative (w r : Fin 3 → ℝ) (i : Fin 3) : 0 ≤ inputLift w r i := by
  have hk : -r i ≤ rgbK r := le_trans (neg_le_neg (rgb_minimum_le r i)) (le_max_right _ _)
  unfold inputLift
  apply mul_nonneg
  · exact div_nonneg (le_max_right _ _) (add_nonneg (le_max_right _ _) (le_max_left _ _))
  · linarith

theorem input_lift_black (w r : Fin 3 → ℝ) (i : Fin 3) (hy : rgbY w r ≤ 0) :
    inputLift w r i = 0 := by simp [inputLift, rgbN, max_eq_right hy]

theorem input_lift_identity (w r : Fin 3 → ℝ) (i : Fin 3)
    (valid : ∀ j, 0 ≤ r j) (hy : 0 < rgbY w r) : inputLift w r i = r i := by
  have hk : rgbK r = 0 := by
    simp only [rgbK, rgbMinimum]
    apply max_eq_left
    have hm : 0 ≤ min (r 0) (min (r 1) (r 2)) := le_min (valid 0) (le_min (valid 1) (valid 2))
    linarith
  simp [inputLift, hk, rgbN, max_eq_left hy.le, ne_of_gt hy]

theorem rgb_y_positive (w r : Fin 3 → ℝ) (hw : ∀ i, 0 < w i)
    (hr : ∀ i, 0 ≤ r i) (hn : ∃ i, r i ≠ 0) : 0 < rgbY w r := by
  obtain ⟨i, hi⟩ := hn
  have hp : 0 < w i*r i := mul_pos (hw i) (lt_of_le_of_ne (hr i) (Ne.symm hi))
  have h0 := mul_nonneg (hw 0).le (hr 0)
  have h1 := mul_nonneg (hw 1).le (hr 1)
  have h2 := mul_nonneg (hw 2).le (hr 2)
  fin_cases i <;> simp only [rgbY] <;> norm_num at hp <;> linarith

theorem input_lift_valid_identity (w r : Fin 3 → ℝ) (i : Fin 3)
    (hw : ∀ j, 0 < w j) (hr : ∀ j, 0 ≤ r j) : inputLift w r i = r i := by
  by_cases hz : ∀ j, r j = 0
  · simp [inputLift, rgbN, rgbY, hz]
  · push Not at hz
    exact input_lift_identity w r i hr (rgb_y_positive w r hw hr hz)

theorem input_lift_idempotent (w r : Fin 3 → ℝ) (i : Fin 3) (hw : ∀ j, 0 < w j) :
    inputLift w (inputLift w r) i = inputLift w r i :=
  input_lift_valid_identity _ _ _ hw (input_lift_nonnegative w r)

theorem input_lift_luminance (w r : Fin 3 → ℝ) (hw : w 0+w 1+w 2 = 1)
    (hy : 0 < rgbY w r) : rgbY w (inputLift w r) = rgbY w r := by
  have hn : rgbN w r = rgbY w r := max_eq_left hy.le
  have hd : rgbY w r+rgbK r ≠ 0 := ne_of_gt (add_pos_of_pos_of_nonneg hy (le_max_left _ _))
  simp only [rgbY, inputLift, hn]
  change w 0*(rgbY w r/(rgbY w r+rgbK r)*(r 0+rgbK r)) +
    w 1*(rgbY w r/(rgbY w r+rgbK r)*(r 1+rgbK r)) +
    w 2*(rgbY w r/(rgbY w r+rgbK r)*(r 2+rgbK r)) = rgbY w r
  field_simp [hd]
  have he : w 0*r 0+w 1*r 1+w 2*r 2 = rgbY w r := rfl
  linear_combination rgbK r * hw + he

theorem input_lift_bound (w r : Fin 3 → ℝ) (i : Fin 3) (M : ℝ)
    (hw : ∀ j, 0 ≤ w j) (hs : w 0+w 1+w 2=1)
    (hm : 0 ≤ M) (hr : ∀ j, |r j| ≤ M) : |inputLift w r i| ≤ M := by
  have hy : rgbY w r ≤ M := by
    have h0 := mul_le_mul_of_nonneg_left (le_trans (le_abs_self _) (hr 0)) (hw 0)
    have h1 := mul_le_mul_of_nonneg_left (le_trans (le_abs_self _) (hr 1)) (hw 1)
    have h2 := mul_le_mul_of_nonneg_left (le_trans (le_abs_self _) (hr 2)) (hw 2)
    unfold rgbY
    nlinarith
  have hn : rgbN w r ≤ M := max_le hy hm
  have hn0 : 0 ≤ rgbN w r := le_max_right _ _
  have hk0 : 0 ≤ rgbK r := le_max_left _ _
  rw [abs_of_nonneg (input_lift_nonnegative w r i)]
  by_cases hd : rgbN w r+rgbK r=0
  · simp [inputLift, hd, hm]
  have hd0 : 0 < rgbN w r+rgbK r := lt_of_le_of_ne (add_nonneg hn0 hk0) (Ne.symm hd)
  unfold inputLift
  rw [div_mul_eq_mul_div, div_le_iff₀ hd0]
  have hi : r i ≤ M := le_trans (le_abs_self _) (hr i)
  nlinarith [mul_le_mul_of_nonneg_left hi hn0, mul_le_mul_of_nonneg_right hn hk0]

theorem input_lift_denominator (w r : Fin 3 → ℝ) (hw : ∀ j, 0 < w j)
    (hd : rgbN w r+rgbK r=0) : ∀ j, r j=0 := by
  have hn0 : 0 ≤ rgbN w r := le_max_right _ _
  have hk0 : 0 ≤ rgbK r := le_max_left _ _
  have hn : rgbN w r=0 := by linarith
  have hk : rgbK r=0 := by linarith
  have hr : ∀ j, 0 ≤ r j := by
    intro j
    have hm : -rgbMinimum r ≤ 0 := by
      calc -rgbMinimum r ≤ rgbK r := le_max_right _ _
           _ = 0 := hk
    have hb := rgb_minimum_le r j
    linarith
  by_contra hz
  push Not at hz
  have hy := rgb_y_positive w r hw hr hz
  have : rgbN w r > 0 := lt_of_lt_of_le hy (le_max_left _ _)
  linarith

theorem input_lift_continuous (w : Fin 3 → ℝ) (hw : ∀ i, 0 < w i)
    (hs : w 0+w 1+w 2=1) (i : Fin 3) : Continuous (fun r => inputLift w r i) := by
  apply continuous_iff_continuousAt.2
  intro p
  by_cases hd : rgbN w p+rgbK p=0
  · have hz := input_lift_denominator w p hw hd
    rw [Metric.continuousAt_iff']
    intro ε hε
    have he : ∀ j, ∀ᶠ r in 𝓝 p, |r j| < ε := by
      intro j
      have hc : Continuous (fun r : Fin 3 → ℝ => |r j|) := by fun_prop
      exact (hc.continuousAt.eventually (Iio_mem_nhds (by simpa [hz j] using hε)))
    have ha := Filter.eventually_all.2 he
    have ho : inputLift w p i = 0 := by simp [inputLift, hd]
    filter_upwards [ha] with r hr
    simp only [ho, dist_eq_norm, sub_zero, Real.norm_eq_abs]
    have hb := input_lift_bound w r i ((ε+max (|r 0|) (max (|r 1|) (|r 2|)))/2)
      (fun j => (hw j).le) hs (by positivity)
    have hm : max (|r 0|) (max (|r 1|) (|r 2|)) < ε := max_lt (hr 0) (max_lt (hr 1) (hr 2))
    have hbound : ∀ j, |r j| ≤ (ε+max (|r 0|) (max (|r 1|) (|r 2|)))/2 := by
      intro j
      have hj : |r j| ≤ max (|r 0|) (max (|r 1|) (|r 2|)) := by
        fin_cases j
        · exact le_max_left _ _
        · exact le_trans (le_max_left _ _) (le_max_right _ _)
        · exact le_trans (le_max_right _ _) (le_max_right _ _)
      linarith
    exact lt_of_le_of_lt (hb hbound) (by linarith)
  · unfold inputLift rgbN rgbK rgbMinimum rgbY at *
    fun_prop (disch := exact hd)


def inputMaximum (r : Fin 3 → ℝ) := max (r 0) (max (r 1) (r 2))
def inputRepair (U : ℝ) (w r : Fin 3 → ℝ) (i : Fin 3) :=
  U/max U (inputMaximum (inputLift w r))*inputLift w r i

theorem input_maximum_ge (r : Fin 3 → ℝ) (i : Fin 3) : r i ≤ inputMaximum r := by
  fin_cases i <;> simp only [inputMaximum]
  · exact le_max_left _ _
  · exact le_trans (le_max_left _ _) (le_max_right _ _)
  · exact le_trans (le_max_right _ _) (le_max_right _ _)

theorem input_repair_bounds (U : ℝ) (w r : Fin 3 → ℝ) (i : Fin 3) (hU : 0 < U) :
    0 ≤ inputRepair U w r i ∧ inputRepair U w r i ≤ U := by
  have hd : 0 < max U (inputMaximum (inputLift w r)) := lt_of_lt_of_le hU (le_max_left _ _)
  have hb : inputLift w r i ≤ max U (inputMaximum (inputLift w r)) :=
    le_trans (input_maximum_ge _ i) (le_max_right _ _)
  unfold inputRepair
  constructor
  · exact mul_nonneg (div_nonneg hU.le hd.le) (input_lift_nonnegative w r i)
  · rw [div_mul_eq_mul_div, div_le_iff₀ hd]
    exact mul_le_mul_of_nonneg_left hb hU.le

theorem input_repair_identity (U : ℝ) (w r : Fin 3 → ℝ) (i : Fin 3)
    (hU : 0 < U) (hw : ∀ j, 0 < w j) (valid : ∀ j, 0 ≤ r j ∧ r j ≤ U) :
    inputRepair U w r i = r i := by
  have hl : inputLift w r = r := funext (fun j => input_lift_valid_identity w r j hw (fun k => (valid k).1))
  have hm : inputMaximum r ≤ U := max_le (valid 0).2 (max_le (valid 1).2 (valid 2).2)
  simp [inputRepair, hl, max_eq_left hm, ne_of_gt hU]

theorem input_repair_idempotent (U : ℝ) (w r : Fin 3 → ℝ) (i : Fin 3)
    (hU : 0 < U) (hw : ∀ j, 0 < w j) :
    inputRepair U w (inputRepair U w r) i = inputRepair U w r i :=
  input_repair_identity U w _ i hU hw (fun j => input_repair_bounds U w r j hU)

theorem input_repair_continuous (U : ℝ) (w : Fin 3 → ℝ) (i : Fin 3)
    (hU : 0 < U) (hw : ∀ j, 0 < w j) (hs : w 0+w 1+w 2=1) :
    Continuous (fun r => inputRepair U w r i) := by
  have hl := fun j => input_lift_continuous w hw hs j
  unfold inputRepair inputMaximum
  apply Continuous.mul
  · apply Continuous.div continuous_const
    · exact continuous_const.max ((hl 0).max ((hl 1).max (hl 2)))
    · intro r
      exact ne_of_gt (lt_of_lt_of_le hU (le_max_left _ _))
  · exact hl i

end
end PerceptualGrade
