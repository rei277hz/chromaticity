"""Run in Blender's Text Editor, then drag/release a Warp handle a few times.

Writes scalar JSONL events and installed Python source hashes to the Desktop;
does not save the project, change scheduling, or read helper authentication.
Run again to replace this tracer. Stop from the Python Console with:

    import sys; sys.modules['_pg_scope_trace_state'].stop()

Correlate scope_key across request/capture/submit/decode/publication/first draw,
and session + job_order + attempt + generation across execution events. A run
also records scope retirement and cancellation so continuous-drag publication
cadence and retirement-to-next-submission gaps can be measured before release.
The report attributes cadence to the edited node; dependent consumers require
their own attribution and shared draw keys are reported as ambiguous. A run
send-to-message interval includes IPC, scheduling and foreground polling, NOT
just worker computation. Message begin/end includes payload decoding/sealing;
scope_decode includes domain reconstruction (and any wait in result()). Draw
means the draw callback returned, not that the display presented a GPU frame.
Tracing adds overhead. Only explicitly named callbacks are wrapped; no profiler
or timer is installed, and no RNA, result, handle, exception or frame is retained.
"""

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import types


_STATE_MODULE = '_pg_scope_trace_state'
_LIMIT = 4096
_SCALARS = (str, int, float, bool, type(None))


def _text(value):
    return ''.join((str(value),))


def _write_all(fd, data):
    while data:
        count = os.write(fd, data)
        if count <= 0:
            raise OSError('Trace write did not advance')
        data = data[count:]


def _key_value(value):
    """Normalize numerical key scalars identically before/after the codec."""
    if type(value) in _SCALARS:
        return value
    if isinstance(value, (tuple, list)):
        return [_key_value(item) for item in value]
    module = type(value).__module__
    if is_dataclass(value) and ('.model.' in module or
                                module.endswith('.perceptual_grade_core.scopes.identity')):
        return [type(value).__name__, [[item.name, _key_value(getattr(value, item.name))]
                                     for item in fields(value)]]
    if type(value).__module__.startswith('numpy') and getattr(value, 'ndim', None) == 0:
        return _key_value(value.item())
    raise TypeError('Unsupported diagnostic key value: ' + type(value).__name__)


def _digest(value):
    return hashlib.sha256(json.dumps(_key_value(value), ensure_ascii=True,
                                    separators=(',', ':')).encode('utf8')).hexdigest()


def _discover():
    names = [name.removesuffix('.integration.lifecycle') for name, module in tuple(sys.modules.items())
             if name.endswith('.perceptual_grade_blender.integration.lifecycle')
             and module is not None and module.registered_session() is not None]
    if len(names) != 1:
        raise RuntimeError('Expected one enabled Perceptual Grade extension; found ' + str(names))
    return names[0]


def _runtime_values(prefix):
    lifecycle = sys.modules.get(prefix + '.integration.lifecycle')
    application = None if lifecycle is None else lifecycle.registered_session()
    runtime = None if application is None else application.app.execution.current_runtime()
    if runtime is None:
        return {}
    return dict(execution_fingerprint=_text(runtime.fingerprint),
                session=_text(runtime.session.identity), runtime_closed=bool(runtime.closed))


def _ticket(ticket):
    return dict(channel=_text(ticket.channel[0]), node_pointer=int(ticket.channel[1]),
                owner=int(ticket.owner), key=int(ticket.key), signal=int(ticket.signal),
                epoch=int(ticket.epoch), quality=int(ticket.quality), ticket=int(ticket.token),
                scheduler_session=int(ticket.session))


def _scope(spec):
    result = dict(scope_key=_digest(spec['key']))
    if spec.get('_schedule') is not None:
        result.update(_ticket(spec['_schedule']))
    return result


def _job(runtime, job):
    return dict(session=_text(runtime.session.identity), job_order=int(job.order),
                attempt=int(job.state.identity), generation=int(job.state.generation),
                operation=_text(job.spec.operation), role=_text(job.role))


def _handle(handle):
    return dict(_job(handle.runtime, handle._job), handle=int(handle.identity),
                finished=bool(handle._job.finished))


