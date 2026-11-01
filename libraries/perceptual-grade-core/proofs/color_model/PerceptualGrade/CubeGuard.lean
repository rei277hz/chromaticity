import PerceptualGrade.SignedAppearance

namespace PerceptualGrade
noncomputable section
open Set

/-- Raw fixed-height/hue radial coordinates. The exact capacity used in these
theorems is the actual cube-ray prefix, not the executable fitted lookup seed. -/
structure CubeRay where
  ja : ℝ
  hue : ℝ
  chroma : ℝ
  deriving DecidableEq

def cubeRayGuard (U : ℝ → ℝ → ℝ) (p : CubeRay) : CubeRay :=
  { p with chroma := min p.chroma (U p.ja p.hue) }

def cubeGuard (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay) : CubeRay :=
  if p.ja ≤ 0 then ⟨0, 0, 0⟩ else
  if W ≤ p.ja then ⟨W, 0, 0⟩ else cubeRayGuard U p

def rgbInCube (rgb : Fin 3 → ℝ) : Prop := ∀ i, rgb i ∈ Icc 0 1024

theorem cube_ray_guard_identity (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hp : p.chroma ≤ U p.ja p.hue) : cubeRayGuard U p = p := by
  cases p
  simp_all [cubeRayGuard]

theorem cube_ray_guard_idempotent (U : ℝ → ℝ → ℝ) (p : CubeRay) :
    cubeRayGuard U (cubeRayGuard U p) = cubeRayGuard U p := by
  simp [cubeRayGuard]

theorem cube_ray_guard_preserves_ja_hue (U : ℝ → ℝ → ℝ) (p : CubeRay) :
    (cubeRayGuard U p).ja = p.ja ∧ (cubeRayGuard U p).hue = p.hue := by
  exact ⟨rfl, rfl⟩

theorem cube_ray_guard_chroma_nonincrease (U : ℝ → ℝ → ℝ) (p : CubeRay) :
    (cubeRayGuard U p).chroma ≤ p.chroma := min_le_left _ _

theorem cube_ray_guard_hk_nonincrease (U : ℝ → ℝ → ℝ) (p : CubeRay) :
    Real.sqrt ((cubeRayGuard U p).ja^2 + 66*(cubeRayGuard U p).chroma) ≤
      Real.sqrt (p.ja^2 + 66*p.chroma) := by
  apply Real.sqrt_le_sqrt
  have hc := cube_ray_guard_chroma_nonincrease U p
  change p.ja^2 + 66*(cubeRayGuard U p).chroma ≤ p.ja^2 + 66*p.chroma
  linarith

theorem cube_ray_guard_radius_bounds (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hC : 0 ≤ p.chroma) (hU : 0 ≤ U p.ja p.hue) :
    (cubeRayGuard U p).chroma ∈ Icc 0 (U p.ja p.hue) := by
  exact ⟨le_min hC hU, min_le_right _ _⟩

/-- Containment requires a certificate for every radius in the cube prefix.
A fitted endpoint alone does not establish this hypothesis. -/
theorem cube_ray_guard_containment (decode : CubeRay → Fin 3 → ℝ)
    (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hC : 0 ≤ p.chroma) (hU : 0 ≤ U p.ja p.hue)
    (hprefix : ∀ c ∈ Icc 0 (U p.ja p.hue), rgbInCube (decode ⟨p.ja, p.hue, c⟩)) :
    rgbInCube (decode (cubeRayGuard U p)) := by
  exact hprefix _ (cube_ray_guard_radius_bounds U p hC hU)

theorem cube_guard_black (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hJ : p.ja ≤ 0) : cubeGuard W U p = ⟨0, 0, 0⟩ := by
  simp [cubeGuard, hJ]

theorem cube_guard_white (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hJ : 0 < p.ja) (hW : W ≤ p.ja) : cubeGuard W U p = ⟨W, 0, 0⟩ := by
  simp [cubeGuard, not_le_of_gt hJ, hW]

