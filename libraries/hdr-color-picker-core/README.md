# HDR picker numerical core

`color_tools.hdr_color_picker_core` owns the picker coordinate model, controls,
and authoring rules. Its fixed ACES 2 HDR Rec.2020 forward/inverse profile is
shared from `color_tools.color_core.aces2`. It depends on `color-core` and
NumPy. The Blender GPU renderer, display processor and brush adapters are in
`hdr-color-picker-blender`.

`//libraries/hdr-color-picker-core/tests:math` checks the current coordinate
mapping, appearance round trips, D65 center, lightness independence, and
independent ACES transform references. The historical picker vectors in
`tests/fixtures/legacy_rust.json` are archived; they describe the superseded
finite log-radius mapping and are not current coordinate conformance data.
Their old generator has been removed.

## Saturation radius

The current mapping is `u = s / K`, `t = u + A*u^3`,
`r = t / sqrt(1 + t^2)`. The current fit gives `K = 34.09902169100728` and
`A = 0`. The curve is C2-smooth at neutral; finite saturation maps inside the
unit circle, whose edge represents infinite saturation and is rejected by the
decoder. The mapping preserves the D65 neutral center, and its radius is
independent of J′.

`tools/fit_radius.py` and `//libraries/hdr-color-picker-core:radius_fit` are
the current fitting tool and Buck2 target. The fitter uses deterministic RGB
endpoint pairs with 70% Rec.709 SDR, 20% P3 HDR, and 10% Rec.2020 HDR weights,
then scores equal-step CAM16-UCS distances along linear J′/x′/y′ interpolation.
The generated JSON report records the input workload, optimizer settings,
parameters, and held-out scores. No archived fixture-generation command is
part of the current workflow.

Reproduce the fit and audit report with:

```sh
buck2 build //libraries/hdr-color-picker-core:radius_fit
```

The workload samples D65 linear RGB cubes: Rec.709 `[0,1]` for SDR,
Display-P3 `[0,10]` for HDR, and Rec.2020 `[0,10]` for HDR. XYZ is divided by
2.03 in the picker model, and the HDR cap is 1000 nits.
`//libraries/hdr-color-picker-core/tests:radius_fit` checks the generated
report against the runtime mapping.

See [GOAL.md](GOAL.md) for the scope and acceptance criteria and
[CHECKLIST.md](CHECKLIST.md) for the implementation status.
