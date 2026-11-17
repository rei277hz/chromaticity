# Publishing

> **Mixed current and historical guidance:** the book-site outputs and linked
> Buck2 publication targets are current. The release procedure retained after
> them still describes the 1.23.2 runtime, source layout, and validation profile.
> For current development commands and supported behavior, use the product
> READMEs in [chromaticity](https://github.com/rei277hz/chromaticity).

The current documentation deliverables are one `perceptual-grade-site.zip`
containing both books, English and Simplified Chinese User Manual PDFs and
EPUBs, and an English Technical Report PDF and EPUB. The archive's root book
chooser links to the manual's language chooser at `manual/index.html` and the
English report at `technical/en/`. The manual's editions are at `manual/en/`
and `manual/zh-Hans/`. Build them with the targets in the
[current publication guide](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-book/README.md),
using Buck2 with `--remote-only`.

## Retained 1.23.2 release procedure

The original release procedure below also required reviewing the installable
extension and DCTL in their hosts. Keep RELEASES.md in the original repository
up to date; it is intentionally not a book chapter.

``` sh
buck2 build //:release '//:docs_deploy[zip]' --show-full-output
buck2 test //:build_inputs //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_inputs //:documentation_site //:packaging_artifacts
```

Extract perceptual-grade-site.zip into the publication directory with index.html and .nojekyll at its root. Reader scripts and static figures are local. Pontano Sans, Roboto Mono and KaTeX load from the pinned CDN resources. Current publication excludes intro/demo animations, stills, and animation provenance from the site, deployment ZIP, PDFs, and EPUBs while retaining the source recordings and separate producer targets. The User Manual describes Next and retains the labeled legacy 1.23.2 extension link; it offers no Next ZIP. The deployment works at a domain root or a project subdirectory. The Next-scoped handbook audit checks this media and download contract against completed artifacts. The release records the site archive’s hash alongside the source inputs.
