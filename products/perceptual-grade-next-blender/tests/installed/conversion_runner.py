"""Run Grade ownership conversion checks in an installed Blender process."""

import addon_utils
import importlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import bpy


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade conversion test",
    module="pg_grade_conversion",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_grade_conversion.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append,
) is extension
assert not errors, errors
nodes._startup_reconcile_tick()


def assert_grade_current(node):
    failures = nodes._drain_preparations()
    assert not failures, failures
    state = nodes._node_stores[node.as_pointer()]["state"]
    details = (node.name, node.get(nodes._NODE_ERROR), state)
    assert not node.get(nodes._NODE_ERROR), details
    assert not node.get(nodes._NODE_PENDING), details
    signature = nodes._kernel_signature(
        node.id_data.bl_idname, nodes._settings_for_node(node), nodes._working_space(),
    )
    assert state.desired_signature == signature, details
    assert state.applied_signature == signature, details
    assert nodes.node_policy.output_allowed(state), details
    assert nodes._kernel_is_current(
        node.node_tree, node.id_data.bl_idname, signature, stack=False,
    ), details


mesh = bpy.data.meshes.new("Grade conversion test mesh")
mesh.from_pydata(((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), (), ((0, 1, 2, 3),))
mesh.update()
obj = bpy.data.objects.new("Grade conversion test object", mesh)
bpy.context.scene.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

conversion_checks = runpy.run_path(str(Path(__file__).with_name("conversion_checks.py")))
conversion_checks["run"](nodes, assert_grade_current)
nodes._drain_preparations()
extension.unregister()
report_path.write_text(json.dumps({"passed": True}))
