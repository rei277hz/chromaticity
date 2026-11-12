# Tone-shaped color operators

Color computes adjustment coefficients from the post-Tone appearance and applies them to fixed incoming color attributes. Lightness and chroma each receive a driver-weighted coefficient; a tonal web shapes hue and chroma, and selective cone Adaptance moves neutral destinations. With the reference's default `hk_guard=True`, H–K repair follows Adaptance and precedes the web's final common Scale. The explicit `hk_guard=False` mode is an unrepaired diagnostic path and is outside the guard guarantees below.

Freeze the post-Tone chroma \(C_0\), signed achromatic energy \(E_0=J_A\lvert J_A\rvert\), and tonal selector \(m=\sqrt{\lvert E_0\rvert+66C_0}\). Coefficient curves, web rows and Adaptance use this nonnegative magnitude. It equals displayed \(H=J_{\mathrm{HK}}\) on the nonnegative achromatic branch; the signed branch can have a different \(H\). These selectors stay fixed while the operators transform the running appearance state.

## Compute the tonal coefficients

Map \(m/H_{\mathrm{high}}\) to the quintic smoothstep \(P\) and integrate the same positive sigmoid windows used for Tone. Normalized cumulative interval functions \(F_i\) produce four weights:

$$
P(x)=6x^5-15x^4+10x^3,\quad x=\operatorname{clamp}(m/H_{\mathrm{high}},0,1),
\qquad
\mathbf w=(1-F_1,\ F_1-F_2,\ F_2-F_3,\ F_3).
$$

Here \(F_0\) belongs to Black→Shadows, \(F_1\) to Shadows→Midtones, and so on. A coefficient is the dot product of these weights with its four control heights. These weights apply to the lightness and chroma rows. The smoothstep pins first and second derivatives at Black and Highlights. Above Highlights, coefficients hold the Highlights height.

The web and Adaptance use quintic cardinal interpolation between adjacent anchors: \(\mathrm{smoother}((m-H_i)/(H_{i+1}-H_i))\), with constant tails outside the endpoint anchors. This differs from the integrated coefficient weights, so a web row, an Adaptance destination and a coefficient height do not all have equal influence between tonal anchors.

![Tone weights and Midtones coefficient](../assets/figures/color-tone-weights.svg)

<p class="figure-caption">Left: overlapping tone weights. Right: Midtones \(C_{\ell}\) → J = +6 across lightness at several Fit values. The height controls an adjustment, while the curve controls its tonal reach.</p>

## Evaluate four drivers

Use modCAM16 saturation \(s=75C/J_A\), with a fixed midpoint \(s_0=35\) and neutral fade scale \(C_n=2\). For \(p=2\), evaluate the classifier without dividing by \(J_A\):

$$
q_s=\frac{C^2}{C^2+r_s^2\lvert J_A\rvert^2},\qquad r_s=\frac{35}{75}=\frac{s_0}{75},\qquad V=\frac{C^2}{C^2+4},\qquad
\mathbf d=\left[V(1-q_s),\ Vq_s,\
\frac{a}{\sqrt{C^2+4}},\ \frac{b}{\sqrt{C^2+4}}\right]^{\mathsf T}.
$$

The absolute value in \(r_s\lvert J_A\rvert\) is deliberate. Written as a ratio, the classifier splits on \(\lvert s\rvert\), so a signed color below the achromatic axis keeps the same low/high classification as its positive counterpart. The archived [1.23.2 DCTL source](../downloads/Perceptual-Grade.dctl) used \(\max(J_A,0)\), sending negative achromatic colors with nonzero chroma to the high-chroma driver. The current DCTL project, frozen Blender product and retained shared production kernels use the separate capacity crossover \(0.4\,U(J_A,h)\). This chapter describes the current reference's symmetric \(35/75\) law; comparisons must identify which law they use.

At black, all drivers are zero. Carry \(J_A\) from the appearance encoder through Tone's common scaling, rather than recovering it by subtracting \(66C\) from \(H^2\). Scale the ratio terms before squaring to avoid overflow.

\(C_{\ell}\) and \(C_h\) are complementary lower-/higher-saturation responses, with sum \(V\). Their classification stays fixed under saturation-preserving Tone adjustments; the absolute-chroma visibility fade still changes. The split is independent of the Highlights anchor and Fit. The \(a\) and \(b\) terms retain signed opponent directions. Every coefficient remains tone dependent.

