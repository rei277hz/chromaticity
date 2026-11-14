# Documentation and media

This chapter preserves the original 1.23.2 source layout and build commands. For
the maintained monorepo targets, editable sources, generated resources, and
deployment ZIP, see the [current book build guide](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-book/README.md).
The current build regenerates derived media from source and keeps historical
release downloads as verified attachments.

The User Manual and Technical Report are independent mdBooks with declared Buck2 inputs for chapters, recordings, screenshots, numerical figures and runtime assets. Reader scripts and generated media are local; KaTeX equations and the text and code fonts load from pinned CDN resources. The User Manual introduction uses the local WebP demonstration. The Bilibili player proof of concept remains commented out in its Markdown source until a real video is ready. Validation retains the exact player URL allowlist for future use.

## Edit and build

The maintained publication now contains two books. The User Manual uses
`docs/book/src/README.md`, `guide/`, and `reference/`, with matching Simplified
Chinese chapters under `docs/book/zh-Hans`. Their `SUMMARY.md` files must keep
the same chapter paths and order. The English-only Technical Report uses
`theory/`, `development/`, shared `reference/`, and its own introduction and
`SUMMARY.md` under `docs/book/src/report/`. Chinese technical chapters have been
discarded. Keep reader instructions in the manual and model calculations and
maintenance guidance in the report. Use Markdown chapter links, `$$` display
equations and `\( ... \)` inline TeX.

Assembly projects these sources into independent mdBook roots. The combined
site serves the manual at `manual/en/` and `manual/zh-Hans/`, and the report at
`technical/en/`, with a book chooser at the root. Shared assets and downloads
remain at the site root. Chapter links across the books are resolved within
that deployment; print editions link to the corresponding published web page.
Build `//products/perceptual-grade-book:archive[zip]` for the single site ZIP,
or `:user-manual[pdf]`, `:user-manual[epub]`, `:technical-report[pdf]`, and
`:technical-report[epub]` in that package for the six print files. Run build
and test commands through Buck2 with `--remote-only`.

### Code references to the books

Code comments can point to a stable section without copying a filename or a
heading slug. Use the exact form below; the book and language are part of the
reference, and the identifier is declared by an explicit anchor immediately
after the Markdown heading:

```python
# pg-book: technical-report/en#next-policy.node-output
```

```markdown
## Node output policy

<a id="next-policy.node-output"></a>
```

The resolver reads Python comments with the Python tokenizer, so the same text
inside a string or docstring is ignored. It indexes only chapters listed by the
edition's `SUMMARY.md`, checks that each identifier is unique, and then checks
the generated HTML contains exactly one matching ID. A chapter can move or its
heading can be renamed while the reference remains valid as long as the
explicit identifier stays with the section. Identifiers are unique within a
book and language. Supported editions are `technical-report/en`,
`user-manual/en`, and `user-manual/zh-Hans`.

Build the reference report with:

```sh
buck2 build --remote-only //products/perceptual-grade-book:book_refs --show-output
```

The output directory contains `book-refs.json` and `book-refs.txt`. They locate
the source comment, original Markdown heading, generated site page, published
URL, and local preview URL. Missing or duplicate anchors and malformed comments
fail the build. The declared input covers Next Blender Python sources and the
comparison publication example; add markers at the policy and effect-consumer
contracts that need navigation. Both reports are build artifacts.

To follow the local URLs, serve the same generated site:

```sh
buck2 run --remote-only //products/perceptual-grade-book:preview -- --port 8080
```

### Historical build commands

The commands below describe the original repository:

``` sh
buck2 build //:docs_site '//:docs_deploy[zip]' --show-full-output
buck2 run //:docs_preview -- --port 8080
buck2 test //:build_inputs //:documentation_intro //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_inputs //:documentation_site
```

The Light and Dark themes adapt the ACES documentation’s typography, neutral surfaces and gold accent. Auto follows system appearance. The full-width title bar sits above both the sidebar and the reading column. The contents stop at chapters and sections; page headings are excluded. Each book and language edition has its own sidebar and search index, with chapter numbers restarting at each part. Previous/next page buttons are removed.

The CSS and reader controls live in docs/book/theme. The maintained builder runs `tools/parts.py` through mdBook’s preprocessor protocol before rendering, so the dynamic and no-JavaScript contents have identical numbering. Changing either book's SUMMARY.md updates its hierarchy; a third nesting level fails instead of adding more detailed navigation.

### CDN typography

Pontano Sans supplies text and Roboto Mono supplies code, matching the font families in the ACES overview page. Text sizes, line heights, heading weights and wide-screen scaling follow that page’s styles. The browser loads version-pinned WOFF2 files directly from jsDelivr, with an early connection and preload for the body font. The swap setting lets the intended font appear even when the first request is slow.

