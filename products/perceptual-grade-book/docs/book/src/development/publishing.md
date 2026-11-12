# Publishing

> **Historical implementation guidance:** this chapter retains the 1.23.2 runtime, source layout, and validation profile. For current development commands and supported behavior, use the product READMEs in [chromaticity](https://github.com/rei277hz/chromaticity).

Publish only after reviewing the installable extension and DCTL in their hosts, and the built handbook in both languages. Keep RELEASES.md in the repository up to date; it is intentionally not a book chapter.

``` sh
buck2 build //:release '//:docs_deploy[zip]' --show-full-output
buck2 test //:build_inputs //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_inputs //:documentation_site //:packaging_artifacts
```

Extract perceptual-grade-site.zip into the publication directory with index.html and .nojekyll at its root. Runtime scripts, equation fonts, figures and generated demonstrations are local. Pontano Sans and Roboto Mono load from the declared CDN. Introduction shows only its local WebP demonstration; the Bilibili player proof of concept is commented out until a real video is ready. The deployment works at a domain root or a project subdirectory. The checks cover chapters, links, fragments, CSS resources, the WebP demonstration, absence of an active external video iframe and deterministic ZIPs. The release records the site archive’s hash alongside the source inputs.
