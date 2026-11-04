"""Ordinary reducer bindings for the helper execution service."""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True, slots=True)
class Policy:
    module: object

    @property
    def event_type(self):
        return self.module.Event


@dataclass(frozen=True, slots=True)
class ExecutionMachines:
    attempt: object
    gpu: object
    retry: object
    startup: object
    coordinator: object = None

    def __post_init__(self):
        if self.coordinator is None:
            if all(type(machine) is Policy
                   for machine in (self.attempt, self.gpu, self.retry, self.startup)):
                module = import_module(__package__.rsplit('.', 1)[0] + '.coordinators.execution')
                coordinator = Policy(module)
            else:
                from ..machines import coordinator_machine
                coordinator = coordinator_machine('execution')
            object.__setattr__(self, 'coordinator', coordinator)

    @staticmethod
    def event(machine, **parameters):
        return machine.event_type(**parameters)


def create_execution_machines():
    root = __package__.rsplit('.', 1)[0]
    return ExecutionMachines(*(Policy(import_module(root + '.policies.' + name))
                               for name in ('attempt', 'gpu', 'retry', 'startup')))
