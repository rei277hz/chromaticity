import PerceptualGrade.TonalWeb

namespace PerceptualGrade
noncomputable section
open Set

def webMeanSlope (p q : ℝ) : ℝ := ((1/p^4+1/q^4)/2)^((-1/4 : ℝ))

theorem web_mean_slope_positive (p q : ℝ) (hp : 0 < p) (hq : 0 < q) :
    0 < webMeanSlope p q := by
  apply Real.rpow_pos_of_pos
  positivity

theorem web_mean_slope_fourth (p q : ℝ) (hp : 0 < p) (hq : 0 < q) :
    (webMeanSlope p q)^4*((1/p^4+1/q^4)/2) = 1 := by
  have hb : 0 < (1/p^4+1/q^4)/2 := by positivity
  unfold webMeanSlope
  rw [← Real.rpow_natCast, ← Real.rpow_mul hb.le]
  norm_num only [show (-1/4 : ℝ)*4 = -1 by norm_num, Real.rpow_neg_one]
  exact inv_mul_cancel₀ (ne_of_gt hb)

/-- 6/5 is a rational bound above 2^(1/4), sufficient for positive central gaps. -/
theorem web_mean_slope_bound (p q : ℝ) (hp : 0 < p) (hq : 0 < q) :
    webMeanSlope p q < (6/5 : ℝ)*p := by
  have hd := web_mean_slope_positive p q hp hq
  have hf := web_mean_slope_fourth p q hp hq
  have hp0 := ne_of_gt hp
  have hq0 := ne_of_gt hq
  have hprod : (webMeanSlope p q)^4*(q^4+p^4) = 2*p^4*q^4 := by
    field_simp at hf
    nlinarith only [hf]
  have hle : (webMeanSlope p q)^4 ≤ 2*p^4 := by
    have hn : 0 ≤ (webMeanSlope p q)^4*p^4 := by positivity
    have hq4 : 0 < q^4 := by positivity
    apply le_of_not_gt
    intro hbad
    have hmul := mul_pos hq4 (sub_pos.mpr hbad)
    nlinarith only [hprod, hn, hmul]
  by_contra h
  have hge : (6/5 : ℝ)*p ≤ webMeanSlope p q := le_of_not_gt h
  have hpow := pow_le_pow_left₀ (by positivity : 0 ≤ (6/5 : ℝ)*p) hge 4
  have hp4 : 0 < p^4 := by positivity
  norm_num [mul_pow] at hpow
  nlinarith

theorem web_mean_slope_symmetric (p q : ℝ) : webMeanSlope p q = webMeanSlope q p := by
  simp only [webMeanSlope, add_comm]

theorem web_quintic_gap_positive (m p q : ℝ) (hm : 0 < m) (hp : 0 < p) (hq : 0 < q) :
    0 < 5*m-2*(webMeanSlope p m+webMeanSlope m q) := by
  have h1 := web_mean_slope_bound m p hm hp
  have h2 := web_mean_slope_bound m q hm hq
  rw [web_mean_slope_symmetric m p] at h1
  linarith

/-- Degree-five Bézier sector as a polynomial in normalized sector coordinate. -/
def webBezier (p0 p1 p2 p3 p4 p5 t : ℝ) : ℝ :=
  p0*(1-t)^5+5*p1*t*(1-t)^4+10*p2*t^2*(1-t)^3+
    10*p3*t^3*(1-t)^2+5*p4*t^4*(1-t)+p5*t^5

def webBezierSlope (p0 p1 p2 p3 p4 p5 t : ℝ) : ℝ :=
  5*((p1-p0)*(1-t)^4+4*(p2-p1)*t*(1-t)^3+
    6*(p3-p2)*t^2*(1-t)^2+4*(p4-p3)*t^3*(1-t)+(p5-p4)*t^4)

theorem web_bezier_derivative (p0 p1 p2 p3 p4 p5 t : ℝ) :
    HasDerivAt (webBezier p0 p1 p2 p3 p4 p5)
      (webBezierSlope p0 p1 p2 p3 p4 p5 t) t := by
  have hi := hasDerivAt_id t
  have hj := hi.const_sub 1
  have h := ((((((hj.pow 5).const_mul p0).add
    ((hi.const_mul (5*p1)).mul (hj.pow 4))).add
    (((hi.pow 2).const_mul (10*p2)).mul (hj.pow 3))).add
    (((hi.pow 3).const_mul (10*p3)).mul (hj.pow 2))).add
    (((hi.pow 4).const_mul (5*p4)).mul hj)).add ((hi.pow 5).const_mul p5)
  convert h using 1
  · funext x; simp [webBezier]
  · simp [webBezierSlope]; ring

