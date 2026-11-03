"""Reproducible optional Eevee/compositor-GPU diagnostics with a private display.

Linux uses pinned Xvfb and Mesa llvmpipe. This exercises Blender's GPU graph
compiler and texture transport, not a physical GPU or desktop-driver claim.
The CPU accuracy target remains the required acceptance target.
"""
import argparse
from functools import partial
from color_tools.kernel.graph import build_group
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import numpy as np


def _json_values(value):
    """Keep failed transport measurements reportable, including nonfinite AOVs."""
    if isinstance(value, np.generic):
        return _json_values(value.item())
    if isinstance(value, np.ndarray):
        return _json_values(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key:_json_values(item) for key,item in value.items()}
    if isinstance(value, (tuple,list)):
        return [_json_values(item) for item in value]
    return value


@contextmanager
def display_environment(xvfb, directory):
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    if sys.platform != 'linux':
        yield env
        return
    if xvfb is None:
        raise ValueError('Linux GPU diagnostics require the pinned Xvfb fixture')
    root = xvfb.resolve()
    runtime = directory/'xdg-runtime'
    runtime.mkdir(mode=0o700)
    env.update(XDG_RUNTIME_DIR=str(runtime), LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe')
    libraries = root/'usr/lib/x86_64-linux-gnu'
    if (libraries/'libGLX_mesa.so.0').exists():
        # The self-contained software fixture supplies the server's GLX/DRI
        # libraries too; setting only Blender's loader paths leaves Xvfb
        # without GLX_ARB_create_context on minimal hosts.
        env.update(LD_LIBRARY_PATH=str(libraries),
                   LIBGL_DRIVERS_PATH=str(libraries/'dri'),
                   __GLX_VENDOR_LIBRARY_NAME='mesa')
    env.pop('WAYLAND_DISPLAY', None)
    read_fd, write_fd = os.pipe()
    process = None
    try:
        with (directory/'xvfb.log').open('w') as log:
            process = subprocess.Popen([
                str(root/'usr/bin/Xvfb'), '-displayfd', str(write_fd),
                '-screen', '0', '1280x960x24', '-nolisten', 'tcp', '-ac',
                '-xkbdir', str(root/'usr/share/X11/xkb'),
            ], cwd=root,
                env=dict(env, LD_LIBRARY_PATH=str(root/'usr/lib/x86_64-linux-gnu')),
                pass_fds=(write_fd,), stdout=log, stderr=subprocess.STDOUT)
            os.close(write_fd)
            write_fd = None
            with selectors.DefaultSelector() as ready:
                ready.register(read_fd, selectors.EVENT_READ)
                if not ready.select(timeout=30):
                    raise RuntimeError('Xvfb did not publish a display number')
                number = os.read(read_fd, 64).decode('ascii').strip()
            if not number.isdigit():
                raise RuntimeError('Xvfb initialization failed: '+(directory/'xvfb.log').read_text())
            env['DISPLAY'] = ':'+number
            yield env
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def worker(output_dir, samples, full=False):
    import bpy
    import gpu
    from color_tools.kernel import prepare
    from . import cases, oracle
    from .evaluate import assess, evidence_hashes
    from .native import NativeFixture

    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    gpu.init()
    backend = {'type':gpu.platform.backend_type_get(), 'renderer':gpu.platform.renderer_get(),
               'vendor':gpu.platform.vendor_get(), 'version':gpu.platform.version_get(),
               'compute_shaders':gpu.capabilities.compute_shader_support_get()}
    backend['software'] = any(name in backend['renderer'].lower() for name in ('llvmpipe', 'softpipe'))
    from .gpu_sampling import run as run_sampling
    sampling = run_sampling()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'sampling.json').write_text(json.dumps(_json_values(sampling), indent=2, allow_nan=False)+'\n')
    if not sampling['passed']:
        raise RuntimeError('Native parameter sampling regression failed; see sampling.json')
    if full:
        from .full_evaluate import run
        report = run(output_dir, samples=samples, warm_runs=0, gpu_backend=backend)
        from .gpu_guards import run as run_guards
        guards = run_guards(output_dir)
        report['sampling_regression'] = sampling
        report['guard_internal'] = guards
        report['numerical_passed'] = bool(report['numerical_passed'] and sampling['passed'] and guards['passed'])
        report['passed'] = bool(report['passed'] and sampling['passed'] and guards['passed'])
        (output_dir/'report.json').write_text(json.dumps(_json_values(report), indent=2, allow_nan=False)+'\n')
        markdown = (output_dir/'report.md').read_text()
        if not report['passed']:
            markdown = markdown.replace('Result: PASS.', 'Result: FAIL.')
        if not report['numerical_passed']:
            markdown = markdown.replace('Numerical acceptance: PASS;', 'Numerical acceptance: FAIL;')
        markdown += ('\nParameter sampling and finite saturation primitives: '
                     +('PASS' if sampling['passed'] else 'FAIL')+'.\n'
                     'Independent GPU H-K, boundary radius, containment and export gates: '
                     +('PASS' if guards['passed'] else 'FAIL')+'. See sampling.json and guard-internal.json.\n')
        (output_dir/'report.md').write_text(markdown)
        if not report['passed']:
            raise RuntimeError('Full native GPU grading accuracy or node budget failed; see report.json')
        return
    values = cases.rgba(samples)
    rows = []
    for space in cases.SPACES:
        for name, linear, tone in cases.grades():
            cases.assert_ui_settings(linear, tone)
            start = time.perf_counter()
            prepared = prepare(linear, tone, space)
            seconds = time.perf_counter()-start
            expected = oracle.evaluate(values[:,:3], linear, tone, space)
            for context, engine, device in (('shader','BLENDER_EEVEE','CPU'),
                                            ('compositor','CYCLES','GPU')):
                fixture = NativeFixture(prepared, values, context, engine=engine, device=device, builder=partial(build_group,export=False))
                try:
                    actual = fixture.render()
                    result = assess(actual, expected, values)
                    result.update(context=context, engine=engine, compositor_device=device,
                                  space=space, case=name, samples=samples,
                                  transport=('EEVEE float16 AOV mantissa/residual/exponent reconstruction'
                                             if fixture.split_aov else 'full-precision EXR output'),
                                  table_cells=prepared.table.cells if prepared.table else 0,
                                  stats=actual['stats'], preparation_seconds=seconds,
                                  render_seconds=actual['seconds'], linear=asdict(linear), tone=asdict(tone))
                    result['passed'] &= result['stats']['expanded_nodes'] <= 300
                    rows.append(result)
                    print(f"{engine}/{device} {space} {name}: error={result['ordinary']['max_normalized']:.6g}; pass={result['passed']}",flush=True)
                finally:
                    fixture.close()
    report = {'schema':1, 'blender':bpy.app.version_string, 'backend':backend,
              'coverage':'optional native GPU pipeline diagnostics; CPU target owns required accuracy acceptance',
              **evidence_hashes(),
              'pixels_sha256':hashlib.sha256(values.tobytes()).hexdigest(),
              'transport':'Eevee readback combines mantissa/residual/exponent from three float16 AOVs to reduce quantization; diagnostic nodes are excluded from grade-node counts',
              'effective_fit_domain':[-2,2], 'samples_per_case':samples,
              'rgb_limit':1e-4, 'ordinary_response_limit':300.,
              'node_limit':300, 'passed':all(row['passed'] for row in rows), 'cases':rows}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(_json_values(report),indent=2,allow_nan=False)+'\n')
    lines = ['# Native GPU Linear + Tone diagnostics','',
             f"Blender {report['blender']}; {backend['type']} / {backend['renderer']}.",
             'This target exercises Eevee and full-precision Compositor GPU. Linux uses software rendering, not physical hardware.',
             'Eevee readback combines mantissa, residual and exponent AOVs to reduce float16 render-buffer quantization and prevent HDR overflow; those diagnostic nodes are outside the grading group.',
             f"Result against the CPU acceptance thresholds: {'PASS' if report['passed'] else 'DIFFERENCES FOUND'}.",'',
             '| Engine / compositor | Space | Case | Max normalized error | Alpha absolute error |',
             '|---|---|---|---:|---:|']
    for row in rows:
        lines.append(f"| {row['engine']} / {row['compositor_device']} | {row['space']} | {row['case']} | {row['ordinary']['max_normalized']:.6g} | {row['alpha_max_absolute']:.6g} |")
    lines += ['', 'The report is diagnostic: native AOV/storage precision and renderer sampling can differ from full-precision node arithmetic.',
              'No physical-GPU, Metal, or complete-product acceptance is inferred from Linux llvmpipe results.','']
    (output_dir/'report.md').write_text('\n'.join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--xvfb', type=Path)
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--full', action='store_true', help='Evaluate complete guarded grades')
    args = parser.parse_args(argv)
    if args.samples < 256:
        parser.error('--samples must be at least 256')
    if args.worker:
        worker(args.output_dir, args.samples, args.full)
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    script = ('import sys; sys.path[:]=' + repr(sys.path) + '; '
              'from tools.perceptual_grade.reports.gpu_report import main; main(sys.argv[1:])')
    with tempfile.TemporaryDirectory(prefix='grade-nodes-gpu-') as directory:
        with display_environment(args.xvfb, Path(directory)) as env:
            process = subprocess.run([sys.executable, '-c', script, '--worker',
                                      '--output-dir', str(args.output_dir.resolve()),
                                      '--samples', str(args.samples), *(['--full'] if args.full else [])],
                                     env=env, capture_output=True, text=True, timeout=1800 if args.full else 240)
            (args.output_dir/'native.log').write_text(process.stdout+'\n'+process.stderr)
            for line in process.stdout.splitlines():
                if line.startswith(('BLENDER_EEVEE/', 'CYCLES/')):
                    print(line, flush=True)
            if process.returncode:
                raise RuntimeError(f'GPU diagnostic process failed ({process.returncode}); see native.log\n'+process.stderr[-2000:])


if __name__ == '__main__':
    main()
