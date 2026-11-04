import PerceptualGrade.PoleSpindle
import Mathlib.Analysis.SpecialFunctions.Trigonometric.Inverse
import Mathlib.Analysis.SpecialFunctions.Complex.Arg

namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped Topology

/-- Largest real root of a monic cubic with three distinct real roots. -/
def poleCubicLargest (u v w : ℝ) : ℝ :=
  (-u + 2 * Real.sqrt (u^2-3*v) *
    Real.cos (Real.arccos ((-2*u^3+9*u*v-27*w) /
      (2*(Real.sqrt (u^2-3*v))^3))/3))/3

/-- Recover the positive middle root without subtracting nearly equal numbers. -/
def poleCubicMiddle (u v w : ℝ) : ℝ :=
  let l := poleCubicLargest u v w
  let q := -w/l
  let s := (q-v)/l
  let h := Real.sqrt (s^2-4*q)
  if 0 ≤ s then -2*q/(h+s) else (h-s)/2

/-- The discriminant identity certifies the domain of the inverse cosine. -/
theorem pole_cubic_discriminant (a b c : ℝ) :
    4*((-(a+b+c))^2-3*(a*b+a*c+b*c))^3 -
      (-2*(-(a+b+c))^3+9*(-(a+b+c))*(a*b+a*c+b*c)-27*(-a*b*c))^2 =
      27*(a-b)^2*(a-c)^2*(b-c)^2 := by ring

/-- The inverse-cosine formula selects the largest root, not an arbitrary root. -/
theorem pole_cubic_largest_correct (a b c : ℝ) (hab : a < b) (hbc : b < c) :
    poleCubicLargest (-(a+b+c)) (a*b+a*c+b*c) (-a*b*c) = c := by
  let u := -(a+b+c)
  let v := a*b+a*c+b*c
  let w := -a*b*c
  let d := Real.sqrt (u^2-3*v)
  let n := -2*u^3+9*u*v-27*w
  have hD : 0 < u^2-3*v := by
    dsimp [u, v]
    nlinarith [sq_nonneg (a-c), sq_nonneg (b-c), sq_pos_of_ne_zero (sub_ne_zero.mpr (ne_of_lt hab))]
  have hd : 0 < d := Real.sqrt_pos.2 hD
  have hd2 : d^2 = u^2-3*v := Real.sq_sqrt hD.le
  have hdisc : n^2 < 4*(u^2-3*v)^3 := by
    have he := pole_cubic_discriminant a b c
    have hp : 0 < 27*(a-b)^2*(a-c)^2*(b-c)^2 := by
      exact mul_pos (mul_pos (mul_pos (by norm_num)
        (sq_pos_of_ne_zero (sub_ne_zero.mpr (ne_of_lt hab))))
        (sq_pos_of_ne_zero (sub_ne_zero.mpr (ne_of_lt (hab.trans hbc)))))
        (sq_pos_of_ne_zero (sub_ne_zero.mpr (ne_of_lt hbc)))
    dsimp [n, u, v, w]
    linarith
  have hden : 0 < 2*d^3 := by positivity
  have hdsq : (2*d^3)^2 = 4*(u^2-3*v)^3 := by
    calc
      (2*d^3)^2 = 4*(d^2)^3 := by ring
      _ = _ := by rw [hd2]
  have hn : - (2*d^3) < n ∧ n < 2*d^3 := by
    constructor <;> nlinarith
  have harg : -1 ≤ n/(2*d^3) ∧ n/(2*d^3) ≤ 1 := by
    constructor
    · apply (le_div_iff₀ hden).2
      linarith [hn.1]
    · apply (div_le_iff₀ hden).2
      linarith [hn.2]
  let θ := Real.arccos (n/(2*d^3))/3
  let m := Real.cos θ
  have htriple : 4*m^3-3*m = n/(2*d^3) := by
    have h := Real.cos_three_mul θ
    have he : 3*θ = Real.arccos (n/(2*d^3)) := by dsimp [θ]; ring
    rw [he, Real.cos_arccos harg.1 harg.2] at h
    exact h.symm
  have hm : 1/2 ≤ m := by
    have ht0 : 0 ≤ θ := div_nonneg (Real.arccos_nonneg _) (by norm_num)
    have ht1 : θ ≤ Real.pi/3 := div_le_div_of_nonneg_right
      (Real.arccos_le_pi _) (by norm_num)
    have h := Real.cos_le_cos_of_nonneg_of_le_pi ht0
      (show Real.pi/3 ≤ Real.pi by linarith [Real.pi_pos]) ht1
    rw [Real.cos_pi_div_three] at h
    exact h
  let l := (-u+2*d*m)/3
  have hlroot : l^3+u*l^2+v*l+w = 0 := by
    have he : (4*m^3-3*m)*(2*d^3) = n := (eq_div_iff (ne_of_gt hden)).1 htriple
    have hid : 27*(l^3+u*l^2+v*l+w) =
        2*d^3*(4*m^3-3*m)-n +
        6*d*m*(d^2-(u^2-3*v)) := by
      dsimp [l, n]
      ring
    rw [hd2] at hid
    nlinarith [he]
  have hbcrit : 3*b+u < d := by
    have hsq : (3*b+u)^2 < d^2 := by
      rw [hd2]
      dsimp [u, v]
      nlinarith [mul_pos (sub_pos.mpr hab) (sub_pos.mpr hbc)]
    nlinarith
  have hlb : b < l := by
    have hmul := mul_le_mul_of_nonneg_left hm (show 0 ≤ 2*d by positivity)
    dsimp [l]
    linarith
  have hfact : (l-a)*(l-b)*(l-c) = 0 := by
    calc
      (l-a)*(l-b)*(l-c) = l^3+u*l^2+v*l+w := by dsimp [u, v, w]; ring
      _ = 0 := hlroot
  have hlc : l = c := by
    rcases mul_eq_zero.mp hfact with hab0 | hc0
    · rcases mul_eq_zero.mp hab0 with ha0 | hb0
      · exfalso; linarith
      · exfalso; linarith
    · linarith
  exact hlc

