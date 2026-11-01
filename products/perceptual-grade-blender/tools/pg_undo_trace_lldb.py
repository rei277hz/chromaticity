"""External LLDB driver: never evaluates expressions or calls into the inferior.

Entry: command script import .../pg_undo_trace_lldb.py; pg-undo-run
All process control goes through SB APIs. Apple's LLDB supplies the interpreter.
"""
import json
import os
from pathlib import Path
import signal
import struct
import sys
import time

# LLDB's command import does not reliably add sibling modules to sys.path.
TOOLS = Path(os.environ.get('PG_UNDO_TRACE_TOOLS_DIR', Path(__file__).absolute().parent))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from pg_undo_trace_native import (Capture, FAULT_SIGNALS, Journal, clock_fields,
                                  history_evidence, run_tool, sha256, write_json)

try:
    import lldb
except ImportError:
    lldb = None

BUILD = 'd13f752e3b9c'
UUID = '43861983-96de-3588-8491-260b05dcc486'
# Source-derived ARM64 LP64 prefixes from the exact build's RNA_types.hh,
# DNA_node_types.h and DNA_ID.h. Every used field is checked against fresh
# objects in a disposable factory-startup process before the user's launch.
PROFILE = {'rna_owner': 0, 'rna_data': 16, 'node_name': 48, 'node_image': 216,
           'id_name': 40, 'id_uid': 324}
SETTERS = ('ShaderNodeTexImage_image_set', 'CompositorNodeImage_image_set')
CLEANUPS = {'BKE_id_free_ex': ('destruction_requested', 'x1'),
            'BKE_libblock_free_data_py': ('payload_cleanup', 'x0')}
# Match the disposable C fixture, not earlier lifetimes at its reused address.
CANARY_HISTORY = dict(expected_size=7137, expected_symbol='pg_canary_allocate')
PROCESS_EVENT_LIMIT = 256


def state_name(state):
    if state is None:
        return 'unknown'
    for name in ('Invalid', 'Unloaded', 'Connected', 'Attaching', 'Launching',
                 'Stopped', 'Running', 'Stepping', 'Crashed', 'Detached', 'Exited', 'Suspended'):
        if state == getattr(lldb, 'eState' + name, None):
            return name.lower()
    return 'unknown'


def sb_description(value):
    """SB object descriptions are host debugger metadata, not inferior expressions."""
    stream = lldb.SBStream()
    value.GetDescription(stream)
    return (stream.GetData() or '')[:16384]


def hexint(value):
    return hex(value) if value else '0x0'


def field_offset(target, typename, field):
    typ = target.FindFirstType(typename)
    if not typ.IsValid():
        return None
    for index in range(typ.GetNumberOfFields()):
        item = typ.GetFieldAtIndex(index)
        if item.GetName() == field:
            offset = item.GetOffsetInBytes()
            member_type = item.GetType()
            invalid = getattr(lldb, 'LLDB_INVALID_OFFSET', (1 << 64) - 1)
            if (offset < 0 or offset == invalid or not member_type.IsValid()
                    or typ.GetByteSize() <= 0 or member_type.GetByteSize() <= 0
                    or offset + member_type.GetByteSize() > typ.GetByteSize()):
                return None
            return offset
    return None


def select_layout(target):
    mapping = {'rna_owner': ('PointerRNA', 'owner_id'), 'rna_data': ('PointerRNA', 'data'),
               'node_name': ('bNode', 'name'), 'node_image': ('bNode', 'id'),
               'id_name': ('ID', 'name'), 'id_uid': ('ID', 'session_uid')}
    dwarf = {key: field_offset(target, *pair) for key, pair in mapping.items()}
    if all(value is not None for value in dwarf.values()):
        return dwarf, 'DWARF; pending canary validation'
    return dict(PROFILE), 'exact-build source profile; pending canary validation'


def native_fault(thread):
    reason = thread.GetStopReason()
    if reason == lldb.eStopReasonException:
        return True
    return (reason == lldb.eStopReasonSignal and thread.GetStopReasonDataCount() > 0
            and thread.GetStopReasonDataAtIndex(0) in FAULT_SIGNALS)


