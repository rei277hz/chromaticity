# Handbook source layout

This directory contains the authored Perceptual Grade 1.23.2 handbook, original
recordings and artwork, and historical measurements. Its English and Simplified
Chinese chapters retain the legacy release's content. The current product build
is documented in [the product README](../README.md); build instructions inside
historical chapters describe the original 1.23.2 repository.

| Location | Content |
| --- | --- |
| `book/src`, `book/zh-Hans` | English and Simplified Chinese chapters and navigation. |
| `book/theme`, `book/book.toml` | Maintained reader integration and mdBook configuration. |
| `book/src/assets` | Authored icons and reference illustrations. |
| `data` | Figure parameters, timing records, and media specifications. |
| `media/screenshots` | Original host captures used by screenshot composition. |
| `media/demos`, `media/intro` | Original recordings converted to WebP during Buck2 builds. |
| `engineering`, `book/src/downloads` | Historical engineering reports and measurements. |

Edit chapters, artwork, captures, and recording specifications here. Buck2
regenerates derived figures, composites, WebPs, icons, and manifests, assembles
both language editions, and packages the deployment ZIP. Generated output is
kept under Buck2's output directory. Source edits use normal Buck2 dependency
tracking.

Both editions must keep matching chapter paths. Replacing an existing recording
or PNG needs no build-rule edit; adding a new generated resource requires a
declared producer and assembly path. Missing inputs and conflicting paths fail
the build. Historical measurements remain recorded evidence and are not
remeasured by documentation builds.

Fonts and KaTeX load from pinned CDN URLs. Their payloads are neither vendored
here nor included in the deployment ZIP; the build verifies pinned inputs and
assembles the corresponding configuration and license notices.
