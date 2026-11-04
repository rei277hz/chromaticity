import PerceptualGrade.PoleSpindleInverse
import PerceptualGrade.PiecewiseSpindle
import Mathlib.Analysis.SpecialFunctions.Pow.Real
import Mathlib.Analysis.Calculus.InverseFunctionTheorem.Deriv

namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped Topology ContDiff

/-- Signed real cube root; both signs are represented by explicit real powers. -/
def piecewiseCbrt (x : ℝ) : ℝ :=
  if 0 ≤ x then x ^ ((3:ℝ)⁻¹) else -((-x) ^ ((3:ℝ)⁻¹))

theorem piecewise_cbrt_cube (x : ℝ) : (piecewiseCbrt x)^3=x := by
  unfold piecewiseCbrt
  split_ifs with hx
  · exact Real.rpow_inv_natCast_pow hx (by norm_num : (3:ℕ) ≠ 0)
  · have he := Real.rpow_inv_natCast_pow (show 0 ≤ -x by linarith)
      (by norm_num : (3:ℕ) ≠ 0)
    change ((-x) ^ ((3:ℝ)⁻¹)) ^ 3 = -x at he
    calc
      (-(-x) ^ ((3:ℝ)⁻¹))^3 = -((-x) ^ ((3:ℝ)⁻¹))^3 := by ring
      _ = x := by nlinarith [he]

/-- Choose the larger-magnitude Cardano radical to avoid cancellation. -/
def piecewiseCardanoRadical (p q : ℝ) : ℝ :=
  if 0 ≤ q then q+Real.sqrt (q^2+p^3/27)
  else q-Real.sqrt (q^2+p^3/27)

def piecewiseCardano (p q : ℝ) : ℝ :=
  let u := piecewiseCbrt (piecewiseCardanoRadical p q)
  u-p/(3*u)

theorem piecewise_cardano_radical_nonzero (p q : ℝ) (hd : 0 < q^2+p^3/27) :
    piecewiseCardanoRadical p q ≠ 0 := by
  have hs := Real.sqrt_pos.2 hd
  unfold piecewiseCardanoRadical
  split_ifs with hq <;> linarith

theorem piecewise_cardano_radical_equation (p q : ℝ) (hd : 0 ≤ q^2+p^3/27) :
    (piecewiseCardanoRadical p q)^2-2*q*piecewiseCardanoRadical p q = p^3/27 := by
  have hs := Real.sq_sqrt hd
  unfold piecewiseCardanoRadical
  split_ifs <;> nlinarith [hs]

/-- Cardano gives an exact root even when the depressed coefficient is negative. -/
theorem piecewise_cardano_root (p q : ℝ) (hd : 0 < q^2+p^3/27) :
    (piecewiseCardano p q)^3+p*piecewiseCardano p q=2*q := by
  let u := piecewiseCbrt (piecewiseCardanoRadical p q)
  have hu : u^3=piecewiseCardanoRadical p q := piecewise_cbrt_cube _
  have hu0 : u ≠ 0 := by
    intro hz
    have he := piecewise_cardano_radical_nonzero p q hd
    apply he
    rw [←hu,hz]
    norm_num
  have he := piecewise_cardano_radical_equation p q hd.le
  change (u-p/(3*u))^3+p*(u-p/(3*u))=2*q
  field_simp
  rw [←hu] at he
  nlinarith [he]

/-- Clearing the shoulder denominator gives exactly its inverse cubic. -/
theorem piecewise_shoulder_inverse_polynomial (rs m Q H a v t : ℝ)
    (hden : 1+a*t+a^2*t^2 ≠ 0) :
    rs+m*t+(Q*t^2+H*t^3)/(1+a*t+a^2*t^2)=rs+v ↔
      (m*a^2+H)*t^3+(m*a+Q-v*a^2)*t^2+(m-v*a)*t-v=0 := by
  constructor <;> intro he
  · have hc := (div_eq_iff hden).mp
      (show (Q*t^2+H*t^3)/(1+a*t+a^2*t^2)=v-m*t by linarith)
    nlinarith [hc]
  · have hc : (Q*t^2+H*t^3)/(1+a*t+a^2*t^2)=v-m*t := by
      apply (div_eq_iff hden).2
      nlinarith [he]
    linarith

