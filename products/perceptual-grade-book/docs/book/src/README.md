# Perceptual Grade for Blender

Perceptual Grade is a three-stage color transform for Blender's Shader and
Compositor node editors. Perceptual Grade provides **Linear**,
**Tone**, and **Color** controls, shared Grades, animated node-owned Grades,
Grade Stacks, and managed image baking. The [Technical Report](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
describes the model and product implementations.

<div class="download-grid">
<a class="download primary" href="downloads/archived-blender-extension.zip"><strong>Archived Blender extension</strong><span>Prebuilt archive</span></a>
</div>

This archived ZIP is the book's sole extension download. Its interface differs
from the current workflows described here.

Begin with [installation and node connections](guide/install.md), then follow
the [three-stage workflow](guide/workflow.md). Set white balance and exposure
in **Linear**, set the tone landmarks in **Tone**, and shape lightness, chroma,
Adaptance, and the six-handle Warp web in **Color**. Shared Grades can be reused
across nodes; convert a Grade node to node-owned settings when it needs its own
animation. A Grade Stack combines ordered forward entries in one sampled
transform.

The manual covers the Shader and Compositor nodes. The [reference chapters](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
explain the mathematics, while the [Blender runtime policy chapter](https://rei277hz.github.io/perceptual-grade/technical/en/development/policies.html)
documents runtime publication, failure handling, and bake behavior.

See [credits](reference/credits.md) for model and implementation references,
and [license](reference/license.md) for licensing.