/-- Both numerical branches of the stable quadratic formula are the middle root. -/
theorem pole_cubic_middle_correct (a b c : ℝ) (ha : a < 0) (hb : 0 < b)
    (hbc : b < c) :
    poleCubicMiddle (-(a+b+c)) (a*b+a*c+b*c) (-a*b*c) = b := by
  have hc : 0 < c := hb.trans hbc
  have hc0 : c ≠ 0 := ne_of_gt hc
  have hl := pole_cubic_largest_correct a b c (ha.trans hb) hbc
  have hq : -(-a*b*c)/c = a*b := by field_simp
  have hs : (a*b-(a*b+a*c+b*c))/c = -(a+b) := by field_simp; ring
  have hh : Real.sqrt ((-(a+b))^2-4*(a*b)) = b-a := by
    have he : (-(a+b))^2-4*(a*b) = (b-a)^2 := by ring
    rw [he, Real.sqrt_sq (by linarith : 0 ≤ b-a)]
  unfold poleCubicMiddle
  simp only [hl]
  rw [hq, hs, hh]
  split_ifs with h
  · have hd : b-a+-(a+b) ≠ 0 := by linarith
    apply (div_eq_iff hd).2
    ring
  · ring


/-- A positive physical root below a negative polynomial sample is the middle root.
The hypotheses are polynomial identities and signs, not an assumed inverse. -/
theorem pole_cubic_physical_root (u v w z P : ℝ) (hz : 0 < z) (hzP : z < P)
    (hw : 0 < w) (hroot : z^3+u*z^2+v*z+w=0)
    (hP : P^3+u*P^2+v*P+w < 0) : poleCubicMiddle u v w = z := by
  let s := u+z
  let q := -w/z
  have hq : q < 0 := div_neg_of_neg_of_pos (neg_neg_of_pos hw) hz
  let d := Real.sqrt (s^2-4*q)
  have hd : 0 < d := Real.sqrt_pos.2 (by nlinarith [sq_nonneg s])
  have hd2 : d^2=s^2-4*q := Real.sq_sqrt (by nlinarith [sq_nonneg s])
  have hsabs : -d < s ∧ s < d := by constructor <;> nlinarith
  let a := (-s-d)/2
  let c := (-s+d)/2
  have ha : a < 0 := by dsimp [a]; linarith [hsabs.1]
  have hc : 0 < c := by dsimp [c]; linarith [hsabs.2]
  have hac : a*c=q := by dsimp [a,c]; nlinarith [hd2]
  have has : a+c = -s := by dsimp [a,c]; ring
  have hcoefU : u = -(a+z+c) := by dsimp [s] at has; linarith
  have hcoefW : w = -a*z*c := by
    have he : q*z = -w := by dsimp [q]; field_simp
    rw [←hac] at he
    nlinarith
  have hcoefV : v = a*z+a*c+z*c := by
    have hz0 : z ≠ 0 := ne_of_gt hz
    have he : z*(v-(a*z+a*c+z*c))=0 := by rw [hcoefU,hcoefW] at hroot; nlinarith [hroot]
    exact sub_eq_zero.mp ((mul_eq_zero.mp he).resolve_left hz0)
  have hfactP : (P-a)*(P-z)*(P-c) < 0 := by
    have he : (P-a)*(P-z)*(P-c)=P^3+u*P^2+v*P+w := by
      rw [hcoefU,hcoefV,hcoefW]; ring
    rwa [he]
  have hPc : P < c := by
    have hleft : 0 < (P-a)*(P-z) := mul_pos (by linarith) (by linarith)
    have hright : P-c < 0 := by nlinarith
    linarith
  rw [hcoefU,hcoefV,hcoefW]
  exact pole_cubic_middle_correct a z c ha hz (hzP.trans hPc)


def poleInverseA3 (t : ℝ) : ℝ := -t+(1-t)*poleSpindleB
def poleInverseA2 (t r : ℝ) : ℝ := t*(poleSpindleP-1)+(1-t)*poleSpindleA+r^2
def poleInverseA1 (t r : ℝ) : ℝ := t*poleSpindleP-r^2*(poleSpindleP-1)
def poleInverseA0 (r : ℝ) : ℝ := -r^2*poleSpindleP

def poleSpindleInverseSquare (t r : ℝ) : ℝ :=
  poleCubicMiddle (poleInverseA2 t r/poleInverseA3 t)
    (poleInverseA1 t r/poleInverseA3 t) (poleInverseA0 r/poleInverseA3 t)

/-- Denominator clearing yields exactly the cubic used by the implementation. -/
theorem pole_spindle_inverse_polynomial (t r z : ℝ) (hz : 0 ≤ z)
    (hp : z < poleSpindleP) :
    poleInverseA3 t*z^3+poleInverseA2 t r*z^2+poleInverseA1 t r*z+poleInverseA0 r =
    (t*z+(1-t)*z*poleSpindleF z-r^2)*(1+z)*(poleSpindleP-z) := by
  have hden := (pole_spindle_denominator_pos z hz hp).ne'
  have h1 : 1+z ≠ 0 := by positivity
  have h2 : poleSpindleP-z ≠ 0 := ne_of_gt (sub_pos.mpr hp)
  unfold poleInverseA3 poleInverseA2 poleInverseA1 poleInverseA0 poleSpindleF
  field_simp [h1,h2]
  ring

