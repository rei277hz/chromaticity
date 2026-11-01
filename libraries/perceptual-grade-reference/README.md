# Perceptual Grade reference

The source package is `color_tools.perceptual_grade_reference`; run its JSON
CLI with `buck2 run //libraries/perceptual-grade-reference:evaluate`.
The [source-package README](src/perceptual_grade_reference/README.md) contains
the detailed model contract.

The reference's Colour equations remain independent of production appearance
integration. Explicitly shared numerical kernels come from
`color_tools.perceptual_grade_core.model` through normal dependencies, and
agreement on those shared algorithms is not independent correctness evidence.
The reference has no Blender dependency. GPU callers pass a `program_factory`
when constructing `BakeStack`; the standalone default supports CPU execution
for controls whose equations agree with the shared kernels.

Analytic low/high chroma membership crosses at `C=(35/75)*abs(J_A)`, with
neutral visibility `C²/(C²+4)` and frozen post-Tone inputs. This applies to
float64/scaled Model, inverse, Stack and CLI evaluation. Shared production
kernels still use `.4*capacity`; reference BakeStack rejects nonzero low/high
lightness/chroma controls before preparation. Other controls remain supported.
Existing product comparisons opt into `tests.reference.legacy_capacity` through
the separate `tests:legacy_capacity_support` target; those verification adapters
are excluded from runtime bundles.
Preserved production Lean driver proofs retain their capacity-based scope and
do not certify the reference's newer crossover equation.

See [crossover acceptance evidence](CROSSOVER_EVIDENCE.md) for tests, analysis
checks, exact build identities and the recorded unrelated GPU-suite limitation.

Host-free numerical studies live under `tools/analysis/`. Their Buck targets
generate the retained radial, spindle, driver and tonal-web reports and figures.
Host rendering and execution profiles belong to `perceptual-grade-blender`.
