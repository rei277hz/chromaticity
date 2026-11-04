# GitHub CI and formatting

There are two workflows. [Lint](../../.github/workflows/lint.yml) runs on pushes,
pull requests, and manual dispatch. [Build and badges](../../.github/workflows/build.yml)
runs only from **Actions → Build and badges → Run workflow**. Both use the local
`setup-buck2` composite action, which installs a checksum-verified standalone
Buck2 binary and retains its bundled prelude. Release `2026-10-15` contains the
existing `2026-10-14-9a1876786f32806f6b65fc51f4c1c3077efc38a5` binary.

## Lint and local formatting

Lint checks maintained Buck/Starlark files and TOML with pinned Buildifier and
Taplo versions, checks the Buck target graph, and checks npm and Rust dependency
freshness. `third_party/rust/regenerate.py --check` uses the pinned Rust/Reindeer
toolchain and locked Cargo dependencies; a cold run downloads tools/crates and
builds Reindeer. Its maintenance caches are reused across CI runs.

**Formatting does not cover Rust, Python, or other program source files.** The
maintained `BUCK`, `PACKAGE`, `.bzl`, and `.bxl` files and TOML configuration are
included, including the central Rust catalogue, Reindeer configuration, crate
fixups, and the handbook mdBook configuration. Generated Rust rules, generated web declarations, lockfiles, dependency
caches and build outputs are excluded.

On Linux x86_64, run the formatting commands locally from a Git or Sapling
working copy root.
The Buck2 fix target installs pinned Buildifier and Taplo in the user cache the first
time it runs; Python 3.11+ and network access are required for that first run. The
manual setup below also installs Buck2 and needs `zstd` if Buck2 is not already available.
The fix target finds Sapling on `PATH` or at `~/.local/share/sapling/sl`; set
`CHROMATICITY_SAPLING_BIN` when it is installed elsewhere.

```sh
python3 tools/ci/install_tools.py --bin-dir /tmp/chromaticity-ci-tools buck2 buildifier taplo
export PATH="/tmp/chromaticity-ci-tools:$PATH"
python3 tools/ci/format.py
python3 tools/ci/format.py --starlark-lint
# Apply only the supported Buck/Starlark and TOML formatting:
python3 tools/ci/format.py --fix
# The same formatter through Buck2:
buck2 run //tools/ci:format_fix
# The checks below are separate commands; the Buck2 target only applies formatting.
python3 tools/ci/check_targets.py
python3 third_party/web/update.py --check
python3 third_party/rust/regenerate.py --check
python3 -m unittest discover -s tools/ci -p 'test_*.py'
```

## Manual builds and smoke suites

The manual workflow builds the **web app and handbook** and runs the smoke
suites listed in [the CI selection](targets.json), including handbook assembly,
rendering, archive, and publisher checks. Proof targets are
under development and excluded from CI. The Blender extensions and DCTL are also
excluded because their build dependencies execute proofs; their normal packaging
gates remain intact. A dependency-graph guard rejects any selected build, test, or
Rust-maintenance toolchain that would bring proof targets back into CI.

CI uses the `ci` stage of [the Debian runtime](../../remote_execution/docker/Dockerfile)
with local execution in a disposable checkout, without requiring private
NativeLink services. This stage adds OpenSSL headers for the Reindeer bootstrap;
the CI container allows 65,536 open files for concurrent compiler processes.
Its helper deliberately requires `CI_DISPOSABLE_CHECKOUT=1`; it changes
that checkout's managed `.buckconfig` block to local execution. Do not invoke it
in an active development checkout.

## Reports and badges

Build and test counts describe the latest published manual run on the default
branch, not every commit or the full test suite. The badges become available
after the first default-branch manual run publishes the `ci-status` branch.
Their linked summary records the commit, timestamp, target results, and workflow
run.

Build counts come from Buck's target build report. Test counts come from actual
test-result events, not from successful compilation of test executables. Each
suite is one selected Buck test target and may contain many Python or Rust cases.
Synthetic download checks are excluded; skipped, failed, missing, and incomplete
results remain visible and cannot produce an all-passing badge. Reports and logs
are retained as workflow artifacts for 14 days, including when commands fail.

Only a default-branch manual run can update the public `ci-status` branch. The
final publishing job alone has repository write permission; it publishes two SVG
badges and their JSON/Markdown summary without committing to the source branch.
Older runs cannot overwrite newer published results. Cancelled runs retain the
previous published result and its original timestamp. No personal access token,
GitHub Pages site, or external badge service is required. Repository rules must
allow the workflow's `GITHUB_TOKEN` to write `ci-status`; do not protect that
generated branch with source-branch review requirements. Forks should update
the README badge URLs to their own repository.
