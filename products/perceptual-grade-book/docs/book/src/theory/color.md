# Tone-shaped color operators

Color computes adjustment coefficients from perceptual lightness and applies them to fixed incoming color attributes. Lightness, chroma, adaptance and hue have distinct receivers and share the same smooth tonal curve family.

## Compute the tonal coefficients

Map \(H/H_{\mathrm{high}}\) to the quintic smoothstep \(P\) and integrate the same positive sigmoid windows used for Tone. Normalized cumulative interval functions \(F_i\) produce four weights:

$$
P(x)=6x^5-15x^4+10x^3,\quad x=\operatorname{clamp}(H/H_{\mathrm{high}},0,1),
\qquad
\mathbf w=(1-F_1,\ F_1-F_2,\ F_2-F_3,\ F_3).
$$

Here \(F_0\) belongs to Black→Shadows, \(F_1\) to Shadows→Midtones, and so on. A coefficient is the dot product of these weights with its four control heights. The Adaptance family replaces the first weight by \(F_0-F_1\), giving its black taper. The smoothstep pins first and second derivatives at Black and Highlights. Above Highlights, coefficients hold the Highlights height.

![Tone weights and Midtones coefficient](../assets/figures/color-tone-weights.png)

<p class="figure-caption">Left: overlapping tone weights. Right: Midtones \(C_{\ell}\) → J = +6 across lightness at several Fit values. The height controls an adjustment, while the curve controls its tonal reach.</p>

## Evaluate four drivers

Use modCAM16 saturation \(s=75C/J_A\), with a fixed midpoint \(s_0=35\) and neutral fade scale \(C_n=2\). For \(p=2\), evaluate the classifier without dividing by \(J_A\):

$$
q_s=\frac{C^2}{C^2+(35/75)^2J_A^2},\qquad V=\frac{C^2}{C^2+4},\qquad
\mathbf d=\left[V(1-q_s),\ Vq_s,\
\frac{a}{\sqrt{C^2+4}},\ \frac{b}{\sqrt{C^2+4}}\right]^{\mathsf T}.
$$

At black, all drivers are zero. Carry \(J_A\) from the appearance encoder through Tone's common scaling, rather than recovering it by subtracting \(66C\) from \(H^2\). Scale the ratio terms before squaring to avoid overflow.

\(C_{\ell}\) and \(C_h\) are complementary lower-/higher-saturation responses, with sum \(V\). Their classification stays fixed under saturation-preserving Tone adjustments; the absolute-chroma visibility fade still changes. The split is independent of the Highlights anchor and Fit. The \(a\) and \(b\) terms retain signed opponent directions. Every coefficient remains tone dependent.

![Chroma and opponent driver responses](../assets/figures/color-drivers.png)

<p class="figure-caption">At a fixed \(H\), \(C_{\ell}\) favors lower-chroma color and \(C_h\) favors higher chroma. \(a\) and \(b\) drivers respond with opposite signs across the hue wheel.</p>

## Mix into the receivers

For a fixed \(H\), a small matrix produces additive lightness, logarithmic chroma gain and chroma-driven hue rotation:

$$
\begin{bmatrix}\Delta H\\\Delta\log_2 C\\\Delta h_C\end{bmatrix}
=
\begin{bmatrix}
L_{\ell}(H)&L_h(H)&L_a(H)&L_b(H)\\
R_{\ell}(H)&R_h(H)&R_a(H)&R_b(H)\\
\theta_{\ell}&\theta_h&0&0
\end{bmatrix}\mathbf d.
$$

Add Global \(C\) Gain to the second row and Tone Hue to the third. The first two rows use four tone-controlled coefficient curves each. The last row has two global chroma coefficients; tone-dependent Hue Concentration is its separate operator. Every driver and coefficient is evaluated once from the same Stage-2 input, so the final settings determine the result independently of editing order.

## Adaptance and hue concentration

Adaptance uses a lightness envelope and smooth chroma protection:

$$
r(C)=0.25+\frac{0.75}{1+(C/30)^2},\qquad
f(H,C;\alpha)=\frac{H}{100}\frac{\alpha r(C)}{1-\alpha+\alpha r(C)}.
$$

It multiplies the two tonal Adaptance curves. At \(\alpha=1\) every chroma receives the same lightness-scaled endpoint. At \(\alpha=0\) the shift is zero. These are engineering correction weights rather than a per-pixel physiological CAT16 law.

Hue Concentration bounds a two-component control \(v\) inside a disk of radius 0.6 and fades it near \(C=0\). It acts as an orientation-preserving circle map:

$$
w=\frac{\tanh(\lVert v\rVert/0.6)}{\lVert v\rVert/0.6}
(v_a+i v_b)\frac{C^2}{C^2+4},
\qquad z_f=\frac{z+w}{1+\overline w z},\quad z=e^{ih}.
$$

Positive control values gather hues toward the selected direction. The zero control uses its finite identity limit. Concentration preserves \(H\) and \(C\); its angular derivative stays positive at fixed \(H/C\).

![Hue concentration and angular spacing](../assets/figures/color-hue-concentration.png)

<p class="figure-caption">Positive \(a\) concentration gathers nearby hues and expands the opposite side. The local spacing ratio stays positive, preserving the concentration operator's hue order.</p>

The defined composition applies concentration, radial gain and rotation, then adds Adaptance:

$$
H_3=H_2+\Delta H,\qquad
\mathbf u_3=f\mathbf A(H_2)+
2^{g+\Delta\log_2 C}R_{\theta(H_2)+\Delta h_C}\mathbf u_f.
$$

The operators have this specified order even though slider editing order is irrelevant. The [H–K guard](hk-guard.md) then supplies a real inverse. An additive Adaptance displacement can change final hue ordering; the concentration map's ordering property describes that operator itself.
