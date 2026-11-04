import PGDependencies

/- Exact real definitions corresponding to src/reference/grading.py. -/
namespace PerceptualGrade
noncomputable section

def sigmoid (x : ℝ) : ℝ := Real.exp x / (1 + Real.exp x)
def softplus (x : ℝ) : ℝ := Real.log (1 + Real.exp x)
def kernel (t l r w : ℝ) : ℝ :=
  w * (softplus ((t-l)/w) - softplus (-l/w) - softplus ((t-r)/w) + softplus (-r/w))
def visibility (C : ℝ) : ℝ := C^2 / (C^2 + 4)
/-- U is the hue-dependent fitted cube capacity sampled before color grading. -/
def membership (U C : ℝ) : ℝ := C^2 / (C^2 + ((2/5 : ℝ)*U)^2)
def lowDriver (U C : ℝ) : ℝ := visibility C * (((2/5 : ℝ)*U)^2 / (C^2 + ((2/5 : ℝ)*U)^2))
def highDriver (U C : ℝ) : ℝ := visibility C * membership U C
/-- Legacy fixed-H a/b translation envelope; current Adaptance is in SelectiveAdaptance. -/
def adaptanceRate (C : ℝ) : ℝ := 1/4 + (3/4)/(1+(C/30)^2)
def adaptanceEnvelope (H C a : ℝ) : ℝ := (max H 0)/100 * (a*adaptanceRate C)/(1-a+a*adaptanceRate C)

theorem sigmoid_pos (x : ℝ) : 0 < sigmoid x := by
  unfold sigmoid
  positivity

theorem sigmoid_lt_one (x : ℝ) : sigmoid x < 1 := by
  unfold sigmoid
  apply (div_lt_one (by positivity)).2
  linarith

theorem sigmoid_strictMono : StrictMono sigmoid := by
  intro x y hxy
  have he := Real.exp_strictMono hxy
  unfold sigmoid
  apply (div_lt_div_iff₀ (by positivity) (by positivity)).2
  nlinarith

theorem softplus_derivative (x : ℝ) : HasDerivAt softplus (sigmoid x) x := by
  change HasDerivAt (fun y : ℝ => Real.log (1 + Real.exp y)) (Real.exp x / (1 + Real.exp x)) x
  have h := (Real.hasDerivAt_log (by positivity : (1 + Real.exp x) ≠ 0)).comp x
    ((Real.hasDerivAt_exp x).const_add 1)
  convert h using 1 <;> simp [Function.comp_def, div_eq_mul_inv, mul_comm]

theorem kernel_zero (l r w : ℝ) : kernel 0 l r w = 0 := by
  unfold kernel
  simp only [zero_sub]
  ring

end
end PerceptualGrade