/-- Concrete coefficient signs and the release equation prove the correct branch. -/
theorem pole_spindle_inverse_square_correct (t r z : ℝ) (ht : 0 < t) (ht1 : t < 1)
    (hr : 0 < r^2) (hz : 0 < z) (hzP : z < poleSpindleP)
    (he : r^2=t*z+(1-t)*z*poleSpindleF z) : poleSpindleInverseSquare t r = z := by
  have ha : poleInverseA3 t < 0 := by
    unfold poleInverseA3 poleSpindleB poleSpindleA poleSpindleP
    nlinarith
  have ha0 := ne_of_lt ha
  have hw : 0 < poleInverseA0 r/poleInverseA3 t :=
    div_pos_of_neg_of_neg (by unfold poleInverseA0 poleSpindleP; nlinarith) ha
  have hroot : z^3+(poleInverseA2 t r/poleInverseA3 t)*z^2+
      (poleInverseA1 t r/poleInverseA3 t)*z+poleInverseA0 r/poleInverseA3 t=0 := by
    have h := pole_spindle_inverse_polynomial t r z hz.le hzP
    rw [←he] at h
    have hp : poleInverseA3 t*z^3+poleInverseA2 t r*z^2+
        poleInverseA1 t r*z+poleInverseA0 r=0 := by nlinarith [h]
    field_simp
    nlinarith [hp]
  have hp : 0 < poleInverseA3 t*poleSpindleP^3+
      poleInverseA2 t r*poleSpindleP^2+poleInverseA1 t r*poleSpindleP+poleInverseA0 r := by
    have hid : poleInverseA3 t*poleSpindleP^3+
        poleInverseA2 t r*poleSpindleP^2+poleInverseA1 t r*poleSpindleP+poleInverseA0 r =
        (1-t)*poleSpindleP^2*(poleSpindleA+poleSpindleB*poleSpindleP) := by
      unfold poleInverseA3 poleInverseA2 poleInverseA1 poleInverseA0
      ring
    rw [hid]
    have hPP : 0 < poleSpindleP^2 := by norm_num [poleSpindleP]
    have hP1 : 0 < poleSpindleA+poleSpindleB*poleSpindleP :=
      pole_spindle_profile_coefficients.2.1
    exact mul_pos (mul_pos (by linarith) hPP) hP1
  have hP : poleSpindleP^3+(poleInverseA2 t r/poleInverseA3 t)*poleSpindleP^2+
      (poleInverseA1 t r/poleInverseA3 t)*poleSpindleP+poleInverseA0 r/poleInverseA3 t < 0 := by
    have heq : poleSpindleP^3+(poleInverseA2 t r/poleInverseA3 t)*poleSpindleP^2+
        (poleInverseA1 t r/poleInverseA3 t)*poleSpindleP+poleInverseA0 r/poleInverseA3 t =
        (poleInverseA3 t*poleSpindleP^3+poleInverseA2 t r*poleSpindleP^2+
        poleInverseA1 t r*poleSpindleP+poleInverseA0 r)/poleInverseA3 t := by field_simp
    rw [heq]
    exact div_neg_of_pos_of_neg hp ha
  exact pole_cubic_physical_root _ _ _ z poleSpindleP hz hzP hw hroot hP


/-- Closed form compression, in units of the spindle capacity.
The identity and neutral cases avoid degeneracies in the cubic formula. -/
def poleSpindleCompress (k y : ℝ) : ℝ :=
  if k = 1 then y else if y = 0 then 0 else
    Real.sqrt (poleSpindleInverseSquare (1/k^2) (y/k))

theorem pole_spindle_compress_one (y : ℝ) : poleSpindleCompress 1 y = y := by
  simp [poleSpindleCompress]

theorem pole_spindle_compress_zero (k : ℝ) : poleSpindleCompress k 0 = 0 := by
  simp [poleSpindleCompress]

/-- The actual noniterative formula is a left inverse, including neutral and the boundary. -/
theorem pole_spindle_compress_release (k x : ℝ) (hk : 1 ≤ k) (hx : 0 ≤ x)
    (hp : x^2 < poleSpindleP) : poleSpindleCompress k (poleSpindleRelease k x) = x := by
  by_cases hk1 : k=1
  · subst k
    simp [poleSpindleCompress, poleSpindleRelease]
  by_cases hx0 : x=0
  · subst x
    simp [poleSpindleRelease, pole_spindle_compress_zero]
  have hxpos : 0 < x := lt_of_le_of_ne hx (Ne.symm hx0)
  have hkpos : 0 < k := by linarith
  have hk0 : k ≠ 0 := ne_of_gt hkpos
  have hkgt : 1 < k := lt_of_le_of_ne hk (Ne.symm hk1)
  have ha := pole_spindle_radicand_pos k x hk hp
  have hs : (Real.sqrt (1+(k^2-1)*poleSpindleF (x^2)))^2 =
      1+(k^2-1)*poleSpindleF (x^2) := Real.sq_sqrt ha.le
  have hy : 0 < poleSpindleRelease k x := by
    unfold poleSpindleRelease
    exact mul_pos hxpos (Real.sqrt_pos.2 ha)
  have ht : 0 < 1/k^2 := div_pos (by norm_num) (sq_pos_of_pos hkpos)
  have ht1 : 1/k^2 < 1 := (div_lt_one (sq_pos_of_pos hkpos)).2 (by nlinarith)
  have hr : 0 < (poleSpindleRelease k x/k)^2 := sq_pos_of_pos (div_pos hy hkpos)
  have he : (poleSpindleRelease k x/k)^2 = (1/k^2)*x^2+
      (1-1/k^2)*x^2*poleSpindleF (x^2) := by
    unfold poleSpindleRelease
    rw [div_pow,mul_pow,hs]
    field_simp
  have hroot := pole_spindle_inverse_square_correct (1/k^2)
    (poleSpindleRelease k x/k) (x^2) ht ht1 hr (sq_pos_of_pos hxpos) hp he
  simp only [poleSpindleCompress, hk1, ite_false, ne_of_gt hy, hroot, Real.sqrt_sq hx]

