# Linear correction

The analytic reference builds Stage 1 as an XYZ matrix, equivalent to a working-RGB matrix by change of basis. Its nine control degrees of freedom have three distinct roles: one for exposure, two for source-white adaptation and six for color relationships around a fixed destination white.

## Separate the nine degrees of freedom

Global Exposure supplies one degree of freedom: a common gain that changes luminance without changing chromaticity. Source White supplies two more, placing the neutral at the chosen destination white.

The remaining six controls shape color relationships around that fixed white. Both Balance controls change colored-pixel luminance. Both Spread and both Heading controls also preserve luminance when Balance is zero.

These are independent control roles, not a claim that their matrices are orthogonal under a Euclidean matrix inner product. Exposure controls the global scale; adaptation places the neutral; directional correction shapes the colors around that neutral. The combined working-RGB matrix is

$$
M_{\mathrm{RGB}}=2^e N^{-1}M_{\mathrm{dir}}M_{\mathrm{CAT}}N,
$$

where \(N\) converts grading RGB to XYZ. In the complete reference Model, the destination Grade white is fixed at D65. The archived products expose the additional white choices described in [Working White](../guide/working-white.md).

Many RGB mixers offer a preserve-luminance option. Preserving the white is a separate constraint: changing colored relationships should not move a neutral off the white you just established. Here every directional adjustment fixes that white by construction. This is the practical advantage of the six-control layout over editing nine unconstrained mixer coefficients.

Luminance and white preservation should not be conflated. The two Balance controls deliberately change the luminance of colored pixels while retaining white. Holding both an arbitrary white vector and every pixel’s \(Y\) fixed leaves four matrix degrees of freedom, not six.

## Adapt white with CAT16

Let \(W_s\) and \(W_d\) be unit-Y source and destination XYZ whites, and \(A\) be the CAT16 matrix. Complete adaptation scales the three cone responses to map \(W_s\) to \(W_d\):

$$
M_{\mathrm{CAT}}=A^{-1}\operatorname{diag}
\left(\frac{AW_d}{AW_s}\right)A.
$$

The source-white controls supply its two chromaticity coordinates. The reference clamps them to \([0,.9]^2\), then projects to the nearest point in the CAT16-positive polygon, which keeps cone gains positive with a small safety margin. Nonfinite source coordinates are errors. The complete reference maps that source white to D65; archived product controls can select other destination whites. Exposure then supplies the independent overall luminance scale.

The reference evaluates the equivalent form

$$
M_{\mathrm{CAT}}=I+A^{-1}\operatorname{diag}(r-1)A,\qquad r=\frac{AW_d}{AW_s}.
$$

This makes equal source and destination whites an exact identity without a tolerance check. The ratio form above is algebraically equivalent; the forms can differ only through floating-point rounding.

## Shape color while keeping white

Two reference directions begin at 30% of the adapted Rec.709 red and blue displacements from destination white. Spread changes each displacement’s length, Heading rotates it, and Balance supplies its reference luminance gain.

$$
\mathbf p'_i=\mathbf w_d+
\left(1+\frac{\mathrm{Spread}_i}{100}\right)
R_{\mathrm{Heading}_i}(\mathbf p_i-\mathbf w_d),
\qquad V'_i=2^{b_i}\operatorname{XYZ}(p'_{i,x},\max(.01,p'_{i,y}),Y=1).
$$

Internal \(b_i\) is the negative of the displayed Balance value. Build a basis from white and the two unit-Y reference vectors:

$$
B=[W_d\ V_r\ V_b],\qquad
M_{\mathrm{dir}}=[W_d\ V'_r\ V'_b]B^{-1},\qquad
M_{\mathrm{dir}}W_d=W_d.
$$

With both Balance controls zero, all three output basis columns retain their input \(Y\), so every linear combination also retains \(Y\). The four Spread/Heading parameters then change chromatic relationships while preserving both luminance and white. Balance adds the other two degrees of freedom without releasing the white constraint.

![White-fixed directional basis and CAT16 gains](../assets/figures/linear-basis.svg)

<p class="figure-caption">Left: Balance changes colored-pixel luminance around an unchanged white. The two directional responses coincide at each setting. Right: CAT16 independently adapts the source white to the working white.</p>

The current reference requires finite control values but does not impose product UI ranges. \(\mathrm{Spread}=-100\) can collapse a direction and some settings can make the directional matrix singular; the parameter count does not imply every possible \(3\times3\) matrix is reachable. Stage 2 begins only after this linear correction is complete.

## Implementation domain

The complete reference Model fixes the Grade white to D65. Its `LinearSettings` can also carry an authoritative finite \(3\times3\) XYZ matrix; when supplied, this matrix replaces the control construction and may be singular. This override is part of the reference API, not one of the nine controls. The archived DCTL and Blender products have their own UI ranges and destination-white settings.
