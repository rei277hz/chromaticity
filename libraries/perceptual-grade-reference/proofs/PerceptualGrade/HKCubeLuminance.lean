import PerceptualGrade.HKGuard
import PerceptualGrade.CubeGuard
import PerceptualGrade.InputRepair

/- Positivity of luminance after the exact-real H–K repair and an ideal cube
   guard. Containment and exact encoding/decoding on the selected output are
   explicit assumptions, not certificates for a numerical capacity table.
   Above cube white, the full cube guard uses its positive white endpoint;
   preservation of J_A and hue is asserted only for the radial guard. -/
namespace PerceptualGrade
noncomputable section
open Set

def hkRepairedEnergy (H C E0 : ℝ) : ℝ :=
  hkGuardEnergy (hkGuardDelta E0 (H^2)) (H^2-66*C)

def hkRepairedRay (H C E0 hue : ℝ) : CubeRay :=
  ⟨signedRoot (hkRepairedEnergy H C E0), hue,
    hkGuardChroma (H^2) C (hkRepairedEnergy H C E0)⟩

/-- The algebraic repair is nonnegative even at zero reference energy or H=0.
    Its executable application requires the nonnegative-H repair branch. -/
theorem hk_repaired_energy_nonnegative (H C E0 : ℝ)
    (hH : 0 ≤ H) (h0 : 0 ≤ E0) :
    0 ≤ hkRepairedEnergy H C E0 := by
  exact hk_guard_energy_nonnegative _ _
    (hk_guard_delta_bounds E0 (H^2) h0 (pow_nonneg hH 2)).1

theorem hk_repaired_ray_ja_nonnegative (H C E0 hue : ℝ)
    (hH : 0 ≤ H) (h0 : 0 ≤ E0) :
    0 ≤ (hkRepairedRay H C E0 hue).ja := by
  exact signed_root_nonneg _ (hk_repaired_energy_nonnegative H C E0 hH h0)

/-- No lower bound on the requested deficit H²−66C is needed. In particular,
    the request may lie on either side of raw J_A=0. -/
theorem hk_repaired_energy_positive (H C E0 : ℝ) (hH : 0 < H) (h0 : 0 < E0) :
    0 < hkRepairedEnergy H C E0 := by
  exact hk_guard_energy_positive _ _
    (hk_guard_delta_positive E0 (H^2) h0 (sq_pos_of_pos hH))

theorem hk_repaired_ray_energy (H C E0 hue : ℝ) :
    signedEnergy (hkRepairedRay H C E0 hue).ja = hkRepairedEnergy H C E0 := by
  exact signed_energy_root _

theorem hk_repaired_ray_ja_positive (H C E0 hue : ℝ) (hH : 0 < H) (h0 : 0 < E0) :
    0 < (hkRepairedRay H C E0 hue).ja := by
  have he := hk_repaired_energy_positive H C E0 hH h0
  change 0 < signedRoot (hkRepairedEnergy H C E0)
  simpa [signedRoot, he.le] using (Real.sqrt_pos.mpr he)

/-- The repaired H and C coordinates encode exactly the same positive
    energy carried by the guard; positivity is not merely metadata. -/
theorem hk_repaired_coordinates_energy (H C E0 : ℝ) :
    (Real.sqrt (H^2+hkGuardLift (H^2) (hkRepairedEnergy H C E0) (H^2-66*C)))^2-
      66*hkGuardChroma (H^2) C (hkRepairedEnergy H C E0) = hkRepairedEnergy H C E0 := by
  have hz : 0 ≤ hkRepairedEnergy H C E0-(H^2-66*C) :=
    sub_nonneg.mpr (hk_guard_energy_above_request _ _)
  have hg : 0 ≤ hkGuardLift (H^2) (hkRepairedEnergy H C E0) (H^2-66*C) :=
    hk_guard_allocation_nonnegative _ _ (by positivity) hz
  rw [Real.sq_sqrt (add_nonneg (sq_nonneg H) hg)]
  exact hk_guard_projection_energy _ _ _

theorem hk_repaired_ray_chroma_bounds (H C E0 hue : ℝ)
    (hC : 0 ≤ C) (h0 : 0 ≤ E0) :
    0 ≤ (hkRepairedRay H C E0 hue).chroma ∧
      (hkRepairedRay H C E0 hue).chroma ≤ C := by
  exact hk_guard_projection_chroma_bounds (H^2) C (hkRepairedEnergy H C E0)
    (sq_nonneg H)
    (hk_guard_energy_le_height E0 (H^2) (H^2-66*C) h0 (sq_nonneg H) (by linarith))
    (hk_guard_energy_above_request _ _)