/-- On the physical cube interval the closed inverse is a right inverse and stays in the spindle. -/
theorem pole_spindle_release_compress (k y : ℝ) (hk : 1 ≤ k) (hy : y ∈ Icc 0 k) :
    poleSpindleCompress k y ∈ Icc 0 1 ∧ poleSpindleRelease k (poleSpindleCompress k y)=y := by
  obtain ⟨x,⟨hx,he⟩,_⟩ := pole_spindle_inverse_exists k y hk hy
  have hp : x^2 < poleSpindleP := by
    have := pole_spindle_P_bounds.1
    nlinarith [hx.1,hx.2]
  rw [←he,pole_spindle_compress_release k x hk hx.1 hp]
  exact ⟨hx,rfl⟩


/-- The explicit compression cannot increase radius on the physical cube interval. -/
theorem pole_spindle_compress_le (k y : ℝ) (hk : 1 ≤ k) (hy : y ∈ Icc 0 k) :
    poleSpindleCompress k y ≤ y := by
  have h := pole_spindle_release_compress k y hk hy
  by_cases hk1 : k=1
  · subst k
    simp [poleSpindleCompress]
  by_cases hx0 : poleSpindleCompress k y=0
  · rw [hx0]
    exact hy.1
  have hx : 0 < poleSpindleCompress k y := lt_of_le_of_ne h.1.1 (Ne.symm hx0)
  have hp : (poleSpindleCompress k y)^2 < poleSpindleP := by
    have := pole_spindle_P_bounds.1
    nlinarith [h.1.1,h.1.2]
  have hl := pole_spindle_global_compression k (poleSpindleCompress k y)
    (lt_of_le_of_ne hk (Ne.symm hk1)) hx hp
  rw [h.2] at hl
  exact hl.le

/-- Factoring the input radius outside the square root avoids tiny-radius underflow.
This is the exact-real counterpart of the reference evaluation of the stable branch. -/
theorem pole_spindle_factored_sqrt (r P a L H s : ℝ) (hr : 0 ≤ r)
    (ha : a ≠ 0) (hL : L ≠ 0) (hHs : H+s ≠ 0) :
    Real.sqrt (-2*(-(-r^2*P/a)/L)/(H+s)) =
      r*Real.sqrt ((-2*P/a)/(L*(H+s))) := by
  have he : -2*(-(-r^2*P/a)/L)/(H+s) = r^2*((-2*P/a)/(L*(H+s))) := by
    field_simp
  rw [he,Real.sqrt_mul (sq_nonneg r),Real.sqrt_sq hr]

/-- Reset with the unchanged hard guard follows for the actual closed inverse. -/
theorem pole_spindle_reset (k y : ℝ) (hk : 1 ≤ k) (hy : y ∈ Icc 0 k) :
    poleSpindleRelease k (hardSpindleRadius 1 (poleSpindleCompress k y))=y := by
  have h := pole_spindle_release_compress k y hk hy
  rw [hard_spindle_identity 1 _ h.1.2]
  exact h.2


/-- Odd analytic extension used only for differentiability statements at neutral. -/
def poleSpindleSignedCompress (k y : ℝ) : ℝ :=
  if 0 ≤ y then poleSpindleCompress k y else -poleSpindleCompress k (-y)

theorem pole_spindle_release_odd (k x : ℝ) :
    poleSpindleRelease k (-x) = -poleSpindleRelease k x := by
  simp [poleSpindleRelease]

theorem pole_spindle_signed_compress_release (k x : ℝ) (hk : 1 ≤ k)
    (hp : x^2 < poleSpindleP) :
    poleSpindleSignedCompress k (poleSpindleRelease k x)=x := by
  by_cases hx : 0 ≤ x
  · have hy : 0 ≤ poleSpindleRelease k x := mul_nonneg hx (Real.sqrt_nonneg _)
    simp only [poleSpindleSignedCompress,hy,ite_true]
    exact pole_spindle_compress_release k x hk hx hp
  · have hxneg : x < 0 := lt_of_not_ge hx
    have hy : poleSpindleRelease k x < 0 := mul_neg_of_neg_of_pos hxneg
      (Real.sqrt_pos.2 (pole_spindle_radicand_pos k x hk hp))
    simp only [poleSpindleSignedCompress,not_le.mpr hy,ite_false]
    rw [←pole_spindle_release_odd]
    have hpneg : (-x)^2 < poleSpindleP := by simpa using hp
    rw [pole_spindle_compress_release k (-x) hk (by linarith) hpneg]
    ring


