# Building Perceptual Grade

Buck2 builds the extension ZIP, localized DCTLs, diagram artwork, translation review CSV, static handbook, test harness, and complete source archive. Dependencies are declared in `BUCK`; generated files live in `buck-out`.

## Docker (Linux x86-64)

``` sh
docker build -t perceptual-grade .
docker run --name pg-build perceptual-grade build //:release --show-full-output
docker cp pg-build:/project/buck-out ./buck-out-docker
docker rm pg-build
```

The root Dockerfile installs Rust `nightly-2026-07-05` with rustup, then runs `cargo install --locked --git … --rev … buck2`. The exact revision is `bd5d1960828e1585d7cdfde3400e828841bd4fc9`, resolved from upstream’s `latest` pre-release tag. It is recorded with the Rust version in `buck2-toolchain.json`. The final image receives the resulting Cargo-built executable. Each build uses the Prelude bundled with that executable.

Buck2’s upstream `.cargo/config.toml` requires `--cfg tokio_unstable`. The Docker Cargo command supplies this through `RUSTFLAGS`, because `cargo install --git` does not inherit the checked-out repository’s local Cargo configuration.

The Docker image also contains C++ compilers and the system libraries needed by the pinned `bpy` wheel. Buck2 downloads pinned CPython and wheels; installation requires network access. Docker’s build cache can reuse the Cargo layer.

## Native host

Install a C++ compiler, Clang, Git, curl, and the libraries listed in the Dockerfile for your platform. Install the same toolchain and executable:

``` sh
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
  sh -s -- --default-toolchain nightly-2026-07-05 --profile minimal -y
. "$HOME/.cargo/env"
RUSTFLAGS='--cfg tokio_unstable' cargo +nightly-2026-07-05 install --locked \
  --git https://github.com/facebook/buck2.git \
  --rev bd5d1960828e1585d7cdfde3400e828841bd4fc9 buck2
buck2 build //:release --show-full-output
```

Locked Python wheels cover Linux x86-64 and macOS Apple Silicon. The host compiler and system libraries remain host dependencies. Use the Docker environment when you need the documented Linux setup. `bpy` is the headless Blender runtime used by tests; a desktop Blender installation is needed for interactive GPU checks.

## Outputs

| Target                | Product                                                |
|-----------------------|--------------------------------------------------------|
| `//:extension[zip]`   | Installable extension ZIP                              |
| `//:dctl`             | One DCTL and UI schema per locale                      |
| `//:assets`           | Both PNGs and compiled gettext catalogs                |
| `//:i18n_review[csv]` | One CSV containing every locale, including notices     |
| `//:dctl_host`        | C++ numerical fixture compiled from the generated DCTL |
| `//:ui_layout[png]`   | Optional UI layout evidence from recorded drawing      |
| `//:docs_site[html]`  | Self-contained static handbook directory               |
| `//:docs_deploy[zip]` | Site deployment ZIP, including generated downloads     |
| `//:release[source]`  | Complete source ZIP with installables and provenance   |

``` sh
buck2 build '//:extension[zip]' '//:i18n_review[csv]' --show-full-output
buck2 build //:release --build-report /tmp/grade-build.json
buck2 uquery 'allpaths(//:extension, //third_party:colour-science)'
buck2 uquery 'deps(//:release)' --output-format dot
buck2 log what-ran
```

## Source ownership

The [project structure](architecture.md) separates installed runtime code, DCTL sources, build-time generators and fixtures. `src/blender` is the package root, with Blender manifest ID `perceptual_grade`.

`tests/packaging` checks archive contents, deterministic ZIP metadata, per-file hashes, dependency-lock agreement and compiled translations. These checks use actual built products.

## Provenance and maintenance

`provenance.json` records source hashes, lock content and artifact hashes; `SHA256.json` covers release outputs. ZIP ordering, timestamps and permissions are deterministic. The DCTL host depends on the generated DCTL, while production DCTL generation is independent of the host test fixtures.

For a Buck2 update, resolve an upstream pre-release revision, read its `rust-toolchain.toml` and `.cargo/config.toml`, update `buck2-toolchain.json` and the Dockerfile, then run the build and tests. The packaging test checks that these pins agree. Prelude customization is unnecessary for this build.

