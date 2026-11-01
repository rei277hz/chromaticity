import PerceptualGrade.ContinuousGuard
import PerceptualGrade.Tone

/- B is sqrt(66*C) in the executable model. Using |B| here makes the exact
   coordinate definitions total on ℝ², without changing that physical domain. -/
namespace PerceptualGrade
noncomputable section
open Set

def signedEnergy (J : ℝ) : ℝ := J*|J|
def signedRoot (E : ℝ) : ℝ := if 0 ≤ E then Real.sqrt E else -Real.sqrt (-E)
def hkMagnitude (J B : ℝ) : ℝ := Real.sqrt (J^2+B^2)
def signedHK (J B : ℝ) : ℝ := if 0 ≤ J then hkMagnitude J B else 2*|B|-hkMagnitude J B
def hkEnergy (H B : ℝ) : ℝ := (H-|B|)*(abs (H-|B|)+2*|B|)

theorem signed_energy_strictMono : StrictMono signedEnergy := by
  intro x y h
  by_cases hx : 0 ≤ x <;> by_cases hy : 0 ≤ y
  · simp only [signedEnergy, abs_of_nonneg hx, abs_of_nonneg hy]
    nlinarith
  · linarith
  · simp only [signedEnergy, abs_of_neg (lt_of_not_ge hx), abs_of_nonneg hy]
    nlinarith
  · simp only [signedEnergy, abs_of_neg (lt_of_not_ge hx), abs_of_neg (lt_of_not_ge hy)]
    nlinarith

theorem signed_root_squared (E : ℝ) : (signedRoot E)^2 = |E| := by
  by_cases h : 0 ≤ E
  · simp [signedRoot, h, abs_of_nonneg h, Real.sq_sqrt h]
  · simp [signedRoot, h, abs_of_neg (lt_of_not_ge h), Real.sq_sqrt (by linarith : 0 ≤ -E)]

theorem signed_root_nonneg (E : ℝ) (h : 0 ≤ E) : 0 ≤ signedRoot E := by
  simp [signedRoot, h, Real.sqrt_nonneg]

theorem signed_root_negative (E : ℝ) (h : E < 0) : signedRoot E < 0 := by
  simp [signedRoot, not_le_of_gt h, Real.sqrt_pos.2 (by linarith : 0 < -E)]

theorem signed_energy_root (E : ℝ) : signedEnergy (signedRoot E) = E := by
  by_cases h : 0 ≤ E
  · have hs := signed_root_squared E
    simp only [signedEnergy, abs_of_nonneg (signed_root_nonneg E h), abs_of_nonneg h] at *
    nlinarith
  · have hs := signed_root_squared E
    simp only [signedEnergy, abs_of_neg (signed_root_negative E (lt_of_not_ge h)),
      abs_of_neg (lt_of_not_ge h)] at *
    nlinarith

theorem signed_root_energy (J : ℝ) : signedRoot (signedEnergy J) = J := by
  apply signed_energy_strictMono.injective
  exact signed_energy_root _

theorem signed_energy_continuous : Continuous signedEnergy := by
  unfold signedEnergy
  fun_prop

theorem signed_root_continuous : Continuous signedRoot := by
  unfold signedRoot
  apply Continuous.if _ (by fun_prop) (by fun_prop)
  intro E hE
  have : E = 0 := by
    simpa only [show {E : ℝ | 0 ≤ E} = Ici 0 from rfl, frontier_Ici, mem_singleton_iff] using hE
  subst E
  simp

theorem hk_magnitude_squared (J B : ℝ) : (hkMagnitude J B)^2 = J^2+B^2 := by
  exact Real.sq_sqrt (by positivity)

theorem hk_magnitude_bound (J B : ℝ) : |B| ≤ hkMagnitude J B := by
  have hs := hk_magnitude_squared J B
  have hn : 0 ≤ hkMagnitude J B := Real.sqrt_nonneg _
  nlinarith [sq_abs B, abs_nonneg B]

