# Direct and sampled evaluation

Perceptual Grade uses analytic appearance operations with product-specific
execution. Blender's Grade node binds prepared settings to a native graph. A
Grade Stack evaluates its ordered entries into one sampled transform. The
Resolve DCTL chain evaluates its stages serially and does not use the Blender
Stack table.

## Blender Stack grid

The Stack cube uses fixed linear ACEScg and ACES-white coordinates. Each RGB
axis contains 65 samples over \([0,1024]\), spaced by the plain log1p shaper
with \(\kappa=0.01\). The 33-sample preview uses every other coordinate of
the final grid. The range describes the Stack sampling domain, not a display
range or a clamp on stored output values.

For \(R=1024\), define

$$
A=\ln(1+R/\kappa),\qquad
S(x)=\frac{\ln(1+x/\kappa)}{A},\qquad
S^{-1}(u)=\kappa\left[\exp(Au)-1\right].
$$

The vertices are \(x_i=S^{-1}(i/64)\), for \(0\le i\le64\), with exact
zero and upper endpoints. A Stack cube stores the complete ordered grading
function at its vertices, including the entries' Linear matrices and white
connections.

![Nonuniform input samples across the Stack domain](../assets/figures/lut-input-grid.svg)

<p class="figure-caption">The 65-point AP1 axis covers the full Stack domain. The second panel enlarges the spacing near black.</p>

## Tetrahedral interpolation

Address each channel in the shaped coordinate, locate its neighboring
physical vertices, then compute the fraction in linear RGB:

$$
i=\operatorname{clamp}\!\left(\left\lfloor64S(x)\right\rfloor,0,63\right),\qquad
f=\frac{x-x_i}{x_{i+1}-x_i}.
$$

Order the three fractions as \(f_1\ge f_2\ge f_3\). The tetrahedron's
vertices follow that channel order from the lower corner to the upper corner.
The implementation evaluates the equivalent difference form

$$
v=v_0+f_1(v_1-v_0)+f_2(v_2-v_1)+f_3(v_3-v_2).
$$

This form reproduces affine functions in exact arithmetic and avoids
subtracting a large constant offset. Shader lookup stores raw float RGB.
Compositor lookup stores the base value and three ordered edge differences in
separate planes, with independently scaled signed coefficients for
half-float transport. The host's precision setting remains authoritative.

![Stack address and interpolation coordinates](../assets/figures/lut-interpolation.svg)

<p class="figure-caption">The logarithmic shaper selects a nonuniform cell. Tetrahedral interpolation uses the input's physical fraction within that cell.</p>

The cell index stays within the edge cells, while the physical fraction is
computed from the original coordinate. Input conversion and boundary policy
are handled by the caller. Output conversion and RGB containment are separate
from interpolation.

## Prepared Grade resources

The Blender Grade graph binds current prepared values through a fixed native
template. Complete parameter banks are staged and validated before the active
selector changes. A failed update restores the prior bank metadata or selects
the visible error path. The [runtime policies](../development/policies.md)
describe admission, receipts, freshness, and recovery.

The Stack helper evaluates both preview and final resolutions. A matching
preview is identified as incomplete until the final cube is ready. Its inverse
entries may require numerical solving; unresolved or out-of-tolerance vertices
are reported, and an approximate result is not described as exact. See the
[forward and inverse specification](../development/forward-inverse-math.md)
and [Grade Stack guide](../guide/inverse-stack.md) for their contracts.
