import PerceptualGrade.TonalWebAdaptance

/- Selective cone-derived Adaptance. Responses are normalized by the modCAM16
   pole 400. The physical rational branch is exact cone-gain conjugation;
   the exterior branch is a monotone quadratic-coordinate continuation.
   Endpoint jets below concern the joins at ±400, not C2 at signed black.
   Neither the saturation-gated complete map nor its RGB export is asserted
   globally injective. -/
namespace PerceptualGrade
noncomputable section
open Set Filter Asymptotics
open scoped Topology

def selectivePhysical (m x : ℝ) : ℝ := m*x/(1+(m-1)*x)

def selectiveExteriorCoordinate (x : ℝ) : ℝ := (Real.sqrt (4*x-3)-1)/2

def selectiveExterior (m x : ℝ) : ℝ :=
  1+selectiveExteriorCoordinate x/m+(selectiveExteriorCoordinate x/m)^2

def selectiveExteriorRadius (u : ℝ) : ℝ := 1+u+u^2

theorem selective_physical_denominator (m x : ℝ) (hm : 0 < m)
    (hx : x ∈ Icc 0 1) : 0 < 1+(m-1)*x := by
  have hp := mul_nonneg hm.le hx.1
  by_cases h : x < 1
  · nlinarith
  · have he : x = 1 := le_antisymm hx.2 (le_of_not_gt h)
    simp [he, hm]

theorem selective_physical_zero (m : ℝ) : selectivePhysical m 0 = 0 := by
  simp [selectivePhysical]

theorem selective_physical_identity (x : ℝ) : selectivePhysical 1 x = x := by
  simp [selectivePhysical]

theorem selective_physical_boundary (m : ℝ) (hm : m ≠ 0) :
    selectivePhysical m 1 = 1 := by
  simp [selectivePhysical, hm]

theorem selective_physical_bounds (m x : ℝ) (hm : 0 < m)
    (hx : x ∈ Icc 0 1) : selectivePhysical m x ∈ Icc 0 1 := by
  have hd := selective_physical_denominator m x hm hx
  constructor
  · unfold selectivePhysical; exact div_nonneg (mul_nonneg hm.le hx.1) hd.le
  · unfold selectivePhysical
    apply (div_le_one hd).2
    nlinarith [hx.2]

theorem selective_physical_strict_mono (m : ℝ) (hm : 0 < m) :
    StrictMonoOn (selectivePhysical m) (Icc 0 1) := by
  intro x hx y hy hxy
  have hdx := selective_physical_denominator m x hm hx
  have hdy := selective_physical_denominator m y hm hy
  unfold selectivePhysical
  apply (div_lt_div_iff₀ hdx hdy).2
  nlinarith [mul_pos hm (sub_pos.mpr hxy)]

theorem selective_physical_group (m n x : ℝ) (hm : 0 < m) (hn : 0 < n)
    (hx : x ∈ Icc 0 1) :
    selectivePhysical m (selectivePhysical n x) = selectivePhysical (m*n) x := by
  have hd := ne_of_gt (selective_physical_denominator n x hn hx)
  have he := ne_of_gt (selective_physical_denominator (m*n) x (mul_pos hm hn) hx)
  have hf : 1+(m-1)*(n*x/(1+(n-1)*x)) =
      (1+(m*n-1)*x)/(1+(n-1)*x) := by
    apply (eq_div_iff hd).2
    rw [add_mul, one_mul, mul_assoc, div_mul_cancel₀ _ hd]
    ring
  unfold selectivePhysical
  rw [hf, ← mul_div_assoc, div_div_div_cancel_right₀ hd]
  congr 1
  ring

theorem selective_physical_inverse (m x : ℝ) (hm : 0 < m)
    (hx : x ∈ Icc 0 1) :
    selectivePhysical m⁻¹ (selectivePhysical m x) = x := by
  rw [selective_physical_group m⁻¹ m x (inv_pos.mpr hm) hm hx,
    inv_mul_cancel₀ (ne_of_gt hm), selective_physical_identity]

/-- Compression of a nonnegative cone power after a cone gain m^(1/.42).
    The 27.13 viewing constant cancels in the normalized response coordinate. -/
