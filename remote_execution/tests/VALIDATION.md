# Deployment verification — 2026-11-01

The deployment and all six delivery/verification builds passed. The full Linux
test run has the failures recorded below.

Runtime: NativeLink **1.8.3**, Debian 13, Linux x86_64, on a 254-CPU server.
Worker image:
`sha256:002d078c33eca34943ab14cf93f93f47187466d94cca96bad8c25ab6b90163ae`.
The effective worker configuration and image stayed unchanged through the folder
reorganization. Client selection now uses the managed root
[.buckconfig](../../.buckconfig) block through `re local` / `re remote`; execution
rules live in [toolchains/remote_execution.bzl](../../toolchains/remote_execution.bzl).

| Check | Observed result | Local evidence |
| --- | --- | --- |
| Local execution | 16 local probes, with no remote execution or cache hits | [Smoke summary](../.state/validation/20261101-163609-dca02c/summary.json) |
| Parallel remote execution | 16 remote probes; peak overlap of 14 | Same smoke summary |
| Cache reuse after cleaning the disposable checkout | 16 cache hits; every probe report unchanged | Same smoke summary |
| Six delivery/verification targets | All passed; 117 remote commands, 1 cache hit, 0 local commands | [Build summary](../.state/evidence/unrestricted-deliveries-summary.json) |
| Full Linux suite | 285 target checks passed, 13 failed; 0 build failures, infrastructure failures, or runner timeouts | [Suite summary](../.state/evidence/unrestricted-validation-summary.json) |
| Suite execution placement | All 196 real tests ran remotely: 183 passed, 13 failed. All 102 local checks were literal `true` materialization checks | [Execution records](../.state/evidence/unrestricted-tests-retry-what-ran.jsonl) |
| Builds needed by the suite | 391 remote commands, 89 cache hits, 0 local commands | Same execution records |
| Local execution during a service outage | Linear color tests passed locally with both NativeLink services stopped | [Local-mode summary](../.state/evidence/final-local-summary.json) |
| Cache persistence across service restart | Both containers recreated; 16 remote-cache hits with identical probe reports | [Restart summary](../.state/evidence/restart-cache-summary.json) |

The six root targets were `//:perceptual_grade`, `//:perceptual_grade_next`,
`//:hdr_color_picker`, `//:dctl`, `//:verify`, and `//:verify_next`.
Their build trace is `a118d8be-c7d2-403c-819f-e0b4bff882ca`.

The full suite took 16m18s, returned exit code 32, and used:

```sh
buck2 test //... --skip-incompatible-targets -- --timeout 1800
```

Its trace is `5962a959-f062-4228-aa9a-5e11fd41073a`. The prelude's `http_file`
materialization checks require local execution, so this broad command omits
`--remote-only`; the repository's real test profile requires remote execution.
The long `persistent` and `persistent_color_stages` suites passed in 11m40s and
12m02s respectively, exceeding the runner's original 600-second default.

## Remaining test failures

These are the **raw full-suite results**, including the subsequently passing
`undo_trace` rerun. Diagnostics come from the
[full log](../.state/evidence/unrestricted-tests-retry.log) and
[test exit records](../.state/evidence/unrestricted-tests-retry-test-exits.json).

| Failed target | Observed diagnostic |
| --- | --- |
| `//libraries/invariant:tests` | Solver returned `unknown` / `timeout` for `loop.first.4.first.first_prefix.preserve.0` |
| `//products/perceptual-grade-blender/tests/blender:scope_trace` | `Unknown product component: blender_runtime.execution.runtime` |
| `//products/perceptual-grade-blender/tests/blender:undo_trace` | Exit 9 during periodic stack capture, without a Python traceback; cause unresolved |
| `//products/perceptual-grade-blender/tests/blender:scope_clouds` | Expected node-only scope identities; actual identities include individual views |
| `//products/perceptual-grade-blender/tests/blender:ownership_acceptance` | Reference-retention assertions and a mismatched `save_finished_handler` |
| `//products/perceptual-grade-blender/tests/blender:warp_view` | Gesture cleanup set mismatch and scale-gesture parameter mismatch |
| `//products/perceptual-grade-blender/tests/blender:runtime` | `NoneType` has no `signature`; publication/order assertions also failed |
| `//products/perceptual-grade-blender/tests/gpu:baking` | `AttributeError: sample_image` |
| `//products/perceptual-grade-next-blender/tests:recovery` | Removed Blender `Image` reference; backing candidate unexpectedly `None` |
| `//tools/architecture/tests:components` | Import-relocation and `model.cube` assertions |
| `//products/perceptual-grade-next-blender/tests:installed_compositor_capture` | `NameError: name 'name' is not defined` inside Blender |
| `//products/perceptual-grade-next-blender/tests:native_stack` | Removed Blender `Image` reference during authored-recipe replacement |
| `//products/perceptual-grade-next-blender/tests:installed_smoke` | `Saved file has no native Next Stack owner`; child exited 1 instead of expected 99 |

An unchanged, focused remote rerun of `undo_trace` passed all 25 cases in 12.1s;
see its [rerun log](../.state/evidence/unrestricted-undo-trace-rerun.log). This
does not change the full-suite counts above. Worker inspection found healthy
status, zero restarts, and no recorded cgroup OOM event.

Only `scope_trace` and `scope_clouds` were reproduced with explicit local
execution; see the [local comparison](../.state/evidence/local-baseline-tests-summary.json).
The solver timeout is an application query limit, distinct from the 1800-second
test-runner deadline.

A first attempt encountered 34 client-side HTTP download failures with TLS
handshake EOF errors. Repeating the same command without configuration changes
cleared those download errors; the table reports the completed retry. The
[initial attempt summary](../.state/evidence/unrestricted-tests-summary.json)
is retained. Raw logs and machine-readable evidence under `.state/` are local
artifacts ignored by Git.
