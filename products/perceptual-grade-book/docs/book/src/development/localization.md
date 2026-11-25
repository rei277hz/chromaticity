# Localization

Perceptual Grade ships English and Simplified Chinese Blender interfaces and
Resolve DCTL controls. The User Manual also has English and Simplified Chinese
editions. Each runtime and book has its own source catalog; keep translated
meaning consistent while following that interface's terminology and context.

## Blender interface

Blender's semantic JSON catalogs are in
`products/perceptual-grade-next-blender/src/locales/`. The extension validates
that locale keys and formatting placeholders match the English catalog, then
loads its compiled gettext catalogs. Blender's `zh_CN` locale resolves to the
Simplified Chinese catalog.

When changing a message, update each catalog with the same key and placeholders.
Follow the UI binding to understand whether the text is a control label,
tooltip, error, warning, or status. Run the product's localization tests with
Buck2 remote execution and inspect the affected panel in Blender when the
layout or meaning depends on the host UI.

## Resolve DCTL controls

DCTL UI declarations are generated from the source fragments and specifications
in `products/perceptual-grade-dctl/src/`. Localized catalogs supply the
English and Simplified Chinese labels. The DCTL interface tests check generated
declarations, slider types, counts, and locale coverage. Numerical and
portability tests check the generated entry points independently of Resolve's
interactive UI.

Preserve Resolve-specific interface limits and types. In particular, the Warp
DCTL uses integer hue sliders so its floating-point slider count remains within
the host limit. A host-level check requires loading the generated DCTL in
Resolve.

## User Manual

English chapters are under `products/perceptual-grade-book/docs/book/src/`.
Simplified Chinese translations are under `docs/book/zh-Hans/` and keep the
same relative chapter paths and ordering. Update both `SUMMARY.md` files when
changing chapter structure. Shared figures and media use the same published
asset paths from either language.

Build the site and run the book or handbook audit target to check chapter
coverage, links, and rendered editions. Read the corresponding page in both
languages after changes to navigation, controls, or interface terminology.
