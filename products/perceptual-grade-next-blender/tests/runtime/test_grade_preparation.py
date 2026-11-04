"""Preparation joins against the packaged extension, without Blender imports."""

import asyncio
from dataclasses import replace
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile


class GradePreparationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-components-")
        root = Path(cls.directory.name)
        package = root / "grade_components_test"
        package.mkdir()
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module("grade_components_test.runtime.grade_preparation")
        cls.settings = importlib.import_module("grade_components_test.kernel.settings")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_components_test" or name.startswith("grade_components_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def preparer(self, **kwargs):
        preparer = self.module.GradePreparer(**kwargs)
        self.addCleanup(preparer.close)
        return preparer

    async def wait_started(self, *events):
        started = await asyncio.gather(*(asyncio.to_thread(event.wait, 10) for event in events))
        self.assertTrue(all(started), "Required preparation component did not start")

    def blocked(self, prepare, started, release):
        def run(*args, **kwargs):
            started.set()
            if not release.wait(10):
                raise RuntimeError("Test did not release a preparation component")
            return prepare(*args, **kwargs)
        return run

    async def test_all_components_start_before_any_is_released(self):
        traces = []
        coordinator_thread = threading.get_ident()
        preparer = self.preparer(on_timing=lambda *event: traces.append(
            (*event, threading.get_ident())
        ))
        release = threading.Event()
        self.addCleanup(release.set)
        started = [threading.Event() for _ in range(3)]
        names = ("prepare_linear", "prepare_tone", "prepare_boundary")
        with (
            patch.object(self.module, names[0], self.blocked(
                getattr(self.module, names[0]), started[0], release)),
            patch.object(self.module, names[1], self.blocked(
                getattr(self.module, names[1]), started[1], release)),
            patch.object(self.module, names[2], self.blocked(
                getattr(self.module, names[2]), started[2], release)),
        ):
            task = asyncio.create_task(preparer.prepare(self.settings.Settings()))
            await self.wait_started(*started)
            self.assertFalse(task.done())
            release.set()
            prepared = await task

        self.assertIsNotNone(prepared.tone.table)
        self.assertFalse(prepared.tone.active)
        self.assertFalse(prepared.color.full_fields)
        self.assertEqual(set(event[1] for event in traces), {
            "linear", "tone", "boundary", "join",
        })
        self.assertTrue(all(event[4] == coordinator_thread for event in traces))
        components = [event for event in traces if event[1] != "join"]
        self.assertLess(max(event[2] for event in components), min(event[3] for event in components))

    async def test_boundary_cache_is_shared_across_tone_revisions(self):
        preparer = self.preparer()
        settings = self.settings.Settings()
        with patch.object(self.module, "prepare_boundary", wraps=self.module.prepare_boundary) as load:
            original = await preparer.prepare(settings)
            changed = await preparer.prepare(replace(
                settings, tone=replace(settings.tone, fit=1.0),
            ))
        self.assertEqual(load.call_count, 1)
        self.assertIs(original.boundary, changed.boundary)
        self.assertFalse(original.boundary.pixels.flags.writeable)
        self.assertIsNotNone(changed.tone.table)
        self.assertNotEqual(self.module.preparation_signature(settings),
                            self.module.preparation_signature(replace(
                                settings, tone=replace(settings.tone, fit=1.0))))

    async def test_failed_child_waits_for_sibling_retirement(self):
        failed = asyncio.Event()
        preparer = self.preparer(on_timing=lambda _sig, name, _a, _b:
                                failed.set() if name == "tone" else None)
        release = threading.Event()
        self.addCleanup(release.set)
        linear_started, boundary_started = threading.Event(), threading.Event()
        with (
            patch.object(self.module, "prepare_tone", side_effect=ValueError("tone failed")),
            patch.object(self.module, "prepare_linear", self.blocked(
                self.module.prepare_linear, linear_started, release)),
            patch.object(self.module, "prepare_boundary", self.blocked(
                self.module.prepare_boundary, boundary_started, release)),
        ):
            task = asyncio.create_task(preparer.prepare(self.settings.Settings()))
            await self.wait_started(linear_started, boundary_started)
            await asyncio.wait_for(failed.wait(), 10)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaisesRegex(ValueError, "tone failed"):
                await task

    async def test_cancellation_waits_for_physical_retirement(self):
        preparer = self.preparer()
        release = threading.Event()
        self.addCleanup(release.set)
        started = [threading.Event() for _ in range(3)]
        with (
            patch.object(self.module, "prepare_linear", self.blocked(
                self.module.prepare_linear, started[0], release)),
            patch.object(self.module, "prepare_tone", self.blocked(
                self.module.prepare_tone, started[1], release)),
            patch.object(self.module, "prepare_boundary", self.blocked(
                self.module.prepare_boundary, started[2], release)),
        ):
            task = asyncio.create_task(preparer.prepare(self.settings.Settings()))
            await self.wait_started(*started)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_async_lane_awaits_aggregate_and_rejects_previews(self):
        runtime_module = importlib.import_module("grade_components_test.runtime.preparation")
        preparer = self.preparer()
        runtime = runtime_module.PreparationRuntime(default_lane="grade")
        self.addCleanup(runtime.close)
        runtime.register_async_lane("grade", preparer.prepare)
        source = object()
        settings = self.settings.Settings()
        with self.assertRaisesRegex(ValueError, "does not support previews"):
            runtime.request(source, "bad-preview", settings, progressive=True)
        runtime.request(source, "grade", settings)
        publications = await asyncio.to_thread(runtime.wait)
        self.assertEqual(len(publications), 1)
        self.assertEqual(publications[0].signature, "grade")
        self.assertIsNone(publications[0].error)
        self.assertIsNotNone(publications[0].prepared.tone.table)
        self.assertIsNotNone(publications[0].prepared.boundary)

    async def test_close_rejects_new_preparation(self):
        preparer = self.preparer()
        preparer.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await preparer.prepare(self.settings.Settings())


if __name__ == "__main__":
    unittest.main()
