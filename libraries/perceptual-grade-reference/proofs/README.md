# Color-model properties

The `PerceptualGrade/` modules state mathematical properties of the appearance,
linear-color, tone, guard, spindle and tonal-web models. The reference library's
`//libraries/perceptual-grade-reference/proofs:color_model` target compiles every
theorem with pinned Lean and audits all
transitive axioms. It rejects unfinished proofs, unapproved axioms and unchecked
native computation. [Acceptance tests](../tests/proofs/test_checker.py) run with
`//libraries/perceptual-grade-reference/tests/proofs:color_model`; they include
false theorems and indirect foreign axioms.

There are currently 30 modules and 571 checked theorems.
These statements do not automatically prove correspondence with every Python,
GPU shader or DCTL implementation. Numerical tests and implementation-specific
validation provide that separate evidence.
