# Code and grading model

Begin with the model or product boundary that owns the behavior. The
[architecture chapter](architecture.md) maps the reference, Blender runtime,
and Resolve DCTL layers. Keep host-independent equations in
`libraries/perceptual-grade-reference`; implement host integration in the
corresponding product.

For a model change, define the forward behavior and its valid domain first.
Preserve explicit invariants such as identity at reset, finite signed and HDR
inputs where supported, hue or saturation preservation, ordering, and inverse
round trips. Update the reference's numerical tests and proof requirements
when a model equation or guarantee changes.

Blender changes belong to their feature owner under
`products/perceptual-grade-next-blender/src/features/`. Keep derived settings
and prepared resources tied to authoritative Grade state. Put shared
host-neutral lifecycle or capture primitives in `src/runtime/` only when
multiple features use the same contract. Policy effects authorize external
mutations; runtime consumers perform them. Update the product's policy,
runtime, native, or installed tests according to the changed boundary.

Resolve DCTL changes belong under `products/perceptual-grade-dctl/src/` and
its generator and tests. DCTL sliders, localized declarations, and execution
order are host-facing interfaces. Verify the generated C/OpenCL entry points
against independent reference calculations. Resolve GPU compilation and
interactive operation still require Resolve itself.

For changes shared across products, compare their adapters with the reference
at matching input, output, and stage boundaries. Product-specific export
behavior may differ; record the boundary and include it in the tests. The
[forward and inverse mathematics](forward-inverse-math.md) chapter documents
the current equations and inverse contracts.
