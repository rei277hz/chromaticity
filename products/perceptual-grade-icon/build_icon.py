"""Run the pinned Blender icon generator with its declared build resources."""
from __future__ import annotations

import argparse
from importlib.resources import files
import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    resources = Path(str(files("pg_icon_build"))).resolve()
    if sys.platform == "darwin":
        blender = resources / "blender" / "Blender.app" / "Contents" / "MacOS" / "Blender"
    else:
        blender = resources / "blender" / "blender"
    generator = resources / "generate_icon.py"
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(generator),
        "--",
        "--output-dir",
        str(args.output_dir.resolve()),
        "--config",
        str(resources / "icon_config.json"),
        "--model",
        str(resources / "modcam16.py"),
    ]
    environment = os.environ.copy()
    environment.update({
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    })
    native_libraries = resources / "native-libs" / "usr" / "lib" / "x86_64-linux-gnu"
    if native_libraries.is_dir():
        existing = environment.get("LD_LIBRARY_PATH")
        environment["LD_LIBRARY_PATH"] = os.pathsep.join(
            path for path in (str(native_libraries), existing) if path
        )
    subprocess.run(command, check=True, env=environment)


if __name__ == "__main__":
    main()
