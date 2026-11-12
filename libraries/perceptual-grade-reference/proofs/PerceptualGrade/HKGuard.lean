import PerceptualGrade.ContinuousGuard

/- Exact-real properties of the H–K repair before final Warp Scale. The requested energy D is
   H²−66C, not the signed appearance continuation below that boundary. -/
namespace PerceptualGrade
noncomputable section
open Set
open scoped ContDiff

def hkGuardDelta (E0 X : ℝ) : ℝ := E0*X/(E0+X)
def hkGuardPolynomial (t : ℝ) : ℝ := 1+4*t+10*t^2
def hkGuardRoot (t : ℝ) : ℝ := Real.sqrt (Real.sqrt (hkGuardPolynomial t))
def hkGuardFloor (δ D : ℝ) : ℝ := δ/hkGuardRoot ((δ-D)/δ)
def hkGuardEnergy (δ D : ℝ) : ℝ :=
  if δ ≤ D then D else if 0 < δ then hkGuardFloor δ D else 0
def hkGuardAllocation (L Z : ℝ) : ℝ := L*Z/Real.sqrt (4*L^2+Z^2)
def hkGuardLift (X E D : ℝ) : ℝ := hkGuardAllocation ((11/25 : ℝ)*X) (E-D)
def hkGuardChroma (X C E : ℝ) : ℝ :=
  (X+hkGuardLift X E (X-66*C)-E)/66

theorem hk_guard_delta_bounds (E0 X : ℝ) (he : 0 ≤ E0) (hx : 0 ≤ X) :
    0 ≤ hkGuardDelta E0 X ∧ hkGuardDelta E0 X ≤ E0 ∧ hkGuardDelta E0 X ≤ X := by
  by_cases h : E0+X = 0
  · simp [hkGuardDelta, h, he, hx]
  · have hd : 0 < E0+X := lt_of_le_of_ne (by positivity) (Ne.symm h)
    unfold hkGuardDelta
    refine ⟨by positivity, (div_le_iff₀ hd).2 ?_, (div_le_iff₀ hd).2 ?_⟩ <;>
      nlinarith [sq_nonneg E0, sq_nonneg X]

theorem hk_guard_delta_positive (E0 X : ℝ) (he : 0 < E0) (hx : 0 < X) :
    0 < hkGuardDelta E0 X := by unfold hkGuardDelta; positivity

theorem hk_guard_delta_lt_height (E0 X : ℝ) (he : 0 ≤ E0) (hx : 0 < X) :
    hkGuardDelta E0 X < X := by
  unfold hkGuardDelta
  apply (div_lt_iff₀ (by positivity)).2
  nlinarith [sq_pos_of_pos hx]

theorem hk_guard_delta_monotone (E0 : ℝ) (he : 0 < E0) :
    StrictMonoOn (hkGuardDelta E0) (Ici 0) := by
  intro x hx y hy hxy
  change 0 ≤ x at hx
  change 0 ≤ y at hy
  unfold hkGuardDelta
  apply (div_lt_div_iff₀ (by positivity) (by positivity)).2
  nlinarith [mul_pos (sq_pos_of_pos he) (sub_pos.mpr hxy)]

theorem hk_guard_delta_stable (E0 X : ℝ) (he : 0 ≤ E0) (hx : 0 < X) :
    hkGuardDelta E0 X = E0/(1+E0/X) := by
  unfold hkGuardDelta
  have hd : E0+X ≠ 0 := ne_of_gt (by positivity)
  field_simp
  ring

theorem hk_guard_polynomial_positive (t : ℝ) : 0 < hkGuardPolynomial t := by
  unfold hkGuardPolynomial
  nlinarith [sq_nonneg (5*t+1)]

theorem hk_guard_root_positive (t : ℝ) : 0 < hkGuardRoot t := by
  exact Real.sqrt_pos.2 (Real.sqrt_pos.2 (hk_guard_polynomial_positive t))

theorem hk_guard_root_fourth (t : ℝ) : (hkGuardRoot t)^4 = hkGuardPolynomial t := by
  have h := Real.sq_sqrt (le_of_lt (hk_guard_polynomial_positive t))
  have hh := Real.sq_sqrt (Real.sqrt_nonneg (hkGuardPolynomial t))
  unfold hkGuardRoot
  nlinarith [sq_nonneg (Real.sqrt (Real.sqrt (hkGuardPolynomial t)))]

