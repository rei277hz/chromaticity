"""Run the pinned Blender template generator with Buck-declared resources."""

from __future__ import annotations

import argparse
from importlib.resources import files
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    resources = Path(str(files("pg_template_build"))).resolve()
    executable = ("Blender.app/Contents/MacOS/Blender"
                  if sys.platform == "darwin" else "blender")
    command = [
        str(resources / "blender" / executable),
        "--background", "--factory-startup", "--disable-autoexec",
        "--python-exit-code", "1", "--python",
        str(resources / "generate_node_templates.py"), "--",
        "--output-dir", str(args.output_dir.resolve()),
        "--packages", str(resources / "packages"),
    ]
    environment = {
        key: value for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                       "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}
    }
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
    with tempfile.TemporaryDirectory(prefix="pg-node-templates-") as temporary:
        environment["BLENDER_USER_CONFIG"] = str(Path(temporary) / "config")
        environment["BLENDER_USER_EXTENSIONS"] = str(Path(temporary) / "extensions")
        subprocess.run(command, check=True, cwd=temporary, env=environment)


if __name__ == "__main__":
    main()
