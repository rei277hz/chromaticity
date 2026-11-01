# Saturation-preserving tone curve

Tone remaps \(H\) while retaining hue and modCAM16 saturation. Five input landmarks define the mapping; fixed tone targets come from the reference and peak calibration. The same analytic curve is the DCTL reference and the source of the extension’s curve tables.

## Build a monotone curve

Convert each input neutral-nits value to normalized \(H\). Order the five levels with minimum spacing. Normalize their span to knots \(u_i\) from Black to Highlights; the corresponding targets are \(y_i\). Choose the smallest positive interval slope \(m\) and nonnegative residual rises \(r_i\):

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

![Tone curves at several Fit settings](../assets/figures/tone-curves.png)

<p class="figure-caption">The crosses are landmark targets. Their influence overlaps smoothly, with tighter transitions at higher Fit. The reference-white guides are at normalized lightness 1.</p>

The active curve is smooth above Input Black. Values at and below that threshold map to zero. The removed black-toe treatment means this cutoff does not acquire a \(C^2\) toe; smoothness at a positive black threshold is a separate boundary behavior. Default landmarks take an exact identity branch. Setting Fit alone at reset leaves that identity intact.

## Preserve saturation through the H–K relation

For this fixed dark surround, modCAM16 saturation is:

$$
s=75\frac{C}{J_A},\qquad H^2=J_A^2+66C.
$$

To reach a desired \(H_2\) while preserving \(k=C_1/J_{A,1}\), solve the positive quadratic root:

$$
J_{A,2}=\sqrt{H_2^2+(33k)^2}-33k,
\qquad C_2=kJ_{A,2},\qquad h_2=h_1.
$$

The implementation evaluates a rationalized, scaled version to avoid cancellation and division by tiny \(J_A\). A neutral naturally keeps \(C=0\). Black uses the zero output limit. This makes the mapped pair valid by construction.

![Saturation-preserving and squared-H policies](../assets/figures/tone-saturation.png)

<p class="figure-caption">For \(H=100,\ C=20\), preserving \(C/J_A\) holds saturation constant. Squared-H chroma coupling instead changes saturation in proportion to mapped \(H\).</p>

Reference Nits defaults to 203 and sets White’s neutral lightness. Highlights uses the selected effective peak, at least twice Reference Nits. The diagrams extend to the neutral lightness of 4000 nits, independently of that peak choice. After this remap, Color’s tone-dependent coefficients use the resulting \(H_2\).