theorem hk_guard_root_ge_one (t : ℝ) (ht : 0 ≤ t) : 1 ≤ hkGuardRoot t := by
  have hp : 1 ≤ hkGuardPolynomial t := by unfold hkGuardPolynomial; nlinarith
  have h1 := Real.sqrt_le_sqrt hp
  have h2 := Real.sqrt_le_sqrt h1
  simpa [hkGuardRoot] using h2

theorem hk_guard_energy_identity (δ D : ℝ) (h : δ ≤ D) : hkGuardEnergy δ D = D := by
  simp [hkGuardEnergy, h]

theorem hk_guard_energy_nonnegative (δ D : ℝ) (hd : 0 ≤ δ) : 0 ≤ hkGuardEnergy δ D := by
  unfold hkGuardEnergy
  split_ifs with h hpos
  · linarith
  · unfold hkGuardFloor
    exact le_of_lt (div_pos hpos (hk_guard_root_positive _))
  · rfl

theorem hk_guard_energy_positive (δ D : ℝ) (hd : 0 < δ) : 0 < hkGuardEnergy δ D := by
  unfold hkGuardEnergy
  split_ifs with h
  · linarith
  · exact div_pos hd (hk_guard_root_positive _)

theorem hk_guard_floor_le_knee (δ D : ℝ) (hd : 0 < δ) (hD : D ≤ δ) :
    hkGuardFloor δ D ≤ δ := by
  have ht : 0 ≤ (δ-D)/δ := div_nonneg (by linarith) (le_of_lt hd)
  unfold hkGuardFloor
  exact (div_le_iff₀ (hk_guard_root_positive _)).2 (by
    nlinarith [mul_le_mul_of_nonneg_left (hk_guard_root_ge_one _ ht) (le_of_lt hd)])

theorem hk_guard_floor_above_request (δ D : ℝ) (hd : 0 < δ) (hD : D ≤ δ) :
    D ≤ hkGuardFloor δ D := by
  by_cases hn : D ≤ 0
  · exact le_trans hn (le_of_lt (div_pos hd (hk_guard_root_positive _)))
  · let t := (δ-D)/δ
    have ht : 0 ≤ t := div_nonneg (by linarith) (le_of_lt hd)
    have ht1 : t ≤ 1 := (div_le_one hd).2 (by linarith)
    have hr := hk_guard_root_positive t
    have hf := hk_guard_root_fourth t
    have hp : hkGuardPolynomial t*(1-t)^4 ≤ 1 := by
      have h : 0 ≤ t^3*(1+3*(1-t)+6*(1-t)^2+10*(1-t)^3) := by positivity
      unfold hkGuardPolynomial
      nlinarith only [h]
    have hh : (hkGuardRoot t*(1-t))^4 ≤ 1 := by
      rw [mul_pow, hf]
      exact hp
    have hprod : hkGuardRoot t*(1-t) ≤ 1 := by
      have hs : 0 ≤ (hkGuardRoot t*(1-t))^2 := sq_nonneg _
      have hs2 : (hkGuardRoot t*(1-t))^2 ≤ 1 := by nlinarith only [hh, hs]
      nlinarith only [hs2]
    have he : D = δ*(1-t) := by dsimp [t]; field_simp; ring
    unfold hkGuardFloor
    apply (le_div_iff₀ hr).2
    rw [he]
    nlinarith only [mul_le_mul_of_nonneg_left hprod (le_of_lt hd)]

theorem hk_guard_energy_above_request (δ D : ℝ) :
    D ≤ hkGuardEnergy δ D := by
  unfold hkGuardEnergy
  split_ifs with h hp
  · rfl
  · exact hk_guard_floor_above_request δ D hp (le_of_not_ge h)
  · linarith

theorem hk_guard_energy_le_height (E0 X D : ℝ) (h0 : 0 ≤ E0) (hx : 0 ≤ X)
    (hD : D ≤ X) : hkGuardEnergy (hkGuardDelta E0 X) D ≤ X := by
  unfold hkGuardEnergy
  split_ifs with h hp
  · exact hD
  · exact le_trans (hk_guard_floor_le_knee _ _ hp (le_of_not_ge h))
      (hk_guard_delta_bounds E0 X h0 hx).2.2
  · exact hx

theorem hk_guard_polynomial_derivative (t : ℝ) :
    HasDerivAt hkGuardPolynomial (4+20*t) t := by
  convert ((hasDerivAt_id t).const_mul 4).const_add 1 |>.add
    (((hasDerivAt_id t).pow 2).const_mul 10) using 1
  · rfl
  · simp; ring

