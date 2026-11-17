"""Run a template test module inside a pinned native Blender runtime."""

import importlib
import json
from pathlib import Path
import sys
import unittest


def main():
    config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    bpy = __import__("bpy")
    __import__("numpy")
    expected_version = tuple(config.get("blender_version", (5, 2, 4)))
    if tuple(bpy.app.version) != expected_version:
        raise RuntimeError(
            f"Template tests require Blender {expected_version}, got {bpy.app.version_string}")
    for entry in config["python_paths"]:
        if entry and entry not in sys.path:
            sys.path.append(entry)
    module = importlib.import_module(config["test_module"])
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
