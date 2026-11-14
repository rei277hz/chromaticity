# Perceptual Grade books

The two-book collection is published at
[rei277hz.github.io/perceptual-grade/](https://rei277hz.github.io/perceptual-grade/).
It contains two books maintained for the **latest Perceptual Grade**. The
bilingual User Manual contains the introduction and user guides in English and
Simplified Chinese. The English-only Technical Report contains the theory and
development chapters. The report's model chapters follow
`libraries/perceptual-grade-reference`, including Stage 3 Adaptance → H–K
repair → common positive Scale. Some manual, host-capture, and runtime material
still describes the preserved 1.23.2 release. Each current or historical
profile is identified; archived downloads and recorded measurements retain
their original meaning. The Technical Report includes the **Next Blender policy
machines** chapter, which follows current Next policies and adapters. Next has
not yet implemented its Warp UI.

Submit [issues](https://github.com/rei277hz/perceptual-grade/issues) to the
downstream project and [pull requests](https://github.com/rei277hz/chromaticity/pulls)
to this development repository. Both books' GitHub toolbars link here.

## Build, preview, and test

Run from the monorepo root:

```sh
buck2 build --remote-only //:perceptual_grade_book --show-output
buck2 build --remote-only '//products/perceptual-grade-book:site[html]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:archive[zip]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:user-manual[pdf]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:user-manual[epub]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:technical-report[pdf]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:technical-report[epub]' --show-output
buck2 run --remote-only //products/perceptual-grade-book:preview -- --port 8080
buck2 test --remote-only //products/perceptual-grade-book/tests:book //products/perceptual-grade-book/tests:publish
buck2 test --remote-only //products/perceptual-grade-book/print:print //products/perceptual-grade-book/print:epub
```

The root alias builds the combined site. It contains the English and Simplified
Chinese User Manual and the English Technical Report. The `html` output is its
deployable directory; `:archive[zip]` produces one `perceptual-grade-site.zip`
with stable ordering, fixed ZIP timestamps and permissions, and a SHA256 report.
The preview serves the built site at `http://127.0.0.1:8080/`. Build actions
use the configured Buck2 remote execution platform; preview and publishing run
locally.

The `:user-manual[pdf]` and `:user-manual[epub]` outputs contain separate
English and Simplified Chinese editions. The corresponding
`:technical-report[pdf]` and `:technical-report[epub]` outputs contain the
English report. PDF is fixed-page A4; EPUB is reflowable. These targets do not
modify the deployable site. The print builder consumes the combined `:site`
output. See [the print workflow](print/README.md) for layout ownership and
review guidance.

Buck2 builds mdBook 0.5.4 from the central
[Rust dependency graph](../../third_party/rust/README.md). Separate actions
regenerate numerical and photographic figures, composed screenshots, demo and
introductory WebPs, favicons, and manifests from declared source inputs. The
11 generated numerical plots combine current-reference Linear, Tone, driver,
and H–K calculations with explicitly historical Concentration, LUT examples,
and benchmark data. Python produces the data and a pinned XeLaTeX/PGFPlots
toolchain renders outlined-text SVGs. Each figure records its model scope and
source hashes. Four recorded LUT-study plots are redrawn from archived
measurements. These charts appear in the English Technical Report and use the
same SVGs in its site, PDF, and EPUB editions.
The publication includes [chart sources and plotted data](https://rei277hz.github.io/perceptual-grade/downloads/chart-sources.zip)
for inspection and reuse, with candidate keys beside the historical plots.
Photos, screenshots, and D2 diagrams retain their existing producers. Pinned
Python/TeX dependencies and bundled FFmpeg are build inputs; a clean build needs
neither the sibling legacy checkout nor locally installed tools.

The renderer preserves the manual's English and Simplified Chinese editions,
language selection, Chinese search, part numbering, print pages, themes,
equations, and historical Markdown report downloads. Fonts and KaTeX load from
version-pinned jsDelivr URLs. KaTeX script and stylesheet references include
integrity hashes. Buck verifies the pinned CDN resources while preparing the
configuration and license notices; font and KaTeX payloads are absent from the
deployment ZIP. Media are served locally. Reading equations and loading the
chosen fonts require access to the CDN.

The Technical Report is currently English-only. Its D2 policy diagrams are
static SVGs with embedded fonts, generated with the pinned D2 distribution
through Buck2. State diagrams use ELK, and workflow traces use D2's built-in
sequence layout. Use ELK for graph layouts; the renderer records its layout and
spacing flags in the provenance manifest:

```sh
buck2 build --remote-only //products/perceptual-grade-book/diagrams:assets --show-output
```

Edit the diagram sources in `docs/book/diagrams/` and their accessible titles in
`diagrams/figures.json`. Outputs and provenance stay in Buck2 artifacts; no
installed D2 or checked-in generated SVG is used. A pinned Chromium/Playwright
check measures the rendered text after embedded fonts load. Overlapping labels
fail the diagram action, blocking the site, PDF, and EPUB until the source is
repaired. Its results and tool versions are recorded in the same provenance.
Each state-machine box names one phase or one derived configuration. A double
border marks an absorbing state; retain literal phase names, including
`terminal`. Keep explanatory notes in the chapter and put conditions on edges.

Use `# pg-book: technical-report/en#next-policy.node-output` in Python comments
to refer to a stable book section. An explicit `<a id="next-policy.node-output"></a>`
immediately after the target heading declares the identifier; chapter filenames
and heading text can change without changing the comment. The resolver checks
the original Markdown and generated HTML and reports both source locations and
published/local URLs. Only real comments are read; strings and docstrings are
ignored. Identifiers must be unique within a book and language.

```sh
buck2 build --remote-only //products/perceptual-grade-book:book_refs --show-output
buck2 test --remote-only //products/perceptual-grade-book/tests:book_refs //products/perceptual-grade-book/tests:book_refs_integration
```

The generated `book-refs.json` and `book-refs.txt` scan the declared Next Blender
Python sources, including the comparison publication example. The supported
editions are `technical-report/en`, `user-manual/en`, and `user-manual/zh-Hans`.
Start `:preview -- --port 8080` through `buck2 run --remote-only` to follow the
local URLs. Keep explicit anchors after their headings so print and EPUB
chapter boundaries retain them with the right section.
Grouped sequence diagrams show events, returned effects, Blender operations,
and receipts through `opt`, `loop`, `alt`/`else`, and `par` workflow fragments.
The comparison publication strategies remain explicitly distinguished from
the production path.

The [Bake section](docs/book/src/development/next-policies.md#next-policy.bake)
connects the request reducer to native Grade/Stack evaluation and managed Image
publication. Its phase and sequence diagrams are `09-bake.d2` and
`09-bake-sequence.d2`; queue admission and output selection remain stateless
decisions in the prose, rather than additional state diagrams.

## Sources and generated resources

| Path | Ownership |
| --- | --- |
| `docs/book/` | Maintained Markdown, navigation, theme, source artwork, and archived reports. |
| `print/` | Derived PDF and EPUB pipeline, print themes, and edition front matter. |
| `docs/data/`, `docs/media/` | Figure settings, recorded measurements, screenshots, and original recordings. |
| `generators/` | Build-time producers using the current reference for current theory and isolated legacy inputs for historical illustrations. |
| `cdn/` | Pinned CDN configuration, resource verification, and license assembly. |
| `historical/`, `historical-manifest.json` | Immutable historical downloads and their SHA256 inventory. |
| `tools/` | Assembly, rendering, validation, archive, preview, and publishing adapters. |

`:book_inputs` combines authored content, generated resources, dependency
notices, and historical downloads, then projects independent `user-manual/`
and `technical-report/` mdBook roots. The corresponding named subtargets expose
each tree. Each input path has one owner: overlapping inputs fail before
rendering. Missing or altered historical downloads also fail. Markdown edits
and changed recording or figure inputs flow through ordinary Buck2 builds
without refreshing a frozen documentation hash inventory. Generated provenance uses stable source
identifiers and records input and output hashes; no checked-in rendered
snapshot is consumed.

The supplied `perceptual_grade-v1.23.2-20261101.zip`, historical DCTL files,
translation-review CSV, and historical license remain archived bytes. The
book pipeline does not build a current extension to replace them. Historical
benchmark and engineering measurements are retained as data, rather than rerun
on each builder. Historical attachment hashes and generator provenance remain explicit inputs.

Tests cover source assembly, edited chapters, missing or overlapping inputs,
generated provenance, manual language editions, the English-only report, local
links and fragments, CDN references, historical download bytes, and deterministic
archive metadata. The book build and its tests remain independent of current
product proof targets.

## Publish to the local website checkout

The downstream repository is the local Git checkout that receives the built
output, by default `~/workspace/rei277hz.github.io/`. The downstream site is its
`perceptual-grade/` directory:

```sh
buck2 run --remote-only //products/perceptual-grade-book:publish
```

This builds `:archive[zip]` through the configured execution platform and then
runs the publisher locally. After validating the completed ZIP, the publisher
replaces every file and directory under the destination. The parent checkout's
`.git` and other site directories are preserved. To select another destination,
append `-- --destination /path/to/website/site-directory`. The destination must
be a direct child of an existing Git worktree and cannot contain its own `.git`.
Committing and pushing the website remain separate operations.