theorem hk_guard_root_rpow (t : ℝ) :
    hkGuardRoot t = (hkGuardPolynomial t)^((1/4 : ℝ)) := by
  unfold hkGuardRoot
  rw [Real.sqrt_eq_rpow, Real.sqrt_eq_rpow, ← Real.rpow_mul (le_of_lt (hk_guard_polynomial_positive t))]
  norm_num

def hkGuardNormalizedFloor (t : ℝ) : ℝ := (hkGuardPolynomial t)^((-1/4 : ℝ))
def hkGuardNormalizedSlope (t : ℝ) : ℝ :=
  (-1/4 : ℝ)*(hkGuardPolynomial t)^((-5/4 : ℝ))*(4+20*t)

theorem hk_guard_normalized_floor_eq (t : ℝ) :
    hkGuardNormalizedFloor t = 1/hkGuardRoot t := by
  rw [hk_guard_root_rpow]
  unfold hkGuardNormalizedFloor
  rw [show (-1/4 : ℝ) = -(1/4 : ℝ) by norm_num, Real.rpow_neg (le_of_lt (hk_guard_polynomial_positive t))]
  simp

theorem hk_guard_normalized_derivative (t : ℝ) :
    HasDerivAt hkGuardNormalizedFloor (hkGuardNormalizedSlope t) t := by
  have h := (hk_guard_polynomial_derivative t).rpow_const
    (Or.inl (ne_of_gt (hk_guard_polynomial_positive t))) (p := (-1/4 : ℝ))
  convert h using 1
  · rfl
  · norm_num [hkGuardNormalizedSlope]
    ring

theorem hk_guard_normalized_second_derivative (t : ℝ) :
    HasDerivAt hkGuardNormalizedSlope
      ((5/16 : ℝ)*(hkGuardPolynomial t)^((-9/4 : ℝ))*(4+20*t)^2-
        5*(hkGuardPolynomial t)^((-5/4 : ℝ))) t := by
  have h := (((hk_guard_polynomial_derivative t).rpow_const
    (Or.inl (ne_of_gt (hk_guard_polynomial_positive t))) (p := (-5/4 : ℝ))).const_mul (-1/4 : ℝ)).mul
    (((hasDerivAt_id t).const_mul 20).const_add 4)
  convert h using 1
  · rfl
  · norm_num
    ring

theorem hk_guard_normalized_knee_jets :
    hkGuardNormalizedFloor 0 = 1 ∧ deriv hkGuardNormalizedFloor 0 = -1 ∧
      deriv (deriv hkGuardNormalizedFloor) 0 = 0 := by
  have hd : deriv hkGuardNormalizedFloor = hkGuardNormalizedSlope :=
    funext fun t => (hk_guard_normalized_derivative t).deriv
  rw [hd, (hk_guard_normalized_second_derivative 0).deriv]
  norm_num [hkGuardNormalizedFloor, hkGuardNormalizedSlope, hkGuardPolynomial]

theorem hk_guard_normalized_knee_c2 :
    ContDiff ℝ 2 (joined 0 (fun t => 1-t) hkGuardNormalizedFloor) := by
  have hf : ContDiff ℝ 2 hkGuardNormalizedFloor := by
    unfold hkGuardNormalizedFloor
    apply ContDiff.rpow_const_of_ne
    · unfold hkGuardPolynomial
      fun_prop
    · intro t
      exact ne_of_gt (hk_guard_polynomial_positive t)
  apply joined_c2 0 _ _ (by fun_prop) hf
  · norm_num [hkGuardNormalizedFloor, hkGuardPolynomial]
  · have h := hk_guard_normalized_knee_jets.2.1
    simpa using h.symm
  · have h := hk_guard_normalized_knee_jets.2.2
    simpa using h.symm

theorem hk_guard_energy_c2 (δ : ℝ) (hd : 0 < δ) :
    ContDiff ℝ 2 (hkGuardEnergy δ) := by
  have he : hkGuardEnergy δ = fun D =>
      δ*joined 0 (fun t => 1-t) hkGuardNormalizedFloor ((δ-D)/δ) := by
    funext D
    by_cases h : δ ≤ D
    · have ht : (δ-D)/δ ≤ 0 := div_nonpos_of_nonpos_of_nonneg (by linarith) (le_of_lt hd)
      simp only [hkGuardEnergy, h, ite_true, joined, ht]
      field_simp
      ring
    · have ht : ¬(δ-D)/δ ≤ 0 := not_le_of_gt (div_pos (by linarith) hd)
      simp only [hkGuardEnergy, h, ite_false, hd, ite_true, joined, ht, hk_guard_normalized_floor_eq, hkGuardFloor]
      ring
  rw [he]
  exact contDiff_const.mul (hk_guard_normalized_knee_c2.comp (by fun_prop))

