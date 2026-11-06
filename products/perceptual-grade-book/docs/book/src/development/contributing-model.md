# Code and grading model

Start by locating the behavior in [Architecture and runtime](architecture.md). A model change belongs in the shared equations; an interaction change belongs in the UI and update lifecycle. Keep the change focused enough that its effect can be explained and reviewed.

Treat the analytic DCTL as the reference. Match its equations in the numerical model and native graph. Keep the Direct curve approximation and the paired baker/sampler aligned. Preserve exact-reset paths, signed-value support, finite domain guards and current-parameter signatures. Test the affected numerical, DCTL, parity and native-render targets through Buck2 before broadening coverage.

The [full forward and inverse specification](forward-inverse-math.md) defines every symbol, all three stages, the 3×6 contribution math, the H–K guard, signed/fallback branches, the implemented inverse solver and the scene/Grade/LUT coordinate boundaries. Sections 6.3 and 6.4 give the 1.23.2 stage-3 controls (Concentration, Hue, Adaptance strength) that the DCTL and the Blender release implement; section 6.5 gives the analytic reference's tonal web, selective Adaptance and final scale. Identify which stage a change targets before editing either. This handbook chapter is the maintained specification; there is no separate engineering Markdown copy.

Model equations now have two homes with different scopes. `libraries/perceptual-grade-reference` is the authoritative analytic model; `libraries/perceptual-grade-core` holds the shared kernels and the preserved production law that the DCTL and the 1.23.2 Blender release use. An equation that moves between them is a model change, not a refactor, and needs its own comparison evidence.

For a UI or runtime change, reproduce the original problem with a small saved scene or a focused test. Preserve graph ownership and cleanup, and verify both Shader and Compositor where they share the affected code. A draw callback should display cached state; schedule data changes through the owning operator or timer.

Describe the user-visible result in the relevant guide and record the change in the repository’s RELEASES.md. Include the host version, render method and settings needed to reproduce your check. See [Testing and measurements](testing.md) for selecting useful validation.
