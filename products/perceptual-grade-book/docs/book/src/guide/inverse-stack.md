# Inverse grading and Grade Stacks

A **Grade** node always applies its shared Grade forward. For an inverse, add **Perceptual Grade Stack** from the node editor’s Color menu and use an inverse entry. Its node title is **Grade Stack**. Both Add-menu entries use the same color icon as the Grade selector.

## Arrange a Stack

Each entry selects a shared Grade. Enabled entries run **from top to bottom**. For example:

| Entry | Grade | Application |
|---|---|---|
| 1 | Grade.001 | Forward |
| 2 | Grade.002 | Inverse |
| 3 | Grade.003 | Forward |

This first applies Grade.001, then the selected inverse of Grade.002, then Grade.003. Alpha passes through unchanged. Empty and bypassed entries are skipped; a Stack with no enabled Grades is identity.

The list belongs to its node. Duplicating a Stack copies the list independently and retains references to the same shared Grades. Enable/bypass, direction and position belong to an entry; the grading settings and Working White belong to its shared Grade.

The node starts at the same width as Grade. A selector row and a compact control row contain:

| Control | Action |
|---|---|
| Eye | Enable or bypass this entry, preserving its settings and position. |
| \(f^{-1}\) | Toggle inverse application. The symbol stays the same; highlighting means **Inverse**. |
| Pencil | Open this entry’s Grade diagram and activate editing. The active pencil is highlighted. Click it again to close. |
| Up / Down | Move the entry earlier or later. |
| × | Remove the entry while preserving its shared Grade. |

**Add Grade** creates an empty, enabled, forward entry. The Grade selector’s own unlink control clears its Grade reference. Selecting a Stack alone opens no diagram.

## Edit a Grade while viewing the Stack

Click an enabled entry’s pencil. The diagram and sidebar edit that **shared Grade**. Changes propagate to every ordinary node and Stack entry using it. Make an independent Grade copy when an adjustment should belong to a different Grade.

The diagram identifies the edited Grade and its direction. Clicking another pencil switches the editing target. At most one pencil is highlighted in this editor, including the pencils on ordinary Grade nodes. Reordering follows the selected occurrence, even when the same Grade appears several times. Removing, unlinking or bypassing that occurrence ends editing. The pencil is greyed out for bypassed, empty or read-only entries.

An inverse entry keeps the Grade’s stored **forward** slider and handle meanings. Changing its parameters changes the inverse that will be baked. Working White is available in **Stage 1** of the selected Grade’s sidebar; it affects all users of that Grade.

## Read the diagrams

| Stage | Handles and curves | Image scopes |
|---|---|---|
| Linear | Selected Grade’s matrix controls | Complete Stack output vectorscope |
| Tone | Selected Grade’s tone curve; its editable level handles are on the curve | **Stack Input / Stack Output** waveforms and histograms |
| Color | Selected Grade’s contribution curves and controls | Complete Stack output, measured using the selected Grade’s perceptual context |

Both Tone scopes use the same Grade white and reference settings. The Grade curve describes that Grade’s tone operation; it is not a one-dimensional representation of the entire Stack. Waveforms have no local Grade level handles in Stack editing mode.

Stage 3 image histograms, tone selection and neutral statistics describe the **Stack output** in the selected Grade’s coordinates. The driver definitions and editable curves remain those of the selected Grade. The combined LUT does not expose intermediate per-entry images.

The Rec.709 vectorscope keeps its existing signal convention. In Stack mode the Linear vectorscope is for inspection; use the selected Grade’s xy and other Linear handles to edit it. A full-Stack output does not provide the isolated matrix response assumed by ordinary Grade vectorscope dragging.

“Stack Output” means this node’s output, before following nodes and Blender’s view transform.

## Baking and scope updates

Every Stack uses **one LUT at a time: 33³ for interactive preview, then 65³ for the settled result**, including the Linear stage of every enabled entry. The baker evaluates the complete sequence at each final grid vertex using the forward equations and best-effort inverse solver. It does not combine previously baked Grade LUTs.

Changing a referenced Grade, enabled state, direction or order schedules a new preview and final refinement. Renaming a Grade preserves the transform and LUT. A Linear-only edit still rebakes a Stack because its matrix is inside the cube. Different Grade whites are connected with Bradford during the analytic bake. The LUT boundary remains fixed native ACEScg/ACES white; scene-coordinate adapters stay outside it.

**Scopes use the currently installed LUT.** The preview updates both native output and scopes; neither evaluates a separate analytic image preview. Handles and curves update immediately. The status identifies the 33³ preview while 65³ refinement is pending.

The first preview is eligible after 40 ms. During a continuous drag, an in-flight 33³ snapshot finishes and may display slightly earlier settings; subsequent edits coalesce into one request for the latest settings. This prevents continuous mouse movement from starving previews. The 65³ refinement starts only after 300 ms without an edit and after its matching preview is ready. These delays are scheduling thresholds, not bake-time guarantees. The previous installed result remains visible until the next preview is ready.

The grids are nested: the 33-point axis takes every other point of the 65-point axis. All **35,937** preview vertices are copied unchanged into the final grid. Refinement evaluates only the **238,688** other vertices. For a settled snapshot, total analytic work is 274,625 vertices, equal to a single 65³ bake; no coarse interpolation supplies final vertices. The 33³ cube has 32 positive cells per axis, with the same native ACEScg/ACES-white coordinates, 0…128 bounds and plain log1p κ = 0.01 curve. Negative inputs extrapolate the first physical cell.

Before the first preview, the node passes its input through and scopes wait. A completed preview refreshes scopes immediately; final publication refreshes them again. Preview and final images carry distinct cache identities and compact atlas dimensions. Final cubes from obsolete settings cannot publish. Final render preparation and normal saving wait for the **latest 65³** result, even if a preview is already installed. Ordinary Grade nodes keep their existing render-method behavior.

Inverse baking automatically prefers Blender’s compute shader when available,
with a Python/NumPy CPU fallback. Each GPU vertex evaluates the complete sequence;
there are no sampled intermediate Grade tables. Device-flagged inverse vertices
are repaired through the full float64 CPU sequence before installing the table.
The sidebar identifies the selected backend and fallback reason. A matching
published GPU preview retains its common vertices if refinement must switch to
CPU. Foreground save/render completion uses the CPU for pending work because
those handlers have no guaranteed drawing context; a matching finished GPU cube
needs no rebake.

An inverse is best effort: black clipping, singular matrices, signed branches
and strong Color folds can destroy information or admit several preimages.
A singular matrix uses a CPU pseudoinverse. CPU diagnostics report reproduction
error and singular-matrix counts; GPU audits identify its float32 policy, RGB
searches and repaired vertices. A GPU audit does not assert the stricter CPU
residual tolerance for unflagged vertices. Interpolation introduces its own
error between vertices, including for accepted inverse solutions. See
[automatic GPU baking](render-methods.md#automatic-gpu-baking).

## Save and share

Normal saves pack the final LUT and a native evaluation graph. The saved appearance can render with the extension disabled. Editing, automatic rebaking and animated Grade updates require the extension. Shader and Compositor editors support the same shared Grades and Stack behavior.

See [render methods](render-methods.md), [working white](working-white.md), [evaluation and interpolation](../theory/lut.md), and the [forward/inverse specification](../development/forward-inverse-math.md).
