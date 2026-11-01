"""Export a timestamped Perceptual Grade diagnostic snapshot from Blender.

After reproducing the delay with the extension enabled, paste this entire file
into a separate Blender Text Editor and choose Text > Run Script. Keep the Warp
editor visible. The ZIP is written to your Desktop; export once while the pad is
stale and again after it updates if possible.

This is a snapshot, not an interaction timing trace. It includes installed LUT
backend/device receipts, worker timings, active jobs and helper/error logs.
Helper configuration files (which contain authentication tokens) are excluded.

Reproduce the script artifact: buck2 build //products/perceptual-grade-blender:pg_diagnostics --show-output
"""

import bpy
import sys
import json
import time
import zipfile
from pathlib import Path
from datetime import datetime
from dataclasses import asdict


def export_pg_diagnostics():
    applications = [module.registered_session()
                    for name, module in tuple(sys.modules.items())
                    if name.endswith('.perceptual_grade_blender.integration.lifecycle')
                    and module is not None and module.registered_session() is not None]
    if len(applications) != 1:
        raise RuntimeError('Expected one enabled Perceptual Grade extension')
    application = applications[0]
    nodes = application.component('graph.nodes')
    lut = application.component('graph.lut')
    runtime = application.app.execution.current_runtime()

    if runtime is None or runtime.closed:
        raise RuntimeError("No active Perceptual Grade execution runtime")

    now = datetime.now().astimezone()
    status = runtime.gpu_status()
    if status["diagnostic"] is not None:
        status["diagnostic"] = asdict(status["diagnostic"])

    report = {
        "captured_at": now.isoformat(),
        "host_perf_counter": time.perf_counter(),
        "blender": bpy.app.version_string,
        "package": str(runtime.package),
        "fingerprint": runtime.fingerprint,
        "gpu_status": status,
        "helpers": {
            role: {"pid": helper.process.pid, "ready": helper.ready}
            for role, helper in runtime.helpers.items()
        },
        "jobs": [
            {
                "operation": job.spec.operation,
                "actual_lane": job.role,
                "phase": job.state.phase,
                "progress": job.progress,
                "finished": job.finished,
            }
            for job in runtime.jobs.values()
        ],
        "installed_luts": [],
    }

    for node in nodes.all_nodes():
        image = lut.image_for(node) if node.node_tree else None
        timings = {}
        if image is not None:
            timings = {
                key: image[key]
                for key in image.keys()
                if key.startswith("_pg_bake_")
                and type(image[key]) in (str, bool, int, float)
            }
        report["installed_luts"].append({
            "tree": node.id_data.name,
            "node": node.name,
            "backend": node.get("_pg_cube_backend", "not recorded"),
            "device": node.get("_pg_cube_device", ""),
            "fallback_reason": node.get("_pg_cube_backend_reason", ""),
            "lut_size": image.get("_pg_cube_size") if image else None,
            "worker_timings": timings,
        })

    destination = Path.home() / "Desktop"
    destination.mkdir(exist_ok=True)
    path = destination / now.strftime("pg-diagnostics-%Y%m%d-%H%M%S-%f.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps(report, indent=2))
        for pattern in ("helper-*.log", "gpu-diagnostic-*.json"):
            for source in runtime.session.path.glob(pattern):
                archive.write(source, "helpers/" + source.name)

    print(json.dumps(report["installed_luts"], indent=2))
    print("Exported:", path)


export_pg_diagnostics()
