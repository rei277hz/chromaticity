import PerceptualGrade.HKCubeLuminance
import PerceptualGrade.WarpGuardChart

/- Corrected Warp ordering: Adaptance, H–K repair, then common positive
   J_A/chroma Scale. These exact-real claims stop before RGB cube projection.
   The repaired branch assumes nonnegative post-Tone reference energy; the
   executable negative-H bypass is not asserted to have nonnegative energy. -/
namespace PerceptualGrade
noncomputable section
open Set

def warpScaledRay (p : CubeRay) (k : ℝ) : CubeRay :=
  ⟨k*p.ja, p.hue, k*p.chroma⟩

def warpRayPad (p : CubeRay) : ℝ × ℝ :=
  (boundedSaturationCoordinate (p.chroma*Real.cos p.hue) p.chroma (signedEnergy p.ja),
    boundedSaturationCoordinate (p.chroma*Real.sin p.hue) p.chroma (signedEnergy p.ja))

def warpPositiveScaleHeight (E C k : ℝ) : ℝ := Real.sqrt (k^2*E+66*k*C)

/-- Carried energy follows the squared scale exactly; it is not reconstructed
    by subtracting two appearance coordinates. -/
theorem warp_scale_energy (p : CubeRay) (k : ℝ) (hk : 0 < k) :
    signedEnergy (warpScaledRay p k).ja = k^2*signedEnergy p.ja := by
  exact signed_energy_positive_scale k p.ja hk

theorem warp_scale_pad_invariant (p : CubeRay) (k : ℝ) (hk : 0 < k) :
    warpRayPad (warpScaledRay p k) = warpRayPad p := by
  unfold warpRayPad warpScaledRay
  simp only [signed_energy_positive_scale k p.ja hk]
  rw [show k*p.chroma*Real.cos p.hue = k*(p.chroma*Real.cos p.hue) by ring,
    show k*p.chroma*Real.sin p.hue = k*(p.chroma*Real.sin p.hue) by ring]
  exact warp_compact_coordinates_scale _ _ _ _ k hk

theorem warp_scale_radius_invariant (p : CubeRay) (k : ℝ) (hk : 0 < k) :
    warpCompactRadiusSq (warpScaledRay p k).chroma
        (signedEnergy (warpScaledRay p k).ja) =
      warpCompactRadiusSq p.chroma (signedEnergy p.ja) := by
  rw [warp_scale_energy p k hk]
  exact warp_compact_radius_scale _ _ k hk

/-- On the repaired branch the signed appearance law is its positive branch.
    This excludes the diagnostic negative-ray turning point. -/
theorem warp_positive_scale_signed_hk (E C k : ℝ)
    (hE : 0 ≤ E) (hC : 0 ≤ C) (hk : 0 < k) :
    signedHK (k*signedRoot E) (Real.sqrt (66*(k*C))) =
      warpPositiveScaleHeight E C k := by
  have hj : 0 ≤ k*signedRoot E := mul_nonneg hk.le (signed_root_nonneg E hE)
  simp only [signedHK, hj, ite_true, hkMagnitude, mul_pow,
    signed_root_squared, abs_of_nonneg hE, Real.sq_sqrt (by positivity : 0 ≤ 66*(k*C))]
  unfold warpPositiveScaleHeight
  congr 1
  ring

theorem warp_positive_scale_height_monotone (E C : ℝ) (hE : 0 ≤ E) (hC : 0 ≤ C) :
    MonotoneOn (warpPositiveScaleHeight E C) (Ici 0) := by
  intro k₁ hk₁ k₂ hk₂ hle
  change 0 ≤ k₁ at hk₁
  change 0 ≤ k₂ at hk₂
  have hs : k₁^2 ≤ k₂^2 := by nlinarith
  have he := mul_le_mul_of_nonneg_right hs hE
  have hc := mul_le_mul_of_nonneg_right hle hC
  apply Real.sqrt_le_sqrt
  nlinarith

/-- Every nonblack repaired state rises strictly with positive Scale, including
    zero energy with positive chroma and positive energy on the neutral axis. -/
theorem warp_positive_scale_height_strict_mono (E C : ℝ)
    (hE : 0 ≤ E) (hC : 0 ≤ C) (hnb : 0 < E ∨ 0 < C) :
    StrictMonoOn (warpPositiveScaleHeight E C) (Ioi 0) := by
  intro k₁ hk₁ k₂ hk₂ hlt
  change 0 < k₁ at hk₁
  change 0 < k₂ at hk₂
  have hs : k₁^2 < k₂^2 := by nlinarith
  apply Real.sqrt_lt_sqrt (by positivity : 0 ≤ k₁^2*E+66*k₁*C)
  rcases hnb with he | hc
  · have he' := mul_lt_mul_of_pos_right hs he
    have hc' := mul_le_mul_of_nonneg_right hlt.le hC
    nlinarith
  · have he' := mul_le_mul_of_nonneg_right hs.le hE
    have hc' := mul_lt_mul_of_pos_right hlt hc
    nlinarith

