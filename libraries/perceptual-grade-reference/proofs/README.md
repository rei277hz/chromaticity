# Color-model properties

The `PerceptualGrade/` modules state mathematical properties of the appearance,
linear-color, tone, guard, spindle and tonal-web models. The reference library's
`//libraries/perceptual-grade-reference/proofs:color_model` target compiles every
theorem with pinned Lean and audits all
transitive axioms. It rejects unfinished proofs, unapproved axioms and unchecked
native computation. [Acceptance tests](../tests/proofs/test_checker.py) run with
`//libraries/perceptual-grade-reference/tests/proofs:color_model`; they include
false theorems and indirect foreign axioms.

These statements do not automatically prove correspondence with every Python,
GPU shader or DCTL implementation. Numerical tests and implementation-specific
validation provide that separate evidence.

`WarpRepairedScale.lean` formalizes the corrected reference order: repair after
Adaptance, then common positive J_A/chroma Scale. It proves the carried-energy
law E′=k²E, preservation of nonnegative/positive J_A and energy, invariance of
both compact Cartesian pad coordinates and radius, and strict increase of
H(k)=sqrt(k²E+66kC) on nonblack nonnegative rays. The composition theorem uses
the actual repaired energy and chroma from `HKCubeLuminance.lean`; no bound on
the unguarded signed deficit is required. H≥0 and nonnegative reference energy
give nonnegative repaired energy. Positive H and positive reference energy
imply strict positivity. Zero reference energy allows black, and the executable
negative-H bypass is outside the positivity guarantee.

`WarpScaleRay.lean` retains the negative-energy turning-point results as
diagnostics of the historical Scale-before-repair order. They do not constrain
the corrected repaired Scale. Cube projection can still change chroma after
these pad guarantees; the proofs stop before that lossy RGB operation.

Run reference proof validation through Buck2 remote execution:

```sh
buck2 build --remote-only //libraries/perceptual-grade-reference/proofs:color_model
buck2 test --remote-only //libraries/perceptual-grade-reference/tests/proofs:color_model
```
