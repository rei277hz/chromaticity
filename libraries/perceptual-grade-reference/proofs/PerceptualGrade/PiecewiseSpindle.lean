import PerceptualGrade.Spindle

/- Reference radial shoulder: exact rational coefficients and C2 scalar joins. -/
namespace PerceptualGrade
noncomputable section
open Set Filter
open scoped ContDiff Topology

def piecewiseSpindleA (eps k : ℝ) : ℝ := eps*(k-1)/(k*(3/4)^2)
def piecewiseSpindleRs (A : ℝ) : ℝ := 3/4+A*(3/4)^3
def piecewiseSpindleM (A : ℝ) : ℝ := 1+3*A*(3/4)^2
def piecewiseSpindleQ (A : ℝ) : ℝ := 3*A*(3/4)
def piecewiseSpindleH (A k : ℝ) : ℝ := 1072*(k-1)-(1827/2)*A

def piecewiseSpindleCore (A x : ℝ) : ℝ := x+A*x^3
def piecewiseSpindleCoreSlope (A x : ℝ) : ℝ := 1+3*A*x^2
def piecewiseSpindleDenom (t : ℝ) : ℝ := 1+14*t+196*t^2
def piecewiseSpindleTail (rs m Q H t : ℝ) : ℝ :=
  rs+m*t+(Q*t^2+H*t^3)/piecewiseSpindleDenom t
def piecewiseSpindleTailSlope (m Q H t : ℝ) : ℝ :=
  m+(Q*t*(2+14*t)+H*t^2*(3+28*t+196*t^2))/(piecewiseSpindleDenom t)^2
def piecewiseSpindleTailCurvature (Q H t : ℝ) : ℝ :=
  2*(Q*(1-588*t^2-2744*t^3)+3*H*t*(1+14*t))/(piecewiseSpindleDenom t)^3

def piecewiseSpindleRelease (eps k : ℝ) : ℝ → ℝ :=
  let A := piecewiseSpindleA eps k
  joined (3/4) (piecewiseSpindleCore A)
    (fun x => piecewiseSpindleTail (piecewiseSpindleRs A) (piecewiseSpindleM A)
      (piecewiseSpindleQ A) (piecewiseSpindleH A k) (x-3/4))

def piecewiseSpindleExterior (k M E delta u : ℝ) : ℝ :=
  k+M*u+E*u^2/(1-u/delta)
def piecewiseSpindleExteriorSlope (M E delta u : ℝ) : ℝ :=
  M+E*delta*u*(2*delta-u)/(delta-u)^2
def piecewiseSpindleExteriorCurvature (E delta u : ℝ) : ℝ :=
  2*E*delta^3/(delta-u)^3

theorem piecewise_spindle_denominator_lower (t : ℝ) :
    3/4 ≤ piecewiseSpindleDenom t := by
  unfold piecewiseSpindleDenom
  nlinarith [sq_nonneg (14*t+1/2)]

theorem piecewise_spindle_denominator_pos (t : ℝ) :
    0 < piecewiseSpindleDenom t := by
  linarith [piecewise_spindle_denominator_lower t]

theorem piecewise_spindle_core_derivative (A x : ℝ) :
    HasDerivAt (piecewiseSpindleCore A) (piecewiseSpindleCoreSlope A x) x := by
  convert (hasDerivAt_id x).add (((hasDerivAt_id x).pow 3).const_mul A) using 1
  · rfl
  · simp [piecewiseSpindleCoreSlope]; ring

theorem piecewise_spindle_core_second_derivative (A x : ℝ) :
    HasDerivAt (piecewiseSpindleCoreSlope A) (6*A*x) x := by
  convert (((hasDerivAt_id x).pow 2).const_mul (3*A)).const_add 1 using 1
  · rfl
  · simp; ring

theorem piecewise_spindle_tail_derivative (rs m Q H t : ℝ) :
    HasDerivAt (piecewiseSpindleTail rs m Q H) (piecewiseSpindleTailSlope m Q H t) t := by
  have hd : piecewiseSpindleDenom t ≠ 0 := (piecewise_spindle_denominator_pos t).ne'
  have hden := (((hasDerivAt_id t).const_mul 14).const_add 1).add
    (((hasDerivAt_id t).pow 2).const_mul 196)
  have hnum := (((hasDerivAt_id t).pow 2).const_mul Q).add
    (((hasDerivAt_id t).pow 3).const_mul H)
  have hr := (((hasDerivAt_id t).const_mul m).const_add rs).add (hnum.div hden hd)
  convert hr using 1
  · rfl
  · unfold piecewiseSpindleTailSlope piecewiseSpindleDenom at *
    simp only [Pi.add_apply, Pi.pow_apply, id_eq, Nat.cast_ofNat, mul_one, Nat.reduceSub, pow_one]
    field_simp [hd]
    ring

