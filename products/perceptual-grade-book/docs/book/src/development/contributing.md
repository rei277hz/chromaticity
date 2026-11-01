# Contributing and publishing

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) is a
downstream code snapshot for distribution. It currently contains the preserved
Perceptual Grade v1.23.2 code from the 2026-11-01 build, not Perceptual Grade
Next. Report problems through its
[issue tracker](https://github.com/rei277hz/perceptual-grade/issues). It does not
accept pull requests.

Development takes place in
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity). Submit all
[pull requests there](https://github.com/rei277hz/chromaticity/pulls), including
code, documentation, and translation changes. Work from that repository's
current source and build instructions.

The technical guidance below describes the historical 1.23.2 source layout and
has not been updated for Perceptual Grade Next.

You can improve Perceptual Grade through its grading model, host integration, translations, teaching material or reproducible measurements. Start with the part you want to change and read the corresponding section below. You do not need to work on every layer to make a useful contribution.

[Code and grading model](contributing-model.md) explains how to keep the DCTL, numerical model and native graph consistent. [Localization](localization.md) covers interface catalogs and handbook translations. [Documentation and media](documentation.md) explains how to edit lessons and replace the supplied recordings, screenshots and diagrams.

[Testing and measurements](testing.md) helps you choose evidence for a change and collect workstation results. [Publishing](publishing.md) covers the final source, installable and site packages. The [build chapter](building.md) supplies the common Buck2 commands and toolchain setup.

Keep the source of each change together with the explanation and verification needed to review it. Describe the problem, the resulting behavior and how you checked it. For changes that readers or users will notice, update the relevant handbook page and the repository's RELEASES.md.
