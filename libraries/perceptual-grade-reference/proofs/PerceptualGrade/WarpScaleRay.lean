import PerceptualGrade.TonalWebAdaptance
import PerceptualGrade.SignedAppearance

/- Diagnostic unrepaired negative signed-energy rays scale as C ↦ kC and
   E ↦ k²E. Here A=66C and q=|E|, so the raw H–K height on that
   Scale ray is 2√(Ak)-√(Ak+qk²). These historical laws explain the
   rejected Scale-before-repair ordering. The corrected Warp repairs first;
   its nonnegative Scale ray is proved in WarpRepairedScale. -/
namespace PerceptualGrade
noncomputable section

def webNegativeScaleHeight (A q k : ℝ) : ℝ :=
  2*Real.sqrt (A*k)-Real.sqrt (A*k+q*k^2)

def webNegativeScaleSlope (A q k : ℝ) : ℝ :=
  (2*Real.sqrt A*Real.sqrt (A+q*k)-(A+2*q*k)) /
    (2*Real.sqrt k*Real.sqrt (A+q*k))

/-- This ray is the signed appearance coordinate after homogeneous Scale of
    an unrepaired negative-energy input. The corrected nonnegative-H repaired
    branch excludes it; negative-H bypass remains outside that guarantee. -/
theorem web_negative_scale_signed_hk (C E k : ℝ)
    (hC : 0 ≤ C) (hE : E < 0) (hk : 0 < k) :
    signedHK (signedRoot (k^2*E)) (Real.sqrt (66*(k*C))) =
      webNegativeScaleHeight (66*C) (-E) k := by
  have hEk : k^2*E < 0 := mul_neg_of_pos_of_neg (sq_pos_of_pos hk) hE
  have hJ : signedRoot (k^2*E) < 0 := signed_root_negative _ hEk
  simp only [signedHK, not_le_of_gt hJ, ite_false, hkMagnitude,
    signed_root_squared, abs_of_neg hEk, abs_of_nonneg (Real.sqrt_nonneg _)]
  rw [Real.sq_sqrt (by positivity : 0 ≤ 66*(k*C))]
  unfold webNegativeScaleHeight
  rw [show 66*(k*C) = 66*C*k by ring,
    show -(k^2*E)+66*C*k = 66*C*k+(-E)*k^2 by ring]

theorem web_negative_scale_height_factor (A q k : ℝ)
    (hA : 0 ≤ A) (hq : 0 ≤ q) (hk : 0 ≤ k) :
    webNegativeScaleHeight A q k =
      Real.sqrt k*(2*Real.sqrt A-Real.sqrt (A+q*k)) := by
  have hbase : 0 ≤ A+q*k := by positivity
  have hfirst : Real.sqrt (A*k) = Real.sqrt k*Real.sqrt A := by
    rw [mul_comm A k, Real.sqrt_mul hk]
  have hsecond : Real.sqrt (A*k+q*k^2) =
      Real.sqrt k*Real.sqrt (A+q*k) := by
    rw [show A*k+q*k^2 = k*(A+q*k) by ring, Real.sqrt_mul hk]
  rw [webNegativeScaleHeight, hfirst, hsecond]
  ring

/-- Raw H–K stays positive precisely before the black threshold. -/
theorem web_negative_scale_height_positive_iff (A q k : ℝ)
    (hA : 0 < A) (hq : 0 ≤ q) (hk : 0 < k) :
    0 < webNegativeScaleHeight A q k ↔ q*k < 3*A := by
  have hf := web_negative_scale_height_factor A q k hA.le hq hk.le
  have hr : 0 < Real.sqrt A := Real.sqrt_pos.2 hA
  have hu : 0 ≤ Real.sqrt (A+q*k) := Real.sqrt_nonneg _
  have husq : (Real.sqrt (A+q*k))^2 = A+q*k :=
    Real.sq_sqrt (by positivity)
  have hrsq : (Real.sqrt A)^2 = A := Real.sq_sqrt hA.le
  rw [hf]
  constructor
  · intro hh
    have hdiff : Real.sqrt (A+q*k) < 2*Real.sqrt A := by
      have hs : 0 < Real.sqrt k := Real.sqrt_pos.2 hk
      nlinarith
    nlinarith [sq_nonneg (Real.sqrt (A+q*k)-2*Real.sqrt A)]
  · intro ht
    have hdiff : Real.sqrt (A+q*k) < 2*Real.sqrt A := by
      nlinarith [sq_nonneg (Real.sqrt (A+q*k)-2*Real.sqrt A)]
    exact mul_pos (Real.sqrt_pos.2 hk) (sub_pos.mpr hdiff)

