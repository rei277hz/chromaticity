import PerceptualGrade.Basic
import Mathlib.Analysis.Calculus.ContDiff.Deriv
import Mathlib.Topology.Piecewise

namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped Topology ContDiff

def joined (a : ℝ) (f g : ℝ → ℝ) (x : ℝ) : ℝ := if x ≤ a then f x else g x

theorem joined_derivative (a : ℝ) (f g f' g' : ℝ → ℝ)
    (hf : ∀ x, HasDerivAt f (f' x) x) (hg : ∀ x, HasDerivAt g (g' x) x)
    (hv : f a = g a) (hs : f' a = g' a) (x : ℝ) :
    HasDerivAt (joined a f g) (joined a f' g' x) x := by
  rcases lt_trichotomy x a with hx | hx | hx
  · have he : joined a f g =ᶠ[𝓝 x] f := by
      filter_upwards [Iio_mem_nhds hx] with y hy
      change y < a at hy
      simp [joined, le_of_lt hy]
    simpa [joined, le_of_lt hx] using (hf x).congr_of_eventuallyEq he
  · subst x
    have hl : HasDerivWithinAt (joined a f g) (f' a) (Iic a) a :=
      (hf a).hasDerivWithinAt.congr_of_mem (by intro y hy; change y ≤ a at hy; simp [joined, hy]) (by simp)
    have hr : HasDerivWithinAt (joined a f g) (f' a) (Ici a) a := by
      rw [hs]
      apply (hg a).hasDerivWithinAt.congr_of_mem _ (by simp)
      intro y hy
      by_cases he : y = a
      · subst y; simp [joined, hv]
      · simp [joined, show ¬y ≤ a by change a ≤ y at hy; intro h; exact he (le_antisymm h hy)]
    simpa [joined, Iic_union_Ici] using hl.union hr
  · have he : joined a f g =ᶠ[𝓝 x] g := by
      filter_upwards [Ioi_mem_nhds hx] with y hy
      change a < y at hy
      simp [joined, not_le_of_gt hy]
    simpa [joined, not_le_of_gt hx] using (hg x).congr_of_eventuallyEq he

theorem joined_c2 (a : ℝ) (f g : ℝ → ℝ) (hf : ContDiff ℝ 2 f) (hg : ContDiff ℝ 2 g)
    (hv : f a = g a) (hs : deriv f a = deriv g a)
    (hc : deriv (deriv f) a = deriv (deriv g) a) : ContDiff ℝ 2 (joined a f g) := by
  have df := joined_derivative a f g (deriv f) (deriv g)
    (fun x => (hf.differentiable (by norm_num) x).hasDerivAt)
    (fun x => (hg.differentiable (by norm_num) x).hasDerivAt) hv hs
  have deq : deriv (joined a f g) = joined a (deriv f) (deriv g) := funext fun x => (df x).deriv
  have dd := joined_derivative a (deriv f) (deriv g) (deriv (deriv f)) (deriv (deriv g))
    (fun x => hf.differentiable_deriv_two x |>.hasDerivAt)
    (fun x => hg.differentiable_deriv_two x |>.hasDerivAt) hs hc
  have ddeq : deriv (joined a (deriv f) (deriv g)) =
      joined a (deriv (deriv f)) (deriv (deriv g)) := funext fun x => (dd x).deriv
  have hfd : ContDiff ℝ 1 (deriv f) := hf.deriv' (n := 1)
  have hgd : ContDiff ℝ 1 (deriv g) := hg.deriv' (n := 1)
  have cont : Continuous (joined a (deriv (deriv f)) (deriv (deriv g))) := by
    apply Continuous.if _ (hfd.continuous_deriv (by norm_num))
      (hgd.continuous_deriv (by norm_num))
    intro x hx
    have : x = a := by simpa only [show {x : ℝ | x ≤ a} = Iic a from rfl, frontier_Iic, mem_singleton_iff] using hx
    subst x; exact hc
  rw [show (2 : ℕ∞ω) = 1+1 by norm_num, contDiff_succ_iff_deriv]
  refine ⟨fun x => (df x).differentiableAt, by simp, ?_⟩
  rw [deq, contDiff_one_iff_deriv, ddeq]
  exact ⟨fun x => (dd x).differentiableAt, cont⟩

def onsetPolynomial (t : ℝ) : ℝ := t^3*(6-8*t+3*t^2)
def onsetSlope (t : ℝ) : ℝ := 18*t^2-32*t^3+15*t^4
def onsetCurvature (t : ℝ) : ℝ := 36*t-96*t^2+60*t^3

theorem onset_derivative (t : ℝ) : HasDerivAt onsetPolynomial (onsetSlope t) t := by
  have h := ((hasDerivAt_id t).pow 3).mul
    ((((hasDerivAt_id t).const_mul 8).const_sub 6).add (((hasDerivAt_id t).pow 2).const_mul 3))
  convert h using 1
  · ext x; simp [onsetPolynomial]
  · simp [onsetSlope]; ring

theorem onset_second_derivative (t : ℝ) : HasDerivAt onsetSlope (onsetCurvature t) t := by
  have h := ((((hasDerivAt_id t).pow 2).const_mul 18).sub
    (((hasDerivAt_id t).pow 3).const_mul 32)).add (((hasDerivAt_id t).pow 4).const_mul 15)
  convert h using 1
  · rfl
  · simp [onsetCurvature]; ring

theorem onset_two_jets :
    onsetPolynomial 0 = 0 ∧ onsetSlope 0 = 0 ∧ onsetCurvature 0 = 0 ∧
    onsetPolynomial 1 = 1 ∧ onsetSlope 1 = 1 ∧ onsetCurvature 1 = 0 := by
  norm_num [onsetPolynomial, onsetSlope, onsetCurvature]

theorem onset_monotone_on_unit : MonotoneOn onsetPolynomial (Icc 0 1) := by
  apply monotoneOn_of_deriv_nonneg (convex_Icc _ _) (by unfold onsetPolynomial; fun_prop)
    (fun x _ => (onset_derivative x).differentiableAt.differentiableWithinAt)
  intro x hx
  rw [(onset_derivative x).deriv]
  have fact : onsetSlope x = x^2*(15*(x-1)^2+2*(1-x)+1) := by unfold onsetSlope; ring
  rw [fact]
  have : x ≤ 1 := (interior_subset hx).2
  positivity

def onsetProfile : ℝ → ℝ := joined 0 (fun _ => 0) (joined 1 onsetPolynomial id)

theorem onset_profile_c2 : ContDiff ℝ 2 onsetProfile := by
  have hp : ContDiff ℝ 2 onsetPolynomial := by unfold onsetPolynomial; fun_prop
  have d : deriv onsetPolynomial = onsetSlope := funext fun x => (onset_derivative x).deriv
  have dd : deriv onsetSlope = onsetCurvature := funext fun x => (onset_second_derivative x).deriv
  have inner : ContDiff ℝ 2 (joined 1 onsetPolynomial id) := by
    apply joined_c2 _ _ _ hp contDiff_id <;> norm_num [d, dd, onsetPolynomial, onsetSlope, onsetCurvature]
  apply joined_c2 _ _ _ contDiff_const inner
  · simp [joined, onsetPolynomial]
  · have hi := joined_derivative 1 onsetPolynomial id onsetSlope (fun _ => 1)
      onset_derivative (fun x => hasDerivAt_id x) (by norm_num [onsetPolynomial])
      (by norm_num [onsetSlope]) 0
    simp [hi.deriv, joined, onsetSlope]
  · have deq : deriv (joined 1 onsetPolynomial id) = joined 1 onsetSlope (fun _ => 1) := by
      funext x
      exact (joined_derivative 1 onsetPolynomial id onsetSlope (fun _ => 1)
        onset_derivative (fun x => hasDerivAt_id x) (by norm_num [onsetPolynomial])
        (by norm_num [onsetSlope]) x).deriv
    rw [deq]
    have hi := joined_derivative 1 onsetSlope (fun _ => 1) onsetCurvature (fun _ => 0)
      onset_second_derivative (fun x => hasDerivAt_const x 1) (by norm_num [onsetSlope])
      (by norm_num [onsetCurvature]) 0
    simp [hi.deriv, joined, onsetCurvature]

theorem onset_unit_bounds (t : ℝ) (ht : t ∈ Icc 0 1) :
    0 ≤ onsetPolynomial t ∧ onsetPolynomial t ≤ 1 := by
  have h := onset_monotone_on_unit
  have h0 := h (by simp : (0:ℝ) ∈ Icc 0 1) ht ht.1
  have h1 := h ht (by simp : (1:ℝ) ∈ Icc 0 1) ht.2
  norm_num [onsetPolynomial] at h0 h1
  exact ⟨h0, h1⟩

theorem nits_floor_c2 (lower : ℝ) :
    ContDiff ℝ 2 (fun x => lower+onsetProfile (x-lower)) := by
  exact contDiff_const.add (onset_profile_c2.comp (contDiff_id.sub contDiff_const))

theorem nits_cap_c2 (upper : ℝ) :
    ContDiff ℝ 2 (fun x => upper-onsetProfile (upper-x)) := by
  exact contDiff_const.sub (onset_profile_c2.comp (contDiff_const.sub contDiff_id))

theorem fit_width_positive (fit : ℝ) : 0 < (1/20 : ℝ)*Real.rpow 2 (-fit) := by
  exact mul_pos (by norm_num) (Real.rpow_pos_of_pos (by norm_num) _)

def responseCompression (FL C : ℝ) : ℝ :=
    400*(FL*C)^((21/50 : ℝ))/(27.13+(FL*C)^((21/50 : ℝ)))
def responseInverse (FL r : ℝ) : ℝ := (27.13*r/(400-r))^((50/21 : ℝ))/FL

theorem compression_domain (FL C : ℝ) (hf : 0 < FL) (hc : 0 < C) :
    0 < responseCompression FL C ∧ responseCompression FL C < 400 := by
  have hp : 0 < (FL*C)^((21/50 : ℝ)) := Real.rpow_pos_of_pos (mul_pos hf hc) _
  unfold responseCompression
  refine ⟨by positivity, (div_lt_iff₀ (by positivity)).2 ?_⟩
  linarith

theorem response_inverse_monotone (FL r q : ℝ) (hf : 0 < FL) (hr : 0 ≤ r)
    (h : r ≤ q) (hq : q < 400) : responseInverse FL r ≤ responseInverse FL q := by
  have hden : 0 < 400-r := by linarith
  have hdenq : 0 < 400-q := by linarith
  have hrat : 27.13*r/(400-r) ≤ 27.13*q/(400-q) := by
    apply (div_le_div_iff₀ hden hdenq).2
    nlinarith
  unfold responseInverse
  apply div_le_div_of_nonneg_right _ (le_of_lt hf)
  exact Real.rpow_le_rpow (by positivity) hrat (by norm_num)

theorem compression_inverse (FL C : ℝ) (hf : 0 < FL) (hc : 0 < C) :
    responseInverse FL (responseCompression FL C) = C := by
  have hp : 0 < (FL*C)^((21/50 : ℝ)) := Real.rpow_pos_of_pos (mul_pos hf hc) _
  have hd : 0 < 27.13+(FL*C)^((21/50 : ℝ)) := by positivity
  have he : 27.13*responseCompression FL C/(400-responseCompression FL C) =
      (FL*C)^((21/50 : ℝ)) := by
    unfold responseCompression
    field_simp
    ring
  unfold responseInverse
  rw [he, ← Real.rpow_mul (le_of_lt (mul_pos hf hc))]
  norm_num
  field_simp

theorem bounded_response_inverse (FL C r : ℝ) (hf : 0 < FL) (hc : 0 < C)
    (hr : 0 ≤ r) (hcap : r ≤ responseCompression FL C) : responseInverse FL r ≤ C := by
  have h := response_inverse_monotone FL r (responseCompression FL C) hf hr hcap
    (compression_domain FL C hf hc).2
  simpa only [compression_inverse FL C hf hc] using h

theorem scaled_energy_geometry (s gamma E C : ℝ) (hs : 0 < s) (hc : 0 ≤ C) :
    (Real.sqrt (s^(2*gamma)*|E|+66*s*C))^2 = s^(2*gamma)*|E|+66*s*C := by
  apply Real.sq_sqrt
  positivity

theorem output_row_bound (a b c x y z S L : ℝ)
    (hx : |x| ≤ S) (hy : |y| ≤ S) (hz : |z| ≤ S)
    (hl : |a|+|b|+|c| ≤ L) (hs : 0 ≤ S) : |a*x+b*y+c*z| ≤ S*L := by
  have h1 := abs_add_le (a*x+b*y) (c*z)
  have h2 := abs_add_le (a*x) (b*y)
  simp only [abs_mul] at h1 h2
  have hx' := mul_le_mul_of_nonneg_left hx (abs_nonneg a)
  have hy' := mul_le_mul_of_nonneg_left hy (abs_nonneg b)
  have hz' := mul_le_mul_of_nonneg_left hz (abs_nonneg c)
  have hl' := mul_le_mul_of_nonneg_left hl hs
  nlinarith

theorem source_relative_output_equivalent (a b c x y z dx dy dz : ℝ) :
    a*(x+dx)+b*(y+dy)+c*(z+dz) = (a*x+b*y+c*z)+(a*dx+b*dy+c*dz) := by ring

end
end PerceptualGrade
