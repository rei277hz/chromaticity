import PerceptualGrade.ContinuousGuard
import PerceptualGrade.CartesianNeutral

/- Exact-real scalar components of the reference tonal web. These results do not
   assert invertibility of tone-dependent grading or of export projection. -/
namespace PerceptualGrade
noncomputable section
open Set
open scoped ContDiff

def webS5 (t : ℝ) : ℝ := 6*t^5-15*t^4+10*t^3
def webS5Slope (t : ℝ) : ℝ := 30*t^2*(1-t)^2
def webS5Curvature (t : ℝ) : ℝ := 60*t*(1-t)*(1-2*t)

theorem web_s5_derivative (t : ℝ) : HasDerivAt webS5 (webS5Slope t) t := by
  have h := ((((hasDerivAt_id t).pow 5).const_mul 6).sub
    (((hasDerivAt_id t).pow 4).const_mul 15)).add (((hasDerivAt_id t).pow 3).const_mul 10)
  convert h using 1
  · rfl
  · simp [webS5Slope]; ring

theorem web_s5_second_derivative (t : ℝ) :
    HasDerivAt webS5Slope (webS5Curvature t) t := by
  have h := (((hasDerivAt_id t).pow 2).const_mul 30).mul
    (((hasDerivAt_id t).const_sub 1).pow 2)
  convert h using 1
  · rfl
  · simp [webS5Curvature]; ring

theorem web_s5_endpoint_jets :
    webS5 0 = 0 ∧ webS5 1 = 1 ∧ webS5Slope 0 = 0 ∧ webS5Slope 1 = 0 ∧
    webS5Curvature 0 = 0 ∧ webS5Curvature 1 = 0 := by
  norm_num [webS5, webS5Slope, webS5Curvature]

theorem web_s5_monotone : Monotone webS5 := by
  apply monotone_of_deriv_nonneg (fun t => (web_s5_derivative t).differentiableAt)
  intro t
  rw [(web_s5_derivative t).deriv]
  unfold webS5Slope
  positivity

theorem web_s5_unit_bounds (t : ℝ) (ht : t ∈ Icc (0 : ℝ) 1) :
    0 ≤ webS5 t ∧ webS5 t ≤ 1 := by
  have h0 := web_s5_monotone ht.1
  have h1 := web_s5_monotone ht.2
  norm_num [webS5] at h0 h1
  exact ⟨h0, h1⟩

def webBlend (a b t : ℝ) : ℝ := a+(b-a)*webS5 t

theorem web_blend_anchors (a b : ℝ) :
    webBlend a b 0 = a ∧ webBlend a b 1 = b := by
  norm_num [webBlend, webS5]

theorem web_blend_reset (a t : ℝ) : webBlend a a t = a := by
  simp [webBlend]

def webS5Clamped : ℝ → ℝ := joined 0 (fun _ => 0) (joined 1 webS5 (fun _ => 1))

theorem web_s5_clamped_c2 : ContDiff ℝ 2 webS5Clamped := by
  have hp : ContDiff ℝ 2 webS5 := by unfold webS5; fun_prop
  have hd : deriv webS5 = webS5Slope := funext fun t => (web_s5_derivative t).deriv
  have hdd : deriv webS5Slope = webS5Curvature := funext fun t => (web_s5_second_derivative t).deriv
  have hj : ContDiff ℝ 2 (joined 1 webS5 (fun _ => 1)) := by
    apply joined_c2 _ _ _ hp (by fun_prop)
    · norm_num [webS5]
    · rw [hd]; norm_num [webS5Slope]
    · rw [hd, hdd]; norm_num [webS5Curvature]
  have hjd : deriv (joined 1 webS5 (fun _ => 1)) = joined 1 webS5Slope (fun _ => 0) := by
    funext t
    exact (joined_derivative 1 webS5 (fun _ => 1) webS5Slope (fun _ => 0)
      web_s5_derivative (fun x => hasDerivAt_const x 1)
      (by norm_num [webS5]) (by norm_num [webS5Slope]) t).deriv
  have hjdd : deriv (joined 1 webS5Slope (fun _ => 0)) = joined 1 webS5Curvature (fun _ => 0) := by
    funext t
    exact (joined_derivative 1 webS5Slope (fun _ => 0) webS5Curvature (fun _ => 0)
      web_s5_second_derivative (fun x => hasDerivAt_const x 0)
      (by norm_num [webS5Slope]) (by norm_num [webS5Curvature]) t).deriv
  apply joined_c2 _ _ _ (by fun_prop) hj
  · norm_num [joined, webS5]
  · rw [hjd]; norm_num [joined, webS5Slope]
  · rw [hjd, hjdd]; norm_num [joined, webS5Curvature]

