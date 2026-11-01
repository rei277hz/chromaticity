import PerceptualGrade.Spindle
import Mathlib.Analysis.SpecialFunctions.Sqrt

/- The reference-only analytic pole map. All constants are exact rationals. -/
namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped ContDiff Topology

def poleSpindleP : ℝ := 1002001 / 1000000
def poleSpindleA : ℝ := 3*poleSpindleP-1-2*20*(poleSpindleP-1)
def poleSpindleB : ℝ := 2*(poleSpindleP-1)-poleSpindleA
def poleSpindleF (z : ℝ) : ℝ :=
  z * (poleSpindleA+poleSpindleB*z) / ((1+z) * (poleSpindleP-z))
def poleSpindleFBlend (z : ℝ) : ℝ :=
  (1-19*(poleSpindleP-1)) *
      (z + z*(1-z)^2 / ((1+z)*(poleSpindleP-z))) +
    19*(poleSpindleP-1) * (z*(poleSpindleP-1)/(poleSpindleP-z))
def poleSpindleRelease (k x : ℝ) : ℝ :=
  x * Real.sqrt (1+(k^2-1)*poleSpindleF (x^2))
def poleSpindleFDerivative (z : ℝ) : ℝ :=
  (poleSpindleA-poleSpindleB) / ((poleSpindleP+1)*(1+z)^2) +
  poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP) / ((poleSpindleP+1)*(poleSpindleP-z)^2)
def poleSpindleSlope (k x : ℝ) : ℝ :=
  Real.sqrt (1+(k^2-1)*poleSpindleF (x^2)) +
  (k^2-1)*x^2*poleSpindleFDerivative (x^2) /
    Real.sqrt (1+(k^2-1)*poleSpindleF (x^2))

theorem pole_spindle_P_bounds : 1 < poleSpindleP ∧ poleSpindleP < 2 := by
  norm_num [poleSpindleP]

theorem pole_spindle_denominator_pos (z : ℝ) (hz : 0 ≤ z) (hp : z < poleSpindleP) :
    0 < (1+z)*(poleSpindleP-z) := by positivity

theorem pole_spindle_profile_coefficients :
    poleSpindleB < 0 ∧ 0 < poleSpindleA+poleSpindleB*poleSpindleP ∧
      0 < poleSpindleA-poleSpindleB := by
  norm_num [poleSpindleA, poleSpindleB, poleSpindleP]

theorem pole_spindle_profile_numerator_pos (z : ℝ) (hp : z < poleSpindleP) :
    0 < poleSpindleA+poleSpindleB*z := by
  have hb := pole_spindle_profile_coefficients.1
  have ha := pole_spindle_profile_coefficients.2.1
  nlinarith [mul_neg_of_neg_of_pos hb (sub_pos.mpr hp)]

theorem pole_spindle_blend_eq_profile (z : ℝ) (hl : 1+z ≠ 0)
    (hr : poleSpindleP-z ≠ 0) : poleSpindleFBlend z = poleSpindleF z := by
  unfold poleSpindleFBlend poleSpindleF poleSpindleB poleSpindleA
  field_simp
  ring

theorem pole_spindle_F_nonneg (z : ℝ) (hz : 0 ≤ z) (hp : z < poleSpindleP) :
    0 ≤ poleSpindleF z := by
  unfold poleSpindleF
  exact div_nonneg (mul_nonneg hz (pole_spindle_profile_numerator_pos z hp).le)
    (pole_spindle_denominator_pos z hz hp).le

theorem pole_spindle_F_pos (z : ℝ) (hz : 0 < z) (hp : z < poleSpindleP) :
    0 < poleSpindleF z := by
  unfold poleSpindleF
  exact div_pos (mul_pos hz (pole_spindle_profile_numerator_pos z hp))
    (pole_spindle_denominator_pos z hz.le hp)

