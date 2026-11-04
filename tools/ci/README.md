# GitHub CI and formatting

CI checks only `products/perceptual-grade-next-blender`, including its policy
proofs. [Lint](../../.github/workflows/lint.yml) and
[Build and badges](../../.github/workflows/build.yml) run on pushes, pull requests,
and manual dispatch. Both use the local
`setup-buck2` composite action, which installs a checksum-verified standalone
Buck2 binary and retains its bundled prelude. Release `2026-10-15` contains the
existing `2026-10-14-9a1876786f32806f6b65fc51f4c1c3077efc38a5` binary.

## Lint and local formatting

Lint checks the product's maintained Buck/Starlark files and TOML with pinned
Buildifier and Taplo versions, formats `.inv` requirements as JSON, validates its
Buck target graph, and enforces the
CI target selection. It does not run repository-wide formatting or npm/Rust
dependency freshness checks.

**Formatting does not cover Rust, Python, or other program source files.** The
maintained `BUCK`, `PACKAGE`, `.bzl`, and `.bxl` files, TOML configuration, and
`.inv` requirements under `products/perceptual-grade-next-blender` are included.
Requirements use two-space JSON indentation and a trailing newline; invalid JSON
and duplicate keys are rejected. The formatter has the same fixed product scope
when invoked locally. Files ending in `.json` are outside its scope.

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
# Apply Buck/Starlark, TOML, and .inv formatting within next-blender:
python3 tools/ci/format.py --fix
# The same formatter through Buck2:
buck2 run //tools/ci:format_fix
# Validate the CI selection separately:
python3 tools/ci/check_targets.py
```

## Product builds, proofs, and tests

[The CI selection](targets.json) builds `:verify_policies` and `:extension` and
runs 37 test suites from next-blender. These cover policy decisions, runtime
preparation, numerical and GPU behavior, packaging and installation, and native
Blender acceptance. The native suites include render preflight, continuous
slider dragging, undo, image saving, and Stack preparation. Report-generation
and experimental candidate suites are not selected.

Every selected label belongs to `products/perceptual-grade-next-blender`.
The dependency-graph guard rejects tests and proofs outside that product,
including those in `libraries/perceptual-grade-core` and
`products/perceptual-grade-blender`. The
`libraries/perceptual-grade-reference/proofs` namespace is also excluded,
including generic build rules and proof subtargets. Ordinary shared source,
resource, and toolchain dependencies may still build as prerequisites for
next-blender; their own validation targets are not run.

CI uses the `ci` stage of [the Debian runtime](../../remote_execution/docker/Dockerfile)
with local execution in a disposable checkout, without requiring private
NativeLink services. The CI container allows 65,536 open files for concurrent
processes. Its helper requires `CI_DISPOSABLE_CHECKOUT=1` and a `CI_CACHE_DIR`
outside the checkout; it changes that checkout's managed `.buckconfig` block to
local execution. Do not invoke it in an active development checkout.

## Reports and badges

Each workflow run retains its own build and test evidence. Public badges describe
the latest published manual run on the default branch, not every commit or the
full repository test suite. The badges become available
after the first default-branch manual run publishes the `ci-status` branch.
Their linked summary records the commit, timestamp, target results, and workflow
run.

Build counts come from Buck's target build report. Test counts come from actual
test-result events, not from successful compilation of test executables. Each
suite is one selected Buck test target and may contain many test cases.
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
