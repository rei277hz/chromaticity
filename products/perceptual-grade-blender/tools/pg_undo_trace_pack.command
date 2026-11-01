#!/bin/bash
# Package one new or historical recorder/native session without launching Blender.
set -euo pipefail
umask 077
if [[ $# -ne 1 ]]; then
    printf '%s\n' 'Usage: bash pg_undo_trace_pack.command SESSION_DIRECTORY' >&2
    exit 2
fi
pg_tools="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
pg_python="${PG_UNDO_TRACE_PYTHON:-python3}"
if ! command -v "$pg_python" >/dev/null 2>&1; then
    printf '%s\n' 'Python 3 was not found. Set PG_UNDO_TRACE_PYTHON to its executable path.' >&2
    exit 2
fi
exec "$pg_python" "$pg_tools/pg_undo_trace_collect.py" "$1"