/-- The strict positive-reference hypothesis is necessary: H>0 alone does
    not exclude the degenerate zero-energy/black endpoint. -/
theorem hk_repaired_zero_reference_counterexample :
    (0 : ℝ) < 1 ∧ hkRepairedEnergy 1 1 0 = 0 := by
  norm_num [hkRepairedEnergy, hkGuardEnergy, hkGuardDelta]

theorem hk_zero_reference_cube_black (W hue : ℝ) (U : ℝ → ℝ → ℝ) :
    cubeGuard W U (hkRepairedRay 1 1 0 hue) = ⟨0, 0, 0⟩ := by
  apply cube_guard_black
  have hz := hk_repaired_zero_reference_counterexample.2
  simp [hkRepairedRay, hz, signedRoot]

/-- Positive encoded energy excludes RGB black without assuming a direct
    proportionality between achromatic energy and physical luminance. -/
theorem encoded_positive_energy_nonblack
    (encodeEnergy : (Fin 3 → ℝ) → ℝ) (rgb : Fin 3 → ℝ)
    (hblack : encodeEnergy (fun _ => 0) = 0)
    (he : 0 < encodeEnergy rgb) : ∃ i, rgb i ≠ 0 := by
  by_contra hn
  simp only [not_exists, not_not] at hn
  have hz : rgb = fun _ => 0 := funext hn
  rw [hz, hblack] at he
  exact lt_irrefl _ he

/-- The only RGB facts needed are nonnegative channels, positive Y weights,
    exact carried-energy encoding, and zero energy for RGB black. -/
theorem encoded_positive_energy_luminance
    (encodeEnergy : (Fin 3 → ℝ) → ℝ) (rgb weights : Fin 3 → ℝ)
    (hblack : encodeEnergy (fun _ => 0) = 0)
    (he : 0 < encodeEnergy rgb) (hlegal : ∀ i, 0 ≤ rgb i)
    (hw : ∀ i, 0 < weights i) : 0 < rgbY weights rgb := by
  exact rgb_y_positive weights rgb hw hlegal
    (encoded_positive_energy_nonblack encodeEnergy rgb hblack he)

/-- Local composition contract. Any ideal output preserving J_A and having
    legal nonnegative RGB has positive Y after the actual H–K energy repair.
    No chroma-only guard can turn this positive energy into black. -/
theorem hk_ideal_cube_positive_luminance
    (H C E0 hue : ℝ) (output : CubeRay)
    (decode : CubeRay → Fin 3 → ℝ) (encodeEnergy : (Fin 3 → ℝ) → ℝ)
    (weights : Fin 3 → ℝ) (hH : 0 < H) (h0 : 0 < E0)
    (hja : output.ja = (hkRepairedRay H C E0 hue).ja)
    (hlegal : ∀ i, 0 ≤ decode output i)
    (hencode : encodeEnergy (decode output) = signedEnergy output.ja)
    (hblack : encodeEnergy (fun _ => 0) = 0)
    (hw : ∀ i, 0 < weights i) : 0 < rgbY weights (decode output) := by
  apply encoded_positive_energy_luminance encodeEnergy (decode output) weights hblack
    _ hlegal hw
  rw [hencode, hja, hk_repaired_ray_energy]
  exact hk_repaired_energy_positive H C E0 hH h0

/-- The existing ideal radial guard supplies J_A/hue preservation and chroma
    reduction by construction. Only legality and the local decoder energy
    identity remain assumptions; no numerical cube-fit accuracy is assumed. -/
theorem hk_cube_ray_guard_positive_luminance
    (H C E0 hue : ℝ) (U : ℝ → ℝ → ℝ)
    (decode : CubeRay → Fin 3 → ℝ) (encodeEnergy : (Fin 3 → ℝ) → ℝ)
    (weights : Fin 3 → ℝ) (hH : 0 < H) (h0 : 0 < E0)
    (hlegal : ∀ i, 0 ≤ decode (cubeRayGuard U (hkRepairedRay H C E0 hue)) i)
    (hencode : encodeEnergy (decode (cubeRayGuard U (hkRepairedRay H C E0 hue))) =
      signedEnergy (cubeRayGuard U (hkRepairedRay H C E0 hue)).ja)
    (hblack : encodeEnergy (fun _ => 0) = 0) (hw : ∀ i, 0 < weights i) :
    0 < rgbY weights (decode (cubeRayGuard U (hkRepairedRay H C E0 hue))) ∧
      (cubeRayGuard U (hkRepairedRay H C E0 hue)).hue = hue ∧
      (cubeRayGuard U (hkRepairedRay H C E0 hue)).chroma ≤
        (hkRepairedRay H C E0 hue).chroma := by
  refine ⟨?_, rfl, cube_ray_guard_chroma_nonincrease _ _⟩
  exact hk_ideal_cube_positive_luminance H C E0 hue _ decode encodeEnergy weights hH h0
    rfl hlegal hencode hblack hw

