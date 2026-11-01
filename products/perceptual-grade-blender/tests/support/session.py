"""Explicit test-scoped Session references and reversible lexical test seams."""
from contextvars import ContextVar
from functools import wraps
from types import SimpleNamespace
import unittest
from unittest import mock

from color_tools.perceptual_grade_blender.integration.components import Component, ComponentRef
from color_tools.perceptual_grade_blender.integration.registry import COMPONENTS

_scope = ContextVar('perceptual_grade_test_session', default=None)


def current_session():
    # A registered test uses exactly the Session retained by its own classes.
    # Source-only tests explicitly install a scoped Session through SessionTest.
    from color_tools.perceptual_grade_blender.integration import lifecycle
    registered = lifecycle.registered_session()
    scope = _scope.get()
    if registered is not None:
        if scope is not None:
            scope.session = registered
        return registered
    if scope is not None:
        return scope.session
    raise RuntimeError('The test must register a product Session or use SessionTest')


class ComponentFixture:
    def __init__(self, name):
        object.__setattr__(self, '_ComponentFixture__name', name)

    def _target(self):
        return current_session()._component(self.__name)

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def __setattr__(self, name, value):
        setattr(self._target(), name, value)


def component(name):
    return ComponentFixture(name)


class SessionTest(unittest.TestCase):
    def _callSetUp(self):
        from color_tools.perceptual_grade_blender.machines import create_machines
        from color_tools.perceptual_grade_blender import session as session_module
        session_type = session_module.Session
        self.session = session_type(create_machines())
        scope = SimpleNamespace(session=self.session)
        token = _scope.set(scope)
        self.addCleanup(_scope.reset, token)
        self.addCleanup(self.session.close)
        supplied = False

        def prepare_session():
            nonlocal supplied
            if not self.session.closed:
                raise RuntimeError('Close the original test Session before preparing another')
            self.session = session_type(create_machines())
            scope.session = self.session
            self.addCleanup(self.session.close)
            supplied = False
            return self.session

        self.prepare_session = prepare_session

        def construct(machines):
            # Tests may replace explicit seams before native registration. The
            # entrypoint must register that exact prepared fixture, rather than
            # a second untouched Session. Reenable still constructs a new App.
            nonlocal supplied
            if supplied or self.session.closed:
                self.session = session_type(machines)
                self.addCleanup(self.session.close)
            supplied = True
            scope.session = self.session
            return self.session

        constructor = mock.patch.object(session_module, 'Session', new=construct)
        constructor.start()
        self.addCleanup(constructor.stop)
        super()._callSetUp()


class _LexicalPatch:
    """Patch a declared Component setter and restore it without deleting exports."""
    def __init__(self, target, name, *args, **kwargs):
        self.target, self.name, self.args, self.kwargs = target, name, args, kwargs

    def __enter__(self):
        self.actual = self.target._target() if isinstance(self.target, ComponentFixture) else self.target
        self.original = getattr(self.actual, self.name)
        holder = SimpleNamespace(**{self.name: self.original})
        self.patch = mock.patch.object(holder, self.name, *self.args, **self.kwargs)
        value = self.patch.__enter__()
        try:
            setattr(self.actual, self.name, getattr(holder, self.name))
        except BaseException:
            self.patch.__exit__(None, None, None)
            raise
        return value

    def __exit__(self, *exc):
        setattr(self.actual, self.name, self.original)
        return self.patch.__exit__(*exc)

    def __call__(self, function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with _LexicalPatch(self.target, self.name, *self.args, **self.kwargs) as value:
                if not self.args and 'new' not in self.kwargs:
                    args += (value,)
                return function(*args, **kwargs)
        return wrapped

    def start(self):
        return self.__enter__()

    def stop(self):
        return self.__exit__(None, None, None)


class _Patch:
    def object(self, target, name, *args, **kwargs):
        if isinstance(target, (ComponentFixture, Component, ComponentRef)):
            return _LexicalPatch(target, name, *args, **kwargs)
        return mock.patch.object(target, name, *args, **kwargs)

    def __call__(self, target, *args, **kwargs):
        prefix = 'color_tools.perceptual_grade_blender.'
        if isinstance(target, str) and target.startswith(prefix):
            tail = target[len(prefix):]
            owners = COMPONENTS | {'integration.lifecycle'}
            owner = next((name for name in sorted(owners, key=len, reverse=True) if tail.startswith(name + '.')), None)
            if owner is not None:
                attributes = tail[len(owner) + 1:].split('.')
                actual = component(owner)
                for name in attributes[:-1]:
                    actual = getattr(actual, name)
                return self.object(actual, attributes[-1], *args, **kwargs)
        return mock.patch(target, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(mock.patch, name)


patch = _Patch()
