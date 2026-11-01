# Linear correction

The extension’s Stage 1 remains a linear RGB operation, with an equivalent linear-XYZ matrix in the DCTL. Its nine degrees of freedom have three distinct control roles: one for exposure, two for chromatic adaptation and six for color relationships around a fixed white.

## Separate the nine degrees of freedom

Global Exposure supplies one degree of freedom: a common gain that changes luminance without changing chromaticity. Source White supplies two more, placing the neutral at the chosen destination white.

The remaining six controls shape color relationships around that fixed white. Both Balance controls change colored-pixel luminance. Both Spread and both Heading controls also preserve luminance when Balance is zero.

These are independent control roles, not a claim that their matrices are orthogonal under a Euclidean matrix inner product. Exposure controls the global scale; adaptation places the neutral; directional correction shapes the colors around that neutral. The combined working-RGB matrix is

$$
M_{\mathrm{RGB}}=2^e N^{-1}M_{\mathrm{dir}}M_{\mathrm{CAT}}N,
$$

where \(N\) converts grading RGB to XYZ. The Blender scene boundary and chosen white are described in [Working White](../guide/working-white.md).

Many RGB mixers offer a preserve-luminance option. Preserving the white is a separate constraint: changing colored relationships should not move a neutral off the white you just established. Here every directional adjustment fixes that white by construction. This is the practical advantage of the six-control layout over editing nine unconstrained mixer coefficients.

Luminance and white preservation should not be conflated. The two Balance controls deliberately change the luminance of colored pixels while retaining white. Holding both an arbitrary white vector and every pixel’s \(Y\) fixed leaves four matrix degrees of freedom, not six.

## Adapt white with CAT16

Let \(W_s\) and \(W_d\) be unit-Y source and destination XYZ whites, and \(A\) be the CAT16 matrix. Complete adaptation scales the three cone responses to map \(W_s\) to \(W_d\):

$$
M_{\mathrm{CAT}}=A^{-1}\operatorname{diag}
\left(\frac{AW_d}{AW_s}\right)A.
$$

The source-white controls supply its two chromaticity coordinates. The allowed region keeps the cone gains positive with a small safety margin. The extension uses the shared Grade’s selected Working White, default D65; the DCTL uses its Destination White setting. Exposure then supplies the independent overall luminance scale.

## Shape color while keeping white

Two reference directions begin at 30% of the adapted Rec.709 red and blue displacements from destination white. Spread changes each displacement’s length, Heading rotates it, and Balance supplies its reference luminance gain.

$$
\mathbf p'_i=\mathbf w_d+
\left(1+\frac{\mathrm{Spread}_i}{100}\right)
R_{\mathrm{Heading}_i}(\mathbf p_i-\mathbf w_d),
\qquad V'_i=2^{b_i}\operatorname{XYZ}(\mathbf p'_i,Y=1).
$$

Internal \(b_i\) is the negative of the displayed Balance value. Build a basis from white and the two unit-Y reference vectors:

$$
B=[W_d\ V_r\ V_b],\qquad
M_{\mathrm{dir}}=[W_d\ V'_r\ V'_b]B^{-1},\qquad
M_{\mathrm{dir}}W_d=W_d.
$$

With both Balance controls zero, all three output basis columns retain their input \(Y\), so every linear combination also retains \(Y\). The four Spread/Heading parameters then change chromatic relationships while preserving both luminance and white. Balance adds the other two degrees of freedom without releasing the white constraint.

![White-fixed directional basis and CAT16 gains](../assets/figures/linear-basis.png)

<p class="figure-caption">Left: Balance changes colored-pixel luminance around an unchanged white. Right: CAT16 independently adapts the source white to the working white.</p>

The positive gains and bounded UI ranges define a practical part of matrix space. \(\mathrm{Spread}=-100\) can collapse a direction and extreme headings can approach degeneracy; the parameter count does not imply every possible \(3\times3\) matrix is reachable. Stage 2 begins only after this linear correction is complete.