/-- The derivative is explicit and has a strictly positive denominator. -/
theorem web_negative_scale_height_derivative (A q k : ℝ)
    (hA : 0 < A) (hq : 0 ≤ q) (hk : 0 < k) :
    HasDerivAt (webNegativeScaleHeight A q) (webNegativeScaleSlope A q k) k := by
  have hb : 0 < A+q*k := by positivity
  have hkn : Real.sqrt k ≠ 0 := ne_of_gt (Real.sqrt_pos.2 hk)
  have hbn : Real.sqrt (A+q*k) ≠ 0 := ne_of_gt (Real.sqrt_pos.2 hb)
  have hfirst : Real.sqrt (A*k) = Real.sqrt k*Real.sqrt A := by
    rw [mul_comm A k, Real.sqrt_mul hk.le]
  have hsecond : Real.sqrt (A*k+q*k^2) =
      Real.sqrt k*Real.sqrt (A+q*k) := by
    rw [show A*k+q*k^2 = k*(A+q*k) by ring, Real.sqrt_mul hk.le]
  have hAn : Real.sqrt A ≠ 0 := ne_of_gt (Real.sqrt_pos.2 hA)
  have hAsq := Real.sq_sqrt hA.le
  have hrad : 0 < A*k+q*k^2 := by positivity
  have hdA := (((hasDerivAt_id k).const_mul A).sqrt
    (ne_of_gt (mul_pos hA hk)))
  have hdq := ((((hasDerivAt_id k).const_mul A).add
      (((hasDerivAt_id k).pow 2).const_mul q)).sqrt (ne_of_gt hrad))
  have h := (hdA.const_mul 2).sub hdq
  convert h using 1
  · rfl
  · simp only [id_eq, mul_one, Nat.cast_ofNat]
    unfold webNegativeScaleSlope
    change _ = 2*(A/(2*Real.sqrt (A*k))) -
      (A+q*(2*k^(2-1)))/(2*Real.sqrt (A*k+q*k^2))
    norm_num only [show (2:ℕ)-1 = 1 by decide, pow_one] at *
    rw [hfirst, hsecond]
    field_simp [hkn, hbn, hAn]
    linear_combination 2*Real.sqrt (A+q*k)*hAsq


/-- Scale raises raw H–K exactly up to the negative-energy turning point. -/
theorem web_negative_scale_slope_nonnegative_iff (A q k : ℝ)
    (hA : 0 < A) (hq : 0 ≤ q) (hk : 0 < k) :
    0 ≤ webNegativeScaleSlope A q k ↔ 2*q*k ≤ Real.sqrt 3*A := by
  have hb : 0 < A+q*k := by positivity
  have hden : 0 < 2*Real.sqrt k*Real.sqrt (A+q*k) := by positivity
  have hl : 0 < 2*Real.sqrt A*Real.sqrt (A+q*k) := by positivity
  have hr : 0 < A+2*q*k := by positivity
  have hqa : 0 ≤ 2*q*k := by positivity
  have hthree : 0 < Real.sqrt 3*A := by positivity
  have hleft : (2*Real.sqrt A*Real.sqrt (A+q*k))^2 = 4*A*(A+q*k) := by
    rw [mul_pow, mul_pow, Real.sq_sqrt hA.le, Real.sq_sqrt hb.le]
    ring
  have hright : (Real.sqrt 3*A)^2 = 3*A^2 := by
    rw [mul_pow, Real.sq_sqrt (by norm_num : (0:ℝ) ≤ 3)]
  rw [webNegativeScaleSlope, le_div_iff₀ hden]
  simp only [zero_mul]
  constructor
  · intro h
    by_contra ht
    have hsq : (Real.sqrt 3*A)^2 < (2*q*k)^2 := by
      nlinarith [sq_nonneg (2*q*k-Real.sqrt 3*A)]
    have hsq' : (A+2*q*k)^2 ≤ (2*Real.sqrt A*Real.sqrt (A+q*k))^2 := by
      nlinarith [sq_nonneg (2*Real.sqrt A*Real.sqrt (A+q*k)-(A+2*q*k))]
    nlinarith
  · intro h
    have hsq : (2*q*k)^2 ≤ (Real.sqrt 3*A)^2 := by
      nlinarith [sq_nonneg (Real.sqrt 3*A-2*q*k)]
    nlinarith [sq_nonneg (2*Real.sqrt A*Real.sqrt (A+q*k)-(A+2*q*k))]

