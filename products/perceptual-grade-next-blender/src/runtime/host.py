"""Blender-specific process launch and isolated-helper configuration."""

import os
import sys


def launch_command(config):
    import bpy

    if bpy.app.binary_path:
        return [
            bpy.app.binary_path,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            config["worker_entry"],
            "--",
            config["config_path"],
        ]
    return [sys.executable, config["worker_entry"], config["config_path"]]


def worker_environment():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in sys.path
        if path and "/bpy/" not in path.replace("\\", "/")
    )
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    return environment


def configure_helper(settings):
    try:
        import bpy
    except ImportError:
        return {}
    backend = settings.get("gpu_backend", "")
    if backend:
        try:
            bpy.context.preferences.system.gpu_backend = backend
        except (TypeError, ValueError):
            pass
    try:
        import gpu
        renderer = gpu.platform.renderer_get()
    except Exception:
        renderer = ""
    return {
        "blender": list(bpy.app.version),
        "gpu_backend": getattr(bpy.context.preferences.system, "gpu_backend", ""),
        "renderer": renderer,
    }
