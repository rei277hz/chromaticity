# Stage 3 Color Gizmo design

This brief describes a future Gizmo for Perceptual Grade Next. The legacy
Blender Gizmo is a layout reference. Next's numeric sidebar remains available
for exact entry and native keyframing.

## Board layout

Use one Color page with a **Contributions** / **Opponent a/b** switch. Open on
Contributions by default. Use the legacy board's compact 390-unit default
width as the design baseline. Both views share the editor area and keep the
waveform and vectorscope in a side rail. Lightness Fit, Chroma Fit, and
Global C Gain stay visible below the editor in both views. Adaptance and Warp
retain their separate Stage 3 controls.

```text
Color   [Contributions] [Opponent a/b]

         Shadows  Midtones  White  Highlights    Waveform
Low C     [ # ]    [ # ]    [ # ]     [ # ]      [      ]
High C    [ o ]    [ o ]    [ o ]     [ o ]      Vectorscope
                                                [      ]
Lightness Fit   Chroma Fit   Global C Gain
```

## Contributions

Arrange four tone columns (Shadows, Midtones, White, Highlights) and two
chroma driver rows (Low C and High C). Each cell has one draggable point for
two independent values, giving eight points and sixteen controls. The blue
square marks Low C and the orange circle marks High C. Label both rows. The
drivers weight incoming color smoothly, so both may contribute to a pixel.

```text
             +Chroma (stops)
                   |
                   |      #
  -Lightness ------+-------> +Lightness (J)
                   |
                   |
             -Chroma         J +12.0  C +0.35
```

Right increases lightness (`J`) and up increases chroma gain (`C` in log2
stops). Draw a zero crosshair on every pad. Normalize each axis to the limits
of that cell's existing setting. Use compact endpoint labels and signed value
readouts in native units, with one decimal place for J and two for C. In the
numeric UI, these pairs are `j_low_0` and `c_low_0` for Low C Shadows, and
`j_high_3` and `c_high_3` for High C Highlights, with the same pattern for the
other tones.

The pads show authored values. Keep fitted response curves out of the Gizmo.

## Opponent a/b

Overlay both opponent layers in one square. Use a solid blue guide through
diamond J handles and a dashed orange guide through circular C handles.
Show all four tone points for each layer. Connect the authored points in tone
order using straight segments as visual guides. Give each layer a fixed scale
based on its largest a/b setting limit across the four tones. Each handle
retains the edit limits of its tone. Show signed a and b values in J units or
C stops for the active layer and tone.

```text
Color   [Contributions] [Opponent a/b]

[Shadows] [Midtones] [White] [Highlights]
[J <>] [C o]                 J: a +4.0  b -2.0  Waveform
                  +b                            [      ]
                   |      o                     Vectorscope
      -a ----------+----------> +a              [      ]
                   |  <>
                  -b

Lightness Fit   Chroma Fit   Global C Gain
```

The tone and layer selectors choose a handle when points coincide, including
at the default zero origin. Highlight the selected handle and draw it above
coincident marks. A click or drag on an unambiguous handle selects that tone
and layer. Each gesture edits only that tone's selected a/b pair, using
horizontal movement for `a` and vertical movement for `b`.

## Interaction and settings

- Click a handle to select it. A direct mouse drag moves both axes freely and
  leaves the point selected when released.
- With a handle selected and the Gizmo active, press `G` for a modal move.
  `G`, then `X` constrains horizontal motion and `G`, then `Y` constrains
  vertical motion. These axes map to J and C in Contributions and a and b in
  Opponent a/b. Axis constraints apply only to the keyboard-initiated move.
- Confirm a `G` move with a click or Enter. Escape or right-click restores
  the starting values. A confirmed gesture is one undo step.
- Bind both views to the same authored settings as the sidebar, using the
  existing Grade ownership, gesture, and keyframe paths. The fit and gain
  fields are `lightness_fit`, `chroma_fit`, and `global_gain`.
- Capture the node, settings owner, and active Stack entry at gesture start.
  Changing any of them cancels the gesture, even when both entries reference
  the same Grade. Restore the edited fields on the original owner if it still
  exists. A cancelled gesture adds no keys or undo step.
- With Auto Key enabled on a per-node Grade, key only the fields changed on
  confirmation, at the frame captured when the gesture began.
- Store view, tone, driver, and layer selection as UI state outside grading and
  preparation signatures. Existing Next files open on Contributions with their
  grading and animation data intact. If a future importer reads legacy Gizmo
  focus, it can map saved J or C focus to the matching opponent layer.

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
