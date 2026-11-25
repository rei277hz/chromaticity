"""Exercise lifecycle admission and retries against the installed coordinator."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="grade-lifecycle-")
        cls.addClassCleanup(directory.cleanup)
        root = Path(directory.name)
        package = root / "grade_lifecycle_test"
        package.mkdir()
        with zipfile.ZipFile(
                files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))

        def clear_imports():
            sys.path.remove(str(root))
            for name in tuple(sys.modules):
                if name == package.name or name.startswith(package.name + "."):
                    del sys.modules[name]

        cls.addClassCleanup(clear_imports)
        cls.lifecycle = importlib.import_module(package.name + ".runtime.lifecycle")

    def setUp(self):
        self.coordinator = self.lifecycle.LifecycleCoordinator()

    def replace_host_data(self):
        self.coordinator.begin(())
        self.coordinator.finish(Mock())

    def test_fence_precedes_cleanup_and_stays_through_repair(self):
        coordinator = self.coordinator

        def cleanup():
            self.assertTrue(coordinator.changing)
            self.assertTrue(coordinator.reset_pending)
            self.assertFalse(coordinator.admits(None))

        self.assertEqual(coordinator.begin((cleanup,)), ())
        release, repair, fail_closed = Mock(), Mock(), Mock()
        self.assertEqual(coordinator.reconcile(release, repair, fail_closed), 0.02)
        release.assert_not_called()
        repair.assert_not_called()
        fail_closed.assert_not_called()

        invalidate = Mock(side_effect=cleanup)
        coordinator.finish(invalidate)
        invalidate.assert_called_once_with()
        permit = None

        def repair_outputs(recovery):
            nonlocal permit
            permit = recovery
            release.assert_called_once_with()
            self.assertFalse(coordinator.changing)
            self.assertTrue(coordinator.reset_pending)
            self.assertFalse(coordinator.admits(None))
            self.assertTrue(coordinator.admits(recovery, 41))

        self.assertIsNone(coordinator.reconcile(release, repair_outputs, fail_closed))
        self.assertFalse(coordinator.reset_pending)
        self.assertTrue(coordinator.admits(None))
        self.assertFalse(coordinator.admits(permit))
        fail_closed.assert_not_called()

    def test_deferred_resource_release_preserves_the_fence(self):
        self.replace_host_data()
        coordinator = self.coordinator
        release = Mock(side_effect=self.lifecycle.PublicationDeferred("native reader"))
        repair, fail_closed = Mock(), Mock()

        self.assertEqual(coordinator.reconcile(release, repair, fail_closed), 0.02)
        self.assertTrue(coordinator.reset_pending)
        repair.assert_not_called()
        fail_closed.assert_not_called()

    def test_failed_repair_authorizes_error_output_and_retries(self):
        self.replace_host_data()
        coordinator = self.coordinator
        error = RuntimeError("repair stopped before reconciling outputs")
        release = Mock()
        repair = Mock(side_effect=(error, None))
        observed = []

        def fail_closed(failure, recovery):
            self.assertTrue(coordinator.reset_pending)
            self.assertFalse(coordinator.admits(None))
            self.assertTrue(coordinator.admits(recovery))
            observed.append((failure, recovery))

        self.assertEqual(coordinator.reconcile(release, repair, fail_closed), 0.2)
        self.assertTrue(coordinator.reset_pending)
        (actual, permit), = observed
        self.assertIs(actual, error)
        self.assertFalse(coordinator.admits(permit))
        self.assertIsNone(coordinator.reconcile(release, repair, fail_closed))
        self.assertFalse(coordinator.reset_pending)

    def test_failed_error_output_keeps_the_fence(self):
        self.replace_host_data()
        coordinator = self.coordinator
        release = Mock()
        repair = Mock(side_effect=RuntimeError("repair failed"))
        fail_closed = Mock(side_effect=RuntimeError("error output failed"))

        with self.assertRaisesRegex(RuntimeError, "error output failed"):
            coordinator.reconcile(release, repair, fail_closed)
        self.assertTrue(coordinator.reset_pending)
        self.assertFalse(coordinator.admits(None))
        self.assertIsNone(coordinator.reconcile(release, Mock(), Mock()))

    def test_render_permit_is_scoped_to_its_nodes_and_expires(self):
        self.replace_host_data()
        coordinator = self.coordinator
        release, repair, fail_closed = Mock(), Mock(), Mock()

        with coordinator.render_recovery((41, 42)) as permit:
            self.assertTrue(coordinator.admits(permit, 41))
            self.assertTrue(coordinator.admits(permit, 42))
            self.assertFalse(coordinator.admits(permit, 43))
            self.assertFalse(coordinator.admits(None, 41))
            self.assertEqual(coordinator.reconcile(release, repair, fail_closed), 0.02)
            release.assert_not_called()
            repair.assert_not_called()
            fail_closed.assert_not_called()

        self.assertFalse(coordinator.admits(permit, 41))
        self.assertTrue(coordinator.reset_pending)

    def test_new_lifecycle_rejects_completion_from_superseded_repair(self):
        self.replace_host_data()
        coordinator = self.coordinator

        def repair_outputs(recovery):
            self.assertTrue(coordinator.admits(recovery))
            self.replace_host_data()
            self.assertFalse(coordinator.admits(recovery))

        release, fail_closed = Mock(), Mock()
        self.assertEqual(coordinator.reconcile(release, repair_outputs, fail_closed), 0.02)
        self.assertTrue(coordinator.reset_pending)
        fail_closed.assert_not_called()
        self.assertIsNone(coordinator.reconcile(release, Mock(), fail_closed))


class _Timers:
    def __init__(self):
        self.callbacks = set()

    def is_registered(self, callback):
        return callback in self.callbacks

    def register(self, callback, **_kwargs):
        self.callbacks.add(callback)

    def unregister(self, callback):
        self.callbacks.remove(callback)


class AddonShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="grade-addon-lifecycle-")
        cls.addClassCleanup(directory.cleanup)
        root = Path(directory.name)
        package = root / "grade_addon_lifecycle_test"
        package.mkdir()
        with zipfile.ZipFile(
                files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))

        def clear_imports():
            sys.path.remove(str(root))
            for name in tuple(sys.modules):
                if name == package.name or name.startswith(package.name + "."):
                    del sys.modules[name]

        cls.addClassCleanup(clear_imports)
        cls.application = importlib.import_module(package.name + ".application")
        cls.vectorscope_module_name = package.name + ".features.vectorscope"

    def make_runtime(self, events, scope):
        runtime = self.application.AddonRuntime(types.SimpleNamespace(
            app=types.SimpleNamespace(timers=_Timers()),
        ))
        runtime.grade = types.SimpleNamespace(
            close_admission=lambda: events.append("grade.close_admission"),
            unregister=lambda: events.append("grade.unregister"),
        )
        runtime.bake = types.SimpleNamespace(
            begin_shutdown=lambda: events.append("bake.begin_shutdown"),
            finish_shutdown=lambda: events.append("bake.finish_shutdown"),
            stop_timer=lambda: events.append("bake.stop_timer"),
        )
        runtime.capture_helper = types.SimpleNamespace(
            close=lambda: events.append("capture.close"),
        )
        module = types.ModuleType(self.vectorscope_module_name)
        module.ui = scope
        return runtime, module

    def test_cleanup_failure_retries_all_feature_teardown(self):
        events = []
        scope = types.SimpleNamespace(
            begin_shutdown=lambda: events.append("scope.begin_shutdown"),
            finish_shutdown=lambda: events.append("scope.finish_shutdown"),
            unregister=Mock(side_effect=(RuntimeError("draw handler still active"), None)),
        )
        runtime, module = self.make_runtime(events, scope)

        with patch.dict(sys.modules, {self.vectorscope_module_name: module}):
            with self.assertRaisesRegex(RuntimeError, "draw handler still active"):
                runtime.unregister()
            self.assertEqual(runtime._shutdown_phase, "feature_teardown")
            self.assertIn(runtime._shutdown_retry, runtime.callbacks.bpy.app.timers.callbacks)
            self.assertIsNone(runtime._shutdown_retry())

        self.assertEqual(scope.unregister.call_count, 2)
        self.assertEqual(events[0:6], [
            "grade.close_admission",
            "bake.begin_shutdown",
            "scope.begin_shutdown",
            "capture.close",
            "bake.finish_shutdown",
            "scope.finish_shutdown",
        ])
        self.assertEqual(events.count("grade.close_admission"), 1)
        self.assertEqual(events.count("bake.begin_shutdown"), 1)
        self.assertEqual(events.count("scope.begin_shutdown"), 1)
        self.assertIsNone(runtime.grade)
        self.assertIsNone(runtime.bake)
        self.assertIsNone(runtime._shutdown_phase)

    def test_capture_retry_resumes_after_completed_admission(self):
        events = []
        scope = types.SimpleNamespace(
            begin_shutdown=lambda: events.append("scope.begin_shutdown"),
            finish_shutdown=lambda: events.append("scope.finish_shutdown"),
            unregister=lambda: events.append("scope.unregister"),
        )
        runtime, module = self.make_runtime(events, scope)
        capture_helper = runtime.capture_helper
        grade = runtime.grade
        grade.close_admission = Mock(
            side_effect=lambda: events.append("grade.close_admission")
        )
        runtime.capture_helper.close = Mock(
            side_effect=(RuntimeError("capture helper is still active"), None)
        )

        with patch.dict(sys.modules, {self.vectorscope_module_name: module}):
            with self.assertRaisesRegex(RuntimeError, "capture helper is still active"):
                runtime.unregister()
            self.assertEqual(runtime._shutdown_phase, "capture_retirement")
            self.assertIn(runtime._shutdown_retry, runtime.callbacks.bpy.app.timers.callbacks)
            self.assertIsNone(runtime._shutdown_retry())

        grade.close_admission.assert_called_once_with()
        capture_helper.close.assert_called_with()
        self.assertEqual(events.count("bake.begin_shutdown"), 1)
        self.assertEqual(events.count("scope.begin_shutdown"), 1)
        self.assertIsNone(runtime._shutdown_phase)
        self.assertIsNone(runtime.grade)

    def test_admission_failure_schedules_retry_before_other_features_start(self):
        events = []
        scope = types.SimpleNamespace(
            begin_shutdown=lambda: events.append("scope.begin_shutdown"),
            finish_shutdown=lambda: events.append("scope.finish_shutdown"),
            unregister=lambda: events.append("scope.unregister"),
        )
        runtime, module = self.make_runtime(events, scope)
        runtime.grade.close_admission = Mock(
            side_effect=(RuntimeError("publication gate is busy"), None)
        )
        grade = runtime.grade

        with patch.dict(sys.modules, {self.vectorscope_module_name: module}):
            with self.assertRaisesRegex(RuntimeError, "publication gate is busy"):
                runtime.unregister()
            self.assertEqual(runtime._shutdown_phase, "grade_admission")
            self.assertIn(runtime._shutdown_retry, runtime.callbacks.bpy.app.timers.callbacks)
            self.assertIsNone(runtime._shutdown_retry())

        self.assertEqual(grade.close_admission.call_count, 2)
        self.assertEqual(events.count("bake.begin_shutdown"), 1)
        self.assertEqual(events.count("scope.begin_shutdown"), 1)
        self.assertIsNone(runtime.grade)
        self.assertIsNone(runtime._shutdown_phase)
