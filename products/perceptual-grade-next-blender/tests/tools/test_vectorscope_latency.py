"""Check that the native vectorscope benchmark measures complete updates."""

from importlib.resources import files
import json
import math
import unittest


class VectorscopeLatencyTests(unittest.TestCase):
    def test_report_covers_cold_and_warm_updates(self):
        resource = files("tests.perceptual_grade_blender") / "vectorscope-latency.json"
        report = json.loads(resource.read_text(encoding="utf8"))
        self.assertEqual(report["schema"], 2)
        self.assertTrue(report["completed"])
        samples = report["samples"]
        controls = report["linear_controls"]
        paths = {"direct_image", "processed_compositor", "shader_viewport"}
        self.assertEqual({sample["path"] for sample in samples}, paths)
        self.assertEqual(len(controls), len(paths))
        self.assertEqual({sample["path"] for sample in controls}, paths)
        for path in paths:
            group = [sample for sample in samples if sample["path"] == path]
            control = next(sample for sample in controls if sample["path"] == path)
            self.assertEqual([sample["phase"] for sample in group], ["cold", "warm", "warm"])
            self.assertEqual(len({sample["capture_signature"] for sample in group}), 3)
            self.assertEqual(
                [sample["helper_reused"] for sample in group],
                [None] * 3 if path == "direct_image" else [False, True, True],
            )
            for sample in group:
                with self.subTest(path=path, phase=sample["phase"], ordinal=sample["ordinal"]):
                    self.assert_complete_sample(sample, helper=path != "direct_image")
            with self.subTest(path=path, trigger="linear_exposure"):
                self.assertEqual(control["trigger"], "linear_exposure")
                self.assertEqual(control["phase"], "warm")
                self.assertTrue(control["capture_reused"])
                self.assertIsNone(control["helper_reused"])
                self.assertEqual(control["capture_signature"], group[-1]["capture_signature"])
                self.assertEqual(control["source_signature"], group[-1]["source_signature"])
                self.assertNotEqual(control["analysis_signature"], group[-1]["analysis_signature"])
                self.assertGreater(control["generation"], group[-1]["generation"])
                self.assert_complete_sample(control, helper=False)
        reducers = report["reducers"]
        expected_reducers = {"cpu", "gpu", "shader-tree"}
        self.assertEqual({row["path"] for row in reducers}, paths)
        for path in paths:
            rows = [row for row in reducers if row["path"] == path]
            self.assertEqual({row["name"] for row in rows}, expected_reducers)
            self.assertEqual(len({row["input_sha256"] for row in rows}), 1)
            for row in rows:
                with self.subTest(path=path, reducer=row["name"]):
                    self.assertTrue(row["parity"])
                    if row["name"] == "shader-tree":
                        self.assertTrue(row["temporary_ids_clean"])
                    self.assertGreater(row["dimensions"][0], 0)
                    self.assertGreater(row["dimensions"][1], 0)
                    for field in ("capture_ms", "mapping_ms", "accumulation_ms",
                                  "normalization_ms", "total_ms", "capture_and_reduce_ms"):
                        self.assertTrue(math.isfinite(row[field]), field)
                        self.assertGreaterEqual(row[field], 0, field)
        checks = report["reducer_checks"]
        self.assertEqual({row["name"] for row in checks}, expected_reducers)
        self.assertTrue(all(row["fixture"] == "signed_alpha_and_bin_boundaries"
                            and row["parity"] for row in checks))
        components = report["color_component_checks"]
        self.assertEqual({row["path"] for row in components if "path" in row}, paths)
        self.assertEqual(
            sum(row.get("fixture") == "signed_alpha_and_bin_boundaries" for row in components), 1,
        )
        for row in components:
            with self.subTest(component=row.get("path", row.get("fixture"))):
                self.assertTrue(row["parity"])
                for field in ("binning_ms", "splat_ms", "maximum_mass_bin_error",
                              "maximum_rgb_energy_bin_error", "splat_mass_error"):
                    self.assertTrue(math.isfinite(row[field]), field)
                    self.assertGreaterEqual(row[field], 0, field)
                self.assertTrue(all(math.isfinite(value) and value >= 0
                                    for value in row["splat_rgb_energy_error"]))
        self.assertEqual(report["reducer_cleanup_checks"], [{
            "path": "direct_image",
            "success_temporary_ids_clean": True,
            "failure": {"failure_injected": True, "temporary_ids_clean": True},
        }])

    def assert_complete_sample(self, sample, *, helper):
        generations = sample["requested_generations"]
        self.assertEqual(generations, sorted(set(generations)))
        self.assertEqual(sample["generation"], generations[-1])
        self.assertGreater(generations[0], sample["previous_generation"])
        self.assertIn(sample["capture_generation"], generations)
        self.assertEqual(sample["superseded"], len(generations) > 1)
        self.assertGreaterEqual(sample["generation"], sample["source_generation"])
        self.assertGreater(sample["source_generation"], 0)
        self.assertLessEqual(sample["trigger_ns"], sample["request_ns"])
        self.assertLessEqual(sample["request_ns"], sample["publication_ns"])
        self.assertLessEqual(sample["publication_ns"], sample["draw_ns"])
        for name in ("latency_ms", "draw_latency_ms"):
            self.assertTrue(math.isfinite(sample[name]), name)
            self.assertGreaterEqual(sample[name], 0, name)
        capture_dimensions = sample["capture_dimensions"]
        self.assertEqual(len(capture_dimensions), 2)
        self.assertTrue(all(0 < dimension <= 512 for dimension in capture_dimensions))
        records = sample["timing_records"]
        clocks = {record["clock"] for record in records}
        expected = {"host", "worker"} if helper else {"host"}
        self.assertEqual(clocks, expected)
        host_stages = {record["stage"] for record in records if record["clock"] == "host"}
        self.assertLessEqual({"request", "publish", "draw"}, host_stages)
        density_stage = ("cached_density" if sample["capture_reused"]
                         else "result_density")
        self.assertIn(density_stage, host_stages)
        if helper:
            self.assertLessEqual({"snapshot", "helper_round_trip", "helper_receive"}, host_stages)
            worker_stages = {record["stage"] for record in records if record["clock"] == "worker"}
            self.assertLessEqual({
                "worker_decode", "worker_dispatch", "worker_encode",
                "capture_snapshot_open", "capture_scene_setup", "capture_setup",
                "capture_render", "capture_readback",
            }, worker_stages)
        for record in records:
            self.assertLessEqual(record["start_ns"], record["end_ns"], record["stage"])
            self.assertTrue(math.isfinite(record["duration_ms"]), record["stage"])
            self.assertGreaterEqual(record["duration_ms"], 0, record["stage"])
            ticket = record["ticket"]
            self.assertIn(ticket["generation"], {sample["generation"], sample["capture_generation"]})
            for field in ("source_generation", "capture_signature", "source_signature"):
                self.assertEqual(ticket[field], sample[field], (record["stage"], field))
            if ticket["generation"] == sample["generation"]:
                self.assertEqual(ticket["analysis_signature"], sample["analysis_signature"], record["stage"])
        publication, = (record for record in records if record["stage"] == "publish")
        draw, = (record for record in records if record["stage"] == "draw")
        self.assertTrue(publication["metadata"]["current"])
        self.assertEqual(publication["metadata"]["capture_generation"], sample["capture_generation"])
        self.assertEqual(publication["end_ns"], sample["publication_ns"])
        self.assertEqual(draw["end_ns"], sample["draw_ns"])
