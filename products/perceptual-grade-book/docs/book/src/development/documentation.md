# Documentation and media

The Perceptual Grade books are assembled from declared Buck2 inputs. Edit
authored Markdown under `products/perceptual-grade-book/docs/book/`, figure and
media specifications under `docs/data/`, and source captures under `docs/media/`.
Generated figures, compositions, site files, and publication archives belong
in Buck outputs.

The User Manual is maintained in English and Simplified Chinese. Their
`SUMMARY.md` files must preserve matching chapter paths and order. The English
Technical Report has its own summary and introduction under
`docs/book/src/report/`. Keep workflow instructions in the manual, and model,
implementation, and validation contracts in the report.

Build and test documentation through Buck2 with remote execution. The book
product README lists site, archive, print, and publication targets. Report and
manual audits check their respective chapter coverage, source references,
published scope, and media contract.

## Stable source references

Python comments can refer to a Technical Report section using a stable anchor:

```python
# pg-book: technical-report/en#grade-policy.node-output
```

Declare the matching identifier immediately after its heading:

```markdown
## Node output policy

<a id="grade-policy.node-output"></a>
```

The resolver reads Python comments rather than matching arbitrary strings.
It checks that each referenced anchor is unique in the source and present in
the generated HTML. Build the reference report with:

```sh
buck2 build --remote-only //products/perceptual-grade-book:book_refs --show-output
```

Keep identifiers stable when moving or renaming a section. Update the resolver
inputs if new source trees need report references.

## Figures and diagrams

Numerical figures use declared model sources and data. Policy diagrams are
authored in `docs/book/diagrams/` and rendered to accessible static SVGs through
the pinned D2 and browser-checking build tools. Update the figure manifest when
adding or renaming a diagram. Its declared title and description provide the
SVG's accessible name and summary.

```sh
buck2 build --remote-only //products/perceptual-grade-book/generators:assets --show-output
buck2 build --remote-only //products/perceptual-grade-book/diagrams:assets --show-output
```

Capture changes should replace the named input while retaining its semantic
role and sufficient resolution for the page and print layouts. Record color
space, application, and control settings needed to interpret a capture in its
source data. The screenshot composer and tests verify that required inputs and
compositions are present.

The books use static media. Source recordings may be retained for editing, but
animated outputs are not published in the site or print editions. Generated
outputs and provenance are produced by Buck2 and should not be copied into the
authored source tree.
