import PerceptualGrade.C2Boundary

namespace PerceptualGrade
noncomputable section
open Set
open scoped ContDiff

/-- Single full-radius release; x is spindle radius / boundary radius. -/
def finiteSpindleRelease (k x : ℝ) : ℝ := x+(k-1)*x^3
def hardSpindleRadius (b x : ℝ) : ℝ := min x b

theorem finite_spindle_c2 (k : ℝ) : ContDiff ℝ 2 (finiteSpindleRelease k) := by
  unfold finiteSpindleRelease
  fun_prop

theorem finite_spindle_derivative (k x : ℝ) :
    HasDerivAt (finiteSpindleRelease k) (1+3*(k-1)*x^2) x := by
  convert (hasDerivAt_id x).add (((hasDerivAt_id x).pow 3).const_mul (k-1)) using 1
  · rfl
  · simp; ring

theorem finite_spindle_second_derivative (k x : ℝ) :
    HasDerivAt (fun t : ℝ => 1+3*(k-1)*t^2) (6*(k-1)*x) x := by
  convert (((hasDerivAt_id x).pow 2).const_mul (3*(k-1))).const_add 1 using 1
  · rfl
  · simp; ring

theorem finite_spindle_endpoints (k : ℝ) :
    finiteSpindleRelease k 0 = 0 ∧ finiteSpindleRelease k 1 = k := by
  simp [finiteSpindleRelease]

theorem finite_spindle_identity (x : ℝ) : finiteSpindleRelease 1 x = x := by
  simp [finiteSpindleRelease]

theorem finite_spindle_strict_mono (k : ℝ) (hk : 1 ≤ k) :
    StrictMonoOn (finiteSpindleRelease k) (Icc 0 1) := by
  unfold finiteSpindleRelease
  simpa only [one_mul] using corner_cubic_monotone 1 (k-1) (by norm_num) (by linarith)

theorem finite_spindle_bounds (k x : ℝ) (hk : 1 ≤ k) (hx : x ∈ Icc 0 1) :
    0 ≤ finiteSpindleRelease k x ∧ finiteSpindleRelease k x ≤ k := by
  have hm := (finite_spindle_strict_mono k hk).monotoneOn
  have he := finite_spindle_endpoints k
  constructor
  · simpa [he.1] using hm (show (0:ℝ) ∈ Icc 0 1 by norm_num) hx hx.1
  · simpa [he.2] using hm hx (show (1:ℝ) ∈ Icc 0 1 by norm_num) hx.2

theorem finite_spindle_slope_bounds (k x : ℝ) (hk : 1 ≤ k) (hx : x ∈ Icc 0 1) :
    1 ≤ 1+3*(k-1)*x^2 ∧ 1+3*(k-1)*x^2 ≤ 3*k-2 := by
  have hx0 := hx.1
  have hx1 := hx.2
  have hs : x^2 ≤ 1 := by nlinarith [mul_nonneg hx0 (sub_nonneg.mpr hx1)]
  have h := mul_le_mul_of_nonneg_left hs (show 0 ≤ 3*(k-1) by linarith)
  have hp := mul_nonneg (show 0 ≤ 3*(k-1) by linarith) (sq_nonneg x)
  constructor <;> nlinarith

theorem finite_spindle_cubic_inverse (k x y : ℝ) (he : x+(k-1)*x^3=y) :
    finiteSpindleRelease k x=y := he

theorem finite_spindle_inverse_unique (k x y : ℝ) (hk : 1 ≤ k)
    (hx : x ∈ Icc 0 1) (hy : y ∈ Icc 0 1)
    (he : finiteSpindleRelease k x=finiteSpindleRelease k y) : x=y :=
  (finite_spindle_strict_mono k hk).injOn hx hy he

theorem finite_spindle_inverse_exists (k y : ℝ) (hk : 1 ≤ k)
    (hy : y ∈ Icc 0 k) : ∃! x, x ∈ Icc 0 1 ∧ finiteSpindleRelease k x = y := by
  have hi : y ∈ Icc (finiteSpindleRelease k 0) (finiteSpindleRelease k 1) := by
    simpa only [(finite_spindle_endpoints k).1, (finite_spindle_endpoints k).2] using hy
  obtain ⟨x, hx, he⟩ := intermediate_value_Icc (show (0:ℝ) ≤ 1 by norm_num)
    (finite_spindle_c2 k).continuous.continuousOn hi
  refine ⟨x, ⟨hx, he⟩, ?_⟩
  intro z hz
  exact finite_spindle_inverse_unique k z x hk hz.1 hx (hz.2.trans he.symm)

