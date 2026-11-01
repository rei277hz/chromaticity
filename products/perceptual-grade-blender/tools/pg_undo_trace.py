"""Record intermittent Reset Stage -> Ctrl-Z crashes from Blender's Text Editor.

Run with ACTION = 'record', then reproduce normally (repeated attempts are OK).
Standalone reports go to Desktop/perceptual-grade-undo-trace-<time>-<pid>-<unique>/.
The macOS launcher groups recorder reruns in its launch directory and packages
them automatically while LLDB holds Blender at its first native fault.
After a crash, restart Blender, change ACTION to 'collect', and run again to ZIP
that session and recent Blender/macOS native crash-report candidates. Collection
does not require the extension to be enabled. Set REPORT_DIR to select a session.

To finish without a crash, set ACTION = 'collect' and run again, or use:
    import sys; sys.modules['_pg_undo_trace_state'].collect()
To stop without collecting:
    import sys; sys.modules['_pg_undo_trace_state'].stop()

No project saving, grade changes, or production wrappers. Operation-only tracing
never inspects monitored locals, return values, exceptions, or RNA identities.
The macOS LLDB companion obtains native identities outside the target process.
The recorder changes process-global diagnostic hooks and redirects stdout/stderr.
It can affect timing. Python 3.12+ supplies detailed monitoring; earlier versions
still get boundary events and stack dumps. Python stacks are not C/C++ stacks.
"""

ACTION = 'record'                   # 'record', 'collect', or 'stop'
REPORT_DIR = None                  # None = launch directory, otherwise Desktop
STACK_INTERVAL_SECONDS = 5.0       # Native watchdog; 0 disables periodic dumps
CAPTURE_CONSOLE = True             # Captures native messages as well as Python


