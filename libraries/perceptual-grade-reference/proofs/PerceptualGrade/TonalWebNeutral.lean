import PerceptualGrade.TonalWebHue

namespace PerceptualGrade
noncomputable section
open Set Filter Asymptotics
open scoped Topology

def webAngularDelta (δ : ℂ → ℝ) (τ : ℝ) (v : ℂ) : ℝ :=
  webS5Clamped (‖v‖/τ)*δ v

def webAngularCartesian (δ : ℂ → ℝ) (τ : ℝ) (v : ℂ) : ℂ :=
  Complex.exp (Complex.I*(webAngularDelta δ τ v : ℂ))*v

theorem web_s5_cubic_bound (t : ℝ) (ht : t ∈ Icc (0 : ℝ) 1) :
    |webS5 t| ≤ 10*t^3 := by
  rw [abs_of_nonneg (web_s5_unit_bounds t ht).1]
  have h0 : 0 ≤ t := ht.1
  have h1 : t ≤ 1 := ht.2
  have h : t^4*(6*t-15) ≤ 0 := mul_nonpos_of_nonneg_of_nonpos (by positivity) (by linarith)
  unfold webS5
  nlinarith only [h]

theorem web_angular_delta_remainder (δ : ℂ → ℝ) (τ K : ℝ)
    (hτ : 0 < τ) (_hK : 0 ≤ K) (hδ : ∀ v, |δ v| ≤ K)
    (v : ℂ) (hv : ‖v‖ < τ) :
    |webAngularDelta δ τ v| ≤ (10*K/τ^3)*‖v‖^3 := by
  have hx0 : 0 ≤ ‖v‖/τ := div_nonneg (norm_nonneg v) hτ.le
  have hx1 : ‖v‖/τ ≤ 1 := (div_le_one hτ).2 hv.le
  have hcl : webS5Clamped (‖v‖/τ) = webS5 (‖v‖/τ) := by
    by_cases h : ‖v‖/τ ≤ 0
    · have hz : ‖v‖/τ = 0 := le_antisymm h hx0
      simp [webS5Clamped, joined, hz, webS5]
    · simp [webS5Clamped, joined, h, hx1]
  unfold webAngularDelta
  rw [hcl, abs_mul]
  calc
    |webS5 (‖v‖/τ)| * |δ v| ≤ (10*(‖v‖/τ)^3)*K :=
      mul_le_mul (web_s5_cubic_bound _ ⟨hx0,hx1⟩) (hδ v) (abs_nonneg _) (by positivity)
    _ = (10*K/τ^3)*‖v‖^3 := by ring

/-- The fade kills directional angular variation to third order at gray. -/
theorem web_angular_delta_neutral_derivative (δ : ℂ → ℝ) (τ K : ℝ)
    (hτ : 0 < τ) (hK : 0 ≤ K) (hδ : ∀ v, |δ v| ≤ K) :
    HasFDerivAt (webAngularDelta δ τ) (0 : ℂ →L[ℝ] ℝ) 0 := by
  have hbig : webAngularDelta δ τ =O[𝓝 0] (fun v : ℂ => ‖v‖^3) := by
    apply IsBigO.of_bound (10*K/τ^3)
    filter_upwards [Metric.ball_mem_nhds (0 : ℂ) hτ] with v hv
    have hv' : ‖v‖ < τ := by simpa [Metric.mem_ball, dist_zero_right] using hv
    simpa only [Real.norm_eq_abs, abs_of_nonneg (pow_nonneg (norm_nonneg v) 3)] using
      web_angular_delta_remainder δ τ K hτ hK hδ v hv'
  have hs := hbig.trans_isLittleO (isLittleO_norm_pow_id (E' := ℂ) (show 1 < 3 by norm_num))
  apply HasFDerivAt.of_isLittleO
  have hz : webAngularDelta δ τ 0 = 0 := by simp [webAngularDelta, webS5Clamped, joined]
  simpa [hz] using hs

/-- Full a/b identity derivative of the actual exponential rotation lift. -/
theorem web_angular_cartesian_neutral_derivative (δ : ℂ → ℝ) (τ K : ℝ)
    (hτ : 0 < τ) (hK : 0 ≤ K) (hδ : ∀ v, |δ v| ≤ K) :
    HasFDerivAt (webAngularCartesian δ τ) (ContinuousLinearMap.id ℝ ℂ) 0 := by
  have ha := web_angular_delta_neutral_derivative δ τ K hτ hK hδ
  have hc := Complex.ofRealCLM.hasFDerivAt.comp 0 ha
  have he := (hc.const_mul Complex.I).cexp
  have h := he.mul (hasFDerivAt_id (𝕜 := ℝ) (0 : ℂ))
  change HasFDerivAt (fun v => Complex.exp (Complex.I*(webAngularDelta δ τ v : ℂ))*v) _ 0
  have hz : webAngularDelta δ τ 0 = 0 := by simp [webAngularDelta, webS5Clamped, joined]
  simpa [hz, Pi.mul_def, Function.comp_def] using h


/-- Zero-Adaptance specialization: compose three opponent-plane stages at fixed tone.
Hue coefficients may be bounded fields; each radial stage evaluates its own input.
The combined translated Warp uses `web_translated_neutral_derivative` instead. -/
theorem web_full_neutral_derivative (δ : ℂ → ℝ) (g1 g2 : ℂ → ℝ)
    (τθ τ1 τ2 Kθ K1 K2 : ℝ)
    (ht : 0 < τθ) (h1 : 0 < τ1) (h2 : 0 < τ2)
    (hk : 0 ≤ Kθ) (hk1 : 0 ≤ K1) (hk2 : 0 ≤ K2)
    (hd : ∀ v, |δ v| ≤ Kθ) (hg1 : ∀ v, |g1 v-1| ≤ K1) (hg2 : ∀ v, |g2 v-1| ≤ K2) :
    HasFDerivAt
      ((webRadialCartesian g2 τ2) ∘ (webRadialCartesian g1 τ1) ∘ (webAngularCartesian δ τθ))
      (ContinuousLinearMap.id ℝ ℂ) 0 := by
  have hA := web_angular_cartesian_neutral_derivative δ τθ Kθ ht hk hd
  have hR1 := web_radial_cartesian_neutral_derivative g1 τ1 K1 h1 hk1 hg1
  have hR2 := web_radial_cartesian_neutral_derivative g2 τ2 K2 h2 hk2 hg2
  have hz : webAngularCartesian δ τθ 0 = 0 := by simp [webAngularCartesian]
  have hz1 : webRadialCartesian g1 τ1 0 = 0 := by simp [webRadialCartesian]
  have hR1' : HasFDerivAt (webRadialCartesian g1 τ1) (ContinuousLinearMap.id ℝ ℂ)
      (webAngularCartesian δ τθ 0) := by rw [hz]; exact hR1
  have hB := hR1'.comp 0 hA
  have hR2' : HasFDerivAt (webRadialCartesian g2 τ2) (ContinuousLinearMap.id ℝ ℂ)
      ((webRadialCartesian g1 τ1 ∘ webAngularCartesian δ τθ) 0) := by
    simp only [Function.comp_apply, hz, hz1]; exact hR2
  have hC := hR2'.comp 0 hB
  simpa [Function.comp_assoc] using hC

end
end PerceptualGrade
