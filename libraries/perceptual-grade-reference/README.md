# Perceptual Grade reference

The source package is `color_tools.perceptual_grade_reference`; run its JSON
CLI with `buck2 run --remote-only //libraries/perceptual-grade-reference:evaluate`.
The [source-package README](src/README.md) contains
the detailed model contract.

The reference's Colour equations remain independent of production appearance
integration. Explicitly shared numerical kernels come from
`color_tools.perceptual_grade_core.model` through normal dependencies, and
agreement on those shared algorithms is not independent correctness evidence.
The reference has no required Blender dependency. It owns the accelerated CPU
kernel, forward/inverse/boundary GPU shader builders and optional Blender GPU
adapter; callers can supply a `program_factory` when constructing `BakeStack`.

Stage 3 evaluates J/C edits → Warp hue/chroma → Adaptance → H–K repair →
common positive J_A/chroma Scale. Appearance handoffs contain this repaired,
scaled state; RGB export applies only cube containment. Repair is not repeated
at export. Its nonnegative-H branch has nonnegative energy, so positive Scale
preserves the compact pad coordinates and cannot enter the negative-energy
Scale branch. Negative-H requests retain the existing bypass and black export
policy. The frozen `perceptual-grade-blender` implementation retains its
historical order; `perceptual-grade-next-blender` has not implemented Warp yet.

Analytic low/high chroma membership crosses at `C=(35/75)*abs(J_A)`, with
neutral visibility `C²/(C²+4)` and frozen post-Tone inputs. This applies to
float64/scaled Model, inverse, Stack, CLI and reference BakeStack CPU/GLSL
evaluation. BakeStack supports nonzero low/high lightness/chroma controls.
Shared production kernels retain their historical `.4*capacity` behavior.
Existing product comparisons opt into `tests.reference.legacy_capacity` through
the separate `tests:legacy_capacity_support` target; those verification adapters
are excluded from runtime bundles.
The reference owns the [Lean color-model proofs](proofs/README.md) and their
[acceptance tests](tests/proofs/test_checker.py). Build them with
`//libraries/perceptual-grade-reference/proofs:color_model`; the acceptance target
is `//libraries/perceptual-grade-reference/tests/proofs:color_model`.
Preserved production Lean driver proofs retain their capacity-based scope and
do not certify the reference's newer crossover equation. Proof ownership does not
expand their implementation-correspondence claims.

See [historical crossover acceptance evidence](CROSSOVER_EVIDENCE.md) for the
previous implementation's tests, build identities and GPU-suite limitation.
Those recorded results do not validate the current ordering change.

Host-free numerical studies live under `tools/analysis/`. Their Buck targets
generate the retained radial, spindle, driver and tonal-web reports and figures.
Host rendering and execution profiles belong to `perceptual-grade-blender`.