theorem cube_guard_interior (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hJ : 0 < p.ja) (hW : p.ja < W) : cubeGuard W U p = cubeRayGuard U p := by
  simp [cubeGuard, not_le_of_gt hJ, not_le_of_gt hW]

theorem cube_guard_identity (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hJ : 0 < p.ja) (hW : p.ja < W) (hp : p.chroma ≤ U p.ja p.hue) :
    cubeGuard W U p = p := by
  rw [cube_guard_interior W U p hJ hW, cube_ray_guard_identity U p hp]

theorem cube_guard_idempotent (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hW : 0 < W) : cubeGuard W U (cubeGuard W U p) = cubeGuard W U p := by
  by_cases hj : p.ja ≤ 0
  · simp [cubeGuard, hj]
  · by_cases hw : W ≤ p.ja
    · simp [cubeGuard, hj, hw, not_le_of_gt hW]
    · simp [cubeGuard, hj, hw, cubeRayGuard]

theorem cube_guard_preserves_ja_hue (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hJ : 0 < p.ja) (hW : p.ja < W) :
    (cubeGuard W U p).ja = p.ja ∧ (cubeGuard W U p).hue = p.hue := by
  rw [cube_guard_interior W U p hJ hW]
  exact cube_ray_guard_preserves_ja_hue U p

theorem cube_guard_nonpositive_energy (W : ℝ) (U : ℝ → ℝ → ℝ) (E h C : ℝ)
    (hE : E ≤ 0) : cubeGuard W U ⟨signedRoot E, h, C⟩ = ⟨0, 0, 0⟩ := by
  apply cube_guard_black
  by_cases hz : E = 0
  · simp [hz, signedRoot]
  · exact le_of_lt (signed_root_negative E (lt_of_le_of_ne hE hz))

theorem cube_guard_white_energy (W : ℝ) (U : ℝ → ℝ → ℝ) (E h C : ℝ)
    (hW : 0 < W) (hE : W^2 ≤ E) :
    cubeGuard W U ⟨signedRoot E, h, C⟩ = ⟨W, 0, 0⟩ := by
  have he : 0 ≤ E := le_trans (sq_nonneg W) hE
  have hj := signed_root_nonneg E he
  have hs := signed_root_squared E
  rw [abs_of_nonneg he] at hs
  have hw : W ≤ signedRoot E := by nlinarith
  exact cube_guard_white W U _ (lt_of_lt_of_le hW hw) hw

theorem cube_guard_interior_energy (W : ℝ) (U : ℝ → ℝ → ℝ) (E h C : ℝ)
    (hW : 0 < W) (hE : 0 < E) (heW : E < W^2) :
    signedEnergy (cubeGuard W U ⟨signedRoot E, h, C⟩).ja = E ∧
    (cubeGuard W U ⟨signedRoot E, h, C⟩).hue = h := by
  have hj := signed_root_nonneg E (le_of_lt hE)
  have hs := signed_root_squared E
  rw [abs_of_nonneg (le_of_lt hE)] at hs
  have hj0 : 0 < signedRoot E := by nlinarith
  have hjW : signedRoot E < W := by nlinarith
  have hp := cube_guard_preserves_ja_hue W U ⟨signedRoot E, h, C⟩ hj0 hjW
  rw [hp.1, signed_energy_root]
  exact ⟨rfl, hp.2⟩

theorem cube_guard_chroma_nonincrease (W : ℝ) (U : ℝ → ℝ → ℝ) (p : CubeRay)
    (hC : 0 ≤ p.chroma) : (cubeGuard W U p).chroma ≤ p.chroma := by
  unfold cubeGuard
  split_ifs <;> first
  | exact hC
  | exact cube_ray_guard_chroma_nonincrease U p

