# Evaluation and interpolation

The analytic reference in `libraries/perceptual-grade-reference` defines the
appearance transform and its forward and inverse contracts. Product adapters
prepare that model for their host. Blender binds prepared data to native Grade
graphs and bakes complete Grade Stacks into sampled cubes. The Resolve DCTL
chain evaluates its stages serially in scene-linear XYZ and signed cone
coordinates.

## From appearance to RGB

In the reference, Stage 3 applies the tonal J/C controls and Warp, then
selective Adaptance, H–K repair, and common positive Scale. For a repaired
point, Scale sends \((a,b,E)\) to \((\lambda a,\lambda b,\lambda^2E)\), with
\(\lambda>0\). The saturation-pad point
\((a,b)/\sqrt{C^2+|E|}\) remains fixed. On the nonnegative-H repair branch,
\(E\ge0\), and the resulting H–K height increases strictly for every
nonblack point.

`Model.grade_state` returns this repaired, scaled appearance. A
forward-to-inverse Stack handoff carries it directly without RGB projection.
`release_state(..., guard=False)` decodes the supplied state;
`guard=True` applies the reference export-cube guard. H–K repair is not
idempotent and is not repeated at RGB export.

The Resolve chain has its own stage boundary. Warp applies Scale, then XYZ
Output performs H–K repair before decoding to scene-linear XYZ D65. This
product-specific order is described in [Architecture and runtime](../development/architecture.md)
and in the [forward and inverse specification](../development/forward-inverse-math.md).

The reference export guard checks the actual decoder and native AP1 RGB cube
\([0,1024]^3\). For interior positive energy, it holds \(J_A\) and hue while
reducing chroma until decoding is legal. Nonpositive energy exports black;
energy at or above the cube-white endpoint exports cube white. Decoder trials
at or beyond the response pole at 400 are rejected. This projection can change
saturation after the appearance-space guarantee and is lossy.

## Approximate the complete function

A sampled table approximates the complete function of its selected product
path. Input-coordinate conversion, the grading stages, and output containment
are part of that function. Sampling and interpolation add their own error, so
agreement between two samplers does not establish agreement with the analytic
model.

The [direct and sampled evaluation chapter](lut.md) describes the Blender
Stack grid, its physical-linear-RGB interpolation, and prepared Grade data.
The Resolve DCTL chain uses analytic stage code rather than a Stack LUT.

## Keep results tied to their settings

A completed Blender resource is valid only for the settings and model that
produced it. Its signature includes the model version, sampling configuration,
and every control that changes the function. A changed function requires a
replacement resource.

- **A stale table is never presented as current.** A last-good result may
  remain visible with an updating indication. If the current kernel cannot be
  built or recovered, the product shows an error and alpha-preserving magenta
  output.
- **A preview is identified as a preview.** A coarse table can update during
  interaction, while final rendering requires the completed current result.
  Blender's Stack uses 33³ and 65³ tables.

The [runtime policies](../development/policies.md) document publication,
reconciliation, and render-preflight contracts. The [runtime architecture](../development/architecture.md)
describes how each product evaluates the model.