theorem pole_spindle_radicand_pos (k x : ℝ) (hk : 1 ≤ k) (hx : x^2 < poleSpindleP) :
    0 < 1+(k^2-1)*poleSpindleF (x^2) := by
  have h : 0 ≤ k^2-1 := by nlinarith
  have := mul_nonneg h (pole_spindle_F_nonneg (x^2) (sq_nonneg _) hx)
  linarith

theorem pole_spindle_F_partial_fractions (z : ℝ) (hl : 1+z ≠ 0)
    (hr : poleSpindleP-z ≠ 0) :
    poleSpindleF z = -poleSpindleB - (poleSpindleA-poleSpindleB)/((poleSpindleP+1)*(1+z)) +
      poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP) / ((poleSpindleP+1)*(poleSpindleP-z)) := by
  unfold poleSpindleF
  have hp : poleSpindleP+1 ≠ 0 := by norm_num [poleSpindleP]
  field_simp
  ring

theorem pole_spindle_F_derivative (z : ℝ) (hl : 1+z ≠ 0)
    (hr : poleSpindleP-z ≠ 0) :
    HasDerivAt poleSpindleF (poleSpindleFDerivative z) z := by
  have hp : poleSpindleP+1 ≠ 0 := by norm_num [poleSpindleP]
  have h₁ := (hasDerivAt_const z (poleSpindleA-poleSpindleB)).div
    (((hasDerivAt_id z).const_add 1).const_mul (poleSpindleP+1)) (mul_ne_zero hp hl)
  have h₂ := (hasDerivAt_const z (poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP))).div
    (((hasDerivAt_id z).const_sub poleSpindleP).const_mul (poleSpindleP+1))
    (mul_ne_zero hp hr)
  have hd := ((hasDerivAt_const z (-poleSpindleB)).sub h₁).add h₂
  have he : poleSpindleF =ᶠ[𝓝 z] (fun y => -poleSpindleB - (poleSpindleA-poleSpindleB)/((poleSpindleP+1)*(1+y)) +
      poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP) / ((poleSpindleP+1)*(poleSpindleP-y))) := by
    filter_upwards [((continuous_const.add continuous_id).continuousAt.eventually_ne hl),
      ((continuous_const.sub continuous_id).continuousAt.eventually_ne hr)] with y hy hy'
    exact pole_spindle_F_partial_fractions y hy hy'
  convert hd.congr_of_eventuallyEq he using 1
  unfold poleSpindleFDerivative
  simp only [id_eq]
  field_simp
  ring

theorem pole_spindle_F_derivative_pos (z : ℝ) (hz : 0 ≤ z) (hp : z < poleSpindleP) :
    0 < poleSpindleFDerivative z := by
  unfold poleSpindleFDerivative
  have : 0 < poleSpindleP := lt_trans (by norm_num) pole_spindle_P_bounds.1
  have ha := pole_spindle_profile_coefficients.2.1
  have hb := pole_spindle_profile_coefficients.2.2
  positivity

theorem pole_spindle_profile_endpoints :
    poleSpindleF 0 = 0 ∧ poleSpindleF 1 = 1 ∧ poleSpindleFDerivative 1 = 20 := by
  norm_num [poleSpindleF, poleSpindleFDerivative, poleSpindleA, poleSpindleB, poleSpindleP]

theorem pole_spindle_release_zero (k : ℝ) : poleSpindleRelease k 0 = 0 := by
  simp [poleSpindleRelease]

theorem pole_spindle_release_one (k : ℝ) (hk : 1 ≤ k) : poleSpindleRelease k 1 = k := by
  have hF : poleSpindleF 1 = 1 := by norm_num [poleSpindleF, poleSpindleB, poleSpindleA, poleSpindleP]
  simp [poleSpindleRelease, hF, Real.sqrt_sq (show 0 ≤ k by linarith)]

theorem pole_spindle_identity (x : ℝ) : poleSpindleRelease 1 x = x := by
  simp [poleSpindleRelease]