theorem hk_energy_inverse (J B : ℝ) : hkEnergy (signedHK J B) B = signedEnergy J := by
  have hs := hk_magnitude_squared J B
  have hb := hk_magnitude_bound J B
  by_cases h : 0 ≤ J
  · simp only [signedHK, h, ite_true, hkEnergy, abs_of_nonneg (sub_nonneg.2 hb),
      signedEnergy, abs_of_nonneg h]
    nlinarith [sq_abs B]
  · have hu : 2*|B|-hkMagnitude J B-|B| ≤ 0 := by linarith
    simp only [signedHK, h, ite_false, hkEnergy, abs_of_nonpos hu,
      signedEnergy, abs_of_neg (lt_of_not_ge h)]
    nlinarith [sq_abs B]

theorem hk_coordinate_inverse (H B : ℝ) : signedHK (signedRoot (hkEnergy H B)) B = H := by
  have hb : 0 ≤ |B| := abs_nonneg B
  have hm := hk_magnitude_squared (signedRoot (hkEnergy H B)) B
  have hn : 0 ≤ hkMagnitude (signedRoot (hkEnergy H B)) B := Real.sqrt_nonneg _
  by_cases h : |B| ≤ H
  · have he : 0 ≤ hkEnergy H B := by unfold hkEnergy; positivity
    have hj := signed_root_nonneg (hkEnergy H B) he
    have hs : (signedRoot (hkEnergy H B))^2 = H^2-B^2 := by
      rw [signed_root_squared, abs_of_nonneg he]
      unfold hkEnergy
      rw [abs_of_nonneg (sub_nonneg.2 h)]
      nlinarith [sq_abs B]
    have hmH : hkMagnitude (signedRoot (hkEnergy H B)) B = H := by
      nlinarith [sq_abs B]
    simp [signedHK, hj, hmH]
  · have hu : H-|B| < 0 := sub_neg.2 (lt_of_not_ge h)
    have he : hkEnergy H B < 0 := by
      unfold hkEnergy
      rw [abs_of_neg hu]
      exact mul_neg_of_neg_of_pos hu (by linarith)
    have hj := signed_root_negative (hkEnergy H B) he
    have hs : (signedRoot (hkEnergy H B))^2 = (2*|B|-H)^2-B^2 := by
      rw [signed_root_squared, abs_of_neg he]
      unfold hkEnergy
      rw [abs_of_neg hu]
      nlinarith [sq_abs B]
    have hmH : hkMagnitude (signedRoot (hkEnergy H B)) B = 2*|B|-H := by
      nlinarith [sq_abs B]
    simp [signedHK, not_le_of_gt hj, hmH]

theorem signed_hk_inverse (J B : ℝ) : signedRoot (hkEnergy (signedHK J B) B) = J := by
  rw [hk_energy_inverse, signed_root_energy]

theorem signed_hk_unique (H B : ℝ) : ∃! J, signedHK J B = H := by
  refine ⟨signedRoot (hkEnergy H B), hk_coordinate_inverse H B, ?_⟩
  intro J hJ
  rw [← hJ, signed_hk_inverse]

theorem hk_energy_strictMono (B : ℝ) : StrictMono (fun H => hkEnergy H B) := by
  intro x y hxy
  have hu : x-|B| < y-|B| := by linarith
  have he := signed_energy_strictMono hu
  have hb : 0 ≤ |B| := abs_nonneg B
  have hl := mul_le_mul_of_nonneg_right (le_of_lt hu) (by positivity : 0 ≤ 2*|B|)
  unfold hkEnergy signedEnergy at *
  nlinarith

theorem signed_hk_strictMono (B : ℝ) : StrictMono (fun J => signedHK J B) := by
  intro x y hxy
  have he := signed_energy_strictMono hxy
  have hx := hk_energy_inverse x B
  have hy := hk_energy_inverse y B
  by_contra h
  have hm := (hk_energy_strictMono B).monotone (le_of_not_gt h)
  rw [hx, hy] at hm
  linarith