theorem hk_guard_root_monotone : MonotoneOn hkGuardRoot (Ici 0) := by
  intro x hx y hy hxy
  apply Real.sqrt_le_sqrt
  apply Real.sqrt_le_sqrt
  unfold hkGuardPolynomial
  have hx0 : 0 ≤ x := hx
  have hy0 : 0 ≤ y := hy
  nlinarith

def hkGuardReverseNormalized (t : ℝ) : ℝ := hkGuardRoot t*(1-t)

theorem hk_guard_reverse_normalized_derivative (t : ℝ) :
    HasDerivAt hkGuardReverseNormalized
      (-15*t^2*(hkGuardPolynomial t)^((-3/4 : ℝ))) t := by
  have hp := hk_guard_polynomial_positive t
  have hf : hkGuardReverseNormalized = fun y =>
      (hkGuardPolynomial y)^((1/4 : ℝ))*(1-y) := by
    funext y
    simp [hkGuardReverseNormalized, hk_guard_root_rpow]
  have he : (hkGuardPolynomial t)^((1/4 : ℝ)) =
      (hkGuardPolynomial t)^((-3/4 : ℝ))*hkGuardPolynomial t := by
    have h := Real.rpow_add hp (-3/4 : ℝ) 1
    convert h using 1 <;> norm_num
  rw [hf]
  have h := ((hk_guard_polynomial_derivative t).rpow_const (Or.inl (ne_of_gt hp)) (p := (1/4 : ℝ))).mul
    ((hasDerivAt_id t).const_sub 1)
  convert h using 1
  · rfl
  · norm_num at he ⊢
    rw [he]
    unfold hkGuardPolynomial
    ring

theorem hk_guard_reverse_normalized_antitone : Antitone hkGuardReverseNormalized := by
  apply antitone_of_deriv_nonpos
  · exact fun t => (hk_guard_reverse_normalized_derivative t).differentiableAt
  · intro t
    rw [(hk_guard_reverse_normalized_derivative t).deriv]
    have hp : 0 < (hkGuardPolynomial t)^((-3/4 : ℝ)) :=
      Real.rpow_pos_of_pos (hk_guard_polynomial_positive t) _
    nlinarith [mul_nonneg (sq_nonneg t) (le_of_lt hp)]

theorem hk_guard_allocation_nonnegative (L Z : ℝ) (hl : 0 ≤ L) (hz : 0 ≤ Z) :
    0 ≤ hkGuardAllocation L Z := by unfold hkGuardAllocation; positivity

theorem hk_guard_allocation_bounds (L Z : ℝ) (hl : 0 ≤ L) (hz : 0 ≤ Z) :
    hkGuardAllocation L Z ≤ L ∧ hkGuardAllocation L Z ≤ Z/2 := by
  by_cases h : 4*L^2+Z^2 = 0
  · simp only [hkGuardAllocation, h, Real.sqrt_zero, div_zero]
    exact ⟨hl, by positivity⟩
  · have hd : 0 < Real.sqrt (4*L^2+Z^2) := Real.sqrt_pos.2 (lt_of_le_of_ne (by positivity) (Ne.symm h))
    have hs := Real.sq_sqrt (by positivity : 0 ≤ 4*L^2+Z^2)
    have hn := Real.sqrt_nonneg (4*L^2+Z^2)
    have hL : 2*L ≤ Real.sqrt (4*L^2+Z^2) := by nlinarith [sq_nonneg Z]
    have hZ : Z ≤ Real.sqrt (4*L^2+Z^2) := by nlinarith [sq_nonneg L]
    unfold hkGuardAllocation
    constructor
    · exact (div_le_iff₀ hd).2 (mul_le_mul_of_nonneg_left hZ hl)
    · apply (div_le_iff₀ hd).2
      nlinarith [mul_le_mul_of_nonneg_left hL hz]

