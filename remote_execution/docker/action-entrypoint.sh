#!/bin/sh
# NativeLink removes this action directory, including these caches, afterwards.
set -eu
: "${NL_ACTION_DIRECTORY:?NativeLink must supply the action directory}"
export HOME="$NL_ACTION_DIRECTORY/home"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_RUNTIME_DIR="$HOME/.runtime"
export TMPDIR="$NL_ACTION_DIRECTORY/tmp"
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_RUNTIME_DIR" "$TMPDIR"
chmod 700 "$XDG_RUNTIME_DIR"

exec "$@"