theorem piecewise_spindle_tail_second_derivative (m Q H t : ℝ) :
    HasDerivAt (piecewiseSpindleTailSlope m Q H) (piecewiseSpindleTailCurvature Q H t) t := by
  have hd : piecewiseSpindleDenom t ≠ 0 := (piecewise_spindle_denominator_pos t).ne'
  have hden := (((hasDerivAt_id t).const_mul 14).const_add 1).add
    (((hasDerivAt_id t).pow 2).const_mul 196)
  have hn₁ := ((hasDerivAt_id t).const_mul Q).mul
    (((hasDerivAt_id t).const_mul 14).const_add 2)
  have hn₂ := (((hasDerivAt_id t).pow 2).const_mul H).mul
    ((((hasDerivAt_id t).const_mul 28).const_add 3).add
      (((hasDerivAt_id t).pow 2).const_mul 196))
  have hr := (((hn₁.add hn₂).div (hden.pow 2) (pow_ne_zero 2 hd)).const_add m)
  convert hr using 1
  · rfl
  · unfold piecewiseSpindleTailCurvature piecewiseSpindleDenom at *
    simp only [Pi.add_apply, Pi.mul_apply, Pi.pow_apply, id_eq, Nat.cast_ofNat, mul_one, Nat.reduceSub, pow_one]
    field_simp [hd]
    ring

theorem piecewise_spindle_core_c2 (A : ℝ) : ContDiff ℝ 2 (piecewiseSpindleCore A) := by
  unfold piecewiseSpindleCore
  fun_prop

theorem piecewise_spindle_tail_c2 (rs m Q H : ℝ) : ContDiff ℝ 2 (piecewiseSpindleTail rs m Q H) := by
  have hd : ∀ t : ℝ, piecewiseSpindleDenom t ≠ 0 := fun t => (piecewise_spindle_denominator_pos t).ne'
  unfold piecewiseSpindleTail piecewiseSpindleDenom at *
  fun_prop (disch := aesop)

theorem piecewise_spindle_join_jets (A k : ℝ) :
    piecewiseSpindleCore A (3/4) = piecewiseSpindleTail (piecewiseSpindleRs A)
      (piecewiseSpindleM A) (piecewiseSpindleQ A) (piecewiseSpindleH A k) 0 ∧
    piecewiseSpindleCoreSlope A (3/4) = piecewiseSpindleTailSlope
      (piecewiseSpindleM A) (piecewiseSpindleQ A) (piecewiseSpindleH A k) 0 ∧
    6*A*(3/4) = piecewiseSpindleTailCurvature (piecewiseSpindleQ A) (piecewiseSpindleH A k) 0 := by
  simp [piecewiseSpindleCore, piecewiseSpindleCoreSlope, piecewiseSpindleTail,
    piecewiseSpindleTailSlope, piecewiseSpindleTailCurvature, piecewiseSpindleDenom,
    piecewiseSpindleRs, piecewiseSpindleM, piecewiseSpindleQ]
  ring

theorem piecewise_spindle_tail_endpoint (A k : ℝ) :
    piecewiseSpindleTail (piecewiseSpindleRs A) (piecewiseSpindleM A)
      (piecewiseSpindleQ A) (piecewiseSpindleH A k) (1/4) = k := by
  unfold piecewiseSpindleTail piecewiseSpindleRs piecewiseSpindleM piecewiseSpindleQ
    piecewiseSpindleH piecewiseSpindleDenom
  ring

theorem piecewise_spindle_c2 (eps k : ℝ) : ContDiff ℝ 2 (piecewiseSpindleRelease eps k) := by
  let A := piecewiseSpindleA eps k
  let tail := piecewiseSpindleTail (piecewiseSpindleRs A) (piecewiseSpindleM A)
    (piecewiseSpindleQ A) (piecewiseSpindleH A k) ∘ (fun x : ℝ => x-3/4)
  let slope := piecewiseSpindleTailSlope (piecewiseSpindleM A)
    (piecewiseSpindleQ A) (piecewiseSpindleH A k) ∘ (fun x : ℝ => x-3/4)
  have dt : deriv tail = slope := by
    funext x
    have hd := (piecewise_spindle_tail_derivative (piecewiseSpindleRs A) (piecewiseSpindleM A)
      (piecewiseSpindleQ A) (piecewiseSpindleH A k) (x-3/4)).comp x ((hasDerivAt_id x).sub_const (3/4))
    simpa [tail, slope, Function.comp_def] using hd.deriv
  have ddt : deriv slope = fun x => piecewiseSpindleTailCurvature (piecewiseSpindleQ A)
      (piecewiseSpindleH A k) (x-3/4) := by
    funext x
    have hd := (piecewise_spindle_tail_second_derivative (piecewiseSpindleM A)
      (piecewiseSpindleQ A) (piecewiseSpindleH A k) (x-3/4)).comp x ((hasDerivAt_id x).sub_const (3/4))
    simpa [slope, Function.comp_def] using hd.deriv
  have dc : deriv (piecewiseSpindleCore A) = piecewiseSpindleCoreSlope A :=
    funext fun x => (piecewise_spindle_core_derivative A x).deriv
  have ddc : deriv (piecewiseSpindleCoreSlope A) = fun x => 6*A*x :=
    funext fun x => (piecewise_spindle_core_second_derivative A x).deriv
  change ContDiff ℝ 2 (joined (3/4) (piecewiseSpindleCore A) tail)
  apply joined_c2 _ _ _ (piecewise_spindle_core_c2 A)
    ((piecewise_spindle_tail_c2 _ _ _ _).comp (by fun_prop))
  · simpa [tail, Function.comp_def] using (piecewise_spindle_join_jets A k).1
  · rw [dc, dt]
    simpa [slope, Function.comp_def] using (piecewise_spindle_join_jets A k).2.1
  · rw [dc, dt, ddc, ddt]
    simpa using (piecewise_spindle_join_jets A k).2.2

