# Print Editions

The print build produces three PDF and three EPUB files from two books: an
English and Simplified Chinese User Manual, plus an English-only Technical
Report. It starts with each book's mdBook `print.html`, then adds front matter,
navigation, static KaTeX markup, print media, and the print or EPUB stylesheet.
There is no second Markdown renderer, and generated documents are not edited
by hand.

The books are maintained for the latest Perceptual Grade. The Technical Report's
model chapters follow the current reference. Some User Manual chapters, host
captures, and runtime engineering material still describe 1.23.2 and are
identified accordingly. The title pages do not label the whole collection as
1.23.2.

## Build and Check

Run from the monorepo root:

```sh
buck2 build --remote-only '//products/perceptual-grade-book:user-manual[pdf]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:user-manual[epub]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:technical-report[pdf]' --show-output
buck2 build --remote-only '//products/perceptual-grade-book:technical-report[epub]' --show-output
buck2 test --remote-only //products/perceptual-grade-book/print:print //products/perceptual-grade-book/print:epub
buck2 build --remote-only //products/perceptual-grade-book/print:review --show-output
buck2 build --remote-only //products/perceptual-grade-book/print:policy_review --show-output
buck2 build --remote-only //products/perceptual-grade-book/print:chart_review --show-output
buck2 build --remote-only //products/perceptual-grade-book/print:chart_preview --show-output
buck2 build --remote-only //products/perceptual-grade-book/print:policy_preview --show-output
```

The PDF output is A4 and uses fixed pagination, running heads, folios, and
chapter-level navigation. The EPUB is reflowable and splits content at chapter
boundaries. The User Manual targets each contain English and Simplified Chinese
files; the Technical Report target contains one English file. The resulting
files are `user-manual-en.pdf`, `user-manual-zh-Hans.pdf`,
`technical-report-en.pdf`, and the corresponding three `.epub` files. Their
build outputs live under Buck2's output directory; `print-manifest.json` records
chapter order, figures, tool versions, hashes, and the combined mdBook site
manifest hash.

The Technical Report's numerical plots are static PGFPlots SVGs shared with its
website edition. Their text is outlined for consistent rendering across browsers,
WeasyPrint PDF, and EPUB readers; image alt text and captions provide context.
The original recorded LUT reports remain downloadable with their source data.

The PDFs use full Tinos and Noto Serif SC font files from a pinned Google Fonts
revision. Noto's full variable source is instantiated at weights 400 and 700
before layout. The English PDF uses Tinos; the Chinese PDF falls back to Noto
Serif SC for Chinese glyphs, including inside code. Do not substitute web font
shards: WeasyPrint 70 can assign different shards the same PDF font identity,
corrupting both visible glyphs and copied text. The renderer excludes the EPUB's
sharded CJK stylesheet from its in-memory PDF document.

The remote test checks embedded fonts, Chinese Unicode extraction (including
`选择工作白点`), and agreement between the User Manual PDF Unicode map
and embedded glyph IDs. The Technical Report remains English-only. EPUB retains
its existing fonts.
Release still requires a visual review of Chinese line breaks, punctuation, and
dense paragraphs at A4 width; text extraction cannot judge those page-level
details.

The optional `:review` target renders the Chinese User Manual's cover and pages
containing “选择工作白点” (“Choose a working white”), together with their
adjacent pages, to PNG using pinned PDFium. Its `review.json` records the PDF
hash and physical page numbers. This is a raster review without OCR.
The `:policy_review` target renders every page of the English Next policy
chapter in the Technical Report, using its PDF outline to select the chapter
boundaries.
The `:policy_preview` target renders one policy or workflow diagram per A4 page
at the same maximum size used in the report. Check these proofs for readable
labels before rebuilding the complete report. The diagram action separately
rejects text overlaps using pinned Chromium and the SVG's embedded fonts;
passing that geometry check does not establish readability after scaling.
The `:chart_preview` target builds an independent A4 PDF with one numerical
chart per page at its natural print size, plus 144 dpi PNGs and a manifest. Use
it while editing chart sources to check labels, legends, clipping, and spacing
without rebuilding the whole book.

The `:chart_review` target renders the English Technical Report's numerical-chart
pages at 144 dpi. It matches generated HTML figure IDs to PDF destinations, so
the selection follows pagination changes. It also includes the page after each historical placement
chart to review candidate keys that flow over a page boundary. The manifests
record each chart, figure ID, PDF hash, and physical page number.
Both PDF builds and tests use `PAR_APPEND_LD_LIBRARY_PATH` to preserve the
pinned Pango/HarfBuzz libraries through Buck's Python launcher.

The combined site remains owned by `//products/perceptual-grade-book:site`. The
print targets consume that output and emit their PDF and EPUB groups. Tests
compare the current site and deployment archive with the actual site manifest,
and check the manifest referenced by each print build. There is no frozen site
baseline to update. Print layout changes alone must not alter the deployed site.

## Layout Ownership

Edit book prose, chapter ordering, and figures in `docs/book/`. Keep the User
Manual's English and Simplified Chinese chapter paths aligned; the Technical
Report is currently English-only. The manual uses `docs/book/src/SUMMARY.md` and
`docs/book/zh-Hans/SUMMARY.md`; the report uses
`docs/book/src/report/SUMMARY.md`. Static D2 SVGs are generated by
`//products/perceptual-grade-book/diagrams:assets` and flow through the combined
site, PDF, and EPUB inputs. Each book's cover, title page, copyright page, and
colophon live in
`print/front-matter/<publication>/<language>/front-matter.html`, where
`<publication>` is `user-manual` or `technical-report`. Shared page tokens and the
print and reflowable EPUB skins live in `print/theme/`.

Tune the page grid, type, and spacing in the stylesheets while keeping the
authored Markdown unchanged. Review a representative set of pages before
building the complete editions: front matter, contents, a chapter opener, body
text, figures and captions, tables, callouts, code, and display equations. For
Simplified Chinese, check line breaks, punctuation placement, font coverage,
and dense paragraphs at A4 width. The chapter and figure lists, static math,
embedded PDF fonts, Chinese text extraction, page labels, archive determinism,
and agreement among current site files, the deployment archive, and the
referenced site manifest are covered by the print acceptance tests.
Stable book anchors used by code comments must follow their headings so they
remain inside the correct print and EPUB chapter. The acceptance tests check
the policy anchors in both editions, including PDF named destinations.

Fonts, KaTeX, and their notices are pinned build inputs. The derived document
copies only referenced local images; historical downloads link to the published
site. Do not add animation, video, or script-driven controls to print content.
