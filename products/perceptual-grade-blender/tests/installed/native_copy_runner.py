"""Arm one native copy in this disposable Blender process, then never return.

The C test library intercepts the exact validated numpy buffer passed to the
production Image.pixels.foreach_set. No production transfer is chunked and no
Python exception stands in for process death.
"""
import ctypes
import importlib
import json
import os
from pathlib import Path
import sys
import time

import addon_utils
import bpy
import numpy as np


def main(repository, project, report_path, kind, cut, mode, descriptor, library):
    assert tuple(bpy.app.version) == (5, 2, 2), bpy.app.version
    assert kind in ('shader', 'compositor') and mode in ('overwrite', 'resume')
    repository = Path(repository).resolve()
    bpy.context.preferences.system.gpu_backend = 'OPENGL'
    bpy.context.preferences.extensions.repos.new(
        name='Native copy interruption', module='pg_copy', custom_directory=str(repository))
    name = 'bl_ext.pg_copy.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, errors

    def module(suffix):
        value = importlib.import_module(name + '.' + suffix)
        assert Path(value.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
        return value

    application = module('perceptual_grade_blender.integration.lifecycle').registered_session()
    assert application is not None
    nodes, lut, resources = (application.component('graph.' + suffix)
                             for suffix in ('nodes', 'lut', 'output_resources'))
    journal = module('blender_runtime.execution.journal')
    runtime = application.app.execution.get_runtime()
    observed, transferred = [], []
    recovery_depth = 0
    original_recover = lut.adopt_native
    def recover(node, intent):
        nonlocal recovery_depth
        outer = recovery_depth == 0
        recovery_depth += 1
        try:
            result = original_recover(node, intent)
            accepted = lut.is_adopted(node)
            if outer:observed.append(dict(tree=node.node_tree.bl_idname, wrapper=node.bl_idname,
                                          accepted=accepted))
            return result
        finally:
            recovery_depth -= 1
    lut.adopt_native = recover
    assert bpy.ops.wm.open_mainfile(filepath=project) == {'FINISHED'}
    deadline = time.monotonic() + 30
    while nodes.recovery_pending():
        assert time.monotonic() < deadline, nodes.recovery_status()
        nodes.recovery_tick()
        time.sleep(.001)
    tree_type = 'ShaderNodeTree' if kind == 'shader' else 'CompositorNodeTree'
    node = next(item for item in nodes.all_nodes() if item.node_tree.bl_idname == tree_type)
    assert observed and all(item['accepted'] for item in observed), observed
    expected_wrappers = {'ShaderNodeTree': 'PGShaderGrade',
                         'CompositorNodeTree': 'PGCompositorGrade'}
    assert {item['tree']: item['wrapper'] for item in observed
            if item['wrapper'] in expected_wrappers.values()} == expected_wrappers, observed
    assert {current.bl_idname for current in nodes.all_nodes()} == set(expected_wrappers.values())
    assert lut.is_adopted(node)
    nodes.write_chromatic(node, {'global_gain': nodes.read_chromatic(node).global_gain + .25})

    shim = ctypes.CDLL(str(Path(library).resolve()))
    shim.pg_copy_arm.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                ctypes.c_size_t, ctypes.c_int)
    shim.pg_copy_arm.restype = ctypes.c_int
    original_transfer = resources.transfer_payload
    original_validate = resources.validate_pixels
    retained = []
    armed = False

    def transfer(image, pixels, cube, report, **kwargs):
        nonlocal armed
        transferred.append(dict(image=image.name, size=cube.size))
        if cube.size != lut.cm.SIZE:
            return original_transfer(image, pixels, cube, report, **kwargs)

        # Progressive production can select a coarse bank before reserving the
        # former final bank. Prepare the actual, now-unselected destination so
        # even a one-float prefix/suffix proves that the native copy is partial.
        # This test-only state is never selected or saved as completed output.
        assert application.component('graph.output_guard').publishing()
        assert kwargs['reservation']['index'] != resources.selected_index(node)
        sentinel = np.empty(len(image.pixels), np.float32)
        sentinel.reshape(-1, 4)[:] = (.25, .25, .25, 2.)
        original_validate(image, sentinel)
        image.pixels.foreach_set(sentinel)
        image.update()

        def validate(candidate, values):
            nonlocal armed
            actual = original_validate(candidate, values)
            if candidate == image and not armed:
                assert application.component('graph.output_guard').publishing()
                record = resources.payload_record(image)
                assert record and record['phase'] == 'WRITING', record
                previous = np.empty_like(actual)
                image.pixels.foreach_get(previous)
                original_validate(image, previous)
                total = actual.nbytes
                prefix = {'first': 4, 'middle': (total // 8) * 4,
                          'last': total - 4, 'resume': (total // 16) * 4}[cut]
                assert 0 < prefix < total and prefix % 4 == 0
                before = previous.view(np.uint8)
                after = actual.view(np.uint8)
                assert np.any(before[:prefix] != after[:prefix]), 'Prefix must change'
                assert np.any(before[prefix:] != after[prefix:]), 'Suffix must remain unfinished'
                assert len(transferred) >= 1
                data = dict(pid=os.getpid(), kind=kind, mode=mode, cut=cut,
                            total=total, prefix=prefix, image=image.name, phase=record['phase'],
                            source=record['source'], observed=observed,
                            session=runtime.session.path.name, directory=str(runtime.session.path),
                            helpers=[dict(pid=helper.process.pid,
                                start=Path(f'/proc/{helper.process.pid}/stat').read_text().split()[21])
                                for helper in runtime.helpers.values()],
                            mechanism='exact source pointer/length native memcpy interception')
                journal.durable_json(report_path, data)
                retained.extend((actual, previous))
                armed = True
                assert shim.pg_copy_arm(actual.ctypes.data, previous.ctypes.data, total,
                                        prefix, int(descriptor)) == 1
            return actual

        resources.validate_pixels = validate
        try:
            return original_transfer(image, pixels, cube, report, **kwargs)
        finally:
            resources.validate_pixels = original_validate

    resources.transfer_payload = transfer
    lut.ensure(node, nodes.bake_model(node), force=True)
    raise AssertionError('Native copy interception did not occur; no crash evidence was obtained')


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])
