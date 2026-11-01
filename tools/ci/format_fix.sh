#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
cache_root="${XDG_CACHE_HOME:-${HOME:?HOME must be set}/.cache}"
tool_dir="$cache_root/chromaticity-ci-tools"
python3 tools/ci/install_tools.py --bin-dir "$tool_dir" buildifier taplo
export PATH="$tool_dir:$PATH"
exec python3 tools/ci/format.py --fix "$@"
