# Perceptual Grade Gizmo design

The Gizmo shows the Linear controls and vectorscope, plus the Stage 2 Tone
curve, four Tone anchors, Fit, Peak, Before and After waveforms, and the Final
Appearance scope. Original Unified Chroma controls are available in the Stage 2
numeric sidebar while their design is being evaluated.

Stage 3 has no J/C contribution or opponent-pad Gizmo. Its numeric controls are
limited to Warp and selective Adaptance. A future graphical Warp editor remains
out of scope for this product change.

The Tone curve uses the prepared Stage 2 settings. Its waveform applies the
incoming Unified Chroma radial map before calculating H–K magnitude, so the
preview reflects the rendered Stage 2 input. The Gizmo does not expose or edit
Muted/Vivid, Crossover, Shadow/Highlight Chroma, or Black Compression.

## Linear vectorscope

Select a Shader or Compositor Grade and toggle **Vectorscope** in the Linear
sidebar. Each plot shows the selected node's Linear output. Nodes that share a
Grade use its Linear settings and sample their own Color inputs. Cb increases
to the right and Cr increases upward in Rec.709 signal space, with fixed
bounds of -0.65 to +0.65 on both axes. The trace averages the measured
display-encoded RGB, weighted by sample alpha and a one-bin Gaussian. A bin
with share `d` of the total plotted mass has logarithmic density
`L = log1p(65535 * d) / log1p(65535)`. An endpoint-normalized exponential
shoulder sets the intensity to `expm1(-L) / expm1(-1)`, lifting sparse bins and
compressing the upper end of the density range. Each bin adds its measured RGB
to the dark background at that intensity. The graticule has a fixed circle,
six outlined 75% RGB/CMY targets, and a dim 123-degree skin-tone guide.

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

## Tone Final Appearance scope

The read-only 2:1 plot sits above the Before and After waveforms, beside the
Tone curve. It measures the selected Grade's appearance after Warp, H–K
repair, and AP1-D65 boundary mapping, immediately before conversion to RGB.
It uses the same Compositor input or Shader viewport context as the other
Gizmo scopes. The plot is unavailable while **Use Bake** is active because
the Grade is displaying a baked RGB texture.

The bottom 80% of the vertical axis covers \(J_\mathrm{HK}=0\) through 100.
The top 20% spans from the marked break at 100 to the neutral 4,000-nit
reference. The readout above the plot gives the percentage of valid alpha
weight above that reference. The horizontal position is
\(s/\sqrt{1+s^2}\), where \(s=C/|J_A|\). Tick labels show the uncompressed
saturation from zero to infinity. Black has zero saturation.

Opacity shows alpha-weighted density. Each bin's tint follows its weighted
circular mean hue, with tint strength set by how closely its hues agree.
Near-neutral samples contribute their full density weight and less hue weight.
Opposing hues produce a visible gray trace. A complete trace can stay visible
with **Updating appearance** while the selected Grade is recaptured. A failed
capture clears the trace and displays its error.

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
