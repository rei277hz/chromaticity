# Handbook dependencies

`pins.bzl` owns the exact CDN URLs and SHA-256 values for KaTeX, Fontsource fonts,
their licenses, and the ColorChecker teaching download. Buck downloads these as
declared inputs; the book's CDN action verifies them and generates its stylesheet,
head template, integrity attributes, and provenance.

KaTeX JavaScript/CSS and all web fonts load from versioned jsDelivr URLs in the
reader's browser. Their downloaded bytes are build inputs only and are absent
from the site ZIP. Licenses and the ColorChecker EXR are included in the ZIP.
The book's own images, videos, and scripts are served locally by the site.

mdBook remains source-built by `//third_party/rust:mdbook-mdbook`; its executable
version comes from the central Rust lock. The license download here matches that
version.

To update a resource, change its exact versioned URL and verified SHA-256 in the
pins, then build and test `//products/perceptual-grade-book/cdn/...` and the full
book. SRI values are derived from the verified KaTeX inputs during the build.