theorem web_bezier_slope_positive (p0 p1 p2 p3 p4 p5 t : ℝ)
    (h01 : p0 < p1) (h12 : p1 < p2) (h23 : p2 < p3)
    (h34 : p3 < p4) (h45 : p4 < p5) (ht : t ∈ Icc (0 : ℝ) 1) :
    0 < webBezierSlope p0 p1 p2 p3 p4 p5 t := by
  have h0 : 0 ≤ t := ht.1
  have h1 : 0 ≤ 1-t := by linarith [ht.2]
  have hA : 0 ≤ 4*(p2-p1)*t*(1-t)^3 := by positivity
  have hB : 0 ≤ 6*(p3-p2)*t^2*(1-t)^2 := by positivity
  have hC : 0 ≤ 4*(p4-p3)*t^3*(1-t) := by positivity
  have hD : 0 ≤ (p5-p4)*t^4 := by positivity
  have hE : 0 ≤ (p1-p0)*(1-t)^4 := by positivity
  unfold webBezierSlope
  by_cases hz : t = 1
  · subst t; norm_num; linarith
  · have hpos : 0 < (p1-p0)*(1-t)^4 := by
      apply mul_pos (sub_pos.mpr h01)
      exact pow_pos (sub_pos.mpr (lt_of_le_of_ne ht.2 hz)) _
    linarith

def webHueSector (φ0 φ1 w d0 d1 : ℝ) : ℝ → ℝ :=
  webBezier φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
    (φ1-2*w*d1/5) (φ1-w*d1/5) φ1

theorem web_hue_sector_endpoints (φ0 φ1 w d0 d1 : ℝ) :
    webHueSector φ0 φ1 w d0 d1 0 = φ0 ∧ webHueSector φ0 φ1 w d0 d1 1 = φ1 := by
  norm_num [webHueSector, webBezier]

theorem web_hue_sector_slope_positive (φ0 φ1 w m p q t : ℝ)
    (hw : 0 < w) (hm : 0 < m) (hp : 0 < p) (hq : 0 < q)
    (hsec : φ1-φ0 = w*m) (ht : t ∈ Icc (0 : ℝ) 1) :
    0 < deriv (webHueSector φ0 φ1 w (webMeanSlope p m) (webMeanSlope m q)) t := by
  unfold webHueSector
  rw [(web_bezier_derivative _ _ _ _ _ _ t).deriv]
  have hd0 := web_mean_slope_positive p m hp hm
  have hd1 := web_mean_slope_positive m q hm hq
  have hg := web_quintic_gap_positive m p q hm hp hq
  apply web_bezier_slope_positive
  · nlinarith [mul_pos hw hd0]
  · nlinarith [mul_pos hw hd0]
  · nlinarith [mul_pos hw hg]
  · nlinarith [mul_pos hw hd1]
  · nlinarith [mul_pos hw hd1]
  · exact ht

def webBezierCurvature (p0 p1 p2 p3 p4 p5 t : ℝ) : ℝ :=
  20*((p2-2*p1+p0)*(1-t)^3+3*(p3-2*p2+p1)*t*(1-t)^2+
    3*(p4-2*p3+p2)*t^2*(1-t)+(p5-2*p4+p3)*t^3)

theorem web_bezier_second_derivative (p0 p1 p2 p3 p4 p5 t : ℝ) :
    HasDerivAt (webBezierSlope p0 p1 p2 p3 p4 p5)
      (webBezierCurvature p0 p1 p2 p3 p4 p5 t) t := by
  have hi := hasDerivAt_id t
  have hj := hi.const_sub 1
  have h := ((((((hj.pow 4).const_mul (p1-p0)).add
    ((hi.const_mul (4*(p2-p1))).mul (hj.pow 3))).add
    (((hi.pow 2).const_mul (6*(p3-p2))).mul (hj.pow 2))).add
    (((hi.pow 3).const_mul (4*(p4-p3))).mul hj)).add
    ((hi.pow 4).const_mul (p5-p4))).const_mul 5
  convert h using 1
  · funext x; simp [webBezierSlope]
  · simp [webBezierCurvature]; ring

