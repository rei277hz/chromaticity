# Localization

> **Historical implementation guidance:** this chapter retains the 1.23.2 runtime, source layout, and validation profile. For current development commands and supported behavior, use the product READMEs in [chromaticity](https://github.com/rei277hz/chromaticity).

A useful translation preserves the meaning of a control across its label, tooltip and demonstration. Interface catalogs and handbook pages are separate sources, so you can contribute either without duplicating runtime logic.

## Translate the interface

Each language has one UTF-8 JSON catalog in `src/blender/locales/`. English is `en.json`; Simplified Chinese is `zh_HANS.json`. Both use semantic IDs such as `tooltip.linear.exposure`. Runtime code looks up IDs through GNU gettext.

Copy `en.json` to a file named for Blender’s language identifier, for example `de_DE.json` or `fr_FR.json`.

Translate its values, preserving all keys and formatting fields such as `{value}` and `{error}`. Keep mathematical notation consistent with the control labels. Read the English tooltip and corresponding source binding for context.

Build and review:

``` sh
buck2 build //:locales //:dctl '//:i18n_review[csv]' --show-full-output
buck2 test //:numerical_test_i18n_terms //:packaging_artifacts
buck2 test //:blender_test_ui //:blender_test_extension_namespace
buck2 build '//:extension[zip]' --show-full-output
```

Install the extension ZIP in Blender, select your language, and enable both interface and tooltip translation. Check the sidebar, all three diagrams, tooltips and warnings. Open the generated DCTL in Resolve to check its labels.

Adding a locale requires no language-specific Buck targets or duplicated tests. The build discovers JSON filenames, compiles each with Babel, emits one DCTL per language and adds one column to `i18n-review.csv`. The extension registers each catalog with Blender. English is also loaded from its JSON catalog.

The CSV includes labels, tooltips, errors, warnings and status messages. Its Exposure column distinguishes current source bindings from messages with no recognized binding. The Used by column points to Python call sites, DCTL controls and shared control-binding metadata. Dynamic message families are included.

Blender may use a locale alias: the existing `zh_CN` alias points to `zh_HANS`. If a new language needs a host-specific alias, add that one mapping to `_ALIASES` in `src/blender/localization/i18n.py`. Standard Blender locale IDs need no code edit.

Build-time Babel validates message IDs and formatting placeholders and generates standard `.mo` files. The installed extension uses Python’s standard `gettext` module and needs no additional translation package or network connection.

To add a new message, add the same ID to every locale, use that ID in the implementation, and regenerate the CSV. Control IDs and binding metadata are in `src/blender/localization/`; DCTL labels and tooltips reference those same IDs from `src/dctl/ui-spec.json`.


## Translate the User Manual

English manual chapters live in `docs/book/src/README.md`, `guide/`, and
`reference/`. Simplified Chinese chapters live in `docs/book/zh-Hans` with the
same relative filenames. Their SUMMARY.md files describe matching chapter
order; translate titles and full content without changing page correspondence.
The Technical Report contains the English theory and development chapters and
its own introduction and SUMMARY under `docs/book/src/report/`. It is currently
English-only; Chinese technical translations have been discarded.

Shared illustrations, recordings and downloads remain declared once. A translated chapter uses the same relative asset paths as its English counterpart. Run the documentation build and check the language menu, links and equations in both versions. The menu keeps the current page and remembers the chosen language.

The root landing page offers both books. The manual's `manual/index.html`
checks the saved choice first, then the browser’s language list, and uses
English when no supported locale matches. Explicit manual language URLs stay
in their requested language. The report has no Chinese language choice. Each
search index covers only the chapters of its own book and language.

Chinese search matches phrases directly in the stored titles and text, because the pinned mdBook search index uses an English stemmer. English retains mdBook’s normal search. Both clients search all parts of their own edition.