Python dependency records live in `third_party/python-lock.json` and the generated `third_party/wheels.bzl`. Use `buck2 run //:lock_wheels -- --repository .` to refresh them. This is an explicit maintenance command that writes reviewable source locks. See [contributing](contributing.md) and [documentation maintenance](documentation.md) for reader-facing resources.

## Run tests

All tests run through Buck2. Follow [the building guide](building.md) for the Cargo-built Buck2 installation or Docker image. Buck2 provides the pinned interpreter, Python dependencies, generated PNGs, MO catalogs, DCTLs and C++ harness.

``` sh
# Fast numerical, DCTL and release-packaging checks.
buck2 test //... --include numerical dctl build -j 2
# Headless Blender registration, UI, scopes and native graph checks.
buck2 test //... --include blender -j 2
# Cross-implementation comparisons.
buck2 test //... --include parity -j 2
# CPU render fixtures, or the entire suite.
buck2 test //... --include renders -j 2 -- --timeout 1800
buck2 test //... -j 2 -- --timeout 1800
# Focused source/package checks.
buck2 test //:numerical_test_i18n_terms //:blender_test_extension_namespace \
  //:blender_blender_registration_test //:blender_test_ui //:packaging_artifacts
```

Docker uses the same commands after the image name:

``` sh
docker build -t perceptual-grade .
docker run --rm perceptual-grade test //... --include numerical dctl build -j 2
docker run --rm perceptual-grade test //... --include blender -j 2
```

`build_defs/test_suites.bzl` lists the fixture targets. The internal execution adapter in `tools/testing` copies each test’s declared inputs into an isolated workspace, loads `src/blender` under its installed package ID, and runs the fixture. Source files and generated inputs cannot be modified by another test. There is one environment/setup path: the Buck2 target graph.

Translation tests validate keys, formatting placeholders, compiled catalogs, native tooltip lookup and DCTL parity. Reviewed wording lives in the locale JSONs; it is not repeated as a second set of expected sentences. All discovered locales participate automatically. `//:i18n_review[csv]` produces the review document.

Packaging checks verify the contents and hashes of actual release ZIPs. Numeric fixtures retain independent reference samples, including signed values and HDR samples. These are current mathematical regression oracles, rather than saved extension-version compatibility snapshots.

For optional drawing evidence:

``` sh
buck2 build //:ui_observations '//:ui_layout[png]' --show-full-output
```

The headless tests exercise Blender’s Python runtime and CPU evaluation. They do not establish Resolve Metal/CUDA compilation or interactive viewport performance. Those checks require the corresponding desktop applications and GPU.

### Documentation checks

``` sh
buck2 test //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_site //:packaging_artifacts //:build_text_sources
buck2 build '//:docs_deploy[zip]' --show-full-output
```

The font, favicon and MOV fixtures check source replacement, format conversion and required-input failures. The documentation fixture checks the rendered site and archive: chapter coverage, local links and fragments, locally packaged runtime resources, fonts, downloads, hashes, and ZIP metadata. It also enforces the root-README-only source layout.

### Desktop acceptance

Install the built extension in desktop Blender and create a node in both Shader and Compositor editors. Open every stage and receiver page; check dragging, Esc/R, hover help, translated labels, tone selection and Color Reference.

In Compositor, compare CPU and GPU with Automatic and Full precision, including Direct updates and publication of a matching LUT during a drag. In Shader, compare both render methods on signed/HDR inputs and check Alpha. Load each generated DCTL in Resolve to check GPU compilation, reset identity, representative controls and the diagram overlay.

Record host application build, OS, GPU, precision, working space and render method with any mismatch. These desktop checks complement the headless fixtures.

## Documentation build status

The documentation redesign adds focused targets for figure inputs, screenshot replacement, native benchmark workloads and the rendered site. The current authoring environment cannot launch Buck2 because its sandbox omits `/proc/self/exe`; elevated execution is disabled. A rendered authoring preview is provided, while these final build gates remain pending on a supported host:

``` sh
buck2 build //:release '//:docs_deploy[zip]' --show-full-output
buck2 test //:documentation_inputs //:documentation_benchmark \
  //:documentation_fonts //:documentation_favicon //:documentation_demos //:documentation_site //:packaging_artifacts //:build_text_sources
```

The earlier source/build record includes numerical, DCTL, registration, UI, parity and native CPU compositor checks. Those results describe the preceding source refactor; the current control-name and documentation revision does not rerun that broad suite. Resolve GPU compilation and interactive Metal performance require desktop checks.
