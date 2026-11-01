# State-machine redesign moved to the new product

The audited [state-machine design](../perceptual-grade-next-blender/STATE_MACHINE_DESIGN.md)
will be implemented in `libraries/perceptual-grade-next-core` and
`products/perceptual-grade-next-blender`.

This product and `libraries/perceptual-grade-core` retain the current implementation
for comparison. Their source, tests and Buck targets are unchanged by the design
handoff. [GOAL.md](../perceptual-grade-next-blender/GOAL.md) and [CHECKLIST.md](../perceptual-grade-next-blender/CHECKLIST.md) track the
new implementation; historical checks do not certify it.