theorem selective_physical_cone_equivalence (m p : ℝ) (hm : 0 < m) (hp : 0 ≤ p) :
    selectivePhysical m (p/(1+p)) = m*p/(1+m*p) := by
  have hd : 1+p ≠ 0 := by positivity
  have he : 1+m*p ≠ 0 := by positivity
  have hx : p/(1+p) ∈ Icc (0 : ℝ) 1 := by
    constructor
    · positivity
    · apply (div_le_one (by positivity)).2; linarith
  have hf : 1+(m-1)*(p/(1+p)) = (1+m*p)/(1+p) := by field_simp [hd]; ring
  unfold selectivePhysical
  rw [hf]
  field_simp [hd, he]

theorem selective_exterior_coordinate_nonneg (x : ℝ) (hx : 1 ≤ x) :
    0 ≤ selectiveExteriorCoordinate x := by
  have hs : 1 ≤ Real.sqrt (4*x-3) := by
    apply (Real.le_sqrt (by norm_num) (by linarith)).2
    linarith
  unfold selectiveExteriorCoordinate
  linarith

theorem selective_exterior_coordinate_radius (u : ℝ) (hu : 0 ≤ u) :
    selectiveExteriorCoordinate (selectiveExteriorRadius u) = u := by
  have he : 4*selectiveExteriorRadius u-3 = (2*u+1)^2 := by
    unfold selectiveExteriorRadius; ring
  rw [selectiveExteriorCoordinate, he, Real.sqrt_sq (by linarith)]
  ring

theorem selective_exterior_radius_coordinate (x : ℝ) (hx : 1 ≤ x) :
    selectiveExteriorRadius (selectiveExteriorCoordinate x) = x := by
  have hs : (Real.sqrt (4*x-3))^2 = 4*x-3 := Real.sq_sqrt (by linarith)
  unfold selectiveExteriorRadius selectiveExteriorCoordinate
  nlinarith

theorem selective_exterior_parametric (m u : ℝ) (hu : 0 ≤ u) :
    selectiveExterior m (selectiveExteriorRadius u) = selectiveExteriorRadius (u/m) := by
  unfold selectiveExterior
  rw [selective_exterior_coordinate_radius u hu]
  rfl

theorem selective_exterior_bounds (m x : ℝ) (hm : 0 < m) (hx : 1 ≤ x) :
    1 ≤ selectiveExterior m x := by
  have hu := selective_exterior_coordinate_nonneg x hx
  unfold selectiveExterior
  have hdiv : 0 ≤ selectiveExteriorCoordinate x/m := div_nonneg hu hm.le
  nlinarith [sq_nonneg (selectiveExteriorCoordinate x/m)]

theorem selective_exterior_identity (x : ℝ) (hx : 1 ≤ x) :
    selectiveExterior 1 x = x := by
  simpa [selectiveExterior, selectiveExteriorRadius] using
    selective_exterior_radius_coordinate x hx

theorem selective_exterior_group (m n x : ℝ) (hm : 0 < m) (hn : 0 < n)
    (hx : 1 ≤ x) :
    selectiveExterior m (selectiveExterior n x) = selectiveExterior (m*n) x := by
  have hu := selective_exterior_coordinate_nonneg x hx
  have hun : 0 ≤ selectiveExteriorCoordinate x/n := div_nonneg hu hn.le
  change selectiveExterior m
      (selectiveExteriorRadius (selectiveExteriorCoordinate x/n)) = _
  rw [selective_exterior_parametric m _ hun]
  unfold selectiveExterior selectiveExteriorRadius
  congr 1 <;> field_simp

theorem selective_exterior_inverse (m x : ℝ) (hm : 0 < m) (hx : 1 ≤ x) :
    selectiveExterior m⁻¹ (selectiveExterior m x) = x := by
  rw [selective_exterior_group m⁻¹ m x (inv_pos.mpr hm) hm hx,
    inv_mul_cancel₀ (ne_of_gt hm), selective_exterior_identity x hx]

theorem selective_exterior_radius_strict_mono :
    StrictMonoOn selectiveExteriorRadius (Ici 0) := by
  intro x hx y hy hxy
  unfold selectiveExteriorRadius
  nlinarith [mul_nonneg (sub_nonneg.mpr hxy.le) (add_nonneg hx hy)]

theorem selective_exterior_strict_mono (m : ℝ) (hm : 0 < m) :
    StrictMonoOn (selectiveExterior m) (Ici 1) := by
  intro x hx y hy hxy
  have hux := selective_exterior_coordinate_nonneg x hx
  have huy := selective_exterior_coordinate_nonneg y hy
  have hcoord : selectiveExteriorCoordinate x < selectiveExteriorCoordinate y := by
    by_contra h
    have hle := (selective_exterior_radius_strict_mono.monotoneOn)
      huy hux (le_of_not_gt h)
    rw [selective_exterior_radius_coordinate y hy,
      selective_exterior_radius_coordinate x hx] at hle
    linarith
  exact selective_exterior_radius_strict_mono (div_nonneg hux hm.le)
    (div_nonneg huy hm.le) ((div_lt_div_iff_of_pos_right hm).2 hcoord)

