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
- Store view, tone, driver, and layer selection as UI state outside grading and
  preparation signatures. Existing Next files open on Contributions with their
  grading and animation data intact. If a future importer reads legacy Gizmo
  focus, it can map saved J or C focus to the matching opponent layer.
