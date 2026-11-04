"""Explicit bindings for the framework's immutable policy functions."""
from importlib import import_module
from .machine import Machine


def policy_machine(name, *, initializers=('new',), queries=()):
    module = import_module(__package__ + '.policies.' + name)
    return Machine(module, initializers=initializers, queries=queries)


def coordinator_machine(name):
    module = import_module(__package__ + '.coordinators.' + name)
    return Machine(module)


def create_execution_machines():
    from .execution.machines import ExecutionMachines
    return ExecutionMachines(
        policy_machine('attempt', queries=('occupied', 'can_clean', 'can_admit')),
        policy_machine('gpu', queries=('gpu_available',)),
        policy_machine('retry'),
        policy_machine('startup'),
    )


def create_ownership_machine():
    return policy_machine('ownership', queries=('admits', 'resolves'))


def create_edge_effect_machine():
    return policy_machine('edge_effect')


def create_native_evaluation_machine():
    from . import native_evaluation
    return Machine(native_evaluation, queries=('available',))