def webToeBase (τ C : ℝ) : ℝ := 1+(C/τ)^4
def webToe (τ C : ℝ) : ℝ := (webToeBase τ C)^((-1/4 : ℝ))
def webRadial (g τ C : ℝ) : ℝ := C*(g+(1-g)*webToe τ C)
def webRadialSlope (g τ C : ℝ) : ℝ := g+(1-g)*(webToeBase τ C)^((-5/4 : ℝ))
def webRadialCalibration (R T τ : ℝ) : ℝ := (T/R-webToe τ R)/(1-webToe τ R)

theorem web_toe_base_positive (τ C : ℝ) : 0 < webToeBase τ C := by
  unfold webToeBase
  positivity

theorem web_toe_bounds (τ C : ℝ) : 0 < webToe τ C ∧ webToe τ C ≤ 1 := by
  constructor
  · exact Real.rpow_pos_of_pos (web_toe_base_positive τ C) _
  · apply Real.rpow_le_one_of_one_le_of_nonpos
    · unfold webToeBase; nlinarith [pow_nonneg (sq_nonneg (C/τ)) 2]
    · norm_num

theorem web_toe_derivative (τ C : ℝ) :
    HasDerivAt (webToe τ) (-(C/τ)^3/τ*(webToeBase τ C)^((-5/4 : ℝ))) C := by
  have hb := (((hasDerivAt_id C).div_const τ).pow 4).const_add 1
  have h := hb.rpow_const (Or.inl (ne_of_gt (web_toe_base_positive τ C))) (p := (-1/4 : ℝ))
  convert h using 1
  · rfl
  · norm_num [webToeBase]; ring

theorem web_radial_derivative (g τ C : ℝ) :
    HasDerivAt (webRadial g τ) (webRadialSlope g τ C) C := by
  have hp := web_toe_base_positive τ C
  have he : webToe τ C = (webToeBase τ C)^((-5/4 : ℝ))*webToeBase τ C := by
    have h := Real.rpow_add hp (-5/4 : ℝ) 1
    convert h using 1 <;> norm_num [webToe]
  have h := (hasDerivAt_id C).mul (((web_toe_derivative τ C).const_mul (1-g)).const_add g)
  convert h using 1
  · rfl
  · simp only [id_eq, one_mul]
    rw [he]
    unfold webRadialSlope webToeBase
    ring

theorem web_radial_slope_positive (g τ C : ℝ) (hg : 0 < g) :
    0 < webRadialSlope g τ C := by
  have hp : 0 < (webToeBase τ C)^((-5/4 : ℝ)) :=
    Real.rpow_pos_of_pos (web_toe_base_positive τ C) _
  have hle : (webToeBase τ C)^((-5/4 : ℝ)) ≤ 1 := by
    apply Real.rpow_le_one_of_one_le_of_nonpos
    · unfold webToeBase; nlinarith [pow_nonneg (sq_nonneg (C/τ)) 2]
    · norm_num
  unfold webRadialSlope
  by_cases hg1 : g ≤ 1
  · nlinarith [mul_nonneg (sub_nonneg.mpr hg1) (le_of_lt hp)]
  · nlinarith [mul_nonneg (show 0 ≤ g-1 by linarith) (show 0 ≤ 1-(webToeBase τ C)^((-5/4 : ℝ)) by linarith)]

