# Book source layout

This directory contains the Perceptual Grade User Manual and Technical Report
sources, current media inputs, and derived figure settings. The manual is
bilingual. The report covers the analytic reference and current Blender and
Resolve implementations.

| Location | Content |
| --- | --- |
| `book/src`, `book/zh-Hans` | English report and User Manual sources, plus Simplified Chinese manual translations. |
| `book/src/SUMMARY.md`, `book/zh-Hans/SUMMARY.md` | English and Chinese User Manual chapter order. |
| `book/src/report/README.md`, `book/src/report/SUMMARY.md` | Technical Report introduction and chapter order. |
| `book/theme`, `book/book.toml` | Shared reader integration and mdBook configuration. |
| `book/src/assets` | Authored reference illustrations and shared artwork. |
| `../print/` | Derived PDF and EPUB pipeline, page styles, and front matter. |
| `data` | Current figure inputs and media specifications. |
| `media/screenshots` | Host captures used by screenshot composition. |
| `media/demos`, `media/intro` | Source recordings used by static media producers. |
| `engineering` | Current implementation validation records cited by the report. |

Edit chapters, artwork, captures, and recording specifications here. Buck2
regenerates figures, composites, static images, icons, and provenance, then
assembles separate Manual and Report mdBook roots. Generated outputs remain in
Buck2 artifacts.

The English and Simplified Chinese manuals keep matching chapter paths and
order. The Technical Report has its own English introduction, theory,
development, and reference chapters. Assembly projects each summary and its
chapters into an independent book. New generated resources need a declared
producer and assembly path. Missing inputs and conflicting destinations fail
the build.

The combined static site loads fonts and KaTeX from pinned CDN URLs. The
deployment archive excludes those CDN payloads. The print pipeline uses the
same authored Markdown and chapter ordering, renders equations with its pinned
math toolchain, and packages required fonts into PDF and EPUB outputs.
