"""Exercise the installed publication comparison nodes in native Blender."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Publication Compare test", module="pg_publication_compare",
    custom_directory=str(repository),
)
extension = importlib.import_module(
    "bl_ext.pg_publication_compare.grade_publication_compare"
)
errors = []
enabled = addon_utils.enable(extension.__name__, default_set=False,
                             handle_error=errors.append)
assert not errors, errors
assert enabled is extension, enabled
nodes = importlib.import_module(extension.__name__ + ".nodes")

cases = (
    ("ShaderNodeTree", "PGDemoShaderVersioned", "versioned"),
    ("CompositorNodeTree", "PGDemoCompositorVersioned", "versioned"),
    ("ShaderNodeTree", "PGDemoShaderOriginal", "original"),
    ("CompositorNodeTree", "PGDemoCompositorOriginal", "original"),
    ("ShaderNodeTree", "PGDemoShaderBanked", "banked"),
    ("CompositorNodeTree", "PGDemoCompositorBanked", "banked"),
)
rows = []
for index, (tree_type, node_type, variant) in enumerate(cases):
    outer = bpy.data.node_groups.new("Compare outer " + str(index), tree_type)
    node = outer.nodes.new(node_type)
    kernel = node.node_tree
    assert kernel is not None
    expected_sockets = ["Color", "Alpha"] if tree_type == "ShaderNodeTree" else ["Color"]
    assert [socket.name for socket in node.inputs] == expected_sockets
    assert [socket.name for socket in node.outputs] == expected_sockets
    assert [socket.name for socket in kernel.interface.items_tree
            if getattr(socket, "in_out", None) == "INPUT"] == expected_sockets
    assert [socket.name for socket in kernel.interface.items_tree
            if getattr(socket, "in_out", None) == "OUTPUT"] == expected_sockets
    assert kernel.get("_pg_publication_variant") == variant
    assert any(item.get(nodes._READER) for item in kernel.nodes)
    assert any(item.get(nodes._ERROR_READER) for item in kernel.nodes)
    assert any(item.bl_idname in {
        "ShaderNodeSeparateColor", "CompositorNodeSeparateColor",
    } for item in kernel.nodes)
    input_split = next(
        item for item in kernel.nodes
        if item.bl_idname == ("ShaderNodeSeparateColor" if tree_type == "ShaderNodeTree"
                              else "CompositorNodeSeparateColor")
        and any(link.from_node.bl_idname == "NodeGroupInput" for link in kernel.links
                if link.to_node == item)
    )
    readers = [item for item in kernel.nodes if item.get(nodes._READER)]
    reader = nodes._helper_reader(kernel)
    if variant == "banked":
        assert len(readers) == 2
        assert {item.get(nodes._BANK_INDEX) for item in readers} == {0, 1}
        assert len({item.image.as_pointer() for item in readers}) == 2
    else:
        assert len(readers) == 1
    if tree_type == "ShaderNodeTree":
        helper_splits = [item for item in kernel.nodes
                         if item.bl_idname == "ShaderNodeSeparateColor"
                         and any(link.from_node in readers and link.to_node == item
                                 for link in kernel.links)]
        assert len(helper_splits) == len(readers)
        multipliers = [item for item in kernel.nodes
                       if item.bl_idname == "ShaderNodeMath"
                       and item.operation == "MULTIPLY"]
        factors = [item for item in kernel.nodes
                   if item.bl_idname == "ShaderNodeMath" and item.operation == "POWER"]
        assert len(factors) == len(readers)
        for helper_split, factor in zip(helper_splits, factors):
            assert any(link.from_node == helper_split and link.from_socket.name == "Red"
                       and link.to_node == factor for link in kernel.links)
        for name in ("Red", "Green", "Blue"):
            assert any(link.from_node == input_split and link.from_socket.name == name
                       and link.to_node in multipliers for link in kernel.links)
            assert len([link for link in kernel.links
                        if link.from_node in factors and link.to_node in multipliers]) == 3 * len(readers)
        if variant == "banked":
            selector = next(item for item in kernel.nodes if item.get(nodes._BANK_SELECTOR))
            selection = next(item for item in kernel.nodes
                             if item.bl_idname == "ShaderNodeMixRGB"
                             and any(link.from_node == selector and link.to_node == item
                                     for link in kernel.links))
            assert selection.inputs[1].is_linked and selection.inputs[2].is_linked
            assert sum(link.from_node in readers and link.to_node in helper_splits
                       for link in kernel.links) == 2
            error_gate = next(item for item in kernel.nodes
                              if item.get(nodes._ERROR_READER))
            error_mix = next(item for item in kernel.nodes
                             if item.bl_idname == "ShaderNodeMixRGB"
                             and any(link.from_node == error_gate and link.to_node == item
                                     for link in kernel.links))
            assert any(link.from_node == selection and link.to_node == error_mix
                       and link.to_socket == error_mix.inputs[1]
                       for link in kernel.links)
    else:
        group_input = next(item for item in kernel.nodes
                           if item.bl_idname == "NodeGroupInput")
        samples = [item for item in kernel.nodes if item.bl_idname == "CompositorNodeMapUV"]
        exposure_values = [item for item in kernel.nodes
                           if item.bl_idname == "CompositorNodeRGBToBW"
                           and any(link.from_node in samples for link in kernel.links
                                   if link.to_node == item)]
        exposure = next(item for item in kernel.nodes
                        if item.bl_idname == "CompositorNodeExposure")
        assert len(samples) == len(exposure_values) == 1
        for sample in samples:
            assert tuple(sample.inputs["UV"].default_value) == (0.5, 0.5, 1.0)
        if variant == "banked":
            selector = next(item for item in kernel.nodes if item.get(nodes._BANK_SELECTOR))
            assert selector.bl_idname == "CompositorNodeSwitch"
            assert selector.inputs["Switch"].default_value is False
            assert all(any(link.from_node == source_reader and link.to_node == selector
                           and link.to_socket == selector.inputs[port]
                           for link in kernel.links)
                       for source_reader, port in zip(readers, ("Off", "On")))
            assert any(link.from_node == selector and link.to_node == samples[0]
                       for link in kernel.links)
        else:
            assert any(link.from_node == readers[0] and link.to_node == samples[0]
                       for link in kernel.links)
        assert all(any(link.from_node == sample and link.to_node == value
                        for link in kernel.links)
                   for sample, value in zip(samples, exposure_values))
        assert any(link.from_node == group_input
                   and link.to_socket == exposure.inputs["Image"]
                   for link in kernel.links)
        assert any(link.from_node == exposure_values[0]
                   and link.to_socket == exposure.inputs["Exposure"]
                   for link in kernel.links)

    settings = kernel.pg_publication
    old_image = nodes._helper_image(kernel)
    old_pixels = tuple(float(value) for value in old_image.pixels[:])
    old_pointer = old_image.as_pointer()
    old_bank = nodes._active_bank(kernel)
    reader_bindings = tuple((item.as_pointer(), item.image.as_pointer()) for item in readers)
    if variant == "versioned":
        old_image.use_fake_user = True
    settings.exposure = 1.0
    new_image = nodes._helper_image(kernel)
    assert new_image is not None
    assert abs(float(new_image.pixels[0]) - 1.0) < 1e-6
    assert abs(float(new_image.pixels[3]) - 1.0) < 1e-6
    image_replaced = new_image.as_pointer() != old_pointer
    if variant == "versioned":
        assert new_image.as_pointer() != old_pointer
        assert tuple(float(value) for value in old_image.pixels[:]) == old_pixels
        old_image.use_fake_user = False
    elif variant == "original":
        assert new_image.as_pointer() == old_pointer
        assert tuple(float(value) for value in old_image.pixels[:]) != old_pixels
    else:
        assert nodes._active_bank(kernel) != old_bank
        assert new_image.as_pointer() != old_pointer
        assert tuple((item.as_pointer(), item.image.as_pointer()) for item in readers) == reader_bindings
        assert tuple(float(value) for value in old_image.pixels[:]) == old_pixels
    assert not kernel.get("_pg_publication_error")
    assert kernel.as_pointer() not in nodes._pending
    output = next(item for item in kernel.nodes if item.bl_idname == "NodeGroupOutput")
    assert output.inputs["Color"].is_linked
    assert any(link.from_node.get(nodes._READER) for link in kernel.links)
    if tree_type == "ShaderNodeTree":
        assert any(link.from_socket == next(
            item for item in kernel.nodes if item.bl_idname == "NodeGroupInput"
        ).outputs["Alpha"] and link.to_socket == output.inputs["Alpha"]
                   for link in kernel.links)

    stable_image = nodes._helper_image(kernel)
    stable_pixels = tuple(float(value) for value in stable_image.pixels[:])
    stable_signature = float(kernel.get(nodes._SIGNATURE))
    stable_image_signature = float(stable_image.get(nodes._SIGNATURE))
    original_write = nodes._write_helper

    def fail_after_partial_write(image, _exposure):
        image.pixels.foreach_set((7.0, 7.0, 7.0, 0.25))
        image.update()
        raise RuntimeError("injected helper upload failure")

    nodes._write_helper = fail_after_partial_write
    settings.exposure = 2.0
    nodes._write_helper = original_write
    assert kernel.get("_pg_publication_error")
    error_gate = next(item for item in kernel.nodes if item.get(nodes._ERROR_READER))
    if tree_type == "CompositorNodeTree":
        assert tuple(error_gate.outputs[0].default_value) == (1.0, 1.0, 1.0, 1.0)
    else:
        assert error_gate.outputs[0].default_value == 1.0
    assert nodes._helper_image(kernel).as_pointer() == stable_image.as_pointer()
    if variant == "original":
        assert tuple(float(value) for value in stable_image.pixels[:]) == stable_pixels
        assert float(kernel.get(nodes._SIGNATURE)) == stable_signature
        assert float(stable_image.get(nodes._SIGNATURE)) == stable_image_signature
    else:
        assert tuple(float(value) for value in stable_image.pixels[:]) == stable_pixels
    settings.exposure = 1.0
    assert not kernel.get("_pg_publication_error")
    assert nodes._helper_image(kernel) is not None
    if variant == "banked":
        rollback_bank = nodes._active_bank(kernel)
        rollback_image = nodes._helper_image(kernel)
        rollback_pixels = tuple(float(value) for value in rollback_image.pixels[:])
        original_set_bank = nodes._set_active_bank

        def fail_after_selector_change(tree, bank):
            original_set_bank(tree, bank)
            if tree == kernel and bank != rollback_bank:
                raise RuntimeError("injected selector receipt failure")

        nodes._set_active_bank = fail_after_selector_change
        settings.exposure = 2.0
        nodes._set_active_bank = original_set_bank
        assert kernel.get("_pg_publication_error")
        assert nodes._active_bank(kernel) == rollback_bank
        assert nodes._helper_image(kernel).as_pointer() == rollback_image.as_pointer()
        assert tuple(float(value) for value in rollback_image.pixels[:]) == rollback_pixels
        settings.exposure = 1.0
        assert not kernel.get("_pg_publication_error")

    row = {"tree_type": tree_type, "node_type": node_type,
           "variant": variant, "image_replaced": image_replaced,
           "multiplier": 2.0 ** float(nodes._helper_image(kernel).pixels[0]),
           "reader_bindings_stable": tuple(
               (item.as_pointer(), item.image.as_pointer()) for item in readers
           ) == reader_bindings}
    if tree_type == "CompositorNodeTree":
        alpha_restore = next(
            item for item in kernel.nodes if item.bl_idname == "CompositorNodeSetAlpha"
        )
        alpha_split = next(
            link.from_node for link in kernel.links
            if link.to_node == alpha_restore and link.to_socket == alpha_restore.inputs["Alpha"]
        )
        assert alpha_split.bl_idname == "CompositorNodeSeparateColor"
        assert any(link.from_node.bl_idname == "NodeGroupInput"
                   and link.to_node == alpha_split
                   for link in kernel.links)
        assert any(link.from_node == alpha_restore
                   and link.to_node == output for link in kernel.links)
        assert any(link.from_node.get(nodes._ERROR_READER)
                   and link.to_node.bl_idname == "CompositorNodeRGBToBW"
                   for link in kernel.links)
        outer.interface.new_socket(name="Image", in_out="OUTPUT",
                                   socket_type="NodeSocketColor")
        group_output = outer.nodes.new("NodeGroupOutput")
        source = outer.nodes.new("CompositorNodeRGB")
        source.outputs[0].default_value = (0.125, 0.25, 0.375, 0.625)
        viewer = outer.nodes.new("CompositorNodeViewer")
        outer.links.new(source.outputs[0], node.inputs["Color"])
        outer.links.new(node.outputs["Color"], viewer.inputs["Image"])
        outer.links.new(node.outputs["Color"], group_output.inputs["Image"])
        scene = bpy.context.scene
        scene.render.use_compositing = True
        scene.render.compositor_device = "CPU"
        scene.render.resolution_x = 16
        scene.render.resolution_y = 16
        scene.render.resolution_percentage = 100
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        scene.compositing_node_group = outer
        area = next((item for item in bpy.context.screen.areas if item.type == "VIEW_3D"),
                    next(iter(bpy.context.screen.areas), None))
        assert area is not None, "Blender did not create a window area for compositor evaluation"
        area.type = "NODE_EDITOR"
        area.ui_type = "CompositorNodeTree"
        area.spaces.active.show_backdrop = False

        def wait_compositor_idle():
            deadline = time.monotonic() + 30.0
            while bpy.app.is_job_running("COMPOSITE"):
                assert time.monotonic() < deadline, "Compositor did not become idle"
                time.sleep(0.01)
            if nodes._gate.current_compositor() is not None:
                nodes._compositor_finished(scene, True)

        def viewer_pixel():
            outer.update_tag()
            scene.compositing_node_group.update_tag()
            scene.update_tag()
            bpy.ops.render.render("EXEC_DEFAULT", write_still=False)
            wait_compositor_idle()
            images = [image for image in bpy.data.images
                      if image.type == "COMPOSITING" and image.has_data]
            assert images and tuple(images[0].size) == (16, 16)
            return tuple(float(value) for value in images[-1].pixels[:4])

        wait_compositor_idle()
        settings.exposure = 0.0
        baseline = viewer_pixel()
        settings.exposure = 1.0
        final = viewer_pixel()
        assert max(abs(value - expected) for value, expected in zip(
            baseline, (0.125, 0.25, 0.375, 0.625)
        )) < 1e-4, (baseline, kernel.get("_pg_publication_error"),
                     tuple(nodes._helper_image(kernel).pixels[:]),
                     float(kernel.get(nodes._SIGNATURE)), kernel.as_pointer() in nodes._pending)
        assert max(abs(value - expected) for value, expected in zip(
            final, (0.25, 0.5, 0.75, 0.625)
        )) < 1e-4, (final, kernel.get("_pg_publication_error"),
                     tuple(nodes._helper_image(kernel).pixels[:]),
                     float(kernel.get(nodes._SIGNATURE)), kernel.as_pointer() in nodes._pending,
                     [(image.name, tuple(image.pixels[:4])) for image in bpy.data.images
                      if image.type == "COMPOSITING" and image.has_data])
        row["baseline_output"] = baseline
        row["final_output"] = final
    rows.append(row)

extension.unregister()
report_path.write_text(json.dumps({"passed": True, "rows": rows}, indent=2))
bpy.ops.wm.quit_blender()