theorem web_radial_strict_mono (g τ : ℝ) (hg : 0 < g) : StrictMono (webRadial g τ) := by
  apply strictMono_of_deriv_pos
  intro C
  rw [(web_radial_derivative g τ C).deriv]
  exact web_radial_slope_positive g τ C hg

theorem web_radial_reset (τ C : ℝ) : webRadial 1 τ C = C := by
  simp [webRadial]

theorem web_radial_zero (g τ : ℝ) : webRadial g τ 0 = 0 := by
  simp [webRadial]

theorem web_radial_neutral_slope (g τ : ℝ) : webRadialSlope g τ 0 = 1 := by
  norm_num [webRadialSlope, webToeBase]

theorem web_radial_calibrates (R T τ : ℝ) (hR : R ≠ 0) (hA : webToe τ R ≠ 1) :
    webRadial (webRadialCalibration R T τ) τ R = T := by
  unfold webRadial webRadialCalibration
  have hden : 1-webToe τ R ≠ 0 := sub_ne_zero.mpr (Ne.symm hA)
  field_simp
  ring

theorem web_radial_calibration_positive (R T τ : ℝ)
    (hA : webToe τ R < 1) (hT : webToe τ R < T/R) :
    0 < webRadialCalibration R T τ := by
  exact div_pos (sub_pos.mpr hT) (sub_pos.mpr hA)

theorem web_radial_c2 (g τ : ℝ) : ContDiff ℝ 2 (webRadial g τ) := by
  have htoe : ContDiff ℝ 2 (webToe τ) := by
    apply ContDiff.rpow_const_of_ne
    · unfold webToeBase; fun_prop
    · intro C; exact ne_of_gt (web_toe_base_positive τ C)
  exact contDiff_id.mul (contDiff_const.add (contDiff_const.mul htoe))

/-- Signed J_A energy and C are homogeneous under the web's saturation scale. -/
theorem web_signed_saturation_scale (scale J C E : ℝ) (hscale : 0 < scale) :
    75*(scale*C)/|scale*J| = 75*C/|J| ∧
      (scale*J)*|scale*J| = scale^2*(J*|J|) ∧
      (E = J*|J| → scale^2*E = (scale*J)*|scale*J|) := by
  have ha : |scale| = scale := abs_of_pos hscale
  rw [abs_mul, ha]
  refine ⟨?_, ?_, ?_⟩
  · field_simp
  · ring
  · intro he; rw [he]; ring

/-- The actual toe has a uniform fourth-order approach to one. -/
theorem web_toe_error_bound (τ C : ℝ) : |webToe τ C-1| ≤ (C/τ)^4 := by
  have hb : 1 ≤ webToeBase τ C := by unfold webToeBase; nlinarith [pow_nonneg (sq_nonneg (C/τ)) 2]
  have hp := web_toe_base_positive τ C
  have ht := web_toe_bounds τ C
  have he : webToe τ C*webToeBase τ C = (webToeBase τ C)^((3/4 : ℝ)) := by
    have h := Real.rpow_add hp (-1/4 : ℝ) 1
    norm_num at h
    norm_num [webToe] at ⊢
    exact h.symm
  have hl : 1 ≤ webToe τ C*webToeBase τ C := by
    rw [he]
    exact Real.one_le_rpow hb (by norm_num)
  rw [abs_of_nonpos (by linarith [ht.2])]
  have hm := mul_le_mul_of_nonneg_right ht.2 (show 0 ≤ (C/τ)^4 by positivity)
  unfold webToeBase at hl
  nlinarith

variable {V : Type*} [NormedAddCommGroup V] [NormedSpace ℝ V]

def webRadialCartesian (g : V → ℝ) (τ : ℝ) (v : V) : V :=
  (g v+(1-g v)*webToe τ ‖v‖) • v

