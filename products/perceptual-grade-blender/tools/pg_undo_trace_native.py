"""Host-side capture utilities. No Blender imports or target-side evaluation.

Used from Apple's LLDB Python, and deliberately independently testable elsewhere.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

SCHEMA = 1
FAULT_SIGNALS = {4, 6, 10, 11}  # Darwin SIGILL, SIGABRT, SIGBUS, SIGSEGV.


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf8') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def clock_fields():
    return dict(wall_time_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sequence = 0

    def emit(self, event, **fields):
        self.sequence += 1
        row = dict(schema=SCHEMA, sequence=self.sequence, event=event, **clock_fields(), **fields)
        # Only caller-owned host scalars enter the journal, never SBValue formatters.
        with self.path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
            stream.flush()
        return row


def run_tool(arguments, output, timeout=30, accepted=(0,)):
    """Bound tool execution; preserve output even on timeout/nonzero status."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = dict(arguments=list(map(str, arguments)), timeout_seconds=timeout,
                  output=str(output), status='error')
    # Do not spread Blender's allocation logging to the inspecting tools.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('MallocStackLogging')}
    environment['LC_ALL'] = 'C'
    try:
        with output.open('wb') as stream:
            completed = subprocess.run(list(map(str, arguments)), stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, env=environment,
                                       timeout=timeout, check=False)
        result.update(returncode=completed.returncode,
                      status='ok' if completed.returncode in accepted else 'error')
    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
    except OSError as error:
        result['error'] = str(error)
    result['elapsed_seconds'] = time.monotonic() - started
    if output.exists():
        result.update(bytes=output.stat().st_size, sha256=sha256(output))
    return result


def history_evidence(path, *, expected_size=None, expected_symbol=None):
    """Recognize record-specific allocation and free stack frames conservatively.

    A FREE header without its own frames is incomplete even when an earlier
    ALLOC record has a stack. Preserve the complete tool output for association
    with the Image address and allocation lifetime during manual review. Optional
    canary filters apply to each record: earlier uses of the same address must
    not stand in for the allocation/free operation being checked.
    """
    evidence = dict(allocation=False, free=False, allocation_stack=False,
                    free_stack=False, stack=False)
    header = re.compile(r'^\s*(ALLOC|MALLOC|CALLOC|REALLOC|FREE|DEALLOC)\b')
    size = re.compile(r'\bsize\s*=\s*(\d+)\b')
    frame = re.compile(r'(?:\b0x[0-9a-fA-F]+\s+\([^\r\n)]+\)\s+\S+|'
                       r'\b0x[0-9a-fA-F]+\b.*\+\s*\d+|'
                       r'\b(?:malloc|calloc|realloc|free|malloc_zone_malloc|malloc_zone_free)\b.*\|'
                       r'|\|.*\b(?:malloc|calloc|realloc|free|malloc_zone_malloc|malloc_zone_free)\b)')
    symbol = (re.compile(r'(?<!\w)' + re.escape(expected_symbol) + r'(?!\w)')
              if expected_symbol is not None else None)
    current = None

    def finish_record():
        if current and current['size_matches'] and current['symbol_matches']:
            evidence[current['kind']] = True
            evidence[current['kind'] + '_stack'] |= current['stack']

    try:
        with Path(path).open(errors='replace') as stream:
            for line in stream:
                match = header.match(line)
                if match:
                    finish_record()
                    size_match = size.search(line[match.end():].partition(':')[0])
                    current = dict(
                        kind='free' if match[1] in ('FREE', 'DEALLOC') else 'allocation',
                        size_matches=(expected_size is None or
                                      bool(size_match and int(size_match[1]) == expected_size)),
                        symbol_matches=symbol is None, stack=False)
                    # malloc_history can print frames on the same line as its
                    # ALLOC/FREE header, including address/module/symbol frames
                    # with neither an offset nor a public allocator name.
                    line = line[match.end():]
                if current and frame.search(line):
                    current['stack'] = True
                    if symbol and symbol.search(line):
                        current['symbol_matches'] = True
            finish_record()
    except OSError:
        pass
    evidence['stack'] = evidence['allocation_stack'] and evidence['free_stack']
    return evidence