theorem hk_guard_allocation_monotone (L M Z V : ℝ)
    (hl : 0 < L) (hz : 0 ≤ Z) (hlm : L ≤ M) (hzv : Z ≤ V) :
    hkGuardAllocation L Z ≤ hkGuardAllocation M V := by
  have hm : 0 < M := lt_of_lt_of_le hl hlm
  have hv : 0 ≤ V := le_trans hz hzv
  have hdl : 0 < Real.sqrt (4*L^2+Z^2) := Real.sqrt_pos.2 (by positivity)
  have hdm : 0 < Real.sqrt (4*M^2+V^2) := Real.sqrt_pos.2 (by positivity)
  have hsl := Real.sq_sqrt (by positivity : 0 ≤ 4*L^2+Z^2)
  have hsm := Real.sq_sqrt (by positivity : 0 ≤ 4*M^2+V^2)
  have h1 : 0 ≤ 4*L^2*M^2*(V^2-Z^2) := by
    have h : 0 ≤ V^2-Z^2 := by nlinarith
    positivity
  have h2 : 0 ≤ Z^2*V^2*(M^2-L^2) := by
    have h : 0 ≤ M^2-L^2 := by nlinarith
    positivity
  have hs : (L*Z*Real.sqrt (4*M^2+V^2))^2 ≤
      (M*V*Real.sqrt (4*L^2+Z^2))^2 := by
    simp only [mul_pow, hsl, hsm]
    nlinarith only [h1, h2]
  unfold hkGuardAllocation
  apply (div_le_div_iff₀ hdl hdm).2
  have hn : 0 ≤ M*V*Real.sqrt (4*L^2+Z^2) := by positivity
  nlinarith only [hs, hn]

def hkGuardInverseT (δ E : ℝ) : ℝ := (Real.sqrt (10*(δ/E)^4-6)-2)/10
def hkGuardInverseD (δ E : ℝ) : ℝ := δ*(1-hkGuardInverseT δ E)
def hkGuardInverseResidual (E0 E X : ℝ) : ℝ :=
  X+hkGuardAllocation ((11/25 : ℝ)*X) (E-hkGuardInverseD (hkGuardDelta E0 X) E)

theorem hk_guard_inverse_parameter (δ E : ℝ) (he : 0 < E) (hd : E ≤ δ) :
    0 ≤ hkGuardInverseT δ E ∧ hkGuardRoot (hkGuardInverseT δ E) = δ/E := by
  have hr : 1 ≤ δ/E := (le_div_iff₀ he).2 (by simpa using hd)
  have hr2 : 1 ≤ (δ/E)^2 := by nlinarith
  have hr4 : 1 ≤ (δ/E)^4 := by nlinarith [sq_nonneg ((δ/E)^2-1)]
  have hs := Real.sq_sqrt (show 0 ≤ 10*(δ/E)^4-6 by linarith)
  have hn := Real.sqrt_nonneg (10*(δ/E)^4-6)
  have ht : 0 ≤ hkGuardInverseT δ E := by unfold hkGuardInverseT; nlinarith
  have hp : hkGuardPolynomial (hkGuardInverseT δ E) = (δ/E)^4 := by
    unfold hkGuardPolynomial hkGuardInverseT
    nlinarith only [hs]
  have hf := hk_guard_root_fourth (hkGuardInverseT δ E)
  have hroot := hk_guard_root_positive (hkGuardInverseT δ E)
  rw [hp] at hf
  have heq : (hkGuardRoot (hkGuardInverseT δ E))^2 = (δ/E)^2 := by
    nlinarith [sq_nonneg (hkGuardRoot (hkGuardInverseT δ E)), sq_nonneg (δ/E)]
  exact ⟨ht, by nlinarith⟩

theorem hk_guard_inverse_t_monotone (E : ℝ) (he : 0 < E) :
    MonotoneOn (fun δ => hkGuardInverseT δ E) (Ici E) := by
  intro x hx y _hy hxy
  have hx0 : 0 ≤ x/E := div_nonneg (le_trans (le_of_lt he) hx) (le_of_lt he)
  have hxy' : x/E ≤ y/E := div_le_div_of_nonneg_right hxy (le_of_lt he)
  have hpow : (x/E)^4 ≤ (y/E)^4 := pow_le_pow_left₀ hx0 hxy' 4
  have hs := Real.sqrt_le_sqrt (show 10*(x/E)^4-6 ≤ 10*(y/E)^4-6 by linarith)
  unfold hkGuardInverseT
  linarith

theorem hk_guard_inverse_d_antitone (E : ℝ) (he : 0 < E) :
    AntitoneOn (fun δ => hkGuardInverseD δ E) (Ici E) := by
  intro x hx y hy hxy
  have ht := hk_guard_inverse_t_monotone E he hx hy hxy
  have hn := hk_guard_reverse_normalized_antitone ht
  have hxroot := (hk_guard_inverse_parameter x E he hx).2
  have hyroot := (hk_guard_inverse_parameter y E he hy).2
  unfold hkGuardReverseNormalized at hn
  rw [hxroot, hyroot] at hn
  have hm := mul_le_mul_of_nonneg_left hn (le_of_lt he)
  unfold hkGuardInverseD
  field_simp at hm
  exact hm

