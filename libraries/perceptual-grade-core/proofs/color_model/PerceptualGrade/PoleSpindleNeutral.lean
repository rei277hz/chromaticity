import PerceptualGrade.PoleSpindleInverse
import PerceptualGrade.CartesianNeutral

namespace PerceptualGrade
noncomputable section
open Set Filter Asymptotics
open scoped Topology

theorem pole_spindle_F_neutral_bounds (z : ℝ) (hz : 0 ≤ z) (hz1 : z ≤ 1/2) :
    0 ≤ poleSpindleF z ∧ poleSpindleF z ≤ 3*z := by
  have hp : z < poleSpindleP := by norm_num [poleSpindleP] at *; linarith
  have hdpos := pole_spindle_denominator_pos z hz hp
  have hden : (1:ℝ)/2 ≤ (1+z)*(poleSpindleP-z) := by
    norm_num [poleSpindleP]
    nlinarith [mul_nonneg hz (show 0 ≤ 1/2-z by linarith)]
  constructor
  · exact pole_spindle_F_nonneg z hz hp
  · unfold poleSpindleF
    have hquot : z*(poleSpindleA+poleSpindleB*z) /
        ((1+z)*(poleSpindleP-z)) ≤ 2*z := by
      apply (div_le_iff₀ hdpos).2
      norm_num [poleSpindleA, poleSpindleB, poleSpindleP]
      nlinarith [mul_nonneg hz (show 0 ≤ 1/2-z by linarith),
        mul_le_mul_of_nonneg_left hden (show 0 ≤ 2*z by positivity)]
    linarith

theorem pole_spindle_factor_neutral_bound (k K z : ℝ) (hk : 1 ≤ k)
    (hK : k ≤ K) (hz : 0 ≤ z) (hz1 : z ≤ 1/2) :
    |Real.sqrt (1+(k^2-1)*poleSpindleF z)-1| ≤ 3*K^2*z := by
  have hf := pole_spindle_F_neutral_bounds z hz hz1
  have hcoef : 0 ≤ k^2-1 := by nlinarith
  have ha : 0 ≤ (k^2-1)*poleSpindleF z := mul_nonneg hcoef hf.1
  have hroot : 1 ≤ Real.sqrt (1+(k^2-1)*poleSpindleF z) :=
    Real.one_le_sqrt.mpr (by linarith)
  have hrootupper : Real.sqrt (1+(k^2-1)*poleSpindleF z) ≤
      1+(k^2-1)*poleSpindleF z := Real.sqrt_le_self_iff.mpr (Or.inr (by linarith))
  rw [abs_of_nonneg (by linarith : 0 ≤ Real.sqrt (1+(k^2-1)*poleSpindleF z)-1)]
  have hkK : k^2-1 ≤ K^2 := by nlinarith
  have hp1 := mul_le_mul_of_nonneg_left hf.2 hcoef
  have hp2 := mul_le_mul_of_nonneg_right hkK (show 0 ≤ 3*z by positivity)
  nlinarith

theorem pole_spindle_inverse_cubic_bound (k K x y : ℝ) (hk : 1 ≤ k)
    (hK : k ≤ K) (hx : 0 ≤ x) (hxy : x ≤ y) (hy : y ≤ 1/2)
    (hinv : x*Real.sqrt (1+(k^2-1)*poleSpindleF (x^2)) = y) :
    |x-y| ≤ 3*K^2*y^3 := by
  have hx2 : x^2 ≤ 1/2 := by nlinarith
  have hf := pole_spindle_factor_neutral_bound k K (x^2) hk hK (sq_nonneg _) hx2
  have hroot := le_abs_self (Real.sqrt (1+(k^2-1)*poleSpindleF (x^2))-1)
  have hp := mul_le_mul_of_nonneg_left (hroot.trans hf) hx
  have hpow := pow_le_pow_left₀ hx hxy 3
  have hm := mul_le_mul_of_nonneg_left hpow (show 0 ≤ 3*K^2 by positivity)
  rw [abs_of_nonpos (by linarith : x-y ≤ 0)]
  nlinarith

variable {E : Type*} [NormedAddCommGroup E] [NormedSpace ℝ E]

/-- Cartesian release permits discontinuous hue capacities; only their bound matters at neutral. -/
def poleSpindleCartesian (B : ℝ) (k : E → ℝ) (v : E) : E :=
  Real.sqrt (1+((k v)^2-1)*poleSpindleF (‖v‖^2/B^2)) • v

