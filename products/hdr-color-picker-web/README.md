# HDR Color Picker for the web

The HDR Color Picker tool is published at
[rei277hz.github.io/color-picker/](https://rei277hz.github.io/color-picker/).

This repository contains a local browser picker for normalized
modCAM16-HK coordinates:

```text
(J', x', y') ∈ [0, 1]^3
```

The `x'` and `y'` channels are Cartesian coordinates around `0.5`; they encode
the shader's logarithmic saturation radius using
`(x, y) = (-R(s) sin(h), R(s) cos(h))`, where
`s = 5.977038579617132 * expm1(3.557365336640551 * R)`.
The constants contain the Rec.2020 pure-blue endpoint
`s_max = 203.64174424420062` at `R = 1`; the valid domain is their unit disk.
The square viewport has four aligned layers: a checkerboard canvas, a
selected-view RGBA PNG gamut slice, a transparent 1024x1024 ColorChecker-dot
PNG, and a transparent overlay canvas containing rings, the neutral cross, and
the picked marker. WebGPU computes
only the slice pixel field when available; a WASM batch path provides the
deterministic fallback. Both canvases always use 512x512 backing stores. A
confirmed WebGPU renderer keeps the slice PNG at 512x512; only the CPU/WASM
fallback may use a temporary 64x64 slice during J' interaction. Coordinates
always determine Rec.2020 authoring display-linear RGB where `(1, 1, 1)` is the
203-nit reference white. That value enters the inverse **ACES 2.0 HDR
1000 nits (Rec.2020)** view directly to produce scene-linear ACEScg. The
selected forward view supplies the slice's internal display-linear pixels; HDR
PQ PNG encoding applies the viewer-convention 2.03 upscale at the final encoder
boundary. A view change does not change coordinates, ACEScg, Background, or
snapping.

ColorChecker dots use the official post-November-2014 X-Rite ColorChecker24
Lab/D50 reference. The complete 24-patch source file and provenance metadata
are checked in under [`libraries/modcam16-color-core/references/colorchecker/`](../../libraries/modcam16-color-core/references/colorchecker/); the UI retains its established
18 chromatic patches. Each patch is converted through direct CAT02
D50→ACES-white adaptation into ACEScg. No RICD flare/scale, inverse ACES view
transform, or HDR placement gain is applied to ColorChecker patches.

DNG development keeps the camera-profile boundary explicit. A valid
`ForwardMatrix` supplies the profile-defined camera→XYZ-D50 transform after
white-balance and calibration factors; no generic CAT replaces that matrix.
When `ForwardMatrix` is absent or unusable, the ColorMatrix path uses linear
Bradford from the selected camera white to D50. Both paths then use the common
CAT02 D50→D65 boundary before the prepared raster enters the application.
Embedded ICC XYZ-PCS/D50 values use Bradford for their D50→D65 conversion.

The Rec.2020 authoring mode defaults to `Rec.2020 (P3-D65 Limited)`, which adds a P3
`[0, 10 / 2.03]` per-channel cube requirement to Rec.2020-authored picker/slice
availability. Clicking the in-slice mode switch changes it to full `Rec.2020`,
and clicking again returns to the limited mode. The selected ACES 2.0 view transform is solely responsible for
adapting the canonical Rec.2020-authored scene value to the chosen output gamut
and dynamic range.

Click the preview to select SDR Rec.709, SDR P3-D65, HDR P3-D65, or HDR
Rec.2020. The whole swatch/surround is one locally generated 256×256 PNG:
8-bit with the matching ICC profile for SDR; 16-bit PQ with P3/Rec.2020 cICP
metadata for HDR. All four views are selectable, independently of display
capabilities. Actual HDR appearance depends on the browser, OS, and display.
There is no separate Mode row or direct Rec.709 mode.

The appearance context uses a 203-nit diffuse white. J' maps linearly as
`J_HK = J' * 217.2768649129496`, ending at physical 1000-nit white. The fixed
203-nit locator is `J' = 0.4602422813863053`; Rec.2020 authoring `(1,1,1)` is
that 203-nit neutral. The fitted-radius X/Y channels use the orientation and
meaning defined above.

Image Options contains `Image reference white is encoded as linear 2.03`.
Checked means the decoded display-linear source stores the 203-nit reference
white as `2.03`; the image path divides by 2.03 before the inverse view
transform. Unchecked means decoded display-linear `1.0` already represents the
203-nit reference white. The dynamic helper below the checkbox states the
active behavior exactly.

Background is a normalized surround J' value in `0..1`, shown beside the
label and routed through the same inverse/forward pipeline. The default is
`0.150`; `1.000` is the 1000-nit neutral. Over-peak foreground picks are
marked unavailable.

See [FINAL_BEHAVIOR.md](./FINAL_BEHAVIOR.md) for the current behavior contract
and [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) for live
implementation and release checks.

## Monorepo build and verification

Run from the monorepo root:

```sh
buck2 build //:hdr_color_picker_web --show-output
```

The default output is `hdr-color-picker-web.zip`. Extract it into a static
HTTP(S) server's document root or a subdirectory. `index.html` is at archive
root and all application assets use relative URLs. Serve JavaScript, CSS, and
Wasm with their standard MIME types. HTTPS or localhost enables browser
features such as WebGPU and clipboard access; the deterministic Wasm fallback
supports environments without WebGPU. No application backend is required.

The product owns the TypeScript UI, workers, Vite configuration, behavior
contract, and browser acceptance. Reusable Rust code lives in
[`modcam16-color-core`](../../libraries/modcam16-color-core/) and
[`modcam16-decomposition`](../../libraries/modcam16-decomposition/). Their crate
names and exported Wasm APIs are preserved. Buck stages the generated packages
at `src/wasm/pkg/` and `src/wasm/decomposition_pkg/` inside its build tree; those
paths are generated inputs, not checked-in copies of the libraries.

Rust dependency versions and features are centralized in
[`third_party/rust`](../../third_party/rust/README.md), whose pinned Reindeer
generator produces the external crate targets. The libraries declare their
first-party relationships and direct dependencies in Buck. Buck compiles each
crate with declared Rust toolchains and links the Wasm modules before running
the centrally built wasm-bindgen executable.

[`third_party/web`](../../third_party/web/README.md) owns npm archives, Node,
browser tooling, and the Python OCIO oracle distribution. The product build
checks TypeScript, runs Vite, and packages the complete static asset tree with
npm and Rust dependency notices and reference provenance. The original source
checkout, preinstalled `node_modules`, and developer Rust caches are not build
inputs.

Compilation runs offline after Buck downloads the declared archives. Complete
tool distributions and dependency trees cross the NativeLink boundary through
CAS. [`tools/rust-build/`](../../tools/rust-build/) owns Rust distribution,
Wasm binding and notice helpers; [`tools/web-build/`](../../tools/web-build/)
owns offline npm assembly and deterministic site packaging.

Run the product, library, archive and dependency-manifest tests from the monorepo
root:

```sh
buck2 test \
  //products/hdr-color-picker-web:math \
  //products/hdr-color-picker-web:png \
  //products/hdr-color-picker-web:ocio \
  //products/hdr-color-picker-web:browser \
  //products/hdr-color-picker-web:acceptance \
  //libraries/modcam16-color-core:test \
  //libraries/modcam16-decomposition:test \
  //tools/web-build/tests:archive \
  //third_party/web:manifest_consistency
```

The product's Buck tests retain the source-based UI, PNG/ICC and independent
PyOpenColorIO ACES validation. Production archive acceptance checks extracted
root and subdirectory hosting, image workers, and the Wasm fallback. Native
and browser checks do not establish physical HDR-display appearance or GPU
parity on untested hardware.

## Publish to the local website checkout

The **downstream repo** is the local Git checkout that receives this product's
built output, by default `~/workspace/rei277hz.github.io/`. The **downstream site**
is its generated `color-picker/` directory. Requests to "update the downstream
repo" or "update the downstream site" mean running this command from the
monorepo root:

```sh
buck2 run //products/hdr-color-picker-web:publish
```

This builds `hdr-color-picker-web.zip` through NativeLink, then runs the publisher
locally. The publisher validates the completed ZIP against its build manifest,
removes **every file and directory** under
`~/workspace/rei277hz.github.io/color-picker/`, and extracts the ZIP's contents
there. It creates `color-picker/` if absent and preserves the parent checkout's
`.git` and other site directories.

To use another checkout, append `-- --destination /path/to/website/site-directory`.
The destination must be a direct child of an existing Git worktree and must not
contain its own `.git`. Committing and pushing the website are separate steps.
NativeLink stays enabled throughout.

```sh
buck2 test //products/hdr-color-picker-web:publish_test
```

## Reindeer migration validation recorded on 2026-11-01

The single-command build produced `hdr-color-picker-web.zip` (3,018,533 bytes),
SHA256 `6feb7cbcfcfbbea754d63a10df9206080347940f916a277b364345094a4e084a`.
Its nine members include both Wasm modules and dependency notices derived from
the application's Rust source closure. Build-only mdBook dependencies are not
included in those notices.

All nine web-related Buck test targets passed remotely: 83 native color-core
tests, 20 native decomposition tests, 23 math tests, 12 PNG/ICC tests, the OCIO
oracle, 21 browser tests, production archive acceptance, and the archive and
dependency-manifest checks. The personal DNG fixture test remains ignored.
Production acceptance passed root and nested hosting and the mobile layout.
The five product test targets recorded 11 remote build actions and five remote
test executions, with no local actions.

A separate source checkout containing no build outputs or Rust caches reproduced
both the web and handbook ZIPs byte for byte. Across the combined product and
native-test build, all 855 Rust compilation actions and 101 build-script actions
were remote-cache hits. The build recorded 2,684 cached actions, one remote Python
distribution extraction, and no local actions.

## Initial import validation recorded on 2026-11-01

These results describe the import before the Reindeer dependency migration.

The single-command build produced `hdr-color-picker-web.zip` (3,030,766 bytes),
SHA256 `a2729bc83a2f08963fb1ef95b386ae0418f256f6b530d0b831ad3b5bb6290967`.
All nine web-related Buck test targets passed remotely: 83 native color-core
tests, 20 native decomposition tests, 23 math tests, 12 PNG/ICC tests, the OCIO
oracle, 21 browser tests, production archive acceptance, and the archive and
dependency-manifest checks. One existing native DNG fixture test remains
ignored because its personal full-resolution inputs are not provided.

Production acceptance served the extracted ZIP at `/` and `/nested/`, loaded
both Wasm modules and all image workers with WebGPU disabled, and checked the
360×645 DPR-3 layout. A separate fresh checkout reused the remote cache for all
eight dependency/compilation/bundle actions and reproduced the exact ZIP hash.
NativeLink infrastructure validation passed 16 local probes, 16 remote probes,
and 16 remote-cache hits on worker image
`sha256:2c0180f95923d81012e70ad19f0cde306eb0708e3b3b1e259b50bf69956c3cc7`.

The broader existing `//tools/architecture/tests:components` gate reports ten
assertion failures in untouched Next Python bundles: absolute fallback imports
in `_shared.py` and `project_readiness.py`, and the missing Next `model/cube.py`
module imported by `model/grading.py`. That gate does not consume the new web
or Rust components. These failures are separate from the passing web targets;
the full repository suite is not claimed green.

## Imported source and exclusions

[ORIGIN.md](ORIGIN.md) records the current-working-tree import. Photoshop/UXP,
Substance Painter, CCX files, and Adobe host diagnostics are excluded. The
explicit Adobe RGB source-gamut option and conversion path are removed;
unsupported requests receive an error. Generic embedded ICC profiles and DNG
camera profiles retain their existing image-processing behavior. The official
OCIO test configuration remains upstream reference data and is not shipped as
an Adobe integration.

The original web and Rust source follows the monorepo's `MIT OR Apache-2.0`
licensing; see [ORIGIN.md](ORIGIN.md). Preserve library dependency notices and
the ColorChecker reference's provenance metadata when distributing build outputs.

## Interaction

Snapped coordinates drive the picker marker, its accessible x'/y' values, and
the values sent to evaluation. The unsnapped pointer coordinates are kept
internally only so a gesture can escape a snap. The nearest ColorChecker dot
or neutral cross is selected within a `0.020` halo; projection onto that
target uses a `0.005` whole-vector band. J' snapping uses the same `0.005`
band and chooses the nearest active ColorChecker patch or the fixed 203-nit
reference locator, with patches winning exact ties.

For mouse input at any viewport width, click the Color trackpad once to arm live
tracking. The selected point follows the cursor, clamps to the slice edge
outside the square, and a second primary click anywhere commits the point.
Press Escape to cancel. Touch and pen input swipe directly on the slice using
relative movement; contact does not jump the point, and the established
quarter-speed sensitivity, smoothed velocity, acceleration, snapping, and
pointer capture are retained. The J′ trackwheel is a persistent, flat control whose
texture follows raw vertical movement one pixel per pixel. Its J' value uses
the same smoothed 1x..4x pointer-speed acceleration as X/Y on top of the base
quarter-J'-per-trackwheel-height response. Mouse input uses click, document-level
follow, then an anywhere confirmation click; touch and pen drag directly.
Its separate ruler shows the displayed (possibly snapped) J' value, the
203-nit reference, and the active patch.

The narrow layout does not scroll. Its minimum acceptance viewport is `360x645`
CSS pixels at `devicePixelRatio = 3`; overflow checks are performed in CSS
pixels while retaining all readouts and controls.
