# Active scene display transform

The Blender 5.3.0 picker follows the bundled configuration's sRGB, Display P3,
Rec.1886, Rec.2020, Rec.2100-PQ and Rec.2100-HLG devices and the views
available under each. Both Automatic and Off display emulation use the active
scene view, look, exposure and gamma. ACEScg and Linear Rec.709 are supported
working spaces. Custom OCIO configurations, view curves and view white balance
remain outside the picker's display contract.

## 3D Viewport

The slice contains scene-linear ACEScg values. The preview uses OCIO to convert
those values to the selected display. Automatic emulation then converts from
the simulated display to Blender's window encoding. The GPU shader compensates
for Blender's gamma-2.2 overlay merge. Its 8-bit sRGBA attachment bounds the
visible range, including on HDR windows. Brush confirmation uses the scene
value at the selected coordinate. The Rec.2020/P3 authoring gamut control
determines which coordinates are selectable.
[Blender 5.3.0 viewport attachments](https://github.com/blender/blender/blob/v5.3.0/source/blender/gpu/intern/gpu_viewport.cc#L141-L150)

## Native preview

Choose **Open Native Preview** in the HDR Color sidebar. The separate Image
Editor follows the current slice and selection while picking stays in the
painting viewport. Its private float EXR uses **View as Render**, so Blender
applies the display transform and window emulation itself. The preview status
uses the capability of that window. An SDR window can show Blender's SDR
presentation of an HDR view. The temporary image and file are released on
close, save, file load, undo or extension disable.
[Blender Image Editor view selection](https://github.com/blender/blender/blob/v5.3.0/source/blender/draw/intern/draw_color_management.cc#L65-L81)

## Acceptance

The picker-specific Buck2 targets are `tests:display`, `tests:viewport` and
`tests:native_preview` under `//products/hdr-color-picker-blender/`.
Coverage includes native image encoding, GPU readback, comparisons with a
native Image Editor in the same window, brush confirmation and preview
lifecycle. File output and on-screen emulation have different transforms for
PQ and HLG. Software-rendered SDR captures measure the latter only within
the window's range.

For physical HDR acceptance, open the native preview on an HDR-enabled window
and compare it with the same float patches in Blender's Image Editor using
Rec.2100-PQ and Rec.2100-HLG HDR views. Include diffuse white and multiple
highlights above it, and record the display, OS, Blender backend, emulation
mode and window HDR status. Physical brightness and macOS/Metal acceptance
require hardware measurements.
