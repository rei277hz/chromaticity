# Perceptual Grade for Blender

Perceptual Grade is a three-stage color transform for Blender's Shader and
Compositor node editors. The current Next implementation provides **Linear**,
**Tone**, and **Color** controls, shared Grades, animated node-owned Grades,
Grade Stacks, and managed image baking. The [Technical Report](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
describes the model and current implementation contracts.

<div class="download-grid">
<a class="download primary" href="downloads/perceptual_grade-v1.23.2-20261101.zip"><strong>Legacy Blender download</strong><span>Perceptual Grade 1.23.2 · 2026-11-01 · not Next</span></a>
</div>

The ZIP above is retained for users of the preserved 1.23.2 extension. It does
not contain Perceptual Grade Next. This handbook does not yet distribute a Next
extension ZIP.

Begin with [installation and node connections](guide/install.md), then follow
the [three-stage workflow](guide/workflow.md). Set white balance and exposure
in **Linear**, set the tone landmarks in **Tone**, and shape lightness, chroma,
Adaptance, and the six-handle Warp web in **Color**. Shared Grades can be reused
across nodes; convert a Grade node to node-owned settings when it needs its own
animation. A Grade Stack combines ordered forward entries in one sampled
transform.

The manual covers the Shader and Compositor nodes. The [reference chapters](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
explain the mathematics, while the [Next policy chapter](https://rei277hz.github.io/perceptual-grade/technical/en/development/next-policies.html)
documents runtime publication, failure handling, and bake behavior.

See [credits](reference/credits.md) for model and implementation references,
and [license](reference/license.md) for licensing.
