# Render methods

An ordinary **Grade** node always applies its Grade forward. Choose **Baked LUT** or **Direct** in the Perceptual Grade sidebar. The node body contains the Grade selector and a pencil for showing or hiding its diagram; it has no Render Method or Direction dropdown. The Perceptual Grade DCTL in Resolve evaluates the equations analytically.

## Choose for the job

For Shading, start with Baked LUT. It reuses precomputed colors when a material is evaluated across samples and light bounces. For Compositing, start with Direct. It evaluates the model in native nodes and avoids a finite 3D color grid across full-frame gradients.

Baked LUT stores Tone and Color at input colors and interpolates between nearby samples. The Linear matrix stays exact, outside the cube. Direct calculates the appearance and color operations using smooth one-dimensional coefficient tables. Compare both on demanding gradients or strong grades before choosing for a final render.

Render Method belongs to the node. Several nodes can share one Grade while using different render methods. Working White belongs to the Grade and appears in Stage 1 of the sidebar.

## While editing

On an ordinary Grade node with Baked LUT selected, edits temporarily use Direct while the matching table is prepared. The completed table takes over when ready. Final rendering waits for the current table; Direct remains Direct throughout.

## Automatic GPU baking

From 1.23.0, nonlinear LUT bakes automatically use Blender's graphics device
when its compute shader passes the startup check. This applies to ordinary
forward Grade LUTs and to forward/inverse Grade Stacks. **Baked LUT** remains
the render method; GPU or CPU describes how its table is prepared.

The sidebar reports **Baking: GPU** with the actual graphics backend/device,
or **Baking: CPU** with a fallback reason. This selection uses Blender's
graphics context, independently of the Cycles CPU/Metal/CUDA preference and
the compositor render device. Matrix-only transforms stay on the CPU because
they need no nonlinear solve. Software graphics devices, unavailable contexts,
failed shader checks and singular inverse matrices also use the CPU.

The shader is compiled from source through Blender's own GPU API. Its first
use can pause while the graphics driver compiles it; later edits reuse the
program. Warm GPU dispatches are bounded, and inverse vertices flagged by the
device are reevaluated through the complete CPU transform before publication.
GPU arithmetic is float32; the CPU uses float64. Their inverse tolerances differ,
so a GPU table is an approximation with its own audit, not a promise of identical
CPU vertices. See [validation and workstation measurement](../development/testing.md#installed-gpu-baking-1230).

GPU work runs in a drawing context. If saving or rendering needs an unfinished
table before that work completes, Blender finishes it on the CPU. An already
installed matching GPU table is reused. No extra GPU package or compiled
extension binary is required.

### GPU startup errors and logs

“Preparing GPU bake” means the job is waiting for GPU startup in a drawing
context. Version 1.23.2 performs the inverse shader's complete Broyden updates
on vector columns: it avoids both the undeclared `outerProduct` builtin and
the matrix/scalar division rejected by the reported Metal compiler.
A compiler or dispatch failure switches to CPU,
shows the exception type/message in the sidebar, and prints one warning and
traceback per graphics context. Failed contexts are retried after disabling
and enabling the extension or restarting Blender.

There is no separate extension log file. On macOS, save the project and quit
Blender, then launch it from Terminal to see and record errors:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --debug-gpu \
  2>&1 | tee "$HOME/Desktop/perceptual-grade-gpu.log"
```

Adjust the application path if Blender is installed elsewhere. Reproduce the
bake; the terminal output is also saved to `perceptual-grade-gpu.log` on the
Desktop. Physical Metal compilation/performance must still be checked on a Mac;
software OpenGL arithmetic tests cannot establish it.

## Grade Stack

A **Grade Stack** uses one LUT, with a 33³ editing preview and 65³ final quality for its entire enabled sequence, including every Linear matrix. Each entry has a forward/inverse toggle. To apply one Grade inversely, use a Stack with one inverse entry.

The Stack first installs a 33³ LUT for fast output and scope updates, then reuses every preview vertex while refining to 65³ after edits settle. Both scopes and native output use the installed LUT. Continuous edits coalesce into successive previews. Final rendering and normal saving require the latest 65³ cube. Before its first preview, the node passes input through and scopes wait. See the Stack guide for scheduling and accuracy details.

See [Inverse grading and Grade Stacks](inverse-stack.md), [evaluation and interpolation](../theory/lut.md), and [measure render methods](../development/testing.md#measure-render-methods).
