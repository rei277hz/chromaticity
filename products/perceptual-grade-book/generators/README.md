# Book asset producers

These Buck actions regenerate Perceptual Grade figures, screenshots, animations,
icons, and policy diagrams. Source producers declare their inputs explicitly, so
media changes rebuild their outputs while chapter-only edits do not. Provenance
records stable logical paths instead of checkout or sandbox paths.

The numerical producer samples the current reference for Linear, Tone, Color,
and H–K behavior. Its two LUT figures read the live Blender kernel's 65-point
ACEScg axis and interpolation address. All figures declare current-reference
scope in `figures.json`. Python produces the numerical tables and PGFPlots source,
then pinned XeLaTeX, PGFPlots, and dvisvgm render the SVGs. The same vectors are
used by the English Technical Report site, PDF, and EPUB. The
`downloads/chart-sources.zip` package contains the source tables, plot files, and
provenance for these figures.

Edit numerical samples and plot definitions in `figures.py`, shared publication
provenance in `figure_common.py`, and typography in `plot-style.tex`. PGFPlots
handles numeric axes and mathematical labels. D2 produces state and architecture
diagrams, while screenshots and authored demonstrations remain raster media.

The chart renderer uses XeTeX's XDV output with the explicit
`pgfsys-dvisvgm.def` driver. dvisvgm outlines the bundled Tinos and TeX Gyre
Termes Math glyphs, so the same SVG needs no reader-side fonts in HTML, PDF, or
EPUB. Each SVG has a white canvas, title, and description. The shared style uses
9 pt labels and 8 pt ticks and legends, and tests limit charts to 160 mm wide
at their natural print size. The source ZIP includes the fonts and their
licenses alongside TeX, tables, and provenance.

```sh
buck2 build --remote-only //products/perceptual-grade-book/generators:assets --show-output
buck2 test --remote-only //products/perceptual-grade-book/generators:tests
buck2 test --remote-only //products/perceptual-grade-book/generators/latex:tests
```

`:assets` is a tree relative to an assembled mdBook root; assembly shares its
resources between both books. Individual public targets are `:figures`,
`:screenshots`, `:demos`, `:intro`, and `:favicon`. Their named outputs include
required media and provenance. Generated files belong in Buck outputs and do not
need to be copied into source.

The video recordings and `:demos`/`:intro` producers remain available, but their
animated outputs, stills, and animation provenance are not members of `:assets`.
No site, deployment ZIP, PDF, or EPUB ships animated images. Reintroducing a
video presentation must preserve that publication boundary.

The tests exercise encoded MOV fixtures, color interpretation, trim timing, print
stills, looping, deterministic output, required media failures, exact PNG
payloads in ICO files, and provenance independent of build locations.
