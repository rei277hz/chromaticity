"""Ordinary typed machine bindings for one picker Session."""
from ..blender_runtime.machines import create_execution_machines, create_ownership_machine


def create_machines():
    return create_execution_machines(), create_ownership_machine()
