"""Environment helpers for installed Blender subprocess acceptance."""

from pathlib import Path
import os
import sys


def with_pinned_linux_libraries(resources, environment):
    """Add Buck-pinned Blender ABI libraries to a child process environment."""
    if sys.platform != "linux":
        return environment
    library_dirs = (
        Path(str(resources / "bpy_abi")).resolve() / "usr/lib/x86_64-linux-gnu",
        Path(str(resources / "xvfb")).resolve() / "usr/lib/x86_64-linux-gnu",
    )
    library_paths = [str(path) for path in library_dirs if path.is_dir()]
    if not library_paths:
        raise RuntimeError("Pinned Blender ABI library resource is unavailable")
    if environment.get("LD_LIBRARY_PATH"):
        library_paths.append(environment["LD_LIBRARY_PATH"])
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(library_paths)
    environment["LIBGL_ALWAYS_SOFTWARE"] = "1"
    environment["GALLIUM_DRIVER"] = "llvmpipe"
    return environment
