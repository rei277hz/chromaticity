"""Lazy Blender launch configuration for a standalone execution owner."""
import os
from pathlib import Path
import sys

from .machines import create_execution_machines
from .runtime import ExecutionRuntime
from .values import seal as seal_values


def launch_command(config):
    import bpy
    if bpy.app.binary_path:
        return [bpy.app.binary_path, '--background', '--factory-startup', '--disable-autoexec',
                '--python-exit-code', '1', '--python', config['worker_entry'], '--', config['config_path']]
    return [sys.executable, config['worker_entry'], config['config_path']]


def create_runtime(owner, *, package, profile, seal=seal_values, limits=None):
    import bpy
    owner.require_open()
    root = bpy.utils.user_resource('CONFIG', path=owner.storage_name + '/execution', create=True)
    environment = os.environ.copy()
    environment['PYTHONPATH'] = os.pathsep.join(
        path for path in sys.path if path and '/bpy/' not in path.replace('\\', '/'))
    settings = {'backend': getattr(bpy.context.preferences.system, 'gpu_backend', '')}
    return ExecutionRuntime(root, app=owner, machines=create_execution_machines(),
                            package=Path(package), profile=profile, seal=seal,
                            limits=limits, launcher=launch_command,
                            worker_host='blender_runtime.execution.blender_worker', host_settings=settings,
                            environment=environment)