theorem signed_hk_continuous : Continuous (fun p : ℝ × ℝ => signedHK p.1 p.2) := by
  unfold signedHK hkMagnitude
  apply Continuous.if _ (by fun_prop) (by fun_prop)
  intro p hp
  have h := (continuous_fst : Continuous (Prod.fst : ℝ × ℝ → ℝ)).frontier_preimage_subset (Ici 0) hp
  have hz : p.1 = 0 := by simpa only [frontier_Ici, mem_preimage, mem_singleton_iff] using h
  simp only [hz, zero_pow (by norm_num : (2:ℕ) ≠ 0), zero_add, Real.sqrt_sq_eq_abs]
  ring

theorem hk_energy_continuous : Continuous (fun p : ℝ × ℝ => hkEnergy p.1 p.2) := by
  unfold hkEnergy
  fun_prop

theorem signed_decoder_continuous :
    Continuous (fun p : ℝ × ℝ => signedRoot (hkEnergy p.1 p.2)) :=
  signed_root_continuous.comp hk_energy_continuous

theorem signed_hk_opponents_continuous :
    Continuous (fun p : ℝ × (ℝ × ℝ) =>
      signedHK p.1 (Real.sqrt (66*Real.sqrt (p.2.1^2+p.2.2^2)))) := by
  exact signed_hk_continuous.comp (show Continuous (fun p : ℝ × (ℝ × ℝ) =>
    (p.1, Real.sqrt (66*Real.sqrt (p.2.1^2+p.2.2^2)))) by fun_prop)

theorem signed_hk_positive (J B : ℝ) (h : 0 ≤ J) : signedHK J B = hkMagnitude J B := by
  simp [signedHK, h]

theorem signed_hk_neutral (J : ℝ) : signedHK J 0 = J := by
  by_cases h : 0 ≤ J
  · simp [signedHK, hkMagnitude, h]
  · simp [signedHK, hkMagnitude, h, Real.sqrt_sq_eq_abs, abs_of_neg (lt_of_not_ge h)]

theorem signed_hk_achromatic_zero (B : ℝ) : signedHK 0 B = |B| := by
  simp [signedHK, hkMagnitude, Real.sqrt_sq_eq_abs]

theorem zero_coordinate_nonblack (B : ℝ) (h : 0 < B) :
    hkEnergy 0 B = -3*B^2 ∧ signedRoot (hkEnergy 0 B) < 0 := by
  have he : hkEnergy 0 B = -3*B^2 := by simp [hkEnergy, abs_of_pos h]; ring
  exact ⟨he, signed_root_negative _ (by rw [he]; nlinarith)⟩

theorem signed_energy_positive_scale (s J : ℝ) (hs : 0 < s) :
    signedEnergy (s*J) = s^2*signedEnergy J := by
  simp only [signedEnergy, abs_mul, abs_of_pos hs]
  ring

theorem signed_energy_response_scale (s gamma J : ℝ) (hs : 0 < s) :
    signedEnergy (s^gamma*J) = s^(2*gamma)*signedEnergy J := by
  rw [signed_energy_positive_scale _ _ (Real.rpow_pos_of_pos hs _),
    ← Real.rpow_natCast, ← Real.rpow_mul (le_of_lt hs)]
  congr 2
  ring

