# Render and bake

Shared Grade and Grade Stack nodes provide a **Bake** operation in Shader and
Compositor trees. Per-node animated Grade nodes intentionally do not provide
Bake, because their settings are time-varying.

## Bake a node result

Select a supported Grade or Stack node, set the output dimensions when the
route allows it, and click **Bake** in the sidebar. The result is published to
a managed packed 32-bit float RGBA Image and the node switches to that reader.
The result is the native evaluated output of the node tree, so Grade uses its
helper-image kernel and Grade Stack uses its full 65³ LUT graph.

**Use Bake** chooses between the Image and live node output without removing the
Image binding. A valid Image remains available when settings, tracked source
data, or the render engine change. The node warns that the bake may be outdated
and shows the reason. Switching back to the engine used for the bake clears the
engine warning when the other inputs still match. Rebaking a shared managed
Image updates every reader.

Settings tracking includes Linear, Tone, and every Stage 3 control on the target,
enabled Stack entries, and live upstream Grade/Stack nodes.

The optional Shader **Vector** input controls baked sampling only. When it is
unlinked, sampling uses the recorded bake UV map, or the active render UV map
for an Image bake.

## Image and UV routes

A pointwise Shader graph with one ordinary still Image and unlinked source
coordinates uses an Image bake: one output pixel per source texel. A constant
Shader graph uses a 1×1 image. Compositor bakes retain the native compositor
output domain, including the scene canvas size for constants.

Linked coordinates, surface-dependent shading, multiple source Images, or an
upstream managed UV bake require a UV bake on a mesh. UV baking uses Cycles and
needs an active, non-overlapping map in the 0–1 tile. Image bakes follow the
Scene render engine: EEVEE uses a private orthographic render, Cycles uses the
selected CPU or GPU device, and Workbench or an unknown engine falls back to
Cycles CPU. UV bakes use the Scene's Cycles CPU/GPU choice. An unavailable GPU
selection fails visibly instead of silently changing devices. The bake helper
does not change Scene or user preferences.

Bake explicitly rejects UDIM/tiled Images, movies and image sequences,
multiview/multilayer sources, Shader to RGB, movie clips and masks, linked or
animated cache/Alembic geometry, missing or overlapping UVs, and unsupported
graph occurrences. Apply unsupported topology-changing or deformation
modifiers before a UV bake. The [Next bake policy](https://rei277hz.github.io/perceptual-grade/technical/en/development/next-policies.html#next-policy.bake)
lists the current route boundaries.

## Render readiness

Next reconciles derived kernels before rendering. Only a full result for the
current settings signature is render-ready. During interaction a previous
complete result may remain visible with **Updating**; a failed current result
shows magenta with alpha preserved and blocks render preflight. Grade Stack
preparation can show its 33³ preview during editing, but final rendering waits
for 65³.