theorem cube_guard_containment (W : ℝ) (U : ℝ → ℝ → ℝ)
    (decode : CubeRay → Fin 3 → ℝ) (p : CubeRay) (hC : 0 ≤ p.chroma)
    (hblack : rgbInCube (decode ⟨0, 0, 0⟩))
    (hwhite : rgbInCube (decode ⟨W, 0, 0⟩))
    (hU : ∀ j h, 0 < j → j < W → 0 ≤ U j h)
    (hprefix : ∀ j h, 0 < j → j < W →
      ∀ c ∈ Icc 0 (U j h), rgbInCube (decode ⟨j, h, c⟩)) :
    rgbInCube (decode (cubeGuard W U p)) := by
  by_cases hj : p.ja ≤ 0
  · simpa [cubeGuard, hj] using hblack
  · by_cases hw : W ≤ p.ja
    · simpa [cubeGuard, hj, hw] using hwhite
    · rw [cube_guard_interior W U p (lt_of_not_ge hj) (lt_of_not_ge hw)]
      exact cube_ray_guard_containment decode U p hC
        (hU p.ja p.hue (lt_of_not_ge hj) (lt_of_not_ge hw))
        (hprefix p.ja p.hue (lt_of_not_ge hj) (lt_of_not_ge hw))

/-- The executable guard uses tested decoded RGB, not an assumed fitted
capacity certificate. Each refinement keeps its tested-valid lower endpoint. -/
def testedCubeRadius (legal : ℝ → Prop) [DecidablePred legal] : ℕ → ℝ → ℝ → ℝ
  | 0, lo, _ => lo
  | n+1, lo, hi =>
    let mid := (lo+hi)/2
    if legal mid then testedCubeRadius legal n mid hi
    else testedCubeRadius legal n lo mid

