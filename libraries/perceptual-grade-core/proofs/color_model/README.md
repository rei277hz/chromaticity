# Color-model properties

The `PerceptualGrade/` modules state mathematical properties of the appearance,
linear-color, tone, guard, spindle and tonal-web models. The owning library's
`color_model` Buck target compiles every theorem with pinned Lean and audits all
transitive axioms. It rejects unfinished proofs, unapproved axioms and unchecked
native computation. Acceptance tests live in `tests/proofs/` beside this proof
tree; they include false theorems and indirect foreign axioms.

There are currently 30 modules and 571 checked theorems. The functional directory
name reflects the model being checked; `.lean` identifies the tool used.
These statements do not automatically prove correspondence with every Python,
GPU shader or DCTL implementation. Numerical tests and implementation-specific
validation provide that separate evidence.
