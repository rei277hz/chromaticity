"""Native Shader Bake uses the fixed Cycles CPU backend."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


class BakeWorkerBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-bake-worker-")
        package = Path(cls.directory.name) / "bake_worker_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, cls.directory.name)
        cls.module = importlib.import_module("bake_worker_test.runtime.bake_worker")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "bake_worker_test" or name.startswith("bake_worker_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def test_cycles_cpu_is_selected_regardless_of_saved_engine_and_device(self):
        scene = SimpleNamespace(render=SimpleNamespace(engine="BLENDER_EEVEE"),
                                cycles=SimpleNamespace(device="GPU"))
        self.module._configure_cycles_cpu(scene)
        self.assertEqual(scene.render.engine, "CYCLES")
        self.assertEqual(scene.cycles.device, "CPU")

    def test_bake_dispatch_uses_the_frozen_route_domain(self):
        context = SimpleNamespace(checkpoint=lambda: None)
        route = {"domain": "IMAGE", "scene": "Scene"}
        inputs = {"snapshot_path": "/snapshot.blend", "artifact_dir": "/artifacts",
                  "images": [], "route": route}
        compositor_inputs = dict(inputs, route=dict(route, domain="COMPOSITOR"))
        bpy = SimpleNamespace(
            data=SimpleNamespace(node_groups=[], scenes=object()),
            context=SimpleNamespace(window=None),
        )
        with patch.dict(sys.modules, {"bpy": bpy}), \
                patch.object(self.module, "_open_snapshot") as open_snapshot, \
                patch.object(self.module, "route_datablock", return_value=None), \
                patch.object(self.module, "_shader", return_value="shader") as shader, \
                patch.object(self.module, "_compositor", return_value="compositor") as compositor:
            worker = self.module.BakeWorker()
            self.assertEqual(worker.dispatch("bake", inputs, context), "shader")
            self.assertEqual(
                worker.dispatch("bake", compositor_inputs, context), "compositor")

        self.assertEqual(open_snapshot.call_count, 2)
        shader.assert_called_once_with(inputs, context)
        compositor.assert_called_once_with(compositor_inputs, context)

    def test_bake_dispatch_rejects_legacy_operations_and_inputs(self):
        context = SimpleNamespace(checkpoint=lambda: None)
        worker = self.module.BakeWorker()
        for operation in ("native_bake", "shader_bake", "compositor_bake"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "Unknown Bake helper operation"):
                    worker.dispatch(operation, {}, context)

        inputs = {"artifact_dir": "/artifacts", "images": [], "route": {"domain": "IMAGE"}}
        for aliases in ({"snapshot": "/snapshot.blend"},
                        {"snapshot_path": "/snapshot.blend", "target": {}}):
            with self.subTest(aliases=aliases):
                with self.assertRaisesRegex(ValueError, "canonical request"):
                    worker.dispatch("bake", dict(inputs, **aliases), context)


if __name__ == "__main__":
    unittest.main()