/-- The stable rational reconstruction equals the shifted Cardano root. -/
theorem piecewise_cardano_factored_reconstruction (c3 h p v z : ℝ)
    (hc3 : c3 ≠ 0) (hden : z^2+z*h+h^2+p ≠ 0)
    (hz : z^3+p*z=v/c3+h^3+p*h) :
    v/(c3*(z^2+z*h+h^2+p))=z-h := by
  apply (div_eq_iff (mul_ne_zero hc3 hden)).2
  have he := (eq_div_iff hc3).1
    (show z^3+p*z-h^3-p*h=v/c3 by linarith)
  nlinarith [he]

def piecewiseCubicInverse (c3 c2 c1 v : ℝ) : ℝ :=
  let h := c2/(3*c3)
  let p := c1/c3-3*h^2
  let q := (v/c3+h^3+p*h)/2
  let z := piecewiseCardano p q
  v/(c3*(z^2+z*h+h^2+p))

/-- The explicit Cardano root solves the original shifted cubic. -/
theorem piecewise_cardano_shift_root (c3 c2 c1 v : ℝ) (hc3 : c3 ≠ 0)
    (hd : 0 < ((v/c3+(c2/(3*c3))^3+
      (c1/c3-3*(c2/(3*c3))^2)*(c2/(3*c3)))/2)^2+
      (c1/c3-3*(c2/(3*c3))^2)^3/27) :
    let h := c2/(3*c3)
    let p := c1/c3-3*h^2
    let q := (v/c3+h^3+p*h)/2
    let z := piecewiseCardano p q
    c3*(z-h)^3+c2*(z-h)^2+c1*(z-h)-v=0 := by
  dsimp only
  have hr := piecewise_cardano_root (c1/c3-3*(c2/(3*c3))^2)
    ((v/c3+(c2/(3*c3))^3+(c1/c3-3*(c2/(3*c3))^2)*(c2/(3*c3)))/2) hd
  field_simp at hr ⊢
  nlinarith [hr]

/-- The stable factor cannot vanish for a nonzero target cubic ordinate. -/
theorem piecewise_cardano_factor_nonzero (c3 h p v z : ℝ)
    (hc3 : c3 ≠ 0) (hv : v ≠ 0)
    (hz : z^3+p*z=v/c3+h^3+p*h) :
    z^2+z*h+h^2+p ≠ 0 := by
  intro he
  have heq : (z-h)*(z^2+z*h+h^2+p)=v/c3 := by nlinarith [hz]
  rw [he,mul_zero] at heq
  exact hv ((div_eq_zero_iff).1 heq.symm |>.resolve_right hc3)

/-- The implemented factored expression solves the cubic, without assuming a
positive depressed coefficient or making an iterative root selection. -/
theorem piecewise_cubic_inverse_root (c3 c2 c1 v : ℝ) (hc3 : c3 ≠ 0) (hv : v ≠ 0)
    (hd : 0 < ((v/c3+(c2/(3*c3))^3+
      (c1/c3-3*(c2/(3*c3))^2)*(c2/(3*c3)))/2)^2+
      (c1/c3-3*(c2/(3*c3))^2)^3/27) :
    c3*(piecewiseCubicInverse c3 c2 c1 v)^3+
      c2*(piecewiseCubicInverse c3 c2 c1 v)^2+
      c1*piecewiseCubicInverse c3 c2 c1 v-v=0 := by
  let h := c2/(3*c3)
  let p := c1/c3-3*h^2
  let q := (v/c3+h^3+p*h)/2
  let z := piecewiseCardano p q
  have hr : z^3+p*z=v/c3+h^3+p*h := by
    have he := piecewise_cardano_root p q hd
    dsimp [q] at he
    linarith
  have hn := piecewise_cardano_factor_nonzero c3 h p v z hc3 hv hr
  have he := piecewise_cardano_factored_reconstruction c3 h p v z hc3 hn hr
  change c3*(v/(c3*(z^2+z*h+h^2+p)))^3+
    c2*(v/(c3*(z^2+z*h+h^2+p)))^2+c1*(v/(c3*(z^2+z*h+h^2+p)))-v=0
  rw [he]
  exact piecewise_cardano_shift_root c3 c2 c1 v hc3 hd

def piecewiseExteriorInverse (M E d Delta : ℝ) : ℝ :=
  2*d*Delta/(M*d+Delta+Real.sqrt ((Delta-M*d)^2+4*E*d^2*Delta))