/-- Cube containment plus positive, normalized adapter rows bounds all cones. -/
theorem normalized_cone_bounds (w rgb : Fin 3 → ℝ)
    (hw : ∀ i, 0 ≤ w i) (hs : ∑ i, w i = 1)
    (hr : ∀ i, rgb i ∈ Icc 0 1024) :
    (∑ i, w i*rgb i) ∈ Icc 0 1024 := by
  constructor
  · exact Finset.sum_nonneg (fun i _ => mul_nonneg (hw i) (hr i).1)
  · calc
      (∑ i, w i*rgb i) ≤ ∑ i, w i*1024 :=
        Finset.sum_le_sum (fun i _ => mul_le_mul_of_nonneg_left (hr i).2 (hw i))
      _ = 1024 := by rw [← Finset.sum_mul, hs]; ring

theorem hard_spindle_identity (b x : ℝ) (hx : x ≤ b) : hardSpindleRadius b x = x :=
  min_eq_left hx

theorem hard_spindle_boundary (b x : ℝ) (hx : b ≤ x) : hardSpindleRadius b x = b :=
  min_eq_right hx

theorem hard_spindle_idempotent (b x : ℝ) :
    hardSpindleRadius b (hardSpindleRadius b x) = hardSpindleRadius b x := by
  simp [hardSpindleRadius]

theorem hard_spindle_continuous (b : ℝ) : Continuous (hardSpindleRadius b) := by
  unfold hardSpindleRadius
  exact continuous_id.min continuous_const

theorem hard_spindle_bounds (b x : ℝ) (hb : 0 ≤ b) (hx : 0 ≤ x) :
    0 ≤ hardSpindleRadius b x ∧ hardSpindleRadius b x ≤ b := by
  exact ⟨le_min hx hb, min_le_right _ _⟩

/-- Reset needs both finite inverse equations only on the represented image. -/
theorem finite_spindle_reset (compress release : ℝ → ℝ) (b x : ℝ)
    (hi : compress x ≤ b) (hinv : release (compress x) = x) :
    release (hardSpindleRadius b (compress x)) = x := by
  rw [hard_spindle_identity b (compress x) hi]
  exact hinv

/-- Composition at reset: signed linear grading precedes cube repair and entry.
The geometric hypotheses apply only to the represented cube image. -/
theorem linear_first_reset {RGB : Type*}
    (linear repair enter guard release : RGB → RGB) (cube : Set RGB) (x : RGB)
    (hrepair : ∀ y, repair y ∈ cube)
    (hguard : ∀ y ∈ cube, guard (enter y) = enter y)
    (hinverse : ∀ y ∈ cube, release (enter y) = y) :
    release (guard (enter (repair (linear x)))) = repair (linear x) := by
  rw [hguard _ (hrepair _)]
  exact hinverse _ (hrepair _)

/-- Raw appearance handoff cancels on a domain where the nonlinear inverse
is a left inverse. No hard projection or RGB decode occurs between grades. -/
theorem appearance_pair_roundtrip {RGB Appearance : Type*}
    (enter : RGB → Appearance) (release : Appearance → RGB)
    (forward inverse : Appearance → Appearance) (x : RGB)
    (hnonlinear : inverse (forward (enter x)) = enter x)
    (hmapping : release (enter x) = x) :
    release (inverse (forward (enter x))) = x := by
  rw [hnonlinear, hmapping]

/-- Matching compiled pairs bypass the nonlinear operations entirely.
This definition also applies to folding maps, without inventing a left inverse. -/
def matchingStackPair {RGB : Type*} (linear repair inverseLinear : RGB → RGB)
    (x : RGB) : RGB := inverseLinear (repair (linear x))

theorem matching_stack_pair_result {RGB : Type*}
    (linear repair inverseLinear : RGB → RGB) (x : RGB) :
    matchingStackPair linear repair inverseLinear x = inverseLinear (repair (linear x)) := rfl

theorem matching_stack_pair_reset {RGB : Type*}
    (linear repair inverseLinear : RGB → RGB) (x : RGB)
    (hrepair : repair (linear x) = linear x)
    (hlinear : inverseLinear (linear x) = x) :
    matchingStackPair linear repair inverseLinear x = x := by
  unfold matchingStackPair
  rw [hrepair, hlinear]

/-- A capacity certificate must include every radius, not only the endpoint. -/
theorem spindle_release_cube (decode : ℝ → Fin 3 → ℝ) (u r : ℝ)
    (hprefix : ∀ x ∈ Icc 0 u, ∀ i, 0 ≤ decode x i ∧ decode x i ≤ 1024)
    (himage : r ∈ Icc 0 u) : ∀ i, 0 ≤ decode r i ∧ decode r i ≤ 1024 := by
  exact hprefix r himage

/-- The interval certificate supplies the response ceiling for both decode paths. -/
theorem guarded_response_domain (FL : ℝ) (r : Fin 3 → ℝ) (hf : 0 < FL)
    (hr : ∀ i, 0 ≤ r i ∧ r i ≤ responseCompression FL 1024) :
    ∀ i, |r i| < 400 := by
  intro i
  rw [abs_of_nonneg (hr i).1]
  exact lt_of_le_of_lt (hr i).2 (compression_domain FL 1024 hf (by norm_num)).2

end
end PerceptualGrade
