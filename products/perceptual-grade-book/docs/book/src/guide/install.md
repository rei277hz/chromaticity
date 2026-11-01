# Install and connect

## Blender Extension

Download the [development extension ZIP, perceptual_grade-v1.23.2-20261101.zip](../downloads/perceptual_grade-v1.23.2-20261101.zip).
This is the Perceptual Grade 1.23.2 development build dated 2026-11-01, using the
preserved implementation rather than Perceptual Grade Next. It replaces the
original extension download. This chapter describes the legacy 1.23.2 workflow
and has not been updated for the development build.

In Blender, open Preferences, choose Add-ons, then use the menu’s Install from Disk command. Select the ZIP and enable Perceptual Grade. In a Shader or Compositor editor, choose Add → Color → Perceptual Grade. Select the node to open its Perceptual Grade sidebar.

![Blender extension installation](../assets/screenshots/blender-install.png)

<p class="figure-caption">Install from Disk and the enabled Perceptual Grade extension.</p>

### Connect a material in Shading

Connect Image Texture’s Color output to Perceptual Grade’s Color input. Connect the graded Color to the material input you want to grade, such as Principled BSDF’s Base Color; keep the shader connected to Material Output. For an unlit image preview, connect the graded color to an Emission shader instead.

![Shader node connections](../assets/screenshots/blender-shading.png)

<p class="figure-caption">Image Texture → Perceptual Grade → shader → Material Output. Show the node sockets and image together.</p>

### Connect an image in Compositing

Enable Use Nodes in the Compositor. Connect Image or Render Layers’ Image output to Perceptual Grade’s Color input, then send the graded Color to the next compositing operation or the output. Add a Viewer connection to inspect the result while dragging the controls. Render once before sampling Render Layers.

![Compositor node connections](../assets/screenshots/blender-compositing.png)

<p class="figure-caption">Image or Render Layers → Perceptual Grade → output, with a Viewer branch.</p>

Set each source image’s Color Space to its actual encoding so Blender decodes it correctly. Leave Color Reference unconnected for now; the [ColorChecker example](linear.md#example-match-a-photographed-colorchecker) introduces it.

## DaVinci Resolve DCTL

Download the [English DCTL](../downloads/Perceptual-Grade.dctl) or [Simplified Chinese DCTL](../downloads/Perceptual-Grade-zh-HANS.dctl). In Project Settings → Color Management → Lookup Tables, choose Open LUT Folder. Copy the file there and choose Update Lists. On the Color page, add the DCTL Resolve FX effect to a serial node and select Perceptual-Grade.

![Resolve DCTL installation](../assets/screenshots/resolve-install.png)

<p class="figure-caption">the installed file, Update Lists, and the DCTL effect's file selector.</p>

### Place explicit CSTs around the DCTL

Use an unmanaged DaVinci YRGB project. Add three serial nodes:

The first node is an input Color Space Transform. Set Input Color Space and Input Gamma to match the footage, Output Color Space to CIE XYZ, and Output Gamma to Linear.

Place Perceptual Grade on the second node. It receives and returns linear XYZ; set Destination White to the white represented by that signal.

The third node is an output Color Space Transform. Set Input Color Space to CIE XYZ and Input Gamma to Linear, then choose the output space and gamma for your monitoring or delivery transform.

For a D65 chain—such as Rec.709 SDR or Rec.2020 PQ footage converted to XYZ—use Destination White = D65. Keep D65 consistent through the return CST. For an ACES-white XYZ chain, use Destination White = ACES. For an explicitly daylight D60 chain, choose D60 daylight; it has different coordinates from ACES white. XYZ itself does not specify a white point: match the conversion you actually used, not the name of the camera or the image’s tint. Source White is the grading control for removing that tint.

For the illustrated D65 chain, turn off Use White Point Adaptation in both CSTs so the conversions retain that white. If you deliberately adapt to another white, set Destination White to the adapted signal’s white instead. A D65 neutral in XYZ has \(X/Y\approx0.9505\) and \(Z/Y\approx1.089\); use a neutral patch to check the conversion before grading.

![Resolve CST and white settings](../assets/screenshots/resolve-cst.png)

<p class="figure-caption">input CST, DCTL Destination White, and output CST, with the three-node chain visible.</p>

Keep automatic tone mapping, gamut mapping, Apply Forward OOTF and Apply Inverse OOTF disabled in the conversion CSTs when setting up the grade. Use a deliberate downstream display transform for HDR-to-SDR monitoring. Check the linear signal’s scale: the DCTL treats \(Y=1\) as Reference Nits. A conversion normalized to a different luminance needs an explicit scale adjustment before the DCTL and the inverse adjustment afterward.

The demonstrations use the Perceptual Grade extension’s gizmos in Blender. Resolve users reproduce each operation with the concrete DCTL slider names listed beside it.

The Grade selector starts empty. Your first grading edit creates a reusable Grade; see [Share and reuse Grades](shared-grades.md) for linking nodes and making independent copies.
