"""Initialize and populate Stacks using the installed extension's GPU helper."""

import importlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import addon_utils
import bpy


repository, report = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.system.gpu_backend = (
    "METAL" if sys.platform == "darwin" else "OPENGL"
)
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade Stack helper test",
    module="pg_stack_helper",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_stack_helper.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_stack_helper.perceptual_grade.features.grade.host")
errors = []
enabled = addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append,
)
assert enabled is extension, errors
assert not errors, errors


def settle(node):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        nodes._preparation_tick()
        state = nodes._record_for(node)["state"]
        assert state.error is None, state.error
        if nodes.node_policy.output_allowed(state):
            assert state.applied_quality == "full"
            assert nodes._kernel_is_current(
                node.node_tree, node.id_data.bl_idname,
                state.desired_signature, "full", stack=True,
            )
            assert node.node_tree.get("_perceptual_grade_stack_kernel")
            assert not node.get(nodes._NODE_ERROR)
            return
        time.sleep(0.005)
    raise TimeoutError("Stack GPU helper did not produce a current result")


def assert_clean_stack_images():
    images = [image for image in bpy.data.images
              if image.get("_perceptual_grade_stack_image")]
    assert images, "Stack LUT image was not installed"
    for image in images:
        assert image.packed_file is not None, image.name
        assert not image.is_dirty, image.name


contexts = []
runtime = None
try:
    # Exercise the Shader Editor's embedded material tree first, before any
    # standalone tree or populated Stack can warm the helper or resource cache.
    material = bpy.data.materials.new("First Stack Material")
    material.use_nodes = True
    compositor_tree = bpy.data.node_groups.new("First Compositor Stack", nodes.COMPOSITOR_TREE)
    for tree in (material.node_tree, compositor_tree):
        context = SimpleNamespace(space_data=SimpleNamespace(
            edit_tree=tree, cursor_location=(0.0, 0.0)))
        assert nodes.PG_OT_add_stack.execute(None, context) == {"FINISHED"}
        node = tree.nodes.active
        assert not node.pg_stack_entries
        settle(node)
        assert_clean_stack_images()

        stack_context = SimpleNamespace(pg_stack_node=node)
        assert nodes.PG_OT_stack_action.execute(
            SimpleNamespace(action="ADD"), stack_context) == {"FINISHED"}
        assert nodes.PG_OT_new_stack_grade.execute(
            SimpleNamespace(index=0), stack_context) == {"FINISHED"}
        assert node.pg_stack_entries[0].grade is not None
        settle(node)
        assert_clean_stack_images()

        # A second calculation must reuse the live helper and regenerate its
        # receipt from the changed settings, including the Tone path.
        node.pg_stack_entries[0].grade.pg_tone.fit = 0.25
        settle(node)
        assert_clean_stack_images()
        contexts.append(tree.bl_idname)

    backend = nodes._preparation_runtime._lanes["lut"].host_owner
    assert isinstance(backend, nodes.StackHelperBackend)
    runtime = backend.runtime
    assert runtime.gpu_ready
    assert runtime._process.pid != os.getpid()
    assert runtime._process.poll() is None
    assert backend.probe.result()["conformance"] is True

    preparation_runtime = nodes._preparation_runtime
    error = RuntimeError("Injected Stack helper shutdown failure")
    failed_disable = []
    with patch.object(backend, "close", side_effect=error) as close:
        addon_utils.disable(extension.__name__, default_set=False,
                            handle_error=failed_disable.append)
        close.assert_called_once_with()
    assert len(failed_disable) == 1
    assert failed_disable[0].exceptions == (error,)
    assert nodes._preparation_runtime is preparation_runtime
    assert preparation_runtime._lanes["lut"].host_owner is backend
    assert not runtime.physical_terminal()
    assert nodes.PGShaderGrade.is_registered
    assert nodes._load_post in bpy.app.handlers.load_post
    assert nodes._preparation_tick() is None

    enabled = addon_utils.enable(
        extension.__name__, default_set=False, handle_error=errors.append,
    )
    assert enabled is extension, errors
    assert not errors, errors
    assert runtime.physical_terminal()
    assert nodes._preparation_runtime is not preparation_runtime
    assert nodes._preparation_runtime._lanes["lut"].host_owner is not backend
    assert nodes.PGShaderGrade.is_registered
finally:
    addon_utils.disable(extension.__name__, default_set=False, handle_error=errors.append)
assert not errors, errors
assert runtime is not None and runtime.physical_terminal()
assert nodes._preparation_runtime is None
report.write_text(json.dumps({
    "passed": True,
    "contexts": contexts,
    "helper_retired": True,
}))