/-- The complete positive continuation, followed by its odd signed extension. -/
def selectivePositive (m x : ℝ) : ℝ :=
  if x ≤ 1 then selectivePhysical m x else selectiveExterior m x

def selectiveSigned (m x : ℝ) : ℝ :=
  if x < 0 then -selectivePositive m (-x) else selectivePositive m x

theorem selective_exterior_boundary (m : ℝ) : selectiveExterior m 1 = 1 := by
  norm_num [selectiveExterior, selectiveExteriorCoordinate]

theorem selective_exterior_above_boundary (m x : ℝ) (hm : 0 < m) (hx : 1 < x) :
    1 < selectiveExterior m x := by
  have h := selective_exterior_strict_mono m hm (by simp) hx.le hx
  simpa [selective_exterior_boundary] using h

theorem selective_positive_zero (m : ℝ) : selectivePositive m 0 = 0 := by
  simp [selectivePositive, selective_physical_zero]

theorem selective_positive_identity (x : ℝ) : selectivePositive 1 x = x := by
  by_cases hx : x ≤ 1
  · simp [selectivePositive, hx, selective_physical_identity]
  · simpa [selectivePositive, hx] using selective_exterior_identity x (le_of_not_ge hx)

theorem selective_positive_nonneg (m x : ℝ) (hm : 0 < m) (hx : 0 ≤ x) :
    0 ≤ selectivePositive m x := by
  by_cases hb : x ≤ 1
  · simpa [selectivePositive, hb] using (selective_physical_bounds m x hm ⟨hx, hb⟩).1
  · have he := selective_exterior_bounds m x hm (le_of_not_ge hb)
    simp only [selectivePositive, ite_eq_right hb]
    linarith

theorem selective_positive_strict_mono (m : ℝ) (hm : 0 < m) :
    StrictMonoOn (selectivePositive m) (Ici 0) := by
  intro x hx y hy hxy
  by_cases hxb : x ≤ 1
  · by_cases hyb : y ≤ 1
    · simpa only [selectivePositive, ite_eq_left hxb, ite_eq_left hyb] using
        selective_physical_strict_mono m hm ⟨hx, hxb⟩ ⟨hy, hyb⟩ hxy
    · have hu := (selective_physical_bounds m x hm ⟨hx, hxb⟩).2
      have hl := selective_exterior_above_boundary m y hm (lt_of_not_ge hyb)
      simp only [selectivePositive, ite_eq_left hxb, ite_eq_right hyb]
      exact lt_of_le_of_lt hu hl
  · have hyb : ¬y ≤ 1 := by linarith
    simpa only [selectivePositive, ite_eq_right hxb, ite_eq_right hyb] using
      selective_exterior_strict_mono m hm (le_of_not_ge hxb) (le_of_not_ge hyb) hxy

theorem selective_positive_pos (m x : ℝ) (hm : 0 < m) (hx : 0 < x) :
    0 < selectivePositive m x := by
  have h := selective_positive_strict_mono m hm (by simp) hx.le hx
  simpa [selective_positive_zero] using h

theorem selective_positive_group (m n x : ℝ) (hm : 0 < m) (hn : 0 < n)
    (hx : 0 ≤ x) :
    selectivePositive m (selectivePositive n x) = selectivePositive (m*n) x := by
  by_cases hb : x ≤ 1
  · have hy := selective_physical_bounds n x hn ⟨hx, hb⟩
    simp only [selectivePositive, ite_eq_left hb, ite_eq_left hy.2]
    exact selective_physical_group m n x hm hn ⟨hx, hb⟩
  · have hy := selective_exterior_above_boundary n x hn (lt_of_not_ge hb)
    simp only [selectivePositive, ite_eq_right hb, ite_eq_right (not_le.mpr hy)]
    exact selective_exterior_group m n x hm hn (le_of_not_ge hb)

theorem selective_signed_zero (m : ℝ) : selectiveSigned m 0 = 0 := by
  simp [selectiveSigned, selective_positive_zero]

theorem selective_signed_identity (x : ℝ) : selectiveSigned 1 x = x := by
  by_cases hx : x < 0 <;> simp [selectiveSigned, hx, selective_positive_identity]

