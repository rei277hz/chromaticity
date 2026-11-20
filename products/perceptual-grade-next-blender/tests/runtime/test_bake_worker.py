"""Native Shader Bake uses the fixed Cycles CPU backend."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
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


if __name__ == "__main__":
    unittest.main()
