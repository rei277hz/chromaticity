# Color core

`color_tools.color_core` contains reusable, host-independent color mathematics:
linear RGB/XYZ algebra and CAT16 white adaptation (`linear`), the fixed ACES 2 HDR
Rec.2020 profile (`aces2`), Grade's signed offset-free modCAM16/HK model
(`modcam16`), and extended-range arithmetic (`scaled`). The ACES profile keeps
its lookup tables in a private module. Importing `color_core.linear` does not
load NumPy-backed appearance math or ACES tables.

The only dependencies are the Python standard library and NumPy. Color-core
never imports Grade, picker, reference, Invariant or native packages; `aces2`,
`modcam16` and `scaled` load only on demand.

The Grade modCAM16 module is specifically the signed, offset-free Grade
variant; it is distinct from the picker and reference appearance equations.
Color-core does not own Grade controls, white admissibility/projection,
pipelines or UI behavior, nor picker coordinate controls, viewing presets or
interaction rules.

Consumers use these kernels through direct Buck dependencies. The preserved
Grade and HDR Color Picker Blender extensions each package the complete source
privately, including its model tables and equations, so installed products do
not share module state. See the [component packaging guide](../../build_defs/README.md).
