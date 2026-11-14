# Publishing

> **Historical implementation guidance:** this chapter retains the 1.23.2 runtime, source layout, and validation profile. For current development commands and supported behavior, use the product READMEs in [chromaticity](https://github.com/rei277hz/chromaticity).

The current documentation deliverables are one `perceptual-grade-site.zip`
containing both books, English and Simplified Chinese User Manual PDFs and
EPUBs, and an English Technical Report PDF and EPUB. The archive's root book
chooser links to the manual's language chooser at `manual/index.html` and the
English report at `technical/en/`. The manual's editions are at `manual/en/`
and `manual/zh-Hans/`. Build them with the targets in the
[current publication guide](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-book/README.md),
using Buck2 with `--remote-only`.

The original release procedure below also required reviewing the installable
extension and DCTL in their hosts. Keep RELEASES.md in the original repository
up to date; it is intentionally not a book chapter.

``` sh
buck2 build //:release '//:docs_deploy[zip]' --show-full-output
buck2 test //:build_inputs //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_inputs //:documentation_site //:packaging_artifacts
```

Extract perceptual-grade-site.zip into the publication directory with index.html and .nojekyll at its root. Reader scripts, figures and generated demonstrations are local. Pontano Sans, Roboto Mono and KaTeX load from the pinned CDN resources. The User Manual introduction shows its local WebP demonstration; the Bilibili player proof of concept is commented out until a real video is ready. The deployment works at a domain root or a project subdirectory. Checks cover both books, cross-book links, fragments, CSS resources, the WebP demonstration, absence of an active external video iframe and deterministic ZIPs. The release records the site archive’s hash alongside the source inputs.
