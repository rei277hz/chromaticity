# Testing Perceptual Grade

Choose checks that exercise the contract changed. The analytic reference,
Resolve DCTLs, and Blender runtime have separate test layers. A passing unit or
proof target establishes only its declared boundary; host execution and
publication need their own acceptance checks.

Run targets through Buck2 with remote execution from the monorepo root.

## Analytic reference

Reference tests cover appearance coordinates, Tone, Color, Warp, H–K repair,
and inverse behavior. Useful focused targets include:

```sh
buck2 test --remote-only \
  //libraries/perceptual-grade-reference/tests:grading \
  //libraries/perceptual-grade-reference/tests:unified_chroma \
  //libraries/perceptual-grade-reference/tests:guarded_warp \
  //libraries/perceptual-grade-reference/tests:hk_guard \
  //libraries/perceptual-grade-reference/tests:inverse
buck2 test --remote-only //libraries/perceptual-grade-reference/proofs:color_model
```

Use the proof bundle when changing a stated mathematical invariant. Numerical
round trips and proof obligations answer different questions, so run both
when the change affects uniqueness, bounds, or continuity claims.

## Resolve DCTL

The DCTL interface suite checks generated control declarations and host slider
constraints. The numerical suite compares generated float32 entry points with
independent reference calculations. Portability checks compile the generated
sources in supported C++ and OpenCL modes.

```sh
buck2 test --remote-only \
  //products/perceptual-grade-dctl/tests:interface \
  //products/perceptual-grade-dctl/tests:numerical \
  //products/perceptual-grade-dctl/tests:portability
```

These checks do not replace loading the generated DCTLs in Resolve. For a
host-level change, inspect both locales, reset behavior, affected controls,
direction, HDR and signed values, and the final XYZ Output boundary.

## Blender extension

Blender checks are organized by behavior in
`products/perceptual-grade-next-blender/tests/BUCK`. Numerical tests cover
prepared settings and color resolution. Policy and runtime tests cover event
transitions, publication, lifecycle, capture freshness, and rollback. Native
tests inspect generated node templates and evaluated graphs. Installed tests
exercise the packaged extension in Blender, including Shader and Compositor
paths where applicable.

Examples of focused target groups include:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:color_resolution \
  //products/perceptual-grade-next-blender/tests:policy_bank_publication \
  //products/perceptual-grade-next-blender/tests:preparation_runtime \
  //products/perceptual-grade-next-blender/tests:node_templates
buck2 test --remote-only \
  //products/perceptual-grade-next-blender/tests:technical_report_audit \
  //products/perceptual-grade-next-blender/tests:handbook_audit
```

Installed tests establish behavior for the Blender versions and execution
profiles they name. They do not imply compatibility with every Blender build,
render device, or color-management configuration. Record the tested host,
working space, render method, precision, and device for a host-specific result.

## Books and publication

The report audit checks chapter coverage, evidence paths, policy anchors, and
source comments. The handbook audit checks the built site and print exports
against the manual's supported scope. Book tests cover assembly, local links,
generated media, archive contents, and publication safety.

Build the site and print outputs with the targets in the
[book product README](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-book/README.md).
Use the report and handbook audit targets after changing a chapter, anchor,
generated asset, or publication contract. Publish only after reviewing the
built site and the outputs relevant to the change.