/-- Derive radial-guard legality from a whole-ray cube-prefix certificate,
    instead of assuming the selected output is legal directly. The only
    decoder law needed for luminance is the local carried-energy identity;
    the capacity table itself is not required to be fitted accurately. -/
theorem hk_cube_ray_guard_positive_luminance_from_prefix
    (H C E0 hue : ℝ) (U : ℝ → ℝ → ℝ)
    (decode : CubeRay → Fin 3 → ℝ) (encodeEnergy : (Fin 3 → ℝ) → ℝ)
    (weights : Fin 3 → ℝ) (hH : 0 < H) (h0 : 0 < E0) (hC : 0 ≤ C)
    (hU : 0 ≤ U (hkRepairedRay H C E0 hue).ja (hkRepairedRay H C E0 hue).hue)
    (hprefix : ∀ c ∈ Icc 0 (U (hkRepairedRay H C E0 hue).ja
        (hkRepairedRay H C E0 hue).hue),
        rgbInCube (decode ⟨(hkRepairedRay H C E0 hue).ja,
          (hkRepairedRay H C E0 hue).hue, c⟩))
    (hencode : ∀ p, encodeEnergy (decode p) = signedEnergy p.ja)
    (hblack : encodeEnergy (fun _ => 0) = 0) (hw : ∀ i, 0 < weights i) :
    0 < rgbY weights (decode (cubeRayGuard U (hkRepairedRay H C E0 hue))) := by
  have hc := hk_repaired_ray_chroma_bounds H C E0 hue hC (le_of_lt h0)
  have hlegal := cube_ray_guard_containment decode U (hkRepairedRay H C E0 hue)
    hc.1 hU hprefix
  exact (hk_cube_ray_guard_positive_luminance H C E0 hue U decode encodeEnergy weights
    hH h0 (fun i => (hlegal i).1) (hencode _) hblack hw).1

/-- Positive achromatic energy survives the full ideal guard. Its upper
    endpoint changes energy to W², which is still positive when W>0. -/
theorem cube_guard_positive_energy (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hW : 0 < W) (he : 0 < signedEnergy p.ja) :
    0 < signedEnergy (cubeGuard W U p).ja := by
  have hj : 0 < p.ja := by
    by_contra hn
    have hp := mul_nonpos_of_nonpos_of_nonneg (le_of_not_gt hn) (abs_nonneg p.ja)
    change p.ja*|p.ja| > 0 at he
    linarith
  by_cases hwhite : W ≤ p.ja
  · rw [cube_guard_white W U p hj hwhite]
    exact mul_pos hW (abs_pos.mpr (ne_of_gt hW))
  · rw [cube_guard_interior W U p hj (lt_of_not_ge hwhite)]
    exact he

/-- Complete exact-real composition including the white endpoint. Local
    output containment and decode/encode consistency are the minimal ideal
    cube contract. This is not a floating-point containment certificate. -/
theorem hk_cube_guard_positive_luminance
    (H C E0 hue W : ℝ) (U : ℝ → ℝ → ℝ)
    (decode : CubeRay → Fin 3 → ℝ) (encodeEnergy : (Fin 3 → ℝ) → ℝ)
    (weights : Fin 3 → ℝ) (hH : 0 < H) (h0 : 0 < E0) (hW : 0 < W)
    (hlegal : rgbInCube (decode (cubeGuard W U (hkRepairedRay H C E0 hue))))
    (hencode : encodeEnergy (decode (cubeGuard W U (hkRepairedRay H C E0 hue))) =
      signedEnergy (cubeGuard W U (hkRepairedRay H C E0 hue)).ja)
    (hblack : encodeEnergy (fun _ => 0) = 0) (hw : ∀ i, 0 < weights i) :
    0 < rgbY weights (decode (cubeGuard W U (hkRepairedRay H C E0 hue))) := by
  apply encoded_positive_energy_luminance encodeEnergy _ weights hblack _
    (fun i => (hlegal i).1) hw
  rw [hencode]
  apply cube_guard_positive_energy W U _ hW
  rw [hk_repaired_ray_energy]
  exact hk_repaired_energy_positive H C E0 hH h0

end
end PerceptualGrade
