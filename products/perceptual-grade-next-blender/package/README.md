# Perceptual Grade

Perceptual color grading for Blender's Shader Editor and Compositor, with native
Grade nodes, ordered Grade Stacks, image baking, and viewport color scopes.

This is a development build. The Grade/Stack workflow has focused Linux testing,
but readiness, recovery, and full acceptance work remain unfinished.

The Perceptual Grade Handbook is published at
[rei277hz.github.io/perceptual-grade/](https://rei277hz.github.io/perceptual-grade/).
**This is a legacy handbook for Perceptual Grade 1.23.2 and has not been updated
for Perceptual Grade Next.**

## Install

1. Use Blender **5.2 or later**. Current recorded Linux checks use Blender 5.2.2.
2. In Blender, choose **Install from Disk**, select the extension ZIP, and enable
   **Perceptual Grade**. Install the complete archive; keep its folders together.
3. Open a Shader Editor or Compositor with an editable node tree.

This version shares the extension identity `perceptual_grade` with the older
Perceptual Grade implementation. Compare them in separate Blender profiles or
processes; simultaneous enablement is not supported.

## Add a Grade or Grade Stack

In the node editor's **Add → Color** menu, choose **Add Perceptual Grade Next**
or **Add Perceptual Grade Stack Next**. These actions are also available through
**F3** search while the pointer is over the node editor. Some current menu and
panel labels still include “Next”; the labels here match this package.

Connect the new group into your color-processing path, select it, and open the
sidebar with **N**. Under the **Perceptual Grade** tab, the **Perceptual Grade Next**
panel exposes the selected node's controls and preparation status.

Grade uses a native node graph. Grade Stack applies an ordered list of entries;
use **Add Grade**, the arrow buttons, and each entry's enable/direction controls
to edit the stack. Stack first displays a 33³ preview and then prepares its 65³
final evaluator. Wait for preparation to finish before baking. A failed
preparation displays its error and a retry action in the panel.

## Bake an Image

Select a Grade or Grade Stack and invoke **Bake Perceptual Grade Next** from the
node editor's **Add → Color** menu or **F3** search. In the dialog, choose an
existing **Bake Image**, or leave it empty to create one.

Shader baking uses the connected source Image Texture. Choose **Image** for its
image domain, or **UV** with an active mesh and valid UV/material setup.
Compositor baking supports the **Image** domain. Grade baking evaluates the
native Grade graph; Stack baking requires its completed 65³ evaluator. Errors
are reported in Blender when the selected source, output, or preparation is
unavailable.

## Scopes

Keep a **3D Viewport** open in the same Blender window. Select a Grade or Stack
in the node editor and click **Open Scope** in its controls panel. The viewport
shows the scope overlay; its **Perceptual Grade** sidebar provides the scope
controls. Choose histogram, waveform, or vectorscope and use the displayed retry
action if capture fails. Scope acquisition pauses during playback and resumes
with a fresh observation after playback stops.

## Development limits

- Grade/Stack controls are static; animated controls, auto-keying, and per-frame
  grading transforms are not supported in this version.
- Readiness, interrupted preparation, Undo/Redo, and recovery still have known
  gaps. This package is not evidence of complete workflow acceptance.
- Scope source coordination and some concurrent Bake/cleanup cases remain open.
- macOS/Metal and physical HDR-display appearance have separate, incomplete
  acceptance coverage. Extreme tonal-Web GPU cases and graph-size limits also
  retain known findings.

See the [current development status](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/README.md)
and [audit checklist](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-next-blender/CHECKLIST.md)
for the exact supported behavior and remaining work.

## Package contents

The archive installs these entries directly beneath the extension root:

| Entry | Purpose |
| --- | --- |
| `README.md` | This installation and usage guide |
| `blender_manifest.toml` | Blender extension identity, version, and requirements |
| `__init__.py` | Extension registration entrypoint |
| `perceptual_grade_next_blender/` | Blender controls, native grading, baking, and scopes |
| `perceptual_grade_next_core/` | Portable Grade/Stack models and workflow logic |
| `perceptual_grade_nodes/` | Native graph construction and the bundled `output_boundary.npz` asset |
| `color_core/` | Shared color mathematics |
| `LICENSE` | Distribution terms and bundled-asset notice |

The complete extension distribution is offered under **GPL-3.0-or-later**; see
[LICENSE](LICENSE). Original monorepo source is also available under MIT or
Apache-2.0, as described there.

[Source repository](https://github.com/rei277hz/chromaticity) ·
[Report an issue](https://github.com/rei277hz/chromaticity/issues)
