# Perceptual Grade Gizmo design

The Gizmo shows the Linear controls and vectorscope, plus the Stage 2 Tone
Curve and Appearance Distribution. The Stage 2 sidebar and Appearance
Distribution both provide Unified Chroma controls.

Stage 3 has no J/C contribution or opponent-pad Gizmo. Its numeric controls are
limited to Warp and selective Adaptance. A future graphical Warp editor remains
out of scope for this product change.

The Tone Curve plots the prepared Stage 2 mapping and its four editable
anchors. Its maximum is the neutral lightness of the selected peak. Input
Lightness and Output Lightness have a one-unit grid, and the SDR/HDR bars split
at Input Lightness = 1. Exposure runs along the bottom edge, Fit along the
right edge, and Peak sits on the title row. The histogram bins alpha-weighted
output lightness after applying Linear and Stage 2 to the captured input.
Selecting a peak, including the current selection, moves Highlights to that
value. White stays fixed, with Highlights clamped to at least 0.001 normalized
lightness above it.

Press **R** during a drag to reset the held control and continue from its
reset value. Highlights resets to the selected peak within the same White
constraint as peak selection. The other Tone anchors reset to their current
output targets within their neighbor bounds. Release confirms the gesture.
Escape or right-click restores its pre-drag value.

Undo and redo preserve the open stage, position, size, and selected Tone
anchor. The scopes refresh for the restored Grade after recovery. Drag an
edge or corner to resize the panel within the Node Editor. Linear opens with
a 300-logical-pixel square vectorscope, and Tone opens at 500 by 340 logical
pixels. Each editor remembers the size of each stage while the Gizmo is open.
The panel consumes pointer events within its bounds. Keyboard shortcuts and
drags that began outside the panel still reach Blender.

## Linear vectorscope

Select a Shader or Compositor Grade and toggle **Vectorscope** in the Linear
sidebar. Each plot shows the selected node's Linear output. Nodes that share a
Grade use its Linear settings and sample their own Color inputs. Cb increases
to the right and Cr increases upward in Rec.709 signal space, with fixed
bounds of -0.65 to +0.65 on both axes. The trace averages the measured
display-encoded RGB, weighted by sample alpha and a one-bin Gaussian. Each
occupied bin's tint is normalized by its largest RGB channel, so the trace
stays visible as exposure drops. A black occupied bin uses neutral gray.
Cb/Cr positions still follow exposure, and empty bins are transparent. A bin
with share `d` of the total plotted mass has logarithmic density
`L = log1p(65535 * d) / log1p(65535)`. An endpoint-normalized exponential
shoulder sets the intensity to `expm1(-L) / expm1(-1)`, lifting sparse bins and
compressing the upper end of the density range. Each bin adds its measured RGB
to the dark background at that intensity. The fixed circle and six outlined
75% RGB/CMY targets are orange at half opacity. The thin 123-degree skin-tone
guide is neutral.

Red and Cyan share the CR direction, and Blue and Yellow share the YB
direction. Drag either color handle to adjust the pair's spread and heading.
Each handle has a vertical balance slider. Dragging it upward increases that
side's balance and lowers the opposite slider by the same amount.

Left-drag anywhere in a current plot to steer its cloud in the pointer
direction. The gesture follows a fixed, alpha-weighted set of representative
pixels and edits only `source_x` and `source_y`. A click or movement below
three UI-scaled pixels leaves the settings untouched. Release confirms one
undo step. With Auto Key enabled, a per-node Grade keys changed coordinates
at the press frame. Escape, right-click, a frame or source change, or switching
the selected node or Grade cancels the drag and restores its original owner.

The Compositor scope samples compatible loaded Image buffers directly and
evaluates processed sources in an isolated copy. The Shader scope samples
visible surfaces through AOVs using the last-used 3D viewport in the same
window. It uses the largest viewport when none has been used. Captures are
bounded to 512 pixels per edge. Larger buffers are averaged by area and
alpha so narrow features contribute to the reduced pixels. Linear edits
recompute the trace from cached RGBA while the capture remains current.
The scope updates when the frame, source pixels, geometry, or viewport
changes. During playback, a complete capture of the same source can remain
visible with **Updating** as newer frames are captured. Capture failures and
unavailable contexts appear in the scope.

## Tone Appearance Distribution

