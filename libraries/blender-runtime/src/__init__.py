"""Privately bundled Blender services; optional legacy adapters import lazily."""
from importlib import import_module

__all__ = ['AdmissionError', 'App', 'ClosedError', 'DomainError', 'Envelope',
           'ExecutionConfig', 'ForeignOwnerError', 'Machine', 'PendingTransitionError',
           'Store', 'Transition']


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    module = 'machine' if name in ('AdmissionError', 'DomainError', 'Machine') else 'app'
    return getattr(import_module(__name__ + '.' + module), name)
