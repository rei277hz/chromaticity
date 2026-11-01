"""Explicit per-enable application composition; imports construct no services."""
from pathlib import Path

from ..blender_runtime import App, ExecutionConfig
from ..blender_runtime.blender import BlenderConfig
from ..blender_runtime.blender.execution import create_runtime
from ..blender_runtime.ownership import OwnershipConfig
from ..blender_runtime.machines import coordinator_machine
from .jobs.configuration import storage_name, profile, seal


def create_app(machines, ownership_machine):
    package = Path(__file__).absolute().parent.parent
    return App(package=package, storage_name=storage_name,
               execution=ExecutionConfig(lambda app: create_runtime(app, machines=machines,
                   package=package, profile=profile, seal=seal)),
               ownership=OwnershipConfig(ownership_machine), blender=BlenderConfig(),
               lifecycle=coordinator_machine('lifecycle'))
