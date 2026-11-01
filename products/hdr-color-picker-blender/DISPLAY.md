# Active scene display transform

The picker computes scene-linear ACEScg values. Its viewport texture uses an
OpenColorIO processor assembled from Blender's current scene settings, rather
than the palette application's fixed browser display transform. The CPU and
GPU paths use the same processor; OpenColorIO generates the shader and LUTs.
Viewport output also compensates for Blender 5.2's gamma-2.2 overlay merge
space and its sRGB framebuffer attachment. Applying only the OCIO transform
would otherwise produce a visibly different final window color.
The merge behavior is defined in Blender's
[`gpu_shader_display_transform_frag.glsl`](https://github.com/blender/blender/blob/d13f752e3b9c/source/blender/imbuf/opencolorio/shaders/gpu_shader_display_transform_frag.glsl#L178),
with the sRGB attachment allocated in
[`gpu_viewport.cc`](https://github.com/blender/blender/blob/d13f752e3b9c/source/blender/gpu/intern/gpu_viewport.cc#L147).

The current fidelity gate supports Blender's bundled OCIO configuration, an
SDR sRGB display device, compatible built-in views and looks, exposure, gamma,
and the ACEScg or Linear Rec.709 working space. View curves, view white balance,
custom OCIO configurations, and other display devices fail closed. The picker
does not silently substitute another display transform for these settings.

`tests/test_display_blender.py` compares the CPU processor against Blender's
independent native `Image.save_render()` path and GPU readback against the CPU
processor. Its cases cover AgX, AgX Punchy, Standard, ACES 2.0, Filmic High
Contrast and Raw, including non-default exposure and gamma. Native-file
comparisons run in both ACEScg and Linear Rec.709 working spaces. The tests also
check unsupported-setting rejection, settings identity and straight alpha.

`tests:viewport` draws through the real `SpaceView3D` `POST_PIXEL` handler and
checks both its region framebuffer and the final native X11 window surface.
It covers those six views in both working spaces. Its window comparison
accounts for Blender's intermediate 8-bit sRGB overlay attachment; this can
quantize very dark colors more coarsely than a single display encoding.

These checks pass on the pinned Linux Blender 5.2.2 with software GPU rendering.
They establish processor parity and actual viewport compositor integration for
those cases. macOS/Metal and physical HDR display behavior remain acceptance
gates; the current sRGB gate does not claim HDR display output support.

Display identities contain values only. A transform owns GPU resources and
does not retain Blender Scene, Brush or other RNA IDs. Disabling or resetting
the extension releases its resources independently of other extensions.