theorem selective_signed_group (m n x : ℝ) (hm : 0 < m) (hn : 0 < n) :
    selectiveSigned m (selectiveSigned n x) = selectiveSigned (m*n) x := by
  by_cases hx : x < 0
  · have hnx := selective_positive_pos n (-x) hn (by linarith)
    have hneg : -selectivePositive n (-x) < 0 := by linarith
    simp only [selectiveSigned, ite_eq_left hx, ite_eq_left hneg, neg_neg]
    rw [selective_positive_group m n (-x) hm hn (by linarith)]
  · have hnx := selective_positive_nonneg n x hn (le_of_not_gt hx)
    simp only [selectiveSigned, ite_eq_right hx, ite_eq_right (not_lt.mpr hnx)]
    exact selective_positive_group m n x hm hn (le_of_not_gt hx)

theorem selective_signed_inverse (m x : ℝ) (hm : 0 < m) :
    selectiveSigned m⁻¹ (selectiveSigned m x) = x := by
  rw [selective_signed_group m⁻¹ m x (inv_pos.mpr hm) hm,
    inv_mul_cancel₀ (ne_of_gt hm), selective_signed_identity]

/-- Undo normalization before undoing the fixed-selector response map. This
    is a scalar component inverse, not an inverse of input-dependent gating. -/
theorem selective_normalized_inverse (m scale x : ℝ) (hm : 0 < m)
    (hs : scale ≠ 0) :
    selectiveSigned m⁻¹ ((scale*selectiveSigned m x)/scale) = x := by
  rw [mul_div_cancel_left₀ _ hs, selective_signed_inverse m x hm]

theorem selective_signed_odd (m x : ℝ) :
    selectiveSigned m (-x) = -selectiveSigned m x := by
  rcases lt_trichotomy x 0 with hx | hx | hx
  · have hn : ¬-x < 0 := by linarith
    simp [selectiveSigned, hx, hn]
  · simp [hx, selective_signed_zero]
  · have hn : -x < 0 := by linarith
    simp [selectiveSigned, not_lt.mpr hx.le, hn]

theorem selective_signed_strict_mono (m : ℝ) (hm : 0 < m) :
    StrictMono (selectiveSigned m) := by
  intro x y hxy
  by_cases hx : x < 0
  · by_cases hy : y < 0
    · have h := selective_positive_strict_mono m hm
        (by change 0 ≤ -y; linarith) (by change 0 ≤ -x; linarith)
        (by change -y < -x; linarith)
      simp only [selectiveSigned, ite_eq_left hx, ite_eq_left hy]
      linarith
    · have hn := selective_positive_pos m (-x) hm (by linarith)
      have hp := selective_positive_nonneg m y hm (le_of_not_gt hy)
      simp only [selectiveSigned, ite_eq_left hx, ite_eq_right hy]
      linarith
  · have hy : ¬y < 0 := by linarith
    simpa only [selectiveSigned, ite_eq_right hx, ite_eq_right hy] using
      selective_positive_strict_mono m hm (le_of_not_gt hx) (le_of_not_gt hy) hxy

/-- A normalized physical endpoint jet; response units multiply slopes by 1,
    and second derivatives by 1/400. -/
def selectivePhysicalSlope (m x : ℝ) : ℝ := m/(1+(m-1)*x)^2

theorem selective_physical_derivative (m x : ℝ)
    (hd : 1+(m-1)*x ≠ 0) :
    HasDerivAt (selectivePhysical m) (selectivePhysicalSlope m x) x := by
  have h := ((hasDerivAt_id x).const_mul m).div
    (((hasDerivAt_id x).const_mul (m-1)).const_add 1) hd
  convert h using 1
  · rfl
  · unfold selectivePhysicalSlope
    simp only [id_eq] at *
    field_simp [hd]; ring

theorem selective_physical_slope_derivative (m x : ℝ)
    (hd : 1+(m-1)*x ≠ 0) :
    HasDerivAt (selectivePhysicalSlope m) (-2*m*(m-1)/(1+(m-1)*x)^3) x := by
  have h := (hasDerivAt_const x m).div
    ((((hasDerivAt_id x).const_mul (m-1)).const_add 1).pow 2) (pow_ne_zero 2 hd)
  convert h using 1
  · rfl
  · simp only [id_eq, Pi.pow_apply] at *
    norm_num
    field_simp [hd]

