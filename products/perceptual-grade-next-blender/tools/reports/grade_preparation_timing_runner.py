"""Run Grade preparation measurements inside Blender."""

import asyncio
import importlib
import json
from pathlib import Path
import sys
import time
import traceback


def main():
    initialization_started = time.perf_counter()
    import bpy

    config_path = Path(sys.argv[sys.argv.index("--") + 1])
    config = json.loads(config_path.read_text(encoding="utf8"))
    report_path = Path(config["report"])
    sys.path.insert(0, config["package_root"])
    nodes = importlib.import_module("perceptual_grade.nodes")
    settings_module = importlib.import_module("perceptual_grade.kernel.settings")
    prep_module = importlib.import_module("perceptual_grade.runtime.grade_preparation")
    graph_module = importlib.import_module("perceptual_grade.kernel.graph")
    Settings = settings_module.Settings
    LinearSettings = settings_module.LinearSettings
    ToneSettings = settings_module.ToneSettings
    GradePreparer = prep_module.GradePreparer

    report = {
        "schema": 1,
        "completed": False,
        "blender": bpy.app.version_string,
        "initialization_seconds": time.perf_counter() - initialization_started,
        "samples": [],
    }
    preparer = GradePreparer(workers=3)
    original_upload = graph_module.Graph._packed_image
    active_uploads = None

    def timed_upload(graph, pixels, **kwargs):
        previous = len(graph.images)
        started = time.perf_counter()
        image = original_upload(graph, pixels, **kwargs)
        if active_uploads is not None and len(graph.images) != previous:
            active_uploads.append({
                "label": kwargs.get("label", "Perceptual Grade coefficients"),
                "shape": list(pixels.shape),
                "seconds": time.perf_counter() - started,
            })
        return image

    graph_module.Graph._packed_image = timed_upload
    try:
        for index in range(config["samples"]):
            tone = ToneSettings(fit=0.0 if index == 0 else min(2.0, 0.25 * index))
            settings = Settings(
                linear=LinearSettings(exposure=0.0 if index == 0 else 0.1 * index),
                tone=tone,
            )
            timings = {}

            def on_timing(_signature, component, started, finished):
                timings[component] = max(0.0, finished - started)

            preparer.on_timing = on_timing
            preparation_started = time.perf_counter()
            prepared = asyncio.run(preparer.prepare(settings))
            preparation_total = time.perf_counter() - preparation_started
            signature = prep_module.preparation_signature(settings)
            sample = {
                "cold": index == 0,
                "tone": "reset" if index == 0 else "adjusted",
                "preparation_signature": signature,
                "preparation": dict(timings),
                "preparation_total_seconds": preparation_total,
                "kernel_build": {},
                "texture_uploads": [],
            }
            active_uploads = sample["texture_uploads"]
            for tree_type in (nodes.SHADER_TREE, nodes.COMPOSITOR_TREE):
                started = time.perf_counter()
                tree = nodes._kernel(
                    tree_type, prepared, settings.space, signature
                )
                sample["kernel_build"][tree_type] = time.perf_counter() - started
                sample.setdefault("node_counts", {})[tree_type] = len(tree.nodes)
                bpy.data.node_groups.remove(tree, do_unlink=True)
            for image in tuple(bpy.data.images):
                if image.users == 0 and image.get("_perceptual_grade_image"):
                    bpy.data.images.remove(image)
            active_uploads = None
            report["samples"].append(sample)
    except BaseException as error:
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        graph_module.Graph._packed_image = original_upload
        active_uploads = None
        preparer.close()
        report["completed"] = "error" not in report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf8"
        )
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
