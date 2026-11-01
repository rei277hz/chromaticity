#!/bin/bash
# Read-only macOS debugger-authorization evidence collector.
# Does not modify signatures, entitlements, permissions, SIP, or Developer Tools.
set -u
set -o pipefail
umask 077

if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    cat <<'HELP'
Usage:
  bash pg_undo_trace_permissions_macos.command [Blender.app-or-executable]
      [output-directory] [--start 'YYYY-MM-DD HH:MM:SS' --end 'YYYY-MM-DD HH:MM:SS']
      [--last duration]

Checks Blender, LLDB and debugserver code signatures/entitlements, Developer
Tools authorization status, Gatekeeper assessment, and bounded macOS unified
logs. The default interval is the 2026-10-18 13:42:40–13:43:20 local-time
window from the reported failure. Use --last 10m for a recent failure instead.
Creates a new evidence directory and ZIP on the Desktop (or at output-directory).
HELP
    exit 0
fi
if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' 'This read-only evidence collector is for macOS only.' >&2
    exit 2
fi

pg_blender_arg="$HOME/Applications/Blender.app"
if [[ $# -gt 0 && "$1" != --* ]]; then
    pg_blender_arg="$1"
    shift
fi
pg_output_arg=''
if [[ $# -gt 0 && "$1" != --* ]]; then
    pg_output_arg="$1"
    shift
fi
pg_log_start='2026-10-18 13:42:40'
pg_log_end='2026-10-18 13:43:20'
pg_log_last=''
while [[ $# -gt 0 ]]; do
    case "$1" in
        --start)
            [[ $# -ge 2 ]] || { printf '%s\n' 'Missing --start value.' >&2; exit 2; }
            pg_log_start="$2"; shift 2 ;;
        --end)
            [[ $# -ge 2 ]] || { printf '%s\n' 'Missing --end value.' >&2; exit 2; }
            pg_log_end="$2"; shift 2 ;;
        --last)
            [[ $# -ge 2 ]] || { printf '%s\n' 'Missing --last value.' >&2; exit 2; }
            pg_log_last="$2"; shift 2 ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            exit 2 ;;
    esac
done

if [[ -d "$pg_blender_arg" ]]; then
    pg_blender_app="$(cd -- "$pg_blender_arg" && pwd -P)" || exit 1
    pg_blender_exe="$pg_blender_app/Contents/MacOS/Blender"
else
    pg_blender_exe="$(cd -- "$(dirname -- "$pg_blender_arg")" && pwd -P)/$(basename -- "$pg_blender_arg")" || exit 1
    pg_blender_app=''
fi
if [[ ! -e "$pg_blender_exe" ]]; then
    printf 'Blender executable was not found: %s\n' "$pg_blender_exe" >&2
    exit 2
fi

if [[ -n "$pg_output_arg" ]]; then
    mkdir -- "$pg_output_arg" || exit 1
    pg_output="$(cd -- "$pg_output_arg" && pwd -P)" || exit 1
else
    mkdir -p -- "$HOME/Desktop" || exit 1
    pg_output="$(mktemp -d "$HOME/Desktop/perceptual-grade-permission-check-$(date +%Y%m%d-%H%M%S)-XXXXXX")" || exit 1
fi

pg_status_file="$pg_output/commands.tsv"
printf 'exit_status\toutput_file\tcommand\n' > "$pg_status_file"

pg_record_command() {
    local pg_file="$1"
    shift
    local pg_status=0
    local pg_rendered
    pg_rendered="$(printf '%q ' "$@")"
    "$@" > "$pg_output/$pg_file" 2>&1 || pg_status=$?
    printf '%s\t%s\t%s\n' "$pg_status" "$pg_file" "$pg_rendered" >> "$pg_status_file"
    return 0
}

pg_record_command macos-version.txt /usr/bin/sw_vers
pg_record_command developer-directory.txt /usr/bin/xcode-select -p
pg_record_command developer-tools-security.txt /usr/sbin/DevToolsSecurity -status
pg_record_command developer-group-membership.txt /usr/sbin/dseditgroup -o checkmember -m "${USER:-$(/usr/bin/id -un)}" _developer
pg_record_command current-user-groups.txt /usr/bin/id -Gn

pg_signature_target="$pg_blender_exe"
if [[ -n "$pg_blender_app" ]]; then pg_signature_target="$pg_blender_app"; fi
pg_record_command blender-app-codesign.txt /usr/bin/codesign -dv --verbose=4 "$pg_signature_target"
pg_record_command blender-app-entitlements.txt /usr/bin/codesign -d --entitlements :- "$pg_signature_target"
pg_record_command blender-executable-codesign.txt /usr/bin/codesign -dv --verbose=4 "$pg_blender_exe"
pg_record_command blender-executable-entitlements.txt /usr/bin/codesign -d --entitlements :- "$pg_blender_exe"
pg_record_command blender-gatekeeper.txt /usr/sbin/spctl --assess --type execute --verbose=4 "$pg_signature_target"

pg_lldb=''
pg_debugserver=''
if [[ -x /usr/bin/xcrun ]]; then
    pg_record_command lldb-path.txt /usr/bin/xcrun --find lldb
    pg_record_command debugserver-path.txt /usr/bin/xcrun --find debugserver
    pg_lldb="$(/usr/bin/xcrun --find lldb 2>/dev/null || true)"
    pg_debugserver="$(/usr/bin/xcrun --find debugserver 2>/dev/null || true)"
else
    printf '%s\n' 'xcrun is unavailable' > "$pg_output/lldb-path.txt"
    printf '%s\n' 'xcrun is unavailable' > "$pg_output/debugserver-path.txt"
    printf '127\tlldb-path.txt\txcrun unavailable\n127\tdebugserver-path.txt\txcrun unavailable\n' >> "$pg_status_file"
fi
if [[ -n "$pg_lldb" && -e "$pg_lldb" ]]; then
    pg_record_command lldb-codesign.txt /usr/bin/codesign -dv --verbose=4 "$pg_lldb"
    pg_record_command lldb-entitlements.txt /usr/bin/codesign -d --entitlements :- "$pg_lldb"
fi
if [[ -n "$pg_debugserver" && -e "$pg_debugserver" ]]; then
    pg_record_command debugserver-codesign.txt /usr/bin/codesign -dv --verbose=4 "$pg_debugserver"
    pg_record_command debugserver-entitlements.txt /usr/bin/codesign -d --entitlements :- "$pg_debugserver"
else
    # LLDB's private helper is not always exposed as an xcrun tool. Inspect
    # bounded candidates without claiming that a candidate was used in the run.
    pg_developer_dir="$(/usr/bin/xcode-select -p 2>/dev/null || true)"
    pg_candidate_index=0
    for pg_candidate in \
        "$pg_developer_dir/Library/PrivateFrameworks/LLDB.framework/Resources/debugserver" \
        "$pg_developer_dir/../SharedFrameworks/LLDB.framework/Resources/debugserver" \
        '/Library/Developer/CommandLineTools/Library/PrivateFrameworks/LLDB.framework/Resources/debugserver'; do
        if [[ -f "$pg_candidate" ]]; then
            pg_candidate_index=$((pg_candidate_index + 1))
            printf '%s\n' "$pg_candidate" >> "$pg_output/debugserver-candidates.txt"
            pg_record_command "debugserver-candidate-$pg_candidate_index-codesign.txt" /usr/bin/codesign -dv --verbose=4 "$pg_candidate"
            pg_record_command "debugserver-candidate-$pg_candidate_index-entitlements.txt" /usr/bin/codesign -d --entitlements :- "$pg_candidate"
        fi
    done
fi

pg_predicate='(process == "debugserver" OR process == "taskgated" OR process == "taskgated-helper" OR process == "amfid" OR process == "syspolicyd" OR process == "sandboxd" OR process == "tccd" OR eventMessage CONTAINS[c] "Not allowed to attach" OR eventMessage CONTAINS[c] "task_for_pid" OR eventMessage CONTAINS[c] "debugserver")'
if [[ -n "$pg_log_last" ]]; then
    pg_record_command unified-log.txt /usr/bin/log show --style compact --info --debug --last "$pg_log_last" --predicate "$pg_predicate"
else
    pg_record_command unified-log.txt /usr/bin/log show --style compact --info --debug --start "$pg_log_start" --end "$pg_log_end" --predicate "$pg_predicate"
fi

cat > "$pg_output/README.txt" <<HELP
Read-only Perceptual Grade macOS debugger-authorization evidence

Blender executable: $pg_blender_exe
Blender app: $pg_blender_app
Log interval: ${pg_log_last:---start $pg_log_start --end $pg_log_end}

This directory contains code-signing metadata, entitlements, Gatekeeper output,
Developer Tools authorization status, tool paths, and a bounded unified-log
query. Machine paths and signing identifiers may be present. No signatures,
entitlements, permissions, SIP settings, or processes were changed.

commands.tsv records every command's exit status and output file. Nonzero
statuses are preserved as evidence; collection continues when a check is
unavailable. A discovered debugserver candidate is not proof of the helper
actually used by the failed debugger launch.
HELP

printf 'Permission evidence: %s\n' "$pg_output"
pg_archive="$pg_output.zip"
if [[ -e "$pg_archive" ]]; then
    printf 'Archive already exists; evidence remains in %s\n' "$pg_output" >&2
    exit 1
fi
if /usr/bin/ditto -c -k --keepParent "$pg_output" "$pg_archive"; then
    printf 'Report ZIP: %s\n' "$pg_archive"
else
    printf 'ZIP creation failed. Evidence remains in %s\n' "$pg_output" >&2
    exit 1
fi
exit 0
