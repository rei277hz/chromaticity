import PerceptualGrade.Tone

/- Exact-real integrated Tone and Unified Chroma in signed appearance coordinates. -/
namespace PerceptualGrade
noncomputable section
open Set

def unifiedRadial (a b k x : ℝ) : ℝ :=
  if k = 0 then b*x else x*(a*k+b*x)/(k+x)

theorem unified_radial_zero (a b k : ℝ) : unifiedRadial a b k 0 = 0 := by
  by_cases hk : k = 0 <;> simp [unifiedRadial, hk]

theorem unified_radial_strict_mono (a b k : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hk : 0 ≤ k) :
    StrictMonoOn (unifiedRadial a b k) (Ici 0) := by
  intro x hx y hy hxy
  change 0 ≤ x at hx
  change 0 ≤ y at hy
  by_cases hz : k = 0
  · simpa [unifiedRadial, hz] using mul_lt_mul_of_pos_left hxy hb
  · have hp : 0 < k := lt_of_le_of_ne hk (Ne.symm hz)
    simp only [unifiedRadial, hz, ite_false]
    apply (div_lt_div_iff₀ (by positivity : 0 < k+x) (by positivity : 0 < k+y)).2
    have hf : 0 < (y-x)*(a*k^2+b*k*(x+y)+b*x*y) := by positivity
    linarith only [hf, show y*(a*k+b*y)*(k+x)-x*(a*k+b*x)*(k+y) =
      (y-x)*(a*k^2+b*k*(x+y)+b*x*y) by ring]

theorem unified_radial_lower (a b k x : ℝ) (hk : 0 ≤ k) (hx : 0 ≤ x) :
    min a b*x ≤ unifiedRadial a b k x := by
  by_cases hz : k = 0
  · simpa [unifiedRadial, hz] using mul_le_mul_of_nonneg_right (min_le_right a b) hx
  · have hp : 0 < k := lt_of_le_of_ne hk (Ne.symm hz)
    simp only [unifiedRadial, hz, ite_false]
    apply (le_div_iff₀ (by positivity : 0 < k+x)).2
    have hl := mul_le_mul_of_nonneg_right (min_le_left a b) hk
    have hr := mul_le_mul_of_nonneg_right (min_le_right a b) hx
    calc
      min a b*x*(k+x) = x*(min a b*k+min a b*x) := by ring
      _ ≤ x*(a*k+b*x) := mul_le_mul_of_nonneg_left (add_le_add hl hr) hx