![Chroma and opponent driver responses](../assets/figures/color-drivers.svg)

<p class="figure-caption">At a fixed tonal selector \(m\), \(C_{\ell}\) favors lower-chroma color and \(C_h\) favors higher chroma. \(a\) and \(b\) drivers respond with opposite signs across the hue wheel.</p>

## Mix the lightness and chroma receivers

Two driver-weighted coefficient rows act directly on the appearance coordinates:

$$
\Delta H=\sum_j L_j(m)\,d_j,\qquad
g=2^{\,g_0+\sum_j R_j(m)\,d_j},
$$

where \(j\) runs over the four drivers, \(g_0\) is Global \(C\) Gain in stops, and \(L_j\) and \(R_j\) are the lightness and chroma coefficient curves. The result is

$$
H\leftarrow H+\Delta H,\qquad (a,b)\leftarrow g\,(a,b).
$$

Both rows are evaluated once from the fixed Stage-2 input, so the final settings determine the result independently of slider editing order. The additive lightness term uses no toe or H–K projection here: a signed color may cross achromatic zero, and the crossing is continuous rather than clipped. Repair belongs to the later guard.

The two coefficient rows are the only place the reference still uses a driver-weighted stage-3 matrix. Hue rotation, chroma geometry and neutral adaptation are no longer expressed as coefficient curves over the drivers.

## Shape hue and chroma with the tonal web

The web is a four-row, six-handle field. Each of the six handles is an actual Rec.709 primary ray — red, yellow, green, cyan, blue and magenta — scaled to the row's tonal height. The four rows are the tonal anchors Shadows, Midtones, White and Highlights. Between rows, handle angles interpolate directly and radii interpolate in log space.

Each row stores three relative controls per handle:

| Field | Meaning |
| --- | --- |
| `log_chroma` | \(\log_2\) of target radius over source radius, before adaptation and scale |
| `hue_degrees` | Unwrapped target hue displacement in degrees |
| `log_scale` | \(\log_2\) of the final common positive \(J_A\)/chroma scale at that handle |

All three arrays are zero at reset, which is the identity. The web is therefore additive in intent but multiplicative in effect, and no single scalar reports its strength.

### Radial law

For a source radius \(R\), target radius \(T\) and a hue-independent toe width \(\tau\), the first radial field calibrates \(R\to T\):

$$
A(C)=\left(1+(C/\tau)^4\right)^{-1/4},\qquad
g_{\mathrm c}=\frac{T/R-A(R)}{1-A(R)},\qquad
F(C)=C\left[g_{\mathrm c}+(1-g_{\mathrm c})A(C)\right].
$$

Because \(A\to1\) as \(C\to0\), the map keeps its near-neutral toe bounded: \(F(C)=C+O(C^5)\) and no chroma is created from black. Its derivative

$$
F'(C)=g_{\mathrm c}+(1-g_{\mathrm c})\left(1+(C/\tau)^4\right)^{-5/4}>0
$$

is positive for every positive \(g_{\mathrm c}\), so each radial field is monotone in \(C\). A second field with the same form maps the target radius onward to the scaled radius. Its output divided by its input gives the final scale \(\lambda\); on the neutral axis, \(\lambda=1\). The implementation evaluates the complement \(1-A\) in factored form so that a large gain does not cancel against a fourth-order term.

Each toe width is an unnormalized inverse-power soft minimum,

$$
\tau=\left(\sum_{v\in\mathcal V}v^{-8}\right)^{-1/8}.
$$

The list \(\mathcal V\) contains the constant \(2\) and \(0.1\) times every relevant radius: source radii for the angular toe, source and target radii for the chroma toe, and target and final radii for the Scale toe. The chroma toe therefore does not depend on Scale. Coefficients interpolate logarithmically between destination hues, which keeps ratios well behaved where a hue sector narrows.

### Angular law

For a source hue sector of width \(w\), destination endpoints \(\varphi_0,\varphi_1\) and slope \(m=(\varphi_1-\varphi_0)/w\), the shared vertex derivative is

$$
d=\left(\tfrac12\left(m_{\mathrm{left}}^{-4}+m_{\mathrm{right}}^{-4}\right)\right)^{-1/4},
$$

and a quintic Bézier spans the sector with control points

