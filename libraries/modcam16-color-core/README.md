# modCAM16 color core

Reusable Rust modCAM16-HK appearance, picker coordinates, ACES forward/inverse
transforms and ColorChecker kernels imported from the current working tree of
`modcam16-hk-ucs`. The crate remains `modcam16-color-core` with both `rlib` and
`cdylib` outputs. It is separate from the monorepo's Python `color-core`, whose
signed Grade appearance model has different numerical semantics.

`src/` owns the numerical implementation and checked-in ACES tables.
`references/colorchecker/` owns the official 24-patch source data and provenance
metadata used by Rust tests and the web product's independent OCIO oracle.
The existing 18 chromatic patch order and Wasm export layouts are preserved.

```sh
buck2 build //libraries/modcam16-color-core:wasm --show-output
buck2 test //libraries/modcam16-color-core:test
```

The `:lib` target is a native Buck Rust library. Its external dependencies come
from the central [Rust catalogue](../../third_party/rust/README.md); the library
has no independent Cargo manifest or lockfile. The generated JavaScript/Wasm
package is consumed by the web product through
declared Buck dependencies. No Adobe application or source generator is needed
at build time. Source provenance and licensing boundaries are recorded in the
[web product](../../products/hdr-color-picker-web/ORIGIN.md).