theorem web_hue_sector_jets (φ0 φ1 w d0 d1 : ℝ) :
    deriv (webHueSector φ0 φ1 w d0 d1) 0 = w*d0 ∧
    deriv (webHueSector φ0 φ1 w d0 d1) 1 = w*d1 ∧
    deriv (deriv (webHueSector φ0 φ1 w d0 d1)) 0 = 0 ∧
    deriv (deriv (webHueSector φ0 φ1 w d0 d1)) 1 = 0 := by
  have hd : deriv (webHueSector φ0 φ1 w d0 d1) =
      webBezierSlope φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
        (φ1-2*w*d1/5) (φ1-w*d1/5) φ1 := by
    funext t
    exact (web_bezier_derivative _ _ _ _ _ _ t).deriv
  rw [hd, (web_bezier_second_derivative _ _ _ _ _ _ 0).deriv,
    (web_bezier_second_derivative _ _ _ _ _ _ 1).deriv]
  norm_num [webBezierSlope, webBezierCurvature]
  ring_nf
  simp

def webHuePhysical (φ0 φ1 x0 w d0 d1 x : ℝ) : ℝ :=
  webHueSector φ0 φ1 w d0 d1 ((x-x0)/w)

theorem web_hue_physical_derivative (φ0 φ1 x0 w d0 d1 x : ℝ) :
    HasDerivAt (webHuePhysical φ0 φ1 x0 w d0 d1)
      (webBezierSlope φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
        (φ1-2*w*d1/5) (φ1-w*d1/5) φ1 ((x-x0)/w)/w) x := by
  have h := (web_bezier_derivative φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
    (φ1-2*w*d1/5) (φ1-w*d1/5) φ1 ((x-x0)/w)).comp x
    (((hasDerivAt_id x).sub_const x0).div_const w)
  convert h using 1
  · rfl
  · simp only [div_eq_mul_inv, one_mul]

theorem web_hue_physical_second_derivative (φ0 φ1 x0 w d0 d1 x : ℝ) :
    HasDerivAt (deriv (webHuePhysical φ0 φ1 x0 w d0 d1))
      (webBezierCurvature φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
        (φ1-2*w*d1/5) (φ1-w*d1/5) φ1 ((x-x0)/w)/w^2) x := by
  have hd : deriv (webHuePhysical φ0 φ1 x0 w d0 d1) = fun z =>
      webBezierSlope φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
        (φ1-2*w*d1/5) (φ1-w*d1/5) φ1 ((z-x0)/w)/w :=
    funext fun z => (web_hue_physical_derivative φ0 φ1 x0 w d0 d1 z).deriv
  rw [hd]
  have h := ((web_bezier_second_derivative φ0 (φ0+w*d0/5) (φ0+2*w*d0/5)
    (φ1-2*w*d1/5) (φ1-w*d1/5) φ1 ((x-x0)/w)).comp x
    (((hasDerivAt_id x).sub_const x0).div_const w)).div_const w
  convert h using 1
  · rfl
  · simp only [div_eq_mul_inv, pow_two]; ring

/-- Adjacent physical hue sectors share d1 and zero curvature at their joint. -/
theorem web_hue_join_c2 (a b c wL wR d0 d1 d2 : ℝ)
    (hl : wL ≠ 0) (hr : wR ≠ 0) :
    ContDiff ℝ 2 (joined wL (webHuePhysical a b 0 wL d0 d1)
      (webHuePhysical b c wL wR d1 d2)) := by
  apply joined_c2
  · unfold webHuePhysical webHueSector webBezier; fun_prop
  · unfold webHuePhysical webHueSector webBezier; fun_prop
  · simp [webHuePhysical, webHueSector, webBezier, hl]
  · rw [(web_hue_physical_derivative a b 0 wL d0 d1 wL).deriv,
      (web_hue_physical_derivative b c wL wR d1 d2 wL).deriv]
    simp [webBezierSlope, hl]
    field_simp
  · rw [(web_hue_physical_second_derivative a b 0 wL d0 d1 wL).deriv,
      (web_hue_physical_second_derivative b c wL wR d1 d2 wL).deriv]
    simp [webBezierCurvature, hl]
    ring

end
end PerceptualGrade

