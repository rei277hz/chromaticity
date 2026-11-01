#!/bin/bash
# Keep the complete exported macOS bundle together. No Blender restart needed.
set -u
umask 077
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
    printf '%s\n' \
      'Usage: bash pg_undo_trace_macos.command [Blender.app-or-executable [project.blend]]' \
      'Runs disposable LLDB/allocation/Blender preflight, then opens your project.' \
      'Automatically captures the first native fault, packs a ZIP, and keeps Blender paused.' \
      'Requires Apple Command Line Tools. Keep all files in the exported bundle together.'
    exit 0
fi
if [[ $# -gt 2 ]]; then
    printf '%s\n' 'Expected a Blender app/executable and optional project.' >&2
    exit 2
fi
if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' 'This native LLDB capture launcher is for macOS only.' >&2
    exit 2
fi
pg_tools="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
pg_blender="${1:-/Applications/Blender.app}"
if [[ -d "$pg_blender" ]]; then pg_blender="$pg_blender/Contents/MacOS/Blender"; fi
if [[ ! -x "$pg_blender" ]]; then
    printf 'Blender executable was not found or is not executable: %s\n' "$pg_blender" >&2
    exit 2
fi
pg_blender_dir="$(cd -- "$(dirname -- "$pg_blender")" && pwd -P)" || exit 1
pg_blender="$pg_blender_dir/$(basename -- "$pg_blender")"
pg_project=''
if [[ $# -eq 2 ]]; then
    if [[ ! -f "$2" ]]; then printf 'Project was not found: %s\n' "$2" >&2; exit 2; fi
    pg_project_dir="$(cd -- "$(dirname -- "$2")" && pwd -P)" || exit 1
    pg_project="$pg_project_dir/$(basename -- "$2")"
fi
for pg_file in pg_undo_trace.py pg_undo_trace_lldb.py pg_undo_trace_native.py \
    pg_undo_trace_collect.py pg_undo_trace_canary.py pg_undo_trace_alloc_canary.c; do
    if [[ ! -f "$pg_tools/$pg_file" ]]; then
        printf 'Incomplete bundle; missing %s\n' "$pg_tools/$pg_file" >&2
        exit 2
    fi
done
pg_lldb="$(xcrun --find lldb 2>/dev/null)" || {
    printf '%s\n' 'Apple LLDB unavailable. Install Apple Command Line Tools, then rerun.' >&2
    exit 2
}
pg_python="$(xcrun --find python3 2>/dev/null)" || {
    printf '%s\n' 'Apple Command Line Tools Python 3 unavailable.' >&2
    exit 2
}
for pg_tool in /usr/bin/malloc_history /usr/bin/leaks; do
    if [[ ! -x "$pg_tool" ]]; then printf 'Required native tool unavailable: %s\n' "$pg_tool" >&2; exit 2; fi
done
pg_desktop="$HOME/Desktop"
mkdir -p -- "$pg_desktop" || exit 1
pg_session="$(mktemp -d "$pg_desktop/perceptual-grade-native-trace-$(date +%Y%m%d-%H%M%S)-XXXXXX")" || exit 1
# Configuration is passed as arguments and JSON; no user path is executable LLDB text.
"$pg_python" - "$pg_session" "$pg_blender" "$pg_project" "$pg_tools" "$pg_lldb" <<'PY'
import datetime, json, os, pathlib, sys, uuid
root, blender, project, tools, lldb = sys.argv[1:]
root = pathlib.Path(root)
launch_id = str(uuid.uuid4())
config = dict(blender=blender, project_args=[project] if project else [], tools=tools, lldb=lldb)
session = dict(schema=1, launch_id=launch_id, status='preflight',
               started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               launcher_pid=os.getppid(), blender_pid=None,
               mandatory_artifacts=['session.json', 'config.json', 'launcher.txt', 'preflight.json', 'native-events.jsonl'],
               causal_evidence=dict(publication=False, undo_decision=False, free_stack=False, surviving_link=False))
for name, value in [('config.json', config), ('session.json', session)]:
    (root / name).write_text(json.dumps(value, indent=2) + '\n')
(root / 'launcher.txt').write_text('Perceptual Grade LLDB launcher v2\n' + json.dumps(config, indent=2) + '\n')
# LLDB command parser supports quoted arguments; escape quotes/backslashes only.
module = str(pathlib.Path(tools) / 'pg_undo_trace_lldb.py')
quoted = '"' + module.replace('\\', '\\\\').replace('"', '\\"') + '"'
(root / 'commands.lldb').write_text('command script import ' + quoted + '\npg-undo-run\n')
PY
pg_config_status=$?
if [[ $pg_config_status -ne 0 ]]; then exit "$pg_config_status"; fi
printf 'Native diagnostics: %s\nRunning preflight; keep this Terminal window open.\n' "$pg_session"
# No allocator settings on LLDB itself. The adapter applies them only to targets.
env -u MallocStackLogging -u MallocStackLoggingNoCompact -u MallocStackLoggingDirectory \
    PG_UNDO_TRACE_SESSION_DIR="$pg_session" PG_UNDO_TRACE_TOOLS_DIR="$pg_tools" \
    "$pg_lldb" --no-lldbinit --source "$pg_session/commands.lldb"
pg_status=$?
printf 'LLDB exited with status %s. Original evidence: %s\n' "$pg_status" "$pg_session"
printf 'To pack again: bash %q %q\n' "$pg_tools/pg_undo_trace_pack.command" "$pg_session"
exit "$pg_status"