The original //:book_fonts action verified every font and license against third_party/docs.bzl, then generated the CSS and downloads/provenance/fonts.json. In the current monorepo, the CDN assets action verifies pinned font and KaTeX resources and assembles their configuration, integrity hashes, and license notices. The browser requests their versioned jsDelivr URLs; their payloads are absent from the deployment ZIP. Missing inputs, changed hashes and unexpected external scripts or styles fail validation.

``` sh
buck2 build //:book_fonts '//:docs_deploy[zip]' --show-full-output
buck2 test //:documentation_fonts //:documentation_site //:build_inputs
```

## Require complete sources

The checked inventory in build_defs/source_inventory.bzl lists every authored source, including MOVs, screenshot PNGs, appearance artwork, catalogs, model code, fixtures, build definitions and locks. The separate `products/perceptual-grade-icon` package owns the authored icon configuration and Blender generator; its `:icons` target supplies the sixteen rendered PNGs to the book. Buck2 checks its source collections against that inventory; missing or unregistered files fail. Pinned downloads require their declared hashes and have no local substitute. All generators run in clean output directories and must produce every declared output; fixture capture, extension packaging, release packaging and site packaging reject incomplete inputs.

Catalog and translation-review actions require every catalog, binding and source module, then check the generated MO files and CSV. Native diagram assets require the pinned model and CMF dependencies. DCTL generation and C++ validation require every fragment, UI specification, catalog and harness source.

Fixtures require their scripts, extension modules and captured reports. Numerical and photographic figures require their model, data and sampled images. Screenshots require every configured PNG; demonstrations require both MOVs for every operation.

The book requires all chapters, theme files, illustrations, fonts, runtime assets and generated media. Deployment checks the complete site manifest. Extension and release packaging require all authored extension files, compiled catalogs, localized DCTLs, the review CSV and dependency locks.

Measurement requires Blender, its worker and resources; lock maintenance requires the existing dependency lock. A missing new measurement cannot reuse an old JSON result.

Replacing an existing file needs no inventory change. After intentionally adding or removing a source, explicitly refresh and review the inventory:

``` sh
python3 tools/build/source_inventory.py --refresh
buck2 test //:build_inputs //:packaging_artifacts
```

The build never refreshes this inventory automatically and never generates a substitute for a missing input. The screenshot dummy generator is an explicit authoring command; the required dummy PNGs are already included as source files.

## Replace the icons

The icon product generates transparent and opaque artwork at 16, 32, 48, 64, 180, 192, 256 and 512 pixels by rendering each requested size in Blender. Keep every filename and native dimension when changing its authored configuration. The book consumes `//products/perceptual-grade-icon:icons`; it does not keep a second authored icon set.

The ICO contains the original transparent PNG payloads at 16, 32, 48, 64 and 256 pixels. The title uses the 32px artwork and the 64px render for high-density displays. The 180px opaque image is copied byte-for-byte to apple-touch-icon.png. The web manifest uses the supplied transparent 192px and 512px images for ordinary Android icons.

The icon generator produces the transparent and opaque variants directly. The book's favicon packager embeds the transparent 16, 32, 48, 64 and 256px PNG bytes in the ICO and copies the native 180, 192 and 512px platform images. It creates the separate 512px maskable tile by placing the opaque 256px render on a padded background; the generated manifest declares only this separate variant as maskable. These icons do not add offline caching or a service worker.

``` sh
buck2 build //:book_favicon '//:docs_deploy[zip]' --show-full-output
buck2 test //:documentation_favicon //:documentation_site
```

## Replace the introduction recording

Replace docs/media/intro/match-three-images.mp4 with your final recording of matching three differently lit images. The supplied Timeline 1.mp4 occupies this required path as a dummy source. The recording is one complete composition; the build does not rearrange it into the paired tutorial layout.

The //:book_intro action reads docs/data/intro-video.json. It explicitly interprets Rec.709 primaries, the BT.709 YCbCr matrix, limited video range and a Gamma 2.4 transfer, then converts to sRGB and embeds an sRGB profile in the WebP. The transfer interpretation does not depend on the MP4's unspecified transfer metadata. Set range explicitly to full if a replacement export uses full-range levels.

The WebP keeps the source dimensions and playback speed, loops indefinitely, and has no audio. Optional start and end values trim the recording in seconds; null end means its recorded end. Frame durations follow the original frame rate, with millisecond rounding distributed across frames. The default quality is 90 to keep the animation practical to download; quality and lossless are explicit encoding settings. A separate lossless still is used only for printing.

