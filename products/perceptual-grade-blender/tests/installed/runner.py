"""Run inside native Blender; never import a source checkout or a bpy wheel."""
from collections.abc import Mapping
import gc
import importlib
import json
import os
import signal
from pathlib import Path
import sys
import time

import addon_utils
import bpy
import numpy as np


def report_value(value):
    # Worker receipts deliberately contain immutable nested mappings. Preserve
    # their values in the report without weakening the production envelope.
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError('Unsupported installed report value: ' + type(value).__name__)


def main(repository, report_path):
    repository = Path(repository).resolve()
    package = repository / 'perceptual_grade'
    expected_binary = Path(bpy.app.binary_path).resolve()
    assert expected_binary.is_file(), 'Acceptance requires native standalone Blender'
    assert tuple(bpy.app.version) in {(5, 2, 4), (5, 3, 0)}, bpy.app.version
    native_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
    bpy.context.preferences.system.gpu_backend = native_backend
    bpy.context.preferences.extensions.repos.new(
        name='PG installed acceptance', module='pg_acceptance', custom_directory=str(repository))
    name = 'bl_ext.pg_acceptance.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    assert Path(addon.__file__).resolve() == package / '__init__.py'

    def module(suffix):
        value = importlib.import_module(name + '.' + suffix)
        assert Path(value.__file__).resolve().is_relative_to(package), value.__file__
        return value

    lifecycle = module('perceptual_grade_blender.integration.lifecycle')
    application = lifecycle.registered_session()
    assert application is not None
    contracts, codec = module('blender_runtime.execution.contracts'), module('perceptual_grade_core.jobs.codec')
    linear, tone, color, transforms = (module('perceptual_grade_core.model.' + part) for part in ('linear', 'tone', 'color', 'transforms'))
    model = transforms.Stack((transforms.Settings(
        linear.I3, tone.Parameters(input_midtones=45.),
        color.Parameters(global_gain=.2,web_hue_1_4=12.,web_chroma_1_4=.05),linear.GradeSpace('D65')),))
    inputs = dict(model=codec.freeze_model(model), progressive=True, encoded=False, stack=False)
    runtime = application.app.execution.get_runtime()
    cold_started=time.perf_counter()
    handles = {role: runtime.submit(contracts.JobSpec('lut_bake', inputs, lane=role,
                                                     key=('installed', role)))
               for role in ('linear', 'bulk', 'gpu')}
    results={'gpu':handles['gpu'].result(timeout=300)}
    cold_seconds=time.perf_counter()-cold_started
    results.update({role:handles[role].result(timeout=300) for role in ('linear','bulk')})
    assert not runtime.gpu_failure, runtime.gpu_failure
    assert handles['gpu'].backend == 'gpu', handles['gpu'].fallback_reason
    cpu, linear_result, gpu = (codec.thaw_cube(results[role]) for role in ('bulk', 'linear', 'gpu'))
    np.testing.assert_array_equal(cpu.values, linear_result.values)
    np.testing.assert_array_equal(cpu.values[::2, ::2, ::2], handles['bulk'].preview['values'])
    np.testing.assert_array_equal(gpu.values[::2, ::2, ::2], handles['gpu'].preview['values'])
    scale = np.maximum(.001 * np.max(np.abs(cpu.values), axis=-1), 1e-7)
    difference = np.max(np.abs(gpu.values - cpu.values), axis=-1)
    assert np.all(difference <= scale), float(np.max(difference / scale))
    assert cpu.signature == gpu.signature and cpu.size == gpu.size == 65
    assert gpu.diagnostics['backend'] == 'GPU', gpu.diagnostics
    def trial(kind,cube,elapsed,preview):
        assert preview['size']==33 and preview['diagnostics']['backend']=='GPU',preview['diagnostics']
        assert preview['diagnostics']['worker_pid']==cube.diagnostics['worker_pid']
        np.testing.assert_array_equal(cube.values[::2,::2,::2],preview['values'])
        return dict(kind=kind,backend=cube.diagnostics['backend'],helper_pid=cube.diagnostics['worker_pid'],
            preview_backend=preview['diagnostics']['backend'],preview_helper_pid=preview['diagnostics']['worker_pid'],
            preview_signature=preview['signature'],final_signature=cube.signature,
            submit_to_result_seconds=elapsed,preparation_seconds=cube.diagnostics['worker_preparation_s'],
            packing_seconds=cube.diagnostics['worker_packing_s'],
            program_reused=cube.diagnostics['worker_program_reused'])
    trials=[trial('cold',gpu,cold_seconds,handles['gpu'].preview)]
    warm_model=transforms.Stack((transforms.Settings(linear.I3,tone.Parameters(input_midtones=45.),
        color.Parameters(global_gain=.2,web_hue_1_4=13.,web_chroma_1_4=.05),linear.GradeSpace('D65')),))
    warm_inputs=dict(inputs,model=codec.freeze_model(warm_model))
    warm_started=time.perf_counter()
    warm_handle=runtime.submit(contracts.JobSpec('lut_bake',warm_inputs,lane='gpu'))
    warm_cpu_handle=runtime.submit(contracts.JobSpec('lut_bake',warm_inputs,lane='bulk'))
    warm=codec.thaw_cube(warm_handle.result(timeout=300));warm_seconds=time.perf_counter()-warm_started
    warm_cpu=codec.thaw_cube(warm_cpu_handle.result(timeout=300))
    assert warm_handle.backend=='gpu' and not warm_handle.fallback_reason
    warm_scale=np.maximum(.001*np.max(abs(warm_cpu.values),axis=-1),1e-7)
    assert np.all(np.max(abs(warm.values-warm_cpu.values),axis=-1)<=warm_scale)
    assert warm.signature!=gpu.signature
    trials.append(trial('warm',warm,warm_seconds,warm_handle.preview))
    assert not trials[0]['program_reused'] and trials[1]['program_reused'],trials
    original_gpu_process=runtime.helpers['gpu'].process
    original_generation=runtime.helpers['gpu'].generation
    valid_gpu_values=warm.values.copy()
    failure_model=transforms.Stack((transforms.Settings(linear.I3,tone.Parameters(input_midtones=45.),
        color.Parameters(global_gain=.2,web_hue_1_4=14.,web_chroma_1_4=.05),linear.GradeSpace('D65')),))
    failure_inputs=dict(inputs,model=codec.freeze_model(failure_model))
    policy=module('blender_runtime.execution.constants')
    original_gpu_process.send_signal(signal.SIGSTOP)
    try:
        failed_handle=runtime.submit(contracts.JobSpec('lut_bake',failure_inputs,lane='gpu'))
        deadline=time.monotonic()+30
        while failed_handle._job.state.phase!=policy.RUNNING and time.monotonic()<deadline:
            runtime.poll();time.sleep(.001)
        assert failed_handle._job.state.phase==policy.RUNNING
        assert runtime.helpers['gpu'].active is failed_handle._job
        failed_attempt=failed_handle._job.state.identity
        original_gpu_process.kill()
        original_gpu_process.wait(timeout=10)
    finally:
        # Only this test's Popen child can be stopped; never leave it suspended
        # when an assertion interrupts the failure-injection sequence.
        if original_gpu_process.poll() is None:
            original_gpu_process.kill();original_gpu_process.wait(timeout=10)
    recovered=codec.thaw_cube(failed_handle.result(timeout=300))
    assert failed_handle.backend=='bulk' and recovered.diagnostics['backend']=='CPU'
    assert failed_handle.fallback_reason and runtime.gpu_status()['state']=='fallback'
    assert recovered.signature==module('perceptual_grade_core.model.lut').signature(failure_model) and recovered.size==65
    assert failed_handle._job.state.identity!=failed_attempt
    np.testing.assert_array_equal(warm.values,valid_gpu_values)
    diagnostic=runtime.gpu_status()['diagnostic']
    persisted=json.loads(Path(diagnostic.diagnostic_path).read_text())
    assert persisted['pid']==original_gpu_process.pid and persisted['attempt']==failed_attempt
    assert persisted['generation']==original_generation and persisted['reason']
    fallback=dict(backend=recovered.diagnostics['backend'],reason=failed_handle.fallback_reason,
        prior_gpu_unchanged=True,diagnostic=persisted)
    probe_handle=runtime.retry_gpu()
    probe=probe_handle.result(timeout=300)
    assert probe['conformance'] and probe['backend']=='GPU' and probe_handle.backend=='gpu',probe
    assert probe['worker_pid']!=gpu.diagnostics['worker_pid'] and original_gpu_process.poll() is not None
    assert probe['device'].startswith(native_backend),probe
    assert runtime.gpu_status()['state']=='ready' and not runtime.gpu_failure
    assert runtime.helpers['gpu'].generation>original_generation
    processes = [helper.process for helper in runtime.helpers.values()]
    assert len({process.pid for process in processes}) == 3
    assert all(process.pid != os.getpid() and process.poll() is None for process in processes)
    for helper in runtime.helpers.values():
        assert helper.ready, helper.error()
        assert Path(helper.process.args[0]).resolve() == expected_binary, helper.process.args
        config_path = runtime.session.path / f'helper-{helper.role}-{helper.generation}.json'
        config = json.loads(config_path.read_text())
        assert Path(config['package']).resolve() == package
        assert config['fingerprint'] == runtime.fingerprint
    data = dict(blender=list(bpy.app.version), roles=list(runtime.helpers),native_backend=native_backend,
                parent_pid=os.getpid(),gpu_trials=trials,gpu_probe=probe,fallback=fallback,
                gpu_backend=gpu.diagnostics['backend'], gpu_device=gpu.diagnostics.get('device', ''),
                maximum_gpu_tolerance_fraction=float(np.max(difference / scale)),
                all_helpers_native=True, source_isolation=True)
    session_path = runtime.session.path
    original_session = runtime.session.identity
    del cpu, linear_result, gpu, results, handles,warm,warm_cpu,warm_handle,warm_cpu_handle,probe_handle,recovered,failed_handle
    gc.collect()

    # Retained RNA snapshots must find actual runtime/menu/operator resources
    # even after Python replaces the integration/output module globals.
    importlib.reload(module('perceptual_grade_blender.graph.output'))
    importlib.reload(module('perceptual_grade_blender.integration.lifecycle'))
    addon.unregister()
    assert runtime.closed and all(process.poll() is not None for process in processes)
    data['all_helpers_exited'] = True
    journal = json.loads((session_path / 'journal.json').read_text())
    assert journal['clean'] is True
    data['journal_clean'] = True
    assert not hasattr(bpy.types.Node, 'pg_grade')
    addon.register()
    fresh_application = lifecycle.registered_session()
    assert fresh_application is not None and fresh_application is not application
    assert application.app.closed
    fresh = fresh_application.app.execution.get_runtime()
    assert fresh is not runtime and fresh.session.identity != original_session
    data['reloaded_runtime_replaced'] = True
    result = fresh.submit(contracts.JobSpec('lut_bake', inputs, lane='bulk')).result(timeout=300)
    assert result['size'] == 65
    fresh_processes = [helper.process for helper in fresh.helpers.values()]
    del result
    addon.unregister()
    assert fresh.closed and all(process.poll() is not None for process in fresh_processes)
    # Every package module loaded under the extension namespace came from ZIP.
    for key, value in tuple(sys.modules.items()):
        if key.startswith(name + '.') and getattr(value, '__file__', None):
            assert Path(value.__file__).resolve().is_relative_to(package), (key, value.__file__)
    Path(report_path).write_text(json.dumps(data, indent=2, default=report_value), encoding='utf8')
    print('PG_INSTALLED_ACCEPTANCE', json.dumps(data, default=report_value), flush=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
