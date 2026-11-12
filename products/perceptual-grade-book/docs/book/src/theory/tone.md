# Saturation-preserving tone curve

The analytic reference remaps the nonnegative magnitude \(M=\sqrt{J_A^2+66C}\), then scales \(J_A\) and the opponent pair together. This preserves hue and signed modCAM16 saturation. Five neutral-nits landmarks define the mapping; fixed tone targets come from the reference and peak calibration. The frozen 1.23.2 products use the same broad curve construction with different target/effective-parameter rules, documented below.

## Build a monotone curve

Convert each neutral-nits input landmark to \(J_A/100\); for a neutral, this is also \(M/100\). Order the five levels with minimum spacing. Normalize their span to knots \(u_i\) from Black to Highlights; the corresponding targets are \(y_i\). Choose the smallest positive interval slope \(m\) and nonnegative residual rises \(r_i\):

$$
m=\min_i\frac{y_{i+1}-y_i}{u_{i+1}-u_i},\qquad
r_i=y_{i+1}-y_i-m(u_{i+1}-u_i),\qquad w=0.05\,2^{-\mathrm{Fit}}.
$$

Each interval contributes a smooth integrated sigmoid window:

$$
K_i(t)=\int_0^t\left[
\operatorname{sigmoid}\left(\frac{v-u_i}{w}\right)
-\operatorname{sigmoid}\left(\frac{v-u_{i+1}}{w}\right)\right]dv,
\qquad F(t)=mt+\sum_i r_i\frac{K_i(t)}{K_i(1)}.
$$

Since every window derivative and \(r_i\) is nonnegative, the curve remains monotone. It reaches the Highlights target at \(t=1\) and has a linear asymptote beyond the landmarks. Intermediate targets are soft. Fit changes how concentrated the interval transitions are.

![Tone curves at several Fit settings](../assets/figures/tone-curves.svg)

<p class="figure-caption">Current reference curves use the Shadows ratio 0.015507796089266005. The crosses are landmark targets; their influence overlaps smoothly, with tighter transitions at higher Fit. The reference-white guides are at normalized lightness 1.</p>

The active curve is smooth above Input Black. Values at and below that threshold map to zero. The removed black-toe treatment means this cutoff does not acquire a \(C^2\) toe; smoothness at a positive black threshold is a separate boundary behavior. Default landmarks take an exact identity branch. Setting Fit alone at reset leaves that identity intact.

## Preserve saturation through the H–K relation

For this fixed dark surround, signed modCAM16 saturation is \(s=75C/J_A\), defined when \(J_A\ne0\). The positive-branch H–K relation is:

$$
s=75\frac{C}{J_A},\qquad H^2=J_A^2+66C.
$$

On the positive branch, to reach a desired \(H_2\) while preserving \(k=C_1/J_{A,1}\), solve the positive quadratic root:

$$
J_{A,2}=\sqrt{H_2^2+(33k)^2}-33k,
\qquad C_2=kJ_{A,2},\qquad h_2=h_1.
$$

The implementation evaluates a rationalized, scaled version to avoid cancellation and division by tiny \(J_A\). Its equivalent form scales the pair by a single gain rather than recomputing \(J_A\):

$$
g=\frac{2H_2^2}{\operatorname{hypot}(66C_1,\ 2J_{A,1}H_2)+66C_1},
\qquad J_{A,2}=gJ_{A,1},\qquad C_2=gC_1.
$$

Both expressions select the same root on this branch; the second keeps \(C/J_A\) exact by construction. A neutral naturally keeps \(C=0\). Black uses the zero output limit.

The signed reference applies the same saturation-preserving scale to either sign. Let \(M_1=\sqrt{J_{A,1}^2+66C_1}\) and let the curve map it to \(M_2\). Then

$$
g=\frac{2M_2^2}{\operatorname{hypot}(66C_1,\ 2J_{A,1}M_2)+66C_1},\qquad
J_{A,2}=gJ_{A,1},\qquad (a_2,b_2)=g(a_1,b_1),\qquad C_2=gC_1.
$$

The gain is positive for a nonblack output, preserving the sign of \(J_A\), hue and \(C/|J_A|\) when defined. The black plateau uses zero gain; a zero denominator also gives zero output. The output coordinate is recomputed with the signed H–K map: \(H_2=M_2\) for \(J_{A,2}\ge0\), and \(H_2=2\sqrt{66C_2}-M_2\) for \(J_{A,2}<0\). Tone and the later Color tonal selectors use the magnitude \(M_2\), not this signed \(H_2\).

![Saturation-preserving and squared-H policies](../assets/figures/tone-saturation.svg)

<p class="figure-caption">This positive-branch example starts at \(H=100,\ C=20\). Preserving \(C/J_A\) holds saturation constant; squared-H chroma coupling instead changes saturation in proportion to mapped \(H\).</p>

Reference Nits defaults to 203 and sets White’s neutral lightness. Highlights uses the effective peak, at least twice Reference Nits. After this remap, Color’s tone-dependent coefficients use the resulting magnitude \(M_2\). The complete analytic Model currently fixes Grade white to D65 and Reference Nits to 203; its lower-level Tone helper accepts a wider effective-reference range.

## Targets and the effective configuration

Four of the five targets are fixed by the reference and the peak: Black at zero, Midtones at 18% of Reference Nits, White at exactly normalized lightness 1, and Highlights at the effective peak. Shadows is a fraction of Reference Nits chosen so the lower landmarks stay perceptually even. The analytic reference uses

$$
y_1=\nu(0.015507796089266005\,R_w)\approx\nu(3.148\ \mathrm{nits}).
$$

The 1.23.2 DCTL and bundled legacy figure model use \(0.037153526983R_w\), or 7.542 nits, for the same landmark. At matching effective reference and peak values, this Shadows target is the difference in the fixed target set. The legacy products also round effective reference and peak settings to whole nits, while the analytic Tone helper maps them smoothly; fractional or out-of-range inputs can therefore change other targets too. The complete analytic Model currently accepts only D65 / 203 nits.

The effective reference and peak are not the raw inputs. The reference passes each through a smooth bounded map, so fractional and out-of-range requests move continuously:

$$
R_w=\operatorname{cap}_{1000}\!\left(\operatorname{floor}_{48}(R_{\mathrm{input}})\right),
\qquad
P_w=\operatorname{cap}_{10000}\!\left(\operatorname{floor}_{2R_w}(P_{\mathrm{input}})\right),
$$

where \(\operatorname{floor}_\ell\) and \(\operatorname{cap}_u\) are the quintic ease-in and ease-out \(e(x)=x^3(6-8x+3x^2)\) applied to the distance from the interval edge, exactly \(x\) more than one unit inside and exactly the bound outside, with matching first and second derivatives at both joins. The earlier handbook described integer rounding to the nearest nit; that is the 1.23.2 behaviour and it produces a step at every half-nit. Use the smooth form for the reference, and treat the effective \(R_w,P_w\) as configuration shared by forward and inverse evaluation rather than as a menu index.