theorem selective_exterior_coordinate_derivative (x : ℝ) (hx : 3/4 < x) :
    HasDerivAt selectiveExteriorCoordinate (1/Real.sqrt (4*x-3)) x := by
  have hp : 0 < 4*x-3 := by linarith
  have h := (((hasDerivAt_id x).const_mul 4).sub_const 3).sqrt (ne_of_gt hp)
  have h' := (h.sub_const 1).div_const 2
  convert h' using 1
  · rfl
  · simp only [id_eq] at *
    field_simp; ring

def selectiveExteriorSlope (m x : ℝ) : ℝ :=
  (1+2*selectiveExteriorCoordinate x/m)/(m*Real.sqrt (4*x-3))

theorem selective_exterior_derivative (m x : ℝ) (hm : m ≠ 0) (hx : 3/4 < x) :
    HasDerivAt (selectiveExterior m) (selectiveExteriorSlope m x) x := by
  have h := (selective_exterior_coordinate_derivative x hx).div_const m
  have hh := (h.const_add 1).add (h.pow 2)
  convert hh using 1
  · rfl
  · unfold selectiveExteriorSlope
    norm_num
    field_simp [hm]

theorem selective_boundary_value_and_slope (m : ℝ) (hm : m ≠ 0) :
    selectivePhysical m 1 = selectiveExterior m 1 ∧
    selectivePhysicalSlope m 1 = selectiveExteriorSlope m 1 := by
  norm_num [selectivePhysical, selectivePhysicalSlope, selectiveExterior,
    selectiveExteriorCoordinate, selectiveExteriorSlope, hm]
  field_simp

theorem selective_exterior_slope_boundary_derivative (m : ℝ) (hm : m ≠ 0) :
    HasDerivAt (selectiveExteriorSlope m) (-2*(m-1)/m^2) 1 := by
  have hu := selective_exterior_coordinate_derivative 1 (by norm_num)
  have hs := (((hasDerivAt_id (1 : ℝ)).const_mul 4).sub_const 3).sqrt (by norm_num)
  have hn := (((hu.div_const m).const_mul 2).const_add 1)
  have hd := hs.const_mul m
  have hh := hn.div hd (by norm_num [hm])
  convert hh using 1
  · unfold selectiveExteriorSlope
    funext x
    simp only [mul_div_assoc, id_eq, Pi.div_apply]
  · norm_num [selectiveExteriorCoordinate]
    field_simp [hm]; ring

theorem selective_boundary_second_jet (m : ℝ) (hm : m ≠ 0) :
    HasDerivAt (selectivePhysicalSlope m) (-2*(m-1)/m^2) 1 ∧
    HasDerivAt (selectiveExteriorSlope m) (-2*(m-1)/m^2) 1 := by
  constructor
  · convert selective_physical_slope_derivative m 1 (by simpa using hm) using 1
    norm_num
    field_simp [hm]
  · exact selective_exterior_slope_boundary_derivative m hm

/-- Odd extension gives the same first jet and the opposite second jet at
    the negative physical endpoint. These are branch jets, not a claim of
    global C2 regularity at the signed-response origin. -/
theorem selective_negative_boundary_jets (m : ℝ) (hm : m ≠ 0) :
    HasDerivAt (fun x => -selectivePhysical m (-x)) (selectivePhysicalSlope m 1) (-1) ∧
    HasDerivAt (fun x => -selectiveExterior m (-x)) (selectivePhysicalSlope m 1) (-1) ∧
    HasDerivAt (fun x => selectivePhysicalSlope m (-x)) (2*(m-1)/m^2) (-1) ∧
    HasDerivAt (fun x => selectiveExteriorSlope m (-x)) (2*(m-1)/m^2) (-1) := by
  have hn := (hasDerivAt_id (-1 : ℝ)).neg
  have hp : HasDerivAt (selectivePhysical m) (selectivePhysicalSlope m 1) (-(-1)) := by
    simpa using selective_physical_derivative m 1 (by simpa using hm)
  have he : HasDerivAt (selectiveExterior m) (selectivePhysicalSlope m 1) (-(-1)) := by
    rw [(selective_boundary_value_and_slope m hm).2]
    simpa using selective_exterior_derivative m 1 hm (by norm_num)
  have hpp : HasDerivAt (selectivePhysicalSlope m) (-2*(m-1)/m^2) (-(-1)) := by
    simpa using (selective_boundary_second_jet m hm).1
  have hep : HasDerivAt (selectiveExteriorSlope m) (-2*(m-1)/m^2) (-(-1)) := by
    simpa using (selective_boundary_second_jet m hm).2
  refine ⟨?_, ?_, ?_, ?_⟩
  · convert (hp.comp (-1) hn).neg using 1
    · rfl
    · ring
  · convert (he.comp (-1) hn).neg using 1
    · rfl
    · ring
  · convert hpp.comp (-1) hn using 1
    · rfl
    · ring
  · convert hep.comp (-1) hn using 1
    · rfl
    · ring