/-- The exterior inverse is below the pole for every finite nonnegative input. -/
theorem piecewise_exterior_inverse_bounds (M E d Delta : ℝ)
    (hM : 0 < M) (hE : 0 < E) (hd : 0 < d) (hD : 0 ≤ Delta) :
    0 ≤ piecewiseExteriorInverse M E d Delta ∧ piecewiseExteriorInverse M E d Delta < d := by
  have hmd : 0 < M*d := mul_pos hM hd
  have hrad : 0 ≤ (Delta-M*d)^2+4*E*d^2*Delta := by positivity
  have hs : (Real.sqrt ((Delta-M*d)^2+4*E*d^2*Delta))^2 =
    (Delta-M*d)^2+4*E*d^2*Delta := Real.sq_sqrt hrad
  have hsn := Real.sqrt_nonneg ((Delta-M*d)^2+4*E*d^2*Delta)
  have hden : 0 < M*d+Delta+Real.sqrt ((Delta-M*d)^2+4*E*d^2*Delta) := by linarith
  have hgap : Delta-M*d < Real.sqrt ((Delta-M*d)^2+4*E*d^2*Delta) := by
    by_cases hz : Delta=0
    · subst Delta
      nlinarith
    · have hp : 0 < 4*E*d^2*Delta := by positivity
      nlinarith [hs]
  unfold piecewiseExteriorInverse
  constructor
  · positivity
  · apply (div_lt_iff₀ hden).2
    have hm := mul_pos hd (sub_pos.mpr hgap)
    nlinarith

/-- Rationalized square-root recovery satisfies the exterior quadratic. -/
theorem piecewise_exterior_inverse_polynomial (M E d Delta : ℝ)
    (hM : 0 < M) (hE : 0 < E) (hd : 0 < d) (hD : 0 ≤ Delta) :
    (E*d-M)*(piecewiseExteriorInverse M E d Delta)^2+
      (M*d+Delta)*piecewiseExteriorInverse M E d Delta-d*Delta=0 := by
  let S := Real.sqrt ((Delta-M*d)^2+4*E*d^2*Delta)
  have hs : S^2=(Delta-M*d)^2+4*E*d^2*Delta :=
    Real.sq_sqrt (by positivity)
  have hS : 0 ≤ S := Real.sqrt_nonneg _
  have hden : M*d+Delta+S ≠ 0 := by have := mul_pos hM hd; linarith
  unfold piecewiseExteriorInverse
  change (E*d-M)*(2*d*Delta/(M*d+Delta+S))^2+
    (M*d+Delta)*(2*d*Delta/(M*d+Delta+S))-d*Delta=0
  field_simp
  linear_combination -d*Delta*hs

/-- Releasing the explicit exterior inverse recovers the requested ordinate. -/
theorem piecewise_exterior_release_inverse (M E d Delta : ℝ)
    (hM : 0 < M) (hE : 0 < E) (hd : 0 < d) (hD : 0 ≤ Delta) :
    M*piecewiseExteriorInverse M E d Delta+
      E*(piecewiseExteriorInverse M E d Delta)^2/(1-piecewiseExteriorInverse M E d Delta/d)=Delta := by
  have hb := piecewise_exterior_inverse_bounds M E d Delta hM hE hd hD
  have hp := piecewise_exterior_inverse_polynomial M E d Delta hM hE hd hD
  have hd0 : d ≠ 0 := ne_of_gt hd
  have hden : 1-piecewiseExteriorInverse M E d Delta/d ≠ 0 := by
    have he := (div_lt_one hd).2 hb.2
    linarith
  have heq : E*(piecewiseExteriorInverse M E d Delta)^2/
    (1-piecewiseExteriorInverse M E d Delta/d)=Delta-M*piecewiseExteriorInverse M E d Delta := by
    apply (div_eq_iff hden).2
    field_simp
    nlinarith [hp]
  linarith

/-- The implemented rationalized core inverse uses one positive real cube root. -/
def piecewiseCoreInverse (A y : ℝ) : ℝ :=
  let b := (3/2)*y*Real.sqrt (3*A)
  let u := piecewiseCbrt (b+Real.sqrt (b^2+1))
  3*y/(u^2+1+1/u^2)