theorem hk_guard_inverse_d_knee (E : ℝ) (he : 0 < E) : hkGuardInverseD E E = E := by
  have hs : Real.sqrt 4 = (2 : ℝ) := (Real.sqrt_eq_iff_eq_sq (by norm_num) (by norm_num)).2 (by norm_num)
  norm_num [hkGuardInverseD, hkGuardInverseT, ne_of_gt he]
  rw [hs]
  norm_num

theorem hk_guard_inverse_deficit_nonnegative (δ E : ℝ) (he : 0 < E) (hd : E ≤ δ) :
    0 ≤ E-hkGuardInverseD δ E := by
  have h := hk_guard_inverse_d_antitone E he (show E ∈ Ici E from le_refl E) hd hd
  dsimp only at h
  change hkGuardInverseD δ E ≤ hkGuardInverseD E E at h
  rw [hk_guard_inverse_d_knee E he] at h
  linarith

theorem hk_guard_inverse_residual_strict_mono (E0 E : ℝ) (h0 : 0 < E0) (he : 0 < E) :
    StrictMonoOn (hkGuardInverseResidual E0 E) {X | 0 < X ∧ E ≤ hkGuardDelta E0 X} := by
  intro x hx y hy hxy
  have hd := (hk_guard_delta_monotone E0 h0).monotoneOn
    (le_of_lt hx.1) (le_of_lt hy.1) (le_of_lt hxy)
  have hD := hk_guard_inverse_d_antitone E he hx.2 hy.2 hd
  have hz := hk_guard_inverse_deficit_nonnegative _ E he hx.2
  have hG := hk_guard_allocation_monotone ((11/25 : ℝ)*x) ((11/25 : ℝ)*y)
    (E-hkGuardInverseD (hkGuardDelta E0 x) E) (E-hkGuardInverseD (hkGuardDelta E0 y) E)
    (by nlinarith [hx.1]) hz (by linarith) (by linarith)
  unfold hkGuardInverseResidual
  linarith

theorem hk_guard_inverse_unique (E0 E U x y : ℝ) (h0 : 0 < E0) (he : 0 < E)
    (hx : 0 < x ∧ E ≤ hkGuardDelta E0 x) (hy : 0 < y ∧ E ≤ hkGuardDelta E0 y)
    (hxu : hkGuardInverseResidual E0 E x = U) (hyu : hkGuardInverseResidual E0 E y = U) :
    x = y := (hk_guard_inverse_residual_strict_mono E0 E h0 he).injOn hx hy (hxu.trans hyu.symm)

theorem hk_guard_inverse_residual_continuous (E0 E X : ℝ) (h0 : 0 < E0) (hx : 0 < X) :
    ContinuousAt (hkGuardInverseResidual E0 E) X := by
  unfold hkGuardInverseResidual hkGuardAllocation hkGuardInverseD hkGuardInverseT hkGuardDelta
  fun_prop (disch := positivity)

/-- Existence and uniqueness are limited to the active positive-energy image.
The black plane and zero-reference cases are deliberately excluded. -/
theorem hk_guard_inverse_exists (E0 E U : ℝ) (h0 : 0 < E0) (he : 0 < E)
    (hu : 0 < U) (ha : E < hkGuardDelta E0 U) :
    ∃! X, (0 < X ∧ E ≤ hkGuardDelta E0 X) ∧ hkGuardInverseResidual E0 E X = U := by
  have he0 : E < E0 := by
    have h := hk_guard_delta_lt_height U E0 (le_of_lt hu) h0
    have hc : hkGuardDelta U E0 = hkGuardDelta E0 U := by unfold hkGuardDelta; ring
    rw [hc] at h
    exact lt_trans ha h
  let a := E*E0/(E0-E)
  have hap : 0 < a := div_pos (mul_pos he h0) (sub_pos.mpr he0)
  have haU : a < U := by
    have h : E*(E0+U) < E0*U := (lt_div_iff₀ (by positivity)).1 ha
    exact (div_lt_iff₀ (sub_pos.mpr he0)).2 (by nlinarith only [h])
  have hda : hkGuardDelta E0 a = E := by
    unfold hkGuardDelta
    have hd : E0+a ≠ 0 := ne_of_gt (by positivity)
    apply (div_eq_iff hd).2
    dsimp [a]
    field_simp [ne_of_gt (sub_pos.mpr he0)]
    ring
  have hfa : hkGuardInverseResidual E0 E a = a := by
    unfold hkGuardInverseResidual
    rw [hda, hk_guard_inverse_d_knee E he]
    simp [hkGuardAllocation]
  have hfU : U ≤ hkGuardInverseResidual E0 E U := by
    have hz := hk_guard_inverse_deficit_nonnegative _ E he (le_of_lt ha)
    have hg := hk_guard_allocation_nonnegative ((11/25 : ℝ)*U)
      (E-hkGuardInverseD (hkGuardDelta E0 U) E) (by positivity) hz
    unfold hkGuardInverseResidual
    linarith
  have hc : ContinuousOn (hkGuardInverseResidual E0 E) (Icc a U) := by
    intro X hX
    exact (hk_guard_inverse_residual_continuous E0 E X h0 (lt_of_lt_of_le hap hX.1)).continuousWithinAt
  obtain ⟨X, hX, hF⟩ := intermediate_value_Icc (le_of_lt haU) hc
    (show U ∈ Icc (hkGuardInverseResidual E0 E a) (hkGuardInverseResidual E0 E U) from
      ⟨by rw [hfa]; exact le_of_lt haU, hfU⟩)
  have hXp : 0 < X := lt_of_lt_of_le hap hX.1
  have hdX : E ≤ hkGuardDelta E0 X := by
    rw [← hda]
    exact (hk_guard_delta_monotone E0 h0).monotoneOn (le_of_lt hap) (le_of_lt hXp) hX.1
  refine ⟨X, ⟨⟨hXp, hdX⟩, hF⟩, ?_⟩
  intro Y hY
  exact hk_guard_inverse_unique E0 E U Y X h0 he hY.1 ⟨hXp, hdX⟩ hY.2 hF