``` sh
buck2 build //:book_intro '//:docs_deploy[zip]' --show-full-output
buck2 test //:documentation_intro //:documentation_site
```

Missing, corrupt, empty or incorrectly configured sources fail before producing an animation. Replace the MP4 or edit its trim settings, then rebuild the site.

## Replace paired recordings

Each demonstration consumes two square MOV screen recordings containing the image and the Perceptual Grade extension’s gizmo in Blender. Example A is SDR, Example B is HDR. Both recordings are Rec.709 gamut with Rec.709-A transfer; the recording of HDR footage is still a display-referred screen recording, not a PQ or HLG video master.

The source pack includes the supplied square dummy recording at every sdr.mov and hdr.mov path below. The same clip occupies both sides of all ten operations; these temporary clips do not illustrate the grades described in the lessons. Replace them with the real recordings, keeping the filenames, in the indicated directory under docs/media/demos:

| Directory          | What to record on both sides                                                                                            |
|--------------------|-------------------------------------------------------------------------------------------------------------------------|
| linear-white-balance | Drag the vectorscope, reset Source White, then repeat by dragging the source-white point directly. |
| linear-correction | Continue from white balance; adjust both Balance handles and all four Spread/Heading handles. |
| colorchecker-match | Starting with that correction, align the chart’s scope readings to the connected EXR.                                   |
| tone-curve         | A: S-shaped contrast. B: gamma-like dark-area lift.                                                                     |
| color-j            | A: Shadows and White. B: Midtones and Highlights. Use the J curve twice in each recording.                              |
| color-jc-curves    | Both select Midtones; adjust J and C curves together.                                                                   |
| color-jc-pads      | Both select Midtones; adjust J and C a/b pads together.                                                                 |
| color-adaptance    | A: Shadows and White. B: Midtones and Highlights.                                                                       |
| color-hue-pad      | A: Shadows and White. B: Midtones and Highlights.                                                                       |
| color-hue-rotation | A: Shadows and White. B: Midtones and Highlights.                                                                       |

For example, replace color-j/sdr.mov and color-j/hdr.mov. Each clip begins with the previous step’s final grade. Within the first white-balance clip, reset only Source White between the two equivalent gestures; carry its final correction into linear-correction. Retain the same image, zoom, framing and display transform throughout. Record only the few seconds of the adjustment; no Resolve recording is required. Its corresponding named sliders are documented in the lesson. The suggested tonal choices and purposes can be revised with the lesson text when final footage is selected; keep the two-tone versus shared-tone structure.

Every MOV is required. One absent side or an absent pair fails before any demonstration is generated. Nonsquare recordings and invalid trims also fail. The build identifies the bundled dummy by its SHA-256 and labels only panels that still contain those bytes. Replacing a MOV automatically removes that panel’s dummy label; no flag needs to be edited. A normal site build never overwrites source recordings or screenshots.

### Trim each side independently

Edit docs/data/demos.json. Start and end are seconds on that file’s timeline; end = null means the end of the recording. For example:

``` json
{
  "sdr": {"file": "tone-curve/sdr.mov", "start": 0.4, "end": 4.7, "range": "auto"},
  "hdr": {"file": "tone-curve/hdr.mov", "start": 1.1, "end": 5.8, "range": "auto"}
}
```

Both trimmed clips start together at playback time zero. Each keeps its elapsed time; the shorter side holds its last frame until the longer side finishes. The default 700 ms final hold gives the viewer time to inspect the result, then the pair loops from the beginning. There is no reverse playback or speed matching. Choose trims around the complete gesture to make the loop easy to follow.

The output settings select a 640-pixel square per side at 20 fps. Frame-rate resampling does not slow or accelerate the operation. A clip may contain up to 60 seconds after trimming. The output has a static first-frame companion for printing. On-screen demonstrations always animate, with infinite looping encoded in the WebP; there is no playback selector.

### Interpret color explicitly

The pinned imageio-ffmpeg 0.6.0 wheel supplies the FFmpeg binary. The build does not search the host for another FFmpeg installation. For YCbCr input, decoding uses the Rec.709 matrix and the recording’s declared range. Range can be set to full or limited in each clip entry when metadata is wrong; auto uses decoder metadata.

