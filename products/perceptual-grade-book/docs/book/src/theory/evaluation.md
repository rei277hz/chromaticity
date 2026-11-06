# Evaluation and interpolation

The equations define one grade. Producing the same result in an analytic DCTL, a native node graph and a sampled color table also requires a valid inverse domain and controlled numerical approximations. This chapter follows those requirements from the end of Color to the returned linear color.

There are four distinct things in the pipeline after the Color coefficients, and they are routinely confused with each other:

1. **H–K repair**, a fixed-reference repair of the requested appearance pair. It is part of the model: every implementation applies it, and its result is what the later stages see.
2. **Decoding**, the signed inverse of the appearance encoding, which requires a real positive achromatic energy and a response magnitude strictly below the pole at 400.
3. **The export cube guard**, a projection onto the native AP1 RGB bound that holds \(J_A\) and hue and reduces chroma. It runs only at export.
4. **Sampled evaluation**, a table lookup and interpolation that approximates the composed function at a finite number of vertices.

Steps 1 and 2 are model transformations. Steps 3 and 4 are approximations of a different kind: the guard changes the color on purpose, while the table changes it by error. A measurement that agrees between two table implementations therefore says nothing about whether either agrees with the analytic grade.

The [bounded H–K guard](hk-guard.md) covers steps 1 and 2, including the signed energy path and the export projection. Its historical evaluation explains how the current guard was chosen, with recorded experiments kept distinct from regenerated comparisons.

[Direct and sampled evaluation](lut.md) covers step 4: the extension's curve tables, the signed HDR sampling grid and physical-linear-RGB interpolation. It also distinguishes agreement with a sampler from agreement with the analytic grade: matching interpolation implementations does not remove the color table's approximation error.

## Keep the paths on the same settings

The same current parameters must reach both paths. A completed LUT is accepted only for the grade that produced it, while forward nodes use Direct during preparation and inverse and Stack nodes retain their previous completed LUT. A table is identified by its model, size, sampling space, address constants and every control that changes the function; a change to any of them invalidates it rather than reusing it with different numbers.

Two consequences follow, and both have been the source of real defects:

- **A stale table must never be presented as current.** If a replacement cannot be completed, the correct behaviour is a visible failure that preserves alpha, not a silent fallback that keeps rendering the previous result.
- **Previews are not results.** A coarse preview installs and updates interactively, but final rendering and ordinary saving require the completed table. The nesting is arranged so the preview vertices are a subset of the final ones and are reused exactly, never recomputed with different arithmetic.

The [runtime architecture](../development/architecture.md) explains how the extension maintains that agreement during interaction, and the [full specification](../development/forward-inverse-math.md) gives the boundary conversions and the inverse contract.