theorem pole_spindle_cartesian_cubic_bound (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K)
    (v : E) (hv : ‖v‖ < B/2) :
    ‖poleSpindleCartesian B k v-v‖ ≤ (3*K^2/B^2)*‖v‖^3 := by
  have hb2 : 0 < B^2 := sq_pos_of_pos hB
  have hz : 0 ≤ ‖v‖^2/B^2 := by positivity
  have hz1 : ‖v‖^2/B^2 ≤ 1/2 := by
    apply (div_le_iff₀ hb2).2
    nlinarith [mul_nonneg (show 0 ≤ B/2-‖v‖ by linarith)
      (show 0 ≤ B/2+‖v‖ by positivity)]
  have hf := pole_spindle_factor_neutral_bound (k v) K (‖v‖^2/B^2)
    (hk v).1 (hk v).2 hz hz1
  calc
    ‖poleSpindleCartesian B k v-v‖ =
        |Real.sqrt (1+((k v)^2-1)*poleSpindleF (‖v‖^2/B^2))-1| * ‖v‖ := by
      unfold poleSpindleCartesian
      rw [show Real.sqrt (1+((k v)^2-1)*poleSpindleF (‖v‖^2/B^2)) • v-v =
        (Real.sqrt (1+((k v)^2-1)*poleSpindleF (‖v‖^2/B^2))-1) • v by
          rw [sub_smul, one_smul]]
      rw [norm_smul, Real.norm_eq_abs]
    _ ≤ (3*K^2*(‖v‖^2/B^2))*‖v‖ := mul_le_mul_of_nonneg_right hf (norm_nonneg v)
    _ = (3*K^2/B^2)*‖v‖^3 := by ring

/-- A scalar normalized compressor is lifted to the chroma plane without changing hue. -/
def poleSpindleCartesianInverse (B : ℝ) (k : E → ℝ) (g : ℝ → ℝ → ℝ) (v : E) : E :=
  if ‖v‖ = 0 then 0 else (B*g (k v) (‖v‖/B)/‖v‖) • v

theorem pole_spindle_cartesian_inverse_cubic_bound (B K : ℝ) (k : E → ℝ)
    (g : ℝ → ℝ → ℝ) (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K)
    (hg : ∀ κ y, 1 ≤ κ → 0 ≤ y → y ≤ 1/2 →
      0 ≤ g κ y ∧ g κ y ≤ y ∧
        g κ y*Real.sqrt (1+(κ^2-1)*poleSpindleF ((g κ y)^2)) = y)
    (v : E) (hv : ‖v‖ < B/2) :
    ‖poleSpindleCartesianInverse B k g v-v‖ ≤ (3*K^2/B^2)*‖v‖^3 := by
  by_cases hn : ‖v‖ = 0
  · have hv0 : v = 0 := norm_eq_zero.mp hn
    simp [hv0, poleSpindleCartesianInverse]
  have hnpos : 0 < ‖v‖ := lt_of_le_of_ne (norm_nonneg _) (Ne.symm hn)
  have hBn : B ≠ 0 := ne_of_gt hB
  have hy : ‖v‖/B ≤ 1/2 := (div_le_iff₀ hB).2 (by linarith)
  obtain ⟨hx, hxy, hi⟩ := hg (k v) (‖v‖/B) (hk v).1 (by positivity) hy
  have hbound := pole_spindle_inverse_cubic_bound (k v) K (g (k v) (‖v‖/B))
    (‖v‖/B) (hk v).1 (hk v).2 hx hxy hy hi
  calc
    ‖poleSpindleCartesianInverse B k g v-v‖ =
        |B*g (k v) (‖v‖/B)/‖v‖-1| * ‖v‖ := by
      simp only [poleSpindleCartesianInverse, hn, ↓reduceIte]
      rw [show (B*g (k v) (‖v‖/B)/‖v‖) • v-v =
        (B*g (k v) (‖v‖/B)/‖v‖-1) • v by rw [sub_smul, one_smul]]
      rw [norm_smul, Real.norm_eq_abs]
    _ = B*|g (k v) (‖v‖/B)-‖v‖/B| := by
      rw [show B*g (k v) (‖v‖/B)/‖v‖-1 =
        (B/‖v‖)*(g (k v) (‖v‖/B)-‖v‖/B) by field_simp]
      rw [abs_mul, abs_of_nonneg (show 0 ≤ B/‖v‖ by positivity)]
      field_simp
    _ ≤ B*(3*K^2*(‖v‖/B)^3) := mul_le_mul_of_nonneg_left hbound hB.le
    _ = (3*K^2/B^2)*‖v‖^3 := by field_simp

