# Evaluation and interpolation

The current analytic reference is `libraries/perceptual-grade-reference`. Its Stage 3 evaluates lightness/chroma rows → Warp hue/chroma → selective Adaptance → H–K repair → common positive Scale. The frozen Blender implementation and the archived 1.23.2 DCTL retain their own ordering and controls. Next Blender has not exposed Warp yet; its future implementation must follow the corrected reference.

## From appearance to RGB

H–K repair belongs inside Stage 3. It uses frozen post-Tone reference energy and runs after Adaptance, before Scale. For a repaired point, Scale sends \((a,b,E)\) to \((\lambda a,\lambda b,\lambda^2E)\), with \(\lambda>0\). The saturation-pad point \((a,b)/\sqrt{C^2+|E|}\) stays fixed. On the nonnegative-H repair branch, \(E\ge0\); its scaled H–K height is \(\sqrt{\lambda^2E+66\lambda C}\), increasing strictly for every nonblack point.

`Model.grade_state` returns this repaired, scaled appearance. A forward→inverse Stack handoff carries it directly, bypassing only RGB cube projection. `release_state(..., guard=False)` decodes the supplied state; `guard=True` applies only the export cube guard. H–K repair is not idempotent and must not be repeated at export or when drawing the pad.

The export cube guard checks the actual decoder and native AP1 RGB cube \([0,1024]^3\). For interior positive energy, it holds \(J_A\) and hue while reducing chroma until decoding is legal. Nonpositive energy exports black; energy at or above the cube-white endpoint exports cube white. Decoder trials with response magnitude at or beyond the pole at 400 are rejected. This projection can change saturation after the pad's appearance-space guarantee, and is lossy.

The [bounded H–K guard](hk-guard.md) gives the repair equations, signed-energy treatment and separate export policy. The reference inverse evaluates the complete forward function, including repair before Scale and final cube containment, for every candidate. It does not nest a standalone H–K inverse inside that search; see the [reference inverse contract](../development/forward-inverse-math.md#20-the-reference-inverse).

## Approximate the complete function

A LUT samples the complete function of its selected profile. Input repair, Stage 3 H–K repair and RGB cube containment are deliberate parts of that function; finite sampling and interpolation add approximation error. Agreement between two samplers therefore does not establish agreement with the analytic grade.

[Direct and sampled evaluation](lut.md) describes the native AP1 input grid, input repair, physical-linear-RGB interpolation and the different table profiles. The recorded plots and measurements identify the older implementations that produced them; they do not validate the corrected Warp ordering.

## Keep the result tied to its settings

A completed table is valid only for the settings and model that produced it. Its signature includes model version, size, sampling space, address constants and every control that changes the function. A changed function requires a replacement table.

- **A stale table must never be presented as current.** A last-good result may remain visible with an updating indication. If the current kernel cannot be built or recovered, fail visibly with magenta output preserving alpha.
- **A preview is identified as a preview.** A coarse table may update during interaction, while final rendering requires the completed current result. Nested 33³/65³ grids reuse their shared vertices exactly.

The [Next Blender policy machines](../development/next-policies.md) document the current product's publication and render-preflight contract. The [runtime architecture](../development/architecture.md) and legacy inverse implementation sections retain historical behavior under their stated scope.