$$
[\varphi_0,\ \varphi_0+w d_0/5,\ \varphi_0+2w d_0/5,\ \varphi_1-2w d_1/5,\ \varphi_1-w d_1/5,\ \varphi_1].
$$

Periodic sectors keep a positive hue derivative, with shared first derivatives and zero second derivatives at each vertex, so the total angular map is a smooth increasing function of source hue. It is applied with a chroma fade,

$$
h_{\mathrm{out}}=h+S_5\!\left(\min(C/\tau_\theta,1)\right)\left(\mathrm{warp}(h)-h\right),
$$

where \(S_5(t)=6t^5-15t^4+10t^3\) and the angular toe uses the default radii. The fade keeps hue unchanged at neutral, where an angle has no meaning, and lets the warp reach full strength once chroma is well above the toe.

A web edit that would cross or collapse two handle angles is rejected and leaves the previous settings in place. Order preservation is checked on the target angles directly, not inferred from the control values.

## Adaptance: neutral destinations

Adaptance stores four direct neutral destinations, one a/b pair per tonal row, plus a half-influence saturation. It is not a control strength over an interpolated offset.

For each positive neutral anchor \(H_i\), let \(A_0=A_w(H_i/100)^{1/\gamma}\) and \(r_0=A_0/3.05\). Decode the requested neutral destination at that anchor through the eccentricity and inverse opponent matrix, obtaining three target responses \(r_i^\ast\), each required to lie strictly between \(0\) and \(400\). The positive response gain and its linear cone gain are then

$$
m_i=\frac{r_i^\ast(400-r_0)}{r_0(400-r_i^\ast)},\qquad g_i=m_i^{\,1/0.42}.
$$

\(g_i\) is local and cone-derived. It is not a change of viewing white: CAT16 supplies the cone basis, while the masking and normalization below are creative choices layered on it.

Between anchors, the gains interpolate logarithmically through the quintic cardinal weights with constant tails. Per pixel, the frozen selectors from the end of Tone decide how far the tint reaches. Let \(R\) be the saved half-influence saturation, with default \(0.25\) and allowed range \([0.05,1]\). Then

$$
v=\frac{R^4E_0^2}{R^4E_0^2+C_0^4},
$$

so nonblack neutrals have \(v=1\), a chromatic post-Tone state with frozen \(E_0=0\) has \(v=0\), and exact black is untouched. The pixel ratio \(C_0/\lvert J_A\rvert\) equals the independent setting \(R\) at half influence. Raising or lowering \(R\) changes how far the tint extends into saturated color without moving any of the four calibrated Adaptance neutral destinations.

The response transform uses parameter \(m_i^{v}\), corresponding to linear cone gain \(g_i^{v}\). The group law \(T_m\circ T_n=T_{mn}\) supplies this fractional gain directly, so the code evaluates \(T\) once. A common normalization \(k^{v}\) multiplies the result, where \(k\) is computed from a hypothetical neutral with the same frozen tonal height. This preserves the original neutral's \(J_A\) at the Adaptance output, including between anchors and on the signed neutral branch. The neutral may acquire chroma, so its \(J_{\mathrm{HK}}\) may change. Later H–K repair can change its achromatic energy; the normalization is not an invariant of the complete Stage 3 output.

For \(\lvert r\rvert\le400\) the response operation is the exact compression-conjugated gain,

$$
T_m(r)=\frac{m\,r}{1+(m-1)\lvert r\rvert/400},
$$

and beyond the physical response range an algebraic exterior continuation keeps the family total, strictly increasing, and reciprocal under \(m\mapsto1/m\). It joins with matching value, slope and curvature at \(\pm400\), but is generally only \(C^1\) at zero; the complete grade is not claimed globally \(C^2\).

Adaptance has an explicit inverse when the original selectors are supplied: divide the responses by \(k^v\), then apply the reciprocal gains. Recovering unknown selectors belongs to the full grade's joint solve.

## Compose the operators

The evaluation order is fixed:

1. The lightness and chroma coefficient rows above.
2. The web's hue warp and radial chroma edit, at fixed signed \(J_{\mathrm{HK}}\), carrying the achromatic energy.
3. Selective cone Adaptance, changing \(a/b\) and the signed achromatic energy.
4. With the default guard enabled, [H–K repair](hk-guard.md) uses the frozen post-Tone reference energy on the nonnegative-\(H\) branch. Negative \(H\) takes the signed bypass; `hk_guard=False` skips repair for diagnostics.
5. The web's final positive scale \(\lambda\), selected from the pre-Adaptance web state: multiply \(a/b\) by \(\lambda\) and the resulting carried energy by \(\lambda^2\).

