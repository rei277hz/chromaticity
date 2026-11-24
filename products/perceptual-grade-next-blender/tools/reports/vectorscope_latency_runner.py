"""Exercise vectorscope source captures and cached Linear edits in Blender's GUI."""

from dataclasses import asdict
from functools import partial
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import addon_utils
import bpy
import gpu
import numpy as np


WIDTH, HEIGHT = 96, 64
RED = (0.72, 0.05, 0.28, 1.0)
GREEN = (0.02, 0.70, 0.05, 1.0)
BLUE = (0.02, 0.08, 0.84, 1.0)


def _paint(image, color):
    image.pixels.foreach_set(np.tile(np.asarray(color, dtype=np.float32), WIDTH * HEIGHT))
    image.update()
    image.update_tag()


def _image(name, width, height):
    image = bpy.data.images.new(name, width=width, height=height, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    return image


def _camera(scene, scale):
    data = bpy.data.cameras.new("Vectorscope fixture camera")
    data.type = "ORTHO"
    data.ortho_scale = scale
    camera = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, 0.0, 5.0)
    scene.camera = camera


def _expected_peak(color, exposure):
    linear = np.asarray(color[:3]) * 2.0 ** exposure
    code = np.where(linear < 0.018, 4.5 * linear, 1.099 * linear ** 0.45 - 0.099)
    luma = np.dot(code, (0.2126, 0.7152, 0.0722))
    chroma = ((code[0] - luma) / 1.5748, (code[2] - luma) / 1.8556)
    return tuple(int((value + 0.65) * 144 / 1.3) for value in chroma)