/-- Exact held-achromatic-response calibration, with target responses in (0,1). -/
def selectiveCalibration (r₀ target : ℝ) : ℝ := target*(1-r₀)/(r₀*(1-target))

theorem selective_calibration_positive (r₀ target : ℝ)
    (hr : r₀ ∈ Ioo 0 1) (ht : target ∈ Ioo 0 1) :
    0 < selectiveCalibration r₀ target := by
  unfold selectiveCalibration
  exact div_pos (mul_pos ht.1 (sub_pos.mpr hr.2))
    (mul_pos hr.1 (sub_pos.mpr ht.2))

theorem selective_calibration_target (r₀ target : ℝ)
    (hr : r₀ ∈ Ioo 0 1) (ht : target ∈ Ioo 0 1) :
    selectivePhysical (selectiveCalibration r₀ target) r₀ = target := by
  have hm := selective_calibration_positive r₀ target hr ht
  have hd := ne_of_gt (selective_physical_denominator _ r₀ hm ⟨hr.1.le, hr.2.le⟩)
  apply (div_eq_iff hd).2
  have hcal : selectiveCalibration r₀ target * (r₀*(1-target)) = target*(1-r₀) := by
    exact div_mul_cancel₀ _ (mul_ne_zero (ne_of_gt hr.1) (ne_of_gt (sub_pos.mpr ht.2)))
  nlinarith

/-- Response normalization uses weights 2,1,.05; 61/20 is their sum. -/
def selectiveAchromatic (r g b : ℝ) : ℝ := 2*r+g+b/20

def selectiveNormalization (r g b : ℝ) : ℝ := (61/20)/selectiveAchromatic r g b

theorem selective_normalization_neutral (r g b : ℝ)
    (hs : selectiveAchromatic r g b ≠ 0) :
    selectiveAchromatic (selectiveNormalization r g b*r)
      (selectiveNormalization r g b*g) (selectiveNormalization r g b*b) = 61/20 := by
  calc
    _ = selectiveNormalization r g b*selectiveAchromatic r g b := by
      unfold selectiveAchromatic; ring
    _ = 61/20 := div_mul_cancel₀ _ hs

theorem selective_normalization_identity : selectiveNormalization 1 1 1 = 1 := by
  norm_num [selectiveNormalization, selectiveAchromatic]

theorem selective_normalization_positive (r g b : ℝ)
    (hr : 0 < r) (hg : 0 < g) (hb : 0 < b) :
    0 < selectiveNormalization r g b := by
  unfold selectiveNormalization selectiveAchromatic; positivity

/-- R is the directly adjustable half-influence saturation C/|J_A| > 0.
    The mask is expressed in squared signed J_A energy E² and C⁴;
    neutral including black has the explicit value one. -/
def selectiveReach (R E C : ℝ) : ℝ :=
  if C = 0 then 1 else R^4*E^2/(R^4*E^2+C^4)

theorem selective_reach_neutral (R E : ℝ) : selectiveReach R E 0 = 1 := by
  simp [selectiveReach]

theorem selective_reach_zero_achromatic (R C : ℝ) (hC : C ≠ 0) :
    selectiveReach R 0 C = 0 := by simp [selectiveReach, hC]

theorem selective_reach_bounds (R E C : ℝ) :
    0 ≤ selectiveReach R E C ∧ selectiveReach R E C ≤ 1 := by
  by_cases hC : C = 0
  · simp [selectiveReach, hC]
  · have hd : 0 < R^4*E^2+C^4 := by positivity
    simp only [selectiveReach, hC, ↓reduceIte]
    constructor
    · positivity
    · apply (div_le_one hd).2; nlinarith [sq_nonneg (C^2)]

theorem selective_reach_half (R J : ℝ) (hR : R ≠ 0) (hJ : J ≠ 0) :
    selectiveReach R (J*|J|) (R*|J|) = 1/2 := by
  have hC : R*|J| ≠ 0 := mul_ne_zero hR (abs_ne_zero.mpr hJ)
  have hfourth : |J|^4 = J^4 := by nlinarith [sq_abs J]
  simp only [selectiveReach, hC, ↓reduceIte, mul_pow, sq_abs, hfourth]
  field_simp
  ring