theorem pole_spindle_release_derivative (k x : ℝ) (hk : 1 ≤ k)
    (hx : x^2 < poleSpindleP) :
    HasDerivAt (poleSpindleRelease k) (poleSpindleSlope k x) x := by
  have hp := pole_spindle_radicand_pos k x hk hx
  have hf := (pole_spindle_F_derivative (x^2) (by positivity) (by linarith)).comp x
    ((hasDerivAt_id x).pow 2)
  have hs := (((hf.const_mul (k^2-1)).const_add 1).sqrt hp.ne')
  convert (hasDerivAt_id x).mul hs using 1
  · rfl
  · unfold poleSpindleSlope
    simp only [Function.comp_apply, Pi.pow_apply, id_eq, Nat.cast_ofNat, mul_one]
    field_simp
    ring

theorem pole_spindle_slope_ge_one (k x : ℝ) (hk : 1 ≤ k)
    (hx : x^2 < poleSpindleP) : 1 ≤ poleSpindleSlope k x := by
  have ha : 0 ≤ k^2-1 := by nlinarith
  have hF := pole_spindle_F_nonneg (x^2) (sq_nonneg _) hx
  have hD := pole_spindle_F_derivative_pos (x^2) (sq_nonneg _) hx
  have hs : 1 ≤ Real.sqrt (1+(k^2-1)*poleSpindleF (x^2)) := by
    have h := Real.sqrt_le_sqrt (show (1:ℝ) ≤ 1+(k^2-1)*poleSpindleF (x^2) by
      nlinarith [mul_nonneg ha hF])
    simpa using h
  unfold poleSpindleSlope
  have hq : 0 ≤ (k^2-1)*x^2*poleSpindleFDerivative (x^2) /
      Real.sqrt (1+(k^2-1)*poleSpindleF (x^2)) := by positivity
  linarith

theorem pole_spindle_c2_at (k x : ℝ) (hk : 1 ≤ k) (hx : x^2 < poleSpindleP) :
    ContDiffAt ℝ 2 (poleSpindleRelease k) x := by
  have hp := (pole_spindle_radicand_pos k x hk hx).ne'
  have hd : (1+x^2)*(poleSpindleP-x^2) ≠ 0 :=
    (pole_spindle_denominator_pos (x^2) (sq_nonneg _) hx).ne'
  unfold poleSpindleRelease poleSpindleF at *
  fun_prop (disch := assumption)

theorem pole_spindle_c2 (k : ℝ) (hk : 1 ≤ k) :
    ContDiffOn ℝ 2 (poleSpindleRelease k) (Ioo (-(1001/1000)) (1001/1000)) := by
  intro x hx
  apply (pole_spindle_c2_at k x hk ?_).contDiffWithinAt
  norm_num [poleSpindleP] at *
  nlinarith [mul_pos (sub_pos.mpr hx.2) (sub_pos.mpr hx.1)]

theorem pole_spindle_neutral_derivative (k : ℝ) (hk : 1 ≤ k) :
    HasDerivAt (poleSpindleRelease k) 1 0 := by
  simpa [poleSpindleSlope, poleSpindleF] using
    pole_spindle_release_derivative k 0 hk (by norm_num [poleSpindleP])

theorem pole_spindle_neutral_second_derivative (k : ℝ) (hk : 1 ≤ k) :
    HasDerivAt (deriv (poleSpindleRelease k)) 0 0 := by
  let q : ℝ → ℝ := fun z => Real.sqrt (1+(k^2-1)*poleSpindleF z) +
    (k^2-1)*z*poleSpindleFDerivative z / Real.sqrt (1+(k^2-1)*poleSpindleF z)
  have hq : DifferentiableAt ℝ q 0 := by
    have hp : poleSpindleP ≠ 0 := by norm_num [poleSpindleP]
    have hs : Real.sqrt (1+(k^2-1)*poleSpindleF 0) ≠ 0 := by simp [poleSpindleF]
    have hr : 1+(k^2-1)*poleSpindleF 0 ≠ 0 := by simp [poleSpindleF]
    have hP : poleSpindleP+1 ≠ 0 := by norm_num [poleSpindleP]
    unfold q poleSpindleFDerivative poleSpindleF at *
    fun_prop (disch := norm_num [poleSpindleP] at *)
  have hd : HasDerivAt (poleSpindleSlope k) 0 0 := by
    have hpow : HasDerivAt (fun x : ℝ => x^2) (0:ℝ) (0:ℝ) := by
      have h := (hasDerivAt_id (0:ℝ)).pow 2
      norm_num at h
      exact h
    have hdq : HasDerivAt q (deriv q 0) ((fun x : ℝ => x^2) 0) := by
      simpa using hq.hasDerivAt
    convert hdq.comp (h := fun x : ℝ => x^2) 0 hpow using 1
    · rfl
    · simp
  apply hd.congr_of_eventuallyEq
  have he : ∀ᶠ x : ℝ in 𝓝 0, x^2 < poleSpindleP := by
    exact (isOpen_lt (by fun_prop : Continuous (fun x : ℝ => x^2)) continuous_const).mem_nhds
      (by norm_num [poleSpindleP])
  filter_upwards [he] with x hx
  exact (pole_spindle_release_derivative k x hk hx).deriv

theorem pole_spindle_endpoint_derivative (k : ℝ) (hk : 1 ≤ k) :
    HasDerivAt (poleSpindleRelease k) (k+20*(k^2-1)/k) 1 := by
  have h := pole_spindle_release_derivative k 1 hk (by norm_num [poleSpindleP])
  convert h using 1
  have hkn : k ≠ 0 := by linarith
  have hF : poleSpindleF 1 = 1 := by
    norm_num [poleSpindleF, poleSpindleA, poleSpindleB, poleSpindleP]
  have hD : poleSpindleFDerivative 1 = 20 := by
    norm_num [poleSpindleFDerivative, poleSpindleA, poleSpindleB, poleSpindleP]
  simp [poleSpindleSlope, hF, hD, Real.sqrt_sq (show 0 ≤ k by linarith)]
  ring

theorem pole_spindle_strict_mono (k : ℝ) (hk : 1 ≤ k) :
    StrictMonoOn (poleSpindleRelease k) (Icc 0 1) := by
  apply strictMonoOn_of_deriv_pos (convex_Icc 0 1)
  · intro x hx
    apply (pole_spindle_c2_at k x hk ?_).continuousAt.continuousWithinAt
    have := pole_spindle_P_bounds.1
    nlinarith [hx.1, hx.2]
  · intro x hx
    have hi : x ∈ Icc (0:ℝ) 1 := interior_subset hx
    have hp : x^2 < poleSpindleP := by
      have := pole_spindle_P_bounds.1
      nlinarith [hi.1, hi.2]
    rw [(pole_spindle_release_derivative k x hk hp).deriv]
    exact lt_of_lt_of_le (by norm_num) (pole_spindle_slope_ge_one k x hk hp)

theorem pole_spindle_strict_mono_extended (k : ℝ) (hk : 1 ≤ k) :
    StrictMonoOn (poleSpindleRelease k) (Ioo (-(1001/1000)) (1001/1000)) := by
  apply strictMonoOn_of_deriv_pos (convex_Ioo (-(1001/1000)) (1001/1000))
  · exact (pole_spindle_c2 k hk).continuousOn
  · intro x hx
    have hi : x ∈ Ioo (-(1001/1000):ℝ) (1001/1000) := interior_subset hx
    have hp : x^2 < poleSpindleP := by
      norm_num [poleSpindleP] at *
      nlinarith [mul_pos (sub_pos.mpr hi.2) (sub_pos.mpr hi.1)]
    rw [(pole_spindle_release_derivative k x hk hp).deriv]
    exact lt_of_lt_of_le (by norm_num) (pole_spindle_slope_ge_one k x hk hp)

theorem pole_spindle_bounds (k x : ℝ) (hk : 1 ≤ k) (hx : x ∈ Icc 0 1) :
    poleSpindleRelease k x ∈ Icc 0 k := by
  have hm := (pole_spindle_strict_mono k hk).monotoneOn
  constructor
  · simpa only [pole_spindle_release_zero] using hm (show (0:ℝ) ∈ Icc 0 1 by norm_num) hx hx.1
  · simpa only [pole_spindle_release_one k hk] using hm hx (show (1:ℝ) ∈ Icc 0 1 by norm_num) hx.2

theorem pole_spindle_global_compression (k x : ℝ) (hk : 1 < k) (hx : 0 < x)
    (hp : x^2 < poleSpindleP) : x < poleSpindleRelease k x := by
  have ha : 0 < k^2-1 := by nlinarith
  have hF := pole_spindle_F_pos (x^2) (sq_pos_of_pos hx) hp
  have hs : 1 < Real.sqrt (1+(k^2-1)*poleSpindleF (x^2)) := by
    have h := Real.sqrt_lt_sqrt (by norm_num : (0:ℝ) ≤ 1)
      (show (1:ℝ) < 1+(k^2-1)*poleSpindleF (x^2) by nlinarith [mul_pos ha hF])
    simpa using h
  simpa [poleSpindleRelease] using mul_lt_mul_of_pos_left hs hx

theorem pole_spindle_inverse_unique (k x y : ℝ) (hk : 1 ≤ k)
    (hx : x ∈ Icc 0 1) (hy : y ∈ Icc 0 1)
    (he : poleSpindleRelease k x = poleSpindleRelease k y) : x=y :=
  (pole_spindle_strict_mono k hk).injOn hx hy he

theorem pole_spindle_inverse_exists (k y : ℝ) (hk : 1 ≤ k)
    (hy : y ∈ Icc 0 k) : ∃! x, x ∈ Icc 0 1 ∧ poleSpindleRelease k x=y := by
  have hi : y ∈ Icc (poleSpindleRelease k 0) (poleSpindleRelease k 1) := by
    simpa only [pole_spindle_release_zero, pole_spindle_release_one k hk] using hy
  have hc : ContinuousOn (poleSpindleRelease k) (Icc 0 1) := by
    intro x hx
    apply (pole_spindle_c2_at k x hk ?_).continuousAt.continuousWithinAt
    have := pole_spindle_P_bounds.1
    nlinarith [hx.1, hx.2]
  obtain ⟨x, hx, he⟩ := intermediate_value_Icc (show (0:ℝ) ≤ 1 by norm_num) hc hi
  refine ⟨x, ⟨hx, he⟩, ?_⟩
  intro z hz
  exact pole_spindle_inverse_unique k z x hk hz.1 hx (hz.2.trans he.symm)

theorem pole_spindle_F_tendsto_pole :
    Tendsto poleSpindleF (𝓝[<] poleSpindleP) atTop := by
  have hid : Tendsto (fun z : ℝ => z) (𝓝[<] poleSpindleP) (𝓝 poleSpindleP) :=
    tendsto_id.mono_right nhdsWithin_le_nhds
  have hd : Tendsto (fun z : ℝ => poleSpindleP-z) (𝓝[<] poleSpindleP) (𝓝[>] 0) := by
    apply tendsto_nhdsWithin_iff.mpr
    constructor
    · simpa using (tendsto_const_nhds : Tendsto (fun _ : ℝ => poleSpindleP)
        (𝓝[<] poleSpindleP) (𝓝 poleSpindleP)).sub hid
    · filter_upwards [self_mem_nhdsWithin] with z hz
      change 0 < poleSpindleP-z
      exact sub_pos.mpr hz
  have hi := hd.inv_tendsto_nhdsGT_zero
  have hc : 0 < poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP)/(poleSpindleP+1) := by
    norm_num [poleSpindleP, poleSpindleA, poleSpindleB]
  have hpole : Tendsto
      (fun z : ℝ => poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP) / ((poleSpindleP+1)*(poleSpindleP-z)))
      (𝓝[<] poleSpindleP) atTop := by
    convert (tendsto_const_nhds : Tendsto (fun _ : ℝ =>
      poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP)/(poleSpindleP+1)) (𝓝[<] poleSpindleP)
      (𝓝 (poleSpindleP*(poleSpindleA+poleSpindleB*poleSpindleP)/(poleSpindleP+1)))).pos_mul_atTop hc hi using 1
    funext z
    simp [div_eq_mul_inv, mul_assoc, mul_comm, mul_left_comm]
  have hregular : Tendsto (fun z : ℝ => -poleSpindleB-(poleSpindleA-poleSpindleB)/((poleSpindleP+1)*(1+z)))
      (𝓝[<] poleSpindleP) (𝓝 (-poleSpindleB-(poleSpindleA-poleSpindleB)/((poleSpindleP+1)*(1+poleSpindleP)))) := by
    have hc : ContinuousAt (fun z : ℝ => -poleSpindleB-(poleSpindleA-poleSpindleB)/((poleSpindleP+1)*(1+z)))
        poleSpindleP := by fun_prop (disch := norm_num [poleSpindleP])
    exact hc.tendsto.mono_left nhdsWithin_le_nhds
  apply (hregular.add_atTop hpole).congr'
  have hl : ∀ᶠ z : ℝ in 𝓝[<] poleSpindleP, 1+z ≠ 0 :=
    ((continuous_const.add continuous_id).continuousAt.eventually_ne
      (show 1+poleSpindleP ≠ 0 by norm_num [poleSpindleP])).filter_mono nhdsWithin_le_nhds
  filter_upwards [hl, self_mem_nhdsWithin] with z hz hp
  exact (pole_spindle_F_partial_fractions z hz (sub_pos.mpr hp).ne').symm

theorem pole_spindle_release_tendsto_pole (k : ℝ) (hk : 1 < k) :
    Tendsto (poleSpindleRelease k) (𝓝[<] (1001/1000)) atTop := by
  have hid : Tendsto (fun x : ℝ => x) (𝓝[<] (1001/1000)) (𝓝 (1001/1000)) :=
    tendsto_id.mono_right nhdsWithin_le_nhds
  have hs : Tendsto (fun x : ℝ => x^2) (𝓝[<] (1001/1000)) (𝓝[<] poleSpindleP) := by
    apply tendsto_nhdsWithin_iff.mpr
    constructor
    · convert hid.pow 2 using 1
      norm_num [poleSpindleP]
    · have hpos : ∀ᶠ x : ℝ in 𝓝[<] (1001/1000), 0 < x :=
        (eventually_gt_nhds (by norm_num : (0:ℝ) < 1001/1000)).filter_mono nhdsWithin_le_nhds
      filter_upwards [hpos, self_mem_nhdsWithin] with x hx hp
      change x^2 < poleSpindleP
      norm_num [poleSpindleP] at *
      nlinarith
  have hF := pole_spindle_F_tendsto_pole.comp hs
  have hA : Tendsto (fun x : ℝ => (k^2-1)*poleSpindleF (x^2))
      (𝓝[<] (1001/1000)) atTop :=
    (tendsto_const_nhds : Tendsto (fun _ : ℝ => k^2-1) (𝓝[<] (1001/1000)) (𝓝 (k^2-1))).pos_mul_atTop
      (by nlinarith) hF
  have hr := (tendsto_const_nhds : Tendsto (fun _ : ℝ => (1:ℝ)) (𝓝[<] (1001/1000)) (𝓝 1)).add_atTop hA
  exact hid.pos_mul_atTop (by norm_num) (Real.tendsto_sqrt_atTop.comp hr)

end
end PerceptualGrade