The pipeline decodes to 16-bit RGB, interprets Rec.709-A as a 1.961 power transfer, then applies the piecewise sRGB encoding before quantizing for WebP. Rec.709 and sRGB share primaries and D65 white, so no primary matrix change is needed. An sRGB ICC profile is embedded. The explicit interpretation overrides reliance on ambiguous QuickTime transfer tags. Blender’s [OCIO configuration](https://github.com/blender/blender/blob/main/release/datafiles/colormanagement/config.ocio) is the reference for the Rec.709-A exponent.

The already-rendered screen image is converted for browsers; this step neither re-grades the footage nor applies another HDR tone map. The build writes source hashes, independent trims, decoded frame counts, durations, conversion settings and FFmpeg version to assets/demos/manifest.json in the site.

``` sh
buck2 build //:book_demos '//:docs_deploy[zip]' --show-full-output
buck2 test //:documentation_demos //:documentation_site
```

The MOV test generates real lossless MOV fixtures and checks color conversion, trim timing, original speed, end holds, loop metadata, ICC, deterministic output and missing-source errors, including an entirely absent pair.

## Replace screenshots

Overwrite the PNGs in docs/media/screenshots, keeping their stable filenames. The layouts in docs/data/screenshots.json compose them into full-size linked figures. Keep sockets, relevant controls and their labels legible.

| Filename                 | Capture                                                                                |
|--------------------------|----------------------------------------------------------------------------------------|
| blender-install.png      | Install from Disk and the enabled extension.                                           |
| blender-shading.png      | Image Texture → Perceptual Grade → shader → Material Output.                           |
| blender-compositing.png  | Image or Render Layers → Perceptual Grade → output, plus Viewer.                       |
| resolve-install.png      | Open LUT Folder, installed DCTL, Update Lists and effect selection.                    |
| resolve-cst-input.png    | Unmanaged DaVinci YRGB node chain and input CST’s XYZ/Linear output.                   |
| resolve-dctl-white.png   | Destination White and the matching linear XYZ chain.                                   |
| resolve-cst-output.png   | Return CST’s XYZ/Linear input and selected output encoding.                            |
| colorchecker-connect.png | Photograph → Color and ACEScg EXR → Color Reference, with both traces.                 |
| waveform-sdr.png         | A’s image and waveform: label dark areas, midtones and diffuse white.                  |
| waveform-hdr.png         | B’s image and waveform at the same scale: label diffuse white and brighter highlights. |

Use the English UI. Record the host version, image interpretation, working space, view transform and changed controls alongside your original capture notes. Disable auto exposure. For the chart, match orientation and crop, interpret the reference EXR explicitly as ACEScg, and avoid glare on the photographed patches.

``` sh
buck2 build //:book_screenshot_figures '//:docs_deploy[zip]' --show-full-output
buck2 test //:documentation_inputs //:documentation_site
```

The optional //:screenshot_placeholders target creates new dummy files in its output directory; ordinary builds never replace authored source captures.

## Appearance references and generated figures

The runtime flowchart is authored as assets/illustrations/runtime-flow.svg and has a text explanation in Architecture and runtime. Edit its vector source when changing the update lifecycle.

The two published modCAM16 reference images are ordinary source PNGs under docs/book/src/assets/illustrations. Replace them directly and update captions and attribution when choosing final artwork. Their origin and hashes are recorded in docs/data/appearance-references.json. They have no drawing generator.

The `//products/perceptual-grade-book/generators:figures` target uses the current reference for the linear basis, Tone, coefficient weights, drivers, and H–K repair. Concentration and the archived LUT examples use the isolated 1.23.2 model; benchmarks and LUT-study comparisons retain their recorded inputs. Each figure declares its scope in `figures.json`, and provenance includes the reference and legacy source hashes. Python supplies the numerical samples to pinned XeLaTeX/PGFPlots, which emits static SVGs for the English Technical Report's website, PDF and EPUB editions. Four book-facing LUT-study figures are redrawn from recorded data. The domain-128 finalist errors retain the report's eight-decimal precision, and two placement axes are reconstructed from the documented formulas; the downloadable report archives remain unchanged. The `//products/perceptual-grade-book/generators:photos` target generates preserved-release and historical-guard comparisons from the five sampled EXR/PQ fixtures. Historical recorded measurements remain explicitly identified inside Bounded H–K guard; regenerated comparison sheets are distinct.

Each producer records input/output hashes. Source or data changes invalidate the corresponding Buck2 action; `//products/perceptual-grade-book:book_inputs` collects and projects the declared outputs into both book trees. The combined site manifest inventories all shipped files, including local media and pinned CDN resource manifests. Browser font and KaTeX payloads remain on the CDN; print editions package their required fonts separately.

[Download the chart sources and plotted data](../downloads/chart-sources.zip) to inspect the numerical inputs, figure definitions and provenance used by the current vector renderer. Candidate keys beside the historical LUT plots map their compact labels to complete grid names.
