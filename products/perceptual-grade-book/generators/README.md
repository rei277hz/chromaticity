# Handbook asset producers

These build-only producers regenerate the Perceptual Grade 1.23.2 handbook's
figures, photographs, screenshots, animations, icon files, and runtime diagrams.
Their source was adapted on 2026-11-04 from that release's `tools/docs`,
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
only from the pinned imageio-ffmpeg wheel. NativeLink executes the producers with
fixed process settings, and each action requires all its declared output files.
Provenance records logical source paths, independent of checkout or sandbox paths.

```sh
buck2 build //products/perceptual-grade-book/generators:assets --show-output
buck2 test //products/perceptual-grade-book/generators:tests
```

`:assets` is a tree relative to the assembled book. Individual public targets are
`:figures`, `:photos`, `:screenshots`, `:demos`, `:intro`, `:favicon`,
`:ab_background`, and `:locus`. Their named outputs include required media and
provenance. Generated files belong in Buck outputs; do not copy them into source.

The tests exercise real encoded MOV fixtures, color interpretation, trim timing,
print stills, looping, deterministic output, required media failures, exact PNG
payloads in ICO files, and provenance independent of build locations.
