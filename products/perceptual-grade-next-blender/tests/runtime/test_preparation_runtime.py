"""Exercise the packaged asyncio coordinator without importing Blender."""

import asyncio
import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import zipfile


class PreparationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-runtime-")
        root = Path(cls.directory.name)
        package = root / "grade_runtime_test"
        package.mkdir()
        resource = files("tests.perceptual_grade_blender") / "extension.zip"
        with zipfile.ZipFile(resource) as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.runtime_module = importlib.import_module("grade_runtime_test.runtime.preparation")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_runtime_test" or name.startswith("grade_runtime_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def runtime(self, prepare):
        runtime = self.runtime_module.PreparationRuntime(prepare)
        self.addCleanup(runtime.close)
        return runtime

    def wait_started(self, event):
        self.assertTrue(event.wait(10), "preparation did not start")

    @staticmethod
    def outcomes(publications):
        return tuple((item.source, item.signature, item.prepared, item.error)
                     for item in publications)

    def loop_read(self, runtime, read):
        async def perform():
            with runtime._lock:
                return read()
        return asyncio.run_coroutine_threadsafe(perform(), runtime.loop).result(10)

    def wait_settled(self, runtime, source):
        """Await worker retirement without draining the host publication mailbox."""
        async def settle():
            with runtime._lock:
                subscription = runtime._sources[source]
            await runtime._wait_source(subscription)
        asyncio.run_coroutine_threadsafe(settle(), runtime.loop).result(10)

    def wait_host_work(self, runtime):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with runtime._host_lock:
                if runtime._host_active is not None or runtime._host_queue:
                    return
            time.sleep(.001)
        self.fail("main-thread preparation was not queued")

    def test_drag_keeps_only_latest_and_starts_successor_without_polling(self):
        started_a, started_d = threading.Event(), threading.Event()
        release_a, release_d = threading.Event(), threading.Event()
        calls, worker_threads = [], []

        def prepare(payload):
            settings, space = payload
            calls.append(settings)
            worker_threads.append(threading.get_ident())
            if settings == "A":
                started_a.set()
                self.assertTrue(release_a.wait(10))
            elif settings == "D":
                started_d.set()
                self.assertTrue(release_d.wait(10))
            return settings, space

        runtime = self.runtime(prepare)
        self.addCleanup(release_a.set)
        self.addCleanup(release_d.set)
        source = object()
        runtime.request(source, "A", ("A", "space"))
        self.wait_started(started_a)
        for value in range(1000):
            runtime.request(source, str(value), (value, "space"))
        runtime.request(source, "D", ("D", "space"))
        counts = self.loop_read(runtime, lambda: (
            len(runtime._sources), len(runtime._jobs), len(runtime._tasks),
            next(iter(runtime._records.values())).state.desired_signature,
        ))
        self.assertEqual(counts, (1, 1, 1,
                                  self.runtime_module._request_signature("default", "D", False)))
        release_a.set()
        self.wait_started(started_d)
        self.assertEqual(calls, ["A", "D"])
        publications = runtime.collect()
        self.assertEqual(self.outcomes(publications), ((source, "A", ("A", "space"), None),))
        self.assertEqual(publications[0].quality, "full")
        self.assertEqual(publications[0].lane, "default")
        release_d.set()
        publications = runtime.wait()
        self.assertEqual(self.outcomes(publications), ((source, "D", ("D", "space"), None),))
        self.assertFalse(runtime.pending)
        self.assertTrue(all(thread != threading.get_ident() for thread in worker_threads))
        self.assertTrue(all(thread != runtime._thread.ident for thread in worker_threads))

    def test_progress_preview_does_not_retire_worker_or_start_queued_successor(self):
        started_a, preview_returned = threading.Event(), threading.Event()
        started_b, release_a, continue_after_preview, release_b = (
            threading.Event() for _ in range(4)
        )
        calls = []

        def prepare(settings, on_preview):
            calls.append(settings)
            if settings == "A":
                started_a.set()
                self.assertTrue(release_a.wait(10))
                on_preview(("33-cube", settings))
                preview_returned.set()
                self.assertTrue(continue_after_preview.wait(10))
            else:
                started_b.set()
                self.assertTrue(release_b.wait(10))
            return ("65-cube", settings)

        runtime = self.runtime(lambda _payload: None)
        runtime.register_lane("lut", prepare, progressive=True)
        self.addCleanup(release_a.set)
        self.addCleanup(continue_after_preview.set)
        self.addCleanup(release_b.set)
        source = object()
        runtime.request(source, "A", "A", lane="lut")
        self.wait_started(started_a)
        runtime.request(source, "B", "B", lane="lut")
        release_a.set()
        self.wait_started(preview_returned)

        previews = runtime.collect()
        self.assertEqual(len(previews), 1)
        self.assertEqual((previews[0].signature, previews[0].prepared,
                          previews[0].quality, previews[0].lane),
                         ("A", ("33-cube", "A"), "preview", "lut"))
        state = self.loop_read(
            runtime, lambda: next(iter(runtime._records.values())).state
        )
        self.assertEqual((state.running_signature, state.desired_signature), (
            self.runtime_module._request_signature("lut", "A", True),
            self.runtime_module._request_signature("lut", "B", True),
        ))
        self.assertFalse(started_b.is_set())
        self.assertEqual(calls, ["A"])

        continue_after_preview.set()
        self.wait_started(started_b)
        first_final = runtime.collect()
        self.assertEqual(self.outcomes(first_final),
                         ((source, "A", ("65-cube", "A"), None),))
        self.assertEqual(first_final[0].quality, "full")
        release_b.set()
        latest = runtime.wait()
        self.assertEqual(self.outcomes(latest),
                         ((source, "B", ("65-cube", "B"), None),))
        self.assertEqual(calls, ["A", "B"])

    def test_default_and_registered_thread_lanes_run_on_separate_pools(self):
        started_linear = threading.Event()
        started_lut = threading.Event()
        release = threading.Event()
        thread_ids = {}

        def linear(settings):
            thread_ids["linear"] = threading.get_ident()
            started_linear.set()
            self.assertTrue(release.wait(10))
            return settings

        def lut(settings):
            thread_ids["lut"] = threading.get_ident()
            started_lut.set()
            self.assertTrue(release.wait(10))
            return settings

        runtime = self.runtime(linear)
        runtime.register_lane("lut", lut)
        self.addCleanup(release.set)
        runtime.request(object(), "linear", "linear")
        runtime.request(object(), "lut", "lut", lane="lut")
        self.wait_started(started_linear)
        self.wait_started(started_lut)
        self.assertNotEqual(thread_ids["linear"], thread_ids["lut"])
        self.assertNotEqual(thread_ids["linear"], runtime._thread.ident)
        self.assertNotEqual(thread_ids["lut"], runtime._thread.ident)
        release.set()
        results = runtime.wait()
        self.assertEqual({item.lane for item in results}, {"default", "lut"})

    def test_lut_final_only_request_skips_preview_callback(self):
        calls = []

        def prepare(settings, on_preview=None):
            calls.append(on_preview)
            if on_preview is not None:
                on_preview("unexpected preview")
            return ("65-cube", settings)

        runtime = self.runtime(lambda _payload: None)
        runtime.register_lane("lut", prepare, progressive=True)
        source = object()
        runtime.request(source, "A", "A", lane="lut", progressive=False)
        publications = runtime.wait()
        self.assertEqual(self.outcomes(publications),
                         ((source, "A", ("65-cube", "A"), None),))
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0])
        self.assertEqual([item.quality for item in publications], ["full"])
        self.assertFalse(publications[0].progressive)

    def test_main_thread_lane_retires_superseded_refinement_after_preview(self):
        main_ident = threading.get_ident()
        advanced = []
        closed = []

        class Job:
            def __init__(self, settings, progressive):
                self.settings = settings
                self.progressive = progressive
                self.step = 0

            def advance(self):
                self.assert_main()
                self.step += 1
                advanced.append((self.settings, self.step))
                if self.progressive and self.step == 1:
                    return "preview", ("preview", self.settings)
                if self.step == 2 or not self.progressive:
                    return "full", ("full", self.settings)
                return None

            @staticmethod
            def assert_main():
                if threading.get_ident() != main_ident:
                    raise AssertionError("GPU job advanced off the host thread")

            def close(self):
                self.assert_main()
                closed.append(self.settings)

        class Owner:
            def create_job(self, settings, progressive):
                return Job(settings, progressive)

            def close(self):
                pass

        runtime = self.runtime(lambda _payload: None)
        runtime.register_polled_lane("lut", Owner(), progressive=True)
        source = object()
        runtime.request(source, "A", "A", lane="lut")
        self.wait_host_work(runtime)
        self.assertTrue(runtime.pending)
        self.assertTrue(runtime.pump_main_thread())
        previews = runtime.collect()
        self.assertEqual([(item.signature, item.quality, item.prepared)
                          for item in previews],
                         [("A", "preview", ("preview", "A"))])

        runtime.request(source, "B", "B", lane="lut")
        self.assertTrue(runtime.pump_main_thread())
        self.assertTrue(runtime.pending)
        self.assertEqual(advanced, [("A", 1)])
        self.assertEqual(closed, ["A"])

        self.wait_host_work(runtime)
        self.assertTrue(runtime.pump_main_thread())
        self.assertEqual(advanced, [("A", 1), ("B", 1)])
        previews = runtime.collect()
        self.assertEqual([(item.signature, item.quality, item.prepared)
                          for item in previews],
                         [("B", "preview", ("preview", "B"))])
        self.assertTrue(runtime.pump_main_thread())
        results = runtime.wait((source,))
        self.assertEqual([(item.signature, item.quality, item.prepared)
                          for item in results],
                         [("B", "full", ("full", "B"))])
        self.assertEqual(closed, ["A", "B"])

    def test_main_thread_wait_pumps_the_host_lane(self):
        calls = []

        class Job:
            def advance(self):
                calls.append(threading.get_ident())
                return "full", "prepared"

            def close(self):
                pass

        class Owner:
            def create_job(self, *_args):
                return Job()

            def close(self):
                pass

        runtime = self.runtime(lambda _payload: None)
        runtime.register_polled_lane("lut", Owner())
        source = object()
        runtime.request(source, "A", "A", lane="lut")
        result = runtime.wait((source,))
        self.assertEqual([(item.signature, item.prepared, item.quality)
                          for item in result], [("A", "prepared", "full")])
        self.assertTrue(calls)
        self.assertEqual(set(calls), {threading.get_ident()})

    def test_forgotten_host_request_is_removed_before_gpu_job_starts(self):
        created = []

        class Job:
            def advance(self):
                raise AssertionError("forgotten GPU work must not start")

            def close(self):
                pass

        class Owner:
            def create_job(self, settings, *_args):
                created.append(settings)
                return Job()

            def close(self):
                pass

        runtime = self.runtime(lambda _payload: None)
        runtime.register_polled_lane("lut", Owner())
        source = object()
        runtime.request(source, "A", "A", lane="lut")
        self.wait_host_work(runtime)

        runtime.forget(source)

        with runtime._host_lock:
            self.assertFalse(runtime._host_queue)
            self.assertIsNone(runtime._host_active)
        self.assertEqual(created, [])
        self.assertFalse(runtime.pending)

    def test_latest_host_request_replaces_queued_work_before_gpu_job_starts(self):
        created = []

        class Job:
            def __init__(self, settings):
                self.settings = settings

            def advance(self):
                return "full", self.settings

            def close(self):
                pass

        class Owner:
            def create_job(self, settings, *_args):
                created.append(settings)
                return Job(settings)

            def close(self):
                pass

        runtime = self.runtime(lambda _payload: None)
        runtime.register_polled_lane("lut", Owner())
        source = object()
        runtime.request(source, "A", "A", lane="lut")
        self.wait_host_work(runtime)

        runtime.request(source, "B", "B", lane="lut")

        result = runtime.wait((source,))
        self.assertEqual([(item.signature, item.prepared, item.quality)
                          for item in result], [("B", "B", "full")])
        self.assertEqual(created, ["B"])
        self.assertFalse(runtime.pending)

    def test_re_requested_signature_does_not_join_withdrawn_host_work(self):
        created = []

        class Job:
            def __init__(self, settings):
                self.settings = settings

            def advance(self):
                return "full", self.settings

            def close(self):
                pass

        class Owner:
            def create_job(self, settings, *_args):
                created.append(settings)
                return Job(settings)

            def close(self):
                pass

        runtime = self.runtime(lambda _payload: None)
        runtime.register_polled_lane("lut", Owner())
        old_source, new_source = object(), object()
        runtime.request(old_source, "same", "same", lane="lut")
        self.wait_host_work(runtime)
        runtime.forget(old_source)

        runtime.request(new_source, "same", "same", lane="lut")

        result = runtime.wait((new_source,))
        self.assertEqual([(item.signature, item.prepared, item.error)
                          for item in result], [("same", "same", None)])
        self.assertEqual(created, ["same"])
        self.assertFalse(runtime.pending)

    def test_unsupported_progressive_request_is_rejected_before_admission(self):
        calls = []
        runtime = self.runtime(lambda settings: calls.append(settings))
        with self.assertRaisesRegex(ValueError, "does not support previews: default"):
            runtime.request(object(), "A", "A", progressive=True)
        self.assertEqual(self.loop_read(runtime, lambda: (
            len(runtime._sources), len(runtime._records), len(runtime._jobs),
            len(runtime._tasks), len(runtime._publications),
        )), (0, 0, 0, 0, 0))
        self.assertEqual(calls, [])
        self.assertFalse(runtime.pending)

    def test_uncollected_results_keep_only_latest_success_per_source(self):
        def prepare(settings, on_preview):
            on_preview(("33-cube", settings))
            return ("65-cube", settings)

        runtime = self.runtime(lambda settings: settings)
        runtime.register_lane("lut", prepare, progressive=True)
        source = object()
        for index in range(30):
            signature = str(index)
            runtime.request(source, signature, signature, lane="lut")
            self.wait_settled(runtime, source)
            self.assertEqual(self.loop_read(runtime, lambda: (
                len(runtime._publications),
                sum(len(slots) for slots in runtime._publications.values()),
                len(runtime._prepared),
            )), (1, 1, 1))
        result = runtime.collect()
        self.assertEqual(self.outcomes(result),
                         ((source, "29", ("65-cube", "29"), None),))
        self.assertEqual(result[0].quality, "full")

    def test_current_failure_supersedes_uncollected_preview(self):
        def prepare(settings, on_preview):
            on_preview(("33-cube", settings))
            raise ValueError("refinement failed")

        runtime = self.runtime(lambda settings: settings)
        runtime.register_lane("lut", prepare, progressive=True)
        source = object()
        runtime.request(source, "A", "A", lane="lut")
        self.wait_settled(runtime, source)
        self.assertEqual(self.loop_read(runtime, lambda: (
            len(runtime._publications),
            sum(len(slots) for slots in runtime._publications.values()),
        )), (1, 2))
        result = runtime.collect()
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0].error, ValueError)
        self.assertEqual(result[0].signature, "A")

    def test_forget_retires_uncollected_receipts_before_source_key_reuse(self):
        runtime = self.runtime(lambda settings: settings)
        source = object()
        runtime.request(source, "A", "A")
        self.wait_settled(runtime, source)
        runtime.forget(source)
        runtime.request(source, "B", "B")
        result = runtime.wait()
        self.assertEqual(self.outcomes(result), ((source, "B", "B", None),))

    def test_equal_settings_with_mode_change_queue_distinct_preparation(self):
        started_progressive = threading.Event()
        release_progressive = threading.Event()
        started_final = threading.Event()
        release_final = threading.Event()
        calls = []

        def prepare(settings, on_preview=None):
            calls.append(on_preview is not None)
            if on_preview is not None:
                on_preview(("33-cube", settings))
                started_progressive.set()
                self.assertTrue(release_progressive.wait(10))
            else:
                started_final.set()
                self.assertTrue(release_final.wait(10))
            return ("65-cube", settings)

        runtime = self.runtime(lambda _payload: None)
        runtime.register_lane("lut", prepare, progressive=True)
        self.addCleanup(release_progressive.set)
        self.addCleanup(release_final.set)
        source = object()
        runtime.request(source, "same", "same", lane="lut", progressive=True)
        self.wait_started(started_progressive)
        self.assertEqual(runtime.collect()[0].quality, "preview")
        runtime.request(source, "same", "same", lane="lut", progressive=False)
        state = self.loop_read(
            runtime, lambda: next(iter(runtime._records.values())).state
        )
        self.assertNotEqual(state.running_signature, state.desired_signature)
        self.assertEqual(runtime.collect(), ())
        self.assertFalse(started_final.is_set())

        release_progressive.set()
        self.wait_started(started_final)
        self.assertEqual(calls, [True, False])
        result = runtime.collect()
        self.assertEqual(self.outcomes(result),
                         ((source, "same", ("65-cube", "same"), None),))
        self.assertEqual(result[0].progressive, True)
        release_final.set()
        latest = runtime.wait()
        self.assertEqual(self.outcomes(latest),
                         ((source, "same", ("65-cube", "same"), None),))
        self.assertFalse(latest[0].progressive)

    def test_final_only_demand_suppresses_inflight_preview_for_same_settings(self):
        started_progressive = threading.Event()
        allow_preview = threading.Event()
        preview_returned = threading.Event()
        continue_bake = threading.Event()
        started_final = threading.Event()
        release_final = threading.Event()
        calls = []

        def prepare(settings, on_preview=None):
            calls.append(on_preview is not None)
            if on_preview is not None:
                started_progressive.set()
                self.assertTrue(allow_preview.wait(10))
                on_preview(("33-cube", settings))
                preview_returned.set()
                self.assertTrue(continue_bake.wait(10))
            else:
                started_final.set()
                self.assertTrue(release_final.wait(10))
            return ("65-cube", settings)

        runtime = self.runtime(lambda _payload: None)
        runtime.register_lane("lut", prepare, progressive=True)
        self.addCleanup(allow_preview.set)
        self.addCleanup(continue_bake.set)
        self.addCleanup(release_final.set)
        source = object()
        runtime.request(source, "same", "same", lane="lut", progressive=True)
        self.wait_started(started_progressive)
        runtime.request(source, "same", "same", lane="lut", progressive=False)
        allow_preview.set()
        self.wait_started(preview_returned)
        self.assertEqual(runtime.collect(), ())

        continue_bake.set()
        self.wait_started(started_final)
        result = runtime.collect()
        self.assertEqual(self.outcomes(result),
                         ((source, "same", ("65-cube", "same"), None),))
        self.assertTrue(result[0].progressive)
        release_final.set()
        result = runtime.wait()
        self.assertEqual(self.outcomes(result),
                         ((source, "same", ("65-cube", "same"), None),))
        self.assertFalse(result[0].progressive)
        self.assertEqual(calls, [True, False])

    def test_returning_to_running_signature_does_not_prepare_twice(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def prepare(settings):
            calls.append(settings)
            started.set()
            self.assertTrue(release.wait(10))
            return settings

        runtime = self.runtime(prepare)
        self.addCleanup(release.set)
        source = object()
        runtime.request(source, "A", "A")
        self.wait_started(started)
        runtime.request(source, "B", "B")
        runtime.request(source, "A", "A")
        release.set()
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "A", "A", None),))
        self.assertEqual(calls, ["A"])

    def test_obsolete_failure_starts_latest_without_publishing_failure(self):
        started_a, started_c = threading.Event(), threading.Event()
        release_a, release_c = threading.Event(), threading.Event()
        calls = []

        def prepare(settings):
            calls.append(settings)
            if settings == "A":
                started_a.set()
                self.assertTrue(release_a.wait(10))
                raise ValueError("obsolete preparation failed")
            started_c.set()
            self.assertTrue(release_c.wait(10))
            return settings

        runtime = self.runtime(prepare)
        self.addCleanup(release_a.set)
        self.addCleanup(release_c.set)
        source = object()
        runtime.request(source, "A", "A")
        self.wait_started(started_a)
        runtime.request(source, "B", "B")
        runtime.request(source, "C", "C")
        release_a.set()
        self.wait_started(started_c)
        self.assertEqual(runtime.collect(), ())
        release_c.set()
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "C", "C", None),))
        self.assertEqual(calls, ["A", "C"])

    def test_current_failure_waits_for_an_explicit_retry(self):
        calls = []

        def prepare(settings):
            calls.append(settings)
            if len(calls) == 1:
                raise ValueError("current preparation failed")
            return settings

        runtime = self.runtime(prepare)
        source = object()
        runtime.request(source, "A", "A")
        result = runtime.wait()
        self.assertEqual((result[0].source, result[0].signature, result[0].prepared),
                         (source, "A", None))
        self.assertIsInstance(result[0].error, ValueError)
        self.assertEqual(result[0].quality, "full")
        self.assertFalse(runtime.pending)
        self.assertEqual(runtime.wait(), ())
        self.assertEqual(calls, ["A"])
        runtime.request(source, "A", "A")
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "A", "A", None),))
        self.assertEqual(calls, ["A", "A"])

    def test_equal_sources_share_work_and_collected_result_remains_reusable(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        prepared = object()

        def prepare(settings):
            calls.append(settings)
            started.set()
            self.assertTrue(release.wait(10))
            return prepared

        runtime = self.runtime(prepare)
        self.addCleanup(release.set)
        first, second = object(), object()
        runtime.request(first, "shared", 42)
        self.wait_started(started)
        runtime.request(second, "shared", 42)
        self.assertEqual(self.loop_read(runtime, lambda: (
            len(runtime._tasks), len(runtime._jobs)
        )), (2, 1))
        release.set()
        results = runtime.wait()
        self.assertEqual({item.source for item in results}, {first, second})
        self.assertTrue(all(item.prepared is prepared and item.error is None for item in results))
        runtime.request(first, "shared", 42)
        self.assertEqual(self.outcomes(runtime.wait()), ((first, "shared", prepared, None),))
        self.assertEqual(calls, [42])

    def test_retry_discards_an_undelivered_failure_with_the_same_signature(self):
        retry_started, release_retry = threading.Event(), threading.Event()
        calls = []

        def prepare(settings):
            calls.append(settings)
            if len(calls) == 1:
                raise ValueError("first attempt failed")
            retry_started.set()
            self.assertTrue(release_retry.wait(10))
            return settings

        runtime = self.runtime(prepare)
        self.addCleanup(release_retry.set)
        source = object()
        runtime.request(source, "A", "A")

        async def wait_for_failure_publication():
            while True:
                with runtime._lock:
                    subscription = runtime._sources[source]
                    publication = runtime._publications.get(subscription, {}).get("error")
                    if publication is not None and publication.error is not None:
                        return
                await asyncio.sleep(0)
        asyncio.run_coroutine_threadsafe(
            wait_for_failure_publication(), runtime.loop
        ).result(10)
        runtime.request(source, "A", "A")
        self.wait_started(retry_started)
        self.assertEqual(runtime.collect(), ())
        release_retry.set()
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "A", "A", None),))
        self.assertEqual(calls, ["A", "A"])

    def test_return_to_last_success_uses_cache_after_active_preparation_retires(self):
        started_b, release_b = threading.Event(), threading.Event()
        calls = []

        def prepare(settings):
            calls.append(settings)
            if settings == "B":
                started_b.set()
                self.assertTrue(release_b.wait(10))
            return settings

        runtime = self.runtime(prepare)
        self.addCleanup(release_b.set)
        source = object()
        runtime.request(source, "A", "A")
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "A", "A", None),))
        runtime.request(source, "B", "B")
        self.wait_started(started_b)
        runtime.request(source, "A", "A")
        release_b.set()
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "A", "A", None),))
        self.assertEqual(calls, ["A", "B"])

    def test_forgotten_subscription_cannot_publish_into_reused_source_key(self):
        started_a, started_b = threading.Event(), threading.Event()
        release_a, release_b = threading.Event(), threading.Event()

        def prepare(settings):
            if settings == "A":
                started_a.set()
                self.assertTrue(release_a.wait(10))
            else:
                started_b.set()
                self.assertTrue(release_b.wait(10))
            return settings

        runtime = self.runtime(prepare)
        self.addCleanup(release_a.set)
        self.addCleanup(release_b.set)
        source = object()
        runtime.request(source, "A", "A")
        self.wait_started(started_a)
        with runtime._lock:
            previous_subscription = runtime._sources[source]
        runtime.forget(source)
        runtime.request(source, "B", "B")
        release_a.set()
        self.wait_started(started_b)

        async def wait_for_previous_retirement():
            while previous_subscription in runtime._records:
                await asyncio.sleep(0)
        asyncio.run_coroutine_threadsafe(
            wait_for_previous_retirement(), runtime.loop
        ).result(10)
        self.assertEqual(runtime.collect(), ())
        release_b.set()
        self.assertEqual(self.outcomes(runtime.wait()), ((source, "B", "B", None),))

    def test_shutdown_waits_for_physical_work_and_drops_the_successor(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def prepare(settings):
            calls.append(settings)
            started.set()
            self.assertTrue(release.wait(10))
            return settings

        runtime = self.runtime(prepare)
        self.addCleanup(release.set)
        source = object()
        runtime.request(source, "A", "A")
        self.wait_started(started)
        runtime.request(source, "B", "B")
        closing = asyncio.run_coroutine_threadsafe(runtime.aclose(), runtime.loop)

        async def wait_for_fence():
            while not runtime.closed:
                await asyncio.sleep(0)
        asyncio.run_coroutine_threadsafe(wait_for_fence(), runtime.loop).result(10)
        self.assertFalse(closing.done())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            runtime.request(source, "C", "C")
        release.set()
        closing.result(10)
        runtime.close()
        self.assertEqual(calls, ["A"])
        self.assertEqual(runtime.collect(), ())
        self.assertFalse(runtime._thread.is_alive())
        self.assertFalse(runtime.pending)


if __name__ == "__main__":
    unittest.main()
