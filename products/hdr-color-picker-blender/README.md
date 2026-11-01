# HDR Color Picker

A Blender 5.2 extension for choosing Grease Pencil Draw Color Attribute colors
with the legacy browser modCAM16-HK-UCS model. It can run independently or beside
Perceptual Grade. The extensions share build inputs and have separate installed
packages, native arenas, helpers, caches and registration lifecycles.

Component packages now sit directly beneath the ZIP root. When upgrading from
the old `_vendor` layout, disable the old extension before replacing it, then
restart Blender before enabling the new version.

## Use

1. Install the Buck2-generated `hdr_color_picker.zip` through Blender's **Install
   from Disk** and enable HDR Color Picker.
2. Select a Grease Pencil object, enter Paint mode, select an editable Draw
   brush, and select **Color Attribute**. Unpin the brush's drawing mode/material.
3. Open **3D Viewport → Sidebar → HDR Color**, then enable **Show Color Picker**.
   The persistent two-dimensional picker appears in the viewport's lower left.
4. Set normalized **J′**, choose the Rec.2020 or P3 authoring gamut, and drag the
   x′/y′ slice. Release to apply; cancel the drag to keep the brush unchanged.
   Numeric controls edit the preview; **Apply Brush Color** confirms it.
5. Use White, Black or Brush to restore a preset or inspect the active brush.

Brush assignment converts scene-linear ACEScg into Blender's working space and
preserves values above one. Colors outside the authoring gamut or with negative
components in the destination working space cannot be committed. A brush,
context, color, or view change during interaction invalidates that interaction.
The extension does not replace Blender's native Linear/Perceptual picker.

Like Blender's native brush controls, applying a brush color does not enter
Blender's undo history: Brush datablocks are excluded from memfile undo.
Cancel an active drag to preserve the previous brush color. Normal scene
undo/redo shortcuts remain available while the picker is visible.

## Numerical and display contracts

[`hdr-color-picker-core`](../../libraries/hdr-color-picker-core/) retains the
legacy browser model's modCAM16-HK appearance and ACES transform, with a new
compact saturation radius fitted for linear J′/x′/y′ interpolation. The
Photoshop UXP fork is a different numerical contract. The old Rust picker
vectors in [`legacy_rust.json`](../../libraries/hdr-color-picker-core/tests/fixtures/legacy_rust.json)
are archived historical data; they do not define current radial coordinates.
The current Buck2 fitter and report are documented in the core README.

The GPU compute slice validates against the NumPy implementation before use.
If unavailable, slice calculation runs in the extension's private CPU helper.
Authoring values remain scene-linear; the preview uses the active scene's OCIO
view, look, exposure and gamma. Unsupported display settings suppress the
preview and confirmation. Current validated support is the bundled configuration
with an SDR sRGB display. HDR **color values** are supported; HDR **display
output** is not yet validated. See [DISPLAY.md](DISPLAY.md) for exact coverage.

## Downstream repo

A **downstream repo** is a separate local Git checkout populated with the built
`hdr_color_picker.zip` contents. "Update the downstream repo" means rebuild the
ZIP and refresh that checkout's product files while preserving its Git metadata.
Committing or pushing the downstream repo is a separate step.

Use the `:extension` build command below to produce the ZIP for that checkout.
This product currently has no `:install_workspace` target or default downstream
destination.

## Build and verification

Run from the monorepo root:

```sh
buck2 build //products/hdr-color-picker-blender:extension --show-output
buck2 test //libraries/hdr-color-picker-core/tests:math
buck2 test //products/hdr-color-picker-blender/tests:packaging
buck2 test //products/hdr-color-picker-blender/tests:native
buck2 test //products/hdr-color-picker-blender/tests:viewport
```

Native tests use pinned Blender 5.2.2, install both ZIPs into a disposable
repository and exercise the real Blender GPU, native display conversion, brush
writes, CPU worker dispatch and independent extension lifecycles. Linux uses a
private software GPU display.
macOS/Metal, physical HDR displays and manual painting acceptance remain open.
Framework policies are handwritten Python checked against owner-local `.inv`
requirements by the shared verifier. Packaging requires proofs for the shipped
policies and generated contracts, then checks the final ZIP's exact source
inventory and bytes. Native tests separately cover picker UI behavior and
Blender interactions; the proofs do not establish Blender's native memory
management. See
[ASSURANCE.md](ASSURANCE.md) for the validation boundaries.

Buck downloads pinned dependencies and generates numerical resources without
requiring sibling source repositories. Blender supplies NumPy at installation;
the [component and packaging guide](../../build_defs/README.md) documents shared
dependency and private-package rules.

The documentation and current fitter source are declared Buck2 artifacts:

```sh
buck2 build //products/hdr-color-picker-blender:readme \
  //products/hdr-color-picker-blender:display_contract \
  //products/hdr-color-picker-blender:assurance \
  //libraries/hdr-color-picker-core:radius_fit_source \
  //:architecture --show-output
```

The current saturation-radius fit is reproducible with Buck2:

```sh
buck2 build //libraries/hdr-color-picker-core:radius_fit
```
