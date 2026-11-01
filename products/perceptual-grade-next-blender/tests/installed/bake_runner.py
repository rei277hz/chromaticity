"""Exercise the checked still-Image Shader Bake in native Blender."""

import addon_utils
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

import bpy
import numpy as np


def _execute_registered_bake(bake_operators, context, *, target, domain):
    operators = tuple(bake_operators._CLASSES)
    operator_type = next((
        item for item in operators
        if getattr(item, "bl_idname", "") == "node.pg_next_bake"
    ), None)
    if operator_type is None:
        raise RuntimeError("Packaged Bake operator was not registered")
    if not hasattr(bpy.ops.node, "pg_next_bake"):
        raise RuntimeError("Blender does not expose the registered Bake operator")
    if not operator_type.poll(context):
        raise RuntimeError("Registered Bake operator rejected the prepared context")
    reports = []
    operator = SimpleNamespace(
        target_image=target,
        domain=domain,
        report=lambda levels, message: reports.append((tuple(levels), str(message))),
    )
    result = operator_type.execute(operator, context)
    return result, reports


def _enable(repository):
    repository = Path(repository).resolve()
    bpy.context.preferences.extensions.repos.new(
        name="Perceptual Grade Next Bake acceptance",
        module="pg_next_bake_acceptance",
        custom_directory=str(repository),
    )
    name = "bl_ext.pg_next_bake_acceptance.perceptual_grade"
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    if addon is None or errors:
        raise RuntimeError("Could not enable packaged Next extension: %r" % errors)
    package = repository / "perceptual_grade" / "__init__.py"
    if Path(addon.__file__).resolve() != package:
        raise RuntimeError("Blender imported Bake code outside the packaged extension")
    return name, addon