/-- Uniformity in hue is explicit: g need not have a limit or derivative at gray. -/
theorem web_radial_cartesian_remainder (g : V → ℝ) (τ K : ℝ)
    (hτ : 0 < τ) (hK : 0 ≤ K) (hg : ∀ v, |g v-1| ≤ K)
    (v : V) (hv : ‖v‖ < τ) :
    ‖webRadialCartesian g τ v-v‖ ≤ (K/τ^2)*‖v‖^3 := by
  have hx : 0 ≤ ‖v‖/τ := div_nonneg (norm_nonneg v) hτ.le
  have hx1 : ‖v‖/τ ≤ 1 := (div_le_one hτ).2 hv.le
  have hpow : (‖v‖/τ)^4 ≤ (‖v‖/τ)^2 := by
    have hsq : (‖v‖/τ)^2 ≤ 1 := by nlinarith
    nlinarith [sq_nonneg (‖v‖/τ), mul_nonneg (sq_nonneg (‖v‖/τ)) (sub_nonneg.mpr hsq)]
  calc
    ‖webRadialCartesian g τ v-v‖ = |g v-1| *|webToe τ ‖v‖-1| *‖v‖ := by
      unfold webRadialCartesian
      rw [show (g v+(1-g v)*webToe τ ‖v‖) • v-v =
        ((1-g v)*(webToe τ ‖v‖-1)) • v by
          rw [show (1-g v)*(webToe τ ‖v‖-1) = g v+(1-g v)*webToe τ ‖v‖-1 by ring, sub_smul, one_smul]]
      rw [norm_smul, Real.norm_eq_abs, abs_mul, abs_sub_comm 1 (g v)]
    _ ≤ K*(‖v‖/τ)^4*‖v‖ := by
      apply mul_le_mul_of_nonneg_right _ (norm_nonneg v)
      exact mul_le_mul (hg v) (web_toe_error_bound τ ‖v‖) (abs_nonneg _) hK
    _ ≤ K*(‖v‖/τ)^2*‖v‖ := mul_le_mul_of_nonneg_right (mul_le_mul_of_nonneg_left hpow hK) (norm_nonneg v)
    _ = (K/τ^2)*‖v‖^3 := by ring

theorem web_radial_cartesian_neutral_derivative (g : V → ℝ) (τ K : ℝ)
    (hτ : 0 < τ) (hK : 0 ≤ K) (hg : ∀ v, |g v-1| ≤ K) :
    HasFDerivAt (webRadialCartesian g τ) (ContinuousLinearMap.id ℝ V) 0 := by
  apply cartesian_neutral_of_cubic_bound _ (K/τ^2) τ hτ
  · simp [webRadialCartesian]
  · exact fun v hv => web_radial_cartesian_remainder g τ K hτ hK hg v hv

/-- Destination-angle radial evaluation cancels the angular/radial coupling.
The partials are with tone held fixed before Adaptance translation. This theorem
does not cover the translated state followed by a scale selected before translation,
nor the full tone-dependent grade. -/
theorem web_staged_jacobian_positive (Fr Fh ψr ψh : ℝ)
    (hF : 0 < Fr) (hψ : 0 < ψh) :
    0 < (Fr+Fh*ψr)*ψh-(Fh*ψh)*ψr := by
  have he : (Fr+Fh*ψr)*ψh-(Fh*ψh)*ψr = Fr*ψh := by ring
  rw [he]
  exact mul_pos hF hψ

theorem web_angular_fade_derivative_positive (w d : ℝ)
    (hw0 : 0 ≤ w) (hw1 : w ≤ 1) (hd : 0 < d) : 0 < 1+w*(d-1) := by
  by_cases hw : w = 0
  · simp [hw]
  · have hp : 0 < w := lt_of_le_of_ne hw0 (Ne.symm hw)
    nlinarith [mul_pos hp hd]

end
end PerceptualGrade
