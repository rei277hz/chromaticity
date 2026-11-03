# Remote execution validation

Run these commands from the repository root after starting the deployment with
`./remote_execution/re up`. The [deployment guide](../README.md) covers setup and
[Buck client configuration](../README.md#buck-client-configuration) in the
checked-in root `.buckconfig`. Builds and tests use NativeLink by default;
`re up` updates its managed NativeLink block with a reachable hostname, remote
platform, and worker image ID. Validation tests local and remote execution in its
own disposable checkout without changing the live checkout's execution mode.
When moving between host and container clients, run `re remote` in the client
environment before running Buck so the selected name is reachable there.

The isolated CLI regression suite needs neither Docker nor a live network:

```sh
buck2 test //remote_execution/tests:cli --remote-only
```

It covers Docker service-name selection, the host's `localhost` fallback,
selection based on the current process despite saved workspace metadata,
migration of saved bridge IPs, numeric-address rejection, and readiness checks
against the expected worker image.

```sh
# Verify local and remote execution, concurrency, isolation, and remote cache reuse.
./remote_execution/re validate

# Also build repository delivery targets and run compatible Linux tests.
./remote_execution/re validate --full

# Override the full run's per-test timeout, in seconds (default: 1800).
./remote_execution/re validate --full --test-timeout 1800
```

## Integration probe

[probe.py](probe.py) runs as 16 independent Buck actions declared in [BUCK](BUCK).
The public `//remote_execution:smoke` target aliases this group. Each probe uses
the Buck-provided Python interpreter, invokes system tools (`gcc`, `g++`, `nm`,
and `tar`), reads and writes temporary data, and records execution times,
worker identity, writable home, temporary directory, and runtime versions.
The local phase requires those system tools on the client's `PATH`; the remote
phase uses the worker image's tools.

Every `re validate` invocation creates a fresh nonce and a disposable source
checkout outside the live repository. The CLI verifies that Buck recognizes that
checkout as a separate project, then runs three stages:

1. Select local execution in the copy's root `.buckconfig` and build all 16
   probes with `--local-only`. Require 16 local probe executions, no remote
   executions or cache hits, and probe working directories inside the disposable
   client checkout.
2. Clean the disposable checkout's Buck state, reset its daemon, and configure
   its managed NativeLink block for the deployed endpoint and worker image.
   Build all 16 probes with `--remote-only`; require 16 remote probe executions
   and no local probe executions. Read the reports and require at least two
   overlapping actions, 16 distinct writable home directories, and execution
   inside the worker's action directory.
3. Clean only the disposable checkout's Buck state and repeat the remote build.
   Require 16 remote-cache hits, no new remote probe executions, and exactly
   unchanged probe outputs.

Both remote builds retain the same Buck isolation-directory name so their action
paths and cache keys match. The final build therefore checks the remote action
cache without relying on earlier local incremental state. The live checkout's
configuration and execution mode remain unchanged, and its `buck-out` is never
cleaned. These checks demonstrate local execution, remote execution, concurrency,
and remote cache reuse; they do not impose resource reservations, thread limits,
or a maximum workload.

## Repository acceptance targets

[validation-targets.json](validation-targets.json) is used only by
`re validate --full`. Its `build` list selects the repository's seven delivery and
verification aggregates; its `test` list currently selects `//...`.
The manifest defines validation coverage, not a workload allowlist. Any compatible
Buck action can use the deployment. Update the manifest as repository acceptance
coverage changes. A blanket `buck2 build //...` also selects diagnostic and
benchmark generators, so the full validation command uses named aggregates.

The test invocation skips incompatible targets and includes Linux software
rendering and headless Blender tests. Linux software rendering does not certify
physical GPU, HDR display, or macOS/Metal acceptance; those require their
respective environments. Build failures, product assertions, proof failures, and
test timeouts remain failures even when the infrastructure probe passes; service
health alone does not establish product correctness. An infrastructure migration
must not weaken existing numerical or workflow assertions to obtain a green run.
A solver time-budget increase changes available computation, not the required
proof or mutation-detection obligations.

The bundled prelude's `http_file` rules expose synthetic local `true` tests that
materialize downloaded artifacts. A blanket `--remote-only` rejects those
bookkeeping checks, so the full test invocation omits that flag. Actual Python
tests use the remote-only executor profile. Inspect `buck2 log what-ran` records
for `reason: "test.run"` and the `Re` executor to verify where those tests ran.
Targeted real tests can use `--remote-only`.

Run real tests directly using the root `.buckconfig` defaults:

```sh
buck2 test //libraries/color-core/tests:linear --remote-only
buck2 test //... --skip-incompatible-targets -- --timeout 1800
buck2 log what-ran --format json --emit-cache-queries
```

`buck2 log what-failed` shows failures. Building a test executable remotely does
not establish where its test process ran; inspect the execution log.

For a local comparison, switch the root configuration and run the affected test
without `--remote-only`. Run each `buck2 kill` only after the checkout's active
Buck commands have finished:

```sh
./remote_execution/re local
buck2 kill
buck2 test //libraries/color-core/tests:linear

./remote_execution/re remote
buck2 kill
```

Both switches edit only the root `.buckconfig` block between
`# BEGIN NativeLink settings (managed by remote_execution/re)` and
`# END NativeLink settings`, preserving other sections. `re local` removes remote
client addresses and selects the local platform with remote execution disabled;
it requires neither Docker nor saved deployment state. `re remote` requires a
ready worker and selects a reachable hostname using the saved deployment's image
ID. It migrates older saved IP endpoints. `re up` also selects remote execution.
The CLI reminds you to restart the idle Buck
daemon after an endpoint or mode change so it reads the new settings.
Platform rules and the Python-test executor profile live in
`toolchains/remote_execution.bzl`.

The test runner's timeout is in seconds and controls each test process; it does
not change solver budgets or product assertions. The runner defaults to 600
seconds, while `re validate --full` supplies 1800 seconds for longer
software-rendering suites.

## Evidence

See [VALIDATION.md](VALIDATION.md) for the recorded deployment run and its
remaining repository test failures.

After deployment readiness passes, each invocation retains evidence under
`remote_execution/.state/validation/<timestamp>-<id>/`, including failures:

| Artifact | Contents |
| --- | --- |
| `summary.json` | Deployment identity, disposable checkout path, measured overlap, execution/cache counts, exit codes, and any validation error. |
| `local.log`, `cold.log`, `warm.log` | Probe build output for local execution, fresh remote execution, and remote cache reuse. |
| `local-build.json`, `cold-build.json`, `warm-build.json` | Buck build reports for the three stages. |
| `local-actions.jsonl`, `cold-actions.jsonl`, `warm-actions.jsonl` | Buck execution records, including cache queries. |
| `local-probes.json` | The 16 local execution reports used to verify execution inside the disposable client checkout. |
| `probes.json` | The 16 worker execution reports used for isolation and overlap checks. |
| `deliveries.log`, `tests.log` | Repository build/test output when `--full` is requested. |

Artifacts are written as their stages complete, so an early failure may leave
only part of this set. The CLI prints the evidence directory and stops the
disposable checkout's Buck daemon when validation finishes. The checkout remains
available at the path recorded in `summary.json` for inspecting materialized
outputs and Buck logs.