/-- Full Fréchet derivative, valid under arbitrary bounded hue dependence. -/
theorem pole_spindle_cartesian_neutral_derivative (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) :
    HasFDerivAt (poleSpindleCartesian B k) (ContinuousLinearMap.id ℝ E) 0 := by
  exact cartesian_neutral_of_cubic_bound _ (3*K^2/B^2) (B/2) (by positivity)
    (by simp [poleSpindleCartesian]) (pole_spindle_cartesian_cubic_bound B K k hB hk)

/-- Cartesian inverse derivative follows from its scalar inverse equation and radius bound. -/
theorem pole_spindle_cartesian_inverse_neutral_derivative (B K : ℝ) (k : E → ℝ)
    (g : ℝ → ℝ → ℝ) (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K)
    (hg : ∀ κ y, 1 ≤ κ → 0 ≤ y → y ≤ 1/2 →
      0 ≤ g κ y ∧ g κ y ≤ y ∧
        g κ y*Real.sqrt (1+(κ^2-1)*poleSpindleF ((g κ y)^2)) = y) :
    HasFDerivAt (poleSpindleCartesianInverse B k g) (ContinuousLinearMap.id ℝ E) 0 := by
  exact cartesian_neutral_of_cubic_bound _ (3*K^2/B^2) (B/2) (by positivity)
    (by simp [poleSpindleCartesianInverse])
    (pole_spindle_cartesian_inverse_cubic_bound B K k g hB hk hg)

/-- Concrete closed-form compression has the same hue-independent Cartesian derivative. -/
theorem pole_spindle_closed_inverse_cartesian_neutral_derivative (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) :
    HasFDerivAt (poleSpindleCartesianInverse B k poleSpindleCompress)
      (ContinuousLinearMap.id ℝ E) 0 := by
  apply pole_spindle_cartesian_inverse_neutral_derivative B K k poleSpindleCompress hB hk
  intro κ y hκ hy hy1
  have hi := pole_spindle_release_compress κ y hκ ⟨hy, by linarith⟩
  refine ⟨hi.1.1, ?_, hi.2⟩
  have hx := hi.1
  have hp : (poleSpindleCompress κ y)^2 < poleSpindleP := by
    have := pole_spindle_P_bounds.1
    nlinarith [hx.1, hx.2]
  have hF := pole_spindle_F_nonneg ((poleSpindleCompress κ y)^2) (sq_nonneg _) hp
  have hcoef : 0 ≤ κ^2-1 := by nlinarith
  have hroot : 1 ≤ Real.sqrt (1+(κ^2-1)*poleSpindleF ((poleSpindleCompress κ y)^2)) :=
    Real.one_le_sqrt.mpr (by nlinarith [mul_nonneg hcoef hF])
  have hm := mul_le_mul_of_nonneg_left hroot hx.1
  have he : poleSpindleCompress κ y *
      Real.sqrt (1+(κ^2-1)*poleSpindleF ((poleSpindleCompress κ y)^2)) = y := hi.2
  simpa only [mul_one, he] using hm

/-- The factored-radius implementation has the proved Cartesian neutral derivative too. -/
theorem pole_spindle_stable_inverse_cartesian_neutral_derivative (B K : ℝ) (k : E → ℝ)
    (hB : 0 < B) (hk : ∀ v, 1 ≤ k v ∧ k v ≤ K) :
    HasFDerivAt (poleSpindleCartesianInverse B k poleSpindleCompressStable)
      (ContinuousLinearMap.id ℝ E) 0 := by
  have he : poleSpindleCartesianInverse B k poleSpindleCompressStable =
      poleSpindleCartesianInverse B k poleSpindleCompress := by
    funext v
    simp only [poleSpindleCartesianInverse,
      pole_spindle_compress_stable_eq (k v) (‖v‖/B) (hk v).1 (by positivity)]
  rw [he]
  exact pole_spindle_closed_inverse_cartesian_neutral_derivative B K k hB hk


end
end PerceptualGrade