The final scale comes last and is chosen before Adaptance and repair, so those operators cannot change its selection. It preserves \(C/\lvert J_A\rvert\) wherever that ratio is defined. With the default guard enabled, repair makes energy nonnegative for requests with \(H\ge0\), and positive Scale preserves its sign.

The six source rays begin with positive energy, but increasing chroma at fixed signed \(H\) can cross into negative energy; Adaptance can also change the energy. In the earlier Scale-before-repair order, the guard's balance could change as Scale varied because its source reference energy stayed fixed. Repairing the request first removes that interaction from final Scale.

The angular map preserves cyclic hue order at fixed chroma and tonal selector. This does not establish global hue ordering or injectivity for the complete color-dependent grade, which includes Adaptance. Appearance Stack handoffs carry the post-policy signed state after Scale. With the default guard enabled, nonnegative-\(H\) requests are repaired, while negative-\(H\) requests bypass repair; Scale multiplies either carried energy by \(\lambda^2\), preserving its sign. RGB cube projection happens only at export.

### Saturation pad and Scale

The reference pad projects the final repaired, scaled state directly:

$$
\mathbf p=\frac{(a,b)}{\sqrt{C^2+\lvert E\rvert}},\qquad
r^2=\frac{C^2}{C^2+\lvert E\rvert}.
$$

The horizontal coordinate is \(-p_b\), the vertical coordinate is \(+p_a\), and neutral/black maps to the center; define \(\mathbf p=(0,0)\) when \(C=E=0\). Handles and contours use this same state without a second H–K repair. The contextual zero-energy rim is selected from the signed request after Adaptance and before repair and Scale. Cube projection is excluded from the pad calculation.

For any common positive Scale \(\lambda\), \((a,b,E)\mapsto(\lambda a,\lambda b,\lambda^2E)\), so both pad coordinates and the radius remain unchanged. This identity holds on either energy branch. With fixed repaired \(E\ge0\) and \(C\ge0\), displayed lightness is

$$
H(\lambda)=\sqrt{\lambda^2E+66\lambda C}.
$$

It increases strictly for every nonblack repaired state; black remains black. Thus changing only Scale cannot move a reference handle inward on this pad in exact arithmetic. The frozen Blender implementation applies Scale before repair and can move its guarded marker; the corrected reference order is intended for future Next Blender Warp.

[WarpRepairedScale.lean](https://github.com/rei277hz/chromaticity/blob/main/libraries/perceptual-grade-reference/proofs/PerceptualGrade/WarpRepairedScale.lean) proves the energy law, pad invariance and monotonic lightness. Its repaired-state positivity results require \(H\ge0\) and nonnegative reference energy; strict positivity requires \(H>0\) and positive reference energy. The executable negative-\(H\) bypass is outside that guarantee. These are exact-real statements before cube export, not floating-point or complete-inverse guarantees. A later cube projection can still reduce chroma.

## Legacy controls

Earlier releases exposed three controls that this part does not describe, because the reference does not implement them:

- **Hue Concentration**, an orientation-preserving circle map that gathers hues toward a chosen direction with no change to \(H\) or \(C\).
- **Adaptance Strength and Adaptance Fit**, a scalar strength inside a chroma-protection envelope \(\alpha r(C)/(1-\alpha+\alpha r(C))\) with \(r(C)=.25+.75/(1+(C/30)^2)\).
- **Global low-chroma and high-chroma Hue**, two rotation coefficients weighted by the \(C_{\ell}\) and \(C_h\) drivers.

The 1.23.2 DCTL and Blender release implement all three, and their saved Grades use them. The reference replaced them with the web and the neutral destinations above, which is why saved settings from one are not reinterpreted as the other. Their full equations remain in the archived release documentation and in the retained DCTL oracle.

![Hue concentration and angular spacing](../assets/figures/color-hue-concentration.svg)

<p class="figure-caption">The 1.23.2 Concentration operator. Positive \(a\) concentration gathers nearby hues and expands the opposite side; the local spacing ratio stays positive, preserving its hue order. The reference replaces this operator with the web's angular map.</p>