/-- The pole supplies enough range for every finite nonnegative cube radius. -/
theorem pole_spindle_release_compress_extended (k y : ℝ) (hk : 1 < k) (hy : 0 ≤ y) :
    poleSpindleCompress k y ∈ Ico 0 (1001/1000) ∧
      poleSpindleRelease k (poleSpindleCompress k y)=y := by
  have hf := pole_spindle_release_tendsto_pole k hk
  have hb : ∀ᶠ b : ℝ in 𝓝[<] (1001/1000),
      0 < b ∧ b < 1001/1000 ∧ y ≤ poleSpindleRelease k b := by
    have h0 : ∀ᶠ b : ℝ in 𝓝[<] (1001/1000), 0 < b :=
      (eventually_gt_nhds (by norm_num : (0:ℝ)<1001/1000)).filter_mono nhdsWithin_le_nhds
    have hp : ∀ᶠ b : ℝ in 𝓝[<] (1001/1000), b < 1001/1000 := self_mem_nhdsWithin
    exact h0.and (hp.and (hf.eventually_ge_atTop y))
  obtain ⟨b,hb0,hbp,hby⟩ := hb.exists
  have hc : ContinuousOn (poleSpindleRelease k) (Icc 0 b) := by
    intro x hx
    apply (pole_spindle_c2_at k x hk.le ?_).continuousAt.continuousWithinAt
    norm_num [poleSpindleP]
    nlinarith [hx.1,hx.2]
  have hi : y ∈ Icc (poleSpindleRelease k 0) (poleSpindleRelease k b) := by
    rw [pole_spindle_release_zero]
    exact ⟨hy,hby⟩
  obtain ⟨x,hx,he⟩ := intermediate_value_Icc hb0.le hc hi
  have hp : x^2 < poleSpindleP := by
    norm_num [poleSpindleP]
    nlinarith [hx.1,hx.2]
  rw [←he,pole_spindle_compress_release k x hk.le hx.1 hp]
  exact ⟨⟨hx.1,lt_of_le_of_lt hx.2 hbp⟩,rfl⟩

/-- Compression approaches the spindle-side pole for unbounded cube chroma. -/
theorem pole_spindle_compress_tendsto_pole (k : ℝ) (hk : 1 < k) :
    Tendsto (poleSpindleCompress k) atTop (𝓝 (1001/1000)) := by
  apply tendsto_order.mpr
  constructor
  · intro a ha
    let b := (max a 0+(1001/1000))/2
    have hb0 : 0 < b := by dsimp [b]; nlinarith [le_max_right a 0]
    have hab : a < b := by dsimp [b]; nlinarith [le_max_left a 0,le_max_right a 0]
    have hbp : b < 1001/1000 := by
      have hm : max a 0 < 1001/1000 := max_lt ha (by norm_num)
      dsimp [b]; linarith
    have hey : ∀ᶠ y : ℝ in atTop, 0 ≤ y ∧ poleSpindleRelease k b < y :=
      (eventually_ge_atTop 0).and (eventually_gt_atTop (poleSpindleRelease k b))
    filter_upwards [hey] with y hy
    have hx := pole_spindle_release_compress_extended k y hk hy.1
    have hbx : b < poleSpindleCompress k y := by
      by_contra hn
      have hm := (pole_spindle_strict_mono_extended k hk.le).monotoneOn
        (show poleSpindleCompress k y ∈ Ioo (-(1001/1000)) (1001/1000) from
          ⟨by linarith [hx.1.1],hx.1.2⟩)
        (show b ∈ Ioo (-(1001/1000):ℝ) (1001/1000) from ⟨by linarith,hbp⟩) (le_of_not_gt hn)
      rw [hx.2] at hm
      linarith [hy.2]
    exact hab.trans hbx
  · intro a ha
    filter_upwards [eventually_ge_atTop (0:ℝ)] with y hy
    have hx := pole_spindle_release_compress_extended k y hk hy
    exact hx.1.2.trans ha


/-- The cosine branch is positive whenever the cubic's quadratic coefficient is negative. -/
theorem pole_cubic_largest_pos (u v w : ℝ) (hu : u < 0) :
    0 < poleCubicLargest u v w := by
  let d := Real.sqrt (u^2-3*v)
  let θ := Real.arccos ((-2*u^3+9*u*v-27*w)/(2*d^3))/3
  have ht0 : 0 ≤ θ := div_nonneg (Real.arccos_nonneg _) (by norm_num)
  have ht1 : θ ≤ Real.pi/3 := div_le_div_of_nonneg_right
    (Real.arccos_le_pi _) (by norm_num)
  have hc := Real.cos_le_cos_of_nonneg_of_le_pi ht0
    (show Real.pi/3 ≤ Real.pi by linarith [Real.pi_pos]) ht1
  rw [Real.cos_pi_div_three] at hc
  have hm : 0 ≤ 2*d*Real.cos θ :=
    mul_nonneg (mul_nonneg (by norm_num) (Real.sqrt_nonneg _)) (by linarith)
  change 0 < (-u+2*d*Real.cos θ)/3
  linarith

/-- The implemented reciprocal and factored gain give the same exact cubic coefficients. -/
theorem pole_spindle_reciprocal_coefficients (k : ℝ) :
    (1/k)*(1/k) = 1/k^2 ∧ (1-1/k)*(1+1/k) = 1-1/k^2 := by
  constructor <;> ring