theorem tested_cube_radius_valid (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (lo hi : ℝ) (hlo : legal lo) : legal (testedCubeRadius legal n lo hi) := by
  induction n generalizing lo hi with
  | zero => exact hlo
  | succ n ih =>
    simp only [testedCubeRadius]
    split_ifs with hm
    · exact ih _ _ hm
    · exact ih _ _ hlo

theorem tested_cube_radius_bounds (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (lo hi : ℝ) (horder : lo ≤ hi) :
    testedCubeRadius legal n lo hi ∈ Icc lo hi := by
  induction n generalizing lo hi with
  | zero => exact ⟨le_refl _, horder⟩
  | succ n ih =>
    simp only [testedCubeRadius]
    split_ifs
    · have hm : (lo+hi)/2 ≤ hi := by linarith
      have h := ih ((lo+hi)/2) hi hm
      exact ⟨by linarith [h.1], h.2⟩
    · have hm : lo ≤ (lo+hi)/2 := by linarith
      have h := ih lo ((lo+hi)/2) hm
      exact ⟨h.1, by linarith [h.2]⟩

/-- Finite decoded-pixel validation suffices for containment at every budget.
No monotonicity of the legality predicate or fit accuracy is assumed. -/
theorem tested_cube_radius_containment (decode : ℝ → Fin 3 → ℝ)
    [DecidablePred fun c => rgbInCube (decode c)]
    (n : ℕ) (lo hi : ℝ) (hlo : rgbInCube (decode lo)) :
    rgbInCube (decode (testedCubeRadius (fun c => rgbInCube (decode c)) n lo hi)) := by
  exact tested_cube_radius_valid (fun c => rgbInCube (decode c)) n lo hi hlo

/-- A legal request is returned exactly; otherwise refinement only contracts. -/
def validatedCubeRadius (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (C cap : ℝ) : ℝ :=
  if legal C then C else testedCubeRadius legal n 0 (min C cap)

theorem validated_cube_radius_identity (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (C cap : ℝ) (hC : legal C) : validatedCubeRadius legal n C cap = C := by
  simp [validatedCubeRadius, hC]

theorem validated_cube_radius_valid (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (C cap : ℝ) (hzero : legal 0) : legal (validatedCubeRadius legal n C cap) := by
  unfold validatedCubeRadius
  split_ifs with hC
  · exact hC
  · exact tested_cube_radius_valid legal n 0 _ hzero

theorem validated_cube_radius_idempotent (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (C cap : ℝ) (hzero : legal 0) :
    validatedCubeRadius legal n (validatedCubeRadius legal n C cap) cap =
      validatedCubeRadius legal n C cap := by
  exact validated_cube_radius_identity _ _ _ _ (validated_cube_radius_valid legal n C cap hzero)

theorem validated_cube_radius_nonincrease (legal : ℝ → Prop) [DecidablePred legal]
    (n : ℕ) (C cap : ℝ) (hC : 0 ≤ C) (hcap : 0 ≤ cap) :
    validatedCubeRadius legal n C cap ∈ Icc 0 C := by
  unfold validatedCubeRadius
  split_ifs
  · exact ⟨hC, le_refl _⟩
  · have h := tested_cube_radius_bounds legal n 0 (min C cap) (le_min hC hcap)
    exact ⟨h.1, h.2.trans (min_le_left _ _)⟩

/-- The validated guard uses a safe cone-box cap; fitted cube capacity may
provide trial seeds but is not assumed to bound the actual cube. -/
def validatedCubeRayGuard (legal : CubeRay → Prop) [DecidablePred legal]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay) : CubeRay :=
  { p with chroma :=
      validatedCubeRadius (fun c => legal ⟨p.ja, p.hue, c⟩) n p.chroma (cap p.ja p.hue) }

theorem validated_cube_guard_identity (legal : CubeRay → Prop) [DecidablePred legal]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay) (hp : legal p) :
    validatedCubeRayGuard legal cap n p = p := by
  cases p
  simp_all [validatedCubeRayGuard, validatedCubeRadius]

theorem validated_cube_guard_valid (legal : CubeRay → Prop) [DecidablePred legal]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay) (hzero : legal ⟨p.ja, p.hue, 0⟩) :
    legal (validatedCubeRayGuard legal cap n p) := by
  exact validated_cube_radius_valid (fun c => legal ⟨p.ja, p.hue, c⟩)
    n p.chroma (cap p.ja p.hue) hzero

theorem validated_cube_guard_idempotent (legal : CubeRay → Prop) [DecidablePred legal]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay) (hzero : legal ⟨p.ja, p.hue, 0⟩) :
    validatedCubeRayGuard legal cap n (validatedCubeRayGuard legal cap n p) =
      validatedCubeRayGuard legal cap n p := by
  exact validated_cube_guard_identity legal cap n _
    (validated_cube_guard_valid legal cap n p hzero)

theorem validated_cube_guard_preserves_ja_hue (legal : CubeRay → Prop) [DecidablePred legal]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay) :
    (validatedCubeRayGuard legal cap n p).ja = p.ja ∧
    (validatedCubeRayGuard legal cap n p).hue = p.hue := by
  exact ⟨rfl, rfl⟩

theorem validated_cube_guard_nonincrease (legal : CubeRay → Prop) [DecidablePred legal]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay)
    (hC : 0 ≤ p.chroma) (hcap : 0 ≤ cap p.ja p.hue) :
    (validatedCubeRayGuard legal cap n p).chroma ∈ Icc 0 p.chroma := by
  exact validated_cube_radius_nonincrease (fun c => legal ⟨p.ja, p.hue, c⟩)
    n p.chroma (cap p.ja p.hue) hC hcap

/-- This containment statement depends solely on tested decoded pixels and
the legal neutral bracket. It makes no fit-accuracy or ray-monotonicity claim. -/
theorem validated_cube_guard_containment (decode : CubeRay → Fin 3 → ℝ)
    [DecidablePred fun p => rgbInCube (decode p)]
    (cap : ℝ → ℝ → ℝ) (n : ℕ) (p : CubeRay)
    (hzero : rgbInCube (decode ⟨p.ja, p.hue, 0⟩)) :
    rgbInCube (decode (validatedCubeRayGuard (fun p => rgbInCube (decode p)) cap n p)) := by
  exact validated_cube_guard_valid (fun p => rgbInCube (decode p)) cap n p hzero

end
end PerceptualGrade
