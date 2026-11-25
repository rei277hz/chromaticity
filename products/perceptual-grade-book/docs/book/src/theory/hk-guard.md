# Bounded H–K guard

The analytic reference carries signed achromatic energy through Tone and Color. Color requests can cross into negative energy even when their signed lightness coordinate is nonnegative. With the default `hk_guard=True`, H–K repair shares the adjustment between a bounded increase in lightness and a reduction in chroma while preserving hue. It follows Adaptance and precedes the final positive Scale. Negative lightness takes a signed bypass; `hk_guard=False` is an unrepaired diagnostic mode.

## Set the energy knee

Keep the Stage 2 energy \(E_2\) as the per-pixel reference. For a finite request with \(H\ge0\), define squared lightness \(X\), the requested H–K deficit \(D\), and clamped reference energy \(E_0\):

$$
X=H^2,\qquad D=H^2-66C,\qquad E_0=\max(E_2,0),\qquad
\delta=\frac{E_0X}{E_0+X}.
$$

The carried signed energy \(E_{\mathrm{req}}=J_A\lvert J_A\rvert\) is authoritative. On the negative-energy branch, rounded \(H^2-66C\) may not equal it. The implementation evaluates the deficit by rationalization:

$$
B=\sqrt{66C},\qquad
u=\frac{E_{\mathrm{req}}}{\sqrt{\lvert E_{\mathrm{req}}\rvert+66C}+B},\qquad
D=\begin{cases}E_{\mathrm{req}},&E_{\mathrm{req}}\ge0,\\
E_{\mathrm{req}}+2u^2,&E_{\mathrm{req}}<0.
\end{cases}
$$

Use \(u=0\) when its denominator is zero. The harmonic form of \(\delta\) avoids a large product and is zero when either argument is zero. Its coefficient is fixed at 1.0.

For \(D\ge\delta\), retain the request and set \(E_g=E_{\mathrm{req}}\). Below a positive knee, set

$$
t=\frac{\delta-D}{\delta},\qquad
E_g=\frac{\delta}{(1+4t+10t^2)^{1/4}}.
$$

The branches match in value, slope, and second derivative at \(D=\delta\). The implementation uses \(v=1/(1+t)\) for bounded intermediate values. At \(\delta=0\), the limit is \(E_g=\max(D,0)\). Thus \(H\ge0\) and \(E_0\ge0\) guarantee \(E_g\ge0\). Strict positivity follows when \(H>0\) and \(E_0>0\).

## Share the repair

Let \(Z\) be the energy increase required by the knee and \(L\) the maximum squared-lightness lift:

$$
Z=\max(E_g-D,0),\qquad L=(1.2^2-1)X=0.44X,\qquad
G=\frac{LZ}{\sqrt{4L^2+Z^2}}.
$$

Recover the repaired appearance coordinates as

$$
H_g=\sqrt{X+G},\qquad
C_g=\frac{X+G-E_g}{66},\qquad
(a_g,b_g)=\frac{C_g}{C}(a,b).
$$

Explicit zero branches handle black and \(C=0\). Rounding protection bounds \(C_g\) to \([0,C]\). On an active repair, \(H\le H_g\le1.2H\) and \(0\le C_g\le C\). The bound applies to repair alone; the subsequent Scale can increase both coordinates. For example, \(H=50,C=80\) with reference \(H=50,C=20\) gives approximately \(H_g=58.188,C_g=48.142\).

![Guard energy and nonnegative-energy boundary](../assets/figures/guard-energy.svg)

<p class="figure-caption">The knee keeps repaired energy nonnegative. Strict positivity requires positive lightness and positive reference energy.</p>

![Sharing repair between H and C](../assets/figures/guard-boundary.svg)

<p class="figure-caption">As requested chroma increases, repair shares the adjustment between bounded lightness lift and chroma reduction.</p>

## Carry energy through Scale and decoding

The reference applies its common positive Scale after repair:

$$
(a_g,b_g,E_g)\mapsto(\lambda a_g,\lambda b_g,\lambda^2E_g),\qquad \lambda>0.
$$

The decoder receives the scaled energy directly. Reconstructing it from rounded appearance coordinates can erase a small positive achromatic component. The [Color chapter](color.md#saturation-pad-and-scale) shows why this common Scale leaves its compact saturation pad fixed.

Requests above the knee retain their coordinates and energy. Negative requested \(H\) bypasses repair and retains the signed state; the nonnegative-energy guarantee does not cover this branch. Nonfinite inputs are rejected. The signed decoder accepts finite signed energy when its cone responses satisfy \(\lvert r\rvert<400\). Positivity is a repair/export policy rather than a prerequisite for signed inverse evaluation.

The repair equations are implemented by `libraries/perceptual-grade-core/src/perceptual_grade_core/model/hk_guard.py` and applied by `libraries/perceptual-grade-reference/src/grading.py`. [HKCubeLuminance.lean](https://github.com/rei277hz/chromaticity/blob/main/libraries/perceptual-grade-reference/proofs/PerceptualGrade/HKCubeLuminance.lean) proves nonnegative repaired energy and achromatic lightness, including strict positivity under positive lightness and reference energy. [WarpRepairedScale.lean](https://github.com/rei277hz/chromaticity/blob/main/libraries/perceptual-grade-reference/proofs/PerceptualGrade/WarpRepairedScale.lean) proves that positive Scale preserves these signs. The zero-reference counterexample shows why strict positivity cannot be claimed for every input.

## Project into the export cube

H–K repair does not guarantee RGB cube containment. Export applies a separate guard in the reference's native AP1 cube \([0,1024]^3\):

1. For carried energy \(E\le0\), export returns black. For \(E\ge W^2\), where \(W\) is cube-white achromatic lightness, it returns neutral cube white \((1024,1024,1024)\).
2. For \(0<E<W^2\), export accepts a direct decode only when it is finite and inside the cube. Otherwise it searches along fixed \(J_A\) and hue for the greatest accepted chroma, checking every candidate with the actual decoder.
3. Candidates whose cone responses reach the pole at \(\lvert r\rvert=400\) are rejected. Accepted RGB must be finite and lie inside \([0,1024]^3\).

Only the interior radial branch holds \(J_A\) and hue fixed while reducing chroma. Black and white endpoint handling differ. Cube projection is lossy and can map distinct appearance requests to the same RGB. The reference inverse evaluates this complete export policy as part of its forward residual.

The theorem `hk_cube_guard_positive_luminance` in `HKCubeLuminance.lean` proves positive output luminance when \(H>0\), \(E_0>0\), and cube-white \(W>0\), under its explicit assumptions about legal RGB, decoder consistency, black energy, and luminance weights. This exact-real result does not certify floating-point containment. The executable reference validates accepted RGB through its decoder; the implementation is in `libraries/perceptual-grade-reference/src/cube_guard.py`.
