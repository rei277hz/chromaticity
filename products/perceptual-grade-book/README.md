# Perceptual Grade 1.23.2 handbook

The handbook is published at
[rei277hz.github.io/perceptual-grade/](https://rei277hz.github.io/perceptual-grade/).
It documents **Perceptual Grade 1.23.2**. Its mathematical content, measurements,
and archived release downloads retain that version's meaning; it has not been
updated for Perceptual Grade Next.

Submit [issues](https://github.com/rei277hz/perceptual-grade/issues) to the
downstream project and [pull requests](https://github.com/rei277hz/chromaticity/pulls)
to this development repository. The handbook's GitHub toolbar links here.

## Build, preview, and test

Run from the monorepo root:

```sh
buck2 build //:perceptual_grade_book --show-output
buck2 build '//products/perceptual-grade-book:site[html]' --show-output
buck2 build '//products/perceptual-grade-book:archive[zip]' --show-output
buck2 run //products/perceptual-grade-book:preview -- --port 8080
buck2 test //products/perceptual-grade-book/tests:book //products/perceptual-grade-book/tests:publish
```

The root alias builds the site. The `html` output is its deployable directory;
`:archive[zip]` produces `perceptual-grade-site.zip` with stable ordering, fixed
ZIP timestamps and permissions, and a SHA256 report. The preview serves the
built site at `http://127.0.0.1:8080/`. Build actions use the configured Buck2
execution platform, including NativeLink; preview and publishing run locally.

Buck2 builds mdBook 0.5.4 from the central
[Rust dependency graph](../../third_party/rust/README.md). Separate actions
regenerate numerical and photographic figures, composed screenshots, demo and
introductory WebPs, favicons, and manifests from declared source inputs. The
photo and figure generators use the original 1.23.2 mathematical implementation.
Their pinned Python packages and bundled FFmpeg are build dependencies; a clean
build needs neither the sibling legacy checkout nor locally installed tools.

The renderer preserves English and Simplified Chinese editions, language
selection, Chinese search, part numbering, print pages, themes, equations, and
historical Markdown report downloads. Fonts and KaTeX load from version-pinned
jsDelivr URLs. KaTeX script and stylesheet references include integrity hashes.
Buck verifies the pinned CDN resources while preparing the configuration and
license notices; font and KaTeX payloads are absent from the deployment ZIP.
Media are served locally. Reading equations and loading the chosen fonts require
access to the CDN.

## Sources and generated resources

| Path | Ownership |
| --- | --- |
| `docs/book/` | Maintained Markdown, navigation, theme, source artwork, and archived reports. |
| `docs/data/`, `docs/media/` | Figure settings, recorded measurements, screenshots, and original recordings. |
| `generators/` | Build-time producers and the isolated legacy numerical inputs needed by the handbook. |
| `cdn/` | Pinned CDN configuration, resource verification, and license assembly. |
| `historical/`, `historical-manifest.json` | Immutable historical downloads and their SHA256 inventory. |
| `tools/` | Assembly, rendering, validation, archive, preview, and publishing adapters. |

`:book_inputs` combines authored content, generated resources, dependency
notices, and historical downloads in a declared output tree. Each path has one
owner: overlapping inputs fail before rendering. Missing or altered historical
downloads also fail. Markdown edits and changed recording or figure inputs flow
through ordinary Buck2 builds without refreshing a frozen documentation hash
inventory. Generated provenance uses stable source identifiers and records input
and output hashes; no checked-in rendered snapshot is consumed.

The supplied `perceptual_grade-v1.23.2-20261101.zip`, historical DCTL files,
translation-review CSV, and historical license remain archived bytes. The
handbook does not build a current extension to replace them. Historical benchmark
and engineering measurements are retained as data, rather than rerun on each
builder. Historical attachment hashes and generator provenance remain explicit inputs.

Tests cover source assembly, edited chapters, missing or overlapping inputs,
generated provenance, both language editions, local links and fragments, CDN
references, historical download bytes, and deterministic archive metadata. The
book build and its tests remain independent of current product proof targets.

## Publish to the local website checkout

The downstream repository is the local Git checkout that receives the built
output, by default `~/workspace/rei277hz.github.io/`. The downstream site is its
`perceptual-grade/` directory:

```sh
buck2 run //products/perceptual-grade-book:publish
```

This builds `:archive[zip]` through the configured execution platform and then
runs the publisher locally. After validating the completed ZIP, the publisher
replaces every file and directory under the destination. The parent checkout's
`.git` and other site directories are preserved. To select another destination,
append `-- --destination /path/to/website/site-directory`. The destination must
be a direct child of an existing Git worktree and cannot contain its own `.git`.
Committing and pushing the website remain separate operations.