theorem warp_positive_scale_height_black (k : ℝ) :
    warpPositiveScaleHeight 0 0 k = 0 := by
  simp [warpPositiveScaleHeight]

/-- H=0 and zero-reference degeneracies remain nonnegative under Scale. -/
theorem warp_repaired_scale_ja_nonnegative (H C E0 hue k : ℝ)
    (hH : 0 ≤ H) (h0 : 0 ≤ E0) (hk : 0 < k) :
    0 ≤ (warpScaledRay (hkRepairedRay H C E0 hue) k).ja := by
  exact mul_nonneg hk.le (hk_repaired_ray_ja_nonnegative H C E0 hue hH h0)

theorem warp_repaired_scale_ja_positive (H C E0 hue k : ℝ)
    (hH : 0 < H) (h0 : 0 < E0) (hk : 0 < k) :
    0 < (warpScaledRay (hkRepairedRay H C E0 hue) k).ja := by
  exact mul_pos hk (hk_repaired_ray_ja_positive H C E0 hue hH h0)

theorem warp_repaired_scale_energy (H C E0 hue k : ℝ) (hk : 0 < k) :
    signedEnergy (warpScaledRay (hkRepairedRay H C E0 hue) k).ja =
      k^2*hkRepairedEnergy H C E0 := by
  rw [warp_scale_energy _ k hk, hk_repaired_ray_energy]

theorem warp_repaired_scale_energy_nonnegative (H C E0 hue k : ℝ)
    (hH : 0 ≤ H) (h0 : 0 ≤ E0) (hk : 0 < k) :
    0 ≤ signedEnergy (warpScaledRay (hkRepairedRay H C E0 hue) k).ja := by
  rw [warp_repaired_scale_energy H C E0 hue k hk]
  exact mul_nonneg (sq_nonneg k) (hk_repaired_energy_nonnegative H C E0 hH h0)

theorem warp_repaired_scale_energy_positive (H C E0 hue k : ℝ)
    (hH : 0 < H) (h0 : 0 < E0) (hk : 0 < k) :
    0 < signedEnergy (warpScaledRay (hkRepairedRay H C E0 hue) k).ja := by
  rw [warp_repaired_scale_energy H C E0 hue k hk]
  exact mul_pos (sq_pos_of_pos hk) (hk_repaired_energy_positive H C E0 hH h0)

theorem warp_repaired_scale_pad_invariant (H C E0 hue k : ℝ) (hk : 0 < k) :
    warpRayPad (warpScaledRay (hkRepairedRay H C E0 hue) k) =
      warpRayPad (hkRepairedRay H C E0 hue) := by
  exact warp_scale_pad_invariant _ k hk

/-- Composition with actual repaired energy and chroma, independent of the
    sign of the unguarded requested deficit H²−66C. -/
theorem warp_repaired_scale_height_strict_mono (H C E0 hue : ℝ)
    (hH : 0 < H) (hC : 0 ≤ C) (h0 : 0 < E0) :
    StrictMonoOn (fun k =>
      signedHK (warpScaledRay (hkRepairedRay H C E0 hue) k).ja
        (Real.sqrt (66*(warpScaledRay (hkRepairedRay H C E0 hue) k).chroma)))
      (Ioi 0) := by
  have he := hk_repaired_energy_positive H C E0 hH h0
  have hc := (hk_repaired_ray_chroma_bounds H C E0 hue hC h0.le).1
  intro k₁ hk₁ k₂ hk₂ hlt
  change 0 < k₁ at hk₁
  change 0 < k₂ at hk₂
  change signedHK (k₁*signedRoot (hkRepairedEnergy H C E0))
      (Real.sqrt (66*(k₁*(hkRepairedRay H C E0 hue).chroma))) <
    signedHK (k₂*signedRoot (hkRepairedEnergy H C E0))
      (Real.sqrt (66*(k₂*(hkRepairedRay H C E0 hue).chroma)))
  rw [warp_positive_scale_signed_hk _ _ k₁ he.le hc hk₁,
    warp_positive_scale_signed_hk _ _ k₂ he.le hc hk₂]
  exact warp_positive_scale_height_strict_mono _ _ he.le hc (Or.inl he)
    hk₁ hk₂ hlt

end
end PerceptualGrade
