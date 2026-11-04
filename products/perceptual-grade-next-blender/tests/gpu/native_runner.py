"""Run the GPU unittest module inside Blender's native Python runtime."""

import json
import importlib
from pathlib import Path
import sys
import unittest


def main():
    config_path = Path(sys.argv[sys.argv.index("--") + 1])
    config = json.loads(config_path.read_text(encoding="utf8"))

    # Load Blender's host modules before adding Buck's paths. In particular,
    # `gpu` is supplied by Blender and must not be resolved from a Python wheel.
    __import__("bpy")
    __import__("gpu")
    __import__("numpy")

    # Buck's test link tree carries the product and reference Python sources.
    # Add those directories after Blender's own paths so Blender's native bpy
    # remains authoritative while pure-Python project modules stay available.
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
