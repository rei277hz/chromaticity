# Share and reuse Grades

A Grade stores the Stage 1 matrix, Working White, Tone and Color settings used by the extension. Select the same Grade on several nodes to adjust them together, including Shader and Compositor users and Grade Stack entries.

The displayed node titles are **Grade** and **Grade Stack**. The extension, sidebar and Add-menu product names remain Perceptual Grade.

## Start with an empty selector

A new Grade node has an empty selector and default settings. The first change to a handle, numeric grading value or Working White creates a Grade automatically. Names start at **Grade.001**, then Grade.002, and so on.

Opening or closing the diagram, reading scopes, choosing a handle, switching pages or changing Render Method does not create a Grade. Cancelling the first handle drag returns the node to its empty state.

The selector appears on the node and at the top of its Perceptual Grade sidebar. Choose an existing Grade to apply its settings immediately. Later edits affect every user of that Grade.

The node’s **pencil** opens its diagram without using the sidebar. Clicking the pencil on another Grade selects that node and shows its diagram; clicking the highlighted pencil hides it. Highlighting follows the actual diagram in that editor, including the sidebar’s Show/Hide Diagram control and the diagram’s close button. The pencil uses the same symbol as a Grade Stack entry. **At most one pencil is highlighted in each Shader or Compositor editor**, across all Grade nodes and Stack entries, even when they share the same Grade. Switching the target clears the previous highlight. Showing a diagram does not create or duplicate Grade data.

Ordinary Grade nodes always apply the Grade forward. Render Method appears in the sidebar. Working White appears only in the Stage 1 controls and belongs to the shared Grade. To use an inverse, add a Grade Stack entry and enable its inverse toggle.

## Make a variation

Use **New Grade** while a Grade is selected to make an independent copy. The copy starts with the selected Grade’s values and receives a unique name. Further adjustments affect users of the copy.

For example, select *Warm scene* on two materials and on a compositor node. Editing exposure from any of those nodes updates all three. To make one material darker independently, create a new Grade on its node, rename the copy *Warm scene – darker*, and adjust its exposure.

Ordinary duplication of a node or material keeps the Grade shared. Use New Grade when the duplicated node should diverge. A Stack’s pencil also edits its shared Grade; creating a Stack does not make its referenced Grades independent.

## Rename, unlink and retain

Edit the name in the selector to rename a Grade. Every user shows its new name.

The selector’s **×** unlinks the Grade from an ordinary node and restores that node’s default grading values. Render Method stays selected on that node. In a Stack, the selector’s unlink control clears the entry’s Grade reference; the entry-removal × removes the whole entry. Shared Grade data is retained.

New Grades have Blender’s fake user enabled so an unused Grade remains available after saving and reopening. Turn off the shield/fake-user control when an unused Grade should follow Blender’s normal orphan-data cleanup rules.

## Shared values and local choices

| Stored in the shared Grade | Stored on the node, entry or editor |
|---|---|
| Stage 1 matrix and its recorded white; selected Working White | Ordinary Grade node’s Baked LUT / Direct method |
| Tone landmarks, Remap Fit, Reference Nits and Peak Nits | Stack entry’s enabled state, forward/inverse choice and position |
| Color contributions, Adaptance, hue and concentration | Connections, selected handles, diagram placement and active editing entry |
| Animation of shared grading parameters | Node name, label, width and layout |

Keyframing a grading parameter animates the Grade for all its users. Linear auto-keying records the nine matrix coefficients; its controls are derived readouts. Interpolation follows matrix coefficients. Changing Working White retains the recorded matrix-animation basis and applies the white conversion to every evaluated frame. Making an independent copy also copies its active animation Action independently.

## Saving and rendering

Normal saves store native Shader and Compositor group representations with current evaluated settings. The selector returns when the extension is enabled. These graphs can render their saved appearance without the extension. Live editing, animated updates and adapting saved graphs to a changed working space require it. Recovery files or autosaves that capture custom nodes should be opened with the extension enabled.

Working White defaults to **D65** in every scene space. See [working white](working-white.md), [render methods](render-methods.md), and [editing Grades inside a Stack](inverse-stack.md#edit-a-grade-while-viewing-the-stack).