def _result_key(result):
    if result is None:
        return {}
    base = result.get('_base', result)
    values=dict(scope_key=_digest(base['_scope_key'])) if '_scope_key' in base else {}
    for name in ('_scope_part','_scope_request','_scope_stats_status'):
        if type(base.get(name)) in _SCALARS and name in base:
            values[name.removeprefix('_')]=base[name]
    return values


def _display_components(result):
    """Record component availability and separate identities, never fit arrays."""
    selected=result if isinstance(result,Mapping) else {}
    values=dict(cloud_available=bool(selected.get('_warp_clouds')),
                statistics_available=selected.get('neutral') is not None)
    for name in ('_visual_request','_statistics_request','_visual_epoch','_statistics_epoch',
                 '_visual_analysis','_statistics_analysis','_display_current'):
        if name in selected and type(selected[name]) in _SCALARS:
            values[name.removeprefix('_')]=selected[name]
    values['retained_statistics']=(values['statistics_available'] and
        selected.get('_statistics_request') is not None and
        selected.get('_statistics_request')!=selected.get('_visual_request'))
    return values


def _cloud_values(result):
    """Extract scalar-only raster metadata; never retain or serialize pixels."""
    if not isinstance(result, Mapping):
        return {}
    base = result.get('_base', result)
    bundle = result.get('_warp_clouds', result.get('warp_clouds'))
    if bundle is None and isinstance(base, Mapping):
        bundle = base.get('_warp_clouds', base.get('warp_clouds'))
    if bundle is None:
        return {}
    records = bundle if isinstance(bundle, (tuple, list)) else (bundle,)
    backend_counts = {}
    totals = dict(width=0, height=0, pixel_bytes=0, array_count=0,
                  views=0, tiles=0)
    timing_fields = ('preparation_seconds', 'compute_submission_seconds',
                     'raster_submission_seconds', 'readback_seconds',
                     'cpu_raster_seconds')
    timings = {name: 0.0 for name in timing_fields}
    view_keys = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        view = record.get('view', {})
        if not isinstance(view, Mapping):
            view = {}
        pixels = record.get('pixels')
        shape = getattr(pixels, 'shape', ())
        nbytes = getattr(pixels, 'nbytes', 0)
        if type(nbytes) is int and nbytes >= 0:
            totals['pixel_bytes'] += nbytes
            if nbytes:
                totals['array_count'] += 1
        if len(shape) >= 2:
            height, width = int(shape[-2]), int(shape[-1])
        else:
            height, width = int(view.get('height', 0)), int(view.get('width', 0))
        totals['width'] = max(totals['width'], width)
        totals['height'] = max(totals['height'], height)
        totals['views'] += 1
        totals['tiles'] += int(shape[0]) * int(shape[1]) if len(shape) == 4 else 0
        backend = record.get('backend')
        if type(backend) is str:
            backend_counts[backend] = backend_counts.get(backend, 0) + 1
        # Only the frozen value descriptor is hashed. The resulting string,
        # never the descriptor or pixel array, can be retained by the tracer.
        view_keys.append(_digest(tuple((name, view.get(name)) for name in
                                      ('key', 'width', 'height', 'rect', 'scale', 'bounds'))))
        metadata = record.get('timings', {})
        if isinstance(metadata, Mapping):
            for name in timing_fields:
                value = metadata.get(name)
                if type(value) in (int, float) and value >= 0:
                    timings[name] += float(value)
    values = {'cloud_view_count': totals['views'], 'cloud_tile_count': totals['tiles'],
              'cloud_pixel_bytes': totals['pixel_bytes'],
              'cloud_array_count': totals['array_count'],
              'cloud_width': totals['width'], 'cloud_height': totals['height']}
    if backend_counts:
        values['cloud_backend'] = ','.join(sorted(backend_counts))
    if view_keys:
        values['cloud_view_key'] = _digest(sorted(view_keys))
    for name in ('_warp_cpu_seconds', '_warp_cpu_reused'):
        if type(base.get(name)) in _SCALARS and name in base:
            values['cloud_' + name.removeprefix('_warp_')] = base[name]
    for name, value in timings.items():
        if value:
            values['cloud_' + name] = value
    return values


def _payload_values(value, prefix):
    """Count transport descriptors without mapping files or reading pixels."""
    arrays = total = 0
    def visit(item):
        nonlocal arrays, total
        if isinstance(item, dict):
            if '$array' in item:
                count = item.get('bytes')
                if type(count) is int and count >= 0:
                    arrays += 1
                    total += count
            else:
                for child in item.values():
                    visit(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child)
    visit(value)
    return {prefix + '_arrays': arrays, prefix + '_bytes': total}


