# Install and connect

## Blender extension

The [legacy development ZIP](../downloads/perceptual_grade-v1.23.2-20261101.zip)
contains Perceptual Grade 1.23.2, not Next. It remains available for users of
that release. The legacy ZIP is not the Next product described by this manual.
The handbook site does not distribute a Next extension ZIP. When you have a
Next package, install it through Blender's Extensions preferences.

In a Shader or Compositor editor, use **Add → Color → Grade** or **Grade Stack**.
Select a node and open the **Perceptual Grade** sidebar in the editor's N-panel.
The Linear and Tone controls appear for the selected Grade output. Color controls
are divided into J, C, Adaptance, and Warp panels.
Choose an existing Grade in the node's selector, or use **New Grade** to create
one, before editing the shared controls.

## Connect a material in Shading

Connect an **Image Texture** Color output to the Grade Color input. Connect the
Grade output to the material input to adjust, such as Principled BSDF Base Color,
and keep the shader connected to Material Output. For an unlit image preview,
connect the Grade output to an Emission shader instead.

Set the Image Texture's Color Space to match the source encoding so Blender
decodes the image correctly. Use the scene's supported working color space for
the overall node graph; Next supports Linear Rec.709, Linear Rec.2020, and
ACEScg scene spaces.

## Connect an image in Compositing

Enable **Use Nodes** in the Compositor. Connect an Image or Render Layers Image
output to Grade Color, then connect the result to the next operation or output.
Add a Viewer branch to inspect adjustments while editing. Render once before
sampling Render Layers.

For node-owned animation, right-click a Grade node and choose **Convert to
Node-Owned Grade**. This copies its current settings into that node. Shared
Grades and Stack entries retain datablock ownership; see [Share and reuse
Grades](shared-grades.md).
