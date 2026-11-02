#!/usr/bin/env bash
set -euo pipefail

if command -v git >/dev/null 2>&1 && repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    :
else
    sapling_bin="${CHROMATICITY_SAPLING_BIN:-}"
    if [ -z "$sapling_bin" ]; then
        sapling_bin="$(command -v sl 2>/dev/null || true)"
    fi
    if [ -z "$sapling_bin" ] && [ -x "${HOME:-}/.local/share/sapling/sl" ]; then
        sapling_bin="${HOME}/.local/share/sapling/sl"
    fi
    if [ -z "$sapling_bin" ] || ! [ -x "$sapling_bin" ] \
        || ! repo_root="$("$sapling_bin" root 2>/dev/null)"; then
        echo "format_fix must run inside a Git or Sapling working copy" >&2
        echo "Set CHROMATICITY_SAPLING_BIN if Sapling is installed outside PATH." >&2
        exit 1
    fi
    export CHROMATICITY_SAPLING_BIN="$sapling_bin"
fi
cd "$repo_root"
cache_root="${XDG_CACHE_HOME:-${HOME:?HOME must be set}/.cache}"
tool_dir="$cache_root/chromaticity-ci-tools"
python3 tools/ci/install_tools.py --bin-dir "$tool_dir" buildifier taplo
export PATH="$tool_dir:$PATH"
exec python3 tools/ci/format.py --fix "$@"
