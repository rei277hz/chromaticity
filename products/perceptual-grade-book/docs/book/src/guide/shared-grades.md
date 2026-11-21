# Share and animate Grades

A **Grade** datablock stores the authoritative Linear, Tone, and Color settings.
Shader and Compositor Grade nodes can use the same datablock, so an edit made in
one editor updates every reader. A Grade Stack owns its ordered list of entries;
each entry refers to a shared Grade.

## Create and reuse a Grade

A new Grade node has no Grade datablock selected, and its default-value controls
remain disabled. Use the selector to choose an existing Grade or **New Grade**
to create one before editing. Selecting the same datablock shares it with another
node. With a Grade selected, New Grade makes an independent copy when one node
needs different settings. Renaming a Grade changes only its name.

Unlinking a Grade from a node clears that node's association and restores its
default settings; it does not remove the datablock. A Grade Stack entry can be
unlinked or removed while preserving its referenced Grade. Blender's fake-user
setting keeps an otherwise-unused datablock when the file is saved.

## Animate a node-owned Grade

Right-click a Grade node and choose **Convert to Node-Owned Grade**. Next copies
the node's current settings onto the node, independently of its shared Grade.
This mode is useful when a transform should follow Blender's timeline. Numeric
Linear, Tone, and Stage 3 fields can be keyed with Blender's normal keyframe
commands or Auto Key. The discrete Tone Peak choice is static.

The animation belongs to the containing Shader or Compositor node tree's Action.
Reusing a material or group shares that animation across its users. To return to
shared settings, choose **Convert to Datablock-Owned Grade**. Next creates a
Grade datablock from the current frame's values and removes that node's Grade
animation; undo restores the previous node-owned animation.

During forward or reverse playback, a node-owned Grade can display the last
completed Grade from the current playback session while the next frame prepares.
**Updating** means the displayed Grade is still catching up with the playhead.
Stopping playback or scrubbing requests the exact settings at the selected frame.

Node-owned Grade nodes intentionally have no Bake control. Their time-varying
values are evaluated as part of animation and render preflight. Shared Grade
and Grade Stack nodes support Bake; see [Render and bake](render-methods.md).

## Save and render

The extension reconciles kernels after file load and before rendering. During
interaction, a previous complete result can remain visible with an **Updating**
status while a replacement is prepared. Only the current complete result is
render-ready. A current preparation failure is visible as magenta output with
alpha preserved, and render preflight stops the affected frame.