/-- Every denominator in the factored-radius branch is strictly positive except the
negative leading coefficient. The hypot radicand is the stable quadratic discriminant. -/
theorem pole_spindle_stable_branch_domain (t r : ℝ) (ht : 0 < t) (ht1 : t < 1)
    (hr : 0 < r) :
    let a := poleInverseA3 t
    let u := poleInverseA2 t r/a
    let v := poleInverseA1 t r/a
    let w := poleInverseA0 r/a
    let L := poleCubicLargest u v w
    let q := -w/L
    let s := (q-v)/L
    a < 0 ∧ 0 < L ∧ q < 0 ∧
      0 < Real.sqrt (s^2-4*q)+s ∧
      Real.sqrt (s^2+(2*Real.sqrt (-q))^2) = Real.sqrt (s^2-4*q) := by
  dsimp only
  let a := poleInverseA3 t
  let u := poleInverseA2 t r/a
  let v := poleInverseA1 t r/a
  let w := poleInverseA0 r/a
  let L := poleCubicLargest u v w
  let q := -w/L
  let s := (q-v)/L
  have ha : a < 0 := by dsimp [a,poleInverseA3,poleSpindleB,poleSpindleA,poleSpindleP]; nlinarith
  have hA2 : 0 < poleInverseA2 t r := by
    have hP := pole_spindle_P_bounds.1
    unfold poleInverseA2
    have h1 : 0 < t*(poleSpindleP-1) := mul_pos ht (sub_pos.mpr hP)
    have h2 : 0 ≤ (1-t)*poleSpindleA := mul_nonneg (by linarith)
      (by norm_num [poleSpindleA,poleSpindleP])
    nlinarith [sq_nonneg r]
  have hu : u < 0 := div_neg_of_pos_of_neg hA2 ha
  have hL : 0 < L := pole_cubic_largest_pos u v w hu
  have hw : 0 < w := by
    apply div_pos_of_neg_of_neg _ ha
    dsimp [poleInverseA0]
    have hP : 0 < poleSpindleP := by norm_num [poleSpindleP]
    exact mul_neg_of_neg_of_pos (neg_neg_of_pos (sq_pos_of_pos hr)) hP
  have hq : q < 0 := div_neg_of_neg_of_pos (neg_neg_of_pos hw) hL
  have hh : 0 < Real.sqrt (s^2-4*q)+s := by
    have hsq : (Real.sqrt (s^2-4*q))^2 = s^2-4*q :=
      Real.sq_sqrt (by nlinarith [sq_nonneg s])
    nlinarith [Real.sqrt_nonneg (s^2-4*q)]
  have he : Real.sqrt (s^2+(2*Real.sqrt (-q))^2) = Real.sqrt (s^2-4*q) := by
    have hs : (Real.sqrt (-q))^2 = -q := Real.sq_sqrt (by linarith)
    congr 1
    nlinarith
  exact ⟨ha,hL,hq,hh,he⟩

/-- Exact real form of the reference's factored-radius and hypot evaluation.
Only the evaluation is branched; both paths evaluate the same analytic inverse. -/
def poleSpindleCompressStable (k y : ℝ) : ℝ :=
  if k = 1 then y else if y = 0 then 0 else
    let t := 1/k^2
    let r := y/k
    let a := poleInverseA3 t
    let u := poleInverseA2 t r/a
    let v := poleInverseA1 t r/a
    let w := poleInverseA0 r/a
    let L := poleCubicLargest u v w
    let q := -w/L
    let s := (q-v)/L
    let h := Real.sqrt (s^2+(2*Real.sqrt (-q))^2)
    if 0 ≤ s then r*Real.sqrt ((-2*poleSpindleP/a)/(L*(h+s)))
    else Real.sqrt ((h-s)/2)

/-- The exact factored-radius implementation equals the proved closed inverse over
its full nonnegative domain, including identity, neutral, and the physical boundary. -/
theorem pole_spindle_compress_stable_eq (k y : ℝ) (hk : 1 ≤ k) (hy : 0 ≤ y) :
    poleSpindleCompressStable k y = poleSpindleCompress k y := by
  by_cases hk1 : k=1
  · simp [poleSpindleCompressStable,poleSpindleCompress,hk1]
  by_cases hy0 : y=0
  · simp [poleSpindleCompressStable,poleSpindleCompress,hy0]
  have hkpos : 0 < k := by linarith
  have hkgt : 1 < k := lt_of_le_of_ne hk (Ne.symm hk1)
  have ht : 0 < 1/k^2 := div_pos (by norm_num) (sq_pos_of_pos hkpos)
  have ht1 : 1/k^2 < 1 := (div_lt_one (sq_pos_of_pos hkpos)).2 (by nlinarith)
  have hr : 0 < y/k := div_pos (lt_of_le_of_ne hy (Ne.symm hy0)) hkpos
  have hd := pole_spindle_stable_branch_domain (1/k^2) (y/k) ht ht1 hr
  dsimp only at hd
  simp only [poleSpindleCompressStable,poleSpindleCompress,hk1,hy0,ite_false]
  unfold poleSpindleInverseSquare poleCubicMiddle
  dsimp only
  rw [hd.2.2.2.2]
  split_ifs with h
  · exact (pole_spindle_factored_sqrt (y/k) poleSpindleP (poleInverseA3 (1/k^2))
      _ _ _ hr.le (ne_of_lt hd.1) (ne_of_gt hd.2.1) (ne_of_gt hd.2.2.2.1)).symm
  · rfl


/-- Cubic-angle evaluation from the two positive extremum magnitudes. -/
def poleCubicPoly (a b c d z : ℝ) : ℝ := a*z^3+b*z^2+c*z+d

def poleExtremaPoint (m n : ℝ) : ℂ := Complex.mk (m-n) (2*Real.sqrt (m*n))

theorem pole_extrema_point_norm (m n : ℝ) (hm : 0 < m) (hn : 0 < n) :
    ‖poleExtremaPoint m n‖ = m+n := by
  have hmn : 0 ≤ m*n := le_of_lt (mul_pos hm hn)
  have hs : (Real.sqrt (m*n))^2 = m*n := Real.sq_sqrt hmn
  have hsum : 0 ≤ m+n := by linarith
  have hsq : Complex.normSq (poleExtremaPoint m n) = (m+n)^2 := by
    simp only [poleExtremaPoint, Complex.normSq_apply]
    nlinarith
  rw [Complex.norm_def, hsq, Real.sqrt_sq hsum]