/-- The implementation's rationalized core formula satisfies its cubic exactly. -/
theorem piecewise_core_inverse_root (A y : ℝ) (hA : 0 ≤ A) :
    piecewiseCoreInverse A y+A*(piecewiseCoreInverse A y)^3=y := by
  by_cases ha : A=0
  · subst A
    norm_num [piecewiseCoreInverse,piecewiseCbrt]
  have haP : 0 < A := lt_of_le_of_ne hA (Ne.symm ha)
  let b := (3/2)*y*Real.sqrt (3*A)
  let u := piecewiseCbrt (b+Real.sqrt (b^2+1))
  have hs3 : (Real.sqrt (3*A))^2=3*A := Real.sq_sqrt (by positivity)
  have hR : (Real.sqrt (b^2+1))^2=b^2+1 := Real.sq_sqrt (by positivity)
  have hRp := Real.sqrt_pos.2 (show 0 < b^2+1 by positivity)
  have hinside : 0 < b+Real.sqrt (b^2+1) := by nlinarith
  have hu : 0 < u := by
    dsimp [u,piecewiseCbrt]
    simp only [hinside.le,ite_true]
    exact Real.rpow_pos_of_pos hinside _
  have hu0 : u ≠ 0 := ne_of_gt hu
  have hu3 : u^3=b+Real.sqrt (b^2+1) := piecewise_cbrt_cube _
  have he : u^6-2*b*u^3=1 := by nlinarith [hu3,hR]
  let z := u-1/u
  have hz : z^3+3*z=2*b := by
    dsimp [z]
    field_simp
    nlinarith [he]
  have hfactor : u^2+1+1/u^2=z^2+3 := by dsimp [z]; field_simp; ring
  have hden : z^2+3 ≠ 0 := by positivity
  have hsA : Real.sqrt (3*A) ≠ 0 := ne_of_gt (Real.sqrt_pos.2 (by positivity))
  have hinv : 3*y/(z^2+3)=z/Real.sqrt (3*A) := by
    field_simp
    dsimp [b] at hz
    nlinarith [hz]
  change 3*y/(u^2+1+1/u^2)+A*(3*y/(u^2+1+1/u^2))^3=y
  rw [hfactor,hinv]
  field_simp
  dsimp [b] at hz
  linear_combination A*hz + (z-Real.sqrt (3*A)*y)*hs3

/-- The core polynomial is injective for its permitted nonnegative coefficient. -/
theorem piecewise_core_polynomial_injective (A : ℝ) (hA : 0 ≤ A) :
    Function.Injective (fun x : ℝ => x+A*x^3) := by
  intro x y hxy
  have hq : 0 ≤ x^2+x*y+y^2 := by nlinarith [sq_nonneg (x+y),sq_nonneg x,sq_nonneg y]
  have hf : 0 < 1+A*(x^2+x*y+y^2) := by positivity
  have he : (x-y)*(1+A*(x^2+x*y+y^2))=0 := by nlinarith [hxy]
  exact sub_eq_zero.mp ((mul_eq_zero.mp he).resolve_right (ne_of_gt hf))

theorem piecewise_core_inverse_roundtrip (A x : ℝ) (hA : 0 ≤ A) :
    piecewiseCoreInverse A (x+A*x^3)=x := by
  apply piecewise_core_polynomial_injective A hA
  exact piecewise_core_inverse_root A (x+A*x^3) hA

/-- The full shoulder denominator is positive, so the inverse cubic is exactly
 equivalent to the rational tail equation. -/