/-- The same threshold is the unique zero of the Scale derivative. -/
theorem web_negative_scale_slope_zero_iff (A q k : ℝ)
    (hA : 0 < A) (hq : 0 ≤ q) (hk : 0 < k) :
    webNegativeScaleSlope A q k = 0 ↔ 2*q*k = Real.sqrt 3*A := by
  have hb : 0 < A+q*k := by positivity
  have hden : 0 < 2*Real.sqrt k*Real.sqrt (A+q*k) := by positivity
  have hl : 0 < 2*Real.sqrt A*Real.sqrt (A+q*k) := by positivity
  have hr : 0 < A+2*q*k := by positivity
  have hqa : 0 ≤ 2*q*k := by positivity
  have hthree : 0 < Real.sqrt 3*A := by positivity
  have hleft : (2*Real.sqrt A*Real.sqrt (A+q*k))^2 = 4*A*(A+q*k) := by
    rw [mul_pow, mul_pow, Real.sq_sqrt hA.le, Real.sq_sqrt hb.le]
    ring
  have hright : (Real.sqrt 3*A)^2 = 3*A^2 := by
    rw [mul_pow, Real.sq_sqrt (by norm_num : (0:ℝ) ≤ 3)]
  rw [webNegativeScaleSlope, div_eq_zero_iff]
  constructor
  · intro h
    rcases h with h | h
    · nlinarith [sq_nonneg (2*q*k-Real.sqrt 3*A)]
    · exact (ne_of_gt hden h).elim
  · intro h
    left
    nlinarith [sq_nonneg (2*Real.sqrt A*Real.sqrt (A+q*k)-(A+2*q*k))]

/-- Staying on the increasing branch stays strictly before zero raw H–K. -/
theorem web_negative_scale_increasing_positive (A q k : ℝ)
    (hA : 0 < A) (hq : 0 ≤ q) (hk : 0 < k)
    (hsafe : 2*q*k ≤ Real.sqrt 3*A) :
    0 < webNegativeScaleHeight A q k := by
  apply (web_negative_scale_height_positive_iff A q k hA hq hk).2
  have hsqrt : Real.sqrt 3 < 6 := by
    nlinarith [Real.sq_sqrt (by norm_num : (0:ℝ) ≤ 3), Real.sqrt_nonneg (3:ℝ)]
  nlinarith [mul_pos hA (sub_pos.mpr hsqrt)]

/-- In physical units A=66C, the turning point is kq=33√3 C.
    This diagnoses the historical unrepaired Scale ray; it is not a ceiling
    on the corrected repaired Warp Scale. -/
theorem web_negative_scale_physical_ceiling (C q k : ℝ)
    (hC : 0 < C) (hq : 0 ≤ q) (hk : 0 < k) :
    (0 ≤ webNegativeScaleSlope (66*C) q k ↔
      q*k ≤ 33*Real.sqrt 3*C) ∧
    (q*k ≤ 33*Real.sqrt 3*C →
      0 < webNegativeScaleHeight (66*C) q k) := by
  have hA : 0 < 66*C := by positivity
  have hthreshold : 2*q*k ≤ Real.sqrt 3*(66*C) ↔
      q*k ≤ 33*Real.sqrt 3*C := by
    constructor <;> intro h <;> nlinarith
  constructor
  · rw [web_negative_scale_slope_nonnegative_iff (66*C) q k hA hq hk,
      hthreshold]
  · intro h
    exact web_negative_scale_increasing_positive (66*C) q k hA hq hk
      (hthreshold.2 h)

/-- With genuinely negative initial energy, there is one turning point.
    Above it Scale decreases raw H–K, although C/|J_A| remains invariant. -/
theorem web_negative_scale_turning_point (C q k : ℝ)
    (hC : 0 < C) (hq : 0 < q) (hk : 0 < k) :
    (webNegativeScaleSlope (66*C) q k = 0 ↔
      k = 33*Real.sqrt 3*C/q) ∧
    (webNegativeScaleSlope (66*C) q k < 0 ↔
      33*Real.sqrt 3*C/q < k) := by
  have hA : 0 < 66*C := by positivity
  constructor
  · rw [web_negative_scale_slope_zero_iff (66*C) q k hA hq.le hk,
      eq_div_iff (ne_of_gt hq)]
    constructor <;> intro h <;> nlinarith
  · rw [lt_iff_not_ge, (web_negative_scale_physical_ceiling C q k hC hq.le hk).1,
      not_le, div_lt_iff₀ hq]
    constructor <;> intro h <;> nlinarith

/-- The historical stored-energy/chroma condition is exactly the
    increasing-ray threshold after homogeneous Scale of an unrepaired input. -/
theorem web_negative_scale_final_state_ceiling (C q k : ℝ) (hk : 0 < k) :
    k^2*q ≤ 33*Real.sqrt 3*(k*C) ↔ q*k ≤ 33*Real.sqrt 3*C := by
  rw [show k^2*q = k*(q*k) by ring,
    show 33*Real.sqrt 3*(k*C) = k*(33*Real.sqrt 3*C) by ring]
  exact mul_le_mul_iff_right₀ hk


end
end PerceptualGrade