class Capture:
    """Capture a stopped process via a small adapter; never resumes it."""
    def __init__(self, directory, adapter, runner=run_tool):
        self.directory = Path(directory)
        self.adapter = adapter
        self.runner = runner

    def execute(self, addresses=(), full_history=True, force_graph=False):
        root = self.directory / 'fault'
        root.mkdir(exist_ok=True)
        if not self.adapter.is_stopped():
            raise RuntimeError('Native capture requires a stopped, live process')
        pid = self.adapter.pid
        write_json(root / 'native.json', self.adapter.snapshot())
        result = dict(schema=SCHEMA, pid=pid, **clock_fields(),
                      process_stopped=True, histories=[], graph=None,
                      artifact_complete=True, free_stack=False, any_free_stack=False, limitations=[])
        # Prioritize addresses supplied by the latest native operation/edge ledger.
        candidates = list(dict.fromkeys(int(p) for p in addresses if int(p) > 0))
        selected = candidates[:32]
        result['addresses_not_queried'] = [hex(p) for p in candidates[32:]]
        result['priority_address'] = hex(selected[0]) if selected else None
        result['priority_evidence_complete'] = False

        def observe_history(row):
            complete = row['status'] == 'ok' and all(row['evidence'].values())
            if complete:
                result['any_free_stack'] = True
                if row['address'] == result['priority_address']:
                    result['priority_evidence_complete'] = True
                    result['free_stack'] = True
            return complete

        if len(candidates) > 32:
            result['limitations'].append('Targeted query limit: 32 addresses; full graph requested')
        for address in selected:
            if not self.adapter.is_stopped():
                result['artifact_complete'] = False
                result['limitations'].append('Process did not remain stopped before allocation query')
                break
            path = root / ('malloc-' + format(address, 'x') + '.txt')
            print('Capturing allocation history for ' + hex(address), flush=True)
            row = self.runner(['/usr/bin/malloc_history', str(pid), hex(address)], path, timeout=30)
            row.update(address=hex(address), evidence=history_evidence(path))
            result['histories'].append(row)
            observe_history(row)
            if not self.adapter.is_stopped():
                result['artifact_complete'] = False
                result['limitations'].append('Process did not remain stopped during allocation capture')
                break
        # The driver puts the implicated old Image first. A freed unrelated
        # historical Image must not suppress fallback for that priority address;
        # the replacement Image can legitimately have no free record yet.
        unresolved = (force_graph or not selected or not result['priority_evidence_complete'] or len(candidates) > 32
                      or any(row['status'] != 'ok' for row in result['histories']))
        if full_history and unresolved and self.adapter.is_stopped():
            graph = root / 'fault.memgraph'
            print('Capturing full stack history graph (up to 180 seconds).', flush=True)
            row = self.runner(['/usr/bin/leaks', '-outputGraph', str(graph), '-noContent',
                               '-fullStackHistory', str(pid)], root / 'leaks.txt',
                              timeout=180, accepted=(0, 1))
            row['valid_file'] = graph.is_file() and graph.stat().st_size > 0
            # A present graph is not equivalent to a verified queryable history.
            row['query_verified'] = False
            if row['status'] == 'ok' and row['valid_file'] and self.adapter.is_stopped():
                for address in selected:
                    if not self.adapter.is_stopped():
                        result['artifact_complete'] = False
                        result['limitations'].append('Process did not remain stopped during graph queries')
                        break
                    output = root / ('memgraph-' + format(address, 'x') + '.txt')
                    query = self.runner(['/usr/bin/malloc_history', str(graph), hex(address)],
                                        output, timeout=30)
                    query.update(address=hex(address), evidence=history_evidence(output))
                    result['histories'].append(query)
                    if observe_history(query):
                        row['query_verified'] = True
            result['graph'] = row
            if row['status'] != 'ok' or not row['valid_file']:
                result['artifact_complete'] = False
                result['limitations'].append('Full-stack-history graph unavailable')
        result['process_stopped'] = self.adapter.is_stopped()
        if not result['process_stopped']:
            result['artifact_complete'] = False
        if any(row['status'] != 'ok' for row in result['histories']):
            result['artifact_complete'] = False
            result['limitations'].append('One or more allocation history queries failed or timed out')
        if not result['free_stack']:
            result['limitations'].append('Allocation/free stack not yet established for the priority Image')
        write_json(root / 'summary.json', result)
        return result
