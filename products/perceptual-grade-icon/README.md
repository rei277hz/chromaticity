# Perceptual Grade icon

This product owns the reproducible direction-A icon pipeline. The authored
inputs are `source/icon_config.json`, `source/modcam16.py`, and the Blender
generator. The generator derives the cusp geometry from the modCAM16 model,
creates the three-shell mesh, writes 16-bit spectral and luminance-derived tone
textures, exports the Blender scene and USD layers, and renders every published
size directly with Blender 5.3.0 CPU Cycles at 256 samples and a fixed seed.

Build the complete package with Buck2:

```sh
buck2 build --remote-only //products/perceptual-grade-icon:icons
```

The `icons` output contains the sixteen native-size PNGs at its root. Its
subtargets also expose the `.blend`, USD layers, mesh data, textures, manifest,
validation report, and provenance hashes. Nothing under this product's source
tree is a generated render or texture.

The generated `.blend` remains editable in Blender 5.3.0. `import_icon.py`
imports the generated USD into a new scene while preserving existing scenes.
The transparent variants use Blender film transparency; opaque variants use
the configured `#141c18` sRGB background.

`modcam16-checks.json` records compact numerical checks for the adapted model.
The build report records the config, model, generator, Blender version, render
settings, and hashes of every derived file so an icon can be traced back to its
inputs without checking in large derived data files.
