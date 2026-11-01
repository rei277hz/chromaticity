# Project and documentation map

`README.md` is the repository's front door. This file is the source-layout map.
The reading material lives in `book/`, an mdBook whose navigation is defined by
[`book/src/SUMMARY.md`](book/src/SUMMARY.md).

| Location | Ownership |
| --- | --- |
| `src/blender/model` | Color models, smooth curves, numerical LUTs and statistics |
| `src/blender/graph` | Runtime native graphs, curve textures and LUT publication |
| `src/blender/scopes` | Pixel sampling and scope statistics |
| `src/blender/ui` | Sidebar, interactive diagrams and gestures |
| `src/blender/localization`, `locales` | Message bindings, gettext integration and translation JSONs |
| `src/blender/integration` | Host registration and cleanup |
| `src/dctl` | Analytic DCTL body, UI specification and overlay |
| `tools/assets`, `tools/build`, `tools/docs` | Build-time artwork, packaging and documentation tools |
| `tools/testing`, `tests` | Buck2 execution adapters and fixtures |
| `third_party`, `toolchains`, `build_defs` | Dependency pins, execution tools and Buck2 rules |

## Documentation ownership

| Location | Content |
| --- | --- |
| `book/src/guide` | Installation and everyday grading |
| `book/src/theory` | Current mathematical specifications |
| `book/src/development` | Building, testing, assets, graph design and contributing |
| `book/src/reference` | Credits, references and license |
| `data`, `media/screenshots`, `media/demos` | Figure data, replaceable host captures and paired square MOV recordings |
| `tools/docs` (repository root) | Reproducible figure and measurement producers |
| `book/theme` | ACES-inspired stylesheet, icon, equations, print images and theme integration |
| `book/book.toml` | mdBook configuration |

Generated PNGs, catalogs, localized DCTLs, the translation CSV, HTML and deployment
archives are Buck2 outputs. `//:docs_inputs` collects book sources and generated
resources; `//:docs_site` renders HTML; `//:docs_deploy` packages it for upload.
The complete `//:release` includes the site archive and source provenance.

The extension's packaged `NOTICE.md` is copied from [runtime-notice.txt](runtime-notice.txt). Legal `LICENSE` files
stay beside their respective sources. Completed work-item checklists are
consolidated into the [runtime architecture chapter](book/src/development/architecture.md).

Start with [building](book/src/development/building.md), [testing](book/src/development/building.md#run-tests),
or [maintaining the book](book/src/development/documentation.md).

## Reconstructed handbook source pack

The application starts from the supplied earlier fixed source, with corrected Cyan-Red and Yellow-Blue control identifiers and labels. The handbook
revision is reconstructed from the attached discussion and the reviewed site.
`reconstruction.json` maps requirements to source files and states validation
limits; `history/revision-discussion.txt` preserves the attached discussion.

Replace the ten PNGs in `media/screenshots` directly. The supplied dummy recording
is bundled in all twenty MOV slots. Replace each pair of
`sdr.mov` and `hdr.mov` under the directory in `data/demos.json`, and set their
independent start/end trims there. Both are square Rec.709/Rec.709-A screen
recordings; Example A is SDR and Example B is HDR. Each operation starts from
the preceding result. Rebuild with:

```sh
buck2 build //:release '//:docs_deploy[zip]' --show-full-output
buck2 test //:build_inputs //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_inputs //:documentation_site \
  //:packaging_artifacts //:build_text_sources
```

All sixteen supplied icon PNGs are in `book/src/assets/icons`. The title and favicon
use transparent artwork. `//:book_favicon` packages exact-size PNGs into the ICO, copies the 180px Apple and 192/512px Android images, and creates a separate maskable composition without resampling.
`//:book_fonts` verifies pinned Pontano Sans and Roboto Mono WOFF2/license inputs;
the deployed book loads those fonts directly from jsDelivr. `tools/docs/parts.py`
restarts numbering at each book part, while contents and search stay combined.
The two appearance reference PNGs are replaceable source artwork without a
drawing generator; update their captions and attribution when replacing them.

Every required source must exist. Builds do not synthesize replacement media,
reuse a previous output directory or omit missing release files. The checked
inventory in `build_defs/source_inventory.bzl` covers all authored inputs.
Overwriting a MOV or PNG at its existing filename needs no inventory edit.
Register an intentional new source with `python3 tools/build/source_inventory.py --refresh`.

English pages live in book/src; title-only Chinese counterparts live in book/zh-Hans. The root entry chooses a remembered language or matches browser locales, with English as the default. Each edition shares search across all parts. Release history lives only in ../RELEASES.md.

Replace media/intro/match-three-images.mp4 for the introductory demonstration. The //:book_intro action converts explicitly declared Rec.709 / Gamma 2.4 video to a looping sRGB WebP at its original dimensions and speed. Trims and range are in data/intro-video.json.
