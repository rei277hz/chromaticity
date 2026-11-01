# Perceptual Grade macOS native undo capture

Run in Terminal, keeping the extracted bundle files together:

```sh
bash pg_undo_trace_macos.command ~/Applications/Blender.app ~/Desktop/project.blend
```

The launcher runs disposable preflight checks first. It requires Apple's Command
Line Tools (`xcrun lldb`, `clang`), debugger permission, `malloc_history`, and
`leaks`. It changes no signing or system security settings. The current native
adapter supports the affected ARM64 Blender 5.2.2 build `d13f752e3b9c`, Mach-O UUID
`43861983-96de-3588-8491-260b05dcc486`. Other binaries fail preflight explicitly.
The disposable `canary` deliberately raises SIGSEGV to check debugger stopping;
this is expected during preflight. Its live and memory-graph checks require the
7,137-byte allocation and free records to contain `pg_canary_allocate` stack
frames. `preflight-allocation/live-check.json` and `graph-check.json` record the
results. Apple address/module/symbol frames without offsets are supported;
older lifetimes at a reused address do not satisfy the canary check.

If preflight succeeds, reproduce reset/undo/redo in the newly opened Blender.
Keep live LUT publication and viewport evaluation enabled. The first native fault
stops Blender automatically. The tool saves native stacks, registers, relevant
links, undo logs, and allocation/free histories while the process remains alive,
then creates a ZIP on the Desktop. Blender remains paused; type `quit` at the
capture prompt when finished. Do not close the Terminal until capture completes.
If packaging fails, the original evidence directory is printed and Blender stays
paused. Correct the reported problem, then type `pack` to retry.

If preflight fails, send the generated report ZIP. It says which capability was
unavailable; it is not a complete crash reproduction. Each launch directory
contains `launch.json`, recording the requested executable, arguments and
diagnostic settings before launch, followed by LLDB's returned error and process
state. A failure before the expected stop also records `wait-stop-failure.json`
with the actual state, exit status, exit description and process description.
`native-events.jsonl` includes bounded process events with their originating PID
and debugger process identity. A new listener is used for each target, and the
process state is saved before disposable-target cleanup. These records preserve
debugger evidence; a negative exit status alone does not identify its cause.

Large histories and native
breakpoints affect timing. Allocation history is attempted for implicated Images;
full-stack-history memgraph fallback has a 180-second timeout. Capture progress
is printed before external tools run. Logs and memory graphs may contain project
paths or memory metadata. Originals are preserved.

To package a session again without restarting Blender:

```sh
bash pg_undo_trace_pack.command ~/Desktop/perceptual-grade-native-trace-SESSION
```

An intact archive and a complete causal explanation are separate outcomes. Check
`collection.json` and `fault/summary.json`: missing hooks, unreadable memory,
missing/free-stack evidence, timeouts, or file changes remain explicit. ID payload
cleanup events are not proof that an allocation was freed. Native `malloc_history`
records supply the allocation/free stack evidence.
The implicated old Image is queried first. A different Image's freed allocation
cannot substitute for that history; missing stack records trigger the graph
fallback and remain explicit in the report.

The standalone `pg_undo_trace.py` still supports Text Editor record/stop/collect.
Version 4 records operation locations and boundaries without inspecting arbitrary
locals, returned wrappers, or exception contents. A Text Editor script alone
cannot retroactively enable allocation history or install the external debugger.

Build downloadable bundle: `buck2 build '//:pg_undo_trace_macos_zip[zip]' --show-output`.
Native macOS preflight and real reset/undo/redo acceptance must run on the Mac;
Linux unit tests validate orchestration, not Apple debugger/allocator behavior.

If Blender preflight reports `attach failed (Not allowed to attach to process)`,
run the read-only permission collector from Terminal:

```sh
bash pg_undo_trace_permissions_macos.command ~/Applications/Blender.app
```

It records Blender, LLDB and debugserver signatures/entitlements, Developer
Tools authorization status, Gatekeeper assessment, and a bounded unified-log
query. Its default log interval is 2026-10-18 13:42:40–13:43:20 local time;
use `--last 10m` for a more recent failure. Results go in a new Desktop folder
and a ZIP beside it. If `xcrun` does not locate debugserver, the script checks
common LLDB private-framework locations and labels any results as candidates.
No signing, permission, SIP or Developer Tools setting is changed. Review
`commands.tsv` and the collected output before sharing the ZIP.

The fallback profile derives from the exact build's `RNA_types.hh`, `DNA_ID.h`,
and `DNA_node_types.h`: PointerRNA owner/data offsets 0/16, bNode name/id offsets
48/216, and ID name/session_uid offsets 40/324. ID.name has 258 bytes in this
build. Source-prefix ARM64 static assertions and a C++ by-value argument fixture
confirm the source layout/ABI: x0 is the source PointerRNA pointer, x1 points to
the by-value replacement PointerRNA, and x2 is reports. The native preflight
checks these fields against known fresh objects; source validation alone does
not establish compatibility with the installed executable.
