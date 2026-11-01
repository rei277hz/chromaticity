# Picker Saturation Radius Goal

Give the HDR color picker a future-proof radial coordinate for modCAM16-HK
saturation. Every finite saturation must map inside the unit circle so that the
control remains usable as supported color gamuts grow. The D65 reference white
stays at the center, and the radial coordinate remains independent of lightness.

Fit the radial curve to support even perceived pacing when interpolating
J′/x′/y′. The fitting workload represents achievable linear Rec.709 SDR, P3 HDR,
and Rec.2020 HDR colors rather than unreachable model-coordinate samples.

## Acceptance

- Use `u = s/K`, `t = u + A*u^3`, and `r = t/sqrt(1+t^2)`, with fitted `K > 0`
  and `A >= 0`.
- Keep the radial mapping C2-smooth at the neutral center.
- Map finite saturation to `0 <= r < 1`; reserve `r = 1` for infinite
  saturation and reject it during decoding.
- Preserve the D65 neutral center and keep hue/radius independent of J′.
- Fit the equal-step CAM16-UCS interpolation metric using a reproducible,
  Buck2-pinned workload weighted 70% Rec.709 SDR, 20% P3 HDR, and 10% Rec.2020
  HDR. Cap each HDR RGB channel at 1000 nits.
- Keep the Python picker and Blender GLSL decoder numerically consistent.
- Keep this work documented and tracked within `hdr-color-picker-core`; the
  Perceptual Grade Next [goal](../../products/perceptual-grade-next-blender/GOAL.md)
  and [checklist](../../products/perceptual-grade-next-blender/CHECKLIST.md) are not part of this change.

## Tool status

- Current: `tools/fit_radius.py`, exposed as
  `//libraries/hdr-color-picker-core:radius_fit`.
- Archived: `tests/fixtures/legacy_rust.json`, which records the old finite
  log-radius picker coordinates and source hashes. Its fixture generator has
  been removed; the archived coordinates do not define current behavior.