theorem piecewise_tail_inverse_polynomial (rs m Q H v t : ℝ) :
    piecewiseSpindleTail rs m Q H t=rs+v ↔
      (196*m+H)*t^3+(14*m+Q-196*v)*t^2+(m-14*v)*t-v=0 := by
  have he := piecewise_shoulder_inverse_polynomial rs m Q H 14 v t
    (show 1+14*t+14^2*t^2 ≠ 0 by
      norm_num
      exact (piecewise_spindle_denominator_pos t).ne')
  norm_num at he
  simpa only [piecewiseSpindleTail,piecewiseSpindleDenom,mul_comm m 196,mul_comm m 14,
    mul_comm v 196,mul_comm v 14] using he

/-- Global strict monotonicity makes the shoulder cubic's real root unique. -/
theorem piecewise_tail_cubic_unique (rs m Q H v t u : ℝ)
    (hQ : 0 ≤ Q) (hH : 0 ≤ H) (hm : 16*Q/126<m)
    (ht : (196*m+H)*t^3+(14*m+Q-196*v)*t^2+(m-14*v)*t-v=0)
    (hu : (196*m+H)*u^3+(14*m+Q-196*v)*u^2+(m-14*v)*u-v=0) : t=u := by
  apply (piecewise_spindle_tail_strict_mono rs m Q H hQ hH hm).injective
  exact ((piecewise_tail_inverse_polynomial rs m Q H v t).2 ht).trans
    ((piecewise_tail_inverse_polynomial rs m Q H v u).2 hu).symm

/-- The actual factored Cardano inverse roundtrips every shoulder point whose
nonzero ordinate and discriminant satisfy the evaluation branch's domain. -/
theorem piecewise_tail_inverse_roundtrip (rs m Q H v t : ℝ)
    (hQ : 0 ≤ Q) (hH : 0 ≤ H) (hm : 16*Q/126<m)
    (hv : v ≠ 0) (ht : piecewiseSpindleTail rs m Q H t=rs+v)
    (hd : 0 < ((v/(196*m+H)+((14*m+Q-196*v)/(3*(196*m+H)))^3+
      ((m-14*v)/(196*m+H)-3*((14*m+Q-196*v)/(3*(196*m+H)))^2)*
      ((14*m+Q-196*v)/(3*(196*m+H))))/2)^2+
      ((m-14*v)/(196*m+H)-3*((14*m+Q-196*v)/(3*(196*m+H)))^2)^3/27) :
    piecewiseCubicInverse (196*m+H) (14*m+Q-196*v) (m-14*v) v=t := by
  have hmp : 0 < m := by linarith
  have hc3 : 196*m+H ≠ 0 := by positivity
  apply piecewise_tail_cubic_unique rs m Q H v _ t hQ hH hm
  · exact piecewise_cubic_inverse_root _ _ _ v hc3 hv hd
  · exact (piecewise_tail_inverse_polynomial rs m Q H v t).1 ht

/-- A unique simple real root forces a positive Cardano discriminant. -/
theorem piecewise_cardano_discriminant_positive (p q z : ℝ)
    (hz : z^3+p*z=2*q) (hsimple : 3*z^2+p ≠ 0)
    (hunique : ∀ w : ℝ, w^3+p*w=2*q → w=z) : 0 < q^2+p^3/27 := by
  have hquad : 0 < 3*z^2+4*p := by
    by_contra hn
    have hrad : 0 ≤ -3*z^2-4*p := by linarith
    let S := Real.sqrt (-3*z^2-4*p)
    have hs : S^2= -3*z^2-4*p := Real.sq_sqrt hrad
    let w := (-z+S)/2
    have hw : w^2+z*w+z^2+p=0 := by dsimp [w]; nlinarith [hs]
    have he : w^3+p*w=2*q := by
      have heq : (w-z)*(w^2+z*w+z^2+p)=0 := by rw [hw]; ring
      nlinarith [hz,heq]
    have hzw := hunique w he
    have heq : S=3*z := by dsimp [w] at hzw; linarith
    rw [heq] at hs
    apply hsimple
    nlinarith [hs]
  have hsq : 0 < (3*z^2+p)^2 := sq_pos_of_ne_zero hsimple
  have hid : 108*(q^2+p^3/27)=(3*z^2+4*p)*(3*z^2+p)^2 := by
    have he : 4*q^2=(z^3+p*z)^2 := by rw [hz]; ring
    nlinarith [he]
  have hp := mul_pos hquad hsq
  nlinarith [hid]

/-- The shoulder cubic derivative equals its positive rational derivative times
 the positive denominator at every root. -/
theorem piecewise_tail_cubic_derivative (rs m Q H v t : ℝ)
    (ht : piecewiseSpindleTail rs m Q H t=rs+v) :
    3*(196*m+H)*t^2+2*(14*m+Q-196*v)*t+(m-14*v) =
      piecewiseSpindleTailSlope m Q H t*piecewiseSpindleDenom t := by
  have hden := (piecewise_spindle_denominator_pos t).ne'
  unfold piecewiseSpindleTail at ht
  have he : Q*t^2+H*t^3=(v-m*t)*piecewiseSpindleDenom t :=
    (div_eq_iff hden).1 (by linarith)
  unfold piecewiseSpindleTailSlope
  field_simp
  unfold piecewiseSpindleDenom at *
  linear_combination (14+392*t)*he

/-- Admissible shoulder coefficients imply the positive discriminant required
 by the actual noniterative Cardano branch. -/
theorem piecewise_tail_discriminant_positive (rs m Q H v t : ℝ)
    (hQ : 0 ≤ Q) (hH : 0 ≤ H) (hm : 16*Q/126<m)
    (ht : piecewiseSpindleTail rs m Q H t=rs+v) :
    0 < ((v/(196*m+H)+((14*m+Q-196*v)/(3*(196*m+H)))^3+
      ((m-14*v)/(196*m+H)-3*((14*m+Q-196*v)/(3*(196*m+H)))^2)*
      ((14*m+Q-196*v)/(3*(196*m+H))))/2)^2+
      ((m-14*v)/(196*m+H)-3*((14*m+Q-196*v)/(3*(196*m+H)))^2)^3/27 := by
  let c3 := 196*m+H
  let c2 := 14*m+Q-196*v
  let c1 := m-14*v
  let h := c2/(3*c3)
  let p := c1/c3-3*h^2
  let q := (v/c3+h^3+p*h)/2
  have hmp : 0 < m := by linarith
  have hc3 : 0 < c3 := by dsimp [c3]; positivity
  have hc30 : c3 ≠ 0 := ne_of_gt hc3
  have htpoly : c3*t^3+c2*t^2+c1*t-v=0 :=
    (piecewise_tail_inverse_polynomial rs m Q H v t).1 ht
  have hroot : (t+h)^3+p*(t+h)=2*q := by
    dsimp [q,p,h]
    field_simp
    nlinarith [htpoly]
  have hslope : 0 < piecewiseSpindleTailSlope m Q H t := by
    have hl := piecewise_spindle_tail_slope_lower m Q H t hQ hH
    linarith
  have hderiv : 0 < 3*c3*t^2+2*c2*t+c1 := by
    change 0 < 3*(196*m+H)*t^2+2*(14*m+Q-196*v)*t+(m-14*v)
    rw [piecewise_tail_cubic_derivative rs m Q H v t ht]
    exact mul_pos hslope (piecewise_spindle_denominator_pos t)
  have hsimple : 3*(t+h)^2+p ≠ 0 := by
    have he : c3*(3*(t+h)^2+p)=3*c3*t^2+2*c2*t+c1 := by
      dsimp [p,h]
      field_simp
      ring
    intro hn
    rw [hn,mul_zero] at he
    linarith
  apply piecewise_cardano_discriminant_positive p q (t+h) hroot hsimple
  intro w hw
  have hu : c3*(w-h)^3+c2*(w-h)^2+c1*(w-h)-v=0 := by
    dsimp [q,p,h] at hw ⊢
    field_simp at hw ⊢
    nlinarith [hw]
  have he := piecewise_tail_cubic_unique rs m Q H v (w-h) t hQ hH hm hu htpoly
  linarith

/-- All admissible shoulder points have an exact closed inverse; the zero
ordinate uses the explicit branch and the remaining branch needs no iteration. -/
theorem piecewise_tail_inverse_roundtrip_admissible (rs m Q H v t : ℝ)
    (hQ : 0 ≤ Q) (hH : 0 ≤ H) (hm : 16*Q/126<m)
    (ht : piecewiseSpindleTail rs m Q H t=rs+v) :
    (if v=0 then 0 else piecewiseCubicInverse (196*m+H) (14*m+Q-196*v) (m-14*v) v)=t := by
  split_ifs with hv
  · subst v
    apply (piecewise_spindle_tail_strict_mono rs m Q H hQ hH hm).injective
    simpa [piecewiseSpindleTail] using ht.symm
  · exact piecewise_tail_inverse_roundtrip rs m Q H v t hQ hH hm hv ht
      (piecewise_tail_discriminant_positive rs m Q H v t hQ hH hm ht)

/-- Exterior compression is also a left inverse on the entire pre-pole domain. -/
theorem piecewise_exterior_inverse_release (k M E d u : ℝ)
    (hM : 0 < M) (hE : 0 < E) (hd : 0 < d) (hu : u ∈ Ico 0 d) :
    piecewiseExteriorInverse M E d (piecewiseSpindleExterior k M E d u-k)=u := by
  have hDelta : 0 ≤ piecewiseSpindleExterior k M E d u-k := by
    have hm := (piecewise_spindle_exterior_strict_mono k M E d hM hE.le hd).monotoneOn
      (show (0:ℝ) ∈ Ico 0 d from ⟨le_rfl,hd⟩) hu hu.1
    simpa [piecewiseSpindleExterior] using sub_nonneg.mpr hm
  have hb := piecewise_exterior_inverse_bounds M E d _ hM hE hd hDelta
  apply (piecewise_spindle_exterior_strict_mono k M E d hM hE.le hd).injOn hb hu
  have he := piecewise_exterior_release_inverse M E d _ hM hE hd hDelta
  unfold piecewiseSpindleExterior at *
  linarith

def piecewiseSpindleCompress (eps k y : ℝ) : ℝ :=
  if k=1 then y else
  let A := piecewiseSpindleA eps k
  let rs := piecewiseSpindleRs A
  let m := piecewiseSpindleM A
  let Q := piecewiseSpindleQ A
  let H := piecewiseSpindleH A k
  if y ≤ rs then piecewiseCoreInverse A y else
    let v := y-rs
    3/4+(if v=0 then 0 else piecewiseCubicInverse (196*m+H) (14*m+Q-196*v) (m-14*v) v)

theorem piecewise_core_strict_mono (A : ℝ) (hA : 0 ≤ A) :
    StrictMono (piecewiseSpindleCore A) := by
  apply strictMono_of_deriv_pos
  intro x
  rw [(piecewise_spindle_core_derivative A x).deriv]
  unfold piecewiseSpindleCoreSlope
  positivity

/-- The actual core/shoulder branch selection roundtrips the physical release. -/
theorem piecewise_spindle_compress_release (eps k x : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) :
    piecewiseSpindleCompress eps k (piecewiseSpindleRelease eps k x)=x := by
  by_cases hk1 : k=1
  · subst k
    simp [piecewiseSpindleCompress,piecewise_spindle_identity]
  let A := piecewiseSpindleA eps k
  let rs := piecewiseSpindleRs A
  let m := piecewiseSpindleM A
  let Q := piecewiseSpindleQ A
  let H := piecewiseSpindleH A k
  have hA : 0 ≤ A := (piecewise_spindle_coefficient_bounds eps k he hk).1
  have hsafe := piecewise_spindle_parameters_safe eps k he hk
  have hQ : 0 ≤ Q := hsafe.1
  have hH : 0 ≤ H := by dsimp [H]; nlinarith [hsafe.2.1]
  have hm : 16*Q/126<m := hsafe.2.2
  have hzero : piecewiseSpindleTail rs m Q H 0=rs := by simp [piecewiseSpindleTail]
  by_cases hx : x ≤ 3/4
  · have hrelease : piecewiseSpindleRelease eps k x=piecewiseSpindleCore A x := by
      simp [piecewiseSpindleRelease,joined,hx,A]
    have hbound : piecewiseSpindleCore A x ≤ rs :=
      (piecewise_core_strict_mono A hA).monotone hx
    rw [hrelease]
    change (if k=1 then piecewiseSpindleCore A x else
      if piecewiseSpindleCore A x ≤ rs then piecewiseCoreInverse A (piecewiseSpindleCore A x)
      else _) = x
    simp only [hk1,ite_false,hbound,ite_true]
    exact piecewise_core_inverse_roundtrip A x hA
  · have hxpos : 0 < x-3/4 := by linarith
    have hrelease : piecewiseSpindleRelease eps k x=piecewiseSpindleTail rs m Q H (x-3/4) := by
      simp [piecewiseSpindleRelease,joined,hx,A,rs,m,Q,H]
    have hbound : rs < piecewiseSpindleTail rs m Q H (x-3/4) := by
      simpa only [hzero] using piecewise_spindle_tail_strict_mono rs m Q H hQ hH hm hxpos
    rw [hrelease]
    change (if k=1 then piecewiseSpindleTail rs m Q H (x-3/4) else
      if piecewiseSpindleTail rs m Q H (x-3/4) ≤ rs then _ else _) = x
    simp only [hk1,ite_false,not_le.mpr hbound,ite_false]
    have hrt := piecewise_tail_inverse_roundtrip_admissible rs m Q H
      (piecewiseSpindleTail rs m Q H (x-3/4)-rs) (x-3/4) hQ hH hm (by ring)
    rw [hrt]
    ring

/-- Compression is also a right inverse throughout the physical cube interval. -/
theorem piecewise_spindle_release_compress (eps k y : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) (hy : y ∈ Icc 0 k) :
    piecewiseSpindleCompress eps k y ∈ Icc 0 1 ∧
      piecewiseSpindleRelease eps k (piecewiseSpindleCompress eps k y)=y := by
  have hc : ContinuousOn (piecewiseSpindleRelease eps k) (Icc 0 1) :=
    (piecewise_spindle_c2 eps k).continuous.continuousOn
  have hend := piecewise_spindle_endpoints eps k
  have hi : y ∈ Icc (piecewiseSpindleRelease eps k 0) (piecewiseSpindleRelease eps k 1) := by
    rw [hend.1,hend.2]
    exact hy
  obtain ⟨x,hx,hxy⟩ := intermediate_value_Icc (show (0:ℝ)≤1 by norm_num) hc hi
  rw [←hxy,piecewise_spindle_compress_release eps k x he hk]
  exact ⟨hx,rfl⟩

/-- The existing identity guard resets every physically mapped ungraded color. -/
theorem piecewise_spindle_reset (eps k y : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) (hy : y ∈ Icc 0 k) :
    piecewiseSpindleRelease eps k (hardSpindleRadius 1 (piecewiseSpindleCompress eps k y))=y := by
  have hi := piecewise_spindle_release_compress eps k y he hk hy
  rw [hard_spindle_identity 1 _ hi.1.2]
  exact hi.2

/-- Every derivative of the physical scalar release is strictly positive. -/
theorem piecewise_spindle_slope_positive (eps k x : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) : 0 < piecewiseSpindleSlope eps k x := by
  obtain ⟨hQ,hH,hm⟩ := piecewise_spindle_parameters_safe eps k he hk
  have ha := (piecewise_spindle_coefficient_bounds eps k he hk).1
  unfold piecewiseSpindleSlope joined
  split_ifs
  · unfold piecewiseSpindleCoreSlope
    positivity
  · have hh : 0 ≤ piecewiseSpindleH (piecewiseSpindleA eps k) k := by linarith
    linarith [piecewise_spindle_tail_slope_lower (piecewiseSpindleM (piecewiseSpindleA eps k))
      (piecewiseSpindleQ (piecewiseSpindleA eps k)) (piecewiseSpindleH (piecewiseSpindleA eps k) k)
      (x-3/4) hQ hh]

/-- The actual closed inverse is C2 at each represented radius, including joins. -/
theorem piecewise_spindle_inverse_c2 (eps k x : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) :
    ContDiffAt ℝ 2 (piecewiseSpindleCompress eps k) (piecewiseSpindleRelease eps k x) := by
  have hc := (piecewise_spindle_c2 eps k).contDiffAt (x:=x)
  have hd := piecewise_spindle_derivative eps k x
  have hn := (piecewise_spindle_slope_positive eps k x he hk).ne'
  have hs := hc.hasStrictDerivAt' hd (by norm_num)
  let e := (hs.hasStrictFDerivAt_equiv hn).toOpenPartialHomeomorph (piecewiseSpindleRelease eps k)
  have hx : x ∈ e.source := (hs.hasStrictFDerivAt_equiv hn).mem_toOpenPartialHomeomorph_source
  have hy : piecewiseSpindleRelease eps k x ∈ e.target := e.map_source hx
  have hxy : e.symm (piecewiseSpindleRelease eps k x)=x := e.left_inv hx
  have hcs : ContDiffAt ℝ 2 e.symm (piecewiseSpindleRelease eps k x) := by
    apply e.contDiffAt_symm_deriv hn hy
    · simpa only [hxy] using (show HasDerivAt e (piecewiseSpindleSlope eps k x) x from hd)
    · simpa only [hxy] using (show ContDiffAt ℝ 2 e x from hc)
  have hg : ∀ᶠ z in 𝓝 x, piecewiseSpindleCompress eps k (piecewiseSpindleRelease eps k z)=z :=
    Filter.Eventually.of_forall fun z => piecewise_spindle_compress_release eps k z he hk
  exact hcs.congr_of_eventuallyEq ((hs.hasStrictFDerivAt_equiv hn).localInverse_unique hg)

theorem piecewise_spindle_compress_c2_on (eps k : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) :
    ContDiffOn ℝ 2 (piecewiseSpindleCompress eps k) (Icc 0 k) := by
  intro y hy
  have hi := piecewise_spindle_release_compress eps k y he hk hy
  have hc := piecewise_spindle_inverse_c2 eps k (piecewiseSpindleCompress eps k y) he hk
  rw [hi.2] at hc
  exact hc.contDiffWithinAt

/-- The inverse's derivative is the reciprocal release derivative. -/
theorem piecewise_spindle_inverse_derivative (eps k x : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) :
    HasDerivAt (piecewiseSpindleCompress eps k) (piecewiseSpindleSlope eps k x)⁻¹
      (piecewiseSpindleRelease eps k x) := by
  have hc := (piecewise_spindle_c2 eps k).contDiffAt (x:=x)
  have hd := piecewise_spindle_derivative eps k x
  have hn := (piecewise_spindle_slope_positive eps k x he hk).ne'
  have hs := hc.hasStrictDerivAt' hd (by norm_num)
  apply (hs.to_local_left_inverse hn ?_).hasDerivAt
  exact Filter.Eventually.of_forall fun z => piecewise_spindle_compress_release eps k z he hk

end
end PerceptualGrade
