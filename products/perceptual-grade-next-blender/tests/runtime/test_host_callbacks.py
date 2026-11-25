"""Exercise feature-owned Blender callback registration."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


class _Timers:
    def __init__(self):
        self.callbacks = set()

    def is_registered(self, callback):
        return callback in self.callbacks

    def register(self, callback, **_kwargs):
        self.callbacks.add(callback)

    def unregister(self, callback):
        self.callbacks.remove(callback)


class _Bpy:
    def __init__(self):
        self.app = type("App", (), {"timers": _Timers()})()


class _FailingCollection(list):
    def __init__(self):
        super().__init__()
        self.fail_removal = True

    def remove(self, item):
        if self.fail_removal:
            raise RuntimeError("host refused callback removal")
        super().remove(item)


class HostCallbackRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-host-callbacks-")
        root = Path(cls.directory.name)
        package = root / "grade_host_callbacks_test"
        package.mkdir()
        archive = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(archive) as extension:
            extension.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module(
            package.name + ".host.callbacks"
        )

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if (name == "grade_host_callbacks_test"
                    or name.startswith("grade_host_callbacks_test.")):
                del sys.modules[name]
        cls.directory.cleanup()

    def setUp(self):
        self.bpy = _Bpy()
        self.router = self.module.HostCallbackRouter(self.bpy)

    def test_unregistering_one_owner_keeps_other_owner_handlers(self):
        grade_handlers = []
        scope_handlers = []
        grade_callback = lambda: None
        scope_callback = lambda: None
        self.router.register_handlers("grade", ((grade_handlers, grade_callback),))
        self.router.register_handlers("vectorscope", ((scope_handlers, scope_callback),))

        self.assertEqual(self.router.unregister_handlers("grade"), ())
        self.assertEqual(grade_handlers, [])
        self.assertEqual(scope_handlers, [scope_callback])
        self.assertEqual(self.router.unregister_handlers("vectorscope"), ())
        self.assertEqual(scope_handlers, [])

    def test_shared_handler_is_removed_after_its_last_owner_releases_it(self):
        handlers = []
        callback = lambda: None
        binding = ((handlers, callback),)
        self.router.register_handlers("grade", binding)
        self.router.register_handlers("vectorscope", binding)

        self.router.unregister_handlers("grade")

        self.assertEqual(handlers, [callback])
        self.router.unregister_handlers("vectorscope")
        self.assertEqual(handlers, [])

    def test_failed_handler_removal_can_be_retried(self):
        handlers = _FailingCollection()
        callback = lambda: None
        self.router.register_handlers("grade", ((handlers, callback),))

        errors = self.router.unregister_handlers("grade")

        self.assertEqual(len(errors), 1)
        self.assertEqual(handlers, [callback])
        handlers.fail_removal = False
        self.assertEqual(self.router.unregister_handlers("grade"), ())
        self.assertEqual(handlers, [])

    def test_timer_registration_is_idempotent_and_routed(self):
        callback = lambda: None
        self.router.ensure_timer("grade", callback, first_interval=0.1, persistent=True)
        self.router.ensure_timer("grade", callback, first_interval=0.1, persistent=True)

        self.assertTrue(self.router.timer_registered(callback))
        self.assertEqual(len(self.bpy.app.timers.callbacks), 1)
        self.router.unregister_timer("grade", callback)
        self.assertFalse(self.router.timer_registered(callback))

    def test_timer_remains_until_all_owners_release_it(self):
        callback = lambda: None
        self.router.ensure_timer("grade", callback, first_interval=0.1)
        self.router.ensure_timer("vectorscope", callback, first_interval=0.1)

        self.router.unregister_timer("grade", callback)

        self.assertTrue(self.router.timer_registered(callback))
        self.router.unregister_timer("vectorscope", callback)
        self.assertFalse(self.router.timer_registered(callback))

    def test_timer_registration_preserves_callback_identity(self):
        callback = lambda: None
        self.router.ensure_timer("grade", callback, first_interval=0.0)
        self.assertIn(callback, self.bpy.app.timers.callbacks)
        self.assertEqual(self.router._timers, [("grade", callback)])

        self.assertTrue(self.router.timer_registered(callback))
        self.router.unregister_timer("grade", callback)
        self.assertFalse(self.router.timer_registered(callback))

    def test_timer_removal_failure_can_be_retried(self):
        callback = lambda: None
        self.router.ensure_timer("grade", callback, first_interval=0.1)
        original = self.bpy.app.timers.unregister
        self.bpy.app.timers.unregister = lambda _callback: (_ for _ in ()).throw(
            RuntimeError("host refused timer removal")
        )

        with self.assertRaisesRegex(RuntimeError, "refused timer removal"):
            self.router.unregister_timer("grade", callback)

        self.assertTrue(self.router.timer_registered(callback))
        self.bpy.app.timers.unregister = original
        self.router.unregister_timer("grade", callback)
        self.assertFalse(self.router.timer_registered(callback))