theorem tone_signed_magnitude (J C H : ℝ) (hC : 0 ≤ C) (hH : 0 < H)
    (hp : 0 < (66*C)^2+4*J^2*H^2) :
    hkMagnitude (toneGain J C H*J) (Real.sqrt (66*(toneGain J C H*C))) = H := by
  have hg := tone_gain_positive J C H hC hH hp
  have hq := tone_gain_quadratic J C H hC hp
  have hc : 0 ≤ 66*(toneGain J C H*C) := by positivity
  have hs := hk_magnitude_squared (toneGain J C H*J) (Real.sqrt (66*(toneGain J C H*C)))
  have hn : 0 ≤ hkMagnitude (toneGain J C H*J) (Real.sqrt (66*(toneGain J C H*C))) := Real.sqrt_nonneg _
  rw [Real.sq_sqrt hc] at hs
  nlinarith

theorem tone_sign_preserved (J k : ℝ) (hk : 0 < k) :
    (0 < k*J ↔ 0 < J) ∧ (k*J < 0 ↔ J < 0) := by
  constructor <;> constructor <;> intro h <;> nlinarith

theorem tone_absolute_saturation (C J k : ℝ) (hk : 0 < k) :
    75*(k*C)/|k*J| = 75*C/|J| := by
  rw [abs_mul, abs_of_pos hk]
  rw [show 75*(k*C) = k*(75*C) by ring]
  exact mul_div_mul_left _ _ (ne_of_gt hk)

theorem carried_energy_reset (J B : ℝ) : hkEnergy (signedHK J B) B = signedEnergy J :=
  hk_energy_inverse J B

theorem relative_energy_same_sign (u v B : ℝ) (h : u*v ≥ 0) :
    u*(|u|+2*B)-v*(|v|+2*B) = (u-v)*(|u|+|v|+2*B) := by
  by_cases hu : 0 ≤ u <;> by_cases hv : 0 ≤ v
  · simp only [abs_of_nonneg hu, abs_of_nonneg hv]; ring
  · have hz : u = 0 := by nlinarith
    simp [hz, abs_of_neg (lt_of_not_ge hv)]
  · have hz : v = 0 := by nlinarith
    simp [hz, abs_of_neg (lt_of_not_ge hu)]
  · simp only [abs_of_neg (lt_of_not_ge hu), abs_of_neg (lt_of_not_ge hv)]; ring

theorem relative_energy_opposite_sign (u v B : ℝ) (h : u*v < 0) :
    u*(|u|+2*B)-v*(|v|+2*B) = (u-v)*((u^2+v^2)/(|u|+|v|)+2*B) := by
  have hd : |u|+|v| ≠ 0 := by
    intro hz
    have : u = 0 := abs_eq_zero.mp (by nlinarith [abs_nonneg u, abs_nonneg v])
    simp [this] at h
  by_cases hu : 0 ≤ u
  · have hv : v < 0 := by nlinarith
    rw [abs_of_nonneg hu, abs_of_neg hv] at hd ⊢
    field_simp [hd]
    ring
  · have hv : 0 < v := by nlinarith
    rw [abs_of_neg (lt_of_not_ge hu), abs_of_pos hv] at hd ⊢
    field_simp [hd]
    ring

def signedPow (x p : ℝ) : ℝ := if 0 ≤ x then x^p else -(-x)^p

theorem signed_pow_zero (p : ℝ) (hp : 0 < p) : signedPow 0 p = 0 := by
  simp [signedPow, Real.zero_rpow (ne_of_gt hp)]

theorem signed_pow_inverse (x p : ℝ) (hp : 0 < p) :
    signedPow (signedPow x p) p⁻¹ = x := by
  by_cases hx : 0 ≤ x
  · have hr : 0 ≤ x^p := Real.rpow_nonneg hx _
    simp only [signedPow, hx, ite_true, hr, Real.rpow_rpow_inv hx (ne_of_gt hp)]
  · have hn : 0 < -x := by linarith
    have hr := Real.rpow_pos_of_pos hn p
    have hs : ¬0 ≤ -(-x)^p := by linarith
    simp only [signedPow, hx, ite_false, hs, neg_neg,
      Real.rpow_rpow_inv (le_of_lt hn) (ne_of_gt hp)]