theorem piecewise_spindle_endpoints (eps k : ℝ) :
    piecewiseSpindleRelease eps k 0 = 0 ∧ piecewiseSpindleRelease eps k 1 = k := by
  constructor
  · norm_num [piecewiseSpindleRelease, joined, piecewiseSpindleCore]
  · simp only [piecewiseSpindleRelease, joined]
    norm_num only [show ¬(1:ℝ) ≤ 3/4 by norm_num, ite_false, show (1:ℝ)-3/4 = 1/4 by norm_num]
    exact piecewise_spindle_tail_endpoint _ _

theorem piecewise_spindle_core_neutral (A : ℝ) :
    HasDerivAt (piecewiseSpindleCore A) 1 0 ∧
    HasDerivAt (piecewiseSpindleCoreSlope A) 0 0 := by
  constructor
  · simpa [piecewiseSpindleCoreSlope] using piecewise_spindle_core_derivative A 0
  · simpa using piecewise_spindle_core_second_derivative A 0

theorem piecewise_spindle_tail_slope_lower (m Q H t : ℝ) (hQ : 0 ≤ Q) (hH : 0 ≤ H) :
    m-16*Q/126 ≤ piecewiseSpindleTailSlope m Q H t := by
  have hd := piecewise_spindle_denominator_lower t
  have hd2 : (9/16:ℝ) ≤ (piecewiseSpindleDenom t)^2 := by nlinarith
  have hn : -(1/14:ℝ) ≤ t*(2+14*t) := by nlinarith [sq_nonneg (14*t+1)]
  have hr : 0 ≤ 3+28*t+196*t^2 := by nlinarith [sq_nonneg (14*t+1)]
  have hmul := mul_nonneg (mul_nonneg hH (sq_nonneg t)) hr
  have hq := mul_le_mul_of_nonneg_left hn hQ
  have hb := mul_le_mul_of_nonneg_left hd2 (show 0 ≤ 16*Q/126 by positivity)
  unfold piecewiseSpindleTailSlope
  have hdpos := sq_pos_of_pos (piecewise_spindle_denominator_pos t)
  have h : -(16*Q/126) ≤
      (Q*t*(2+14*t)+H*t^2*(3+28*t+196*t^2))/(piecewiseSpindleDenom t)^2 := by
    apply (le_div_iff₀ hdpos).2
    nlinarith
  linarith

theorem piecewise_spindle_tail_strict_mono (rs m Q H : ℝ) (hQ : 0 ≤ Q)
    (hH : 0 ≤ H) (hm : 16*Q/126 < m) : StrictMono (piecewiseSpindleTail rs m Q H) := by
  apply strictMono_of_deriv_pos
  intro x
  rw [(piecewise_spindle_tail_derivative rs m Q H x).deriv]
  linarith [piecewise_spindle_tail_slope_lower m Q H x hQ hH]

theorem piecewise_spindle_tail_curvature_nonneg (Q H t : ℝ) (hQ : 0 ≤ Q)
    (hH : 400*Q ≤ H) (ht : t ∈ Icc 0 (1/4)) :
    0 ≤ piecewiseSpindleTailCurvature Q H t := by
  have ht0 := ht.1
  have ht1 := ht.2
  have hH0 : 0 ≤ H := by linarith
  have hcoef : 0 ≤ 42*H-1274*Q := by linarith
  have hq := mul_nonneg hQ (show 0 ≤ 1/4-t by linarith)
  have hqt := mul_nonneg (mul_nonneg hq (sq_nonneg t)) (show (0:ℝ) ≤ 2744 by norm_num)
  have hrest := mul_nonneg hcoef (sq_nonneg t)
  have hht := mul_nonneg hH0 ht0
  unfold piecewiseSpindleTailCurvature
  apply div_nonneg _ (le_of_lt (pow_pos (piecewise_spindle_denominator_pos t) 3))
  nlinarith

