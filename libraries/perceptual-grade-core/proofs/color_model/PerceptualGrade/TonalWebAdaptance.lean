import PerceptualGrade.TonalWebNeutral

/- Generic final-scale facts and historical fixed-H Adaptance translation
   algebra. The translated composition and its old envelope below are retained
   as legacy results; they are not the current selective cone-derived operator.
   See SelectiveAdaptance for the current response map and Reach mask. Neither
   construction is claimed globally injective after input-dependent gating. -/
namespace PerceptualGrade
noncomputable section
open Filter Asymptotics
open scoped Topology

/-- Historical translation: invert an absolute target before the source web. -/
theorem web_combined_target (target offset scale : ℝ) (hs : scale ≠ 0) :
    scale * ((target / scale - offset) + offset) = target := by
  field_simp
  ring

/-- Historical translation: relative controls follow a fixed center offset. -/
theorem web_corner_follows_center (source offset delta scale : ℝ) :
    scale * (source + offset + delta) - scale * (source + offset) = scale * delta := by
  ring

/-- Historical translation: divide the neutral target by its offset weight. -/
theorem web_center_target (target weight : ℝ) (hw : weight ≠ 0) :
    (target / weight) * weight = target := by
  exact div_mul_cancel₀ target hw

/-- Final scale preserves physical signed saturation after Adaptance. -/
theorem web_combined_signed_scale (scale J C E : ℝ) (hs : 0 < scale)
    (he : E = J * |J|) :
    75*(scale*C)/|scale*J| = 75*C/|J| ∧
    scale^2*E = (scale*J)*|scale*J| := by
  exact ⟨(web_signed_saturation_scale scale J C E hs).1,
    (web_signed_saturation_scale scale J C E hs).2.2 he⟩

/-- The scale ratio, including its neutral extension, approaches one uniformly. -/
def webScaleField (g : ℂ → ℝ) (τ : ℝ) (v : ℂ) : ℝ :=
  g v + (1-g v)*webToe τ ‖v‖

theorem web_scale_field_neutral_derivative (g : ℂ → ℝ) (τ K : ℝ)
    (_ht : 0 < τ) (hk : 0 ≤ K) (hg : ∀ v, |g v-1| ≤ K) :
    HasFDerivAt (webScaleField g τ) (0 : ℂ →L[ℝ] ℝ) 0 := by
  have hb : (fun v => webScaleField g τ v-1) =O[𝓝 0] (fun v : ℂ => ‖v‖^4) := by
    apply IsBigO.of_bound (K/τ^4)
    filter_upwards [] with v
    have he : webScaleField g τ v-1 = (1-g v)*(webToe τ ‖v‖-1) := by
      unfold webScaleField; ring
    rw [he, Real.norm_eq_abs, abs_mul, abs_sub_comm 1 (g v)]
    calc
      |g v-1| * |webToe τ ‖v‖-1| ≤ K*(‖v‖/τ)^4 :=
        mul_le_mul (hg v) (web_toe_error_bound τ ‖v‖) (abs_nonneg _) hk
      _ = (K/τ^4)*‖‖v‖^4‖ := by
        rw [Real.norm_eq_abs, abs_of_nonneg (by positivity : 0 ≤ ‖v‖^4)]
        ring
  have hs := hb.trans_isLittleO (isLittleO_norm_pow_id (E' := ℂ) (show 1 < 4 by norm_num))
  apply HasFDerivAt.of_isLittleO
  have hz : webScaleField g τ 0 = 1 := by norm_num [webScaleField, webToe, webToeBase]
  simpa [hz] using hs

/-- Legacy fixed-H Adaptance envelope expressed in squared chroma units. -/
def webAdaptanceFactor (H strength r : ℝ) : ℝ :=
  (H/100) * (strength*(1+r/3600)) / (1+(1-3*strength/4)*r/900)

def webAdaptanceOffset (H strength : ℝ) (A v : ℂ) : ℂ :=
  webAdaptanceFactor H strength (v.re^2+v.im^2) • A

/-- The legacy chroma-squared envelope has zero differential at neutral. -/
theorem web_adaptance_offset_neutral_derivative (H strength : ℝ) (A : ℂ) :
    HasFDerivAt (webAdaptanceOffset H strength A) (0 : ℂ →L[ℝ] ℂ) 0 := by
  have hr := Complex.reCLM.hasFDerivAt (x := (0 : ℂ))
  have hi := Complex.imCLM.hasFDerivAt (x := (0 : ℂ))
  have hn : HasFDerivAt (fun v : ℂ => v.re^2+v.im^2) (0 : ℂ →L[ℝ] ℝ) 0 := by
    convert (hr.pow 2).add (hi.pow 2) using 1
    · rfl
    · simp
  have hf : HasDerivAt (webAdaptanceFactor H strength)
      ((H/100)*strength/3600-(H/100)*strength*(1-3*strength/4)/900) 0 := by
    have hd := hasDerivAt_id (0 : ℝ)
    have hu := (((hd.div_const 3600).const_add 1).const_mul strength).const_mul (H/100)
    have hv := (((hd.const_mul (1-3*strength/4)).div_const 900).const_add 1)
    convert hu.div hv (by norm_num) using 1
    · rfl
    · norm_num; ring
  have hf' := hf.hasFDerivAt
  have hf'' : HasFDerivAt (webAdaptanceFactor H strength)
      (ContinuousLinearMap.toSpanSingleton ℝ
        ((H/100)*strength/3600-(H/100)*strength*(1-3*strength/4)/900))
      ((0 : ℂ).re^2+(0 : ℂ).im^2) := by simpa using hf'
  have hc := hf''.comp 0 hn
  have ho := hc.smul_const A
  convert ho using 1
  · rfl
  · simp

/-- Historical translation's identity derivative at neutral. The offset may vary with input,
but its differential must vanish at neutral, as for the chroma-squared envelope.
The scale samples the pre-offset web result, never the translated radius. -/
theorem web_translated_neutral_derivative (W D : ℂ → ℂ) (g : ℂ → ℝ)
    (τ K : ℝ) (ht : 0 < τ) (hk : 0 ≤ K)
    (hg : ∀ v, |g v-1| ≤ K) (hw0 : W 0 = 0)
    (hw : HasFDerivAt W (ContinuousLinearMap.id ℝ ℂ) 0)
    (hd : HasFDerivAt D (0 : ℂ →L[ℝ] ℂ) 0) :
    HasFDerivAt (fun v => webScaleField g τ (W v) • (W v + D v))
      (ContinuousLinearMap.id ℝ ℂ) 0 := by
  have hs := web_scale_field_neutral_derivative g τ K ht hk hg
  have hs' : HasFDerivAt (webScaleField g τ) (0 : ℂ →L[ℝ] ℝ) (W 0) := by
    rw [hw0]; exact hs
  have h := (hs'.comp 0 hw).smul (hw.add hd)
  have hz : webScaleField g τ 0 = 1 := by norm_num [webScaleField, webToe, webToeBase]
  convert h using 1
  · rfl
  · simp [hw0, hz]



end
end PerceptualGrade