theorem pole_extrema_point_ne_zero (m n : ℝ) (hm : 0 < m) (hn : 0 < n) :
    poleExtremaPoint m n ≠ 0 := by
  intro h
  have hi : (poleExtremaPoint m n).im = 0 := by rw [h]; rfl
  simp [poleExtremaPoint] at hi
  have : 0 < Real.sqrt (m*n) := Real.sqrt_pos.2 (mul_pos hm hn)
  linarith

theorem pole_extrema_angle_invariant (m n : ℝ) (hm : 0 < m) (hn : 0 < n) :
    Real.cos (Complex.arg (poleExtremaPoint m n)) = (m-n)/(m+n) := by
  rw [Complex.cos_arg (pole_extrema_point_ne_zero m n hm hn)]
  rw [pole_extrema_point_norm m n hm hn]
  simp [poleExtremaPoint]

theorem pole_extrema_angle_range (m n : ℝ) (_hm : 0 < m) (_hn : 0 < n) :
    0 ≤ Complex.arg (poleExtremaPoint m n) ∧
      Complex.arg (poleExtremaPoint m n) ≤ Real.pi := by
  constructor
  · rw [Complex.arg_nonneg_iff]
    simp [poleExtremaPoint]
  · exact Complex.arg_le_pi _

theorem pole_extrema_angle_eq_arccos (m n : ℝ) (hm : 0 < m) (hn : 0 < n) :
    Real.arccos ((m-n)/(m+n)) = Complex.arg (poleExtremaPoint m n) := by
  have hs : 0 < m+n := by linarith
  have hratio : -1 ≤ (m-n)/(m+n) ∧ (m-n)/(m+n) ≤ 1 := by
    constructor
    · apply (le_div_iff₀ hs).2
      linarith
    · apply (div_le_iff₀ hs).2
      linarith
  calc
    Real.arccos ((m-n)/(m+n)) =
        Real.arccos (Real.cos (Complex.arg (poleExtremaPoint m n))) := by
          rw [pole_extrema_angle_invariant m n hm hn]
    _ = Complex.arg (poleExtremaPoint m n) := by
      exact Real.arccos_cos (pole_extrema_angle_range m n hm hn).1
        (pole_extrema_angle_range m n hm hn).2

theorem pole_cubic_upper_extremum_value
    (a b c d p delta hp : ℝ)
    (hcrit : 3*a*delta^2 + 2*(b+3*a*p)*delta + hp = 0)
    (hderiv : hp = 3*a*p^2+2*b*p+c) :
    poleCubicPoly a b c d (p+delta) =
      poleCubicPoly a b c d p + delta^2*(-2*a*delta-(b+3*a*p)) := by
  unfold poleCubicPoly at *
  linear_combination delta*hcrit - delta*hderiv

theorem pole_cubic_upper_extremum_positive_sum
    (a b c d p delta sd hp base : ℝ)
    (hbase : base = poleCubicPoly a b c d p)
    (hcrit : 3*a*delta^2 + 2*(b+3*a*p)*delta + hp = 0)
    (hderiv : hp = 3*a*p^2+2*b*p+c)
    (hfactor : -2*a*delta-(b+3*a*p) = (2*sd-(b+3*a*p))/3) :
    poleCubicPoly a b c d (p+delta) = base + delta^2*(2*sd-(b+3*a*p))/3 := by
  rw [pole_cubic_upper_extremum_value a b c d p delta hp hcrit hderiv, hbase,
    hfactor]
  ring

theorem pole_cubic_lower_extremum_value
    (a b c d sd z : ℝ)
    (hs : sd^2 = b^2-3*a*c)
    (hz : z = -c/(b+sd))
    (hden : b+sd ≠ 0) :
    poleCubicPoly a b c d z = d-z^2*(b+2*sd)/3 := by
  have hlinear : 3*a*z = sd-b := by
    rw [hz]
    field_simp
    nlinarith [hs]
  have hzrel : z*(b+sd)+c=0 := by rw [hz]; field_simp; ring
  unfold poleCubicPoly
  linear_combination z*hzrel + (z^2/3)*hlinear

/-- The derivative and value at the pole are evaluated without cancellation. -/
theorem pole_spindle_cubic_pole_value (t r : ℝ) :
    poleCubicPoly (poleInverseA3 t) (poleInverseA2 t r) (poleInverseA1 t r)
      (poleInverseA0 r) poleSpindleP =
      (1-t)*poleSpindleP^2*39*(poleSpindleP-1)^2 := by
  unfold poleCubicPoly poleInverseA3 poleInverseA2 poleInverseA1 poleInverseA0
    poleSpindleB poleSpindleA
  ring

theorem pole_spindle_cubic_pole_derivative (t r : ℝ) :
    3*poleInverseA3 t*poleSpindleP^2+2*poleInverseA2 t r*poleSpindleP+
      poleInverseA1 t r =
      (1+poleSpindleP)*(r^2-poleSpindleP) + (1-t)*poleSpindleP*(poleSpindleP-1)*
        (2*19+3*39*(poleSpindleP-1)) := by
  unfold poleInverseA3 poleInverseA2 poleInverseA1 poleSpindleB poleSpindleA
  ring

/-- Rationalization of the maximum location is exactly the same critical point. -/
theorem pole_cubic_upper_extremum_rationalization (a b c p sd : ℝ)
    (ha : a ≠ 0) (hs : sd^2=b^2-3*a*c) (hden : sd-(b+3*a*p) ≠ 0) :
    (3*a*p^2+2*b*p+c)/(sd-(b+3*a*p)) = (-(b+3*a*p)-sd)/(3*a) := by
  field_simp
  nlinarith [hs]

