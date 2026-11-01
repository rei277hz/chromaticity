# modCAM16 image decomposition

Reusable Rust image decoding, camera/ICC interpretation, preview, and
decomposition kernels imported from the current working tree of
`modcam16-hk-ucs`. The crate name remains `modcam16-decomposition-wasm`; its Buck
library depends on `//libraries/modcam16-color-core:lib`. External dependencies
come from the central [Rust catalogue](../../third_party/rust/README.md), with no
independent Cargo manifest or lockfile.

`src/gpu.wgsl` is a declared shader input. The image-processing API preserves
PNG/JPEG, HEIF/HEIC pixel-buffer, DNG, and EXR behavior and the generated Wasm
export names. Named source-gamut overrides support Rec.709/sRGB, Display P3,
Rec.2020, and scene-reference ACES; Adobe RGB overrides are rejected. Generic
ICC and DNG profile interpretation remains supported.

```sh
buck2 build //libraries/modcam16-decomposition:wasm --show-output
buck2 test //libraries/modcam16-decomposition:test
```

The stale declaration of an absent `gpu_host_tests.rs` module was removed;
existing CPU tests remain with the implementation. One ignored test requires
personal DNG fixtures and is not part of required acceptance. Browser/Wasm
fallback evidence does not establish hardware WebGPU parity.

See the [web product provenance](../../products/hdr-color-picker-web/ORIGIN.md)
for import and licensing boundaries.