def _view_values(plot, scale):
    try:
        rect = tuple(float(value) for value in plot.rect)
        values = dict(view_rect_width=rect[2], view_rect_height=rect[3],
                      view_xmin=float(plot.xmin), view_ymin=float(plot.ymin),
                      view_xmax=float(plot.xmax), view_ymax=float(plot.ymax),
                      view_scale=float(scale))
        if len(rect) >= 4:
            values.update(view_rect_x=rect[0], view_rect_y=rect[1])
        return values
    except Exception:
        return {}


class _Trace:
    def __init__(self, prefix, stem):
        self.prefix = prefix
        self.application = sys.modules[prefix + '.integration.lifecycle'].registered_session()
        self.path = stem.with_suffix('.jsonl')
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self.sequence = self.calls = 0
        self.closed = self.write_failed = False
        self.originals = {}
        self.hooks = []  # Python module/class paths and functions only, never RNA.
        self.requests = OrderedDict()
        self.drawn = OrderedDict()
        self.job_keys = OrderedDict()
        self.active_draw_fields = None
        self.component_state = None

    def emit(self, event, **values):
        if self.closed or self.write_failed:
            return
        try:
            if any(type(value) not in _SCALARS for value in values.values()):
                raise TypeError('Trace records accept exact scalar values only')
            self.sequence += 1
            record = dict(sequence=self.sequence, monotonic_ns=time.monotonic_ns(),
                          event=event, **values)
            _write_all(self.fd, (json.dumps(record, ensure_ascii=True) + '\n').encode('utf8'))
        except Exception:
            self.write_failed = True

    def values(self, extractor, *args):
        try:
            result = extractor(*args)
            if any(type(value) not in _SCALARS for value in result.values()):
                raise TypeError('Nonscalar extracted field')
            return result
        except Exception:
            self.emit('diagnostic_fields_unavailable', extractor=_text(extractor.__name__))
            return {}

    def remember(self, cache, key, value):
        # Callers supply strings, tuples of exact scalars, or scalar-only dicts.
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _LIMIT:
            cache.popitem(last=False)

    def start(self, event, values):
        self.calls += 1
        result = dict(values, call=self.calls)
        self.emit(event, **result)
        return result

    def error(self, event, error, values):
        try:
            self.emit(event, error_type=_text(type(error).__name__),
                      error=_text(error)[:1000], **values)
        except Exception:
            self.emit(event, error_text_unavailable=True, **values)

    def module_name(self, module):
        if module == 'blender_runtime.execution.runtime':
            return self.prefix.rsplit('.', 1)[0] + '.' + module
        return self.prefix + '.' + module

    def target(self, path):
        module, separator, class_name = path.partition(':')
        target = (sys.modules[self.module_name(module)] if module.startswith('invariant.')
                  else self.application.component(module))
        return getattr(target, class_name) if separator else target

    def hook(self, tag, path, name, wrapper):
        importlib.import_module(self.module_name(path.partition(':')[0]))
        target = self.target(path)
        original = getattr(target, name)
        if not callable(original):
            raise TypeError('Trace target is not callable: ' + path + '.' + name)
        self.originals[tag] = original
        self.hooks.append((path, name, original, wrapper))
        setattr(target, name, wrapper)

    def job_fields(self, runtime, helper):
        def extract():
            result = dict(session=_text(runtime.session.identity), role=_text(helper.role),
                          generation=int(helper.generation))
            if helper.active is not None:
                result.update(_job(runtime, helper.active))
                result.update(self.job_keys.get((result['session'], result['job_order']), {}))
            return result
        return self.values(extract)

    def install_hooks(self):
        def begin(node):
            if self.closed:
                return self.originals['begin'](node)
            result = self.originals['begin'](node)
            def extract():
                return dict(gesture=int(result), node_pointer=int(node.as_pointer()),
                            node=_text(node.name), tree=_text(node.id_data.name))
            self.emit('gesture_begin', **self.values(extract))
            return result

        def end(token):
            if self.closed:
                return self.originals['end'](token)
            values = self.values(lambda: dict(gesture=int(token)))
            self.emit('gesture_release', **values)
            try:
                result = self.originals['end'](token)
            except Exception as error:
                self.error('gesture_release_error', error, values)
                raise
            self.emit('gesture_release_returned', **values)
            return result

        def scope_request(node, kind, spec):
            if self.closed:
                return self.originals['scope_request'](node, kind, spec)
            result = self.originals['scope_request'](node, kind, spec)
            def observe():
                values = dict(_ticket(result), scope_key=_digest(spec['key']))
                owner = (values['scheduler_session'], values['channel'], values['node_pointer'])
                signature = tuple(value for name, value in values.items() if name != 'ticket')
                if self.requests.get(owner) != signature:
                    self.remember(self.requests, owner, signature)
                    self.emit('scope_request', **values)
                return {}
            self.values(observe)
            return result

        def capture(spec, *args, **kwargs):
            if self.closed:
                return self.originals['capture'](spec,*args,**kwargs)
            values = self.start('capture_begin', self.values(_scope, spec))
            try:
                result = self.originals['capture'](spec,*args,**kwargs)
            except Exception as error:
                try:
                    waiting = type(error).__name__ == 'ScopePreparing' or _text(error) == 'Preparing compositor scopes'
                except Exception:
                    waiting = False
                self.error('capture_wait' if waiting else 'capture_error', error, values)
                raise
            self.emit('capture_end', **values)
            return result

        def scope_submit(operation, snapshot, *args, **kwargs):
            if self.closed:
                return self.originals['scope_submit'](operation, snapshot,*args,**kwargs)
            values = self.start('scope_submit_begin', self.values(_scope, snapshot))
            try:
                result = self.originals['scope_submit'](operation, snapshot,*args,**kwargs)
            except Exception as error:
                self.error('scope_submit_error', error, values)
                raise
            info = self.values(_handle, result.handle)
            values.update(info)
            if 'scope_key' in values and 'session' in info:
                self.remember(self.job_keys, (info['session'], info['job_order']),
                              dict(scope_key=values['scope_key']))
            self.emit('scope_submit', **values)
            return result

        def submit(runtime, spec):
            if self.closed:
                return self.originals['submit'](runtime, spec)
            result = self.originals['submit'](runtime, spec)
            self.emit('job_submit', **self.values(_handle, result))
            return result

        def send(runtime, helper, message):
            if self.closed:
                return self.originals['send'](runtime, helper, message)
            trace = message.get('kind') == 'run'
            fields = self.job_fields(runtime, helper) if trace else {}
            if trace:
                fields.update(self.values(_payload_values, message.get('inputs'), 'input_payload'))
            values = self.start('run_send_begin', fields) if trace else {}
            try:
                result = self.originals['send'](runtime, helper, message)
            except Exception as error:
                if trace:
                    self.error('run_send_error', error, values)
                raise
            if trace:
                self.emit('run_send', sent=bool(result), **values)
            return result

        def receive(runtime, helper, message):
            if self.closed:
                return self.originals['message'](runtime, helper, message)
            kind = message.get('kind')
            trace = kind in ('preview', 'complete', 'failed', 'cancelled')
            values = {}
            if trace:
                def extract():
                    return dict(message_kind=_text(kind),
                                message_attempt=message.get('attempt'),
                                message_generation=message.get('generation'),
                                matches_active=bool(helper.active is not None
                                    and message.get('attempt') == helper.active.state.identity
                                    and message.get('session') == runtime.session.identity
                                    and message.get('generation') == helper.generation))
                values = self.job_fields(runtime, helper)
                values.update(self.values(extract))
                if kind in ('preview', 'complete'):
                    values.update(self.values(_payload_values, message.get('value'), 'output_payload'))
                values = self.start('job_message_begin', values)
            try:
                result = self.originals['message'](runtime, helper, message)
            except Exception as error:
                if trace:
                    self.error('job_message_error', error, values)
                raise
            if trace:
                self.emit('job_message_end', **values)
            return result

        def decode(future, timeout=None):
            if self.closed:
                return self.originals['decode'](future, timeout=timeout)
            first = future._decoded is None
            values = self.start('scope_decode_begin', self.values(_handle, future.handle)) if first else {}
            try:
                result = self.originals['decode'](future, timeout=timeout)
            except Exception as error:
                if first:
                    self.error('scope_decode_error', error, values)
                raise
            if first:
                values.update(self.values(_result_key, result))
                values.update(self.values(_cloud_values, result))
                self.emit('scope_decode_end', **values)
            return result

        def preview(future):
            if self.closed:return self.originals['preview'](future)
            pending=future.handle.preview
            first=pending is not None and pending is not getattr(future,'_preview_seen',None)
            values=self.start('scope_preview_decode_begin',self.values(_handle,future.handle)) if first else {}
            try:result=self.originals['preview'](future)
            except Exception as error:
                if first:self.error('scope_preview_decode_error',error,values)
                raise
            if first:
                values.update(self.values(_result_key,result))
                values.update(self.values(_cloud_values,result))
                self.emit('scope_preview_decode_end',**values)
            return result

        def scope_publish(ticket, payload=None, provenance=None):
            if self.closed:
                return self.originals['scope_publish'](ticket, payload, provenance)
            result = self.originals['scope_publish'](ticket, payload, provenance)
            values = self.values(_ticket, ticket)
            values.update(self.values(_result_key, payload))
            values.update(self.values(_cloud_values, payload))
            self.emit('scope_publish', accepted=bool(result), **values)
            return result

        def scope_complete(ticket):
            result=self.originals['scope_complete'](ticket)
            if not self.closed:self.emit('scope_retired',**self.values(_ticket,ticket))
            return result

        def cancel(future):
            values=self.values(_handle,future.handle) if not self.closed else {}
            result=self.originals['cancel'](future)
            if not self.closed:self.emit('scope_cancel',**values)
            return result

        def publication(ticket, commit=True):
            if self.closed:
                return self.originals['publication'](ticket, commit)
            result = self.originals['publication'](ticket, commit)
            if result and commit:
                self.emit('lut_publication', **self.values(_ticket, ticket))
            return result

        def draw(plot, result, external, s):
            if self.closed:
                return self.originals['draw'](plot, result, external, s)
            values = self.values(_result_key, result)
            components = self.values(_display_components,result)
            values.update(components)
            view_values = self.values(_view_values, plot, s)
            tone = result.get('_warp_tone') if isinstance(result, Mapping) else None
            # A matching p95 publication reuses the raster but has its own
            # first overlay frame; keep both timings instead of hiding it as
            # an already-drawn request.
            key = (values.get('scope_key'), values.get('scope_part'), tone,
                   _digest(tuple(sorted(view_values.items()))),
                   values.get('visual_request'),values.get('statistics_request'))
            component_state=(tuple(sorted(components.items())),key[3],tone)
            if component_state!=self.component_state:
                self.component_state=component_state
                self.emit('warp_components',**values,**view_values)
            first = key[0] is not None and key not in self.drawn
            if first:
                values.update(self.values(_cloud_values, result))
                values.update(view_values)
                if type(tone) is int:
                    values['tone'] = tone
            previous = self.active_draw_fields
            self.active_draw_fields = values if first else None
            began = time.perf_counter_ns()
            try:
                returned = self.originals['draw'](plot, result, external, s)
            finally:
                self.active_draw_fields = previous
            if first:
                self.remember(self.drawn, key, True)
                values['duration_ms'] = (time.perf_counter_ns() - began) / 1e6
                self.emit('warp_draw', **values)
            return returned

        def instrument_cloud(tag, name, fields):
            original = getattr(self.target('ui.warp_samples'), name, None)
            if not callable(original):
                return
            def measured(*args, **kwargs):
                if self.closed:
                    return original(*args, **kwargs)
                began = time.perf_counter_ns()
                result = original(*args, **kwargs)
                if tag == 'cloud_raster_draw' and self.active_draw_fields is None:
                    return result
                values = dict(self.active_draw_fields or {},
                              duration_ms=(time.perf_counter_ns() - began) / 1e6)
                for field, index in fields.items():
                    if index < len(args) and type(args[index]) in _SCALARS:
                        values[field] = args[index]
                if args:
                    shape = getattr(args[0], 'shape', ())
                    if len(shape) >= 2:
                        values['height'], values['width'] = int(shape[-2]), int(shape[-1])
                self.emit(tag, **values)
                return result
            self.originals[tag] = original
            self.hooks.append(('ui.warp_samples', name, original, measured))
            setattr(self.target('ui.warp_samples'), name, measured)

        for tag, path, name, wrapper in (
                ('begin', 'graph.scheduler', 'begin', begin),
                ('end', 'graph.scheduler', 'end', end),
                ('scope_request', 'graph.scheduler', 'scope_request', scope_request),
                ('capture', 'scopes.sampling', 'capture', capture),
                ('scope_submit', 'scopes.jobs', '_submit', scope_submit),
                ('submit', 'blender_runtime.execution.runtime:ExecutionRuntime', 'submit', submit),
                ('send', 'blender_runtime.execution.runtime:ExecutionRuntime', '_send', send),
                ('message', 'blender_runtime.execution.runtime:ExecutionRuntime', '_message', receive),
                ('decode', 'scopes.jobs:ScopeResult', 'result', decode),
                ('scope_publish', 'graph.scheduler', 'scope_publish', scope_publish),
                ('scope_complete', 'graph.scheduler', 'scope_complete', scope_complete),
                ('cancel', 'scopes.jobs:ScopeResult', 'cancel', cancel),
                ('publication', 'graph.scheduler', 'publication', publication),
                ('draw', 'ui.warp_samples', 'draw', draw)):
            self.hook(tag, path, name, wrapper)
        instrument_cloud('cloud_coverage_conversion', 'normalize_coverage',
                         {'tone': 1, 'layer': 2})
        instrument_cloud('cloud_texture_upload', 'upload_coverage', {})
        instrument_cloud('cloud_raster_draw', 'draw_raster', {'tone': 2})
        if callable(getattr(self.target('scopes.jobs:ScopeResult'),'preview',None)):
            self.hook('preview','scopes.jobs:ScopeResult','preview',preview)

    def stop(self):
        if self.closed:
            return
        self.emit('stopped', write_failed=self.write_failed)
        self.closed = True
        for path, name, original, wrapper in reversed(self.hooks):
            try:
                target = self.target(path)
                if getattr(target, name, None) is wrapper:
                    setattr(target, name, original)
            except (KeyError, AttributeError):
                pass  # Reload/disable may have removed this module or class.
        os.close(self.fd)
        self.fd = None
        self.requests.clear()
        self.drawn.clear()
        self.job_keys.clear()
        self.active_draw_fields = None
        self.component_state = None
        print('Perceptual Grade scope trace stopped:', self.path)


