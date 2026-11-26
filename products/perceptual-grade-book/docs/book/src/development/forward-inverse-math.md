# Forward and inverse math

This chapter specifies the current Perceptual Grade model and the adapter
contracts used by its products. The analytic reference in
`libraries/perceptual-grade-reference` is the authority for appearance-space
operations. Blender and Resolve adapt that model to different execution and
export boundaries, so their complete transforms are not interchangeable.

The equations below describe real-valued operations. Product kernels evaluate
them in finite precision and may use bounded numerical solvers. An inverse
claim always names the map and domain it covers.

## Model overview

For an RGB input (x), a reference forward grade has this structure:

$$
x \xrightarrow{\text{Linear}} x_1
\xrightarrow{\text{appearance encode}} (J_A,a,b,E)
\xrightarrow{\text{Tone and chroma}} q_2
\xrightarrow{\text{Color and Warp}} q_3
\xrightarrow{\text{H--K repair}} q_g
\xrightarrow{\text{decode and export}} y.
$$

The selected settings use either the integrated Tone/Chroma map or the
separate Tone and J/C controls. They are alternative control contracts. Warp
and Adaptance follow either configuration. The reference API selects the
integrated map by default. The detailed [Tone](../theory/tone.md),
[Color](../theory/color.md), [H--K repair](../theory/hk-guard.md), and
[Grade Stack](../guide/inverse-stack.md) chapters cover their respective user
controls and runtime behavior.

| Product path | Forward operations | Inverse contract |
| --- | --- | --- |
| Analytic reference `Model` | Linear, appearance encoding, selected Tone/Chroma path, Color/Warp, H--K repair, decode, and reference RGB boundary handling | Full RGB inverse searches and forward-validates candidates. The integrated Tone/Chroma sub-map has a separate uniqueness proof. |
| Blender Grade Stack | Ordered Grade entries in fixed AP1-D65 coordinates, then one sampled Stack LUT and the scene boundary | Per-entry inverse uses a bounded GPU solve where needed. The LUT records approximation residuals for affected vertices. |
| Resolve DCTL chain | Linear, XYZ input, Tone, Color J/C, Warp, then XYZ output with H--K repair | Color J/C and Warp expose local Direction controls. There is no single full-grade inverse node. |

## Coordinates and carried state

The appearance chart is represented by

$$
q=(H,a,b),\qquad C=\sqrt{a^2+b^2},\qquad
E=J_A\lvert J_A\rvert.
$$

Here (J_A) is the achromatic lightness and (H=J_{\mathrm{HK}}) includes
the chroma contribution. (E) is carried separately because recovering it
from rounded (H) and (C) can lose small signed values. With

$$
B=\sqrt{66C},\qquad M=\sqrt{J_A^2+66C},
$$

the signed H--K coordinate is

$$
H=\begin{cases}
M,&J_A\ge0,\\
2B-M,&J_A<0.
\end{cases}
$$

Tone and tonal selection use (M), not the reflected negative-side (H).
Chroma changes scale ((a,b)) along its current direction. The signed
appearance state retains both (J_A) and (E) across operations that need
them.

## Linear and appearance encoding

Let (P) convert the selected scene-linear RGB space to XYZ, (W_s) be the
source white, (W_d) the Grade white, and (A) the CAT16 matrix. The white
adaptation is

$$
M_{\mathrm{CAT}}=A^{-1}
\operatorname{diag}\!\left(\frac{AW_d}{AW_s}\right)A.
$$

Directional balance, spread, and heading form a white-preserving matrix
\(M_{\mathrm{dir}}\). Exposure (e), in stops, completes Stage 1:

$$
M_1=2^e M_{\mathrm{dir}}M_{\mathrm{CAT}},\qquad
X_1=M_1 P x.
$$

The complete reference currently fixes the Grade white to D65 and its viewing
reference to 203 nits. Its linear settings may supply a complete XYZ matrix
instead of the control-derived matrix. See [Linear](../theory/linear.md) for
the directional basis and the product-specific scene-space adapters.

For appearance encoding, normalize CAT16 cone responses by the destination
white. For a normalized cone value (n_i), the signed response is

$$
p_i=(F_L\lvert n_i\rvert)^{0.42},\qquad
r_i=\operatorname{sgn}(n_i)\frac{400p_i}{27.13+p_i}.
$$

The achromatic response (A_c=2r_R+r_G+0.05r_B) yields

$$
J_A=100\operatorname{sgn}(A_c)
\left\lvert\frac{A_c}{A_w}\right\rvert^\gamma.
$$

The opponent rows convert ((r_R,r_G,r_B)) to a preliminary pair
\((a_o,b_o)\). modCAM16's hue eccentricity factor \(\epsilon(\theta)\)
then sets the chart radius and direction:

$$
(a,b)=\frac{1204\epsilon(\theta)}{A_w}(a_o,b_o).
$$

Exact neutrals use (a=b=0). The encoder also handles the response pole with
retained response margins. The [Color theory chapter](../theory/color.md)
defines those eccentricity and opponent terms in full.