theorem hk_guard_inverse_energy_roundtrip (δ E : ℝ) (he : 0 < E) (hd : E ≤ δ) :
    hkGuardFloor δ (hkGuardInverseD δ E) = E := by
  have hδ : 0 < δ := lt_of_lt_of_le he hd
  have hroot := (hk_guard_inverse_parameter δ E he hd).2
  have ht : (δ-hkGuardInverseD δ E)/δ = hkGuardInverseT δ E := by
    unfold hkGuardInverseD
    field_simp
    ring
  unfold hkGuardFloor
  rw [ht, hroot]
  field_simp

theorem hk_guard_inverse_request_roundtrip (δ D : ℝ) (hd : 0 < δ) (hD : D ≤ δ) :
    hkGuardInverseD δ (hkGuardFloor δ D) = D := by
  let t := (δ-D)/δ
  have ht : 0 ≤ t := div_nonneg (by linarith) (le_of_lt hd)
  have hr := hk_guard_root_positive t
  have hf := hk_guard_root_fourth t
  have hratio : δ/hkGuardFloor δ D = hkGuardRoot t := by
    unfold hkGuardFloor
    dsimp [t]
    field_simp
  have hs : Real.sqrt (10*(hkGuardRoot t)^4-6) = 2+10*t := by
    apply (Real.sqrt_eq_iff_eq_sq (by rw [hf]; unfold hkGuardPolynomial; nlinarith) (by linarith)).2
    rw [hf]
    unfold hkGuardPolynomial
    ring
  unfold hkGuardInverseD hkGuardInverseT
  rw [hratio, hs]
  dsimp [t]
  field_simp
  ring

theorem hk_guard_forward_inverse_residual (E0 X D : ℝ) (h0 : 0 < E0) (hx : 0 < X)
    (hd : D ≤ hkGuardDelta E0 X) :
    hkGuardInverseResidual E0 (hkGuardFloor (hkGuardDelta E0 X) D) X =
      X+hkGuardLift X (hkGuardFloor (hkGuardDelta E0 X) D) D := by
  unfold hkGuardInverseResidual hkGuardLift
  rw [hk_guard_inverse_request_roundtrip _ _ (hk_guard_delta_positive E0 X h0 hx) hd]

