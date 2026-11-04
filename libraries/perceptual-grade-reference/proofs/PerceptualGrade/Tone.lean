import PerceptualGrade.Basic

namespace PerceptualGrade
noncomputable section

def toneGain (J C H : ℝ) : ℝ := 2*H^2/(Real.sqrt ((66*C)^2+4*J^2*H^2)+66*C)
def clipUnit (u : ℝ) : ℝ := min (max u 0) 1

theorem tone_gain_positive (J C H : ℝ) (hC : 0 ≤ C) (hH : 0 < H)
    (hp : 0 < (66*C)^2+4*J^2*H^2) : 0 < toneGain J C H := by
  have hs := Real.sqrt_pos.2 hp
  unfold toneGain
  positivity

theorem tone_gain_quadratic (J C H : ℝ) (hC : 0 ≤ C)
    (hp : 0 < (66*C)^2+4*J^2*H^2) :
    J^2*(toneGain J C H)^2+66*C*toneGain J C H = H^2 := by
  have hs := Real.sqrt_pos.2 hp
  have hd : Real.sqrt ((66*C)^2+4*J^2*H^2)+66*C ≠ 0 := by positivity
  have hsq := Real.sq_sqrt (le_of_lt hp)
  let d := Real.sqrt ((66*C)^2+4*J^2*H^2)+66*C
  have hg : toneGain J C H*d = 2*H^2 := div_mul_cancel₀ _ hd
  have hproduct : (J^2*(toneGain J C H)^2+66*C*toneGain J C H-H^2)*d^2 = 0 := by
    calc
      _ = J^2*(toneGain J C H*d)^2+66*C*(toneGain J C H*d)*d-H^2*d^2 := by ring
      _ = J^2*(2*H^2)^2+66*C*(2*H^2)*d-H^2*d^2 := by rw [hg]
      _ = 0 := by dsimp [d]; linear_combination -H^2*hsq
  exact sub_eq_zero.mp ((mul_eq_zero.mp hproduct).resolve_right (pow_ne_zero 2 hd))

theorem clip_unit_bounds (u : ℝ) : 0 ≤ clipUnit u ∧ clipUnit u ≤ 1 := by
  exact ⟨le_min (le_max_right _ _) (by norm_num), min_le_right _ _⟩

theorem coefficient_constructor_order (a b c d : ℝ) :
    let u0 := clipUnit a
    let u1 := min u0 (clipUnit b)
    let u2 := min u1 (clipUnit c)
    let u3 := min u2 (clipUnit d)
    u0 ≤ 1 ∧ u1 ≤ u0 ∧ u2 ≤ u1 ∧ u3 ≤ u2 ∧ 0 ≤ u3 := by
  dsimp
  refine ⟨(clip_unit_bounds a).2, min_le_left _ _, min_le_left _ _, min_le_left _ _, ?_⟩
  exact le_min (le_min (le_min (clip_unit_bounds a).1 (clip_unit_bounds b).1)
    (clip_unit_bounds c).1) (clip_unit_bounds d).1

theorem kernel_derivative (t l r w : ℝ) (hw : w ≠ 0) :
    HasDerivAt (fun t => kernel t l r w) (sigmoid ((t-l)/w)-sigmoid ((t-r)/w)) t := by
  have hl := (softplus_derivative ((t-l)/w)).comp t (((hasDerivAt_id t).sub_const l).div_const w)
  have hr := (softplus_derivative ((t-r)/w)).comp t (((hasDerivAt_id t).sub_const r).div_const w)
  convert (((hl.sub_const (softplus (-l/w))).sub hr).add_const (softplus (-r/w))).const_mul w using 1
  · rfl
  · field_simp

theorem kernel_strictMono (l r w : ℝ) (hlr : l < r) (hw : 0 < w) :
    StrictMono (fun t => kernel t l r w) := by
  apply strictMono_of_deriv_pos
  intro t
  rw [(kernel_derivative t l r w (ne_of_gt hw)).deriv]
  apply sub_pos.mpr
  apply sigmoid_strictMono
  exact (div_lt_div_iff_of_pos_right hw).2 (by linarith)

