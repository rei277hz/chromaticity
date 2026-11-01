"""Verify private compositor input/output capture in installed Blender."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import types

import bpy
import numpy as np


def _execute_registered_bake(bake_operators, context, *, target, domain):
    operator_type = next((
        item for item in bake_operators._CLASSES
        if getattr(item, "bl_idname", "") == "node.pg_next_bake"
    ), None)
    if operator_type is None or not hasattr(bpy.ops.node, "pg_next_bake"):
        raise RuntimeError("Packaged Compositor Bake operator was not registered")
    if not operator_type.poll(context):
        raise RuntimeError("Registered Compositor Bake operator rejected its context")
    reports = []
    operator = types.SimpleNamespace(
        target_image=target,
        domain=domain,
        report=lambda levels, message: reports.append((tuple(levels), str(message))),
    )
    result = operator_type.execute(operator, context)
    return result, reports


def main(repository, report_path):
    if repository == "SOURCE_TREE":
        repository_root = Path(__file__).resolve().parents[4]
        source_root = repository_root / "products/perceptual-grade-next-blender/src"
        color_tools = types.ModuleType("color_tools")
        color_tools.__path__ = [
            str(source_root),
            str(repository_root / "libraries/perceptual-grade-next-core/src"),
            str(repository_root / "libraries/perceptual-grade-nodes/src"),
            str(repository_root / "libraries/color-core/src"),
        ]
        product = types.ModuleType("color_tools.perceptual_grade_next_blender")
        product.__path__ = [str(source_root / "perceptual_grade_next_blender")]
        sys.modules["color_tools"] = color_tools
        sys.modules["color_tools.perceptual_grade_next_blender"] = product
        nodes_package = importlib.import_module("color_tools.perceptual_grade_nodes")
        resource_files = tuple((
            repository_root / "buck-out/v2/art/root/libraries/perceptual-grade-nodes"
            / "__runtime_bundle__").glob("*/packages/perceptual_grade_nodes/output_boundary.npz"))
        if not resource_files:
            raise RuntimeError("Build //libraries/perceptual-grade-nodes:boundary_resource first")
        boundary = importlib.import_module("color_tools.perceptual_grade_nodes.boundary")
        resource_path = resource_files[0]
        def load_boundary(fl, aw, gamma):
            with resource_path.open("rb") as stream:
                return boundary._load_boundary(stream, fl, aw, gamma)
        boundary.prepare_boundary = load_boundary
        capture = importlib.import_module(
            "color_tools.perceptual_grade_next_blender.native_compositor_bake"
        )
        product_module = "color_tools.perceptual_grade_next_blender."
        extension_origin = "source tree"
    else:
        repository = Path(repository).resolve()
        bpy.context.preferences.extensions.repos.new(
            name="Perceptual Grade Next compositor capture",
            module="pg_next_compositor_capture",
            custom_directory=str(repository),
        )
        module = "bl_ext.pg_next_compositor_capture.perceptual_grade"
        errors = []
        addon = addon_utils.enable(module, default_set=False, handle_error=errors.append)
        if addon is None or errors:
            raise RuntimeError("Could not enable packaged Next extension: %r" % errors)
        capture = importlib.import_module(
            module + ".perceptual_grade_next_blender.native_compositor_bake"
        )
        product_module = module + ".perceptual_grade_next_blender."
        extension_origin = str(Path(addon.__file__).resolve())
    native_grade_module = importlib.import_module(product_module + "native_grade")
    controls = importlib.import_module(product_module + "controls")
    updates = importlib.import_module(product_module + "updates")
    bake_operators = importlib.import_module(product_module + "bake_operators")
    core = importlib.import_module("color_tools.perceptual_grade_next_core"
                                   if repository == "SOURCE_TREE" else
                                   module + ".perceptual_grade_next_core")
    controls.register()

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.compositor_device = "CPU"
    scene.render.resolution_x = 4
    scene.render.resolution_y = 2
    scene.render.resolution_percentage = 100
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.render.use_sequencer = False

    source_values = np.asarray((
        ((0.1, 0.2, 0.3, 0.25), (0.4, 0.5, 0.6, 0.5)),
        ((0.7, 0.8, 0.9, 0.75), (1.0, 0.9, 0.8, 1.0)),
    ), dtype=np.float32)
    source = bpy.data.images.new(
        "Compositor Snapshot Source", 2, 2, alpha=True, float_buffer=True,
    )
    source.use_half_precision = False
    source.colorspace_settings.name = "Non-Color"
    source.alpha_mode = "CHANNEL_PACKED"
    source.pixels.foreach_set(source_values.reshape(-1))
    source.update()

    settings = core.GradeSettings(
        linear=core.LinearSettings(exposure=1.0),
    )
    native = native_grade_module.build_native_grade(
        settings=settings, tree_type="CompositorNodeTree",
        name="Compositor Snapshot Grade",
    )

    root = bpy.data.node_groups.new(
        "Compositor Snapshot Root", "CompositorNodeTree",
    )
    root.interface.new_socket(
        name="Color", in_out="INPUT", socket_type="NodeSocketColor",
    )
    root.interface.new_socket(
        name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
    )
    image_node = root.nodes.new("CompositorNodeImage")
    image_node.image = source
    owner = root.nodes.new("CompositorNodeGroup")
    owner.node_tree = native.tree
    owner["perceptual_grade_next_backend"] = "native_grade_graph"
    owner["perceptual_grade_next_schema"] = 1
    owner["perceptual_grade_next_settings"] = native.tree[
        "perceptual_grade_next_settings"
    ]
    owner["perceptual_grade_next_edit_revision"] = 0
    owner["perceptual_grade_next_applied_revision"] = 0
    owner["perceptual_grade_next_preparation_state"] = "READY"
    owner["perceptual_grade_next_preparation_error"] = ""
    controls.attach_controls(owner, native.settings)
    readiness = importlib.import_module(
        name + ".perceptual_grade_next_blender.project_readiness"
    )
    readiness.accept_grade_manifest(owner, native)
    updates.register_native_owner(owner, native, "grade")
    root_output = root.nodes.new("NodeGroupOutput")
    root_output.is_active_output = True
    root.links.new(image_node.outputs["Image"], owner.inputs["Color"])
    root.links.new(owner.outputs["Color"], root_output.inputs["Color"])
    scene.compositing_node_group = root

    before = {
        "scene": scene.as_pointer(),
        "root": root.as_pointer(),
        "nodes": tuple(node.as_pointer() for node in root.nodes),
        "engine": scene.render.engine,
        "resolution": (scene.render.resolution_x, scene.render.resolution_y),
        "render_path": scene.render.filepath,
    }
    source_capture = capture.capture_compositor_signal(
        scene, root, root, owner, (), stage="input",
    )
    verified_source, graded = capture.capture_compositor_signal(
        scene, root, root, owner, (), stage="output",
    )
    after = {
        "scene": scene.as_pointer(),
        "root": root.as_pointer(),
        "nodes": tuple(node.as_pointer() for node in root.nodes),
        "engine": scene.render.engine,
        "resolution": (scene.render.resolution_x, scene.render.resolution_y),
        "render_path": scene.render.filepath,
    }
    if not np.allclose(source_capture, source_values, atol=1e-6, rtol=0):
        raise RuntimeError(
            "Compositor source snapshot differs: shape=%r pixels=%r expected=%r"
            % (source_capture.shape, source_capture.tolist(), source_values.tolist())
        )
    if not np.array_equal(verified_source, source_capture):
        raise RuntimeError("Compositor source changed between snapshot and output")
    if not np.isfinite(graded).all() or np.array_equal(graded, source_values):
        raise RuntimeError("Native Compositor Grade did not produce graded pixels")
    if before != after or scene.compositing_node_group is not root:
        raise RuntimeError("Private Compositor Bake changed caller scene state")

    target = bpy.data.images.new(
        "Compositor Bake Target", 2, 2, alpha=True, float_buffer=True,
    )
    target.use_half_precision = False
    target.colorspace_settings.name = "Non-Color"
    prior = np.full((2, 2, 4), 7.0, dtype=np.float32)
    target.pixels.foreach_set(prior.reshape(-1))
    target.update()
    operator_result, operator_reports = _execute_registered_bake(
        bake_operators,
        types.SimpleNamespace(
            space_data=types.SimpleNamespace(edit_tree=root),
            active_node=owner,
            scene=scene,
            screen=types.SimpleNamespace(is_animation_playing=False),
        ),
        target=target,
        domain="IMAGE",
    )
    if operator_result != {"FINISHED"} or operator_reports:
        raise RuntimeError(
            "Registered Compositor Bake operator did not finish: %r %r"
            % (operator_result, operator_reports)
        )
    result = target
    result_pixels = importlib.import_module(
        product_module + "native_bake"
    ).read_image_rgba(result)
    if result is not target or np.array_equal(result_pixels, prior):
        raise RuntimeError("Compositor Bake did not publish to the selected Image")
    if not np.allclose(result_pixels[..., 3], source_values[..., 3], atol=1e-6, rtol=0):
        raise RuntimeError("Compositor Grade Bake changed alpha")
    if not np.allclose(result_pixels[..., :3], graded[..., :3],
                       atol=2e-5, rtol=1e-6):
        raise RuntimeError("Registered Compositor Bake differs from native graph output")
    if target.get("perceptual_grade_next_bake_active_backup"):
        raise RuntimeError("Compositor Bake recovery backing was not retired")

    frozen_target = bpy.data.images.new(
        "Compositor Frozen Input Rejection", 2, 2, alpha=True, float_buffer=True,
    )
    frozen_target.use_half_precision = False
    frozen_target.colorspace_settings.name = "Non-Color"
    frozen_prior = np.full((2, 2, 4), -3.0, dtype=np.float32)
    frozen_target.pixels.foreach_set(frozen_prior.reshape(-1))
    frozen_target.update()
    original_capture = bake_operators.capture_compositor_signal
    injected = {"done": False}

    def mutate_between_freeze_and_evaluation(*args, **kwargs):
        if kwargs.get("stage") == "output" and not injected["done"]:
            changed_source = source_values.copy()
            changed_source[0, 0, 0] += 0.125
            source.pixels.foreach_set(changed_source.reshape(-1))
            source.update()
            injected["done"] = True
        return original_capture(*args, **kwargs)

    bake_operators.capture_compositor_signal = mutate_between_freeze_and_evaluation
    try:
        rejected_result, rejected_reports = _execute_registered_bake(
            bake_operators,
            types.SimpleNamespace(
                space_data=types.SimpleNamespace(edit_tree=root),
                active_node=owner,
                scene=scene,
                screen=types.SimpleNamespace(is_animation_playing=False),
            ),
            target=frozen_target,
            domain="IMAGE",
        )
    finally:
        bake_operators.capture_compositor_signal = original_capture
        source.pixels.foreach_set(source_values.reshape(-1))
        source.update()
    frozen_after = importlib.import_module(
        product_module + "native_bake"
    ).read_image_rgba(frozen_target)
    if not injected["done"] or rejected_result != {"CANCELLED"} or not rejected_reports:
        raise RuntimeError(
            "Registered Compositor Bake did not reject a changed frozen input: %r %r"
            % (rejected_result, rejected_reports)
        )
    if not np.array_equal(frozen_after, frozen_prior):
        raise RuntimeError("Rejected Compositor Bake changed its destination Image")
    if frozen_target.get("perceptual_grade_next_bake_active_backup"):
        raise RuntimeError("Rejected Compositor Bake retained recovery backing")

    Path(report_path).write_text(json.dumps({
        "passed": True,
        "blender": list(bpy.app.version),
        "extension_origin": extension_origin,
        "source_shape": list(source_capture.shape),
        "output_shape": list(graded.shape),
        "source_verified": True,
        "scene_preserved": True,
        "operator_published": True,
        "registered_operator_finished": operator_result == {"FINISHED"},
        "frozen_input_change_rejected": rejected_result == {"CANCELLED"},
        "publication_recovery_cleared": True,
        "alpha_preserved": True,
        "output_min": float(graded.min()),
        "output_max": float(graded.max()),
    }, sort_keys=True), encoding="utf8")


if __name__ == "__main__":
    main(*sys.argv[sys.argv.index("--") + 1:])