class Session:
    def __init__(self, config):
        self.report_path = Path(config["report"])
        self.timeout = config["sample_timeout"]
        self.scenario = config["scenario"]
        self.report = {"scenario": self.scenario, "completed": False,
                       "samples": [], "linear_controls": [],
                       "reducers": [], "reducer_checks": [],
                       "reducer_cleanup_checks": [], "color_component_checks": []}
        self.records = []
        self.reducer_dataset = None

        sys.path.insert(0, config["benchmark_import_path"])
        bpy.context.preferences.view.show_splash = False
        bpy.context.preferences.extensions.repos.new(
            name="Perceptual Grade vectorscope timing", module="pg_vectorscope_timing",
            custom_directory=config["repository"],
        )
        extension = importlib.import_module("bl_ext.pg_vectorscope_timing.perceptual_grade")
        self.nodes = importlib.import_module(extension.__name__ + ".nodes")
        self.ui = importlib.import_module(extension.__name__ + ".vectorscope_ui")
        self.analysis = importlib.import_module(extension.__name__ + ".vectorscope")
        self.capture = importlib.import_module(
            extension.__name__ + ".runtime.vectorscope_capture"
        )
        self.reducer_selection = config["reducer"]
        errors = []
        assert addon_utils.enable(extension.__name__, default_set=False,
                                  handle_error=errors.append) is extension, errors
        assert not errors and not bpy.app.background, errors
        self.runtime = self.ui._runtime
        self.runtime.timing = self.record_timing
        self.invalidations = None
        self.invalidate = self.runtime.invalidate
        self.runtime.invalidate = self.trace_invalidation

        self.scene = bpy.context.scene
        render = self.scene.render
        engines = {item.identifier for item in render.bl_rna.properties["engine"].enum_items}
        engine = next((name for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
                       if name in engines), None)
        assert engine is not None, ("EEVEE is unavailable", sorted(engines))
        render.engine = engine
        render.resolution_x, render.resolution_y = WIDTH, HEIGHT
        render.resolution_percentage = 100
        render.use_compositing = self.scenario != "shader_viewport"
        render.compositor_device = "CPU"
        render.compositor_precision = "FULL"
        render.film_transparent = False
        self.scene.view_settings.view_transform = "Standard"
        self.window = bpy.context.window
        self.area = next(item for item in self.window.screen.areas if item.type == "VIEW_3D")
        self.report["environment"] = {
            "blender": bpy.app.version_string,
            "blender_build": bpy.app.build_hash.decode("ascii"),
            "gpu_backend": gpu.platform.backend_type_get(),
            "gpu_renderer": gpu.platform.renderer_get(),
            "gpu_version": gpu.platform.version_get(),
            "render_engine": render.engine,
            "compositor_device": render.compositor_device,
            "scene_dimensions": [WIDTH, HEIGHT],
        }

    def scope_revision(self):
        with self.runtime._observations:
            epoch = self.runtime.source_epochs.get(self.key)
        payload = self.runtime.payloads.get(self.key)
        return {"source_epoch": epoch,
                "route_signature": None if payload is None else payload.route["capture_signature"]}

    def trace_invalidation(self, scene=None, changed_ids=()):
        invalidations = self.invalidations
        if invalidations is None:
            return self.invalidate(scene, changed_ids)
        changed_ids = tuple(changed_ids)
        with self.runtime._observations:
            dependencies = self.runtime.dependencies.get(self.key, frozenset())
            previous_epoch = self.runtime.source_epochs.get(self.key)
        timestamp = time.perf_counter_ns()
        affected = self.invalidate(scene, changed_ids)
        with self.runtime._observations:
            epoch = self.runtime.source_epochs.get(self.key)
        identifiers = []
        for identifier in changed_ids:
            try:
                pointer = int(identifier.as_pointer())
                identifiers.append({
                    "pointer": pointer,
                    "name": str(getattr(identifier, "name_full",
                                         getattr(identifier, "name", ""))),
                    "type": str(getattr(getattr(identifier, "bl_rna", None),
                                         "identifier", type(identifier).__name__)),
                    "matches_dependency": pointer in dependencies,
                })
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        invalidations.append({
            "time_ns": timestamp, "changed_ids": identifiers,
            "affected_scope": self.key in affected,
            "previous_source_epoch": previous_epoch, "source_epoch": epoch,
        })
        return affected

    def record_timing(self, stage, start_ns, end_ns, ticket, metadata):
        if self.invalidations is not None and stage == "request":
            metadata = {**metadata, **self.scope_revision()}
        self.records.append({
            "stage": stage, "clock": metadata["clock"],
            "start_ns": start_ns, "end_ns": end_ns, "duration_ms": (end_ns - start_ns) / 1e6,
            "ticket": None if ticket is None else asdict(ticket), "metadata": metadata,
        })

    def checkpoint(self, step):
        self.report["step"] = step
        pending = self.report_path.with_suffix(".json.tmp")
        pending.write_text(json.dumps(self.report, indent=2, allow_nan=False) + "\n", encoding="utf8")
        pending.replace(self.report_path)

    def editor(self, tree, grade):
        self.area.type = "NODE_EDITOR"
        self.area.ui_type = tree.bl_idname
        space = self.area.spaces.active
        if tree.bl_idname == self.nodes.SHADER_TREE:
            space.shader_type = "OBJECT"
        space.pin = True
        space.node_tree = tree
        space.show_region_ui = True
        tree.nodes.active = grade
        for node in tree.nodes:
            node.select = node == grade
        self.region = next(region for region in self.area.regions if region.type == "WINDOW")
        self.key = self.ui._key(self.window, self.area)

    def display(self):
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            return self.ui.display_state(bpy.context)

    def compare_reducers(self, path, dataset):
        from tools.perceptual_grade.reports.vectorscope_reducers import (
            _parity_pixels, compare_color_components, compare_reducers,
        )
        from tools.perceptual_grade.reports.vectorscope_shader_tree import (
            shader_reducer, verify_failure_cleanup,
        )

        comparisons, checks = compare_reducers(
            self.analysis, {path: dataset}, self.reducer_selection,
            partial(shader_reducer, capture=self.capture),
        )
        self.report["reducers"].extend(comparisons)
        self.report["reducer_checks"].extend(checks)
        rgba, matrix, space, _capture_ms = dataset
        self.report["color_component_checks"].append({
            "path": path, **compare_color_components(self.analysis, rgba, matrix, space),
        })
        if path == "direct_image":
            pixels = _parity_pixels(self.analysis)
            pixels[..., :3] *= 0.5
            self.report["color_component_checks"].append({
                "fixture": "signed_alpha_and_bin_boundaries",
                **compare_color_components(
                    self.analysis, pixels, 2.0 * np.eye(3), "Linear Rec.709",
                ),
            })
        if path == "direct_image" and self.reducer_selection in {"all", "shader-tree"}:
            shader_check = next(row for row in checks if row["name"] == "shader-tree")
            failure = verify_failure_cleanup(pixels, 2.0 * np.eye(3), capture=self.capture)
            self.report["reducer_cleanup_checks"].append({
                "path": path,
                "success_temporary_ids_clean": shader_check["temporary_ids_clean"],
                "failure": failure,
            })

    def run_reducer_comparison(self):
        if self.reducer_dataset is not None:
            path, dataset = self.reducer_dataset
            self.compare_reducers(path, dataset)

    def toggle(self):
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            assert bpy.ops.perceptual_grade.toggle_vectorscope() == {"FINISHED"}

    def measure(self, path, ordinal, trigger, edit, color, exposure=0.0):
        control = trigger == "linear_exposure"
        self.checkpoint(f"{path} / {trigger} / {ordinal}")
        old = self.display()
        previous = None if old is None else old.brightness
        previous_generation = self.runtime.state.generation
        previous_ticket = next((item for item in self.runtime.state.desired if item.key == self.key), None)
        expected = _expected_peak(color, exposure)
        self.records.clear()
        if control:
            previous_revision = self.scope_revision()
            self.invalidations = []
        trigger_ns = time.perf_counter_ns()
        edit()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            display = self.display()
            if display is not None:
                assert display.status not in {"error", "unavailable"}, display.error
            state = self.runtime.state
            publication = next((item for item in state.published if item.key == self.key), None)
            ticket = next((item for item in state.desired if item.key == self.key), None)
            if (display is None or display.status != "current" or publication is None
                    or ticket is None or ticket.generation <= previous_generation
                    or publication.current_generation != ticket.generation):
                yield
                continue
            current = [record for record in self.records if record["ticket"]["generation"] == ticket.generation]
            published = next((record for record in current if record["stage"] == "publish"
                              and record["metadata"]["current"]), None)
            draw = next((record for record in current if record["stage"] == "draw"), None)
            if published is None or draw is None:
                yield
                continue

            brightness = display.brightness
            assert brightness.shape == (144, 144) and np.isfinite(brightness).all(), brightness.shape
            assert display.rgba.shape == (144, 144, 4) and not display.rgba.flags.writeable
            peak = tuple(int(value) for value in np.unravel_index(np.argmax(brightness), brightness.shape))
            if (not np.any(brightness > 0) or np.array_equal(brightness, previous)
                    or max(abs(value - target) for value, target in zip(peak, expected)) > 1):
                yield
                continue
            request_ns = next(record["start_ns"] for record in current if record["stage"] == "request")
            publication_ns = published["end_ns"]
            draw_ns = draw["end_ns"]
            assert trigger_ns <= request_ns <= publication_ns <= draw_ns
            capture_generation = published["metadata"]["capture_generation"]
            records = [record for record in self.records
                       if record["ticket"]["generation"] in {ticket.generation, capture_generation}
                       and record["ticket"]["capture_signature"] == ticket.capture_signature
                       and record["ticket"]["source_signature"] == ticket.source_signature
                       and (record["stage"] not in {"draw", "publish"} or record is draw or record is published)]
            requested_generations = [record["ticket"]["generation"] for record in self.records
                                     if record["stage"] == "request"]
            rgba = self.runtime.samples[ticket.capture_signature]
            height, width = rgba.shape[:2]
            helper_reused = next((record["metadata"]["helper_reused"] for record in records
                                  if "helper_reused" in record["metadata"]), None)
            identity = asdict(ticket)
            identity.pop("key")
            sample = {
                **identity,
                "path": path, "phase": "warm" if control or ordinal else "cold",
                "ordinal": ordinal, "trigger": trigger, "frame": int(self.scene.frame_current),
                "capture_dimensions": [width, height], "peak_bin": list(peak),
                "helper_reused": helper_reused,
                "capture_reused": any(record["stage"] == "cached_density" for record in current),
                "capture_generation": capture_generation, "previous_generation": previous_generation,
                "previous_capture_signature": None if previous_ticket is None else previous_ticket.capture_signature,
                "requested_generations": requested_generations,
                "superseded": len(requested_generations) > 1,
                "trigger_ns": trigger_ns, "request_ns": request_ns,
                "publication_ns": publication_ns, "draw_ns": draw_ns,
                "latency_ms": (publication_ns - trigger_ns) / 1e6,
                "draw_latency_ms": (draw_ns - trigger_ns) / 1e6,
                "timing_records": records,
            }
            if control:
                sample["previous_revision"] = previous_revision
                sample["invalidations"] = self.invalidations
                sample["attempt_timing_records"] = list(self.records)
                self.invalidations = None
            self.report["linear_controls" if control else "samples"].append(sample)
            if not control and ordinal == 2:
                density = next((record for record in records
                                if record["stage"] == "result_density"
                                and record["ticket"]["generation"] == capture_generation), None)
                if density is None:
                    raise RuntimeError("Reducer comparison is missing its matching capture density timing")
                payload = self.runtime.payloads[self.key]
                capture_ms = (density["start_ns"] - trigger_ns) / 1e6
                self.reducer_dataset = (
                    path, (rgba.copy(), payload.matrix.copy(), payload.space, capture_ms),
                )
            return
        self.report["pending_timings"] = self.records
        if self.invalidations is not None:
            self.report["pending_invalidations"] = self.invalidations
        raise TimeoutError(f"No matching current vectorscope draw for {path} / {trigger}")

    def compositor(self):
        scene = self.scene
        _camera(scene, 4.0)
        tree = bpy.data.node_groups.new("Vectorscope compositor fixture", self.nodes.COMPOSITOR_TREE)
        tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        scene.compositing_node_group = tree
        source = tree.nodes.new("CompositorNodeImage")
        source.image = _image("Vectorscope Image", WIDTH, HEIGHT)
        _paint(source.image, RED)
        image_output = source.outputs["Image"]
        if self.scenario == "processed_compositor":
            transform = tree.nodes.new("CompositorNodeTransform")
            transform.inputs["X"].default_value = 9.0
            transform.inputs["Scale"].default_value = 0.82
            tree.links.new(image_output, transform.inputs["Image"])
            image_output = transform.outputs["Image"]
        grade = self.nodes.create_per_node_node(tree)
        endpoint = tree.nodes.new("NodeGroupOutput")
        tree.links.new(image_output, grade.inputs["Color"])
        tree.links.new(grade.outputs["Color"], endpoint.inputs["Color"])
        self.editor(tree, grade)
        yield

        path = self.scenario
        yield from self.measure(path, 0, "enable_scope", self.toggle, RED)
        for ordinal, color in enumerate((GREEN, BLUE), 1):
            yield from self.measure(path, ordinal, "image_pixels", lambda: _paint(source.image, color), color)
        yield from self.measure(path, 0, "linear_exposure", lambda: setattr(grade, "exposure", 1.0), BLUE, 1.0)

    def shader(self):
        scene = self.scene
        mesh = bpy.data.meshes.new("Vectorscope shader mesh")
        mesh.from_pydata(((-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)), (), ((0, 1, 2, 3),))
        uv = mesh.uv_layers.new(name="Vectorscope UV")

        def move_uv(u):
            for item in uv.uv:
                item.vector = (u, 0.5)
            mesh.update()
            mesh.update_tag()

        move_uv(0.25)
        obj = bpy.data.objects.new("Vectorscope shader plane", mesh)
        scene.collection.objects.link(obj)
        material = bpy.data.materials.new("Vectorscope shader material")
        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        image = _image("Vectorscope UV texture", 2, 1)
        image.pixels.foreach_set(np.asarray((*RED, *BLUE), dtype=np.float32))
        image.update()
        coordinates = tree.nodes.new("ShaderNodeUVMap")
        coordinates.uv_map = uv.name
        color = tree.nodes.new("ShaderNodeTexImage")
        color.image = image
        color.interpolation = "Closest"
        grade = self.nodes.create_per_node_node(tree)
        shader = tree.nodes.new("ShaderNodeEmission")
        endpoint = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(coordinates.outputs["UV"], color.inputs["Vector"])
        tree.links.new(color.outputs["Color"], grade.inputs["Color"])
        tree.links.new(grade.outputs["Color"], shader.inputs["Color"])
        tree.links.new(shader.outputs[0], endpoint.inputs["Surface"])
        obj.data.materials.append(material)
        _camera(scene, 5.0)
        for item in scene.objects:
            item.select_set(item == obj)
        bpy.context.view_layer.objects.active = obj
        self.editor(tree, grade)
        view = next(item for item in self.window.screen.areas if item.type == "OUTLINER")
        view.type = "VIEW_3D"
        view.spaces.active.region_3d.view_perspective = "CAMERA"
        yield

        path = "shader_viewport"
        yield from self.measure(path, 0, "enable_scope", self.toggle, RED)
        yield from self.measure(path, 1, "mesh_uv", lambda: move_uv(0.75), BLUE)
        yield from self.measure(path, 2, "mesh_uv", lambda: move_uv(0.25), RED)
        yield from self.measure(path, 0, "linear_exposure", lambda: setattr(grade, "exposure", 1.0), RED, 1.0)

    def quit(self):
        with bpy.context.temp_override(window=self.window):
            assert bpy.ops.wm.quit_blender("EXEC_DEFAULT") == {"FINISHED"}
            self.window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=640, y=480)
        return None

    def start(self):
        sequence = self.shader() if self.scenario == "shader_viewport" else self.compositor()

        def advance():
            try:
                next(sequence)
                return 0.02
            except StopIteration:
                self.runtime.timing = None
                self.runtime.invalidate = self.invalidate
                try:
                    self.run_reducer_comparison()
                except Exception:
                    self.report["reducer_error"] = traceback.format_exc()
                    self.checkpoint("reducer comparison")
                    print(self.report["reducer_error"], flush=True)
                    os._exit(1)
                self.report["completed"] = True
                self.checkpoint("completed")
                bpy.app.timers.register(self.quit, first_interval=0.1, persistent=True)
                return None
            except Exception:
                self.report["error"] = traceback.format_exc()
                self.report["pending_timings"] = self.records
                self.checkpoint(self.report.get("step", "setup"))
                print(self.report["error"], flush=True)
                os._exit(1)

        bpy.app.timers.register(advance, first_interval=0.2, persistent=True)


if __name__ == "__main__":
    configuration = Path(sys.argv[sys.argv.index("--") + 1])
    Session(json.loads(configuration.read_text(encoding="utf8"))).start()