theorem piecewise_spindle_coefficient_bounds (eps k : ℝ) (he : eps ∈ Icc 0 (1/4))
    (hk : 1 ≤ k) :
    0 ≤ piecewiseSpindleA eps k ∧ piecewiseSpindleA eps k ≤ (4/9)*(k-1) ∧
    piecewiseSpindleA eps k ≤ 4/9 := by
  have hk0 : 0 < k := by linarith
  have hrat : 0 ≤ (k-1)/k ∧ (k-1)/k ≤ 1 := by
    constructor
    · exact div_nonneg (by linarith) hk0.le
    · apply (div_le_iff₀ hk0).2; linarith
  have he0 := he.1
  have he1 := he.2
  have ha : piecewiseSpindleA eps k = (16/9)*eps*((k-1)/k) := by
    unfold piecewiseSpindleA
    field_simp
    ring
  rw [ha]
  have heb : (16/9)*eps ≤ (4/9:ℝ) := by linarith
  have heb0 : 0 ≤ (16/9)*eps := by positivity
  have hrat2 : (k-1)/k ≤ k-1 := by
    apply (div_le_iff₀ hk0).2
    nlinarith
  constructor
  · positivity
  constructor
  · exact le_trans (mul_le_mul_of_nonneg_left hrat2 heb0)
      (mul_le_mul_of_nonneg_right heb (by linarith))
  · nlinarith [mul_le_mul_of_nonneg_left hrat.2 heb0]

theorem piecewise_spindle_parameters_safe (eps k : ℝ) (he : eps ∈ Icc 0 (1/4))
    (hk : 1 ≤ k) :
    0 ≤ piecewiseSpindleQ (piecewiseSpindleA eps k) ∧
    400*piecewiseSpindleQ (piecewiseSpindleA eps k) ≤
      piecewiseSpindleH (piecewiseSpindleA eps k) k ∧
    16*piecewiseSpindleQ (piecewiseSpindleA eps k)/126 <
      piecewiseSpindleM (piecewiseSpindleA eps k) := by
  obtain ⟨ha0, haK, ha1⟩ := piecewise_spindle_coefficient_bounds eps k he hk
  unfold piecewiseSpindleQ piecewiseSpindleH piecewiseSpindleM
  constructor
  · positivity
  constructor <;> nlinarith

theorem piecewise_spindle_exterior_derivative (k M E delta u : ℝ) (hd : delta ≠ 0)
    (hu : delta-u ≠ 0) :
    HasDerivAt (piecewiseSpindleExterior k M E delta) (piecewiseSpindleExteriorSlope M E delta u) u := by
  have hz : 1-u/delta ≠ 0 := by field_simp [hd]; exact div_ne_zero hu hd
  have hn := (((hasDerivAt_id u).pow 2).const_mul E)
  have hden := ((hasDerivAt_id u).div_const delta).const_sub 1
  have hr := (((hasDerivAt_id u).const_mul M).const_add k).add (hn.div hden hz)
  convert hr using 1
  · rfl
  · unfold piecewiseSpindleExteriorSlope
    simp only [Pi.pow_apply, id_eq, Nat.cast_ofNat, mul_one, Nat.reduceSub, pow_one]
    field_simp [hd, hu]
    ring

theorem piecewise_spindle_exterior_second_derivative (M E delta u : ℝ)
    (hu : delta-u ≠ 0) :
    HasDerivAt (piecewiseSpindleExteriorSlope M E delta) (piecewiseSpindleExteriorCurvature E delta u) u := by
  have hn := ((hasDerivAt_id u).const_mul (E*delta)).mul ((hasDerivAt_id u).const_sub (2*delta))
  have hden := ((hasDerivAt_id u).const_sub delta).pow 2
  have hr := (hn.div hden (pow_ne_zero 2 hu)).const_add M
  convert hr using 1
  · rfl
  · unfold piecewiseSpindleExteriorCurvature
    simp only [Pi.pow_apply, Pi.mul_apply, id_eq, Nat.cast_ofNat, mul_one, Nat.reduceSub, pow_one]
    field_simp [hu]
    ring

theorem piecewise_spindle_exterior_c2_at (k M E delta u : ℝ) (hd : delta ≠ 0)
    (hu : delta-u ≠ 0) : ContDiffAt ℝ 2 (piecewiseSpindleExterior k M E delta) u := by
  have hz : 1-u/delta ≠ 0 := by field_simp [hd]; exact div_ne_zero hu hd
  unfold piecewiseSpindleExterior
  fun_prop (disch := assumption)

