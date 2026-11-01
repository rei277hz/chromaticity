# Grade and Stack UI validation — 1.17.0

The supplied complete 1.16.0 source pack was merged with the 1.17.0 Blender runtime,
new editing regressions, English/Chinese handbook and forward/inverse specification.
The DCTL sources, Buck2 build definitions, documentation generators, media and
original fixtures remain in the complete source tree.

All **54 numerical, Blender, DCTL and parity fixtures passed**, including the new
30-case pytest suite. The original isolated fixture runner was used with its explicit
`--authoring-preview` flag. Blender was 5.2.2 LTS, Python 3.13.15 and NumPy 2.5.3.
`//:blender_test_stack_editing` registers the added tests with the Buck2 graph.
Existing Stack/white/undo tests now model inverse application through Stack entries;
UI and translated-title expectations use the new node titles. Solver studies use a
test-only nonlinear inverse adapter, with no restored standalone inverse node path.

Input declaration checks and all 19 generator output contracts passed. Locale
validation also passed, including automatic discovery of a synthetic third language.
The pinned mdBook 0.5.4 rebuild passed its structure, resource/link and deployment
ZIP checks: 28 chapters per language, 63 HTML pages and 3,534 links/resources.
All 1,045 equations rendered with the bundled KaTeX. Unchanged published media
were reused as authoring inputs; numerical figures and changed text were rebuilt.
The structured [validation record](grade-stack-ui-validation.json) contains the full
fixture list and documentation checks.

Buck2 itself is unavailable in this runtime, so these executions do not satisfy its
release gate. Desktop/GPU/Resolve checks remain separate. Existing numerical
precision and illustrative benchmark reports have not been relabeled as new runs.