theorem hk_guard_inverse_bracket (E0 E U X : ℝ) (h0 : 0 < E0) (he : 0 < E)
    (hx : 0 < X) (hd : E ≤ hkGuardDelta E0 X)
    (hu : hkGuardInverseResidual E0 E X = U) :
    X ∈ Icc (max (U/(36/25 : ℝ)) (E*E0/(E0-E))) U := by
  have hz := hk_guard_inverse_deficit_nonnegative (hkGuardDelta E0 X) E he hd
  have hn := hk_guard_allocation_nonnegative ((11/25 : ℝ)*X)
    (E-hkGuardInverseD (hkGuardDelta E0 X) E) (by positivity) hz
  have hb := (hk_guard_allocation_bounds ((11/25 : ℝ)*X)
    (E-hkGuardInverseD (hkGuardDelta E0 X) E) (by positivity) hz).1
  have he0 : E < E0 := by
    have h := hk_guard_delta_lt_height X E0 (le_of_lt hx) h0
    have hc : hkGuardDelta X E0 = hkGuardDelta E0 X := by unfold hkGuardDelta; ring
    rw [hc] at h
    exact lt_of_le_of_lt hd h
  have hdelta : E*(E0+X) ≤ E0*X := by
    exact (le_div_iff₀ (by positivity)).1 hd
  have hE : E*E0/(E0-E) ≤ X := (div_le_iff₀ (by linarith)).2 (by nlinarith only [hdelta])
  unfold hkGuardInverseResidual at hu
  exact ⟨max_le (by linarith) hE, by linarith⟩

theorem hk_guard_active_branch_separation (E0 E X U : ℝ) (h0 : 0 < E0)
    (hx : 0 < X) (hxU : X ≤ U) (he : E < hkGuardDelta E0 X) :
    E < hkGuardDelta E0 U := by
  have hm := (hk_guard_delta_monotone E0 h0).monotoneOn
    (le_of_lt hx) (le_trans (le_of_lt hx) hxU) hxU
  exact lt_of_lt_of_le he hm

theorem hk_guard_signed_deficit_nonnegative_branch (u b : ℝ) (hu : 0 ≤ u) :
    (u+b)^2-b^2 = u*(|u|+2*b) := by rw [abs_of_nonneg hu]; ring

theorem hk_guard_signed_deficit_negative_branch (u b : ℝ) (hu : u < 0) :
    (u+b)^2-b^2 = u*(|u|+2*b)+2*u^2 := by rw [abs_of_neg hu]; ring

theorem hk_guard_projection_energy (X C E : ℝ) :
    X+hkGuardLift X E (X-66*C)-66*hkGuardChroma X C E = E := by
  unfold hkGuardChroma
  ring

theorem hk_guard_projection_chroma_bounds (X C E : ℝ)
    (hx : 0 ≤ X) (he : E ≤ X) (hr : X-66*C ≤ E) :
    0 ≤ hkGuardChroma X C E ∧ hkGuardChroma X C E ≤ C := by
  have hz : 0 ≤ E-(X-66*C) := by linarith
  have h0 := hk_guard_allocation_nonnegative ((11/25 : ℝ)*X) (E-(X-66*C)) (by positivity) hz
  have h1 := (hk_guard_allocation_bounds ((11/25 : ℝ)*X) (E-(X-66*C)) (by positivity) hz).2
  unfold hkGuardChroma hkGuardLift
  constructor <;> linarith

theorem hk_guard_projection_lightness_bounds (H E D : ℝ) (hh : 0 ≤ H) (hr : D ≤ E) :
    H ≤ Real.sqrt (H^2+hkGuardLift (H^2) E D) ∧
      Real.sqrt (H^2+hkGuardLift (H^2) E D) ≤ (6/5 : ℝ)*H := by
  have h0 := hk_guard_allocation_nonnegative ((11/25 : ℝ)*H^2) (E-D) (by positivity) (by linarith)
  have h1 := (hk_guard_allocation_bounds ((11/25 : ℝ)*H^2) (E-D) (by positivity) (by linarith)).1
  have hs := Real.sq_sqrt (show 0 ≤ H^2+hkGuardLift (H^2) E D by unfold hkGuardLift; positivity)
  have hn := Real.sqrt_nonneg (H^2+hkGuardLift (H^2) E D)
  unfold hkGuardLift at *
  constructor <;> nlinarith

theorem hk_guard_hue_preserved (a b C Cg : ℝ) (hc : 0 < C) (hg : 0 < Cg) :
    (Cg/C*a)/Cg = a/C ∧ (Cg/C*b)/Cg = b/C := by
  constructor <;> field_simp

theorem hk_guard_reset_energy (E0 X : ℝ) (he : 0 ≤ E0) (hx : 0 ≤ X) :
    hkGuardEnergy (hkGuardDelta E0 X) E0 = E0 :=
  hk_guard_energy_identity _ _ (hk_guard_delta_bounds E0 X he hx).2.1

theorem hk_guard_neutral_energy (E0 X : ℝ) (he : 0 ≤ E0) (hx : 0 ≤ X) :
    hkGuardEnergy (hkGuardDelta E0 X) X = X :=
  hk_guard_energy_identity _ _ (hk_guard_delta_bounds E0 X he hx).2.2

end
end PerceptualGrade