## Integrated Tone and Chroma

The reference's default 2–3A map first shapes chroma at the incoming (J_A),
then remaps the H--K magnitude while preserving hue and saturation. Let

$$
B_C=\frac{35}{75}\lvert J_A\rvert,\qquad
R(C;L,H,k)=C\frac{Lk+HC}{k+C},
$$

where (L,H>0) are endpoint gains and (k\ge0) is the radial knee. For
Muted/Vivid gains (g_m,g_v) in stops and crossover (p\in(0,1)),

$$
L=2^{g_m},\qquad H=2^{g_v},\qquad
k=B_C\frac{p}{1-p}\sqrt{\frac{H}{L}},\qquad
C_1=R(C;L,H,k).
$$

This one curve combines the two chroma controls. The neutral axis remains
neutral. At small nonzero chroma the gain tends toward the Muted endpoint.

Shadow and Highlight Chroma apply a second radial map. Define

$$
u=\min\!\left(1,\left\lvert\frac{\lvert J_A\rvert}{J_c}-1\right\rvert\right),
\qquad s(u)=u^2(3-2u),
$$

where (J_c) is the Tone Crossover. The amount (d) is the Shadow setting
below the crossover and the Highlight setting above it, multiplied by
(s(u)). Then

$$
C_2=R\!\left(C_1;1,2^d,\frac{B_C}{9}\right),\qquad
(a_2,b_2)=\frac{C_2}{C}(a,b),
$$

with the zero-chroma case defined as ((a_2,b_2)=(0,0)). This fade reaches
unity at the crossover and approaches the selected Shadow or Highlight amount
away from it. Both chroma maps use the original (J_A).

For source levels (x_i) and target levels (y_i), the Tone curve uses
normalized, strictly increasing knots. Its slope and residual rises are

$$
m=\min_i\frac{y_{i+1}-y_i}{x_{i+1}-x_i},\qquad
r_i=y_{i+1}-y_i-m(x_{i+1}-x_i)\ge0.
$$

With Fit (f\in[-2,2]), set (w=0.05\,2^{-f}). For each adjacent knot
pair, define the integrated sigmoid window

$$
K_i(t)=\int_0^t\left[
\sigma\!\left(\frac{v-x_i}{w}\right)-
\sigma\!\left(\frac{v-x_{i+1}}{w}\right)\right]dv,
\qquad
F(t)=mt+\sum_i r_i\frac{K_i(t)}{K_i(1)}.
$$

The nonnegative residuals and positive (m) make (F) strictly increasing.
Input Black compression first maps (z\ge0) to

$$
B_b(z)=z\frac{z+b}{z+2b},
$$

where (b) is the black parameter in normalized J, with identity when
(b=0). The curve acts on the compressed H--K magnitude. If the requested
output magnitude is (M_2), one positive ray gain gives

$$
g=\frac{2M_2^2}
{\operatorname{hypot}(66C,2J_A M_2)+66C},\qquad
(J_{A,2},a_3,b_3)=g(J_A,a_2,b_2).
$$

The same positive gain scales (C) and |(J_A)|, preserving
modCAM16 saturation when (J_A\ne0). The zero denominator uses the black
limit. Tone landmarks and effective peak selection are described in
[Saturation-preserving Tone](../theory/tone.md).

### Inverse of the integrated map

For fixed (J_A), solving (y=R(C;L,H,k)) gives

$$
HC^2+(Lk-y)C-yk=0.
$$

When (L,H>0), its radial derivative is positive for (C\ge0). It has one
nonnegative solution, including the (k=0) limit (C=y/H). The implementation
uses a scaled, cancellation-resistant quadratic evaluation. The inverse undoes
the Shadow/Highlight map, then the Muted/Vivid map, both at the preserved
incoming (J_A).

Black compression is strictly increasing on (z\ge0), and the Tone curve
has positive slope everywhere. Its inverse therefore has one nonnegative
solution. The implementation brackets and bisects this scalar root, then
recovers the input ray scale. Thus the integrated stage has a unique
real-valued inverse even though its Tone calculation uses a numerical solve.
The exact-real result is proved in
`libraries/perceptual-grade-reference/proofs/PerceptualGrade/UnifiedChroma.lean`.
The proof covers this integrated map and ends at its handoff to Color/Warp.

## Color, Warp, and H--K repair

The separate Tone/J/C configuration applies its J/C controls after Tone.
Four tone-dependent coefficient rows weight low- and high-chroma drivers and
the signed opponent axes. With (C=\operatorname{hypot}(a,b)) and
(R=(35/75)\lvert J_A\rvert), define

$$
V=\frac{C^2}{C^2+4},\qquad
d_{\mathrm{low}}=V\frac{R^2}{C^2+R^2},\qquad
d_{\mathrm{high}}=V\frac{C^2}{C^2+R^2},
$$

$$
d_a=\frac{a}{\sqrt{C^2+4}},\qquad
d_b=\frac{b}{\sqrt{C^2+4}}.
$$

