# Rust dependencies

`Cargo.toml` is this monorepo's Rust dependency catalogue. `Cargo.lock` pins its
complete dependency graph. First-party libraries and products declare Rust
targets in their own `BUCK` files and depend on public aliases in
`//third_party/rust`; they do not maintain separate Cargo manifests or locks.

Reindeer generates `BUCK` ahead of time. Normal Buck builds invoke the declared
Rust compiler directly and download checksum-pinned crate archives through
Buck's `http_archive` rules. Cargo and Reindeer are maintenance tools, not build
actions. Crate sources are not checked into this repository.

The generation tool is pinned to Reindeer
[`ede87128a86b36aa04e625071f87f52f05c7a827`](https://github.com/facebookincubator/reindeer/tree/ede87128a86b36aa04e625071f87f52f05c7a827).
The maintenance wrapper builds that revision with its upstream lockfile into a
user cache and verifies Cargo's installation receipt. It uses the Rust 1.99.1
distribution declared by `//tools/rust-build:distribution`.

Run these commands from the repository root:

```sh
python3 third_party/rust/regenerate.py
python3 third_party/rust/regenerate.py --check
```

To change a dependency, edit its requirement/features in `Cargo.toml`, run
`python3 third_party/rust/regenerate.py --update`, review the lock and generated
diffs, and build the affected products and Rust tests. `--update` permits Cargo
to resolve changed requirements while retaining compatible locked versions.
Ordinary regeneration and `--check` pass `--locked` to Cargo. Neither changes
dependency versions. New build scripts require explicit reviewed instructions
in `fixups/<crate>/fixups.toml`; generation fails until those are supplied.

The catalogue includes Linux x86_64 and macOS arm64 execution platforms and a
`wasm32-unknown-unknown` target platform. Their names map to Buck constraints in
`PACKAGE`. Reindeer's explicit execution-platform settings keep host procedural
macro/build-script feature resolution separate from Wasm dependencies.

mdBook and wasm-bindgen CLI are source-built executable dependencies:

| Tool | Generated public target |
| --- | --- |
| mdBook | `//third_party/rust:mdbook-mdbook` |
| wasm-bindgen | `//third_party/rust:wasm-bindgen-cli-wasm-bindgen` |

Their consumers use `exec_dep`, so they run on the execution platform. mdBook's
watch, serve, and search defaults are preserved. The wasm-bindgen CLI version
must match the wasm-bindgen crate version exactly. The wrapper checks that and
generates `tools/versions.json`, exported as `//third_party/rust/tools:versions`,
with tool versions, crate checksums, generator revision, and the lockfile hash.

Executable artifact dependencies need Cargo's `bindeps` support during metadata
generation. `cargo.bindeps = true` makes this pinned Reindeer invoke Cargo with
`-Zbindeps` and a scoped `RUSTC_BOOTSTRAP=1`. This does not change normal Buck
compilation. Direct Cargo maintenance commands need the same scoped settings.

Build-script fixups retain upstream code generation and compiler probes. Ring
and psm compile their packaged native sources through Buck's declared C/C++
toolchain; their link directives are explicitly honored. Stacker's script is
disabled because it only builds Windows sources, outside the configured target
set. The wasm-bindgen-shared overlay omits its optional checkout Git revision
lookup while preserving the schema hash, so local repository state does not
affect the generated bindings tool's version.

Do not run `reindeer vendor` here. Reindeer detects existing vendor state even
with `vendor = false`; the wrapper rejects it to keep the generated rules using
archives. `--cargo` and `--rustc` can supply explicitly verified 1.99.1 binaries
when bootstrapping the Buck toolchain itself.

After bootstrapping the generator, the wrapper sets `CARGO_HOME` to the ignored
`third_party/rust/.cargo` maintenance cache for both Cargo and Reindeer. A fresh
checkout downloads the locked crates there automatically; no cache symlinks or
manual setup are needed. Reindeer verifies each archive checksum before using
its size, avoiding an extra network request per crate on subsequent runs.

Linux NativeLink validation covers both native library test suites, both Wasm
packages, the deployed web archive, and the rendered handbook. A fresh source
checkout reused all 855 Rust compilation and 101 build-script actions from the
remote cache and reproduced both product archives exactly. Locked regeneration
also passes with an initially empty maintenance cache. The Darwin compiler
archives and component layouts were verified; execution on macOS has not been
tested from this Linux environment.