theorem piecewise_spindle_exterior_join_jets (k M E delta : ℝ) (hd : delta ≠ 0) :
    piecewiseSpindleExterior k M E delta 0 = k ∧
    piecewiseSpindleExteriorSlope M E delta 0 = M ∧
    piecewiseSpindleExteriorCurvature E delta 0 = 2*E := by
  simp [piecewiseSpindleExterior, piecewiseSpindleExteriorSlope,
    piecewiseSpindleExteriorCurvature, hd]

theorem piecewise_spindle_exterior_strict_mono (k M E delta : ℝ) (hM : 0 < M)
    (hE : 0 ≤ E) (hd : 0 < delta) :
    StrictMonoOn (piecewiseSpindleExterior k M E delta) (Ico 0 delta) := by
  apply strictMonoOn_of_deriv_pos (convex_Ico 0 delta)
  · intro u hu
    exact (piecewise_spindle_exterior_c2_at k M E delta u hd.ne' (sub_pos.mpr hu.2).ne').continuousAt.continuousWithinAt
  · intro u hu
    have hi : u ∈ Ico (0:ℝ) delta := interior_subset hu
    rw [(piecewise_spindle_exterior_derivative k M E delta u hd.ne' (sub_pos.mpr hi.2).ne').deriv]
    unfold piecewiseSpindleExteriorSlope
    have hu0 := hi.1
    have hh : 0 ≤ 2*delta-u := by linarith [hi.2]
    have hn : 0 ≤ E*delta*u*(2*delta-u)/(delta-u)^2 := by positivity
    linarith