def main(repository, report_path):
    if tuple(bpy.app.version) != (5, 2, 2):
        raise RuntimeError("Installed Bake acceptance requires Blender 5.2.2")
    name, addon = _enable(repository)
    modules = name + ".perceptual_grade_next_blender."
    native_grade = importlib.import_module(modules + "native_grade")
    controls = importlib.import_module(modules + "controls")
    updates = importlib.import_module(modules + "updates")
    bake_operators = importlib.import_module(modules + "bake_operators")
    read_image_rgba = importlib.import_module(modules + "native_bake").read_image_rgba

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    source_pixels = np.asarray(
        [[(0.05, 0.10, 0.20, 0.25), (0.40, 0.50, 0.60, 0.75)]],
        dtype=np.float32,
    )
    source = bpy.data.images.new(
        "Installed Next Bake Source", 2, 1, alpha=True, float_buffer=True,
    )
    source.use_half_precision = False
    source.colorspace_settings.name = "Non-Color"
    source.pixels.foreach_set(source_pixels.reshape(-1))
    source.update()
    target = bpy.data.images.new(
        "Installed Next Bake Target", 2, 1, alpha=True, float_buffer=True,
    )
    target.use_half_precision = False
    target.colorspace_settings.name = "Non-Color"
    prior = np.full((1, 2, 4), 7.0, dtype=np.float32)
    target.pixels.foreach_set(prior.reshape(-1))
    target.update()

    native = native_grade.build_native_grade(name="Installed Next Bake Grade")
    host = bpy.data.node_groups.new("Installed Next Bake Owner", "ShaderNodeTree")
    for name_value, direction, socket_type in (
            ("Color", "INPUT", "NodeSocketColor"),
            ("Alpha", "INPUT", "NodeSocketFloat"),
            ("Color", "OUTPUT", "NodeSocketColor"),
            ("Alpha", "OUTPUT", "NodeSocketFloat")):
        host.interface.new_socket(
            name=name_value, in_out=direction, socket_type=socket_type,
        )
    texture = host.nodes.new("ShaderNodeTexImage")
    texture.image = source
    texture.interpolation = "Closest"
    node = host.nodes.new("ShaderNodeGroup")
    node.node_tree = native.tree
    output = host.nodes.new("NodeGroupOutput")
    host.links.new(texture.outputs["Color"], node.inputs["Color"])
    host.links.new(texture.outputs["Alpha"], node.inputs["Alpha"])
    host.links.new(node.outputs["Color"], output.inputs["Color"])
    host.links.new(node.outputs["Alpha"], output.inputs["Alpha"])
    node["perceptual_grade_next_backend"] = "native_grade_graph"
    node["perceptual_grade_next_schema"] = 1
    node["perceptual_grade_next_settings"] = native.tree[
        "perceptual_grade_next_settings"
    ]
    node["perceptual_grade_next_edit_revision"] = 0
    node["perceptual_grade_next_applied_revision"] = 0
    node["perceptual_grade_next_preparation_state"] = "READY"
    node["perceptual_grade_next_preparation_error"] = ""
    controls.attach_controls(node, native.settings)
    readiness = importlib.import_module(
        name + ".perceptual_grade_next_blender.project_readiness"
    )
    readiness.accept_grade_manifest(node, native)
    updates.register_native_owner(node, native, "grade")
    # Keep the authored owner in a user material and scene object, like a real
    # Shader workflow, so the test has no fake-user persistence assumption.
    material = bpy.data.materials.new("Installed Next Bake Material")
    material.use_nodes = True
    material_group = material.node_tree.nodes.new("ShaderNodeGroup")
    material_group.node_tree = host
    principled = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(
        material_group.outputs["Color"], principled.inputs["Base Color"],
    )
    mesh = bpy.data.meshes.new("Installed Next Bake Mesh")
    mesh.from_pydata(
        ((-1, -1, 0), (0, -1, 0), (0, 1, 0), (-1, 1, 0),
         (0, -1, 0), (1, -1, 0), (1, 1, 0), (0, 1, 0)), (),
        ((0, 1, 2, 3), (4, 5, 6, 7)),
    )
    uv = mesh.uv_layers.new(name="Bake UV")
    for item, value in zip(uv.data, (
            (0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0),
            (0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0))):
        item.uv = value
    unrelated_material = bpy.data.materials.new("Installed Next Unrelated Material")
    unrelated_material.use_nodes = True
    unrelated_emission = unrelated_material.node_tree.nodes.new("ShaderNodeEmission")
    unrelated_emission.inputs["Color"].default_value = (1.0, 0.2, 0.1, 1.0)
    data_material = bpy.data.materials.new("Installed Next Data Material")
    data_material.use_nodes = True
    data_material.node_tree.nodes.new("ShaderNodeEmission")
    mesh.polygons[0].material_index = 1
    obj = bpy.data.objects.new("Installed Next Bake Object", mesh)
    scene.collection.objects.link(obj)
    obj.data.materials.append(data_material)
    obj.data.materials.append(material)
    obj.material_slots[0].link = "OBJECT"
    obj.material_slots[0].material = unrelated_material
    mesh.polygons[1].material_index = 0

    context = SimpleNamespace(
        space_data=SimpleNamespace(edit_tree=host),
        active_node=node,
        scene=scene,
        active_object=obj,
        view_layer=bpy.context.view_layer,
        screen=bpy.context.screen,
        selected_objects=bpy.context.selected_objects,
        evaluated_depsgraph_get=bpy.context.evaluated_depsgraph_get,
    )
    operator = SimpleNamespace(target_image=target, domain="IMAGE")
    result = bake_operators._run_bake(context, operator)
    pixels = read_image_rgba(result)
    if result is not target:
        raise RuntimeError("Bake did not publish to the selected target Image")
    if not np.isfinite(pixels).all():
        raise RuntimeError("Native Bake published non-finite pixels")
    if np.array_equal(pixels, prior):
        raise RuntimeError("Native Bake did not replace the target pixels")
    if not np.allclose(pixels[..., 3], source_pixels[..., 3], atol=1e-4, rtol=0):
        raise RuntimeError(
            "Native Grade Bake alpha mismatch: source=%r published=%r"
            % (source_pixels[..., 3].tolist(), pixels[..., 3].tolist())
        )
    if target.get("perceptual_grade_next_bake_active_backup"):
        raise RuntimeError("Image publication recovery backing was not retired")
    uv_target = bpy.data.images.new(
        "Installed Next UV Bake Target", 4, 4, alpha=True, float_buffer=True,
    )
    uv_target.use_half_precision = False
    uv_target.colorspace_settings.name = "Non-Color"
    uv_prior = np.full((4, 4, 4), 5.0, dtype=np.float32)
    uv_target.pixels.foreach_set(uv_prior.reshape(-1))
    uv_target.update()
    original_material = obj.data.materials[1]
    original_mesh = obj.data
    operator_result, operator_reports = _execute_registered_bake(
        bake_operators, context, target=uv_target, domain="UV",
    )
    if operator_result != {"FINISHED"} or operator_reports:
        raise RuntimeError(
            "Registered UV Bake operator did not finish: %r %r"
            % (operator_result, operator_reports)
        )
    uv_result = uv_target
    uv_pixels = read_image_rgba(uv_result)
    covered = int(np.count_nonzero(uv_pixels[..., 3] > 0.0))
    uncovered = int(np.count_nonzero(uv_pixels[..., 3] == 0.0))
    non_owner_covered = int(np.count_nonzero(uv_pixels[:, :2, 3] > 0.0))
    if uv_result is not uv_target or uv_pixels.shape != (4, 4, 4):
        raise RuntimeError("UV Bake did not publish the selected target dimensions")
    if not np.isfinite(uv_pixels).all() or np.array_equal(uv_pixels, uv_prior):
        raise RuntimeError("Native UV Bake did not replace the target pixels")
    if covered == 0 or uncovered == 0:
        raise RuntimeError("UV Bake did not preserve native island coverage")
    if non_owner_covered:
        raise RuntimeError("UV Bake included faces without the selected Grade material")
    covered_red = uv_pixels[..., 0][uv_pixels[..., 3] > 0.0]
    if float(covered_red.max()) >= 0.1:
        raise RuntimeError(
            "UV Bake sampled source by destination UV instead of Generated: %r"
            % float(covered_red.max())
        )
    if obj.data is not original_mesh or obj.data.materials[1] is not original_material:
        raise RuntimeError("UV Bake mutated the original mesh or material assignment")
    if (len(obj.material_slots) != 2
            or obj.material_slots[0].link != "OBJECT"
            or obj.material_slots[0].material is not unrelated_material
            or obj.data.materials[0] is not data_material):
        raise RuntimeError("UV Bake changed the original material slots")
    if uv_target.get("perceptual_grade_next_bake_active_backup"):
        raise RuntimeError("UV Image publication recovery backing was not retired")

    preflight_targets = {
        int(image.as_pointer()) for image in bpy.data.images
    }
    with patch.object(
            bake_operators, "route_facts",
            side_effect=RuntimeError("installed route preflight fault")):
        preflight_result, preflight_reports = _execute_registered_bake(
            bake_operators, context, target="", domain="IMAGE",
        )
    preflight_orphans = tuple(
        image.name for image in bpy.data.images
        if image.name.startswith("PG Next Bake Result")
        and int(image.as_pointer()) not in preflight_targets
    )
    if (preflight_result != {"CANCELLED"} or not preflight_reports
            or preflight_orphans):
        raise RuntimeError(
            "Route-preflight failure left an auto-created Bake Image: result=%r "
            "reports=%r orphans=%r" % (
                preflight_result, preflight_reports, preflight_orphans,
            )
        )

    admitted_targets = {
        int(image.as_pointer()) for image in bpy.data.images
    }
    with patch.object(
            bake_operators.OutputGateway, "freeze_bake_source",
            side_effect=RuntimeError("installed admitted Bake fault")):
        admitted_result, admitted_reports = _execute_registered_bake(
            bake_operators, context, target="", domain="IMAGE",
        )
    admitted_orphans = tuple(
        image.name for image in bpy.data.images
        if image.name.startswith("PG Next Bake Result")
        and int(image.as_pointer()) not in admitted_targets
    )
    if (admitted_result != {"CANCELLED"} or not admitted_reports
            or admitted_orphans
            or bake_operators._GATEWAY.state.bake_phase != "cancelled"):
        raise RuntimeError(
            "Admitted Bake failure left an auto-created Image or live request: "
            "result=%r reports=%r orphans=%r phase=%r" % (
                admitted_result, admitted_reports, admitted_orphans,
                bake_operators._GATEWAY.state.bake_phase,
            )
        )

    selected_target_before_failure = read_image_rgba(target).copy()
    with patch.object(
            bake_operators.OutputGateway, "freeze_bake_source",
            side_effect=RuntimeError("installed selected-target Bake fault")):
        selected_result, selected_reports = _execute_registered_bake(
            bake_operators, context, target=target, domain="IMAGE",
        )
    if (selected_result != {"CANCELLED"} or not selected_reports
            or bpy.data.images.get(target.name) is not target
            or not np.array_equal(read_image_rgba(target), selected_target_before_failure)):
        raise RuntimeError("Failed Bake changed or removed the user-selected Image")
    data = {
        "passed": True,
        "blender": list(bpy.app.version),
        "extension_origin": str(Path(addon.__file__).resolve()),
        "evaluator": "native_grade_graph",
        "published_rgba_shape": list(pixels.shape),
        "pixels_changed": True,
        "alpha_preserved": True,
        "publication_recovery_cleared": True,
        "published_min": float(pixels.min()),
        "published_max": float(pixels.max()),
        "uv_evaluator": "native_grade_graph",
        "uv_published_rgba_shape": list(uv_pixels.shape),
        "uv_covered_pixels": covered,
        "uv_uncovered_pixels": uncovered,
        "uv_non_owner_covered_pixels": non_owner_covered,
        "uv_source_unchanged": obj.data is original_mesh,
        "uv_material_unchanged": obj.data.materials[1] is original_material,
        "uv_registered_operator_finished": operator_result == {"FINISHED"},
        "preflight_failure_cancelled": preflight_result == {"CANCELLED"},
        "preflight_failure_orphans": list(preflight_orphans),
        "admitted_failure_cancelled": admitted_result == {"CANCELLED"},
        "admitted_failure_orphans": list(admitted_orphans),
        "admitted_failure_phase": bake_operators._GATEWAY.state.bake_phase,
        "selected_failure_preserved_target": (
            selected_result == {"CANCELLED"}
            and bpy.data.images.get(target.name) is target
            and np.array_equal(read_image_rgba(target), selected_target_before_failure)
        ),
    }
    Path(report_path).write_text(json.dumps(data, sort_keys=True), encoding="utf8")


if __name__ == "__main__":
    main(*sys.argv[sys.argv.index("--") + 1:])
