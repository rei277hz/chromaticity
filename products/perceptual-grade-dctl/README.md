# Perceptual Grade DCTL

This product follows the root [MIT](../../LICENSE-MIT) or
[Apache-2.0](../../LICENSE-APACHE) licensing, at your option. The additional GPL
distribution grant for Blender extensions does not apply to DCTL.

Build both localized editions with
`buck2 build //products/perceptual-grade-dctl:dctl --show-output`.
`product.toml` owns this product's version independently of Blender manifests.

The product owns grading/overlay headers, the Resolve UI specification and its
source generator. It imports host-independent grading resources/catalogs from
`perceptual-grade-core` and generic DCTL color primitives from `color-dctl`.
Its tests additionally use the independent `perceptual-grade-reference`. None of
its generation or numerical validation targets depends on a Blender product or
Blender's Python runtime.

The emitted files are standalone. Tests compile the emitted numerical source
as float32 C++ and OpenCL, compare it with the numerical reference, and validate
localized UI declarations. The product-specific host dispatch lives under
`tests/support`; the reusable parser and float3 shim are in `tools/dctl-testing`.