theorem selective_reach_scale (R E C k : ℝ) (hk : k ≠ 0) :
    selectiveReach R (k^2*E) (k*C) = selectiveReach R E C := by
  by_cases hC : C = 0
  · simp [selectiveReach, hC]
  · have hkc : k*C ≠ 0 := mul_ne_zero hk hC
    simp only [selectiveReach, hC, hkc, ↓reduceIte]
    have hd : R^4*(k^2*E)^2+(k*C)^4 = k^4*(R^4*E^2+C^4) := by ring
    rw [hd]
    have hn : R^4*(k^2*E)^2 = k^4*(R^4*E^2) := by ring
    rw [hn, mul_div_mul_left _ _ (pow_ne_zero 4 hk)]

/-- One Cartesian component of the linear saturation chart. The executable
    display excludes chromatic zero-energy points rather than dividing by 0. -/
def linearSaturationCoordinate (x E : ℝ) : ℝ := x/Real.sqrt |E|

/-- Final Scale changes neither saturation-pad coordinate, including the
    negative-energy branch. This does not claim invariance after RGB guards. -/
theorem linear_saturation_scale (x E k : ℝ) (hk : 0 < k) :
    linearSaturationCoordinate (k*x) (k^2*E) = linearSaturationCoordinate x E := by
  have hd : Real.sqrt |k^2*E| = k*Real.sqrt |E| := by
    rw [abs_mul, abs_of_nonneg (sq_nonneg k), Real.sqrt_mul (sq_nonneg k),
      Real.sqrt_sq_eq_abs, abs_of_pos hk]
  simp only [linearSaturationCoordinate, hd]
  exact mul_div_mul_left x (Real.sqrt |E|) (ne_of_gt hk)

/-- A neutral anchor has J_A=h after Adaptance calibration, so its direct
    a/b destination for a requested chart coordinate p is h*p. -/
theorem linear_saturation_center_target (h p : ℝ) (hh : 0 < h) :
    linearSaturationCoordinate (h*p) (h^2) = p := by
  rw [linearSaturationCoordinate, abs_of_nonneg (sq_nonneg h),
    Real.sqrt_sq_eq_abs, abs_of_pos hh, mul_div_cancel_left₀ _ (ne_of_gt hh)]

/-- The bounded chart uses carried energy directly. Signed branches share the
    magnitude chart; the executable chart explicitly assigns neutral to zero. -/
def boundedSaturationCoordinate (x C E : ℝ) : ℝ := x/Real.sqrt (C^2+|E|)

def boundedSaturationRadius (C E : ℝ) : ℝ := boundedSaturationCoordinate C C E

theorem bounded_saturation_radius_square (C E : ℝ) :
    (boundedSaturationRadius C E)^2 = C^2/(C^2+|E|) := by
  simp only [boundedSaturationRadius, boundedSaturationCoordinate, div_pow,
    Real.sq_sqrt (by positivity : 0 ≤ C^2+|E|)]

theorem bounded_saturation_radius_bounds (C E : ℝ) (hC : 0 ≤ C) :
    0 ≤ boundedSaturationRadius C E ∧ boundedSaturationRadius C E ≤ 1 := by
  have hn : 0 ≤ boundedSaturationRadius C E := by
    unfold boundedSaturationRadius boundedSaturationCoordinate; positivity
  constructor
  · exact hn
  · have hs : (boundedSaturationRadius C E)^2 ≤ 1 := by
      rw [bounded_saturation_radius_square]
      exact div_le_one_of_le₀ (by linarith [abs_nonneg E]) (by positivity)
    nlinarith

theorem bounded_saturation_zero_energy_boundary (C : ℝ) (hC : 0 < C) :
    boundedSaturationRadius C 0 = 1 := by
  simp [boundedSaturationRadius, boundedSaturationCoordinate,
    Real.sqrt_sq_eq_abs, abs_of_pos hC, ne_of_gt hC]

theorem bounded_saturation_chromatic_factor (C E : ℝ) (hC : 0 < C) :
    0 < 1/Real.sqrt (C^2+|E|) := by positivity

theorem bounded_saturation_signed_chart (x C E : ℝ) :
    boundedSaturationCoordinate x C (-E) = boundedSaturationCoordinate x C E := by
  simp [boundedSaturationCoordinate]

