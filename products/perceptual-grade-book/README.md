# Perceptual Grade 1.23.2 handbook

The Perceptual Grade Handbook is published at
[rei277hz.github.io/perceptual-grade/](https://rei277hz.github.io/perceptual-grade/).

**Legacy handbook:** this documents Perceptual Grade 1.23.2 and has not been
updated for Perceptual Grade Next.

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) is the
downstream code snapshot, currently containing the preserved Perceptual Grade
v1.23.2 code from the 2026-11-01 build, not Perceptual Grade Next. It accepts
[issues](https://github.com/rei277hz/perceptual-grade/issues),
but does not accept pull requests. Submit all
[pull requests to rei277hz/chromaticity](https://github.com/rei277hz/chromaticity/pulls),
the development repository. The handbook's GitHub toolbar link points there.

This product preserves the documentation from **Perceptual Grade 1.23.2**. Its
208 original files under [docs/](docs/README.md) preserve English and Simplified
Chinese chapters, recordings, measurements, and historical development
instructions. Documented updates cover the current licensing policy, disabling
the introductory Bilibili proof of concept, legacy notices in both language
introductions, repository roles and contribution links, and the replacement
development-extension download links; all other original
files are unchanged.
The historical chapters describe that release. The current monorepo and
Perceptual Grade Next have different implementations and build targets.

Use the commands below to build this imported book. Commands inside the
[original handbook](docs/book/src/README.md) remain historical instructions for
the 1.23.2 source tree.

## Build, preview, and test

Run from the monorepo root:

```sh
buck2 build //:perceptual_grade_book --show-output
buck2 build '//products/perceptual-grade-book:site[html]' --show-output
buck2 build '//products/perceptual-grade-book:archive[zip]' --show-output
buck2 run //products/perceptual-grade-book:preview -- --port 8080
buck2 test //products/perceptual-grade-book/tests:book
```

The root alias builds `:site`. Its `html` output is the deployable static site;
`:archive[zip]` packages it with fixed ZIP timestamps and permissions. The preview
serves the built site at `http://127.0.0.1:8080/`. Building uses the monorepo's
configured execution mode, including NativeLink; the preview server runs locally.

Buck compiles the pinned mdBook 0.5.4 executable from the central
[Rust dependency graph](../../third_party/rust/README.md). The builder preserves both language editions, the language
picker, Chinese search, chapter numbering, themes, and KaTeX equations. KaTeX and
media are served from the built site. As in the original book, text/code fonts
load from pinned jsDelivr URLs. The introduction shows its local WebP demonstration;
the Bilibili player proof of concept is commented out until a real video is ready.
The build also preserves the historical Markdown reports as downloads and keeps
their generated links pointing to the original `.md` files.

## Publish to the local website checkout

The **downstream repo** is the local Git checkout that receives this product's
built output, by default `~/workspace/rei277hz.github.io/`. The **downstream site**
is its generated `perceptual-grade/` directory. Requests to "update the downstream
repo" or "update the downstream site" mean running this command from the
monorepo root:

```sh
buck2 run //products/perceptual-grade-book:publish
```

This builds `:archive[zip]` through NativeLink, then runs the publisher locally.
The publisher validates the completed ZIP, removes **every file and directory**
under `~/workspace/rei277hz.github.io/perceptual-grade/`, and extracts the ZIP's
contents there. It creates the `perceptual-grade/` directory if absent. The parent
website checkout's `.git` and other site directories are preserved.

To use another checkout, append `-- --destination /path/to/website/site-directory`.
The destination must be a direct child of an existing Git worktree and must not
contain its own `.git`. The command updates local files; committing and pushing
the website remain separate steps. NativeLink stays enabled throughout.

```sh
buck2 test //products/perceptual-grade-book/tests:publish
```

## Preserved sources and supplemental snapshot

| Path | Purpose |
| --- | --- |
| `docs/` | The complete 1.23.2 documentation tree, with documented source adaptations. |
| `snapshot/` | Supplemental files added to `docs/book`: preserved generated media, fonts, vendor files, provenance, historical downloads, and the replacement development-extension ZIP. |
| `import-manifest.json` | SHA-256 inventories of every original and supplemental file, plus reconstruction provenance. |
| `tool-pins.bzl` | Preserved asset versions and historical tool archive provenance; active mdBook pins live in `third_party/rust/`. |
| `tools/` | Assembly, mdBook rendering, validation, archive, preview, and local publishing adapters. |
| `tests/` | Import preservation, rendered-site, archive, and failure-mode checks. |

Normal builds verify both inventories, copy `docs/book` into a declared output,
and add the snapshot. Supplemental paths must not replace original files. Missing,
extra, or changed inputs fail before rendering. The build does not need the
sibling checkout, historical Blender runtime, FFmpeg, or asset-generation scripts.

The supplemental generated artifacts were **reconstructed from the old inputs**;
they are not claimed to be the bytes of a previously published site. Their
generator/input hashes, tool pins, and build identifiers are recorded in
`import-manifest.json`. Historical measurements already present in `docs/` remain
the original records; this import does not rerun or reinterpret their findings.

The current English and Simplified Chinese [license pages](docs/book/src/reference/license.md)
explain the root `MIT OR Apache-2.0` source license and the additional
`GPL-3.0-or-later` grant for Blender releases and their Corresponding Source.
English credits retain the scientific attribution formerly shipped in the
extension's notice. `provenance.docs_adaptations` records each edited page's
original SHA-256 and the reason for its change; the `docs` inventory checks the
current bytes. The original extension download has been replaced with the
supplied `perceptual_grade-v1.23.2-20261101.zip` in `snapshot/src/downloads/`, and the
old ZIP has been removed. This is a Perceptual Grade 1.23.2 development build
dated 2026-11-01 of the preserved implementation, not Perceptual Grade Next.
The supplied ZIP is preserved byte for byte. The legacy handbook has not been
updated to describe this development build. Archived DCTL downloads, runtime
notices, other snapshot assets, and historical license texts remain unchanged.

The original one-time snapshot preparation used this procedure, before the
extension-download replacement described above:

1. Build `//:docs_inputs` in a disposable copy of the 1.23.2 source tree with its
   pinned tools and historical generators. The import used NativeLink; its runtime
   and build-only configuration changes are recorded in `import-manifest.json`.
2. Copy only assembled paths absent from the original `docs/book` into
   `snapshot/`, retaining their paths relative to the assembled book.
3. Populate the site downloads with the exact original
   `install/perceptual_grade-1.23.2.zip` and `install/Perceptual-Grade*.dctl` files.
4. Replace temporary build paths in supplemental figure provenance with verified
   paths relative to the historical release, retaining all input/output hashes.
5. Record all snapshot SHA-256 values and reconstruction provenance in
   `import-manifest.json`; verify the original 208 documentation files remain
   unchanged.

Snapshot regeneration is an explicit maintenance operation. Ordinary book builds
consume the checked-in snapshot. Refreshing it requires reviewing the changed
artifacts and manifest together, then rebuilding and testing the site.

The test target verifies preserved file hashes, both language editions, local
links and fragments, math markup, shared assets, historical downloads, manifests,
and deterministic archive metadata. It also checks that missing or tampered
supplemental files and attempts to overwrite original book files are rejected.

The Reindeer migration was validated on 2026-11-01: the source-built mdBook
produced both editions, 65 HTML pages and 3,915 checked local references. All 17
book tests passed through NativeLink. The 69,526,892-byte archive was reproduced
byte for byte from a separate source checkout using the remote cache; its SHA256
is `5effe302b0117ed14bec8198192c901f69092354559e3b915aba05b5b41a5990`.
