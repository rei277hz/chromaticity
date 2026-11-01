# Progressive Stack LUT validation — 1.18.0

45 numerical, Blender and native-render fixtures passed through the original
isolated authoring-preview runner, including 42 Stack editing cases. The added
coverage verifies both native 33³ and 65³ samplers, exact shared-vertex reuse,
continuous editing, cancellation, node deletion, scope-cache refresh and
synchronous final-quality preparation. A render fixture's internal label
assertion was updated for the resolution-independent vertex label and rerun.

The [full validation record](progressive-lut-validation.json) lists every fixture.
The [numerical benchmark](progressive-bake-performance.json) includes all Grade
parameters, environment details and nine runs; its [CSV](progressive-bake-performance.csv)
contains individual timings. All refined final tables matched independent full
bakes bit for bit in these measurements. Shared preview vertices are evaluated
only once. Total bake time can rise because inverse solving has two phases;
the change reduces time to the first visible preview.

The handbook includes the nested-grid equations and timing table. No old-project
compatibility or migration path is added. Production code remains Python with
Blender's bundled NumPy. Buck2 itself was unavailable; no release-gate pass or
GPU/desktop certification is claimed.
