#!/bin/bash
# Pack the existing 2026-10-18 / PID 44389 evidence. Does not launch Blender.
# Usage: bash pg_undo_trace_pack_44389.command [Desktop-or-evidence-directory]
set -euo pipefail
umask 077

if [[ $# -gt 1 ]]; then
    printf '%s\n' 'Usage: bash pg_undo_trace_pack_44389.command [evidence-directory]' >&2
    exit 2
fi
pg_desktop="${1:-$HOME/Desktop}"
pg_desktop="$(cd -- "$pg_desktop" && pwd -P)"
pg_native='perceptual-grade-native-trace-20261018-025605-vYpqPZ'
pg_first='perceptual-grade-undo-trace-20261018-025608-44389-1792263368053659000'
pg_main="$pg_native/stack-logs.44389.10c9d8000.Blender.Rghxeg.index"

if [[ ! -f "$pg_desktop/$pg_main" || ! -s "$pg_desktop/$pg_main" || -L "$pg_desktop/$pg_main" ]]; then
    printf 'The required main-process allocation log is missing, empty, or a link:\n%s\n' \
        "$pg_desktop/$pg_main" >&2
    printf '%s\n' 'No archive was created. Keep the original evidence folders.' >&2
    exit 1
fi
for pg_tool in zip unzip; do
    if ! command -v "$pg_tool" >/dev/null 2>&1; then
        printf 'Required tool not found: %s\n' "$pg_tool" >&2
        exit 1
    fi
done

pg_inputs=("$pg_native")
pg_note='The earlier recorder folder is included.'
if [[ -d "$pg_desktop/$pg_first" && ! -L "$pg_desktop/$pg_first" ]]; then
    pg_inputs+=("$pg_first")
else
    pg_note='The earlier recorder folder was not found; the complete native directory is included.'
    printf '%s\n' "$pg_note"
fi

pg_work="$(mktemp -d "$pg_desktop/.pg-undo-pack-44389.XXXXXX")"
cleanup() {
    rm -f "$pg_work/report.zip" "$pg_work/PACKING.txt" "$pg_work/members.txt"
    rmdir "$pg_work" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

pg_output="$pg_desktop/perceptual-grade-extra-44389-$(date +%Y%m%d-%H%M%S)-${pg_work##*.}.zip"
{
    printf '%s\n' 'Supplementary evidence for Blender PID 44389, 2026-10-18.'
    printf 'Packed from: %s\n' "$pg_desktop"
    printf 'Required allocation log: %s\n' "$pg_main"
    printf '%s\n' "$pg_note" 'No per-file or total-size exclusion is applied.'
    printf 'Included source folder: %s\n' "${pg_inputs[@]}"
} > "$pg_work/PACKING.txt"

printf '%s\n' 'Packing the original logs, including the large main-process allocation file.' \
    'Compression and verification may take a few minutes.'
(
    cd "$pg_desktop"
    zip -q -r -y -MM "$pg_work/report.zip" "${pg_inputs[@]}"
)
(
    cd -- "$pg_work"
    zip -q report.zip PACKING.txt
)
unzip -tq "$pg_work/report.zip"
unzip -Z1 "$pg_work/report.zip" > "$pg_work/members.txt"
if ! grep -Fqx "$pg_main" "$pg_work/members.txt"; then
    printf '%s\n' 'Verification failed: the required allocation log is absent.' >&2
    exit 1
fi
if [[ ${#pg_inputs[@]} -gt 1 ]] && ! grep -Fqx "$pg_first/" "$pg_work/members.txt"; then
    printf '%s\n' 'Verification failed: the earlier recorder folder is absent.' >&2
    exit 1
fi
if [[ -e "$pg_output" ]]; then
    printf 'Output already exists; refusing to overwrite: %s\n' "$pg_output" >&2
    exit 1
fi
mv -n "$pg_work/report.zip" "$pg_output"
if [[ -e "$pg_work/report.zip" ]]; then
    printf '%s\n' 'Could not publish the archive without overwriting another file.' >&2
    exit 1
fi
printf '\nSend this ZIP:\n%s\n\n%s\n' "$pg_output" \
    'Your original evidence folders have been preserved.'