/-- Both opponent components have the same positive radial factor. -/
theorem bounded_saturation_preserves_hue (a b E : ℝ) :
    boundedSaturationCoordinate a (Real.sqrt (a^2+b^2)) E*b =
      boundedSaturationCoordinate b (Real.sqrt (a^2+b^2)) E*a := by
  unfold boundedSaturationCoordinate; ring

theorem bounded_saturation_scale (x C E k : ℝ) (hk : 0 < k) :
    boundedSaturationCoordinate (k*x) (k*C) (k^2*E) =
      boundedSaturationCoordinate x C E := by
  have hd : Real.sqrt ((k*C)^2+|k^2*E|) = k*Real.sqrt (C^2+|E|) := by
    rw [abs_mul, abs_of_nonneg (sq_nonneg k)]
    have he : (k*C)^2+k^2*|E| = k^2*(C^2+|E|) := by ring
    rw [he, Real.sqrt_mul (sq_nonneg k), Real.sqrt_sq_eq_abs, abs_of_pos hk]
  simp only [boundedSaturationCoordinate, hd]
  exact mul_div_mul_left x (Real.sqrt (C^2+|E|)) (ne_of_gt hk)

/-- Releasing an interior point recovers the original linear saturation, on
    either signed branch. The unit circle is deliberately outside this inverse. -/
theorem bounded_saturation_linear_inverse (x C E : ℝ) (hE : E ≠ 0) :
    boundedSaturationCoordinate x C E /
      Real.sqrt (1-(boundedSaturationRadius C E)^2) =
        linearSaturationCoordinate x E := by
  have ha : 0 < |E| := abs_pos.mpr hE
  have hd : 0 < C^2+|E| := by positivity
  have he : 1-(boundedSaturationRadius C E)^2 = |E|/(C^2+|E|) := by
    rw [bounded_saturation_radius_square]
    field_simp; ring
  rw [he, Real.sqrt_div (abs_nonneg E)]
  unfold boundedSaturationCoordinate linearSaturationCoordinate
  have hs : Real.sqrt (C^2+|E|) ≠ 0 := ne_of_gt (Real.sqrt_pos.2 hd)
  field_simp

theorem selective_reach_quartic_bound (R E C : ℝ) (hR : R ≠ 0) (hE : E ≠ 0) :
    |selectiveReach R E C-1| ≤ C^4/(R^4*E^2) := by
  have ha : 0 < R^4*E^2 := by positivity
  by_cases hC : C = 0
  · simp [selectiveReach, hC]
  · have hd : 0 < R^4*E^2+C^4 := by positivity
    have he : selectiveReach R E C-1 = -(C^4/(R^4*E^2+C^4)) := by
      simp only [selectiveReach, hC, ↓reduceIte]
      field_simp; ring
    rw [he, abs_neg, abs_of_nonneg (by positivity)]
    apply (div_le_div_iff₀ hd ha).2
    nlinarith [sq_nonneg (C^4)]

theorem selective_reach_neutral_derivative (R E : ℝ) (hR : R ≠ 0) (hE : E ≠ 0) :
    HasFDerivAt (fun v : ℂ => selectiveReach R E ‖v‖) (0 : ℂ →L[ℝ] ℝ) 0 := by
  have hb : (fun v : ℂ => selectiveReach R E ‖v‖-1) =O[𝓝 0]
      (fun v : ℂ => ‖v‖^4) := by
    apply IsBigO.of_bound (1/(R^4*E^2))
    filter_upwards [] with v
    simpa [Real.norm_eq_abs, abs_of_nonneg (by positivity : 0 ≤ ‖v‖^4),
      div_eq_mul_inv, mul_comm] using selective_reach_quartic_bound R E ‖v‖ hR hE
  have hs := hb.trans_isLittleO (isLittleO_norm_pow_id (E' := ℂ) (show 1 < 4 by norm_num))
  apply HasFDerivAt.of_isLittleO
  simpa [selective_reach_neutral] using hs

theorem selective_reach_high_chroma_limit (R E : ℝ) :
    Tendsto (selectiveReach R E) atTop (𝓝 0) := by
  have hp : Tendsto (fun C : ℝ => C^4) atTop atTop := tendsto_pow_atTop (by norm_num)
  have hd : Tendsto (fun C : ℝ => R^4*E^2+C^4) atTop atTop :=
    tendsto_const_nhds.add_atTop hp
  have ht := hd.const_div_atTop (R^4*E^2)
  apply ht.congr'
  filter_upwards [eventually_gt_atTop (0 : ℝ)] with C hC
  simp [selectiveReach, ne_of_gt hC]

end
end PerceptualGrade