The plot fills the left column and shares the Tone Curve's height. It
measures the selected Grade's appearance after Warp, H–K
repair, and AP1-D65 boundary mapping, immediately before conversion to RGB.
It uses the same Compositor input or Shader viewport context as the other
Gizmo scopes. The plot is unavailable while **Use Bake** is active because
the Grade is displaying a baked RGB texture.

The vertical axis is Lightness with normalized J ticks. The selected peak
neutral is at the top, while \(J_\mathrm{HK}/100=1\) remains at 80% of the
height and uses the regular grid style. The horizontal axis follows the HDR
Color Picker’s saturation compression. The plot position is
\(s/\sqrt{k^2+s^2}\), where \(s=C/|J_A|\) and \(k=34.09902169100728/75\).
The numerator is the fitted `K` from `//libraries/hdr-color-picker-core:radius_fit`.
Ticks display the compressed coordinate. Black is at zero and infinite
saturation is at the right edge, labeled `1`.

Drag the dashed cyan guide or the rhombus at its bottom end to adjust
Saturation Crossover. Its value is the compressed coordinate, with a default
of `0.5` and range of `0–0.99`. Tone correction runs first, then all four
chroma controls operate on the corrected appearance. Muted and Vivid gains use
the compressed saturation coordinate. Drag the dashed orange guide or the
circle at its left end to adjust C Tone Crossover. It specifies normalized
output-neutral lightness where Shadow Chroma and Highlight Chroma reach zero,
with a default of `0.45` and range of `0.1–1.4`. A value of `1` corresponds to
neutral output J of 100. Gain transitions use post-Tone `abs(J_A)`.

Hover the plot body to highlight C Muted Gain left of the Saturation Crossover
or C Vivid Gain to its right. The top and bottom 12% of the plot select
Highlight Chroma above C Tone Crossover and Shadow Chroma below it, with
shorter entry zones when the guide is close to an edge. Crossover guides
take priority. The selected region has a slightly brighter background
beneath the grid and trace. Its readout shows the gain in stops. Drag
horizontally right to increase any of the four gains. One plot-width drag
spans `-4` to `+4` stops. The sidebar provides Highlight Chroma even when the
tone guide is too close to the top for its strip.

Opacity shows alpha-weighted density. Each bin's tint follows its weighted
circular mean hue, with tint strength set by how closely its hues agree.
Near-neutral samples contribute their full density weight and less hue weight.
Opposing hues produce a visible gray trace. During Grade edits from the panel
or Gizmo, **Preview** plots up to 4,096 deterministic samples when the current
input capture and matching Grade parameters are ready.
The generated Grade shader applies Warp, H–K repair, and gamut mapping before
plotting the samples. Reduced captures include coverage-averaged pixels, so
the preview can differ from the native result, especially at edges. The last
complete appearance remains visible while a Grade-only replacement is
prepared. **Updating appearance** appears during source or frame recapture.
The scope requests an exact native capture when the edit settles. Capture
failures show an error.

## Linear scope latency report

Build the Linux x86-64 latency report with

```sh
buck2 build --remote-only //products/perceptual-grade-next-blender/tools/reports:vectorscope_latency_report
```

The output includes `report.json` and `report.md`. It measures cold and warm
captures for direct Images, processed Compositor inputs, and Shader viewport
inputs. It also measures a Linear exposure edit for each route and records
whether that edit reused the sampled pixels. Linear-edit diagnostics include
source epochs, matching invalidation IDs, and capture or render attempts.

The report compares three reducers on the final warm RGBA capture from each
route. The live Gizmo uses NumPy. The GPU experiment maps each sample to a
chroma bin with a compute shader and sums its alpha weight in a float
framebuffer. The Shader Editor experiment renders bin and weight outputs from
a temporary material tree and uses the same float framebuffer to sum them.
The benchmark executable accepts `--reducer cpu`, `--reducer gpu`,
`--reducer shader-tree`, and `--reducer all` (the default).

Capture latency and scalar reducer latency are measured separately. The
report adds them for each comparison and checks the raw weighted bins
against NumPy. It separately checks the live trace's mass and RGB energy
against independent histograms and measures their Gaussian splat.
GPU readback includes synchronization. Shader Editor mapping includes the
temporary scene setup, render, and readback. The remote fixture uses Mesa
llvmpipe, so GPU timings describe software rendering on the worker.