def _implementation():
    # A private closure survives Blender Text Editor reusing __main__ globals
    # for unrelated scripts or repeated runs. State never lives in driver_namespace.
    import datetime
    import dis
    import faulthandler
    import hashlib
    import json
    import marshal
    import os
    from pathlib import Path
    import shutil
    import sys
    import threading
    import time
    import types
    import zipfile
    implementation_code = sys._getframe().f_code

    state_module = '_pg_undo_trace_state'
    boundaries = ('undo_pre', 'undo_post', 'redo_pre', 'redo_post', 'load_pre', 'load_post',
                  'save_pre', 'save_post', 'save_post_fail')
    watched_modules = {
        'graph.lut': ('adopt_native', '_output_snapshot', '_manifest',
                      'validate_output', 'read_cube', 'publish', 'commit_rows',
                      '_publication_checkpoint', 'image_for', 'request', '_graph_snapshot',
                      '_restore_graph', 'make_kernel', 'compositor_helper', 'shader_helper',
                      'clear', 'tick'),
        'graph.nodes': ('undo_redo_pre_handler', 'reset_cache_handler',
                        'write_chromatic', 'write_tone', 'reset_linear',
                        'refresh_all', 'clear_transient_caches', 'suspend_handler',
                        'recovery_tick', 'retry_recovery', '_retirement_ready',
                        'refresh_node', 'poll_working_space', 'assign_kernel'),
        'graph.output_resources': ('current_image', 'selected_index', 'bank_images',
                                   'validate_layout', 'adopt_native', 'request_intent',
                                   'pack_image', 'record'),
        'graph.bake': ('begin_replacement', 'fence_runtime', 'retire_replaced_state',
                       'runtime_reconcile', 'physical_retired', '_finish_fenced'),
        'graph.grades': ('release_node_references',),
        'blender_runtime.blender.native': ('remove_image', 'remove_node_group', 'remove_node', 'keys'),
        'ownership.transactions': ('repair_all', 'require_clean', 'id_key', 'node_key'),
        'blender_runtime.ownership.arena': ('begin_boundary', 'native_replaced', 'recovered', 'retire',
                            'retire_datablock'),
        'ui.diagram': ('settle_drags', 'end_color_drag'),
    }
    # Match loaded source, not hardcoded line numbers. Full loaded bytecode and
    # selected source are exported so each checkpoint remains reviewable.
    hotspots = {
        'graph.lut.image_for': ('tree=node.node_tree', 'kernel_nodes=', 'image=item.image',
                               'if image is not None'),
        'graph.lut._output_snapshot': ('tree=node.node_tree', 'kernel_nodes=',
                                      'images.append', 'return tree'),
        'graph.lut._manifest': ('image=None', 'if image is None', 'size=image.get',
                               "image.get('_pg_cube_schema')", 'or encoding not in',
                               'expected=', 'return dict'),
        'graph.lut.read_cube': ('image.get(', 'size=', 'encoding=', 'cached=', 'return cube'),
        'graph.lut._graph_snapshot': ('route=', 'return dict'),
        'graph.lut.request': ('failure_key=', 'valid_image=', 'if valid_image'),
        'graph.lut.publish': ('old=image_for', 'snapshot=', 'staged=[]',
                              "_publication_checkpoint('cleanup')", 'if old is not None'),
        'graph.lut.publish.install': ('staged.append(image)', 'helper=compositor_helper',
                                     '_publication_checkpoint(', 'return image'),
        'graph.lut.publish.rollback': ('for image in staged', 'if image.users'),
        'graph.lut.make_kernel': ('tree[nodes.KERNEL]',),
        'graph.lut.compositor_helper': ("if kind=='Address'",),
    }

    def write_all(fd, data):
        while data:
            count = os.write(fd, data)
            if count <= 0:
                raise OSError('Trace write did not advance')
            data = data[count:]

    def write_json(path, value):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            write_all(fd, (json.dumps(value, ensure_ascii=True, indent=2) + '\n').encode())
        finally:
            os.close(fd)

    def stack_locations():
        # Copy only locations. Never read locals, repr RNA, or retain a frame.
        frame = sys._getframe(1)
        result = []
        try:
            while frame is not None and len(result) < 64:
                result.append(dict(file=frame.f_code.co_filename,
                                   function=frame.f_code.co_name, line=frame.f_lineno))
                frame = frame.f_back
        finally:
            del frame
        return result

    def discover():
        found = []
        for name, module in tuple(sys.modules.items()):
            if name.endswith('.perceptual_grade_blender.integration.lifecycle') and module is not None:
                application = module.registered_session()
                if application is not None:
                    found.append((name.removesuffix('.integration.lifecycle'), application.component('graph.lut')))
        if len(found) != 1:
            raise RuntimeError('Enable one Perceptual Grade extension first; found: '
                               + str([prefix for prefix, _ in found]))
        return found[0]

    class _Trace:
        def __init__(self, prefix, lut, output_dir):
            self.prefix = prefix
            self.application = sys.modules[prefix + '.integration.lifecycle'].registered_session()
            self.path = Path(output_dir).expanduser().resolve()
            self.package = Path(lut.__file__).absolute().parents[2]
            self.watched = {}
            self.code_maps = {}
            self.operation_sites = {}
            self.line_sites = {}
            self.roots = set()
            self.active = {}
            self.calls = {}
            self.call_sequence = 0
            self.generation = 0
            self.boundary_sequence = 0
            self.boundary_id = None
            self.fds = {}
            self.saved_console = {}
            self.hooks = []
            self.tool_id = None
            self.callbacks = {}
            self.closed = False
            self.sequence = 0
            self.write_failed = False
            self.fatal_attached = False
            self.watchdog_attached = False
            self.previous_fatal = faulthandler.is_enabled()
            self.started = time.time()
            self.clock_origin = dict(wall_time_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())
            session_dir = os.environ.get('PG_UNDO_TRACE_SESSION_DIR')
            self.native_session_dir = Path(session_dir).expanduser().resolve() if session_dir else None
            self.launch_id = os.environ.get('PG_UNDO_TRACE_LAUNCH_ID')
            undo_log = os.environ.get('PG_UNDO_TRACE_UNDO_LOG')
            self.native_undo_log = (Path(undo_log).expanduser().resolve() if undo_log else
                                    self.native_session_dir / 'native-undo.log'
                                    if self.native_session_dir is not None else None)

            def add(function, label, root=False):
                while isinstance(function, types.FunctionType) and hasattr(function, '__wrapped__'):
                    function = function.__wrapped__
                code = getattr(function, '__code__', None)
                if not isinstance(code, types.CodeType):
                    return
                def add_code(code, label):
                    # Yielding code does not have a synchronous call lifetime.
                    # PY_START/PY_RETURN alone would leave phantom parents while
                    # a generator is suspended; never retain/monitor its frame.
                    if code.co_flags & (0x20 | 0x80 | 0x200):
                        return
                    self.watched[code] = label
                    try:
                        source = Path(code.co_filename).read_text().splitlines()
                    except (OSError, UnicodeError):
                        source = []
                    instructions = list(dis.get_instructions(code))
                    lines = {line for _, _, line in code.co_lines() if line is not None}
                    selected = {n: source[n - 1] for n in sorted(lines) if 0 < n <= len(source)}
                    self.line_sites[code] = ({n for n, s in selected.items()
                                             if any(token in s for token in hotspots[label])}
                                            if label in hotspots else set())
                    sites = {}
                    for instruction in instructions:
                        op, attr = instruction.opname, instruction.argval
                        pos = instruction.positions
                        source_line = selected.get(pos.lineno, '')
                        # Only these functions need opcode events. Observe the
                        # native operation itself, including one-line store loops.
                        if (op == 'STORE_ATTR' and attr in ('image', 'node_tree')
                                or op == 'LOAD_ATTR' and attr in ('image', 'node_tree')
                                or op == 'CALL' and label == 'graph.lut.request'
                                and "valid_image=image is not None" in source_line):
                            sites[instruction.offset] = dict(op=op, attribute=attr if op != 'CALL' else None,
                                                             line=pos.lineno, column=pos.col_offset)
                    self.operation_sites[code] = sites
                    self.code_maps[code] = dict(label=label, file=code.co_filename,
                        first_line=code.co_firstlineno,
                        code_id=hashlib.sha256(marshal.dumps(code)).hexdigest(),
                        source=selected, observed_lines=sorted(self.line_sites[code]),
                        native_operations=sites,
                        instructions=[dict(offset=i.offset, op=i.opname, argument=i.argrepr,
                            line=i.positions.lineno, end_line=i.positions.end_lineno,
                            column=i.positions.col_offset, end_column=i.positions.end_col_offset)
                            for i in instructions])
                    for child in code.co_consts:
                        if isinstance(child, types.CodeType):
                            add_code(child, label + '.' + child.co_name)
                add_code(code, label)
                if root:
                    self.roots.add(code)

            for suffix, names in watched_modules.items():
                if suffix == 'blender_runtime.blender.native':
                    module = self.application.app.blender.native
                elif suffix == 'blender_runtime.ownership.arena':
                    module = self.application.app.ownership
                else:
                    module = self.application.component(suffix)
                for name in names:
                    add(getattr(module, name, None), suffix + '.' + name,
                        name in ('adopt_native', 'undo_redo_pre_handler', 'reset_cache_handler'))
            panel = self.application.component('ui.panel')
            component_items = sys.modules[self.prefix + '.integration.components'].component_items
            if panel is not None:
                for name, cls in component_items(self.application._component('ui.panel')):
                    if name.startswith('PG_OT_reset') and isinstance(cls, type):
                        add(getattr(cls, 'execute', None), 'ui.panel.' + name + '.execute', True)
            diagram = self.application.component('ui.diagram')
            cls = getattr(diagram, 'PG_OT_diagram_drag', None)
            add(getattr(cls, 'reset_dragged', None), 'ui.diagram.reset_dragged', True)
            grades = self.application.component('graph.grades')
            for name, cls in component_items(self.application._component('graph.grades')) if grades else ():
                if isinstance(cls, type) and name.startswith('Grade'):
                    for method in ('copy', 'free'):
                        add(getattr(cls, method, None), 'graph.grades.' + name + '.' + method)

        def emit(self, event, **values):
            if self.closed or self.write_failed or 'events' not in self.fds:
                return
            try:
                native_undo_bytes = None
                if self.native_undo_log is not None:
                    try:
                        native_undo_bytes = self.native_undo_log.stat().st_size
                    except OSError:
                        pass
                self.sequence += 1
                row = dict(sequence=self.sequence, monotonic_ns=time.monotonic_ns(),
                           wall_time=time.time(), thread=threading.get_ident(), event=event,
                           generation=self.generation, boundary_id=self.boundary_id,
                           launch_id=self.launch_id, native_undo_bytes=native_undo_bytes,
                           console_bytes=os.fstat(self.fds['console']).st_size if 'console' in self.fds else 0,
                           **values)
                # All callers construct scalars or containers of scalar locations.
                write_all(self.fds['events'], (json.dumps(row, ensure_ascii=True) + '\n').encode())
            except BaseException:
                # Diagnostics must not change the monitored operation's behavior.
                self.write_failed = True

        def _frame(self, code):
            frame = sys._getframe(1)
            while frame is not None and frame.f_code is not code:
                frame = frame.f_back
            return frame

        def _call(self, code):
            calls = self.calls.get(threading.get_ident(), ())
            return calls[-1] if calls and calls[-1]['code'] is code else None

        def _start_event(self, code, offset):
            try:
                if self.closed:
                    return
                tid = threading.get_ident()
                calls = self.calls.setdefault(tid, [])
                self.call_sequence += 1
                frame = self._frame(code)
                try:
                    caller = frame.f_back if frame else None
                    origin = dict(file=caller.f_code.co_filename, line=caller.f_lineno,
                                  instruction=caller.f_lasti) if caller else None
                finally:
                    del frame, caller
                call = dict(id=self.call_sequence, code=code,
                            parent=calls[-1]['id'] if calls else None)
                calls.append(call)
                if code in self.roots:
                    self.active[tid] = self.active.get(tid, 0) + 1
                self.emit('function_enter', function=self.watched[code], instruction=offset,
                          code_id=self.code_maps[code]['code_id'], call_id=call['id'],
                          parent_call_id=call['parent'], caller=origin, stack=stack_locations())
            except BaseException:
                pass

        def _finish_event(self, code, offset, _value):
            try:
                if self.closed:
                    return
                tid = threading.get_ident()
                call = self._call(code)
                if call is not None:
                    # PY_RETURN precedes frame teardown. Do not inspect _value:
                    # it may itself be a damaged native wrapper.
                    self.emit('return_requested', function=self.watched[code], instruction=offset,
                              call_id=call['id'])
                    self.calls[tid].pop()
                if code in self.roots:
                    self._leave(tid)
            except BaseException:
                pass

        def _leave(self, tid):
            depth = self.active.get(tid, 0) - 1
            if depth > 0:
                self.active[tid] = depth
            else:
                self.active.pop(tid, None)

        def _line_event(self, code, line):
            try:
                detailed = line in self.line_sites[code]
                if self.closed or not (detailed or self.active.get(threading.get_ident(), 0)):
                    return
                call = self._call(code)
                if call is not None:
                    self.emit('line', function=self.watched[code], line=line, call_id=call['id'])
            except BaseException:
                pass

        def _instruction_event(self, code, offset):
            try:
                if self.closed:
                    return
                call = self._call(code)
                if call is None:
                    return
                pending = call.pop('native_pending', None)
                if pending is not None:
                    self.emit('native_operation_returned', call_id=call['id'], instruction=pending,
                              next_instruction=offset)
                site = self.operation_sites[code].get(offset)
                if site is not None:
                    self.emit('native_operation_before', call_id=call['id'], function=self.watched[code],
                              instruction=offset, operation=site)
                    call['native_pending'] = offset
            except BaseException:
                pass

        def _exception_event(self, event, code, offset, _exception):
            try:
                if self.closed or code not in self.watched:
                    return
                tid = threading.get_ident()
                call = self._call(code)
                if call is not None:
                    # No type-name, traceback, repr or other observation of
                    # _exception: only independently safe execution locations.
                    self.emit(event, function=self.watched[code], instruction=offset,
                              call_id=call['id'], stack=stack_locations())
                    pending = call.pop('native_pending', None)
                    if pending is not None:
                        self.emit('native_operation_raised', call_id=call['id'], instruction=pending,
                                  mutation_outcome='unknown')
                    if event == 'python_unwind':
                        self.calls[tid].pop()
                if event == 'python_unwind' and code in self.roots:
                    self._leave(tid)
            except BaseException:
                pass

        def _monitor(self):
            monitor = getattr(sys, 'monitoring', None)
            if monitor is None:
                self.emit('detailed_monitoring_unavailable', reason='Requires Python 3.12+')
                return
            for tool in (3, 4):
                if monitor.get_tool(tool) is None:
                    try:
                        monitor.use_tool_id(tool, 'Perceptual Grade crash recorder')
                    except ValueError:
                        continue
                    self.tool_id = tool
                    break
            if self.tool_id is None:
                self.emit('detailed_monitoring_unavailable', reason='No free diagnostic monitoring ID (3/4)')
                return
            events = monitor.events
            self.callbacks = {
                events.PY_START: self._start_event,
                events.PY_RETURN: self._finish_event,
                events.LINE: self._line_event,
                events.INSTRUCTION: self._instruction_event,
                events.RAISE: lambda c, o, e: self._exception_event('python_raise', c, o, e),
                events.PY_UNWIND: lambda c, o, e: self._exception_event('python_unwind', c, o, e),
            }
            for event, callback in self.callbacks.items():
                monitor.register_callback(self.tool_id, event, callback)
            # Exception/unwind events are GLOBAL-only; callbacks filter immediately.
            monitor.set_events(self.tool_id, events.RAISE | events.PY_UNWIND)
            for code in self.watched:
                monitor.set_local_events(self.tool_id, code,
                    events.PY_START | events.PY_RETURN | events.LINE
                    | (events.INSTRUCTION if self.operation_sites[code] else 0))

        def _handlers(self):
            import bpy
            for name in boundaries:
                collection = getattr(bpy.app.handlers, name, None)
                if collection is None:
                    continue
                def observer(position, boundary):
                    @bpy.app.handlers.persistent
                    def callback(*_args):
                        try:
                            if position == 'enter' and boundary.endswith('_pre'):
                                self.boundary_sequence += 1
                                self.boundary_id = self.boundary_sequence
                                if boundary != 'save_pre':
                                    self.generation += 1
                            self.emit('boundary_' + boundary + '_' + position,
                                      stack=stack_locations())
                        except BaseException:
                            pass
                    return callback
                head, tail = observer('enter', name), observer('completed', name)
                collection.insert(0, head)
                collection.append(tail)
                self.hooks.extend(((name, head), (name, tail)))

        def _metadata(self, interval, capture_console):
            bpy = sys.modules.get('bpy')
            app = getattr(bpy, 'app', None)
            build = getattr(app, 'build_hash', b'')
            data = dict(schema=4, created=datetime.datetime.now().astimezone().isoformat(),
                        started_epoch=self.started, pid=os.getpid(), python=sys.version,
                        platform=sys.platform, module=self.prefix, package=str(self.package),
                        blender=list(getattr(app, 'version', ())),
                        blender_build=build.decode(errors='replace') if isinstance(build, bytes) else str(build),
                        blender_tempdir=str(getattr(app, 'tempdir', '')),
                        blend_filepath=str(getattr(getattr(bpy, 'data', None), 'filepath', '')),
                        source_sha256={p.relative_to(self.package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(self.package.rglob('*.py')) if p.is_file()},
                        watched_code_sha256={label + ':' + str(code.co_firstlineno) + ':' + self.code_maps[code]['code_id']: self.code_maps[code]['code_id']
                                             for code, label in self.watched.items()},
                        monitoring_tool=self.tool_id, interval_seconds=interval,
                        capture_console=capture_console, prior_faulthandler=self.previous_fatal,
                        prior_profiler_present=sys.getprofile() is not None,
                        recorder_version=4, tracing_mode='operation-only',
                        launch_id=self.launch_id, clock_origin=self.clock_origin,
                        native_session_dir=str(self.native_session_dir) if self.native_session_dir else None,
                        native_undo_log=str(self.native_undo_log) if self.native_undo_log else None,
                        recorder_implementation_sha256=hashlib.sha256(
                            marshal.dumps(implementation_code)).hexdigest(),
                        allocator_environment={key: os.environ.get(key) for key in
                            ('MallocStackLogging', 'MallocStackLoggingNoCompact', 'MallocStackLoggingDirectory')},
                        locals_available=False, native_identity_fields=[],
                        value_inspection=False,
                        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                        if '__file__' in globals() and Path(__file__).is_file() else None)
            write_json(self.path / 'metadata.json', data)
            write_json(self.path / 'code-map.json', list(self.code_maps.values()))

        def start(self, interval=5.0, capture_console=True, handlers=True):
            if interval < 0:
                raise ValueError('Stack interval must be nonnegative')
            self.path.mkdir(parents=True, exist_ok=False)
            os.chmod(self.path, 0o700)
            try:
                for name, filename in (('events', 'events.jsonl'), ('fatal', 'fatal-python.txt'),
                                       ('periodic', 'periodic-python.txt'), ('console', 'console.log')):
                    self.fds[name] = os.open(self.path / filename,
                                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
                if capture_console:
                    for target in (1, 2):
                        self.saved_console[target] = os.dup(target)
                        os.dup2(self.fds['console'], target)
                faulthandler.enable(file=self.fds['fatal'], all_threads=True)
                self.fatal_attached = True
                if interval:
                    faulthandler.dump_traceback_later(interval, repeat=True,
                                                     file=self.fds['periodic'], exit=False)
                    self.watchdog_attached = True
                self._monitor()
                if handlers:
                    self._handlers()
                self._metadata(interval, capture_console)
                (self.path / 'README.txt').write_text(
                    'Perceptual Grade reset/undo crash recording\n\n'
                    'Recorder v4: operation-only Python execution tracing.\n'
                    'events.jsonl: call relationships, source operations, boundaries and stack locations.\n'
                    'No monitored locals, return values, exception contents/types or RNA identities are inspected.\n'
                    'Native resource identities and lifetimes belong to the external debugger capture.\n'
                    'call_id/parent_call_id correlate calls; generation labels native replacement boundaries.\n'
                    'launch_id and clock_origin correlate recordings within one native launch.\n'
                    'console_bytes/native_undo_bytes bound log positions (buffering may delay writes).\n'
                    'native_operation_before/returned bracket actual bytecode operations; on raise mutation is unknown.\n'
                    'return_requested is BEFORE frame teardown, without observing the return value.\n'
                    'boundary_*_completed: this observer ran after the preceding handlers; exceptions in\n'
                    'earlier handlers may have been printed and ignored by Blender.\n'
                    'fatal-python.txt: fatal-signal Python stacks, not native C/C++ backtraces.\n'
                    'periodic-python.txt: all-thread Python stacks from a native watchdog.\n'
                    'console.log: stdout/stderr, including flushed native error messages.\n'
                    'metadata.json: installed source hashes, build, clock origin and report lookup paths.\n'
                    'code-map.json: loaded code hashes, exact bytecode offsets/positions and source excerpts.\n'
                    'Direct append writes survive process abort, not necessarily power loss.\n\n'
                    'The native launcher packages automatically while Blender is paused at its first fault.\n'
                    'For standalone recording, rerun with ACTION = "collect" after restart to create a ZIP.\n'
                    'Native reports in native-reports/ are time-filtered candidates; check PID and time.\n'
                    'No native report is guaranteed; an OS kill may leave no fatal stack either.\n'
                    'This script changes diagnostic hooks and may change timing. No monitored objects,\n'
                    'frames, local proxies, return values or exceptions are retained.\n'
                    'Native allocation/free history requires launching Blender with the macOS companion;\n'
                    'it cannot be enabled retroactively by this script. Collection lists missing/skipped logs.\n'
                    'Detailed events follow code loaded at installation; rerun after addon reload.\n'
                    'The process-global watchdog replaces any previous schedule. Stop cannot recover it.\n'
                    'If faulthandler was already enabled, stop restores it to stderr: its prior\n'
                    'destination is not discoverable through Python. Console redirection is restored\n'
                    'only if still owned. Console capture may include other addons\' output and paths.\n',
                    encoding='utf8')
                self.emit('installed', interval_seconds=interval, monitoring_tool=self.tool_id)
            except BaseException:
                self.stop()
                raise
            return self.path

        def stop(self):
            # Each resource is independent: a third-party hook or closed console
            # fd must not prevent detaching the fatal handler/watchdog. Failed
            # cleanup remains retryable and keeps any still-referenced fd alive.
            if not self.closed:
                self.emit('stopped', write_failed=self.write_failed)
                self.closed = True
            self.cleanup_errors = []

            def attempt(label, operation):
                try:
                    operation()
                    return True
                except BaseException as error:
                    self.cleanup_errors.append(label + ': ' + type(error).__name__)
                    return False

            if self.tool_id is not None:
                monitor = sys.monitoring
                clean = True
                for code in self.watched:
                    clean &= attempt('monitor local',
                                     lambda: monitor.set_local_events(self.tool_id, code, 0))
                clean &= attempt('monitor global', lambda: monitor.set_events(self.tool_id, 0))
                for event in self.callbacks:
                    clean &= attempt('monitor callback',
                                     lambda: monitor.register_callback(self.tool_id, event, None))
                if clean and attempt('monitor tool', lambda: monitor.free_tool_id(self.tool_id)):
                    self.callbacks.clear()
                    self.tool_id = None
            self.active.clear()
            self.calls.clear()
            bpy = sys.modules.get('bpy')
            remaining = []
            for name, callback in self.hooks:
                def remove():
                    collection = getattr(bpy.app.handlers, name)
                    if callback in collection:
                        collection.remove(callback)
                if not attempt('handler ' + name, remove):
                    remaining.append((name, callback))
            self.hooks = remaining
            if self.watchdog_attached and attempt('watchdog', faulthandler.cancel_dump_traceback_later):
                self.watchdog_attached = False
            if self.fatal_attached and attempt('fatal handler', faulthandler.disable):
                self.fatal_attached = False
            for stream in (sys.stdout, sys.stderr):
                if stream is not None:
                    attempt('console flush', lambda stream=stream: stream.flush())
            for target, saved in tuple(self.saved_console.items()):
                def restore():
                    try:
                        current = os.fstat(target)
                    except OSError:
                        current = None  # Another tool may have closed stdout/stderr.
                    owned = os.fstat(self.fds['console'])
                    if current is None or (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                        os.dup2(saved, target)
                    os.close(saved)
                if attempt('console restore', restore):
                    del self.saved_console[target]
            if self.previous_fatal and not self.fatal_attached:
                if attempt('prior fatal handler', lambda: faulthandler.enable(file=2, all_threads=True)):
                    self.previous_fatal = False
            for name, fd in tuple(self.fds.items()):
                if ((name == 'fatal' and self.fatal_attached)
                        or (name == 'periodic' and self.watchdog_attached)
                        or (name == 'console' and self.saved_console)):
                    continue
                if attempt('close ' + name, lambda: os.close(fd)):
                    del self.fds[name]

    def stop():
        state = sys.modules.get(state_module)
        trace = getattr(state, 'trace', None)
        if trace is not None:
            trace.stop()

    def desktop():
        path = Path.home() / 'Desktop'
        path.mkdir(exist_ok=True)
        return path

    def install(output_dir=None, interval=5.0, capture_console=True):
        prefix, lut = discover()
        stop()
        prior = getattr(sys.modules.get(state_module), 'trace', None)
        if prior is not None and (prior.fds or prior.hooks or prior.tool_id is not None
                                  or prior.previous_fatal):
            raise RuntimeError('Previous recorder cleanup is incomplete; retry its stop(). '
                               + str(prior.cleanup_errors))
        if output_dir is None:
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            unique = stamp + '-' + str(os.getpid()) + '-' + str(time.time_ns())
            native_session = os.environ.get('PG_UNDO_TRACE_SESSION_DIR')
            if native_session:
                session_root = Path(native_session).expanduser().resolve()
                if not (session_root / 'session.json').is_file():
                    raise RuntimeError('Native launch session.json is missing: ' + str(session_root))
                output_dir = session_root / 'python' / ('recorder-' + unique)
            else:
                output_dir = desktop() / ('perceptual-grade-undo-trace-' + unique)
        trace = _Trace(prefix, lut, output_dir)
        state = types.ModuleType(state_module)
        state.trace = trace
        state.stop = trace.stop
        state.collect = lambda: collect_report(trace.path)
        sys.modules[state_module] = state
        trace.start(interval=interval, capture_console=capture_console)
        message = 'Perceptual Grade crash recorder active: ' + str(trace.path) + '\n'
        # Show path in Blender's Python Console, and original native console.
        print(message, flush=True)
        if 1 in trace.saved_console:
            write_all(trace.saved_console[1], message.encode())
        return trace.path

    def collect_report(directory=None):
        state = sys.modules.get(state_module)
        trace = getattr(state, 'trace', None)
        if directory is None and trace is not None:
            directory = trace.path
        if directory is None:
            candidates = [p for p in desktop().glob('perceptual-grade-undo-trace-*')
                          if p.is_dir() and (p / 'metadata.json').is_file()]
            if not candidates:
                raise RuntimeError('No crash recording found on Desktop; set REPORT_DIR explicitly.')
            directory = max(candidates, key=lambda p: p.stat().st_mtime)
        directory = Path(directory).expanduser().resolve()
        if trace is not None and directory == trace.path:
            trace.stop()
        # The diagnostic bundle always supplies its shared ZIP64 collector.
        metadata = (json.loads((directory / 'metadata.json').read_text())
                    if (directory / 'metadata.json').is_file() else {})
        session_root = directory if (directory / 'session.json').is_file() else None
        if metadata.get('native_session_dir'):
            candidate = Path(metadata['native_session_dir']).expanduser().resolve()
            if (candidate / 'session.json').is_file():
                session_root = candidate
        search_roots = []
        if os.environ.get('PG_UNDO_TRACE_TOOLS_DIR'):
            search_roots.append(Path(os.environ['PG_UNDO_TRACE_TOOLS_DIR']).expanduser())
        search_roots.append(Path(implementation_code.co_filename).absolute().parent)
        for root in search_roots:
            companion = root / 'pg_undo_trace_collect.py'
            if companion.is_file():
                from importlib.machinery import SourceFileLoader
                from importlib.util import module_from_spec, spec_from_loader
                loader = SourceFileLoader('_pg_undo_trace_collector', str(companion))
                module = module_from_spec(spec_from_loader(loader.name, loader))
                loader.exec_module(module)
                return module.collect_session(session_root or directory)
        raise RuntimeError('Keep pg_undo_trace_collect.py beside the recorder, or set '
                           'PG_UNDO_TRACE_TOOLS_DIR to the diagnostic bundle.')

    return dict(_STATE_MODULE=state_module, _Trace=_Trace, install=install,
                stop=stop, collect_report=collect_report)


globals().update(_implementation())

if __name__ == '__main__':
    if ACTION == 'record':
        install(output_dir=REPORT_DIR, interval=STACK_INTERVAL_SECONDS,
                capture_console=CAPTURE_CONSOLE)
    elif ACTION == 'collect':
        collect_report(REPORT_DIR)
    elif ACTION == 'stop':
        stop()
    else:
        raise ValueError('ACTION must be record, collect, or stop')
