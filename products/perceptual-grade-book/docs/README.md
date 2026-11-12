# Handbook source layout

This directory contains the maintained Perceptual Grade handbook, original
recordings and artwork, and historical measurements. Its English and Simplified
Chinese model chapters track the latest `libraries/perceptual-grade-reference`.
The usage guide and parts of the engineering documentation still lag at 1.23.2;
mark their version explicitly until they are updated. Historical measurements
and downloads remain evidence for their original configuration. The current
book build is documented in [the product README](../README.md); build instructions
inside historical chapters describe the original 1.23.2 repository.

| Location | Content |
| --- | --- |
| `book/src`, `book/zh-Hans` | English and Simplified Chinese chapters and navigation. |
| `book/theme`, `book/book.toml` | Maintained reader integration and mdBook configuration. |
| `book/src/assets` | Authored icons and reference illustrations. |
| `../print/` | Derived PDF and EPUB build, page styles, and bilingual front matter. |
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

The mdBook static site continues to load its fonts and KaTeX from pinned CDN
URLs. Those payloads are not included in the deployment ZIP. The separate print
pipeline reads mdBook's own `print.html`, renders its math statically with the
pinned KaTeX package, and vendors the required fonts into the derived PDF and
EPUB inputs. It uses the same authored Markdown and chapter ordering without
changing the site output.
