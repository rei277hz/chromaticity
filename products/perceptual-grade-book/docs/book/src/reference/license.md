# License

Copyright © 2026 Rei277Hz.

## Repository source

The original source code in the development repository,
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity), is available under either the
[MIT License](https://github.com/rei277hz/chromaticity/blob/main/LICENSE-MIT)
or the [Apache License, Version 2.0](https://github.com/rei277hz/chromaticity/blob/main/LICENSE-APACHE),
at your option (`MIT OR Apache-2.0`). This includes the Blender product source,
shared libraries, web product, build tools, and DCTL. DCTL follows these root
licenses and has no additional product license.

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) is the
downstream code snapshot, currently containing the preserved Perceptual Grade
v1.23.2 code from the 2026-11-01 build, not Perceptual Grade Next. It accepts
[issues](https://github.com/rei277hz/perceptual-grade/issues),
but does not accept pull requests; submit
[pull requests to chromaticity](https://github.com/rei277hz/chromaticity/pulls).
See [Contributing](../development/contributing.md) for the repository roles.

## Blender extension distributions

The original code in each packaged Blender extension and its Corresponding
Source are additionally offered under the GNU General Public License, version 3
or any later version (`GPL-3.0-or-later`). This grant does not withdraw the MIT
or Apache-2.0 permissions for the repository source.

Each Blender product's `LICENSE` is a packaging input: it supplies the release
explanation and full GPLv3 text in the ZIP's single `LICENSE` file. It does not
replace the root source-code licenses. The ZIP does not include separate
MIT/Apache license texts or a `NOTICE.md`, and its manifest declares
`license = ["SPDX:GPL-3.0-or-later"]`.

Corresponding Source means the preferred form for modifying the release,
including the required generator inputs and build scripts for generated code.
Release downloads must identify and provide that source for the exact released
version under the additional GPL grant. General-purpose build tools and
unrelated monorepo products do not become GPL-licensed through this grant.
See [GPLv3, sections 1 and 6](https://www.gnu.org/licenses/gpl-3.0.html).

For a release, create a full monorepo source archive with `git archive` from the
committed release revision, build the extension ZIPs from a clean extraction of
that archive, and publish the source archive alongside the ZIPs. The release
listing must identify the exact commit and link to that source archive. This
preserves the generator inputs and build scripts without adding them to the
installation ZIP. A link to a changing branch is not an exact release reference.

## Assets, third-party materials, and historical downloads

The GPL grant above covers code. Original non-code assets included in Blender
extension releases are dedicated under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/), as identified in
the packaged `LICENSE`. This follows the
[Blender Extensions licensing requirements](https://extensions.blender.org/terms-of-service/).
It does not relicense third-party data, reference illustrations, fonts, or other
credited materials; their existing terms and attributions remain applicable.
See [Credits and references](credits.md).

The maintained handbook also preserves historical release downloads. The supplied
[Perceptual Grade 1.23.2 development ZIP dated 2026-11-01](../downloads/perceptual_grade-v1.23.2-20261101.zip)
replaces the original extension download; its included license applies to that
download. The archived DCTL downloads, original runtime notice, and
[historical GPL license](../downloads/licenses/perceptual-grade-LICENSE) are
preserved as published under their historical terms. This page documents the
current monorepo and extension-distribution policy; it does not rewrite those
archived files.
