"""Stream one diagnostic launch into a verified ZIP without requiring Blender.

Mandatory evidence has no file, byte, or entry exclusion. Optional helper logs
remain bounded. Source files are read to their initial length; concurrent changes
are reported, never mistaken for complete snapshots. No source log is deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import zipfile

OPTIONAL_LIMITS = dict(per_file_bytes=256 * 1024**2, total_bytes=512 * 1024**2, entries=2000)
CAUSAL_KEYS = ('publication', 'undo_decision', 'free_stack', 'surviving_link')
CORE_NAMES = {'session.json', 'launch.json', 'launcher.txt', 'launcher-console.log',
              'preflight.json', 'native-events.jsonl', 'native-undo.log',
              'wait-stop-failure.json', 'wait-stop-timeout.json', 'before-dispose.json',
              'capture-errors.log',
              'debugger-console.log', 'lldb-console.log'}


def _open_regular(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_NONBLOCK', 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('not a regular file')
        return os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise


def _json(path):
    """Metadata is bounded and never followed through symlinks or special files."""
    try:
        with _open_regular(path) as source:
            data = source.read(2 * 1024**2 + 1)
        if len(data) > 2 * 1024**2:
            return {}
        result = json.loads(data)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _safe_relative(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('mandatory artifact must be a relative path: ' + str(value))
    return path


def _walk(root):
    """Enumerate without following directory links; record failures explicitly."""
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    else:
                        yield path, None
        except OSError as error:
            yield directory, error


def _main_pid(manifest, metadata, native):
    value = manifest.get('blender_pid') or metadata.get('pid')
    if value:
        try:
            return int(value)
        except (ValueError, TypeError):
            pass
    if native:
        try:
            with _open_regular(native / 'launcher.txt') as source:
                match = re.search(rb'(?m)^blender_pid=(\d+)\s*$', source.read(1024**2))
            if match:
                return int(match[1])
        except (ValueError, OSError):
            pass
    return None


def _is_main_process(path, pid):
    if pid is None:
        return False
    text = str(path)
    return (re.search(r'(?:stack-logs\.|process-|pid-)' + str(pid) + r'(?:[./-]|$)', text)
            is not None)


def _session_context(directory):
    directory = Path(directory).expanduser().absolute()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Session directory is missing or a symlink: ' + str(directory))
    directory = directory.resolve()
    metadata = _json(directory / 'metadata.json')
    native_value = metadata.get('native_session_dir')
    native = Path(native_value).expanduser().absolute() if native_value else None
    if (directory / 'session.json').is_file():
        native = directory
    manifest_path = native / 'session.json' if native else None
    manifest = _json(manifest_path) if manifest_path else {}
    manifest_status = ('valid-schema-1' if manifest.get('schema') == 1 else
                       'unsupported-schema' if manifest else
                       'missing-or-invalid' if manifest_path and manifest_path.exists() else 'missing')
    if manifest and native and native.is_dir() and not native.is_symlink():
        # All entry points to a modern launch produce the same launch archive.
        directory = native.resolve()
    elif not metadata:
        raise ValueError('Expected session.json or metadata.json in ' + str(directory))
    return directory, native, manifest, metadata, manifest_status


def _recordings(directory, native, manifest, metadata):
    recordings = {}
    requested = []
    launch_id = manifest.get('launch_id') or metadata.get('launch_id')

    def accept(path, explicit=False):
        path = Path(path).expanduser().absolute()
        if path.is_symlink():
            return
        data = _json(path / 'metadata.json')
        if not data:
            if explicit:
                requested.append(dict(source=str(path), status='missing-recorder-session', mandatory=True))
            return
        association = data.get('native_session_dir')
        if launch_id:
            matches = data.get('launch_id') == launch_id
        else:
            matches = bool(native and association and Path(association).expanduser().absolute() == native)
        if path == directory and metadata:
            matches = True
        if matches:
            recordings[path.resolve()] = data
        elif explicit:
            requested.append(dict(source=str(path), status='recorder-launch-mismatch', mandatory=True))

    if metadata:
        accept(directory if (directory / 'metadata.json').is_file() else Path(metadata.get('directory', directory)))
    if native and not native.is_symlink() and native.is_dir():
        for entry in manifest.get('recorder_sessions', []):
            if isinstance(entry, str):
                path = Path(entry)
                accept(path if path.is_absolute() else native / path, explicit=True)
        python_root = native / 'python'
        if python_root.is_dir() and not python_root.is_symlink():
            for child in python_root.iterdir():
                if child.is_dir() and not child.is_symlink():
                    accept(child)
    return recordings, requested


def _native_reports(recordings):
    seen = set()
    for directory, metadata in recordings.items():
        start = metadata.get('started_epoch', 0)
        writes = []
        for name in ('events.jsonl', 'fatal-python.txt', 'periodic-python.txt', 'console.log'):
            path = directory / name
            try:
                if not path.is_symlink() and stat.S_ISREG(path.stat().st_mode):
                    writes.append(path.stat().st_mtime)
            except OSError:
                pass  # Missing recorder files are already mandatory artifact gaps.
        cutoff = min(time.time(), max(writes, default=start) + 600)
        roots = {Path('/tmp'), Path.home() / 'Library/Logs/DiagnosticReports',
                 Path('/Library/Logs/DiagnosticReports')}
        if metadata.get('blender_tempdir'):
            roots.update((Path(metadata['blender_tempdir']), Path(metadata['blender_tempdir']).parent))
        if metadata.get('blend_filepath'):
            roots.add(Path(metadata['blend_filepath']).parent)
        for root in sorted(roots):
            try:
                for path in root.iterdir():
                    if path in seen or path.is_symlink():
                        continue
                    if not (path.name.endswith('.crash.txt') or
                            path.suffix in ('.ips', '.crash') and 'blender' in path.name.lower()):
                        continue
                    info = path.stat()
                    if not stat.S_ISREG(info.st_mode) or not start - 2 <= info.st_mtime <= cutoff:
                        continue
                    seen.add(path)
                    identity = hashlib.sha256(str(path.absolute()).encode()).hexdigest()[:12]
                    yield path, Path('native-reports') / (identity + '-' + path.name)
            except OSError:
                continue


def _write_json(path, data):
    temporary = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
    os.replace(temporary, path)


def collect_session(directory):
    """Return verified archive Path; completeness is recorded in collection.json.

    Missing mandatory artifacts still produce a useful ZIP. CLI exits 3 for that
    case. Failure to create/verify the ZIP raises and never publishes it.
    """
    directory, native, manifest, metadata, manifest_status = _session_context(directory)
    recordings, requests = _recordings(directory, native, manifest, metadata)
    pid = _main_pid(manifest, metadata, native)
    mandatory_values = manifest.get('mandatory_artifacts', [])
    mandatory_values = mandatory_values if isinstance(mandatory_values, list) else []
    required = {_safe_relative(item) for item in mandatory_values if isinstance(item, str)}
    if manifest:
        required.add(Path('session.json'))
    entries = []
    records = list(requests)
    seen = set()
    optional_enumerated = 0
    optional_skipped = 0
    native_requested = native is not None
    native_valid = native is not None and native.is_dir() and not native.is_symlink()

    def add(path, copy, mandatory, category, error=None):
        identity = str(path.absolute())
        if identity in seen:
            return None
        seen.add(identity)
        record = dict(source=identity, copy=str(copy), mandatory=mandatory, category=category)
        if error:
            record.update(status='enumeration-error', error=str(error))
        entries.append((path, copy, record))
        return record

    # Explicit mandatory paths are enumerated first, before helper processes.
    if native_valid:
        prefix = Path('.') if directory == native else Path('native-allocation')
        for relative in sorted(required):
            record = add(native / relative, prefix / relative, True, 'native-allocation')
            cursor = native
            for part in relative.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    if record is not None:
                        record['status'] = 'skipped-symlink'
                    break
        for path, error in _walk(native):
            relative = path.relative_to(native)
            # Recorder metadata decides association; unrelated sessions cannot
            # sneak into the archive via native-root traversal.
            if relative.parts and relative.parts[0] == 'python':
                continue
            if path.name == 'collection.json' or path.name.endswith(('.zip', '.zip.partial')):
                continue
            mandatory = (error is not None or relative in required or path.name in CORE_NAMES or
                         bool(relative.parts and (relative.parts[0] in ('fault', 'allocation-history')
                                                 or manifest and relative.parts[0].startswith('preflight-'))) or
                         _is_main_process(relative, pid))
            if mandatory:
                add(path, prefix / relative, True, 'native-allocation', error)
            elif optional_enumerated < OPTIONAL_LIMITS['entries']:
                add(path, prefix / relative, False, 'native-allocation', error)
                optional_enumerated += 1
            else:
                optional_skipped += 1
    elif native_requested:
        records.append(dict(source=str(native), status='missing-or-symlink-directory',
                            mandatory=True, category='native-allocation'))

    for recording, _ in sorted(recordings.items()):
        if recording == directory:
            prefix = Path('.')
        elif native_valid and recording.is_relative_to(native):
            prefix = recording.relative_to(native)
        else:
            prefix = Path('recorder-sessions') / recording.name
        for name in ('metadata.json', 'events.jsonl', 'fatal-python.txt', 'periodic-python.txt', 'console.log'):
            add(recording / name, prefix / name, True, 'recorder')
        for path, error in _walk(recording):
            if path.name == 'collection.json' or path.name.endswith(('.zip', '.zip.partial')):
                continue
            add(path, prefix / path.relative_to(recording), True, 'recorder', error)
    for path, copy in _native_reports(recordings):
        add(path, copy, False, 'native-report')
    # Required and main-PID data cannot be crowded out by optional helper logs.
    entries.sort(key=lambda item: (not item[2]['mandatory'], str(item[1])))
    archive = directory.with_name(directory.name + '-' + str(time.time_ns()) + '.zip')
    partial = archive.with_suffix('.zip.partial')
    optional_bytes = optional_count = total = 0
    try:
        with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            for path, copy, record in entries:
                records.append(record)
                if 'status' in record:
                    continue
                if path.is_symlink():
                    record['status'] = 'skipped-symlink'
                    continue
                if not record['mandatory'] and optional_count >= OPTIONAL_LIMITS['entries']:
                    record['status'] = 'entry-count-limit'
                    continue
                if not record['mandatory']:
                    optional_count += 1
                try:
                    with _open_regular(path) as source:
                        before = os.fstat(source.fileno())
                        record.update(bytes=before.st_size, modified_epoch=before.st_mtime)
                        if not record['mandatory'] and (before.st_size > OPTIONAL_LIMITS['per_file_bytes'] or
                                optional_bytes + before.st_size > OPTIONAL_LIMITS['total_bytes']):
                            record['status'] = 'size-limit'
                            continue
                        digest = hashlib.sha256()
                        captured = 0
                        with bundle.open(str(Path(directory.name) / copy), 'w', force_zip64=True) as target:
                            remaining = before.st_size
                            while remaining:
                                chunk = source.read(min(1024**2, remaining))
                                if not chunk:
                                    break
                                target.write(chunk)
                                digest.update(chunk)
                                captured += len(chunk)
                                remaining -= len(chunk)
                        total += captured
                        if not record['mandatory']:
                            optional_bytes += captured
                        after = os.fstat(source.fileno())
                        changed = (before.st_size != after.st_size or
                                   before.st_mtime_ns != after.st_mtime_ns or remaining != 0)
                        record.update(status='included', captured_bytes=captured, sha256=digest.hexdigest(),
                                      changed_during_copy=changed, complete_snapshot=not changed)
                except ValueError as error:
                    record.update(status='skipped-nonregular-file', error=str(error))
                except OSError as error:
                    if error.errno == 2:
                        record.update(status='missing-artifact' if record['mandatory'] else 'missing-file')
                    else:
                        # ENOSPC/EDQUOT on ZIP output cannot be recovered by omitting
                        # evidence. Abort without publishing an invalid archive.
                        if error.errno in (28, 122):
                            raise
                        record.update(status='read-error', error=str(error))
            if optional_skipped:
                records.append(dict(source=str(native), status='entry-count-limit', mandatory=False,
                                    category='native-allocation', skipped_entries=optional_skipped,
                                    limit=OPTIONAL_LIMITS['entries']))
            optional_incomplete = any(not row.get('mandatory') and (row.get('status') != 'included'
                                      or not row.get('complete_snapshot')) for row in records)
            missing = [row for row in records if row.get('mandatory') and
                       (row.get('status') != 'included' or not row.get('complete_snapshot'))]
            manifest_causal = manifest.get('causal_evidence')
            manifest_causal = manifest_causal if isinstance(manifest_causal, dict) else {}
            causal = {key: manifest_causal.get(key, 'unknown') for key in CAUSAL_KEYS}
            fault = _json(native / 'fault' / 'summary.json') if native_valid else {}
            causal.update({key: value for key, value in fault.get('causal_evidence', {}).items()
                           if key in CAUSAL_KEYS})
            causal_complete = all(value is True or value == 'observed' for value in causal.values())
            collection = dict(schema=2, launch_id=manifest.get('launch_id') or metadata.get('launch_id'),
                              blender_pid=pid, session_manifest_status=manifest_status,
                              collected_epoch=time.time(),
                              recordings=[str(path) for path in sorted(recordings)],
                              artifacts=records, artifact_completeness='incomplete' if missing else 'complete',
                              optional_completeness='incomplete' if optional_incomplete else 'complete',
                              optional_entries_skipped=optional_skipped,
                              mandatory_gaps=[dict(source=row['source'], status=row.get('status'),
                                                   changed_during_copy=row.get('changed_during_copy', False))
                                              for row in missing],
                              causal_evidence=causal, causal_coverage='complete' if causal_complete else 'incomplete',
                              capture_complete=fault.get('artifact_complete'),
                              capture_limitations=fault.get('limitations', []),
                              causal_gaps=[key for key, value in causal.items()
                                           if not (value is True or value == 'observed')],
                              captured_bytes=total, zip64=True, verification='CRC verified before archive publication',
                              native_allocation=[row for row in records if row.get('category') == 'native-allocation'],
                              native_allocation_requested=native_requested,
                              native_allocation_limits=dict(OPTIONAL_LIMITS, applies_to='optional helper artifacts only'),
                              native_allocation_captured_bytes=sum(row.get('captured_bytes', 0) for row in records
                                                                   if row.get('category') == 'native-allocation'))
            bundle.writestr(str(Path(directory.name) / 'collection.json'), json.dumps(collection, indent=2) + '\n')
        with zipfile.ZipFile(partial) as bundle:
            bad_member = bundle.testzip()
            if bad_member:
                raise RuntimeError('ZIP CRC verification failed: ' + bad_member)
        # Link publication is exclusive: an existing report cannot be replaced.
        _write_json(directory / 'collection.json', collection)
        os.link(partial, archive)
        partial.unlink()
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    print('Perceptual Grade diagnostic ZIP: ' + str(archive), flush=True)
    print('Artifacts: ' + collection['artifact_completeness'] + '; causal evidence: ' + collection['causal_coverage'],
          flush=True)
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_directory', type=Path)
    arguments = parser.parse_args(argv)
    try:
        archive = collect_session(arguments.session_directory)
        with zipfile.ZipFile(archive) as bundle:
            collection = json.loads(bundle.read(next(name for name in bundle.namelist()
                                                     if name.count('/') == 1 and name.endswith('/collection.json'))))
        return 0 if collection['artifact_completeness'] == 'complete' else 3
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print('Diagnostic packaging failed; original logs are preserved: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
