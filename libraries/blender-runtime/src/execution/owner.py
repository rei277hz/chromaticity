"""Foreground ownership for ordinary helper execution reducers.

No actor threads or runtime contract checks are created. Reducer state stays on
its owning thread, including weak-reference cleanup.
"""
import inspect
import queue
import threading
from uuid import uuid4


class ForeignOwnerError(ValueError):
    """A helper capability belongs to another execution lifecycle."""


class _Store:
    def __init__(self, owner, machine, initial):
        self.owner = owner
        self.module = machine.module
        self.state = self.module.new(**initial)

    def _dispatch_cleanup(self, event):
        self.owner.require_thread()
        self.state, effects = self.module.step(self.state, event)
        return effects

    def dispatch(self, event):
        self.owner.require_open()
        return self._dispatch_cleanup(event)

    def _query_cleanup(self, name, **parameters):
        self.owner.require_thread()
        query = getattr(self.module, name)
        arguments = inspect.signature(query).parameters
        return query(self.state, **parameters) if 'state' in arguments else query(**parameters)

    def query(self, name, **parameters):
        self.owner.require_open()
        return self._query_cleanup(name, **parameters)


class ExecutionOwner:
    """One helper lifecycle; construction starts no helper.

    Shut down its ExecutionRuntime before closing this owner.
    """
    def __init__(self, *, storage_name='perceptual_grade'):
        self.storage_name = storage_name
        self.identity = uuid4().hex
        self.closed = False
        self._thread = threading.get_ident()
        self._finalizers = queue.SimpleQueue()

    def require_thread(self):
        if threading.get_ident() != self._thread:
            raise RuntimeError('Execution ownership requires its foreground thread')

    def require_open(self):
        self.require_thread()
        if self.closed:
            raise RuntimeError('Execution owner is closed')

    def store(self, *, machine, initial=None):
        self.require_open()
        return _Store(self, machine, {} if initial is None else initial)

    def _defer_finalizer(self, callback, *arguments):
        if threading.get_ident() == self._thread:
            callback(*arguments)
        else:
            self._finalizers.put((callback, arguments))

    def drain_finalizers(self):
        self.require_thread()
        while True:
            try:
                callback, arguments = self._finalizers.get_nowait()
            except queue.Empty:
                return
            callback(*arguments)

    def close(self):
        self.require_thread()
        self.drain_finalizers()
        self.closed = True