theorem kernel_normalizer_positive (l r w : ℝ) (hlr : l < r) (hw : 0 < w) :
    0 < kernel 1 l r w := by
  have h := kernel_strictMono l r w hlr hw (show (0:ℝ) < 1 by norm_num)
  simpa [kernel_zero] using h

theorem kernel_normalized_endpoints (l r w : ℝ) (hlr : l < r) (hw : 0 < w) :
    kernel 0 l r w / kernel 1 l r w = 0 ∧ kernel 1 l r w / kernel 1 l r w = 1 := by
  exact ⟨by rw [kernel_zero, zero_div], div_self (ne_of_gt (kernel_normalizer_positive l r w hlr hw))⟩

theorem kernel_normalized_bounds (t l r w : ℝ) (ht : 0 ≤ t) (ht1 : t ≤ 1)
    (hlr : l < r) (hw : 0 < w) :
    0 ≤ kernel t l r w / kernel 1 l r w ∧ kernel t l r w / kernel 1 l r w ≤ 1 := by
  have hm := (kernel_strictMono l r w hlr hw).monotone
  have hp := kernel_normalizer_positive l r w hlr hw
  have h0 : 0 ≤ kernel t l r w := by simpa [kernel_zero] using hm ht
  exact ⟨div_nonneg h0 (le_of_lt hp), (div_le_one hp).2 (hm ht1)⟩

theorem tone_strictMono (m : ℝ) (hm : 0 < m) (f : Fin 4 → ℝ → ℝ)
    (hf : ∀ i, Monotone (f i)) (a : Fin 4 → ℝ) (ha : ∀ i, 0 ≤ a i) :
    StrictMono (fun t => m*t + ∑ i, a i*f i t) := by
  intro x y hxy
  have hsum : (∑ i, a i*f i x) ≤ ∑ i, a i*f i y :=
    Finset.sum_le_sum (fun i _ => mul_le_mul_of_nonneg_left (hf i (le_of_lt hxy)) (ha i))
  nlinarith

theorem tone_black_plateau (black span : ℝ) (hspan : 0 < span) (x y : ℝ)
    (hx : x ≤ black) (hy : y ≤ black) :
    max 0 ((x-black)/span) = max 0 ((y-black)/span) := by
  rw [max_eq_left (div_nonpos_of_nonpos_of_nonneg (sub_nonpos.mpr hx) (le_of_lt hspan)),
      max_eq_left (div_nonpos_of_nonpos_of_nonneg (sub_nonpos.mpr hy) (le_of_lt hspan))]

theorem normal_weights (u1 u2 u3 : ℝ) (hu1 : u1 ≤ 1) (h12 : u2 ≤ u1)
    (h23 : u3 ≤ u2) (h3 : 0 ≤ u3) :
    0 ≤ 1-u1 ∧ 0 ≤ u1-u2 ∧ 0 ≤ u2-u3 ∧ 0 ≤ u3 ∧
    (1-u1)+(u1-u2)+(u2-u3)+u3 = 1 := by
  exact ⟨by linarith, by linarith, by linarith, h3, by ring⟩

theorem adaptance_weights (u0 u1 u2 u3 : ℝ) (h01 : u1 ≤ u0) (h12 : u2 ≤ u1)
    (h23 : u3 ≤ u2) (h3 : 0 ≤ u3) :
    0 ≤ u0-u1 ∧ 0 ≤ u1-u2 ∧ 0 ≤ u2-u3 ∧ 0 ≤ u3 ∧
    (u0-u1)+(u1-u2)+(u2-u3)+u3 = u0 := by
  exact ⟨by linarith, by linarith, by linarith, h3, by ring⟩

theorem stage2_saturation_preserved (C J k : ℝ) (hk : k ≠ 0) :
    75*(k*C)/(k*J) = 75*C/J := by
  rw [show 75*(k*C) = k*(75*C) by ring]
  exact mul_div_mul_left _ _ hk

end
end PerceptualGrade