def read_oracle(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


class Driver:
    def __init__(self, debugger, root):
        self.debugger = debugger
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = json.loads((self.root / 'config.json').read_text())
        self.session = json.loads((self.root / 'session.json').read_text())
        self.journal = Journal(self.root / 'native-events.jsonl')
        self.target = None
        self.process = None
        self.layout = dict(PROFILE)
        self.breaks = {}
        self.pending = {}
        self.edges = {}
        self.images = {}
        self.hit_count = 0
        self.pause_ns = 0
        self.setter_verified = 0
        self.completed_setters = 0
        self.canary = False
        self.last_candidates = []
        self.last_stop_id = None
        self.wait_after_stop_id = None
        self.first_fault_seen = False
        self.listener = None
        self.process_event_count = 0

    def emit(self, event, **fields):
        try:
            undo_bytes = (self.run_dir / 'native-undo.log').stat().st_size
        except (OSError, AttributeError):
            undo_bytes = None
        return self.journal.emit(event, phase=getattr(self, 'phase', 'setup'),
                                 pid=self.pid if self.process else None,
                                 native_undo_bytes=undo_bytes, **fields)

    @property
    def pid(self):
        return self.process.GetProcessID()

    def is_stopped(self):
        return bool(self.process and self.process.IsValid()
                    and self.process.GetState() in (lldb.eStateStopped, lldb.eStateCrashed))

    def read(self, address, length):
        if not self.is_stopped() or not address or length > 4096:
            raise RuntimeError('Invalid bounded native read')
        error = lldb.SBError()
        value = self.process.ReadMemory(address, length, error)
        if not error.Success() or len(value) != length:
            raise RuntimeError('Native read failed at ' + hexint(address) + ': ' + str(error))
        return value

    def pointer(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def reg(self, frame, name):
        value = frame.FindRegister(name)
        if not value.IsValid():
            raise RuntimeError('Missing ABI register ' + name)
        error = lldb.SBError()
        result = value.GetValueAsUnsigned(error)
        if not error.Success():
            raise RuntimeError('Unreadable ABI register ' + name)
        return result

    def identity(self, address):
        if not address:
            return dict(pointer=0, name=None, uid=None, code=None)
        name = self.read(address + self.layout['id_name'], 258).split(b'\0', 1)[0]
        uid = struct.unpack('<I', self.read(address + self.layout['id_uid'], 4))[0]
        return dict(pointer=address, code=name[:2].decode('ascii', 'replace'),
                    name=name[2:].decode('utf8', 'replace'), uid=uid,
                    observation='raw stopped-process bytes; not a liveness assertion')

    def maybe_identity(self, address):
        try:
            return self.identity(address)
        except RuntimeError as error:
            return dict(pointer=address, error=str(error))

    def stack(self, thread, limit=128):
        rows = []
        for index in range(min(limit, thread.GetNumFrames())):
            frame = thread.GetFrameAtIndex(index)
            address = frame.GetPCAddress()
            module = address.GetModule()
            rows.append(dict(index=index, pc=hexint(frame.GetPC()), sp=hexint(frame.GetSP()),
                             function=frame.GetFunctionName() or frame.GetSymbol().GetName(),
                             module=str(module.GetFileSpec()) if module.IsValid() else None,
                             uuid=module.GetUUIDString() if module.IsValid() else None))
        return rows

    def snapshot(self):
        threads = []
        for thread in self.process:
            frame = thread.GetFrameAtIndex(0)
            registers = {}
            for group in frame.GetRegisters():
                for register in group:
                    # Raw SBValue, no summaries/synthetic values or expression evaluation.
                    registers[register.GetName()] = register.GetValue()
            pc = frame.GetPC()
            instructions = []
            for instruction in self.target.ReadInstructions(frame.GetPCAddress(), 20):
                instructions.append(dict(address=hexint(instruction.GetAddress().GetLoadAddress(self.target)),
                                         mnemonic=instruction.GetMnemonic(self.target),
                                         operands=instruction.GetOperands(self.target)))
            try:
                memory = dict(address=hexint(max(0, pc - 64)),
                              bytes=self.read(max(0, pc - 64), 192).hex())
            except RuntimeError as error:
                memory = dict(error=str(error))
            threads.append(dict(tid=thread.GetThreadID(), reason=thread.GetStopReason(),
                                description=thread.GetStopDescription(1024),
                                reason_data=[thread.GetStopReasonDataAtIndex(i)
                                             for i in range(thread.GetStopReasonDataCount())],
                                registers=registers, frames=self.stack(thread),
                                instructions=instructions, instruction_memory=memory))
        modules = [dict(path=str(module.GetFileSpec()), uuid=module.GetUUIDString(),
                        load_address=hexint(module.GetObjectFileHeaderAddress().GetLoadAddress(self.target)))
                   for module in self.target.modules]
        edges = []
        for node, edge in self.edges.items():
            row = dict(edge)
            try:
                row['current_link'] = self.pointer(node + self.layout['node_image'])
                row['current_node_name'] = self.read(node + self.layout['node_name'], 64).split(b'\0', 1)[0].decode('utf8', 'replace')
                row['owner_now'] = self.maybe_identity(edge['tree']['pointer'])
                row['observation'] = 'historical address reread; native object lifetime unverified'
            except RuntimeError as error:
                row['read_error'] = str(error)
            edges.append(row)
        return dict(schema=1, pid=self.pid, **clock_fields(), threads=threads, modules=modules,
                    historical_edges=edges, layout=self.layout, hit_count=self.hit_count,
                    breakpoint_pause_ns=self.pause_ns, pending_setters=list(self.pending.values()))

    def module_identity(self):
        module = self.target.GetModuleAtIndex(0)
        return dict(uuid=(module.GetUUIDString() or '').lower(), triple=self.target.GetTriple(),
                    executable=str(module.GetFileSpec()))

    def process_details(self):
        """Capture launch/terminal diagnostics before Kill/DeleteTarget erase them."""
        result = dict(**clock_fields())
        if self.process is None:
            return dict(result, valid=False, state_name='absent')
        for key, method in (('valid', 'IsValid'), ('pid', 'GetProcessID'),
                            ('unique_id', 'GetUniqueID'), ('state', 'GetState'),
                            ('stop_id', 'GetStopID'),
                            ('exit_status', 'GetExitStatus'), ('exit_description', 'GetExitDescription')):
            try:
                result[key] = getattr(self.process, method)()
            except Exception as error:
                result[key + '_unavailable'] = str(error)
        result['state_name'] = state_name(result.get('state'))
        try:
            result['description'] = sb_description(self.process)
        except Exception as error:
            result['description_unavailable'] = str(error)
        return result

    def record_process(self, reason, details=None):
        row = self.process_details() if details is None else dict(details)
        row['reason'] = reason
        write_json(self.run_dir / (reason + '.json'), row)
        self.emit('process_observed', observation=row)
        return row

    def best_effort_process_record(self, reason, details=None):
        try:
            return self.record_process(reason, details)
        except Exception as error:
            self.log_capture_error('record process state (' + reason + ')', error)
            return details or {}

    def record_process_event(self, event):
        # A separate listener is used for each target. Still identify the
        # originating process explicitly, so an unexpected event is evidence,
        # never an instruction to resume or a substitute for GetState().
        if self.process_event_count > PROCESS_EVENT_LIMIT:
            return
        if self.process_event_count == PROCESS_EVENT_LIMIT:
            self.emit('process_event_limit', limit=PROCESS_EVENT_LIMIT)
            self.process_event_count += 1
            return
        self.process_event_count += 1
        row = dict(event_type=event.GetType(), description=sb_description(event))
        if lldb.SBProcess.EventIsProcessEvent(event):
            process = lldb.SBProcess.GetProcessFromEvent(event)
            state = lldb.SBProcess.GetStateFromEvent(event)
            row.update(pid=process.GetProcessID(), unique_id=process.GetUniqueID(),
                       current_process=process.GetUniqueID() == self.process.GetUniqueID(),
                       state=state, state_name=state_name(state),
                       restarted=lldb.SBProcess.GetRestartedFromEvent(event))
        self.emit('process_event', observation=row)

    def launch(self, executable, arguments, directory, phase, allocator=True):
        self.phase = phase
        self.run_dir = Path(directory)
        self.wait_after_stop_id = None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.process_event_count = 0
        # Killing the allocation canary can leave queued terminal events.
        # Do not mix a previous target's event stream with this launch.
        self.listener = lldb.SBListener('pg-undo-native-' + phase)
        self.target = self.debugger.CreateTarget(str(executable))
        if not self.target.IsValid():
            raise RuntimeError('LLDB could not create target')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('MallocStackLogging') and not key.startswith('PG_UNDO_TRACE')}
        if allocator:
            env.update(MallocStackLoggingNoCompact='1', MallocStackLoggingDirectory=str(self.run_dir))
        env.update(PG_UNDO_TRACE_SESSION_DIR=str(self.root),
                   PG_UNDO_TRACE_LAUNCH_ID=self.session['launch_id'],
                   PG_UNDO_TRACE_TOOLS_DIR=str(TOOLS),
                   PG_UNDO_TRACE_UNDO_LOG=str(self.run_dir / 'native-undo.log'),
                   PG_UNDO_TRACE_CANARY_DIR=str(self.run_dir))
        launch = lldb.SBLaunchInfo(list(map(str, arguments)))
        launch.SetEnvironmentEntries([key + '=' + value for key, value in env.items()], True)
        launch.SetWorkingDirectory(str(self.run_dir))
        launch.SetListener(self.listener)
        # Clear debugger defaults that might disable ASLR or launch via a shell.
        launch.SetLaunchFlags(lldb.eLaunchFlagStopAtEntry)
        launch.AddOpenFileAction(0, '/dev/null', True, False)
        launch.AddOpenFileAction(1, str(self.run_dir / 'launcher-console.log'), False, True)
        # Share one open-file description, so stdout/stderr use one append
        # offset instead of opening/truncating the same path independently.
        launch.AddDuplicateFileAction(1, 2)
        attempt = dict(schema=1, phase=phase, executable=str(executable),
                       arguments=list(map(str, arguments)), working_directory=str(self.run_dir),
                       launch_flags=lldb.eLaunchFlagStopAtEntry,
                       environment={key: value for key, value in env.items()
                                    if key.startswith(('MallocStackLogging', 'PG_UNDO_TRACE'))},
                       **clock_fields())
        write_json(self.run_dir / 'launch.json', attempt)
        self.emit('process_launch_requested', request=attempt)
        error = lldb.SBError()
        self.process = self.target.Launch(launch, error)
        attempt['returned'] = dict(error_success=error.Success(), error=str(error),
                                   process=self.process_details())
        for key, method in (('error_code', 'GetError'), ('error_type', 'GetType')):
            try:
                attempt['returned'][key] = getattr(error, method)()
            except Exception as metadata_error:
                attempt['returned'][key + '_unavailable'] = str(metadata_error)
        try:
            write_json(self.run_dir / 'launch.json', attempt)
        except Exception as record_error:
            self.log_capture_error('save returned launch result', record_error)
        try:
            self.emit('process_launch_returned', result=attempt['returned'])
        except Exception as record_error:
            self.log_capture_error('record returned launch event', record_error)
        if not error.Success() or not self.process.IsValid():
            raise RuntimeError('Debugger launch denied/failed: ' + str(error))
        self.wait_stop(30)
        signals = self.process.GetUnixSignals()
        for number in sorted(FAULT_SIGNALS | {signal.SIGSTOP}):
            signals.SetShouldStop(number, True)
            signals.SetShouldSuppress(number, False)
            signals.SetShouldNotify(number, True)
        self.breaks.clear()
        self.pending.clear()
        self.edges.clear()
        self.images.clear()
        self.last_candidates = []
        self.emit('process_launched', identity=self.module_identity(), environment={
            key: value for key, value in env.items() if key.startswith('MallocStackLogging')})
        return self.module_identity()

    def wait_stop(self, timeout=None):
        start = time.monotonic()
        while True:
            state = self.process.GetState()
            if state in (lldb.eStateStopped, lldb.eStateCrashed):
                stop_id = self.process.GetStopID()
                if self.wait_after_stop_id is None or stop_id != self.wait_after_stop_id:
                    self.last_stop_id = stop_id
                    self.wait_after_stop_id = None
                    return
            if state in (lldb.eStateExited, lldb.eStateDetached, lldb.eStateInvalid):
                details = self.process_details()
                self.best_effort_process_record('wait-stop-failure', details)
                self.drain_process_events()
                raise RuntimeError('Inferior ' + state_name(state) + ' before expected stop: pid='
                                   + str(details.get('pid')) + ', exit_status='
                                   + str(details.get('exit_status')) + ', exit_description='
                                   + repr(details.get('exit_description')) + ', description='
                                   + repr(details.get('description'))
                                   + '; see ' + str(self.run_dir / 'wait-stop-failure.json'))
            if timeout is not None and time.monotonic() - start > timeout:
                self.best_effort_process_record('wait-stop-timeout')
                self.process.Stop()
                raise RuntimeError('Timed out waiting for inferior stop')
            event = lldb.SBEvent()
            if self.listener.WaitForEvent(1, event):
                try:
                    self.record_process_event(event)
                except Exception as error:
                    self.log_capture_error('record process event', error)

    def drain_process_events(self):
        """Record already-queued events without allowing them to mask a stop."""
        if self.listener is None:
            return
        while self.process_event_count <= PROCESS_EVENT_LIMIT:
            event = lldb.SBEvent()
            try:
                available = self.listener.GetNextEvent(event)
            except Exception as error:
                self.log_capture_error('drain queued process event', error)
                return
            if not available:
                return
            try:
                self.record_process_event(event)
            except Exception as error:
                self.log_capture_error('record queued process event', error)
                return

    def resume(self):
        # In async LLDB mode Continue() can return while SBProcess still
        # exposes the previous stopped state. Never process that stale stop.
        self.wait_after_stop_id = self.process.GetStopID()
        error = self.process.Continue()
        if not error.Success():
            self.wait_after_stop_id = None
            raise RuntimeError('Continue failed: ' + str(error))

    def symbol_break(self, name, kind, required=True):
        contexts = self.target.FindFunctions(name, lldb.eFunctionNameTypeAuto)
        locations = set()
        for index in range(contexts.GetSize()):
            context = contexts.GetContextAtIndex(index)
            function, symbol = context.GetFunction(), context.GetSymbol()
            address = function.GetStartAddress() if function.IsValid() else symbol.GetStartAddress()
            if address.IsValid():
                loaded = address.GetLoadAddress(self.target)
                if loaded != lldb.LLDB_INVALID_ADDRESS:
                    locations.add(loaded)
        ids = []
        for address in sorted(locations):
            # Exact entry addresses: no prologue skipping when reading ABI registers.
            breakpoint = self.target.BreakpointCreateByAddress(address)
            self.breaks[breakpoint.GetID()] = dict(kind=kind, symbol=name, address=address)
            ids.append(breakpoint.GetID())
        self.emit('symbol_resolution', symbol=name, locations=len(locations), required=required)
        if required and not locations:
            raise RuntimeError('Required native symbol unresolved: ' + name)
        return ids

    def hooks(self):
        for symbol in SETTERS:
            self.symbol_break(symbol, 'setter')
        for symbol in CLEANUPS:
            self.symbol_break(symbol, 'cleanup', required=False)

    def validate_setter(self, row):
        oracle = read_oracle(self.run_dir / 'oracle.jsonl')
        expected = oracle[-1] if oracle else {}
        if expected.get('event') != 'setter_expected':
            return False  # Startup image assignments are not canary assertions.
        for key in ('node',):
            if row[key] != expected[key]:
                raise RuntimeError('Canary ABI mismatch: ' + key)
        for key, actual in (('tree', row['tree']), ('old', row['old']), ('new', row['new'])):
            wanted = expected[key]
            for member in ('pointer', 'name', 'uid'):
                if actual.get(member) != wanted[member]:
                    raise RuntimeError('Canary native layout mismatch: ' + key + '.' + member)
        if row['node_name'] != expected['node_name']:
            raise RuntimeError('Canary node name mismatch')
        self.setter_verified += 1
        return True

    def setter(self, thread, frame, hook):
        source = self.reg(frame, 'x0')
        value = self.reg(frame, 'x1')  # Nontrivial PointerRNA value is passed indirectly on ARM64.
        tree = self.pointer(source + self.layout['rna_owner'])
        node = self.pointer(source + self.layout['rna_data'])
        old = self.pointer(node + self.layout['node_image'])
        new = self.pointer(value + self.layout['rna_data'])
        row = dict(node=node, node_name=self.read(node + self.layout['node_name'], 64).split(b'\0', 1)[0].decode('utf8', 'replace'),
                   tree=self.maybe_identity(tree), old=self.maybe_identity(old), new=self.maybe_identity(new),
                   thread_id=thread.GetThreadID(), symbol=hook['symbol'], stack=self.stack(thread, 24))
        # Copy metadata only while stopped; it never claims allocation liveness.
        self.last_candidates = [old, new]
        for item in (row['old'], row['new']):
            if item['pointer']:
                self.images[item['pointer']] = item
        self.emit('image_assignment_enter', **row)
        verified = self.validate_setter(row) if self.canary else False
        return_address = self.reg(frame, 'lr')
        breakpoint = self.target.BreakpointCreateByAddress(return_address)
        locations = breakpoint.GetNumLocations() if breakpoint.IsValid() else 0
        self.emit('setter_return_breakpoint_resolution', symbol=hook['symbol'],
                  return_address=hexint(return_address), locations=locations,
                  thread_id=thread.GetThreadID())
        if not breakpoint.IsValid() or locations == 0:
            if breakpoint.IsValid():
                self.target.BreakpointDelete(breakpoint.GetID())
            raise RuntimeError('Setter return address did not resolve to a breakpoint location: '
                               + hexint(return_address))
        breakpoint.SetThreadID(thread.GetThreadID())
        ident = breakpoint.GetID()
        self.breaks[ident] = dict(kind='return', symbol=hook['symbol'])
        self.pending[ident] = dict(row, expected_sp=frame.GetSP(), return_address=return_address,
                                  verified=verified)

    def returned(self, thread, frame, ident):
        row = self.pending[ident]
        # Recursive calls can share the same LR; require the matching caller SP.
        if frame.GetSP() != row['expected_sp']:
            return
        actual = self.pointer(row['node'] + self.layout['node_image'])
        self.emit('image_assignment_return', node=row['node'], tree=row['tree'],
                  old=row['old'], new=row['new'], actual_link=actual,
                  completed=actual == row['new']['pointer'], thread_id=thread.GetThreadID())
        if self.canary and row['verified']:
            if actual != row['new']['pointer']:
                raise RuntimeError('Canary setter returned without expected native link')
            self.completed_setters += 1
        self.edges[row['node']] = dict(node=row['node'], node_name=row['node_name'], tree=row['tree'],
                                      installed_image=actual, expected_image=row['new'],
                                      observed_at=time.monotonic_ns())
        del self.pending[ident]
        del self.breaks[ident]
        self.target.BreakpointDelete(ident)

    def cleanup(self, thread, frame, hook):
        event, register = CLEANUPS[hook['symbol']]
        address = self.reg(frame, register)
        if address in self.images:
            fields = dict(image=address, historical_identity=self.images[address],
                          identity_now=self.maybe_identity(address), stack=self.stack(thread, 48),
                          symbol=hook['symbol'], thread_id=thread.GetThreadID(),
                          allocation_release_proven=False)
            if hook['symbol'] == 'BKE_id_free_ex':
                fields.update(main=self.reg(frame, 'x0'), flags=self.reg(frame, 'w2'))
            self.emit(event, **fields)

    def handle_breaks(self):
        start = time.monotonic_ns()
        handled = False
        for thread in self.process:
            if thread.GetStopReason() != lldb.eStopReasonBreakpoint:
                continue
            frame = thread.GetFrameAtIndex(0)
            for index in range(0, thread.GetStopReasonDataCount(), 2):
                ident = thread.GetStopReasonDataAtIndex(index)
                hook = self.breaks.get(ident)
                if hook is None:
                    continue
                handled = True
                self.hit_count += 1
                if hook['kind'] == 'setter':
                    self.setter(thread, frame, hook)
                elif hook['kind'] == 'return':
                    self.returned(thread, frame, ident)
                else:
                    self.cleanup(thread, frame, hook)
        self.pause_ns += time.monotonic_ns() - start
        return handled

    def kill_disposable(self):
        if self.process is not None:
            self.best_effort_process_record('before-dispose')
        if self.process and self.process.IsValid():
            self.process.Kill()
        if self.target:
            self.debugger.DeleteTarget(self.target)
        self.process = None
        self.target = None

    def allocation_preflight(self):
        directory = self.root / 'preflight-allocation'
        directory.mkdir(exist_ok=True)
        compiled = run_tool(['/usr/bin/xcrun', 'clang', '-g', '-O0',
                             str(TOOLS / 'pg_undo_trace_alloc_canary.c'), '-o', str(directory / 'canary')],
                            directory / 'compile.txt', timeout=60)
        if compiled['status'] != 'ok':
            raise RuntimeError('Allocation preflight fixture compilation failed; see compile.txt')
        self.launch(directory / 'canary', [], directory, 'allocation-preflight')
        self.resume()
        self.wait_stop(30)
        if not any(native_fault(thread) for thread in self.process):
            raise RuntimeError('Allocation canary did not stop at first native fault')
        text = (directory / 'launcher-console.log').read_text(errors='replace')
        import re
        match = re.search(r'PG_ALLOC_CANARY (0x[0-9a-fA-F]+)', text)
        if not match:
            raise RuntimeError('Allocation canary address not recorded')
        address = int(match.group(1), 16)
        result = Capture(directory, self).execute([address], full_history=False)
        history = directory / 'fault' / ('malloc-' + format(address, 'x') + '.txt')
        evidence = history_evidence(history, **CANARY_HISTORY)
        query = result['histories'][0]
        write_json(directory / 'live-check.json', dict(address=hex(address), query=query,
                                                      evidence=evidence, **CANARY_HISTORY,
                                                      process_stopped=self.is_stopped()))
        if query['status'] != 'ok' or not all(evidence.values()) or not self.is_stopped():
            missing = ', '.join(key for key, present in evidence.items() if not present)
            raise RuntimeError('Live allocation/free stack preflight failed: query='
                               + query['status'] + ', missing=' + (missing or 'none')
                               + '; see preflight-allocation/live-check.json and ' + str(history))
        # Always validate the full-history fallback on a known freed address.
        graph = directory / 'known.memgraph'
        capture = run_tool(['/usr/bin/leaks', '-outputGraph', str(graph), '-noContent',
                            '-fullStackHistory', str(self.pid)], directory / 'leaks.txt',
                           timeout=180, accepted=(0, 1))
        output = directory / 'graph-history.txt'
        query = run_tool(['/usr/bin/malloc_history', str(graph), hex(address)], output, timeout=30)
        evidence = history_evidence(output, **CANARY_HISTORY)
        write_json(directory / 'graph-check.json', dict(capture=capture, query=query, evidence=evidence,
                                                       address=hex(address), **CANARY_HISTORY,
                                                       process_stopped=self.is_stopped()))
        if capture['status'] != 'ok' or query['status'] != 'ok' or not all(evidence.values()) or not self.is_stopped():
            missing = ', '.join(key for key, present in evidence.items() if not present)
            raise RuntimeError('Full-stack-history graph preflight failed: capture='
                               + capture['status'] + ', query=' + query['status']
                               + ', missing=' + (missing or 'none')
                               + '; see preflight-allocation/graph-check.json')
        self.kill_disposable()

    def blender_preflight(self):
        directory = self.root / 'preflight-blender'
        self.canary = True
        args = ['--factory-startup', '--background', '--log', 'undo', '--log-level', 'debug',
                '--log-show-source', '--log-file', str(directory / 'native-undo.log'),
                '--python-exit-code', '7', '--python', str(TOOLS / 'pg_undo_trace_canary.py')]
        identity = self.launch(self.config['blender'], args, directory, 'blender-preflight')
        if identity['uuid'] != UUID or not identity['triple'].startswith(('arm64-', 'aarch64-')):
            raise RuntimeError('Unsupported Blender executable UUID/architecture: ' + str(identity))
        self.layout, source = select_layout(self.target)
        self.emit('layout_selected', layout=self.layout, source=source)
        self.hooks()
        start = time.monotonic()
        while time.monotonic() - start < 120:
            self.resume()
            self.wait_stop(120 - (time.monotonic() - start))
            if any(native_fault(thread) for thread in self.process):
                write_json(directory / 'unexpected-fault.json', self.snapshot())
                raise RuntimeError('Disposable Blender fixture faulted')
            if self.handle_breaks():
                continue
            if any(thread.GetStopReason() == lldb.eStopReasonSignal and
                   thread.GetStopReasonDataAtIndex(0) == signal.SIGSTOP for thread in self.process):
                break
            raise RuntimeError('Unexpected preflight stop; refusing to resume blindly')
        oracle = read_oracle(directory / 'oracle.jsonl')
        builds = [row for row in oracle if row['event'] == 'build']
        if not builds or builds[-1]['build'] != BUILD:
            raise RuntimeError('Unsupported Blender source build')
        if self.setter_verified != 12 or self.completed_setters != 12:
            raise RuntimeError('Native setter validation incomplete: ' + str((self.setter_verified, self.completed_setters)))
        if not any(row['event'] == 'undo_completed' for row in oracle):
            raise RuntimeError('Blender undo canary did not complete')
        undo = (directory / 'native-undo.log').read_text(errors='replace')
        if not any(phrase in undo for phrase in ('keep identical data-block', 'read to old existing address',
                                                'read at new address')):
            raise RuntimeError('Native undo decision log unavailable')
        deleted = [row['image']['pointer'] for row in oracle if row['event'] == 'delete_expected']
        result = Capture(directory, self).execute(deleted, full_history=False)
        if not result['free_stack']:
            raise RuntimeError('Deleted Blender Image allocation/free history missing')
        self.emit('canary_verified', setter_count=self.setter_verified, completed=self.completed_setters,
                  layout=self.layout, source=source)
        self.kill_disposable()
        self.canary = False

    def save_session(self, **fields):
        self.session.update(fields)
        write_json(self.root / 'session.json', self.session)

    def package(self):
        from pg_undo_trace_collect import collect_session
        archive = collect_session(self.root)
        print('\nReport ZIP: ' + str(archive), flush=True)
        return archive

    def log_capture_error(self, stage, error):
        """Best-effort error reporting must not mask the original native failure."""
        message = '{}: {}: {}'.format(stage, type(error).__name__, error)
        try:
            with (self.root / 'capture-errors.log').open('a', encoding='utf8') as stream:
                stream.write(message + '\n')
                stream.flush()
        except Exception:
            pass
        try:
            print('Perceptual Grade capture error: ' + message, file=sys.stderr, flush=True)
        except Exception:
            pass

    def snapshot_fault_best_effort(self):
        """Persist stopped native state before history queries or archive work."""
        if not self.is_stopped():
            return False
        path = self.root / 'fault' / 'native.json'
        if path.exists():
            return True
        try:
            write_json(path, self.snapshot())
            return True
        except Exception as error:
            self.log_capture_error('fault snapshot', error)
            return False

    def capture_first_fault(self):
        self.first_fault_seen = True
        self.snapshot_fault_best_effort()
        try:
            self.emit('first_native_fault', snapshot='fault/native.json')
        except Exception as error:
            self.log_capture_error('record first-fault marker', error)
        try:
            self.save_session(status='capturing-fault',
                              mandatory_artifacts=self.session['mandatory_artifacts'] +
                              ['fault/native.json', 'fault/summary.json'])
        except Exception as error:
            self.log_capture_error('save first-fault session state', error)
        print('Native fault stopped. Capturing stacks and live allocation histories; keep Terminal open.', flush=True)
        addresses = self.last_candidates + list(reversed(self.images))
        # A setter fault supplies its pending old/new links. Other faults may
        # involve an unknown address, so preserve full history as well.
        result = Capture(self.root, self).execute(addresses, full_history=True,
                                                 force_graph=not bool(self.pending))
        self.save_session(status='fault-paused',
                          mandatory_artifacts=self.session['mandatory_artifacts'],
                          causal_evidence=dict(publication=bool(self.edges),
                                               undo_decision='recorded; requires timeline correlation',
                                               free_stack='history available; requires resource correlation'
                                               if result['free_stack'] else False,
                                               surviving_link='raw snapshots; requires lifetime correlation'))
        self.package()
        self.keep_paused()

    def handle_driver_failure(self, error):
        """Capture/ZIP failures still leave an explicitly paused, inspectable target."""
        self.log_capture_error('capture driver', error)
        try:
            if self.process and self.process.GetState() == lldb.eStateRunning:
                self.process.Stop()
                self.wait_stop(10)
        except Exception as stop_error:
            self.log_capture_error('stop target after driver failure', stop_error)
        self.snapshot_fault_best_effort()
        try:
            status = 'fault-capture-incomplete' if self.first_fault_seen else 'driver-error'
            self.save_session(status=status, error=str(error))
        except Exception as session_error:
            self.log_capture_error('save driver-error session state', session_error)
        if not (self.root / 'fault' / 'summary.json').exists():
            try:
                write_json(self.root / 'fault' / 'summary.json',
                           dict(artifact_complete=False,
                                limitations=['Capture driver error: ' + str(error)]))
            except Exception as summary_error:
                self.log_capture_error('write incomplete capture summary', summary_error)
        try:
            self.package()
        except Exception as package_error:
            self.log_capture_error('package capture after driver failure', package_error)
            print('Evidence was not packaged; original session directory: ' + str(self.root)
                  + '. While Blender is paused, use "pack" to retry or "quit" to terminate.',
                  file=sys.stderr, flush=True)
        if self.is_stopped():
            self.keep_paused()
        else:
            print('Blender is no longer available in a stopped state. Original evidence: '
                  + str(self.root), file=sys.stderr, flush=True)

    def reproduce(self):
        args = list(self.config.get('project_args', [])) + [
            '--log', 'undo', '--log-level', 'debug', '--log-show-source',
            '--log-file', str(self.root / 'native-undo.log'),
            '--python', str(TOOLS / 'pg_undo_trace.py')]
        self.launch(self.config['blender'], args, self.root, 'reproduction')
        if self.module_identity()['uuid'] != UUID:
            raise RuntimeError('Executable changed after preflight')
        self.hooks()
        self.save_session(blender_pid=self.pid, status='recording',
                          mandatory_artifacts=['session.json', 'config.json', 'preflight.json',
                                               'native-events.jsonl', 'native-undo.log', 'launcher-console.log'])
        print('Preflight passed. Blender is recording; reproduce reset/undo/redo now.', flush=True)
        while True:
            self.resume()
            try:
                self.wait_stop()
            except RuntimeError:
                if self.process.GetState() == lldb.eStateExited:
                    self.save_session(status='exited', exit_status=self.process.GetExitStatus())
                    self.package()
                    return
                raise
            if any(native_fault(thread) for thread in self.process):
                self.capture_first_fault()
                return
            if not self.handle_breaks():
                self.emit('unexpected_stop', snapshot=self.snapshot())
                self.save_session(status='unexpected-stop')
                self.package()
                self.keep_paused()
                return

    def keep_paused(self):
        print('Blender remains stopped and alive. Type "pack" to collect again or "quit" to terminate.', flush=True)
        while self.is_stopped():
            try:
                command = input('pg-capture (paused)> ').strip().lower()
            except EOFError:
                # Return control to interactive LLDB without detaching the target.
                print('Input closed; target remains selected and paused in LLDB.', flush=True)
                return
            except KeyboardInterrupt:
                print('\nBlender remains paused. Use pack or quit.', flush=True)
                continue
            if command == 'quit':
                self.process.Kill()
                self.save_session(status='terminated-after-capture')
                return
            if command == 'pack':
                try:
                    self.package()
                except Exception as error:
                    self.log_capture_error('manual package retry', error)
                    print('Packaging failed. Blender remains paused; correct the problem and retry "pack".',
                          file=sys.stderr, flush=True)
            else:
                print('Use pack or quit. Blender has not resumed.', flush=True)

    def run(self):
        self.debugger.SetAsync(True)
        try:
            print('Preflight: checking live native allocation/free histories.', flush=True)
            self.allocation_preflight()
            print('Preflight: validating exact Blender layouts, assignments, and undo logs.', flush=True)
            self.blender_preflight()
            write_json(self.root / 'preflight.json', dict(status='passed', layout=self.layout,
                                                        blender_sha256=sha256(self.config['blender']),
                                                        build=BUILD, uuid=UUID, **clock_fields()))
        except Exception as error:
            self.log_capture_error('preflight', error)
            try:
                write_json(self.root / 'preflight.json', dict(status='failed', error=str(error), **clock_fields()))
            except Exception as record_error:
                self.log_capture_error('save failed preflight result', record_error)
            try:
                self.emit('preflight_failed', error=str(error))
            except Exception as record_error:
                self.log_capture_error('record failed preflight event', record_error)
            # These targets contain factory data only. Never launch the user's file.
            try:
                self.kill_disposable()
            except Exception as cleanup_error:
                self.log_capture_error('dispose failed preflight target', cleanup_error)
            try:
                self.save_session(status='preflight-failed', error=str(error))
            except Exception as record_error:
                self.log_capture_error('save failed preflight session', record_error)
            try:
                self.package()
            except Exception as package_error:
                self.log_capture_error('package failed preflight', package_error)
                print('Preflight report packaging failed. Original evidence: ' + str(self.root), flush=True)
            print('Preflight failed; your project was not opened. ' + str(error), flush=True)
            return
        try:
            self.reproduce()
        except (Exception, KeyboardInterrupt) as error:
            try:
                self.emit('capture_driver_error', error=str(error))
            except Exception as event_error:
                self.log_capture_error('record driver error event', event_error)
            self.handle_driver_failure(error)


def run(debugger, command, result, internal_dict):
    root = os.environ.get('PG_UNDO_TRACE_SESSION_DIR')
    if not root:
        result.SetError('Use pg_undo_trace_macos.command to create a capture session')
        return
    # Kept reachable so the selected target and external observations survive return.
    global ACTIVE
    ACTIVE = Driver(debugger, root)
    ACTIVE.run()


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand('command script add -f pg_undo_trace_lldb.run pg-undo-run')