theorem piecewise_spindle_exterior_tendsto_pole (k M E delta : ℝ)
    (hE : 0 < E) (hd : 0 < delta) :
    Tendsto (piecewiseSpindleExterior k M E delta) (𝓝[<] delta) atTop := by
  have hid : Tendsto (fun u : ℝ => u) (𝓝[<] delta) (𝓝 delta) :=
    tendsto_id.mono_right nhdsWithin_le_nhds
  have hden : Tendsto (fun u : ℝ => delta-u) (𝓝[<] delta) (𝓝[>] 0) := by
    apply tendsto_nhdsWithin_iff.mpr
    constructor
    · simpa using (tendsto_const_nhds : Tendsto (fun _ : ℝ => delta) (𝓝[<] delta) (𝓝 delta)).sub hid
    · filter_upwards [self_mem_nhdsWithin] with u hu
      exact sub_pos.mpr (show u < delta from hu)
  have hn : Tendsto (fun u : ℝ => E*delta*u^2) (𝓝[<] delta) (𝓝 (E*delta*delta^2)) := by
    exact ((tendsto_const_nhds.mul tendsto_const_nhds).mul (hid.pow 2))
  have hp := hn.pos_mul_atTop (show 0 < E*delta*delta^2 by positivity) hden.inv_tendsto_nhdsGT_zero
  have hr : Tendsto (fun u : ℝ => k+M*u) (𝓝[<] delta) (𝓝 (k+M*delta)) :=
    tendsto_const_nhds.add (tendsto_const_nhds.mul hid)
  apply (hr.add_atTop hp).congr'
  filter_upwards [self_mem_nhdsWithin] with u hu
  have hne : delta-u ≠ 0 := (sub_pos.mpr hu).ne'
  unfold piecewiseSpindleExterior
  simp only [Pi.inv_apply]
  field_simp [hd.ne', hne]

def piecewiseSpindleSlope (eps k : ℝ) : ℝ → ℝ :=
  let A := piecewiseSpindleA eps k
  joined (3/4) (piecewiseSpindleCoreSlope A)
    (fun x => piecewiseSpindleTailSlope (piecewiseSpindleM A)
      (piecewiseSpindleQ A) (piecewiseSpindleH A k) (x-3/4))
def piecewiseSpindleCurvature (eps k : ℝ) : ℝ → ℝ :=
  let A := piecewiseSpindleA eps k
  joined (3/4) (fun x => 6*A*x)
    (fun x => piecewiseSpindleTailCurvature (piecewiseSpindleQ A)
      (piecewiseSpindleH A k) (x-3/4))

theorem piecewise_spindle_derivative (eps k x : ℝ) :
    HasDerivAt (piecewiseSpindleRelease eps k) (piecewiseSpindleSlope eps k x) x := by
  unfold piecewiseSpindleRelease piecewiseSpindleSlope
  apply joined_derivative
  · exact piecewise_spindle_core_derivative _
  · intro y
    have hh := (piecewise_spindle_tail_derivative (piecewiseSpindleRs (piecewiseSpindleA eps k))
      (piecewiseSpindleM (piecewiseSpindleA eps k)) (piecewiseSpindleQ (piecewiseSpindleA eps k))
      (piecewiseSpindleH (piecewiseSpindleA eps k) k) (y-3/4)).comp y ((hasDerivAt_id y).sub_const (3/4))
    simpa [Function.comp_def] using hh
  · simpa using (piecewise_spindle_join_jets (piecewiseSpindleA eps k) k).1
  · simpa using (piecewise_spindle_join_jets (piecewiseSpindleA eps k) k).2.1

theorem piecewise_spindle_second_derivative (eps k x : ℝ) :
    HasDerivAt (piecewiseSpindleSlope eps k) (piecewiseSpindleCurvature eps k x) x := by
  unfold piecewiseSpindleSlope piecewiseSpindleCurvature
  apply joined_derivative
  · exact piecewise_spindle_core_second_derivative _
  · intro y
    have hh := (piecewise_spindle_tail_second_derivative
      (piecewiseSpindleM (piecewiseSpindleA eps k)) (piecewiseSpindleQ (piecewiseSpindleA eps k))
      (piecewiseSpindleH (piecewiseSpindleA eps k) k) (y-3/4)).comp y ((hasDerivAt_id y).sub_const (3/4))
    simpa [Function.comp_def] using hh
  · simpa using (piecewise_spindle_join_jets (piecewiseSpindleA eps k) k).2.1
  · simpa using (piecewise_spindle_join_jets (piecewiseSpindleA eps k) k).2.2

theorem piecewise_spindle_neutral_derivative (eps k : ℝ) :
    HasDerivAt (piecewiseSpindleRelease eps k) 1 0 := by
  simpa [piecewiseSpindleSlope, joined, piecewiseSpindleCoreSlope, show (0:ℝ) ≤ 3/4 by norm_num] using piecewise_spindle_derivative eps k 0

theorem piecewise_spindle_neutral_second_derivative (eps k : ℝ) :
    HasDerivAt (deriv (piecewiseSpindleRelease eps k)) 0 0 := by
  have hd : deriv (piecewiseSpindleRelease eps k) = piecewiseSpindleSlope eps k :=
    funext fun x => (piecewise_spindle_derivative eps k x).deriv
  rw [hd]
  simpa [piecewiseSpindleCurvature, joined, show (0:ℝ) ≤ 3/4 by norm_num] using piecewise_spindle_second_derivative eps k 0

theorem piecewise_spindle_strict_mono (eps k : ℝ) (he : eps ∈ Icc 0 (1/4))
    (hk : 1 ≤ k) : StrictMono (piecewiseSpindleRelease eps k) := by
  obtain ⟨hQ, hH, hm⟩ := piecewise_spindle_parameters_safe eps k he hk
  have ha := (piecewise_spindle_coefficient_bounds eps k he hk).1
  apply strictMono_of_deriv_pos
  intro x
  rw [(piecewise_spindle_derivative eps k x).deriv]
  unfold piecewiseSpindleSlope joined
  split_ifs
  · unfold piecewiseSpindleCoreSlope
    positivity
  · have hh : 0 ≤ piecewiseSpindleH (piecewiseSpindleA eps k) k := by linarith
    linarith [piecewise_spindle_tail_slope_lower (piecewiseSpindleM (piecewiseSpindleA eps k))
      (piecewiseSpindleQ (piecewiseSpindleA eps k)) (piecewiseSpindleH (piecewiseSpindleA eps k) k)
      (x-3/4) hQ hh]

theorem piecewise_spindle_physical_curvature_nonneg (eps k x : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 ≤ k) (hx : x ∈ Icc 0 1) :
    0 ≤ piecewiseSpindleCurvature eps k x := by
  have ha := (piecewise_spindle_coefficient_bounds eps k he hk).1
  obtain ⟨hQ, hH, _⟩ := piecewise_spindle_parameters_safe eps k he hk
  unfold piecewiseSpindleCurvature joined
  split_ifs with h
  · have hx0 := hx.1
    positivity
  · exact piecewise_spindle_tail_curvature_nonneg _ _ _ hQ hH ⟨by linarith, by linarith [hx.2]⟩

theorem piecewise_spindle_identity (eps x : ℝ) : piecewiseSpindleRelease eps 1 x = x := by
  unfold piecewiseSpindleRelease joined
  simp only [piecewiseSpindleA, sub_self, mul_zero, zero_div]
  split_ifs <;>
    simp [piecewiseSpindleCore, piecewiseSpindleTail, piecewiseSpindleRs, piecewiseSpindleM,
      piecewiseSpindleQ, piecewiseSpindleH]

theorem piecewise_spindle_global_compression (eps k x : ℝ) (he : 0 < eps)
    (he1 : eps ≤ 1/4) (hk : 1 < k) (hx : 0 < x) : x < piecewiseSpindleRelease eps k x := by
  have ha : 0 < piecewiseSpindleA eps k := by unfold piecewiseSpindleA; positivity
  obtain ⟨hQ, hH, _⟩ := piecewise_spindle_parameters_safe eps k ⟨he.le, he1⟩ hk.le
  have hh : 0 ≤ piecewiseSpindleH (piecewiseSpindleA eps k) k := by linarith
  unfold piecewiseSpindleRelease joined
  split_ifs with h
  · unfold piecewiseSpindleCore
    have hp := mul_pos ha (pow_pos hx 3)
    linarith
  · have ht : 0 ≤ x-3/4 := by linarith
    have hp : 0 ≤ (piecewiseSpindleQ (piecewiseSpindleA eps k)*(x-3/4)^2+
        piecewiseSpindleH (piecewiseSpindleA eps k) k*(x-3/4)^3)/piecewiseSpindleDenom (x-3/4) := by
      apply div_nonneg _ (piecewise_spindle_denominator_pos _).le
      positivity
    unfold piecewiseSpindleTail piecewiseSpindleRs piecewiseSpindleM
    nlinarith [mul_nonneg ha.le ht]

theorem piecewise_spindle_tail_taylor (rs m Q H u : ℝ) :
    let M := piecewiseSpindleTailSlope m Q H (1/4)
    let E := piecewiseSpindleTailCurvature Q H (1/4)/2
    piecewiseSpindleTail rs m Q H (u+1/4) =
      piecewiseSpindleTail rs m Q H (1/4)+M*u+E*u^2+
        u^3*((196*m+H)-196*M-112*E-196*E*u)/piecewiseSpindleDenom (u+1/4) := by
  have hd : piecewiseSpindleDenom (u+1/4) ≠ 0 := (piecewise_spindle_denominator_pos _).ne'
  dsimp
  unfold piecewiseSpindleTail piecewiseSpindleTailSlope piecewiseSpindleTailCurvature
    piecewiseSpindleDenom at *
  have hd' : 268+1792*u+3136*u^2 ≠ 0 := by
    have hh := piecewise_spindle_denominator_pos (u+1/4)
    unfold piecewiseSpindleDenom at hh
    nlinarith
  field_simp [hd]
  ring_nf at hd' ⊢
  field_simp [hd']
  ring

def piecewiseSpindleExtended (eps k delta : ℝ) : ℝ → ℝ :=
  joined 1 (piecewiseSpindleRelease eps k)
    (fun x => piecewiseSpindleExterior k (piecewiseSpindleSlope eps k 1)
      (piecewiseSpindleCurvature eps k 1/2) delta (x-1))

theorem piecewise_spindle_extended_correction (eps k delta x : ℝ)
    (hd : delta ≠ 0) (hx : x < 1+delta) :
    let A := piecewiseSpindleA eps k
    let M := piecewiseSpindleSlope eps k 1
    let E := piecewiseSpindleCurvature eps k 1/2
    let Z := 196*piecewiseSpindleM A+piecewiseSpindleH A k-196*M-112*E
    piecewiseSpindleExtended eps k delta x =
      piecewiseSpindleRelease eps k x + positiveCubic (x-1) *
        (E/(delta-(x-1))-(Z-196*E*(x-1))/piecewiseSpindleDenom (x-3/4)) := by
  dsimp only
  by_cases h : x ≤ 1
  · rw [piecewiseSpindleExtended, joined, ite_eq_left h, positive_cubic_nonpositive _ (by linarith)]
    ring
  have h1 : 1 < x := lt_of_not_ge h
  have h2 : ¬x ≤ 3/4 := by linarith
  have hz : delta-(x-1) ≠ 0 := by linarith
  have hden : piecewiseSpindleDenom (x-3/4) ≠ 0 := (piecewise_spindle_denominator_pos _).ne'
  rw [piecewiseSpindleExtended, joined, ite_eq_right h, positive_cubic_nonnegative _ (by linarith)]
  have ht := piecewise_spindle_tail_taylor (piecewiseSpindleRs (piecewiseSpindleA eps k))
    (piecewiseSpindleM (piecewiseSpindleA eps k)) (piecewiseSpindleQ (piecewiseSpindleA eps k))
    (piecewiseSpindleH (piecewiseSpindleA eps k) k) (x-1)
  dsimp only at ht
  rw [show x-1+1/4 = x-3/4 by ring, piecewise_spindle_tail_endpoint] at ht
  unfold piecewiseSpindleRelease joined
  rw [ite_eq_right h2]
  dsimp only
  rw [ht]
  unfold piecewiseSpindleSlope piecewiseSpindleCurvature joined
  norm_num only [show ¬(1:ℝ) ≤ 3/4 by norm_num, ite_false,
    show (1:ℝ)-3/4 = 1/4 by norm_num]
  unfold piecewiseSpindleExterior
  field_simp [hd, hz, hden]
  ring

theorem piecewise_spindle_extended_c2 (eps k delta : ℝ) (hd : 0 < delta) :
    ContDiffOn ℝ 2 (piecewiseSpindleExtended eps k delta) (Iio (1+delta)) := by
  intro x hx
  have hn : delta-(x-1) ≠ 0 := by have := hx; change x < 1+delta at this; linarith
  have hc : ContDiffAt ℝ 2 (fun y : ℝ => positiveCubic (y-1)) x :=
    positive_cubic_c2.contDiffAt.comp x (by fun_prop)
  let A := piecewiseSpindleA eps k
  let M := piecewiseSpindleSlope eps k 1
  let E := piecewiseSpindleCurvature eps k 1/2
  let Z := 196*piecewiseSpindleM A+piecewiseSpindleH A k-196*M-112*E
  have hden : piecewiseSpindleDenom (x-3/4) ≠ 0 := (piecewise_spindle_denominator_pos _).ne'
  have hr : ContDiffAt ℝ 2 (fun y : ℝ => E/(delta-(y-1))-
      (Z-196*E*(y-1))/piecewiseSpindleDenom (y-3/4)) x := by
    unfold piecewiseSpindleDenom at *
    fun_prop (disch := assumption)
  have hall := (piecewise_spindle_c2 eps k).contDiffAt.add (hc.mul hr)
  apply (hall.congr_of_eventuallyEq ?_).contDiffWithinAt
  filter_upwards [Iio_mem_nhds hx] with y hy
  exact piecewise_spindle_extended_correction eps k delta y hd.ne' hy

theorem piecewise_spindle_slope_pos (eps k x : ℝ) (he : eps ∈ Icc 0 (1/4))
    (hk : 1 ≤ k) : 0 < piecewiseSpindleSlope eps k x := by
  obtain ⟨hQ, hH, hm⟩ := piecewise_spindle_parameters_safe eps k he hk
  have ha := (piecewise_spindle_coefficient_bounds eps k he hk).1
  unfold piecewiseSpindleSlope joined
  split_ifs
  · unfold piecewiseSpindleCoreSlope
    positivity
  · have hh : 0 ≤ piecewiseSpindleH (piecewiseSpindleA eps k) k := by linarith
    linarith [piecewise_spindle_tail_slope_lower (piecewiseSpindleM (piecewiseSpindleA eps k))
      (piecewiseSpindleQ (piecewiseSpindleA eps k)) (piecewiseSpindleH (piecewiseSpindleA eps k) k)
      (x-3/4) hQ hh]

theorem piecewise_spindle_boundary_curvature_pos (eps k : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 < k) :
    0 < piecewiseSpindleCurvature eps k 1 := by
  obtain ⟨ha0, haK, _⟩ := piecewise_spindle_coefficient_bounds eps k he hk.le
  unfold piecewiseSpindleCurvature joined
  norm_num only [show ¬(1:ℝ) ≤ 3/4 by norm_num, ite_false, show (1:ℝ)-3/4 = 1/4 by norm_num]
  unfold piecewiseSpindleTailCurvature piecewiseSpindleDenom piecewiseSpindleQ piecewiseSpindleH
  norm_num
  nlinarith

theorem piecewise_spindle_extended_tendsto_pole (eps k delta : ℝ)
    (he : eps ∈ Icc 0 (1/4)) (hk : 1 < k) (hd : 0 < delta) :
    Tendsto (piecewiseSpindleExtended eps k delta) (𝓝[<] (1+delta)) atTop := by
  have hE : 0 < piecewiseSpindleCurvature eps k 1/2 := by
    linarith [piecewise_spindle_boundary_curvature_pos eps k he hk]
  have ht : Tendsto (fun x : ℝ => x-1) (𝓝[<] (1+delta)) (𝓝[<] delta) := by
    apply tendsto_nhdsWithin_iff.mpr
    constructor
    · have hid : Tendsto (fun x : ℝ => x) (𝓝[<] (1+delta)) (𝓝 (1+delta)) :=
        tendsto_id.mono_right nhdsWithin_le_nhds
      convert hid.sub_const 1 using 1
      ring_nf
    · filter_upwards [self_mem_nhdsWithin] with x hx
      change x-1 < delta
      change x < 1+delta at hx
      linarith
  have hp := (piecewise_spindle_exterior_tendsto_pole k (piecewiseSpindleSlope eps k 1)
    (piecewiseSpindleCurvature eps k 1/2) delta hE hd).comp ht
  apply hp.congr'
  have hb : Ioi (1:ℝ) ∈ 𝓝[<] (1+delta) :=
    mem_nhdsWithin_of_mem_nhds (Ioi_mem_nhds (by linarith))
  filter_upwards [hb] with x hx
  change 1 < x at hx
  simp [piecewiseSpindleExtended, joined, not_le_of_gt hx]

end
end PerceptualGrade