def stop():
    trace = getattr(sys.modules.get(_STATE_MODULE), 'trace', None)
    if trace is not None:
        trace.stop()


def install():
    import bpy

    stop()
    prefix = _discover()
    package = Path(sys.modules[prefix + '.graph.nodes'].__file__).absolute().parents[2]
    desktop = Path.home() / 'Desktop'
    desktop.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    stem = desktop / ('perceptual-grade-scope-trace-' + stamp + '-' + str(os.getpid())
                      + '-' + str(time.time_ns()))
    metadata = dict(schema=2, created=datetime.datetime.now().astimezone().isoformat(),
                    blender=list(bpy.app.version), blender_build=_text(bpy.app.build_hash.decode()),
                    python=sys.version, platform=sys.platform, pid=os.getpid(),
                    package=str(package), module=prefix,
                    source_sha256={path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sorted(package.rglob('*.py')) if path.is_file()},
                    **_runtime_values(prefix))
    metadata_path = stem.with_suffix('.metadata.json')
    fd = os.open(metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(fd, (json.dumps(metadata, ensure_ascii=True, indent=2) + '\n').encode('utf8'))
    finally:
        os.close(fd)
    trace = _Trace(prefix, stem)
    state = sys.modules.get(_STATE_MODULE)
    if state is None:
        state = types.ModuleType(_STATE_MODULE)
        sys.modules[_STATE_MODULE] = state
    state.trace, state.stop = trace, trace.stop
    try:
        trace.install_hooks()
    except Exception:
        trace.stop()
        raise
    trace.emit('installed', **_runtime_values(prefix))
    print('Perceptual Grade scope trace:', trace.path)
    print('Source metadata:', metadata_path)
    print("Stop: import sys; sys.modules['_pg_scope_trace_state'].stop()")
    return trace.path


if __name__ == '__main__':
    install()