theorem unified_scalar_inverse_exists (f : ℝ → ℝ) (m y : ℝ)
    (hm : 0 < m) (hy : 0 ≤ y) (hz : f 0 = 0)
    (hs : StrictMonoOn f (Ici 0)) (hc : ContinuousOn f (Ici 0))
    (hl : ∀ x, 0 ≤ x → m*x ≤ f x) : ∃! x, 0 ≤ x ∧ f x = y := by
  have hu : 0 ≤ y/m := div_nonneg hy hm.le
  have hupper : y ≤ f (y/m) := by
    calc
      y = m*(y/m) := by field_simp
      _ ≤ f (y/m) := hl _ hu
  have hsub : Icc (0:ℝ) (y/m) ⊆ Ici 0 := fun _ hx => hx.1
  obtain ⟨x, hx, he⟩ := intermediate_value_Icc hu (hc.mono hsub)
    (show y ∈ Icc (f 0) (f (y/m)) from ⟨hz.symm ▸ hy, hupper⟩)
  exact ⟨x, ⟨hx.1, he⟩, fun z hz' => hs.injOn hz'.1 hx.1 (hz'.2.trans he.symm)⟩

theorem unified_radial_inverse_exists (a b k y : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hk : 0 ≤ k) (hy : 0 ≤ y) :
    ∃! x, 0 ≤ x ∧ unifiedRadial a b k x = y := by
  apply unified_scalar_inverse_exists _ (min a b) y (lt_min ha hb) hy
    (unified_radial_zero a b k) (unified_radial_strict_mono a b k ha hb hk)
  · by_cases hz : k = 0
    · have he : unifiedRadial a b k = fun x : ℝ => b*x := by
        funext x
        simp [unifiedRadial, hz]
      rw [he]
      exact (continuous_const.mul continuous_id : Continuous fun x : ℝ => b*x).continuousOn
    · have hp : 0 < k := lt_of_le_of_ne hk (Ne.symm hz)
      have he : unifiedRadial a b k = fun x : ℝ => x*(a*k+b*x)/(k+x) := by
        funext x
        simp [unifiedRadial, hz]
      rw [he]
      apply ContinuousOn.div (by fun_prop) (by fun_prop)
      intro x hx
      exact ne_of_gt (add_pos_of_pos_of_nonneg hp hx)
  · exact fun x hx => unified_radial_lower a b k x hk hx

theorem unified_radial_quadratic (a b k x : ℝ) (hk : 0 < k) (hx : 0 ≤ x) :
    let y := unifiedRadial a b k x
    b*x^2+(a*k-y)*x-k*y = 0 := by
  simp only [unifiedRadial, ne_of_gt hk, ite_false]
  have hd : k+x ≠ 0 := ne_of_gt (add_pos_of_pos_of_nonneg hk hx)
  field_simp
  ring

def unifiedRadialInverseGain (a b k y : ℝ) : ℝ :=
  if k = 0 then 1/b else
    let d := a*k-y
    let root := Real.sqrt (d^2+4*b*k*y)
    if 0 ≤ d then 2*k/(root+d) else (root-d)/(2*b*y)

/-- The two stable gain formulas recover the same unique nonnegative source. -/
theorem unified_radial_stable_inverse (a b k y : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hk : 0 ≤ k) (hy : 0 ≤ y) :
    0 ≤ y*unifiedRadialInverseGain a b k y ∧
      unifiedRadial a b k (y*unifiedRadialInverseGain a b k y) = y := by
  obtain ⟨x, hx, _⟩ := unified_radial_inverse_exists a b k y ha hb hk hy
  have he : y*unifiedRadialInverseGain a b k y = x := by
    rcases eq_or_lt_of_le hy with hzero | hypos
    · have heq : unifiedRadial a b k x = unifiedRadial a b k 0 := by
        rw [hx.2, ← hzero, unified_radial_zero]
      have hx0 := (unified_radial_strict_mono a b k ha hb hk).injOn hx.1
        (show (0:ℝ) ∈ Ici (0:ℝ) by simp) heq
      simp [← hzero, hx0]
    · by_cases hk0 : k = 0
      · simp [unifiedRadial, hk0] at hx
        simp only [unifiedRadialInverseGain, hk0, ite_true, ← hx.2]
        field_simp [hb.ne']
      · have hkpos : 0 < k := lt_of_le_of_ne hk (Ne.symm hk0)
        let d := a*k-y
        let root := Real.sqrt (d^2+4*b*k*y)
        have hxpos : 0 < x := by
          apply lt_of_le_of_ne hx.1
          intro hz
          have : 0 = y := by simpa [← hz, unified_radial_zero] using hx.2
          exact hypos.ne' this.symm
        have hpoly := unified_radial_quadratic a b k x hkpos hx.1
        change b*x^2+(a*k-unifiedRadial a b k x)*x-k*unifiedRadial a b k x = 0 at hpoly
        rw [hx.2] at hpoly
        change b*x^2+d*x-k*y = 0 at hpoly
        have hprod : x*(b*x+d) = k*y := by linarith only [hpoly, show x*(b*x+d) = b*x^2+d*x by ring]
        have hsum : 0 < b*x+d := by
          by_contra! hn
          have hn' := mul_nonpos_of_nonneg_of_nonpos hxpos.le hn
          linarith only [hn', hprod, mul_pos hkpos hypos]
        have hsign : 0 < 2*b*x+d := by linarith only [hsum, mul_pos hb hxpos]
        have hsq : root^2 = (2*b*x+d)^2 := by
          dsimp [root]
          rw [Real.sq_sqrt (by positivity)]
          linear_combination -4*b*hpoly
        have hroot : root = 2*b*x+d := by
          have hr : 0 ≤ root := Real.sqrt_nonneg _
          simpa only [abs_of_nonneg hr, abs_of_pos hsign] using
            (sq_eq_sq_iff_abs_eq_abs _ _).mp hsq
        simp only [unifiedRadialInverseGain, hk0, ite_false]
        change y*(if 0 ≤ d then 2*k/(root+d) else (root-d)/(2*b*y)) = x
        split
        · have hden : 0 < root+d := by rw [hroot]; linarith only [hsum]
          rw [← mul_div_assoc]
          apply (div_eq_iff hden.ne').2
          rw [hroot]
          linarith only [hprod, show x*(2*b*x+d+d) = 2*(x*(b*x+d)) by ring,
            show y*(2*k) = 2*(k*y) by ring]
        · rw [← mul_div_assoc]
          apply (div_eq_iff (by positivity : 2*b*y ≠ 0)).2
          rw [hroot]
          ring
  rw [he]
  exact hx

def unifiedBlack (black x : ℝ) : ℝ := unifiedRadial (1/2) 1 (2*black) x

theorem unified_black_formula (black x : ℝ) (hb : 0 < black) :
    unifiedBlack black x = x*(x+black)/(x+2*black) := by
  have hk : (2:ℝ)*black ≠ 0 := by positivity
  simp only [unifiedBlack, unifiedRadial, hk, ite_false]
  congr 1 <;> ring

theorem unified_black_inverse_exists (black y : ℝ) (hb : 0 ≤ black) (hy : 0 ≤ y) :
    ∃! x, 0 ≤ x ∧ unifiedBlack black x = y :=
  unified_radial_inverse_exists _ _ _ _ (by norm_num) (by norm_num) (by positivity) hy

def unifiedFitted (m : ℝ) (weights left right : Fin 4 → ℝ) (w t : ℝ) : ℝ :=
  m*t + ∑ i, weights i*(kernel t (left i) (right i) w / kernel 1 (left i) (right i) w)

theorem unified_fitted_lower (m : ℝ) (weights left right : Fin 4 → ℝ) (w x : ℝ)
    (hw : 0 < w) (ha : ∀ i, 0 ≤ weights i) (hk : ∀ i, left i < right i) (hx : 0 ≤ x) :
    m*x ≤ unifiedFitted m weights left right w x := by
  apply le_add_of_nonneg_right
  apply Finset.sum_nonneg
  intro i _
  have hi : 0 ≤ kernel x (left i) (right i) w := by
    simpa only [kernel_zero] using (kernel_strictMono (left i) (right i) w (hk i) hw).monotone hx
  exact mul_nonneg (ha i) (div_nonneg hi (kernel_normalizer_positive _ _ _ (hk i) hw).le)

theorem unified_fitted_inverse_exists (m : ℝ) (weights left right : Fin 4 → ℝ) (w y : ℝ)
    (hm : 0 < m) (hw : 0 < w) (ha : ∀ i, 0 ≤ weights i) (hk : ∀ i, left i < right i)
    (hy : 0 ≤ y) : ∃! t, 0 ≤ t ∧ unifiedFitted m weights left right w t = y := by
  have hnorm i := kernel_normalizer_positive (left i) (right i) w (hk i) hw
  have hkernel i := kernel_strictMono (left i) (right i) w (hk i) hw
  apply unified_scalar_inverse_exists _ m y hm hy
  · simp [unifiedFitted, kernel_zero]
  · let f i t := kernel t (left i) (right i) w / kernel 1 (left i) (right i) w
    have hf (i : Fin 4) : Monotone (f i) := by
      intro x y hxy
      exact div_le_div_of_nonneg_right ((hkernel i).monotone hxy) (hnorm i).le
    exact (tone_strictMono m hm f hf weights ha).strictMonoOn (Ici 0)
  · have hc (i : Fin 4) : Continuous (fun t => kernel t (left i) (right i) w) := by
      exact continuous_iff_continuousAt.mpr fun t =>
        (kernel_derivative t (left i) (right i) w hw.ne').continuousAt
    have hsum : Continuous (fun t => ∑ i, weights i *
        (kernel t (left i) (right i) w / kernel 1 (left i) (right i) w)) :=
      continuous_finsetSum _ fun i _ => continuous_const.mul ((hc i).div_const _)
    exact (continuous_const.mul continuous_id |>.add hsum).continuousOn
  · exact fun x => unified_fitted_lower m weights left right w x hw ha hk

structure UnifiedToneCurve where
  black : ℝ
  span : ℝ
  slope : ℝ
  residual : Fin 4 → ℝ
  left : Fin 4 → ℝ
  right : Fin 4 → ℝ
  width : ℝ
  black_nonneg : 0 ≤ black
  span_pos : 0 < span
  slope_pos : 0 < slope
  residual_nonneg : ∀ i, 0 ≤ residual i
  knots_ordered : ∀ i, left i < right i
  width_pos : 0 < width

def unifiedToneCurve (curve : UnifiedToneCurve) (x : ℝ) : ℝ :=
  100 * unifiedFitted curve.slope curve.residual curve.left curve.right curve.width
    (unifiedBlack curve.black (x/100) / curve.span)

theorem unified_tone_curve_zero (curve : UnifiedToneCurve) : unifiedToneCurve curve 0 = 0 := by
  simp [unifiedToneCurve, unifiedBlack, unified_radial_zero, unifiedFitted, kernel_zero]

theorem unified_black_nonneg (black x : ℝ) (hb : 0 ≤ black) (hx : 0 ≤ x) :
    0 ≤ unifiedBlack black x := by
  apply le_trans _ (unified_radial_lower (1/2) 1 (2*black) x (by positivity) hx)
  positivity

theorem unified_tone_curve_nonneg (curve : UnifiedToneCurve) (x : ℝ) (hx : 0 ≤ x) :
    0 ≤ unifiedToneCurve curve x := by
  have ht : 0 ≤ unifiedBlack curve.black (x/100)/curve.span :=
    div_nonneg (unified_black_nonneg _ _ curve.black_nonneg (by positivity)) curve.span_pos.le
  have hm := curve.slope_pos
  apply mul_nonneg (by norm_num)
  exact (mul_nonneg hm.le ht).trans (unified_fitted_lower _ _ _ _ _ _ curve.width_pos
    curve.residual_nonneg curve.knots_ordered ht)

theorem unified_tone_curve_inverse_exists (curve : UnifiedToneCurve) (y : ℝ) (hy : 0 ≤ y) :
    ∃! x, 0 ≤ x ∧ unifiedToneCurve curve x = y := by
  obtain ⟨t, ht, ht_unique⟩ := unified_fitted_inverse_exists curve.slope curve.residual
    curve.left curve.right curve.width (y/100) curve.slope_pos curve.width_pos
    curve.residual_nonneg curve.knots_ordered (by positivity)
  have ht0 := ht.1
  obtain ⟨u, hu, hu_unique⟩ := unified_black_inverse_exists curve.black (t*curve.span)
    curve.black_nonneg (mul_nonneg ht0 curve.span_pos.le)
  have hu0 := hu.1
  have hs := curve.span_pos.ne'
  refine ⟨100*u, ⟨by positivity, ?_⟩, ?_⟩
  · simp only [unifiedToneCurve]
    rw [show 100*u/100 = u by ring, hu.2, mul_div_cancel_right₀ _ hs, ht.2]
    ring
  · intro z hz
    have hz0 := hz.1
    have hblack := unified_black_nonneg curve.black (z/100) curve.black_nonneg (by positivity)
    have hEq := ht_unique (unifiedBlack curve.black (z/100)/curve.span) ⟨
      div_nonneg hblack curve.span_pos.le, by unfold unifiedToneCurve at hz; linarith [hz.2]⟩
    have hU := hu_unique (z/100) ⟨by positivity, (div_eq_iff hs).1 hEq⟩
    linarith

/-- The real component carries signed J_A. The complex component is Cartesian a+ib. -/
abbrev UnifiedPoint := ℝ × ℂ

def unifiedOpponent (f : ℝ → ℝ) (v : ℂ) : ℂ := (f ‖v‖ / ‖v‖) • v

theorem unified_opponent_norm (f : ℝ → ℝ) (hf : f 0 = 0)
    (hn : ∀ x, 0 ≤ x → 0 ≤ f x) (v : ℂ) : ‖unifiedOpponent f v‖ = f ‖v‖ := by
  by_cases hz : v = 0
  · simp [unifiedOpponent, hz, hf]
  · have hp : 0 < ‖v‖ := norm_pos_iff.mpr hz
    rw [unifiedOpponent, norm_smul, Real.norm_eq_abs,
      abs_of_nonneg (div_nonneg (hn _ hp.le) hp.le), div_mul_cancel₀ _ hp.ne']

theorem unified_opponent_bijective (f : ℝ → ℝ) (hf : f 0 = 0)
    (hn : ∀ x, 0 ≤ x → 0 ≤ f x)
    (hi : ∀ y, 0 ≤ y → ∃! x, 0 ≤ x ∧ f x = y) :
    Function.Bijective (unifiedOpponent f) := by
  have hnorm v := unified_opponent_norm f hf hn v
  constructor
  · intro v w he
    have hrad := congrArg norm he
    change ‖unifiedOpponent f v‖ = ‖unifiedOpponent f w‖ at hrad
    rw [hnorm, hnorm] at hrad
    obtain ⟨r, _, hr⟩ := hi (f ‖w‖) (hn _ (norm_nonneg w))
    have hc : ‖v‖ = ‖w‖ := (hr _ ⟨norm_nonneg v, hrad⟩).trans
      (hr _ ⟨norm_nonneg w, rfl⟩).symm
    by_cases hz : w = 0
    · simpa [hz] using hc
    · have hp : 0 < ‖w‖ := norm_pos_iff.mpr hz
      have hfpos : 0 < f ‖w‖ := by
        apply lt_of_le_of_ne (hn _ hp.le)
        intro heq
        have hr' := hr 0 ⟨le_rfl, hf.trans heq⟩
        have hw := hr _ ⟨hp.le, rfl⟩
        exact hp.ne' (hw.trans hr'.symm)
      have hgain : f ‖w‖/‖w‖ ≠ 0 := (div_pos hfpos hp).ne'
      unfold unifiedOpponent at he
      rw [hc] at he
      have hs := congrArg (fun v : ℂ => (f ‖w‖/‖w‖)⁻¹ • v) he
      simpa only [smul_smul, inv_mul_cancel₀ hgain, one_smul] using hs
  · intro w
    by_cases hz : w = 0
    · exact ⟨0, by simp [unifiedOpponent, hz]⟩
    · have hp : 0 < ‖w‖ := norm_pos_iff.mpr hz
      obtain ⟨r, hr, _⟩ := hi ‖w‖ hp.le
      let v : ℂ := (r/‖w‖) • w
      have hv : ‖v‖ = r := by
        rw [show v = (r/‖w‖) • w from rfl, norm_smul, Real.norm_eq_abs,
          abs_of_nonneg (div_nonneg hr.1 hp.le), div_mul_cancel₀ _ hp.ne']
      have hrp : r ≠ 0 := by
        intro h
        exact hp.ne' (hr.2.symm.trans (h ▸ hf))
      refine ⟨v, ?_⟩
      rw [unifiedOpponent, hv, hr.2]
      change (‖w‖/r) • ((r/‖w‖) • w) = w
      rw [smul_smul, show ‖w‖/r*(r/‖w‖) = 1 by field_simp, one_smul]

def unifiedStops (s : ℝ) : ℝ := Real.exp (s*Real.log 2)

def unifiedToneStops (shadow highlight crossover j : ℝ) : ℝ :=
  let offset := |j|/(100*crossover)-1
  let t := clipUnit |offset|
  (if offset < 0 then shadow else highlight) * (t^2*(3-2*t))

def unifiedSaturationScale : ℝ := 3409902169100728/(100000000000000*75)

def unifiedSaturationRatio (coordinate : ℝ) : ℝ :=
  unifiedSaturationScale * coordinate /
    Real.sqrt ((1-coordinate)*(1+coordinate))

theorem unified_saturation_ratio_nonneg (coordinate : ℝ)
    (hcoordinate : 0 ≤ coordinate) (hupper : coordinate ≤ 99/100) :
    0 ≤ unifiedSaturationRatio coordinate := by
  have hleft : 0 < 1-coordinate := by linarith
  have hright : 0 < 1+coordinate := by linarith
  have hscale : 0 < unifiedSaturationScale := by
    norm_num [unifiedSaturationScale]
  have hroot : 0 < Real.sqrt ((1-coordinate)*(1+coordinate)) :=
    Real.sqrt_pos.2 (mul_pos hleft hright)
  unfold unifiedSaturationRatio
  exact div_nonneg (mul_nonneg hscale.le hcoordinate) hroot.le

structure UnifiedChromaControls where
  muted : ℝ
  vivid : ℝ
  saturation_crossover : ℝ
  shadow : ℝ
  highlight : ℝ
  tone_crossover : ℝ
  saturation_nonneg : 0 ≤ saturation_crossover
  saturation_le_cap : saturation_crossover ≤ 99/100
  tone_crossover_min : 1/10 ≤ tone_crossover
  tone_crossover_max : tone_crossover ≤ 14/10

def unifiedChromaRadius (c : UnifiedChromaControls) (j x : ℝ) : ℝ :=
  let base := (35/75 : ℝ)*|j|
  let a := unifiedStops c.muted
  let b := unifiedStops c.vivid
  let k := |j| * unifiedSaturationRatio c.saturation_crossover * Real.sqrt (b/a)
  let g := unifiedStops (unifiedToneStops c.shadow c.highlight c.tone_crossover j)
  unifiedRadial 1 g (base/9) (unifiedRadial a b k x)

theorem unified_chroma_radius_zero (c : UnifiedChromaControls) (j : ℝ) :
    unifiedChromaRadius c j 0 = 0 := by
  simp [unifiedChromaRadius, unified_radial_zero]

theorem unified_chroma_radius_nonneg (c : UnifiedChromaControls) (j x : ℝ) (hx : 0 ≤ x) :
    0 ≤ unifiedChromaRadius c j x := by
  unfold unifiedChromaRadius
  have h (a b k x : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) (hk : 0 ≤ k) (hx : 0 ≤ x) :
      0 ≤ unifiedRadial a b k x :=
    (mul_nonneg (le_min ha hb) hx).trans (unified_radial_lower a b k x hk hx)
  have hsraw := unified_saturation_ratio_nonneg c.saturation_crossover
    c.saturation_nonneg c.saturation_le_cap
  apply h _ _ _ _ (by norm_num) (by unfold unifiedStops; positivity) (by positivity)
  exact h _ _ _ _ (by unfold unifiedStops; positivity) (by unfold unifiedStops; positivity)
    (mul_nonneg (mul_nonneg (abs_nonneg j) hsraw) (Real.sqrt_nonneg _)) hx

theorem unified_chroma_radius_inverse_exists (c : UnifiedChromaControls) (j y : ℝ) (hy : 0 ≤ y) :
    ∃! x, 0 ≤ x ∧ unifiedChromaRadius c j x = y := by
  let base := (35/75 : ℝ)*|j|
  let a := unifiedStops c.muted
  let b := unifiedStops c.vivid
  let k := |j| * unifiedSaturationRatio c.saturation_crossover * Real.sqrt (b/a)
  let g := unifiedStops (unifiedToneStops c.shadow c.highlight c.tone_crossover j)
  have hg : 0 < g := Real.exp_pos _
  have ha : 0 < a := Real.exp_pos _
  have hb : 0 < b := Real.exp_pos _
  have hbase : 0 ≤ base := by dsimp [base]; positivity
  have htoe : 0 ≤ base/9 := by positivity
  have hnum := unified_saturation_ratio_nonneg c.saturation_crossover
    c.saturation_nonneg c.saturation_le_cap
  have hk : 0 ≤ k :=
    mul_nonneg (mul_nonneg (abs_nonneg j) hnum) (Real.sqrt_nonneg _)
  obtain ⟨r, hr, hru⟩ := unified_radial_inverse_exists 1 g (base/9) y (by norm_num) hg htoe hy
  obtain ⟨x, hx, hxu⟩ := unified_radial_inverse_exists a b k r ha hb hk hr.1
  refine ⟨x, ⟨hx.1, ?_⟩, ?_⟩
  · change unifiedRadial 1 g (base/9) (unifiedRadial a b k x) = y
    rw [hx.2, hr.2]
  · intro z hz
    have hz0 : 0 ≤ unifiedRadial a b k z :=
      (mul_nonneg (le_min ha.le hb.le) hz.1).trans (unified_radial_lower a b k z hk hz.1)
    exact hxu z ⟨hz.1, hru _ ⟨hz0, hz.2⟩⟩

def unifiedChromaMap (c : UnifiedChromaControls) (p : UnifiedPoint) : UnifiedPoint :=
  (p.1, unifiedOpponent (unifiedChromaRadius c p.1) p.2)

theorem unified_chroma_bijective (c : UnifiedChromaControls) :
    Function.Bijective (unifiedChromaMap c) := by
  have h j := unified_opponent_bijective (unifiedChromaRadius c j)
    (unified_chroma_radius_zero c j) (unified_chroma_radius_nonneg c j)
    (unified_chroma_radius_inverse_exists c j)
  constructor
  · rintro ⟨j, v⟩ ⟨k, w⟩ he
    have hj : j = k := congrArg Prod.fst he
    subst k
    have hv := (h j).1 (congrArg Prod.snd he)
    exact Prod.ext rfl hv
  · rintro ⟨j, w⟩
    obtain ⟨v, hv⟩ := (h j).2 w
    exact ⟨(j, v), Prod.ext rfl hv⟩

def unifiedRay (k : ℝ) (p : UnifiedPoint) : UnifiedPoint := (k*p.1, k • p.2)

def unifiedHeight (p : UnifiedPoint) : ℝ := Real.sqrt (p.1^2+66*‖p.2‖)

theorem unified_ray_one (p : UnifiedPoint) : unifiedRay 1 p = p := by
  simp [unifiedRay]

theorem unified_ray_mul (s k : ℝ) (p : UnifiedPoint) :
    unifiedRay s (unifiedRay k p) = unifiedRay (s*k) p := by
  simp [unifiedRay, mul_assoc]

theorem unified_ray_height_square (k : ℝ) (p : UnifiedPoint) (hk : 0 ≤ k) :
    unifiedHeight (unifiedRay k p)^2 = p.1^2*k^2+66*‖p.2‖*k := by
  unfold unifiedRay unifiedHeight
  simp only [norm_smul, Real.norm_eq_abs, abs_of_nonneg hk]
  rw [Real.sq_sqrt (by positivity)]
  ring

theorem unified_height_pos (p : UnifiedPoint) (hp : p ≠ 0) : 0 < unifiedHeight p := by
  apply Real.sqrt_pos.2
  by_cases hj : p.1 = 0
  · have hv : p.2 ≠ 0 := fun h => hp (Prod.ext hj h)
    have hc := norm_pos_iff.mpr hv
    positivity
  · positivity

theorem unified_ray_height_unique (p : UnifiedPoint) (hp : p ≠ 0)
    (s k : ℝ) (hs : 0 < s) (hk : 0 < k)
    (he : unifiedHeight (unifiedRay s p) = unifiedHeight (unifiedRay k p)) : s = k := by
  have h := congrArg (fun x : ℝ => x^2) he
  rw [unified_ray_height_square s p hs.le, unified_ray_height_square k p hk.le] at h
  have hfactor : (s-k)*(p.1^2*(s+k)+66*‖p.2‖) = 0 := by
    linarith only [h, show (s-k)*(p.1^2*(s+k)+66*‖p.2‖) =
      (p.1^2*s^2+66*‖p.2‖*s)-(p.1^2*k^2+66*‖p.2‖*k) by ring]
  have hpos : 0 < p.1^2*(s+k)+66*‖p.2‖ := by
    by_cases hj : p.1 = 0
    · have hv : p.2 ≠ 0 := fun h => hp (Prod.ext hj h)
      have hc := norm_pos_iff.mpr hv
      positivity
    · positivity
  exact sub_eq_zero.mp ((mul_eq_zero.mp hfactor).resolve_right hpos.ne')

theorem unified_ray_gain (p : UnifiedPoint) (t : ℝ) (hp : p ≠ 0) (ht : 0 < t) :
    0 < toneGain p.1 ‖p.2‖ t ∧ unifiedHeight (unifiedRay (toneGain p.1 ‖p.2‖ t) p) = t := by
  have hdiscr : 0 < (66*‖p.2‖)^2+4*p.1^2*t^2 := by
    by_cases hj : p.1 = 0
    · have hv : p.2 ≠ 0 := fun h => hp (Prod.ext hj h)
      have hc := norm_pos_iff.mpr hv
      positivity
    · positivity
  have hg := tone_gain_positive p.1 ‖p.2‖ t (norm_nonneg _) ht hdiscr
  refine ⟨hg, ?_⟩
  have hsq := unified_ray_height_square _ p hg.le
  rw [tone_gain_quadratic p.1 ‖p.2‖ t (norm_nonneg _) hdiscr] at hsq
  have he := (sq_eq_sq_iff_abs_eq_abs _ _).mp hsq
  have hn : 0 ≤ unifiedHeight (unifiedRay (toneGain p.1 ‖p.2‖ t) p) := Real.sqrt_nonneg _
  simpa only [abs_of_nonneg hn, abs_of_pos ht] using he

def unifiedToneMap (f : ℝ → ℝ) (p : UnifiedPoint) : UnifiedPoint :=
  unifiedRay (toneGain p.1 ‖p.2‖ (f (unifiedHeight p))) p

theorem unified_tone_bijective (f : ℝ → ℝ) (hf : f 0 = 0)
    (hn : ∀ x, 0 ≤ x → 0 ≤ f x)
    (hi : ∀ y, 0 ≤ y → ∃! x, 0 ≤ x ∧ f x = y) :
    Function.Bijective (unifiedToneMap f) := by
  have hfpos : ∀ p : UnifiedPoint, p ≠ 0 → 0 < f (unifiedHeight p) := by
    intro p hp
    have hh := unified_height_pos p hp
    by_contra! h
    /- The candidate curve is positive on positive height. -/
    obtain ⟨x, _, hx⟩ := hi 0 le_rfl
    have hz := hx 0 ⟨le_rfl, hf⟩
    have hEq : f (unifiedHeight p) = 0 := le_antisymm h (hn _ hh.le)
    have hp' := hx (unifiedHeight p) ⟨hh.le, hEq⟩
    exact hh.ne' (hp'.trans hz.symm)
  have hzero : unifiedToneMap f 0 = 0 := by simp [unifiedToneMap, unifiedRay]
  have hhzero : unifiedHeight 0 = 0 := by simp [unifiedHeight]
  have hedit (p : UnifiedPoint) (hp : p ≠ 0) :=
    unified_ray_gain p (f (unifiedHeight p)) hp (hfpos p hp)
  have hmap (p : UnifiedPoint) : unifiedHeight (unifiedToneMap f p) = f (unifiedHeight p) := by
    by_cases hz : p = 0
    · simp [hz, hzero, hhzero, hf]
    · exact (hedit p hz).2
  constructor
  · intro p q he
    have h := congrArg unifiedHeight he
    rw [hmap, hmap] at h
    by_cases hq : q = 0
    · subst q
      by_contra hp
      have hpos := hfpos p hp
      rw [hhzero, hf] at h
      exact hpos.ne' h
    · have hp : p ≠ 0 := by
        intro hz
        have hpos := hfpos q hq
        rw [hz, hhzero, hf] at h
        exact hpos.ne' h.symm
      obtain ⟨r, _, hr⟩ := hi (f (unifiedHeight q)) (hfpos q hq).le
      have hh : unifiedHeight p = unifiedHeight q :=
        (hr _ ⟨Real.sqrt_nonneg _, h⟩).trans (hr _ ⟨Real.sqrt_nonneg _, rfl⟩).symm
      let s := toneGain p.1 ‖p.2‖ (f (unifiedHeight p))
      let k := toneGain q.1 ‖q.2‖ (f (unifiedHeight q))
      have hs : 0 < s := (hedit p hp).1
      have hk : 0 < k := (hedit q hq).1
      have hqray : unifiedRay (s/k) p = q := by
        have hy := congrArg (unifiedRay (1/k)) he
        change unifiedRay (1/k) (unifiedRay s p) = unifiedRay (1/k) (unifiedRay k q) at hy
        rwa [unified_ray_mul, unified_ray_mul, show 1/k*k = 1 by field_simp [hk.ne'],
          unified_ray_one, show 1/k*s = s/k by ring] at hy
      have hscale := unified_ray_height_unique p hp (s/k) 1 (div_pos hs hk) one_pos (by
        rw [hqray, unified_ray_one, hh])
      rw [hscale, unified_ray_one] at hqray
      exact hqray
  · intro q
    by_cases hq : q = 0
    · exact ⟨0, hzero.trans hq.symm⟩
    · have hqheight := unified_height_pos q hq
      obtain ⟨r, hr, _⟩ := hi (unifiedHeight q) hqheight.le
      have hrpos : 0 < r := by
        apply lt_of_le_of_ne hr.1
        intro he
        exact hqheight.ne' (hr.2.symm.trans (he ▸ hf))
      obtain ⟨hk, hhit⟩ := unified_ray_gain q r hq hrpos
      let k := toneGain q.1 ‖q.2‖ r
      let p := unifiedRay k q
      have hhp : unifiedHeight p = r := hhit
      have hp : p ≠ 0 := by
        intro he
        simp [he, unifiedHeight] at hhp
        linarith
      let s := toneGain p.1 ‖p.2‖ (f (unifiedHeight p))
      have hs : 0 < s := (hedit p hp).1
      have he : unifiedHeight (unifiedRay (s*k) q) = unifiedHeight (unifiedRay 1 q) := by
        rw [← unified_ray_mul, unified_ray_one]
        change unifiedHeight (unifiedToneMap f p) = _
        rw [hmap, hhp, hr.2]
      have hscale := unified_ray_height_unique q hq (s*k) 1 (mul_pos hs hk) one_pos he
      refine ⟨p, ?_⟩
      change unifiedRay s (unifiedRay k q) = q
      rw [unified_ray_mul, hscale, unified_ray_one]

def unifiedChromaTone (c : UnifiedChromaControls) (f : ℝ → ℝ) (p : UnifiedPoint) : UnifiedPoint :=
  unifiedChromaMap c (unifiedToneMap f p)

theorem unified_chroma_tone_inverse_exists_unique (controls : UnifiedChromaControls)
    (curve : UnifiedToneCurve) (y : UnifiedPoint) :
    ∃! x, unifiedChromaTone controls (unifiedToneCurve curve) x = y := by
  have h := (unified_chroma_bijective controls).comp
    (unified_tone_bijective (unifiedToneCurve curve) (unified_tone_curve_zero curve)
      (unified_tone_curve_nonneg curve) (unified_tone_curve_inverse_exists curve))
  obtain ⟨x, hx⟩ := h.2 y
  exact ⟨x, hx, fun z hz => h.1 (hz.trans hx.symm)⟩

end
end PerceptualGrade