The low/high weights sum to the neutral-visibility factor (V). At an exact
neutral every driver is zero. The weighted lightness coefficients add to
(H), and the weighted chroma coefficients plus Global Gain set one positive
gain on ((a,b)). The four controls overlap smoothly through their coefficient
curves. These separate J/C controls cannot be combined with nondefault
integrated Tone/Chroma settings in the reference `Model`.

The Warp web has four tonal rows and six Rec.709 hue handles. It maps hue by a
periodic increasing curve and maps chroma by monotone radial fields with a
neutral toe. Selective Adaptance then applies tone-dependent cone gains toward
the authored neutral destinations. The [Color chapter](../theory/color.md)
specifies the web interpolation, radial law, and response-gain equations.

The reference order after the selected Tone/J/C path is

$$
\text{Warp hue/chroma}
\;\to\;\text{Adaptance}
\;\to\;\text{H--K repair}
\;\to\;\text{common positive Scale}.
$$

H--K repair uses the frozen post-Tone reference energy. For a nonnegative
requested (H), it shares correction between a bounded lightness lift and
chroma reduction while preserving hue. The final Scale multiplies
((J_A,a,b)) by (\lambda>0) and (E) by (\lambda^2). Repair is not
repeated during RGB decoding. Negative (H) follows the documented signed
bypass. See [Bounded H--K guard](../theory/hk-guard.md) for its full formula,
branch conditions, and cube-export rules.

## Product boundaries

### Reference and Blender

The reference's full RGB entry applies the AP1 input repair required by its
Blender-compatible boundary. Its exported RGB path decodes the carried
appearance state and, when requested, applies the actual-decoder cube guard in
([0,1024]^3). That projection is lossy. Appearance-state Stack handoffs
carry repaired state directly and avoid an intermediate RGB export.

The Blender extension evaluates the same Tone/Chroma and Warp ordering in its prepared
Grade kernel. A Stack composes entries in fixed AP1-D65 coordinates and
samples the whole sequence once. Forward and inverse entries can hand off
appearance state without decoding it between entries. Only final export uses
the AP1 boundary. The [Stack guide](../guide/inverse-stack.md) describes its
LUT lifecycle and user-visible approximation report.

### Resolve DCTL

Resolve uses six serial DCTLs. Linear adjusts scene-linear XYZ D65. XYZ Input
converts to signed cone responses. Cone Tone applies the Tone curve, Cone
Color J/C applies its J/C controls, Cone Warp applies hue/chroma, Adaptance,
and Scale, and XYZ Output performs H--K repair before decoding to XYZ D65.
Resolve does not apply the Blender AP1 input repair or AP1 cube boundary.
Signed and above-range XYZ values are retained by the cone chain.

Resolve's Warp node places Scale before the final H--K repair in XYZ Output.
The reference and Blender extension repair before their final positive Scale. This
ordering difference is part of the product contract. It means a Color-node
inverse must be evaluated within the matching Resolve chain, not substituted
for the reference or Blender inverse.

## Inverse contracts

### Reference full-grade inverse

`Model.inverse_xyz` searches for candidates to the complete exported forward
map. It works in asinh canonical RGB coordinates, uses a fixed multistart set,
and applies damped least-squares updates with a 128-iteration cap. Every result
is evaluated again through the complete forward path. A row is reported as
`root` only when its scaled maximum residual is at most \(2\times10^{-10}\).
Otherwise it reports the best candidate as `approximate`; nonfinite rows are
`invalid`.

Among the roots found, the solver chooses the one nearest its linear prior.
The seed set is finite, so it does not enumerate every possible preimage or
prove that a closer root was not missed. The separate reference Stack oracle
searches inside the nonnegative AP1 cube and also reports residuals rather than
claiming uniqueness.

### Blender Stack inverse

The Stack inverse reverses Tone/Chroma analytically where possible. It uses
the quadratic radial inverses and a bounded bisection for the Tone curve.
Warp inversion then uses a bounded damped solve over its three appearance
coordinates. Candidate states are checked against the complete forward Grade
and the requested appearance or RGB target. A Stack LUT may therefore contain
approximate inverse vertices. The product reports their count and worst
residual instead of treating an approximation as an exact root.

The integrated Tone/Chroma uniqueness proof does not extend through Warp,
Adaptance, H--K repair, or AP1 cube projection. Those operations and the export
boundary are part of the full Stack residual. A full Grade Stack inverse is
not claimed globally unique.

### Resolve DCTL Direction

Color J/C and Warp can be placed in inverse Direction. Their local inverse
branches reverse their corresponding forward operations. Some components use
bounded iteration, including Tone and Warp inversions in the Resolve product
DCTLs.
The six-node chain does not provide one inverse for Linear through XYZ Output,
and the final H--K repair has no paired inverse node. For two Color operations,
reverse their serial order when applying their inverses.

The distinction is between a unique inverse for the integrated 2–3A map on
signed appearance triples and a full product inverse. Only the former has the
exact-real uniqueness theorem. A measured residual establishes reproduction
for a particular candidate; it does not establish global uniqueness.
