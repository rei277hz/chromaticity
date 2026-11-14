# Book asset producers

These build-only producers regenerate the maintained Perceptual Grade books'
figures, photographs, screenshots, animations, icon files, and runtime diagrams.
Their original source was adapted on 2026-11-04 from 1.23.2's `tools/docs`,
`tools/assets`, and model/localization modules. Original paths and SHA-256 values
are recorded in `source-provenance.json`; the original GPL-3.0 license is retained
in `LICENSE`. Copyright belongs to Rei277Hz and the Perceptual Grade contributors.

`pg_book_legacy` preserves the model used by the historical chapters. It is
isolated from current product implementations and is used only by these build
tools. Its authored JSON catalogs are compiled by the pinned Babel dependency.
The photo producer reuses the existing photographic sample arrays and imports
the release's PQ PNG and fixture metadata. It renders the legacy comparison
through pinned Blender's ACES 2.0 / sRGB display transform.

All dependencies are explicit Buck inputs. Numerical/data/recording edits rebuild
their producer; chapter edits do not invalidate these media actions. FFmpeg comes
only from the pinned imageio-ffmpeg wheel. Remote execution runs the producers
with fixed process settings, and each action requires all its declared output
files.
Provenance records logical source paths, independent of checkout or sandbox paths.

The numerical plot producer uses the current mathematical reference for Linear,
Tone, coefficient weights, drivers, and H–K repair. It retains the legacy model
for the historical Concentration and LUT illustrations, and recorded benchmark
inputs remain historical. Each figure declares its scope in `figures.json`;
the data manifest records the current reference and legacy source hashes.
The producer computes model samples in Python and renders 11 plots
as SVG with the pinned XeLaTeX, PGFPlots, and dvisvgm toolchain. The plots appear
in the English Technical Report, with the same SVGs used for its site, PDF, and
EPUB editions. Four archived LUT plots are redrawn
from recorded rankings, scores, and axes; the domain-128 finalist errors retain
the report's eight-decimal precision, and two comparison axes are reconstructed
from the published sampling formulas. Original report archives remain unchanged.
The `:figures_data` action prepares the numeric tables and figure definitions;
`:figures` renders the SVGs. The publication's `downloads/chart-sources.zip`
contains the chart sources and plotted data. Candidate key fragments accompany
the historical figures in the report.

Edit numerical samples and plot definitions in `figures.py`, recorded-study
extraction in `historical_figures.py`, and shared typography in `plot-style.tex`.
PGFPlots handles numeric axes and mathematical labels; D2 remains the producer
for state and architecture diagrams. Photographs and screenshots remain raster
images.

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
buck2 test --remote-only //products/perceptual-grade-book/generators:historical_figures_test //products/perceptual-grade-book/generators/latex:tests
```

`:assets` is a tree relative to an assembled mdBook root; assembly shares its
resources between both books. Individual public targets are
`:figures`, `:photos`, `:screenshots`, `:demos`, `:intro`, `:favicon`,
`:ab_background`, and `:locus`. Their named outputs include required media and
provenance. Generated files belong in Buck outputs; do not copy them into source.

The tests exercise real encoded MOV fixtures, color interpretation, trim timing,
print stills, looping, deterministic output, required media failures, exact PNG
payloads in ICO files, and provenance independent of build locations.