theorem signed_pow_continuous (p : ℝ) (hp : 0 < p) : Continuous (fun x => signedPow x p) := by
  unfold signedPow
  apply Continuous.if _ (Real.continuous_rpow_const (le_of_lt hp))
    ((Real.continuous_rpow_const (le_of_lt hp)).comp continuous_neg |>.neg)
  intro x hx
  have : x = 0 := by
    simpa only [show {x : ℝ | 0 ≤ x} = Ici 0 from rfl, frontier_Ici, mem_singleton_iff] using hx
  subst x
  simp [Real.zero_rpow (ne_of_gt hp)]

theorem signed_pow_positive_scale (s x p : ℝ) (hs : 0 < s) :
    signedPow (s*x) p = s^p*signedPow x p := by
  by_cases hx : 0 ≤ x
  · have h := mul_nonneg (le_of_lt hs) hx
    simp only [signedPow, hx, h, ite_true, Real.mul_rpow (le_of_lt hs) hx]
  · have h : ¬0 ≤ s*x := by nlinarith
    have hn : 0 ≤ -x := by linarith
    simp only [signedPow, hx, h, ite_false]
    rw [show -(s*x) = s*(-x) by ring, Real.mul_rpow (le_of_lt hs) hn]
    ring

theorem signed_achromatic_roundtrip (A Aw gamma : ℝ) (hw : 0 < Aw) (hg : 0 < gamma) :
    Aw*signedPow (signedRoot (signedEnergy (100*signedPow (A/Aw) gamma)) / 100) gamma⁻¹ = A := by
  rw [signed_root_energy]
  have he : 100*signedPow (A/Aw) gamma/100 = signedPow (A/Aw) gamma := by ring
  rw [he, signed_pow_inverse _ _ hg]
  field_simp

def signedCompression (FL x : ℝ) : ℝ :=
  if 0 ≤ x then responseCompression FL x else -responseCompression FL (-x)
def signedResponseInverse (FL r : ℝ) : ℝ :=
  if 0 ≤ r then responseInverse FL r else -responseInverse FL (-r)

theorem signed_compression_domain (FL x : ℝ) (hf : 0 < FL) : |signedCompression FL x| < 400 := by
  rcases lt_trichotomy 0 x with h | h | h
  · have hd := compression_domain FL x hf h
    simp only [signedCompression, le_of_lt h, ite_true, abs_of_pos hd.1]
    exact hd.2
  · rw [← h]
    norm_num [signedCompression, responseCompression]
  · have hd := compression_domain FL (-x) hf (by linarith)
    simp only [signedCompression, not_le_of_gt h, ite_false, abs_neg, abs_of_pos hd.1]
    exact hd.2

theorem signed_compression_inverse (FL x : ℝ) (hf : 0 < FL) :
    signedResponseInverse FL (signedCompression FL x) = x := by
  rcases lt_trichotomy 0 x with h | h | h
  · have hd := compression_domain FL x hf h
    simp only [signedCompression, le_of_lt h, ite_true, signedResponseInverse,
      le_of_lt hd.1, compression_inverse FL x hf h]
  · rw [← h]
    norm_num [signedCompression, signedResponseInverse, responseCompression, responseInverse]
  · have hn : 0 < -x := by linarith
    have hd := compression_domain FL (-x) hf hn
    have hr : ¬0 ≤ -responseCompression FL (-x) := by linarith
    simp only [signedCompression, not_le_of_gt h, ite_false, signedResponseInverse,
      hr, neg_neg, compression_inverse FL (-x) hf hn]

theorem relative_energy_chroma_change (u u0 B B0 slope : ℝ)
    (hd : u*(|u|+2*B)-u0*(|u0|+2*B) = (u-u0)*(slope+2*B)) :
    u*(|u|+2*B)-u0*(|u0|+2*B0) = (u-u0)*(slope+2*B)+2*u0*(B-B0) := by
  linear_combination hd

end
end PerceptualGrade
