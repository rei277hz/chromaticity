# State-machine redesign moved to the new product

The audited state-machine design was implemented in the rebuilt Blender product.
Its host-free policies live in [`src/policy`](../perceptual-grade-next-blender/src/policy/)
and are documented in [`POLICY.md`](../perceptual-grade-next-blender/POLICY.md).

This product and `libraries/perceptual-grade-core` retain the earlier
implementation for comparison. Their source, tests, and Buck targets are
independent of the rebuilt product's policy proofs.