/-- Critical values determine the stable normalized cosine invariant. -/
theorem pole_cubic_extrema_invariant (a b c d sd : ℝ)
    (ha : a ≠ 0) (hs : sd^2=b^2-3*a*c) (hsd : sd ≠ 0) :
    let m := poleCubicPoly a b c d ((-b-sd)/(3*a))
    let n := -poleCubicPoly a b c d ((-b+sd)/(3*a))
    (m-n)/(m+n) = (2*b^3-9*a*b*c+27*a^2*d)/(2*sd^3) := by
  dsimp only
  have hmax : 27*a^2*poleCubicPoly a b c d ((-b-sd)/(3*a)) =
      2*b^3-9*a*b*c+27*a^2*d+2*sd^3 := by
    unfold poleCubicPoly
    field_simp
    linear_combination -81*sd*hs
  have hmin : 27*a^2*poleCubicPoly a b c d ((-b+sd)/(3*a)) =
      2*b^3-9*a*b*c+27*a^2*d-2*sd^3 := by
    unfold poleCubicPoly
    field_simp
    linear_combination 81*sd*hs
  have hsum : poleCubicPoly a b c d ((-b-sd)/(3*a)) -
      poleCubicPoly a b c d ((-b+sd)/(3*a)) = 4*sd^3/(27*a^2) := by
    field_simp
    linear_combination hmax-hmin
  have hdiff : poleCubicPoly a b c d ((-b-sd)/(3*a)) +
      poleCubicPoly a b c d ((-b+sd)/(3*a)) =
        2*(2*b^3-9*a*b*c+27*a^2*d)/(27*a^2) := by
    field_simp
    linear_combination hmax+hmin
  simp only [sub_neg_eq_add, ←sub_eq_add_neg]
  rw [hsum, hdiff]
  field_simp
  ring

/-- The normalized invariant is exactly that of the original monic cubic. -/
theorem pole_cubic_monic_invariant (a b c d sd : ℝ)
    (ha : a < 0) (hs : sd^2=b^2-3*a*c) (hsd : 0 < sd) :
    (-2*(b/a)^3+9*(b/a)*(c/a)-27*(d/a)) /
      (2*(Real.sqrt ((b/a)^2-3*(c/a)))^3) =
      (2*b^3-9*a*b*c+27*a^2*d)/(2*sd^3) := by
  have ha0 : a ≠ 0 := ne_of_lt ha
  have hs0 : sd ≠ 0 := ne_of_gt hsd
  have hroot : Real.sqrt ((b/a)^2-3*(c/a)) = -sd/a := by
    have hsq : (b/a)^2-3*(c/a) = (-sd/a)^2 := by
      field_simp
      nlinarith [hs]
    rw [hsq, Real.sqrt_sq (le_of_lt (div_pos_of_neg_of_neg (by linarith) ha))]
  rw [hroot]
  field_simp
  ring

/-- The implementation's separate square roots represent the same positive ordinate. -/
theorem pole_extrema_point_ordinate (m n : ℝ) (hm : 0 < m) :
    2*Real.sqrt m*Real.sqrt n = 2*Real.sqrt (m*n) := by
  rw [Real.sqrt_mul hm.le]
  ring

/-- The extrema-based principal angle selects exactly the original largest cubic root. -/
theorem pole_cubic_extrema_largest_eq (a b c d sd m n : ℝ)
    (ha : a < 0) (hs : sd^2=b^2-3*a*c) (hsd : 0 < sd)
    (hm : 0 < m) (hn : 0 < n)
    (hmdef : m=poleCubicPoly a b c d ((-b-sd)/(3*a)))
    (hndef : n= -poleCubicPoly a b c d ((-b+sd)/(3*a))) :
    (b+2*sd*Real.cos (Complex.arg (poleExtremaPoint m n)/3))/(-3*a) =
      poleCubicLargest (b/a) (c/a) (d/a) := by
  have ha0 : a ≠ 0 := ne_of_lt ha
  have hinvariant : (m-n)/(m+n) =
      (-2*(b/a)^3+9*(b/a)*(c/a)-27*(d/a)) /
        (2*(Real.sqrt ((b/a)^2-3*(c/a)))^3) := by
    rw [pole_cubic_monic_invariant a b c d sd ha hs hsd, hmdef, hndef]
    exact pole_cubic_extrema_invariant a b c d sd ha0 hs (ne_of_gt hsd)
  have hroot : Real.sqrt ((b/a)^2-3*(c/a)) = -sd/a := by
    have hsq : (b/a)^2-3*(c/a) = (-sd/a)^2 := by
      field_simp
      nlinarith [hs]
    rw [hsq, Real.sqrt_sq (le_of_lt (div_pos_of_neg_of_neg (by linarith) ha))]
  rw [←pole_extrema_angle_eq_arccos m n hm hn, hinvariant]
  unfold poleCubicLargest
  rw [hroot]
  field_simp
  ring

/-- The positive-sum maximum is the actual cubic value at the explicit upper critical point. -/
theorem pole_cubic_upper_extremum_evaluation (a b c d p sd : ℝ)
    (ha : a ≠ 0) (hs : sd^2=b^2-3*a*c) :
    let delta := (-(b+3*a*p)-sd)/(3*a)
    poleCubicPoly a b c d ((-b-sd)/(3*a)) =
      poleCubicPoly a b c d p + delta^2*(2*sd-(b+3*a*p))/3 := by
  dsimp only
  have he : (-b-sd)/(3*a) = p+ (-(b+3*a*p)-sd)/(3*a) := by field_simp; ring
  rw [he]
  apply pole_cubic_upper_extremum_positive_sum a b c d p
    ((-(b+3*a*p)-sd)/(3*a)) sd (3*a*p^2+2*b*p+c)
    (poleCubicPoly a b c d p) rfl ?_ rfl ?_
  · field_simp
    nlinarith [hs]
  · field_simp
    ring

end
end PerceptualGrade
