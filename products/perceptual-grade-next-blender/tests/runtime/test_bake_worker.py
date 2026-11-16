"""Native bake backend selection and exact Cycles GPU admission."""

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

    @staticmethod
    def _fake_bpy(devices):
        preferences = SimpleNamespace(
            compute_device_type="NONE",
            devices=list(devices),
            refresh_devices=lambda: None,
        )
        bpy = SimpleNamespace(context=SimpleNamespace(preferences=SimpleNamespace(
            addons={"cycles": SimpleNamespace(preferences=preferences)},
        )))
        return bpy, preferences

    @staticmethod
    def _scene():
        return SimpleNamespace(cycles=SimpleNamespace(device="CPU"))

    def test_cycles_cpu_is_selected_without_touching_gpu_preferences(self):
        scene = self._scene()
        scene.cycles.device = "GPU"
        result = self.module._configure_cycles_device(
            scene, {"shader_backend": "CYCLES_CPU"},
        )
        self.assertEqual(result, "CPU")
        self.assertEqual(scene.cycles.device, "CPU")

    def test_cycles_gpu_applies_the_exact_enabled_device_set(self):
        devices = [
            SimpleNamespace(id="gpu-1", name="GPU 1", type="METAL", use=False),
            SimpleNamespace(id="gpu-2", name="GPU 2", type="METAL", use=True),
            SimpleNamespace(id="cpu", name="CPU", type="CPU", use=True),
        ]
        bpy, preferences = self._fake_bpy(devices)
        addon_utils = SimpleNamespace(enable=lambda *_args, **_kwargs: None)
        descriptor = {
            "shader_backend": "CYCLES_GPU",
            "cycles_gpu": {
                "compute_device_type": "METAL",
                "devices": ({"id": "gpu-1", "name": "GPU 1", "type": "METAL"},),
            },
        }
        scene = self._scene()
        with patch.dict(sys.modules, {"bpy": bpy, "addon_utils": addon_utils}):
            result = self.module._configure_cycles_device(scene, descriptor)
        self.assertEqual(result, "GPU")
        self.assertEqual(scene.cycles.device, "GPU")
        self.assertEqual(preferences.compute_device_type, "METAL")
        self.assertTrue(devices[0].use)
        self.assertFalse(devices[1].use)
        self.assertFalse(devices[2].use)

    def test_cycles_gpu_missing_device_fails_without_cpu_fallback(self):
        devices = [SimpleNamespace(id="other", name="Other", type="METAL", use=False)]
        bpy, _preferences = self._fake_bpy(devices)
        addon_utils = SimpleNamespace(enable=lambda *_args, **_kwargs: None)
        descriptor = {
            "shader_backend": "CYCLES_GPU",
            "cycles_gpu": {
                "compute_device_type": "METAL",
                "devices": ({"id": "requested", "name": "Requested", "type": "METAL"},),
            },
        }
        scene = self._scene()
        with patch.dict(sys.modules, {"bpy": bpy, "addon_utils": addon_utils}), \
                self.assertRaisesRegex(RuntimeError, "Requested Cycles GPU is unavailable"):
            self.module._configure_cycles_device(scene, descriptor)
        self.assertEqual(scene.cycles.device, "GPU")


if __name__ == "__main__":
    unittest.main()
