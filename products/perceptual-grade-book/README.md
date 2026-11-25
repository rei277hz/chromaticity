# Perceptual Grade books

The two-book collection is published at
[rei277hz.github.io/perceptual-grade/](https://rei277hz.github.io/perceptual-grade/).
The bilingual User Manual covers Blender workflows. The English Technical
Report covers the shared analytic model, Blender runtime, and Resolve DCTL
product. Both follow Perceptual Grade's current controls and implementation
contracts.

`libraries/perceptual-grade-reference` is authoritative for model mathematics.
The Blender and DCTL sources, requirements, and tests define their respective
host behavior. The Technical Report records source and test evidence for
observable implementation claims. Its chapter audit checks coverage and
comment references; reviewers check that the prose matches the implementation.

The manual retains one archived extension download. Its exact bytes, checksum,
and embedded license are preserved. No other superseded product material is
part of the book.

## Build and preview

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
```

The root alias builds the combined site with `/manual/en/`, `/manual/zh-Hans/`,
and `/technical/en/`. The archive contains that deployable site with stable
ordering and timestamps. The preview serves the site at
`http://127.0.0.1:8080/`. The PDF and EPUB outputs use the same authored
chapters and do not modify the deployable site.

The Technical Report audit is available through
`//products/perceptual-grade-next-blender/tests:technical_report_audit` and
checks chapter coverage, source evidence, and report references in product
comments. The manual audit is available through
`//products/perceptual-grade-next-blender/tests:handbook_audit` and checks the
published user-facing scope and static media. Both are Buck targets.

## Figures and diagrams

Numerical figures derive from the current analytic reference. D2 policy
diagrams are authored in `docs/book/diagrams/` and generated as accessible
static SVGs through Buck2:

```sh
buck2 build --remote-only //products/perceptual-grade-book/diagrams:assets --show-output
buck2 build --remote-only //products/perceptual-grade-book:book_refs --show-output
```

Use stable `grade-policy.*` anchors in comments such as
`# pg-book: technical-report/en#grade-policy.node-output`. The source-reference
resolver checks the authored Markdown and generated HTML. Anchor identifiers
must be unique within each book and language. Published policy URLs use the
same identifiers.

## Sources and generated resources

| Path | Ownership |
| --- | --- |
| `docs/book/` | English report and bilingual manual sources, themes, and authored artwork. |
| `docs/data/`, `docs/media/` | Current figure inputs, host captures, and recordings. |
| `generators/` | Buck producers for current figures, screenshots, icons, and static media. |
| `diagrams/` | Current policy-diagram rendering, accessibility checks, and provenance. |
| `historical/` | The one checksum-verified archived ZIP. |
| `print/` | Derived PDF and EPUB pipeline, themes, and edition front matter. |
| `tools/` | Assembly, reference resolution, rendering, archive, preview, and publication adapters. |

`:book_inputs` projects the authored manual and report into separate mdBook
roots. Generated resources have explicit producers and provenance. The
publication archive contains HTML, local static assets, and the single archived
ZIP. Fonts and KaTeX load from pinned CDN URLs; the print editions package the
fonts they require.

## Publish to the local website checkout

The default destination is
`~/workspace/rei277hz.github.io/perceptual-grade/`:

```sh
buck2 run --remote-only //products/perceptual-grade-book:publish
```

The publisher validates the completed archive and replaces the contents of the
book-site directory while preserving the parent checkout's `.git` and sibling
directories. To choose another destination, append
`-- --destination /path/to/website/site-directory`. Committing and pushing the
website remain separate operations.
