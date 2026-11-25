# Building Perceptual Grade

The repository uses Buck2 to build Blender extensions, localized Resolve
DCTLs, generated resources, the books, and their test fixtures. Run executable
builds and validation with remote execution from the monorepo root.

## Product outputs

| Target | Output |
| --- | --- |
| `//products/perceptual-grade-next-blender:extension` | Packaged Blender extension. |
| `//products/perceptual-grade-next-blender:node_templates` | Generated native node templates and runtime indexes. |
| `//products/perceptual-grade-dctl:dctl` | English and Simplified Chinese Resolve DCTL stages. |
| `//products/perceptual-grade-book:site[html]` | Deployable manual and Technical Report site. |
| `//products/perceptual-grade-book:archive[zip]` | Deterministic site archive and checksum report. |
| `//products/perceptual-grade-book:user-manual[pdf]` | English and Simplified Chinese manual PDFs. |
| `//products/perceptual-grade-book:technical-report[pdf]` | English Technical Report PDF. |

Build the product packages with:

```sh
buck2 build --remote-only //products/perceptual-grade-next-blender:extension --show-output
buck2 build --remote-only //products/perceptual-grade-dctl:dctl --show-output
buck2 build --remote-only //products/perceptual-grade-next-blender:node_templates --show-output
```

Use `--show-output` to print artifact locations. DCTL target outputs contain
both locales. The extension target packages runtime code and the generated
resources declared by its Buck graph.

## Source ownership

The analytic equations and model proofs live in
`libraries/perceptual-grade-reference`. Blender runtime features live in
`products/perceptual-grade-next-blender/src/features/`, with host-neutral
primitives in `src/runtime/` and numerical preparation in `src/kernel/`.
Resolve DCTL source fragments and locale-specific control specifications live
in `products/perceptual-grade-dctl/src/`; `tools/generate_dctl.py` assembles
their entry points. Book chapters, figure inputs, and media producers belong
to `products/perceptual-grade-book`.

Each product owns its adapter and conformance tests. Shared model changes
should update the reference tests and the relevant Blender or DCTL checks.
Generated package contents are build outputs; edit their declared source
inputs and rebuild them.

## Remote validation

Use Buck targets that match the changed behavior. For Blender, the target list
is declared in `products/perceptual-grade-next-blender/tests/BUCK`. For DCTL,
the focused interface, numerical, and portability suites are:

```sh
buck2 test --remote-only \
  //products/perceptual-grade-dctl/tests:interface \
  //products/perceptual-grade-dctl/tests:numerical \
  //products/perceptual-grade-dctl/tests:portability
```

The report audit and manual audit are part of the Blender product's packaging
tests. Book assembly, site publication, and print outputs are documented in
the [book product README](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-book/README.md).
Desktop Resolve compilation and interactive Blender acceptance require their
respective host applications and are not established by headless tests.
