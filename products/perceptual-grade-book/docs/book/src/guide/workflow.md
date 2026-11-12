# Grade in three stages

> **Preserved release:** this usage chapter and its captures describe 1.23.2 and still lag the latest model. See [Understanding the model](../theory/structure.md) for the current reference; these controls do not describe Next’s future Warp implementation.

Follow two images through the same sequence. Example A is SDR; Example B is HDR. They stay on the left and right throughout the book. Each pair demonstrates the same control with a different grading intention.

Start by neutralizing the light and balancing exposure in both images. Refine the SDR image’s muted color relationships while preserving the HDR image’s separation between diffuse surfaces and bright highlights. In Tone, build an S-shaped contrast curve for A and use a gamma-like curve to open darker areas in B. Carry those choices into Color, where the same controls refine each image’s own tonal distribution.

Every demonstration starts with the previous demonstration’s result. Keep the same images, crop, view transform and exposure settings across the sequence; carry the completed Linear and Tone adjustments into all six Color operations. The side-by-side animations compare two examples, not a before/after split.

In [Linear](linear.md), make what should look white actually white, then check exposure and color relationships against the chart. In [Tone](tone.md), shape contrast and open the shadows, then compare the SDR and HDR waveforms. In [Color](color.md), shape lightness, chroma, Adaptance and hue within selected tonal regions.

The square recordings show each image beside the Perceptual Grade extension’s gizmo in Blender. They loop at their recorded speed; if one adjustment finishes earlier, its final frame waits for the other. Each pair repeats automatically after a short final-frame hold.

These are screen recordings of SDR and HDR source images, both encoded for the web as sRGB. The HDR example demonstrates grading and scope behavior; this web page does not reproduce an HDR display’s peak luminance.

Panels labelled Dummy recording still use the bundled temporary clip. The accompanying lesson describes the intended operation; the label disappears automatically when its source recording is replaced.
