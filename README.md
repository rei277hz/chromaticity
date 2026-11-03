# chromaticity

[![Lint](https://github.com/rei277hz/chromaticity/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/rei277hz/chromaticity/actions/workflows/lint.yml)
[![Linux build targets](https://raw.githubusercontent.com/rei277hz/chromaticity/ci-status/builds.svg)](https://github.com/rei277hz/chromaticity/blob/ci-status/README.md)
[![Linux smoke suites](https://raw.githubusercontent.com/rei277hz/chromaticity/ci-status/tests.svg)](https://github.com/rei277hz/chromaticity/blob/ci-status/README.md)

Color grading, HDR color pickers, and reusable color-science libraries for
Blender, DaVinci Resolve, and the web.

Build/test badges describe the latest published manual run on the default
branch, not every commit or the full suite. They become available after the
first run; see [CI and badge reporting](tools/ci/README.md).

## Products

Each product owns its application, packaging, and acceptance tests. Blender
extensions bundle private dependencies and have independent lifecycles.

| Product | Description |
| --- | --- |
| [Perceptual Grade](products/perceptual-grade-blender/README.md) | Preserved Blender grading, analytic baking, and scopes |
| [Perceptual Grade Next](products/perceptual-grade-next-blender/README.md) | New Blender grading implementation; delivery and acceptance remain incomplete |
| [HDR Color Picker for Blender](products/hdr-color-picker-blender/README.md) | HDR color authoring for Grease Pencil |
| [HDR Color Picker for the web](products/hdr-color-picker-web/README.md) | Browser picker and image processing with WebGPU/Wasm |
| [Perceptual Grade DCTL](products/perceptual-grade-dctl/README.md) | Standalone grading tools for DaVinci Resolve |
| [Perceptual Grade handbook](products/perceptual-grade-book/README.md) | Historical 1.23.2 documentation, static-site build, and preview |

The preserved Grade product and the rebuilt Blender product have separate
contracts and evidence. The rebuilt product owns its state-machine policies,
requirements, proofs, and installed acceptance tests. Consult their READMEs for
current status, build commands, and installation.

## Libraries

Libraries own reusable implementation and component tests. Product-specific
behavior and installed acceptance remain with the products.

| Library | Responsibility |
| --- | --- |
| [Invariant](libraries/invariant/README.md) | Typed Machines, actor-owned Stores, source-bound verification, and runtime contracts |
| [Blender runtime](libraries/blender-runtime/README.md) | App lifecycles, execution helpers, native ownership, and registration |
| [Color core](libraries/color-core/README.md) | Shared Python color mathematics, ACES 2, and Grade modCAM16 |
| [Color DCTL](libraries/color-dctl/README.md) | Reusable DCTL matrix, chromaticity, and transfer helpers |
| [Perceptual Grade core](libraries/perceptual-grade-core/README.md) | Preserved grading mathematics, scopes, catalogs, and policies |
| [Perceptual Grade nodes](libraries/perceptual-grade-nodes/README.md) | Native Linear/Tone/Color graphs and guarded export |
| [Perceptual Grade reference](libraries/perceptual-grade-reference/README.md) | Reference algorithms and numerical investigation |
| [HDR Color Picker core](libraries/hdr-color-picker-core/README.md) | Picker coordinates, controls, and authoring rules |
| [modCAM16 color core](libraries/modcam16-color-core/README.md) | Rust picker appearance model, ACES kernels, and reference fixtures |
| [modCAM16 decomposition](libraries/modcam16-decomposition/README.md) | Rust image decoding, camera/ICC interpretation, and decomposition |

## Build entry points

Linux x86_64 builds use pinned Buck2 and default to NativeLink remote execution.
Install Buck2 with the [CI tooling instructions](tools/ci/README.md), then follow
[NativeLink setup](remote_execution/README.md#start) for Docker and client setup.
Run from the repository root:

```sh
./remote_execution/re up
./remote_execution/re validate
buck2 build //:hdr_color_picker_web --show-output
```

The example builds the web app's deployable ZIP. Other product commands are in
the linked READMEs above. For local execution, switching modes, and dependency
changes, see [Buck client configuration](remote_execution/README.md#buck-client-configuration)
and [runtime dependencies](remote_execution/README.md#runtime-dependencies-and-upgrades).

Handwritten Python defines policy behavior; Invariant checks source-bound
requirements with Z3, and Lean verifies color mathematics. Native behavior and
physical-device acceptance require separate evidence. See the
[verification guide](tools/verification/README.md) for targets and limits.

## Development documentation

| Guide | Contents |
| --- | --- |
| [Component packaging](build_defs/README.md) | Source ownership, Buck Python dependencies, and private extension packages |
| [CI and formatting](tools/ci/README.md) | Workflow triggers, local checks, and badge publishing |
| [Remote execution](remote_execution/README.md) | Deployment, dependency ownership, and runtime maintenance |
| [Remote validation](remote_execution/tests/README.md) | Local/remote execution checks, cache reuse, and acceptance coverage |
| [Verification](tools/verification/README.md) | Proofs, archive integrity, integration tests, and evidence boundaries |
| [Rust dependencies](third_party/rust/README.md) | Central dependency lock, Reindeer targets, and crate fixups |
| [Web dependencies](third_party/web/README.md) | Pinned npm archives, Node, and browser tooling |

## License

Original source code in this monorepo, including the Blender products, shared
libraries, and DCTL, is licensed under either the [MIT License](LICENSE-MIT) or
the [Apache License, Version 2.0](LICENSE-APACHE), at your option
(`MIT OR Apache-2.0`). Separately identified third-party materials, assets, and
archived distributions retain their own licensing.

Each Blender extension ZIP and its Corresponding Source are additionally offered
under `GPL-3.0-or-later`. The Blender products' `LICENSE` files are packaging
inputs for that distribution grant; they do not replace the root source-code
licenses. See the handbook's [licensing explanation](products/perceptual-grade-book/docs/book/src/reference/license.md)
([简体中文](products/perceptual-grade-book/docs/book/zh-Hans/reference/license.md)),
including the procedure for publishing the exact source used to build a release.
