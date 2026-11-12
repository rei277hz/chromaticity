"""Exercise the installed extension package in native Blender."""

import atexit
import importlib
import json
from pathlib import Path
import runpy
import sys
import threading
import tempfile
import time
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np
import _bpy_restrict_state as restricted


repository, report = map(Path, sys.argv[sys.argv.index("--") + 1:])
_RUNNER_STARTED = time.perf_counter()
_TIMING_SECTIONS = []
_CURRENT_SECTION = "extension startup"
_CURRENT_SECTION_STARTED = _RUNNER_STARTED
_RUNNER_COMPLETED = False


def _write_timing_report():
    now = time.perf_counter()
    sections = list(_TIMING_SECTIONS)
    if _CURRENT_SECTION is not None:
        sections.append({
            "name": _CURRENT_SECTION,
            "seconds": round(now - _CURRENT_SECTION_STARTED, 6),
        })
    nodes_module = globals().get("nodes")
    node_type = getattr(nodes_module, "PGShaderGrade", None)
    report.write_text(json.dumps({
        "registered": bool(getattr(node_type, "is_registered", False)),
        "blender": list(bpy.app.version),
        "timings": {
            "unit": "seconds",
            "runner_seconds": round(now - _RUNNER_STARTED, 6),
            "sections": sections,
            "complete": _RUNNER_COMPLETED,
        },
    }))


def _start_timing_section(name):
    global _CURRENT_SECTION, _CURRENT_SECTION_STARTED
    now = time.perf_counter()
    _TIMING_SECTIONS.append({
        "name": _CURRENT_SECTION,
        "seconds": round(now - _CURRENT_SECTION_STARTED, 6),
    })
    _CURRENT_SECTION = name
    _CURRENT_SECTION_STARTED = now
    _write_timing_report()


def _complete_timing_report():
    global _CURRENT_SECTION, _RUNNER_COMPLETED
    if _CURRENT_SECTION is not None:
        now = time.perf_counter()
        _TIMING_SECTIONS.append({
            "name": _CURRENT_SECTION,
            "seconds": round(now - _CURRENT_SECTION_STARTED, 6),
        })
        _CURRENT_SECTION = None
    _RUNNER_COMPLETED = True
    _write_timing_report()


def _write_incomplete_timing_report():
    if not _RUNNER_COMPLETED:
        _write_timing_report()


atexit.register(_write_incomplete_timing_report)
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade smoke test",
    module="pg_grade_smoke",
    custom_directory=str(repository),
)

extension = importlib.import_module("bl_ext.pg_grade_smoke.perceptual_grade")
nodes = importlib.import_module(
    "bl_ext.pg_grade_smoke.perceptual_grade.nodes"
)
node_library = importlib.import_module(
    "bl_ext.pg_grade_smoke.perceptual_grade.kernel"
)
lut_kernel = importlib.import_module(
    "bl_ext.pg_grade_smoke.perceptual_grade.kernel.lut"
)
initial_scans = []
original_ensure_all_kernels = nodes._ensure_all_kernels


def track_initial_scan(*args, **kwargs):
    assert type(bpy.data).__name__ != "_RestrictData"
    initial_scans.append(None)
    return original_ensure_all_kernels(*args, **kwargs)


nodes._ensure_all_kernels = track_initial_scan
enable_errors = []
enabled_extension = addon_utils.enable(
    extension.__name__, default_set=False, handle_error=enable_errors.append
)
assert enabled_extension is extension and not enable_errors, enable_errors
assert not initial_scans
assert bpy.app.timers.is_registered(nodes._startup_reconcile_tick)
localization = nodes.localization
assert localization._registered
assert localization.resolve_locale("zh_CN") == "zh_HANS"
assert localization.resolve_locale("fr_FR") == "en"
assert localization.tr("node.grade.title", locale="zh_CN") == "调色"
assert localization.host_messages("zh_CN")[(localization.CONTEXT, "Grade")] == "调色"
assert localization.host_messages("zh_CN")[("*", "Color")] == "颜色"
assert localization.host_messages("zh_CN")[("*", "Alpha")] == "Alpha"
with restricted.RestrictBlend():
    assert type(bpy.data).__name__ == "_RestrictData"
    assert nodes._startup_reconcile_tick() == 0.1
assert not initial_scans


def reconcile_for_render(scene):
    """Exercise the complete native render lifecycle around the preflight."""
    nodes._render_init(scene)
    try:
        nodes._render_pre(scene)
    finally:
        nodes._render_finished(scene)


def assert_menu_item(tree):
    class Layout:
        def __init__(self):
            self.items = []

        def separator(self):
            self.items.append(("separator",))

        def operator(self, operator_id, **kwargs):
            self.items.append((operator_id, kwargs))

    layout = Layout()
    nodes.draw_add_menu(SimpleNamespace(layout=layout),
                        SimpleNamespace(space_data=SimpleNamespace(edit_tree=tree)))
    assert (nodes.PG_OT_add_grade.bl_idname,
            {"text": "Grade", "icon": "COLOR"}) in layout.items
    assert (nodes.PG_OT_add_per_node_grade.bl_idname,
            {"text": "Per-Node Grade", "icon": "ANIM_DATA"}) in layout.items
    assert (nodes.PG_OT_add_stack.bl_idname,
            {"text": "Grade Stack", "icon": "NODETREE"}) in layout.items


def assert_not_animatable(owner, data_path):
    try:
        inserted = owner.keyframe_insert(data_path=data_path, frame=1)
    except TypeError as error:
        assert "not animatable" in str(error), error
    else:
        assert not inserted, (owner, data_path)


def check_per_node_properties(node):
    tree = node.id_data
    node.name = 'Per-Node "Grade" \\ controls'
    assert all(name not in node.bl_rna.properties
               for name in ("pg_grade", "pg_linear", "pg_tone"))
    assert nodes._holder(node) == node
    for field in (*nodes._LINEAR_FIELDS, *nodes._ANIMATABLE_TONE_FIELDS):
        value = getattr(node, field)
        path = node.path_from_id(field)
        assert path == node.path_from_id() + "." + field
        assert tree.path_resolve(path) == value
        assert node.bl_rna.properties[field].is_animatable
        assert node.keyframe_insert(data_path=field, frame=5.25)
        animation_data = tree.animation_data
        strip = animation_data.action.layers[0].strips[0]
        curve = strip.channelbag(animation_data.action_slot).fcurves.find(path)
        assert curve is not None, (node.bl_idname, field, path)
        assert len(curve.keyframe_points) == 1
        point = curve.keyframe_points[0]
        assert abs(point.co.x - 5.25) < 1e-6
        assert abs(point.co.y - value) < 1e-6
        assert node.keyframe_delete(data_path=field, frame=5.25)
    assert not node.bl_rna.properties["peak_nits"].is_animatable
    assert_not_animatable(node, "peak_nits")

    context = SimpleNamespace(pg_node=node, space_data=SimpleNamespace(edit_tree=tree))
    source_x = node.source_x
    node.source_y = 0.0
    assert node.source_y > 0.0 and node.source_x == source_x
    source_y = node.source_y
    node.source_x = 0.9
    assert 0.0 < node.source_x < 0.9 and node.source_y == source_y
    assert nodes.PG_OT_match_white.execute(None, context) == {"FINISHED"}
    assert abs(node.source_x - nodes.D65[0]) < 1e-6
    assert abs(node.source_y - nodes.D65[1]) < 1e-6

    neighbors = node.input_shadows, node.input_white
    for value in (250.0, 0.1):
        node.input_midtones = value
        assert node.input_shadows < node.input_midtones < node.input_white
        assert (node.input_shadows, node.input_white) == neighbors
    node.exposure = 0.75
    node.cr_balance = 0.5
    node.fit = 0.25
    node.peak_nits = "2000"
    snapshot = nodes._settings_for_node(node)
    assert snapshot.linear.exposure == 0.75
    assert snapshot.linear.balance == (-0.5, 0.0)
    assert snapshot.tone.fit == 0.25 and snapshot.tone.peak_nits == 2000.0
    assert snapshot.tone.input_nits[2] == node.input_midtones
    copied_grade = nodes._make_grade(node)
    try:
        for field in nodes._LINEAR_FIELDS:
            assert getattr(copied_grade.pg_linear, field) == getattr(node, field)
        for field in nodes._TONE_FIELDS:
            assert getattr(copied_grade.pg_tone, field) == getattr(node, field)
    finally:
        bpy.data.node_groups.remove(copied_grade)
    assert nodes.PG_OT_reset_directions.execute(None, context) == {"FINISHED"}
    assert all(getattr(node, field) == 0.0 for field in nodes._LINEAR_FIELDS[3:])
    assert node.exposure == 0.75
    assert nodes.PG_OT_reset_tone.execute(None, context) == {"FINISHED"}
    assert nodes._tone_settings(node) == nodes.ToneSettings()
    nodes._reset_linear(node)
    assert all(abs(getattr(node, field) - value) < 1e-6
               for field, value in nodes._LINEAR_DEFAULTS.items())

    # Nested settings must still find their shared node when a per-node Grade
    # occurs earlier in the same tree's node collection.
    shared = nodes.create_node(tree)
    try:
        assert tuple(tree.nodes).index(node) < tuple(tree.nodes).index(shared)
        assert nodes._holder(shared.pg_linear) == shared
        assert nodes._holder(shared.pg_tone) == shared
        shared.pg_linear.exposure = 1.0
        shared.pg_tone.fit = 0.5
        assert shared.pg_linear.exposure == 0.0
        assert shared.pg_tone.fit == 0.0
    finally:
        tree.nodes.remove(shared)


def connect_grade_graph(tree, node, compositor=False):
    source = tree.nodes.new("CompositorNodeRGB" if compositor else "ShaderNodeRGB")
    sink = tree.nodes.new("CompositorNodeSetAlpha" if compositor
                          else "ShaderNodeBsdfPrincipled")
    if compositor:
        input_socket, output_socket = source.outputs[0], sink.inputs["Image"]
    else:
        input_socket, output_socket = source.outputs["Color"], sink.inputs["Base Color"]

    color_default = (0.13, 0.27, 0.39, 0.51)
    node.inputs["Color"].default_value = color_default
    tree.links.new(input_socket, node.inputs["Color"])
    tree.links.new(node.outputs["Color"], output_socket)
    edges = [
        (source, input_socket.name, node, "Color"),
        (node, "Color", sink, output_socket.name),
    ]
    defaults = {"Color": color_default}

    if not compositor:
        alpha_source = tree.nodes.new("ShaderNodeValue")
        alpha_sink = tree.nodes.new("ShaderNodeMath")
        alpha_default = 0.73
        node.inputs["Alpha"].default_value = alpha_default
        tree.links.new(alpha_source.outputs["Value"], node.inputs["Alpha"])
        tree.links.new(node.outputs["Alpha"], alpha_sink.inputs[0])
        edges.extend((
            (alpha_source, "Value", node, "Alpha"),
            (node, "Alpha", alpha_sink, alpha_sink.inputs[0].name),
        ))
        defaults["Alpha"] = alpha_default

    return {"tree": tree, "node": node, "edges": tuple(edges),
            "defaults": defaults}


def assert_grade_graph(graph):
    tree, node = graph["tree"], graph["node"]
    expected_edges = {
        (source.as_pointer(), output, target.as_pointer(), input_)
        for source, output, target, input_ in graph["edges"]
    }
    actual_edges = {
        (link.from_node.as_pointer(), link.from_socket.name,
         link.to_node.as_pointer(), link.to_socket.name)
        for link in tree.links
        if link.from_node == node or link.to_node == node
    }
    assert actual_edges == expected_edges, (actual_edges, expected_edges)
    for name, expected in graph["defaults"].items():
        actual = node.inputs[name].default_value
        if isinstance(expected, tuple):
            assert all(abs(a - b) < 1e-6 for a, b in zip(actual, expected)), (
                name, tuple(actual), expected
            )
        else:
            assert abs(actual - expected) < 1e-6, (name, actual, expected)


def parameter_banks(node):
    tree = node.node_tree
    images = tuple(tree.get(key) for key in nodes.PARAMETER_BANK_BINDINGS)
    active = tree.get(nodes.PARAMETER_ACTIVE_BANK)
    assert len(images) == 2 and all(image is not None for image in images)
    assert active in (0, 1)
    assert all(image.get(nodes.PARAMETER_IMAGE) == nodes.PARAMETER_SCHEMA
               for image in images)
    selectors = [item for item in tree.nodes if item.get(nodes.PARAMETER_SELECTOR)]
    assert len(selectors) == 1, (node.name, selectors)
    selector = selectors[0]
    if tree.bl_idname == nodes.SHADER_TREE:
        selected = int(round(float(selector.outputs["Value"].default_value)))
    else:
        selected = int(round(float(selector.inputs[0].default_value)))
    assert selected == active, (node.name, active, selected)
    readers = [item for item in node.node_tree.nodes if item.get(nodes.PARAMETER_READER)]
    observed = {item.get(nodes.PARAMETER_READER_BANK): item.image for item in readers}
    assert set(observed) == {0, 1}, (node.name, observed)
    assert all(observed[bank] == images[bank] for bank in (0, 1)), node.name
    return images


def parameter_image(node):
    banks = parameter_banks(node)
    return banks[node.node_tree[nodes.PARAMETER_ACTIVE_BANK]]


def assert_grade_current(node):
    state = nodes._node_stores[node.as_pointer()]["state"]
    details = (node.name, node.get(nodes._NODE_ERROR), state)
    assert not node.get(nodes._NODE_ERROR), details
    assert not node.get(nodes._NODE_PENDING), details
    assert not node.use_custom_color, details
    signature = nodes._kernel_signature(
        node.id_data.bl_idname, nodes._settings_for_node(node), nodes._working_space()
    )
    assert state.desired_signature == signature, details
    assert state.applied_signature == signature, details
    assert nodes.node_policy.output_allowed(state), details
    assert nodes._kernel_is_current(
        node.node_tree, node.id_data.bl_idname, signature, stack=False
    ), details
    banks = parameter_banks(node)
    assert all(image.packed_file is not None and not image.is_dirty for image in banks), details
    if node.id_data.bl_idname == nodes.SHADER_TREE:
        group_input = node.node_tree.nodes.get("Group Input")
        group_output = node.node_tree.nodes.get("Group Output")
        assert any(link.from_socket == group_input.outputs["Alpha"]
                   and link.to_socket == group_output.inputs["Alpha"]
                   for link in node.node_tree.links), details


def assert_local_grade_resources(identities):
    resources = []
    for collection, owner_name, node_name in identities:
        owner = getattr(bpy.data, collection)[owner_name]
        node = owner.node_tree.nodes[node_name]
        assert node.pg_grade is None
        assert owner.node_tree.is_embedded_data
        assert_grade_current(node)
        kernel = node.node_tree
        assert kernel.get(nodes.PARAMETER_OWNER) == owner
        assert not kernel[nodes.PARAMETER_OWNER].is_embedded_data
        assert kernel.get(nodes.PARAMETER_OWNER_NODE) == node_name
        resources.append((kernel.name, tuple(image.name for image in parameter_banks(node))))
    assert len({kernel for kernel, _image in resources}) == len(identities)
    assert len({images for _kernel, images in resources}) == len(identities)
    return tuple(resources)


def grade_resource_inventory(node):
    """Numerical edits preserve topology and parameter image format."""
    seen = set()
    inventory = []

    def visit(tree):
        pointer = tree.as_pointer()
        if pointer in seen:
            return
        seen.add(pointer)
        inventory.append(("tree", pointer))
        for item in tree.nodes:
            inventory.append(("node", item.as_pointer(), item.bl_idname))
            image = getattr(item, "image", None)
            if image is not None:
                inventory.append(("image", item.as_pointer(), image.as_pointer(),
                                  tuple(image.size), image.colorspace_settings.name,
                                  image.alpha_mode))
            child = getattr(item, "node_tree", None)
            if child is not None:
                visit(child)
        inventory.extend(("link", link.as_pointer(), link.from_socket.as_pointer(),
                          link.to_socket.as_pointer()) for link in tree.links)

    visit(node.node_tree)
    return tuple(inventory)


def begin_ui_gesture(nodes, tree, node, window_key, *, activate=True):
    # Stub only native observer installation; route input through the actual
    # coordinator and modal adapter below.
    nodes._gesture_state, effects = nodes.gesture_policy.step(
        nodes._gesture_state, nodes.gesture_policy.Event("window_seen", window_id=window_key))
    token = nodes.gesture_policy.pending_observer(nodes._gesture_state, window_key)
    nodes._dispatch_gesture(nodes.gesture_policy.Event(
        "observer_install_result", window_id=window_key, token=token, success=True))
    router = SimpleNamespace(window_key=window_key, token=token)
    area = SimpleNamespace(
        type="NODE_EDITOR",
        spaces=SimpleNamespace(active=SimpleNamespace(edit_tree=tree, show_region_ui=True)),
        regions=(SimpleNamespace(type="UI", x=50, y=50, width=200, height=200),),
    )
    context = SimpleNamespace(
        window=SimpleNamespace(screen=SimpleNamespace(areas=(area,))),
        area=None, region=None, space_data=None,
    )
    tree.nodes.active = node

    def send(event_type, value, x, y):
        event = SimpleNamespace(type=event_type, value=value, mouse_x=x, mouse_y=y)
        return nodes.PG_OT_gesture_router.modal(router, context, event)

    assert send("LEFTMOUSE", "PRESS", 100, 100) == {"PASS_THROUGH"}
    assert nodes._gesture_token(router.window_key) is not None and nodes._gesture_phase(router.window_key) != "active"
    record = nodes._record_for(node)
    assert not record["state"].gesture_active

    assert send("MOUSEMOVE", "NOTHING", 102, 101) == {"PASS_THROUGH"}
    assert nodes._gesture_token(router.window_key) is not None and nodes._gesture_phase(router.window_key) != "active"
    assert nodes._gesture_phase(window_key) == "armed"
    assert not record["state"].gesture_active

    if not activate:
        return router, context

    assert send("MOUSEMOVE", "NOTHING", 103, 100) == {"PASS_THROUGH"}
    assert (nodes._gesture_phase(router.window_key) == "active") and nodes._gesture_token(router.window_key) is not None
    assert nodes._gesture_phase(window_key) not in ("armed", "finishing_armed")
    assert record["state"].gesture_active
    return router, context


def release_ui_gesture(nodes, router, context):
    callbacks = []
    original_partial = nodes.partial

    def capture_release_callback(function, *args, **kwargs):
        callback = original_partial(function, *args, **kwargs)
        if function is nodes._observe_gesture_finish:
            callbacks.append(callback)
        return callback

    nodes.partial = capture_release_callback
    try:
        event = SimpleNamespace(type="LEFTMOUSE", value="RELEASE",
                                mouse_x=103, mouse_y=100)
        assert nodes.PG_OT_gesture_router.modal(router, context, event) == {
            "PASS_THROUGH"
        }
    finally:
        nodes.partial = original_partial
    assert len(callbacks) == 1
    callback = callbacks[0]
    callback()
    if bpy.app.timers.is_registered(callback):
        bpy.app.timers.unregister(callback)
    nodes._dispatch_gesture(nodes.gesture_policy.Event("window_gone", window_id=router.window_key))


class TestStackBackend:
    """Small deterministic host backend for lifecycle tests without a GPU context."""

    def create_job(self, payload, progressive):
        settings, working_space = payload
        matrices = tuple(nodes.prepare_linear(item.linear, working_space).rgb_matrix
                         for item in settings)
        matrix, to_lut, from_lut, signature = lut_kernel._stack_matrix(
            matrices, working_space
        )

        def cube(size):
            coordinates = lut_kernel.axis(lut_kernel.SIZE)
            if size == lut_kernel.PREVIEW_SIZE:
                coordinates = coordinates[::2]
            lattice = np.stack(np.meshgrid(coordinates, coordinates, coordinates,
                                           indexing="ij"), axis=-1)
            values = (lattice @ matrix.T).astype(np.float32)
            edges = np.zeros((3, size, size, size, 3), dtype=np.float32)
            for direction in range(3):
                delta = np.zeros(size, dtype=np.float64)
                delta[:-1] = np.diff(coordinates)
                shape = [1, 1, 1, 1]
                shape[direction] = size
                edges[direction] = (
                    delta.reshape(shape)
                    * matrix[:, direction].reshape(1, 1, 1, 3)
                ).astype(np.float32)
            values.flags.writeable = False
            edges.flags.writeable = False
            to_lut.flags.writeable = False
            from_lut.flags.writeable = False
            result = lut_kernel.LinearCube(
                values, edges, signature, working_space,
                to_lut, from_lut, size,
            )
            return nodes._PreparedStack(settings, working_space, result)

        return TestStackJob(cube, progressive)

    def close(self):
        pass


class TestStackJob:
    def __init__(self, make_cube, progressive):
        self.make_cube = make_cube
        self.progressive = progressive
        self.step = 0

    def advance(self):
        self.step += 1
        if self.progressive and self.step == 1:
            return "preview", self.make_cube(lut_kernel.PREVIEW_SIZE)
        return "full", self.make_cube(lut_kernel.SIZE)

    def close(self):
        pass


nodes.StackHelperBackend = TestStackBackend
nodes._preparation_runtime._lanes["lut"].host_owner = TestStackBackend()


extension.register()
assert not initial_scans
assert bpy.app.timers.is_registered(nodes._startup_reconcile_tick)
assert nodes.PGShaderGrade.is_registered
assert nodes.PGCompositorGrade.is_registered
assert nodes.PGShaderGradePerNode.is_registered
assert nodes.PGCompositorGradePerNode.is_registered
assert nodes.PGGradeData.is_registered
assert nodes.PGLinearSettings.is_registered
assert nodes.PGToneSettings.is_registered
assert nodes.PG_PT_linear.is_registered
assert nodes.PGShaderGradeStack.is_registered
assert nodes.PGCompositorGradeStack.is_registered
assert nodes.PGStackEntry.is_registered
assert nodes.PG_OT_stack_action.is_registered
assert nodes.PG_OT_new_stack_grade.is_registered
assert nodes.PG_OT_add_grade.is_registered
assert nodes.PG_OT_add_per_node_grade.is_registered
assert nodes.PG_OT_new_grade.is_registered
assert nodes.PG_OT_unlink_grade.is_registered
assert nodes.PG_OT_match_white.is_registered
assert nodes.PG_OT_reset_directions.is_registered
assert callable(node_library.prepare_linear)
for menu_type in nodes.MENU_TYPES:
    assert nodes.draw_add_menu in menu_type.draw._draw_funcs
    assert menu_type.draw._draw_funcs.count(nodes.draw_add_menu) == 1
for handler, callback in (
    (bpy.app.handlers.load_post, nodes._load_post),
    (bpy.app.handlers.undo_pre, nodes._undo_redo_pre),
    (bpy.app.handlers.redo_pre, nodes._undo_redo_pre),
    (bpy.app.handlers.undo_post, nodes._undo_redo_post),
    (bpy.app.handlers.redo_post, nodes._undo_redo_post),
    (bpy.app.handlers.render_pre, nodes._render_pre),
    (bpy.app.handlers.depsgraph_update_post, nodes._depsgraph_update_post),
):
    assert handler.count(callback) == 1

# The first Grade is added to the embedded material tree used by the Shader
# Editor, before any standalone group or shared Grade can mask initialization.
_start_timing_section("node and ownership setup")
first_material = bpy.data.materials.new("First Material Grade")
first_material.use_nodes = True
first_material.use_fake_user = True
assert first_material.node_tree.is_embedded_data
first_context = SimpleNamespace(space_data=SimpleNamespace(
    edit_tree=first_material.node_tree, cursor_location=(40.0, -20.0)))
assert nodes.PG_OT_add_grade.poll(first_context)
assert nodes.PG_OT_add_grade.execute(None, first_context) == {"FINISHED"}
first_node = first_material.node_tree.nodes.active
assert first_node.pg_grade is None
assert nodes._startup_reconcile_tick() is None
assert len(initial_scans) == 1
if bpy.app.timers.is_registered(nodes._startup_reconcile_tick):
    bpy.app.timers.unregister(nodes._startup_reconcile_tick)
assert not bpy.app.timers.is_registered(nodes._startup_reconcile_tick)
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(first_node)
assert first_node.pg_grade is None
assert first_node.inputs["Alpha"].default_value == 1.0
first_material_name = first_material.name
first_node_name = first_node.name

# Deleting and recreating the same local Grade must not reuse removed image
# wrappers from the previous node's resources. Keep the runtime cache intact.
removed_kernel_name = first_node.node_tree.name
removed_image_names = tuple(image.name for image in parameter_banks(first_node))
first_material.node_tree.nodes.remove(first_node)
del first_node
assert first_node_name not in first_material.node_tree.nodes
assert removed_kernel_name not in bpy.data.node_groups
assert all(name not in bpy.data.images for name in removed_image_names)
assert nodes.PG_OT_add_grade.execute(None, first_context) == {"FINISHED"}
first_node = first_material.node_tree.nodes.active
assert first_node.name == first_node_name
assert first_node.pg_grade is None
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(first_node)

# Equal local settings retain separate writable resources within one tree and
# across containing datablocks whose Grade nodes have the same name.
local_grade_identities = [("materials", first_material_name, first_node_name)]
second_local_node = nodes.create_node(first_material.node_tree)
local_grade_identities.append(
    ("materials", first_material_name, second_local_node.name))
for collection, owner in (
        ("materials", bpy.data.materials.new("Independent Material Grade")),
        ("worlds", bpy.data.worlds.new("Local World Grade")),
        ("lights", bpy.data.lights.new("Local Light Grade", type="POINT"))):
    owner.use_nodes = True
    owner.use_fake_user = True
    local_node = nodes.create_node(owner.node_tree)
    local_node.name = first_node_name
    local_grade_identities.append((collection, owner.name, local_node.name))
local_grade_identities = tuple(local_grade_identities)
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert_local_grade_resources(local_grade_identities)
del first_context, first_node, first_material, second_local_node, owner, local_node

shader_tree = bpy.data.node_groups.new("Grade Shader Test", "ShaderNodeTree")
shader_tree.use_fake_user = True
shader_space = SimpleNamespace(edit_tree=shader_tree, cursor_location=(40.0, -20.0))
shader_context = SimpleNamespace(space_data=shader_space)
assert nodes.PG_OT_add_grade.poll(shader_context)
assert nodes.PG_OT_add_grade.execute(None, shader_context) == {"FINISHED"}
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
shader_node = shader_tree.nodes.active
assert shader_node.bl_idname == "PGShaderGrade"
assert [socket.name for socket in shader_node.inputs] == ["Color", "Alpha"]
assert [socket.bl_idname for socket in shader_node.inputs] == [
    "NodeSocketColor", "NodeSocketFloat"
]
assert shader_node.inputs["Alpha"].default_value == 1.0
assert [socket.name for socket in shader_node.outputs] == ["Color", "Alpha"]
assert shader_node.pg_grade is None
assert_not_animatable(
    shader_tree, shader_node.path_from_id() + ".pg_linear.exposure",
)
assert tuple(shader_node.location) == (40.0, -20.0)
assert shader_node.select
assert_menu_item(shader_tree)

shader_input = shader_node.node_tree.nodes.get("Group Input")
shader_output = shader_node.node_tree.nodes.get("Group Output")
assert any(link.from_socket == shader_input.outputs["Color"]
           for link in shader_node.node_tree.links)
assert any(link.to_socket == shader_output.inputs["Color"]
           for link in shader_node.node_tree.links)
assert any(link.from_socket == shader_input.outputs["Alpha"]
           and link.to_socket == shader_output.inputs["Alpha"]
           for link in shader_node.node_tree.links), tuple(
               (link.from_socket.name, link.to_socket.name)
               for link in shader_node.node_tree.links)

compositor_tree = bpy.data.node_groups.new("Grade Compositor Test", "CompositorNodeTree")
compositor_tree.use_fake_user = True
compositor_space = SimpleNamespace(edit_tree=compositor_tree, cursor_location=(25.0, 15.0))
compositor_context = SimpleNamespace(space_data=compositor_space)
assert nodes.PG_OT_add_grade.poll(compositor_context)
assert nodes.PG_OT_add_grade.execute(None, compositor_context) == {"FINISHED"}
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
compositor_node = compositor_tree.nodes.active
assert_grade_current(compositor_node)
removed_node_name = compositor_node.name
removed_kernel_name = compositor_node.node_tree.name
removed_image_names = tuple(image.name for image in parameter_banks(compositor_node))
compositor_tree.nodes.remove(compositor_node)
del compositor_node
assert removed_kernel_name not in bpy.data.node_groups
assert all(name not in bpy.data.images for name in removed_image_names)
assert nodes.PG_OT_add_grade.execute(None, compositor_context) == {"FINISHED"}
compositor_node = compositor_tree.nodes.active
assert compositor_node.name == removed_node_name
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(compositor_node)
assert compositor_node.bl_idname == "PGCompositorGrade"
assert [socket.name for socket in compositor_node.inputs] == ["Color"]
assert [socket.name for socket in compositor_node.outputs] == ["Color"]
assert compositor_node.pg_grade is None
assert_not_animatable(
    compositor_tree, compositor_node.path_from_id() + ".pg_linear.exposure",
)
assert_menu_item(compositor_tree)

compositor_input = compositor_node.node_tree.nodes.get("Group Input")
compositor_output = compositor_node.node_tree.nodes.get("Group Output")
restore = next(link.from_node for link in compositor_node.node_tree.links
               if link.to_socket == compositor_output.inputs["Color"])
assert restore.bl_idname == "CompositorNodeSetAlpha"
separate = next(link.from_node for link in compositor_node.node_tree.links
                if link.to_socket == restore.inputs["Alpha"])
assert separate.bl_idname == "CompositorNodeSeparateColor"
assert any(link.from_socket == separate.outputs["Alpha"]
           and link.to_socket == restore.inputs["Alpha"]
           for link in compositor_node.node_tree.links)
assert any(link.from_socket == restore.outputs["Image"]
           and link.to_socket == compositor_output.inputs["Color"]
           for link in compositor_node.node_tree.links)

# Per-Node Grade owns native node-tree F-curves and does not expose a shared
# Grade datablock selector.
per_node_tree = bpy.data.node_groups.new("Per-Node Grade Variant Test", "ShaderNodeTree")
per_node_context = SimpleNamespace(space_data=SimpleNamespace(
    edit_tree=per_node_tree, cursor_location=(15.0, 25.0)))
assert nodes.PG_OT_add_per_node_grade.poll(per_node_context)
assert nodes.PG_OT_add_per_node_grade.execute(None, per_node_context) == {"FINISHED"}
per_node_shader = per_node_tree.nodes.active
assert per_node_shader.bl_idname == "PGShaderGradePerNode"
assert [socket.name for socket in per_node_shader.inputs] == ["Color", "Alpha"]
assert [socket.name for socket in per_node_shader.outputs] == ["Color", "Alpha"]
check_per_node_properties(per_node_shader)
per_node_path = per_node_shader.path_from_id("exposure")
for frame, exposure in ((1, 0.0), (3, 2.0)):
    bpy.context.scene.frame_set(frame)
    per_node_shader.exposure = exposure
    assert per_node_tree.keyframe_insert(data_path=per_node_path, frame=frame)
per_node_action = per_node_tree.animation_data.action
per_node_strip = per_node_action.layers[0].strips[0]
per_node_curve = next(
    curve for curve in per_node_strip.channelbag(per_node_tree.animation_data.action_slot).fcurves
    if curve.data_path == per_node_path
)
assert per_node_curve is not None
for point in per_node_curve.keyframe_points:
    point.interpolation = "LINEAR"
assert tuple((round(point.co.x), round(point.co.y))
             for point in per_node_curve.keyframe_points) == ((1, 0), (3, 2))
per_node_shader[nodes._NODE_ANIMATION_ERROR] = True
status_labels = []
nodes._draw_node_status(
    per_node_shader,
    SimpleNamespace(label=lambda **kwargs: status_labels.append(kwargs)),
)
assert {item["text"] for item in status_labels} >= {
    "Could not create an animation keyframe",
}
del per_node_shader[nodes._NODE_ANIMATION_ERROR]
per_node_compositor_tree = bpy.data.node_groups.new(
    "Per-Node Grade Variant Compositor Test", "CompositorNodeTree",
)
per_node_compositor = nodes.create_per_node_node(per_node_compositor_tree)
assert per_node_compositor.bl_idname == "PGCompositorGradePerNode"
assert [socket.name for socket in per_node_compositor.inputs] == ["Color"]
assert [socket.name for socket in per_node_compositor.outputs] == ["Color"]
check_per_node_properties(per_node_compositor)
per_node_compositor_tree.nodes.remove(per_node_compositor)
per_node_tree.nodes.remove(per_node_shader)
bpy.data.node_groups.remove(per_node_compositor_tree)
bpy.data.node_groups.remove(per_node_tree)

# Static shared datablock values reject keyframe insertion.
shared_grade = bpy.data.node_groups.new(
    "Static Grade animation rejection", nodes.PGGradeData.bl_idname,
)
assert_not_animatable(shared_grade, "pg_linear.exposure")
assert_not_animatable(shared_grade, "pg_tone.fit")
assert any(link.from_socket == compositor_input.outputs["Color"]
           and link.to_socket == separate.inputs["Image"]
           for link in compositor_node.node_tree.links)

# Shared datablock edits upload one image used by fixed Shader/Compositor graphs.
shared_grade = bpy.data.node_groups.new("Shared Grade Test", nodes.PGGradeData.bl_idname)
shader_node.pg_grade = shared_grade
compositor_node.pg_grade = shared_grade
shared_shader_nodes = [nodes.create_node(shader_tree) for _ in range(3)]
for shared_node in shared_shader_nodes:
    shared_node.pg_grade = shared_grade
shared_compositor_node = nodes.create_node(compositor_tree)
shared_compositor_node.pg_grade = shared_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert len({node.node_tree.as_pointer() for node in shared_shader_nodes}) == 1
shared_parameter_image = parameter_image(shader_node)
shared_parameter_banks = parameter_banks(shader_node)
assert all(parameter_banks(node) == shared_parameter_banks
           for node in (*shared_shader_nodes, compositor_node, shared_compositor_node))
for tree in (shared_shader_nodes[0].node_tree, shared_compositor_node.node_tree):
    assert tree.get(nodes.PARAMETER_OWNER) == shared_grade
    assert tree.get(nodes.PARAMETER_OWNER_NODE, "") == ""

# Cached slider requests use stored receipts for both tree types. A Compositor
# request with no runtime receipt is an adoption boundary and keeps its full
# audit, so model the ordinary receipt-backed cache here.
original_parameter_kernel_valid = nodes._parameter_kernel_valid
original_compositor_known = nodes._compositor_receipts.known
try:
    def reject_deep_request_audit(_kernel):
        raise AssertionError("cached Grade request performed a deep kernel audit")

    nodes._parameter_kernel_valid = reject_deep_request_audit
    nodes._compositor_receipts.known = lambda _pointer: True
    for cached_node in (shared_shader_nodes[0], shared_compositor_node):
        cached_record = nodes._node_stores[cached_node.as_pointer()]
        applied_signature = cached_record["state"].applied_signature
        assert applied_signature is not None
        assert not nodes._request_node(cached_node, nodes._working_space())
        assert cached_record["state"].applied_signature == applied_signature
finally:
    nodes._parameter_kernel_valid = original_parameter_kernel_valid
    nodes._compositor_receipts.known = original_compositor_known

# Removing one user must retain the kernel and image still used by its peers.
shared_kernel = shader_node.node_tree
removed_node_name = shared_shader_nodes[0].name
shader_tree.nodes.remove(shared_shader_nodes[0])
assert_grade_current(shader_node)
assert_grade_current(compositor_node)
assert shader_node.node_tree == shared_kernel
assert parameter_banks(shader_node) == shared_parameter_banks
shared_shader_nodes[0] = nodes.create_node(shader_tree)
assert shared_shader_nodes[0].name == removed_node_name
shared_shader_nodes[0].pg_grade = shared_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(shared_shader_nodes[0])
assert shared_shader_nodes[0].node_tree == shared_kernel
shared_parameter_image = parameter_image(shared_shader_nodes[0])
shared_parameter_banks = parameter_banks(shared_shader_nodes[0])
assert all(parameter_banks(node) == shared_parameter_banks
           for node in (*shared_shader_nodes, shader_node, compositor_node, shared_compositor_node))
initial_active_bank = shader_node.node_tree[nodes.PARAMETER_ACTIVE_BANK]
shared_inventories = tuple(grade_resource_inventory(node)
                          for node in (shader_node, compositor_node))
shader_graph = connect_grade_graph(shader_tree, shader_node)
compositor_graph = connect_grade_graph(compositor_tree, compositor_node,
                                       compositor=True)
assert_grade_graph(shader_graph)
assert_grade_graph(compositor_graph)
main_thread = threading.get_ident()
preparation_threads = []
kernel_build_threads = []
parameter_write_threads = []
preparation_started = threading.Event()
release_preparation = threading.Event()
runtime = nodes._preparation_runtime
original_prepare = runtime.prepare
original_kernel_builder = nodes._kernel
original_parameter_writer = nodes._write_grade_parameters


async def record_prepare(payload):
    settings = payload.linear
    preparation_threads.append((threading.get_ident(), settings.exposure))
    preparation_started.set()
    assert release_preparation.wait(10), "preparation worker was not released"
    return await original_prepare(payload)


def record_kernel_build(*args, **kwargs):
    kernel_build_threads.append(threading.get_ident())
    return original_kernel_builder(*args, **kwargs)


def record_parameter_write(image, pixels):
    parameter_write_threads.append((threading.get_ident(), image.as_pointer()))
    return original_parameter_writer(image, pixels)


runtime.prepare = record_prepare
nodes._kernel = record_kernel_build
nodes._write_grade_parameters = record_parameter_write
shared_grade.pg_linear.exposure = 1.0
assert preparation_started.wait(10), "preparation did not start on a worker"
assert shader_node.pg_linear.exposure == 0.0
assert compositor_node.pg_linear.exposure == 0.0
for node in (shader_node, compositor_node):
    assert node.node_tree.get(nodes._KERNEL_KIND) == nodes._KERNEL_SCHEMA
    assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    assert node.get(nodes._NODE_PENDING) == "status.showing_last_good"
assert_grade_graph(shader_graph)
assert_grade_graph(compositor_graph)
release_preparation.set()
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
runtime.prepare = original_prepare
nodes._kernel = original_kernel_builder
nodes._write_grade_parameters = original_parameter_writer
assert len(preparation_threads) == 1, preparation_threads
assert all(thread != main_thread for thread, _exposure in preparation_threads)
assert not kernel_build_threads, kernel_build_threads
shared_parameter_image = parameter_image(shader_node)
assert parameter_banks(shader_node) == shared_parameter_banks
assert shader_node.node_tree[nodes.PARAMETER_ACTIVE_BANK] == 1 - initial_active_bank
assert parameter_write_threads == [(main_thread, shared_parameter_image.as_pointer())]
assert all(parameter_image(node) == shared_parameter_image
           for node in (*shared_shader_nodes, compositor_node, shared_compositor_node))
assert shared_parameter_image.get(nodes.PARAMETER_SIGNATURE) == (
    nodes._preparation_signature(
        nodes._grade_settings(shared_grade, nodes._working_space()),
        nodes._working_space(),
    )
)
assert tuple(grade_resource_inventory(node)
             for node in (shader_node, compositor_node)) == shared_inventories
assert len({node.node_tree.as_pointer() for node in shared_shader_nodes}) == 1
assert_grade_graph(shader_graph)
assert_grade_graph(compositor_graph)
assert any(node.bl_idname == "ShaderNodeVectorMath"
           for node in shader_node.node_tree.nodes)
assert any(node.bl_idname == "ShaderNodeVectorMath"
           for node in compositor_node.node_tree.nodes)
assert shared_grade.pg_linear.cr_balance == 0.0

# Settings use the product UI convention; the library owns the transform sign.
_start_timing_section("parameter and save/load recovery")
shared_grade.pg_linear.cr_balance = 0.5
assert nodes._linear_settings(shared_grade.pg_linear).balance == (-0.5, 0.0)
assert shader_node.pg_linear.cr_balance == 0.0
assert compositor_node.pg_linear.cr_balance == 0.0
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert len({node.node_tree.as_pointer() for node in shared_shader_nodes}) == 1

# Tone settings are part of the authoritative Stage 2 snapshot and its kernel
# signature. A linked Grade edit updates every Shader/Compositor consumer.
shared_grade.pg_tone.fit = 0.5
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
shared_tone_settings = nodes._grade_settings(shared_grade, nodes._working_space())
shared_tone_signature = nodes._signature(
    nodes.SHADER_TREE, nodes._snapshot_values(shared_tone_settings), nodes._working_space()
)
for node in (*shared_shader_nodes, shader_node, compositor_node):
    expected_kind = node.id_data.bl_idname
    expected_signature = nodes._signature(
        expected_kind, nodes._snapshot_values(shared_tone_settings), nodes._working_space()
    )
    assert node.node_tree.get(nodes._KERNEL_SIGNATURE) == expected_signature, (
        node.name, node.get(nodes._NODE_PENDING),
        node.node_tree.get(nodes._KERNEL_SIGNATURE), expected_signature,
        nodes._node_stores.get(node.as_pointer()),
    )
    assert node.node_tree.get("_perceptual_grade_stage2_complete")
assert shared_tone_signature == nodes._kernel_signature(
    nodes.SHADER_TREE, shared_grade.pg_linear, nodes._working_space()
)
assert any(node.bl_idname == "ShaderNodeTexImage"
           and "Tone" in node.label
           for node in shader_node.node_tree.nodes)

# Material node trees are included in shared Grade updates.
material = bpy.data.materials.new("Grade Material Test")
material.use_nodes = True
material.use_fake_user = True
material_node = nodes.create_node(material.node_tree)
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert material_node.pg_grade is None
assert_grade_current(material_node)
material_node.pg_grade = shared_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
material_kernel = material_node.node_tree
shared_grade.pg_linear.exposure = 1.5
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert material_node.pg_linear.exposure == 0.0
assert material_node.node_tree == material_kernel
shared_parameter_image = parameter_image(shared_shader_nodes[0])
assert parameter_image(material_node) == shared_parameter_image

# Equal-valued independent Grades must never share writable resources. Selecting
# another Grade with an equal signature still changes the owner and bindings.
independent_grade = nodes._make_grade(shared_grade)
independent_grade.name = "Independent Equal Grade"
independent_node = nodes.create_node(shader_tree)
independent_node.pg_grade = independent_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
independent_image = parameter_image(independent_node)
assert independent_node.node_tree != shared_shader_nodes[0].node_tree
assert independent_image != shared_parameter_image
assert independent_node.node_tree.get(nodes._KERNEL_SIGNATURE) == (
    shared_shader_nodes[0].node_tree.get(nodes._KERNEL_SIGNATURE)
)
# The final user of a shared Grade also releases its generated resources, and
# relinking that same Grade must build fresh resources from its saved settings.
removed_node_name = independent_node.name
removed_kernel_name = independent_node.node_tree.name
removed_image_names = tuple(image.name for image in parameter_banks(independent_node))
shader_tree.nodes.remove(independent_node)
del independent_node, independent_image
assert removed_kernel_name not in bpy.data.node_groups
assert all(name not in bpy.data.images for name in removed_image_names)
independent_node = nodes.create_node(shader_tree)
assert independent_node.name == removed_node_name
independent_node.pg_grade = independent_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(independent_node)

# Saved metadata alone cannot make a graph current: every parameter reader
# must remain marked and bound to that Grade's current image.
for corruption in ("unmarked", "misbound", "misbound_tracked"):
    corrupt_kernel = independent_node.node_tree
    corrupt_kernel.use_fake_user = True
    reader = next(item for item in corrupt_kernel.nodes if item.get(nodes.PARAMETER_READER))
    if corruption == "unmarked":
        del reader[nodes.PARAMETER_READER]
    else:
        reader.image = parameter_image(shared_shader_nodes[0])
    assert not nodes._parameter_kernel_valid(corrupt_kernel)
    if corruption != "misbound_tracked":
        # Recreate the record to exercise saved-kernel adoption. The final case
        # keeps its record so render preflight must reject a corrupt live cache.
        nodes._node_stores.pop(independent_node.as_pointer())
    if corruption == "misbound_tracked":
        original_valid = nodes._parameter_kernel_valid
        audited_kernels = []
        corrupt_kernel_pointer = corrupt_kernel.as_pointer()

        def track_deep_audit(kernel):
            audited_kernels.append(
                kernel.as_pointer() if kernel is not None else None
            )
            return original_valid(kernel)

        nodes._parameter_kernel_valid = track_deep_audit
        try:
            failures = nodes._ensure_all_kernels()
            assert not failures, failures
            failures = nodes._drain_preparations()
            assert not failures, failures
            assert corrupt_kernel_pointer in audited_kernels
        finally:
            nodes._parameter_kernel_valid = original_valid
    else:
        failures = nodes._refresh_nodes((independent_node,))
        assert not failures, failures
        failures = nodes._drain_preparations()
        assert not failures, failures
    assert_grade_current(independent_node)
    assert independent_node.node_tree != corrupt_kernel
    corrupt_kernel.use_fake_user = False
    assert not nodes._retire_kernels((corrupt_kernel,))

# Readiness must prove that each published selector actually chooses the two
# parameter branches, rather than trusting reader metadata alone.
shader_kernel = independent_node.node_tree
shader_selector = next(item for item in shader_kernel.nodes
                       if item.get(nodes.PARAMETER_SAMPLE_SELECTOR)
                       and item.get(nodes.PARAMETER_SAMPLE_KIND) == "vector")
shader_factor = shader_selector.inputs[0]
shader_factor_link = shader_factor.links[0]
shader_factor_source, shader_factor_target = (
    shader_factor_link.from_socket, shader_factor_link.to_socket,
)
shader_kernel.links.remove(shader_factor_link)
assert not nodes._parameter_kernel_valid(shader_kernel)
shader_kernel.links.new(shader_factor_source, shader_factor_target)
assert nodes._parameter_kernel_valid(shader_kernel)

compositor_kernel = shared_compositor_node.node_tree
sample_id = next(item[nodes.PARAMETER_SAMPLE_ID]
                 for item in compositor_kernel.nodes
                 if item.get(nodes.PARAMETER_SAMPLE_SELECTOR))
map_uv = next(item for item in compositor_kernel.nodes
              if item.bl_idname == "CompositorNodeMapUV"
              and item.get(nodes.PARAMETER_SAMPLE_ID) == sample_id
              and item.get(nodes.PARAMETER_SAMPLE_BANK) == 0)
separate = next(item for item in compositor_kernel.nodes
                if item.bl_idname == "CompositorNodeSeparateColor"
                and item.get(nodes.PARAMETER_SAMPLE_ID) == sample_id
                and item.get(nodes.PARAMETER_SAMPLE_BANK) == 0)
compositor_link = separate.inputs["Image"].links[0]
compositor_source, compositor_target = (
    compositor_link.from_socket, compositor_link.to_socket,
)
compositor_kernel.links.remove(compositor_link)
assert not nodes._parameter_kernel_valid(compositor_kernel)
compositor_kernel.links.new(compositor_source, compositor_target)
assert nodes._parameter_kernel_valid(compositor_kernel)
other_map_uv = next(item for item in compositor_kernel.nodes
                    if item.bl_idname == "CompositorNodeMapUV"
                    and item.get(nodes.PARAMETER_SAMPLE_ID) != sample_id)
wrong_uv_link = other_map_uv.inputs["UV"].links[0]
wrong_uv = (wrong_uv_link.from_socket, wrong_uv_link.to_socket)
original_uv_link = map_uv.inputs["UV"].links[0]
original_uv = (original_uv_link.from_socket, original_uv_link.to_socket)
compositor_kernel.links.remove(original_uv_link)
compositor_kernel.links.new(wrong_uv[0], map_uv.inputs["UV"])
assert not nodes._parameter_kernel_valid(compositor_kernel)
compositor_kernel.links.remove(map_uv.inputs["UV"].links[0])
compositor_kernel.links.new(original_uv[0], original_uv[1])
assert nodes._parameter_kernel_valid(compositor_kernel)

# Native removal can invalidate an image without going through node teardown.
# A fresh reconciliation must reject the cached wrapper and repair the Grade.
removed_images = parameter_banks(independent_node)
for removed_image in removed_images:
    bpy.data.images.remove(removed_image, do_unlink=True)
del removed_image, removed_images
failures = nodes._refresh_nodes((independent_node,))
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(independent_node)

# Recover an already-poisoned cache even when no installed kernel remains for
# ordinary replacement retirement to invalidate the removed resource wrappers.
removed_kernel = independent_node.node_tree
removed_images = parameter_banks(independent_node)
bpy.data.node_groups.remove(removed_kernel, do_unlink=True)
for removed_image in removed_images:
    bpy.data.images.remove(removed_image)
del removed_kernel, removed_image, removed_images
assert independent_node.node_tree is None
failures = nodes._refresh_nodes((independent_node,))
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(independent_node)
independent_image = parameter_image(independent_node)
reselected_node = shared_shader_nodes[2]
shared_kernel = reselected_node.node_tree
reselected_node.pg_grade = independent_grade
failures = nodes._drain_preparations()
assert not failures, failures
assert reselected_node.node_tree == independent_node.node_tree
independent_image = parameter_image(independent_node)
assert parameter_image(reselected_node) == independent_image
independent_pixels = np.asarray(independent_image.pixels[:], dtype=np.float32)
shared_grade.pg_linear.exposure = 1.625
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert np.array_equal(independent_image.pixels[:], independent_pixels)
assert reselected_node.node_tree == independent_node.node_tree
reselected_node.pg_grade = shared_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert reselected_node.node_tree == shared_kernel
shared_parameter_image = parameter_image(shared_shader_nodes[0])
assert parameter_image(reselected_node) == shared_parameter_image
shared_grade.pg_linear.exposure = 1.5
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures

# The New operator copies the selected grade; Unlink restores local defaults.
new_context = SimpleNamespace(pg_node=compositor_node)
assert nodes.PG_OT_new_grade.poll(new_context)
assert nodes.PG_OT_new_grade.execute(None, new_context) == {"FINISHED"}
copied_grade = compositor_node.pg_grade
assert copied_grade != shared_grade
assert copied_grade.pg_linear.exposure == 1.5
assert abs(copied_grade.pg_tone.fit - 0.5) < 1e-6
assert nodes.PG_OT_unlink_grade.execute(None, new_context) == {"FINISHED"}
assert compositor_node.pg_grade is None
assert compositor_node.pg_linear.exposure == 0.0

# Local settings cannot create a Grade; adjustment requires explicit creation.
shader_node.pg_grade = None
shader_node.pg_linear.exposure = 0.5
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert shader_node.pg_grade is None
assert all(abs(getattr(shader_node.pg_linear, name) - value) < 1e-6
           for name, value in nodes._LINEAR_DEFAULTS.items())
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=shader_node)) == {"FINISHED"}
assert shader_node.pg_grade is not None
shader_node.pg_grade.pg_linear.exposure = 0.5
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert shader_node.pg_grade.pg_linear.exposure == 0.5

# A partially saved multi-node update is reconciled from the shared Grade's
# authoritative settings and the signatures stored on generated kernels.
old_shared_kernel = shared_shader_nodes[1].node_tree.copy()
old_shared_kernel.use_fake_user = True
# A legacy/corrupt derived group is not an authoritative owner resource.
del old_shared_kernel[nodes.PARAMETER_OWNER]
if nodes.PARAMETER_OWNER_NODE in old_shared_kernel:
    del old_shared_kernel[nodes.PARAMETER_OWNER_NODE]
saved_shared_kernel_name = shared_shader_nodes[0].node_tree.name
saved_compositor_kernel_name = shared_compositor_node.node_tree.name
shared_grade.pg_linear.exposure = 2.0
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
new_signature = nodes._kernel_signature(
    nodes.SHADER_TREE, shared_grade.pg_linear, nodes._working_space()
)
assert all(node.node_tree.get(nodes._KERNEL_SIGNATURE) == new_signature
           for node in shared_shader_nodes)
shared_shader_nodes[1].node_tree = old_shared_kernel
shared_shader_nodes[2].node_tree = old_shared_kernel
assert shared_shader_nodes[0].node_tree != shared_shader_nodes[1].node_tree
saved_parameter_pixels = np.asarray(
    parameter_image(shared_shader_nodes[0]).pixels[:], dtype=np.float32
)
saved_parameter_signature = parameter_image(shared_shader_nodes[0]).get(
    nodes.PARAMETER_SIGNATURE
)
saved_local_resources = assert_local_grade_resources(local_grade_identities)

with tempfile.TemporaryDirectory(prefix="perceptual-grade-recovery-") as temp:
    saved_file = Path(temp) / "partial-grade.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))

nodes._drain_preparations()

shader_tree = bpy.data.node_groups["Grade Shader Test"]
assert assert_local_grade_resources(local_grade_identities) == saved_local_resources
compositor_tree = bpy.data.node_groups["Grade Compositor Test"]
material = bpy.data.materials["Grade Material Test"]
shared_grade = bpy.data.node_groups["Shared Grade Test"]
shader_node = next(node for node in shader_tree.nodes
                   if node.bl_idname == "PGShaderGrade"
                   and node.pg_grade is not None
                   and node.pg_grade.pg_linear.exposure == 0.5)
compositor_node = next(node for node in compositor_tree.nodes
                       if node.bl_idname == "PGCompositorGrade"
                       and node.pg_grade is None)
shared_compositor_node = next(node for node in compositor_tree.nodes
                              if node.bl_idname == "PGCompositorGrade"
                              and node.pg_grade == shared_grade)
material_node = next(node for node in material.node_tree.nodes
                     if node.bl_idname == "PGShaderGrade")
shared_shader_nodes = [node for node in shader_tree.nodes
                       if node.bl_idname == "PGShaderGrade"
                       and node.pg_grade == shared_grade]
assert len(shared_shader_nodes) == 3
new_signature = nodes._kernel_signature(
    nodes.SHADER_TREE, shared_grade.pg_linear, nodes._working_space()
)
assert len({node.node_tree.as_pointer() for node in shared_shader_nodes}) == 1
assert all(node.node_tree.get(nodes._KERNEL_SIGNATURE) == new_signature
           for node in shared_shader_nodes)
assert shared_shader_nodes[0].node_tree.name == saved_shared_kernel_name
# Repairing the partially saved shared group may rewrite its inactive bank;
# the active bank's signature and numerical content must survive.
assert shared_compositor_node.node_tree.name == saved_compositor_kernel_name
assert parameter_image(shared_compositor_node) == parameter_image(shared_shader_nodes[0])
assert parameter_image(shared_shader_nodes[0]).get(nodes.PARAMETER_SIGNATURE) == (
    saved_parameter_signature
)
assert np.array_equal(parameter_image(shared_shader_nodes[0]).pixels[:],
                      saved_parameter_pixels)
before_repeat = shared_shader_nodes[0].node_tree
before_repeat_resources = grade_resource_inventory(shared_shader_nodes[0])
before_repeat_local_pointers = tuple(
    (bpy.data.node_groups[kernel].as_pointer(),
     tuple(bpy.data.images[image].as_pointer() for image in images))
    for kernel, images in saved_local_resources
)
nodes._load_post("")
nodes._drain_preparations()
assert all(node.node_tree == before_repeat for node in shared_shader_nodes)
assert grade_resource_inventory(shared_shader_nodes[0]) == before_repeat_resources
assert assert_local_grade_resources(local_grade_identities) == saved_local_resources
assert tuple(
    (bpy.data.node_groups[kernel].as_pointer(),
     tuple(bpy.data.images[image].as_pointer() for image in images))
    for kernel, images in saved_local_resources
) == before_repeat_local_pointers

active_space = nodes._working_space()
nodes._ensure_all_kernels("ACEScg")
nodes._drain_preparations()
assert all(node.node_tree.get("_perceptual_grade_working_space") == "ACEScg"
           for node in shared_shader_nodes)
failures = nodes._ensure_all_kernels(active_space)
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert all(node.node_tree.get("_perceptual_grade_working_space") == active_space
           for node in shared_shader_nodes)

# Failed regeneration routes every affected node through a visible magenta
# error, then a successful pre-render reconciliation restores the Grade.
original_parameter_writer = nodes._write_grade_parameters
original_output_effect = nodes._apply_output_effect
output_effects = []


def record_output_effect(node, effect):
    output_effects.append(effect.output_mode)
    return original_output_effect(node, effect)


nodes._apply_output_effect = record_output_effect


upload_attempts = []
failed_image = parameter_image(shared_shader_nodes[0])
before_failed_pixels = np.asarray(failed_image.pixels[:], dtype=np.float32)
before_failed_signature = failed_image.get(nodes.PARAMETER_SIGNATURE)
failed_image.use_fake_user = True


def fail_first_upload(image, pixels):
    upload_attempts.append(image.as_pointer())
    original_parameter_writer(image, pixels)
    if len(upload_attempts) == 1:
        raise RuntimeError("simulated parameter upload failure")


nodes._write_grade_parameters = fail_first_upload
shared_grade.pg_linear.exposure = 2.5
reconcile_for_render(bpy.context.scene)
nodes._drain_preparations()
assert all(node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
           for node in shared_shader_nodes)
assert all(node.get(nodes._NODE_ERROR) for node in shared_shader_nodes)
# Failed unpublished storage is discarded; rollback must not rewrite the old image.
assert len(upload_attempts) == 1, upload_attempts
assert upload_attempts[0] != failed_image.as_pointer()
assert np.array_equal(failed_image.pixels[:], before_failed_pixels)
assert failed_image.get(nodes.PARAMETER_SIGNATURE) == before_failed_signature
assert all(node.use_custom_color
           and all(abs(actual - expected) < 1e-6
                   for actual, expected in zip(node.color, (0.65, 0.04, 0.04)))
           for node in shared_shader_nodes)
shader_error = shared_shader_nodes[0].node_tree
shader_output = shader_error.nodes.get("Group Output")
assert tuple(shader_output.inputs["Color"].default_value) == (1.0, 0.0, 1.0, 1.0)
assert any(link.from_socket.name == "Alpha"
           and link.to_socket.name == "Alpha" for link in shader_error.links)
assert nodes._kernel_error_text(shared_shader_nodes[0]) == "Grade output is magenta"
assert shared_compositor_node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
compositor_error = shared_compositor_node.node_tree
magenta = next(node for node in compositor_error.nodes
               if node.bl_idname == "CompositorNodeRGB")
assert tuple(magenta.outputs[0].default_value) == (1.0, 0.0, 1.0, 1.0)
assert any(node.bl_idname == "CompositorNodeSetAlpha" for node in compositor_error.nodes)
separate_error = next(node for node in compositor_error.nodes
                      if node.bl_idname == "CompositorNodeSeparateColor")
restore_error = next(node for node in compositor_error.nodes
                     if node.bl_idname == "CompositorNodeSetAlpha")
assert any(link.from_socket == separate_error.outputs["Alpha"]
           and link.to_socket == restore_error.inputs["Alpha"]
           for link in compositor_error.links)
assert any(link.from_socket == magenta.outputs[0]
           and link.to_socket == restore_error.inputs["Image"]
           for link in compositor_error.links)
nodes._write_grade_parameters = original_parameter_writer
failures = nodes._ensure_all_kernels()
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
failed_image.use_fake_user = False
assert all(node.node_tree.get(nodes._KERNEL_SIGNATURE)
           == nodes._kernel_signature(nodes.SHADER_TREE, shared_grade.pg_linear,
                                      nodes._working_space())
           for node in shared_shader_nodes)
assert all(not node.get(nodes._NODE_ERROR) for node in shared_shader_nodes)
assert all(not node.use_custom_color for node in shared_shader_nodes)
assert "error" in output_effects and "current" in output_effects
nodes._apply_output_effect = original_output_effect

# Forward-only Grade Stacks build 65-cube lookup kernels in both tree types.
_start_timing_section("Stack builds and gestures")
stack_grade = nodes._make_grade()
stack_grade.pg_linear.exposure = 0.5
shader_stack = nodes.create_stack_node(shader_tree)
shader_entry = shader_stack.pg_stack_entries.add()
shader_entry.key = "shader-forward"
shader_entry.grade = stack_grade
compositor_stack = nodes.create_stack_node(compositor_tree)
compositor_entry = compositor_stack.pg_stack_entries.add()
compositor_entry.key = "compositor-forward"
compositor_entry.grade = stack_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
for stack_node, color_name, alpha_name in (
        (shader_stack, "Color", "Alpha"), (compositor_stack, "Color", None)):
    kernel = stack_node.node_tree
    assert kernel.get("_perceptual_grade_stack_kernel"), (
        stack_node.bl_idname, stack_node.get(nodes._NODE_ERROR),
        nodes._record_for(stack_node)["state"], dict(kernel.items())
    )
    assert kernel.get(nodes._KERNEL_QUALITY) == "full"
    assert any(node.bl_idname in {"ShaderNodeTexImage", "CompositorNodeImage"}
               for node in kernel.nodes)
    source = kernel.nodes.get("Group Input")
    output = kernel.nodes.get("Group Output")
    assert any(link.from_socket == source.outputs[color_name]
               for link in kernel.links)
    assert any(link.to_socket == output.inputs[color_name]
               for link in kernel.links)
    if alpha_name is not None:
        assert any(link.from_socket == source.outputs[alpha_name]
                   and link.to_socket == output.inputs[alpha_name]
                   for link in kernel.links)
    else:
        assert any(node.bl_idname == "CompositorNodeSetAlpha" for node in kernel.nodes)
assert shader_stack.pg_stack_entries[0].grade == stack_grade
assert compositor_stack.pg_stack_entries[0].grade == stack_grade
assert nodes._stack_grade_ids(shader_stack) == (stack_grade.as_pointer(),)
assert nodes._stack_signature(
    nodes._settings_for_node(shader_stack), nodes._working_space()
) == shader_stack.node_tree.get(nodes._KERNEL_SIGNATURE)
shader_stack_graph = connect_grade_graph(shader_tree, shader_stack)
compositor_stack_graph = connect_grade_graph(
    compositor_tree, compositor_stack, compositor=True
)
assert_grade_graph(shader_stack_graph)
assert_grade_graph(compositor_stack_graph)
stack_ui_checks = runpy.run_path(str(Path(__file__).with_name("stack_ui_checks.py")))
for tree in (shader_tree, compositor_tree):
    stack_ui_checks["check_grade_ui"](nodes, tree)
    stack_ui_checks["check_stack_ui"](nodes, tree)
    stack_ui_checks["check_gesture_region_routing"](
        nodes, tree, 740 + (tree.bl_idname == "CompositorNodeTree")
    )

# Direct Grade value changes prepare only the final 65-cube result.
stack_grade.pg_linear.exposure = 0.75
assert_grade_graph(shader_stack_graph)
assert_grade_graph(compositor_stack_graph)
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
for stack_node in (shader_stack, compositor_stack):
    source = nodes._record_for(stack_node)["source"]
    prepared = nodes._preparation_runtime._sources[source].last_success
    assert prepared is not None and prepared[0] == "lut" and not prepared[2]
    assert stack_node.node_tree.get(nodes._KERNEL_QUALITY) == "full"
    assert not stack_node.get(nodes._NODE_ERROR)
assert_grade_graph(shader_stack_graph)
assert_grade_graph(compositor_stack_graph)

# A click without pointer movement may edit a value, but it remains final-only.
click_window = 730
nodes._arm_gesture(click_window, shader_stack, (0, 0))
click_token = nodes._gesture_token(click_window)
stack_grade.pg_linear.exposure = 0.875
assert_grade_graph(shader_stack_graph)
assert_grade_graph(compositor_stack_graph)
nodes._end_gesture(click_window, click_token)
reconcile_for_render(bpy.context.scene)
assert_grade_graph(shader_stack_graph)
assert_grade_graph(compositor_stack_graph)
for stack_node in (shader_stack, compositor_stack):
    source = nodes._record_for(stack_node)["source"]
    prepared = nodes._preparation_runtime._sources[source].last_success
    assert prepared is not None and prepared[0] == "lut" and not prepared[2]
    assert stack_node.node_tree.get(nodes._KERNEL_QUALITY) == "full"

# A continuous sidebar drag replaces stale 65-cube refinement with the newest
# 33-cube preview, then finishes that setting at 65-cube quality after release.
runtime = nodes._preparation_runtime
lut_lane = runtime._lanes["lut"]
original_stack_owner = lut_lane.host_owner
preview_ready = threading.Event()
continue_full = threading.Event()
stale_refinement_advanced = threading.Event()
stale_refinement_retired = threading.Event()
latest_preview_ready = threading.Event()
continue_latest_full = threading.Event()
stack_preparation_exposures = []
gesture_window = 731
gesture_router = None
gesture_context = None


class HoldingStackOwner:
    def create_job(self, payload, progressive):
        settings, working_space = payload
        exposure = settings[0].linear.exposure
        stack_preparation_exposures.append(exposure)
        job = original_stack_owner.create_job(payload, progressive)
        ready, release = ((preview_ready, continue_full) if exposure == 1.0 else
                          (latest_preview_ready, continue_latest_full))
        retired = stale_refinement_retired if exposure == 1.0 else None
        return HoldingStackJob(job, ready, release, progressive, retired)

    def close(self):
        original_stack_owner.close()


class HoldingStackJob:
    def __init__(self, job, ready, release, progressive, retired):
        self.job = job
        self.ready = ready
        self.release = release
        self.progressive = progressive
        self.retired = retired
        self.preview_sent = False

    def advance(self):
        if self.progressive and self.preview_sent and not self.release.is_set():
            if self.retired is stale_refinement_retired:
                stale_refinement_advanced.set()
            return None
        receipt = self.job.advance()
        if receipt is not None and receipt[0] == "preview":
            self.preview_sent = True
            self.ready.set()
        return receipt

    def close(self):
        self.job.close()
        if self.preview_sent and self.retired is not None:
            self.retired.set()


def pump_until(event):
    deadline = time.monotonic() + 10
    while not event.is_set() and time.monotonic() < deadline:
        nodes._preparation_tick()
        time.sleep(.001)
    assert event.is_set(), "GPU host lane did not reach the expected receipt"


def pump_until_latest_stack_previews():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        nodes._preparation_tick()
        states = tuple(nodes._record_for(stack_node)["state"]
                       for stack_node in (shader_stack, compositor_stack))
        if all(state.applied_quality == "preview"
               and state.applied_signature == state.desired_signature
               for state in states):
            return
        time.sleep(.001)
    raise AssertionError("latest Stack preview was not published to both consumers")


lut_lane.host_owner = HoldingStackOwner()
try:
    gesture_router, gesture_context = begin_ui_gesture(
        nodes, shader_tree, shader_stack, gesture_window
    )
    stack_grade.pg_linear.exposure = 1.0
    pump_until(preview_ready)
    for exposure in (1.125, 1.25, 1.375):
        stack_grade.pg_linear.exposure = exposure
    pump_until(latest_preview_ready)
    assert stale_refinement_retired.is_set()
    pump_until_latest_stack_previews()
    assert not stale_refinement_advanced.is_set()
    assert stack_preparation_exposures == [1.0, 1.375], stack_preparation_exposures
    for stack_node in (shader_stack, compositor_stack):
        state = nodes._record_for(stack_node)["state"]
        assert state.applied_quality == "preview"
        assert state.applied_signature == state.desired_signature, (
            state.applied_signature, state.desired_signature,
            stack_node.pg_stack_entries[0].grade.pg_linear.exposure,
        )
        assert stack_node.node_tree.get(nodes._KERNEL_QUALITY) == "preview"
    assert_grade_graph(shader_stack_graph)
    assert_grade_graph(compositor_stack_graph)
    release_ui_gesture(nodes, gesture_router, gesture_context)
    gesture_router = None
    for stack_node in (shader_stack, compositor_stack):
        state = nodes._record_for(stack_node)["state"]
        assert not state.gesture_active and state.applied_quality == "preview"
        assert nodes.node_policy.output_mode(state) == "preview"
    assert_grade_graph(shader_stack_graph)
    assert_grade_graph(compositor_stack_graph)
    continue_latest_full.set()
    nodes._drain_preparations()
    for stack_node in (shader_stack, compositor_stack):
        state = nodes._record_for(stack_node)["state"]
        source = nodes._record_for(stack_node)["source"]
        prepared = runtime._sources[source].last_success
        assert prepared is not None and prepared[0] == "lut" and prepared[2]
        assert state.applied_quality == "full"
        assert stack_node.node_tree.get(nodes._KERNEL_QUALITY) == "full"
        assert nodes.node_policy.output_allowed(state)
    assert_grade_graph(shader_stack_graph)
    assert_grade_graph(compositor_stack_graph)
finally:
    continue_full.set()
    continue_latest_full.set()
    if gesture_router is not None:
        token = nodes._gesture_token(gesture_router.window_key)
        if token is not None:
            nodes._end_gesture(gesture_window, token)
        nodes._dispatch_gesture(nodes.gesture_policy.Event("window_gone", window_id=gesture_window))
    lut_lane.host_owner = original_stack_owner

# The first drag on an explicitly created Grade coalesces pending settings
# without replacing its datablock or preparation source.
modal_runtime = nodes._preparation_runtime
original_modal_prepare = modal_runtime.prepare
local_drag_node = nodes.create_node(shader_tree)
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=local_drag_node)) == {"FINISHED"}
local_grade = local_drag_node.pg_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert local_grade is not None
assert all(abs(getattr(local_grade.pg_linear, name) - value) < 1e-6
           for name, value in nodes._LINEAR_DEFAULTS.items())
local_old_kernel = local_drag_node.node_tree
local_old_signature = local_old_kernel.get(nodes._KERNEL_SIGNATURE)
local_old_source = nodes._record_for(local_drag_node)["source"]
assert local_old_signature == nodes._kernel_signature(
    nodes.SHADER_TREE, local_grade.pg_linear, nodes._working_space()
)
local_first_started = threading.Event()
local_latest_started = threading.Event()
release_local_first = threading.Event()
release_local_latest = threading.Event()
local_preparation_exposures = []


async def hold_local_drag_preparation(payload):
    settings = payload.linear
    exposure = settings.exposure
    local_preparation_exposures.append(exposure)
    if exposure == 0.8125:
        local_first_started.set()
        assert release_local_first.wait(10), "local drag preparation was not released"
    if exposure == 0.90625:
        local_latest_started.set()
        assert release_local_latest.wait(10), "latest local drag was not released"
    return await original_modal_prepare(payload)


modal_runtime.prepare = hold_local_drag_preparation
local_window = 741
local_router = None
try:
    local_router, local_context = begin_ui_gesture(
        nodes, shader_tree, local_drag_node, local_window
    )
    assert nodes._record_for(local_drag_node)["state"].gesture_active
    local_grade.pg_linear.exposure = 0.8125
    assert local_drag_node.pg_grade == local_grade
    assert local_grade.pg_linear.exposure == 0.8125
    assert local_first_started.wait(10), (
        "first Grade drag preparation did not start; "
        f"record={nodes._node_stores.get(local_drag_node.as_pointer())!r}; "
        f"pending={modal_runtime.pending}; "
        f"sources={[(source.latest, source.dirty) for source in modal_runtime._sources.values()]!r}"
    )
    assert nodes._record_for(local_drag_node)["source"] is local_old_source

    for exposure in (0.75, 0.90625):
        local_grade.pg_linear.exposure = exposure
    nodes._preparation_tick()
    assert local_preparation_exposures == [0.8125], local_preparation_exposures
    local_record = nodes._record_for(local_drag_node)
    local_state = local_record["state"]
    assert local_state.gesture_active
    assert local_state.desired_signature != local_old_signature
    assert local_state.applied_signature == local_old_signature
    assert local_state.applied_quality == "full"
    assert local_state.error is None
    assert nodes.node_policy.output_mode(local_state) == "preview"
    assert local_drag_node.node_tree == local_old_kernel
    assert local_drag_node.node_tree.get(nodes._KERNEL_SIGNATURE) == local_old_signature
    assert local_drag_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    assert local_drag_node.get(nodes._NODE_ERROR) is None
    assert local_drag_node.get(nodes._NODE_PENDING) == (
        "status.showing_last_good"
    )
    assert local_drag_node.use_custom_color
    assert all(abs(actual - expected) < 1e-6 for actual, expected in zip(
        local_drag_node.color, (0.65, 0.32, 0.04)
    ))

    release_ui_gesture(nodes, local_router, local_context)
    local_router = None
    assert local_drag_node.pg_grade == local_grade
    assert local_grade.pg_linear.exposure == 0.90625
    local_state = nodes._record_for(local_drag_node)["state"]
    assert not local_state.gesture_active
    assert local_state.applied_signature == local_old_signature
    assert nodes.node_policy.output_mode(local_state) == "preview"
    assert local_drag_node.node_tree == local_old_kernel
    assert local_drag_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    assert local_drag_node.get(nodes._NODE_ERROR) is None
    assert local_drag_node.get(nodes._NODE_PENDING) == (
        "status.showing_last_good"
    )

    release_local_first.set()
    assert local_latest_started.wait(10), "latest local value was not prepared"
    nodes._preparation_tick()
    assert local_drag_node.node_tree == local_old_kernel
    assert local_drag_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    release_local_latest.set()
    nodes._drain_preparations()
finally:
    release_local_first.set()
    release_local_latest.set()
    if local_router is not None:
        token = nodes._gesture_token(local_router.window_key)
        if token is not None:
            if (nodes._gesture_phase(local_router.window_key) == "active"):
                nodes._end_gesture(local_window, token)
            else:
                nodes._end_gesture(local_window, token)
        nodes._dispatch_gesture(nodes.gesture_policy.Event("window_gone", window_id=local_window))
    modal_runtime.prepare = original_modal_prepare

local_final_signature = nodes._kernel_signature(
    nodes.SHADER_TREE, local_grade.pg_linear, nodes._working_space()
)
local_final_state = nodes._record_for(local_drag_node)["state"]
assert local_preparation_exposures == [0.8125, 0.90625], local_preparation_exposures
assert not local_final_state.gesture_active
assert local_final_state.applied_signature == local_final_signature
assert nodes.node_policy.output_allowed(local_final_state)
assert local_drag_node.node_tree.get(nodes._KERNEL_SIGNATURE) == local_final_signature
assert local_drag_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
assert not local_drag_node.get(nodes._NODE_ERROR)
assert not local_drag_node.get(nodes._NODE_PENDING)
assert not local_drag_node.use_custom_color

# A linked Grade drag activates all Shader/Compositor users and retains each
# current kernel until release invalidates the stale output.
linked_drag_grade = bpy.data.node_groups.new(
    "Modal Linked Drag Grade", nodes.PGGradeData.bl_idname
)
linked_drag_shader = nodes.create_node(shader_tree)
linked_drag_compositor = nodes.create_node(compositor_tree)
linked_drag_shader.pg_grade = linked_drag_grade
linked_drag_compositor.pg_grade = linked_drag_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
linked_drag_nodes = (linked_drag_shader, linked_drag_compositor)
linked_old_kernels = {node.as_pointer(): node.node_tree for node in linked_drag_nodes}
linked_old_signatures = {
    node.as_pointer(): node.node_tree.get(nodes._KERNEL_SIGNATURE)
    for node in linked_drag_nodes
}
linked_source = nodes._record_for(linked_drag_shader)["source"]
assert nodes._record_for(linked_drag_compositor)["source"] is linked_source
linked_started = threading.Event()
release_linked = threading.Event()
linked_exposures = []


async def hold_linked_drag_preparation(payload):
    settings = payload.linear
    linked_exposures.append(settings.exposure)
    linked_started.set()
    assert release_linked.wait(10), "linked drag preparation was not released"
    return await original_modal_prepare(payload)


modal_runtime.prepare = hold_linked_drag_preparation
linked_window = 742
linked_router = None
try:
    linked_router, linked_context = begin_ui_gesture(
        nodes, shader_tree, linked_drag_shader, linked_window
    )
    linked_drag_grade.pg_linear.exposure = 2.125
    assert linked_started.wait(10), "linked Grade preparation did not start"
    assert linked_exposures == [2.125], linked_exposures
    for node in linked_drag_nodes:
        record = nodes._record_for(node)
        state = record["state"]
        pointer = node.as_pointer()
        assert record["source"] is linked_source
        assert state.gesture_active
        assert state.applied_signature == linked_old_signatures[pointer]
        assert state.desired_signature != state.applied_signature
        assert state.error is None
        assert nodes.node_policy.output_mode(state) == "preview"
        assert node.node_tree == linked_old_kernels[pointer]
        assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
        assert node.get(nodes._NODE_ERROR) is None

    release_ui_gesture(nodes, linked_router, linked_context)
    linked_router = None
    for node in linked_drag_nodes:
        state = nodes._record_for(node)["state"]
        assert not state.gesture_active
        assert state.applied_signature == linked_old_signatures[node.as_pointer()]
        assert nodes.node_policy.output_mode(state) == "preview"
        assert node.node_tree == linked_old_kernels[node.as_pointer()]
        assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None

    release_linked.set()
    nodes._drain_preparations()
finally:
    release_linked.set()
    if linked_router is not None:
        token = nodes._gesture_token(linked_router.window_key)
        if token is not None:
            if (nodes._gesture_phase(linked_router.window_key) == "active"):
                nodes._end_gesture(linked_window, token)
            else:
                nodes._end_gesture(linked_window, token)
        nodes._dispatch_gesture(nodes.gesture_policy.Event("window_gone", window_id=linked_window))
    modal_runtime.prepare = original_modal_prepare

assert linked_exposures == [2.125], linked_exposures
for node in linked_drag_nodes:
    state = nodes._record_for(node)["state"]
    signature = nodes._kernel_signature(
        node.id_data.bl_idname, linked_drag_grade.pg_linear, nodes._working_space()
    )
    assert not state.gesture_active
    assert state.applied_signature == signature
    assert nodes.node_policy.output_allowed(state)
    assert node.node_tree.get(nodes._KERNEL_SIGNATURE) == signature
    assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    assert not node.get(nodes._NODE_ERROR)
    assert not node.get(nodes._NODE_PENDING)

# A click/direct numeric entry never enters gesture mode. Its final-only
# preparation begins when the sub-threshold click is released.
click_entry_node = nodes.create_node(shader_tree)
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=click_entry_node)) == {"FINISHED"}
click_grade = click_entry_node.pg_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
assert click_grade is not None
click_old_kernel = click_entry_node.node_tree
click_old_source = nodes._record_for(click_entry_node)["source"]
click_started = threading.Event()
release_click_preparation = threading.Event()
click_exposures = []


async def hold_click_preparation(payload):
    settings = payload.linear
    click_exposures.append(settings.exposure)
    click_started.set()
    assert release_click_preparation.wait(10), "click preparation was not released"
    return await original_modal_prepare(payload)


modal_runtime.prepare = hold_click_preparation
click_window = 743
click_router = None
try:
    click_router, click_context = begin_ui_gesture(
        nodes, shader_tree, click_entry_node, click_window, activate=False
    )
    click_grade.pg_linear.exposure = 3.25
    assert click_entry_node.pg_grade == click_grade
    assert nodes._record_for(click_entry_node)["source"] is click_old_source
    click_state = nodes._record_for(click_entry_node)["state"]
    assert not click_state.gesture_active
    assert click_state.applied_signature == click_state.desired_signature
    assert click_entry_node.node_tree == click_old_kernel
    assert click_exposures == []

    release_ui_gesture(nodes, click_router, click_context)
    click_router = None
    assert click_entry_node.pg_grade == click_grade
    assert click_started.wait(10), "direct value entry did not start final preparation"
    click_source = nodes._record_for(click_entry_node)["source"]
    assert click_source is click_old_source
    click_state = nodes._record_for(click_entry_node)["state"]
    assert not click_state.gesture_active
    assert click_state.applied_signature is not None
    assert nodes.node_policy.output_mode(click_state) == "preview"
    assert click_entry_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    assert click_entry_node.get(nodes._NODE_PENDING) == (
        "status.showing_last_good"
    )
    assert modal_runtime._sources[click_source].latest.progressive is False
    assert click_exposures == [3.25], click_exposures
    release_click_preparation.set()
    nodes._drain_preparations()
finally:
    release_click_preparation.set()
    if click_router is not None:
        token = nodes._gesture_token(click_router.window_key)
        if token is not None:
            nodes._end_gesture(click_window, token)
        nodes._dispatch_gesture(nodes.gesture_policy.Event("window_gone", window_id=click_window))
    modal_runtime.prepare = original_modal_prepare

click_final_state = nodes._record_for(click_entry_node)["state"]
click_final_signature = nodes._kernel_signature(
    nodes.SHADER_TREE, click_entry_node.pg_grade.pg_linear, nodes._working_space()
)
assert click_exposures == [3.25], click_exposures
assert not click_final_state.gesture_active
assert click_final_state.applied_signature == click_final_signature
assert nodes.node_policy.output_allowed(click_final_state)
assert click_entry_node.node_tree.get(nodes._KERNEL_SIGNATURE) == click_final_signature
assert click_entry_node.node_tree.get(nodes._KERNEL_QUALITY) == "full"
assert click_entry_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
assert not click_entry_node.get(nodes._NODE_ERROR)
assert not click_entry_node.get(nodes._NODE_PENDING)

# An invalid working space also blocks through the node policy effect before a
# later successful render reconciliation restores all nodes.
_start_timing_section("concurrency and failure recovery")
original_working_space = nodes._working_space


def fail_working_space():
    raise ValueError("simulated unsupported working space")


nodes._working_space = fail_working_space
workspace_failures = nodes._ensure_all_kernels()
assert not workspace_failures
assert all(node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
           and node.use_custom_color for node in shared_shader_nodes)
nodes._working_space = original_working_space
failures = nodes._ensure_all_kernels()
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert all(not node.use_custom_color and not node.get(nodes._NODE_ERROR)
           for node in shared_shader_nodes)

# Dragging keeps only one newest replacement. The running result can appear as
# a marked preview, and the successor starts without pumping the Blender timer.
stale_grade = bpy.data.node_groups.new("Stale Preparation Grade", nodes.PGGradeData.bl_idname)
stale_grade.pg_linear.exposure = 0.25
stale_node = nodes.create_node(shader_tree)
stale_node.pg_grade = stale_grade
stale_compositor_node = nodes.create_node(compositor_tree)
stale_compositor_node.pg_grade = stale_grade
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
stale_shader_graph = connect_grade_graph(shader_tree, stale_node)
stale_compositor_graph = connect_grade_graph(
    compositor_tree, stale_compositor_node, compositor=True
)
runtime = nodes._preparation_runtime
original_prepare = runtime.prepare
old_preparation_started = threading.Event()
release_old_preparation = threading.Event()
latest_preparation_started = threading.Event()
release_latest_preparation = threading.Event()
preparation_exposures = []


async def delay_preparation(payload):
    settings = payload.linear
    preparation_exposures.append(settings.exposure)
    if settings.exposure == 0.4375:
        old_preparation_started.set()
        assert release_old_preparation.wait(10), "old preparation was not released"
    if settings.exposure == 0.875:
        latest_preparation_started.set()
        assert release_latest_preparation.wait(10), "latest preparation was not released"
    return await original_prepare(payload)


runtime.prepare = delay_preparation
gesture_token = None
try:
    gesture_token = nodes._begin_gesture(732, stale_node)
    stale_grade.pg_linear.exposure = 0.4375
    nodes._refresh_nodes((stale_node,))
    assert old_preparation_started.wait(10), "old preparation did not start"
    for exposure in (0.625, 0.875):
        stale_grade.pg_linear.exposure = exposure
    release_old_preparation.set()
    assert latest_preparation_started.wait(10), "successor waited for Blender timer"
    nodes._preparation_tick()
    assert preparation_exposures == [0.4375, 0.875], preparation_exposures
    assert stale_node.node_tree.get(nodes._KERNEL_KIND) == nodes._KERNEL_SCHEMA
    assert stale_node.get(nodes._NODE_PENDING) == "status.showing_last_good"
    state = nodes._record_for(stale_node)["state"]
    assert state.applied_signature != state.desired_signature
    assert not nodes.node_policy.output_allowed(state)
    for preview_node in (stale_node, stale_compositor_node):
        assert preview_node.get(nodes._NODE_PENDING) == (
            "status.showing_last_good"
        )
        assert preview_node.use_custom_color
        assert all(abs(actual - expected) < 1e-6
                   for actual, expected in zip(preview_node.color, (0.65, 0.32, 0.04)))
    assert_grade_graph(stale_shader_graph)
    assert_grade_graph(stale_compositor_graph)
    preview = stale_node.node_tree
    nodes._preparation_tick()
    assert stale_node.node_tree == preview

    nodes._end_gesture(732, gesture_token)
    gesture_token = None
    for pending_node in (stale_node, stale_compositor_node):
        assert pending_node.node_tree.get(nodes._KERNEL_KIND) == nodes._KERNEL_SCHEMA
        assert pending_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
        assert pending_node.get(nodes._NODE_PENDING) == (
            "status.showing_last_good"
        )
    assert_grade_graph(stale_shader_graph)
    assert_grade_graph(stale_compositor_graph)

    release_latest_preparation.set()
    nodes._drain_preparations()
finally:
    release_old_preparation.set()
    release_latest_preparation.set()
    if gesture_token is not None:
        nodes._end_gesture(732, gesture_token)
    runtime.prepare = original_prepare
latest_signature = nodes._kernel_signature(
    nodes.SHADER_TREE, stale_grade.pg_linear, nodes._working_space()
)
assert stale_node.node_tree.get(nodes._KERNEL_SIGNATURE) == latest_signature
assert stale_compositor_node.node_tree.get(nodes._KERNEL_SIGNATURE) == (
    nodes._kernel_signature(nodes.COMPOSITOR_TREE, stale_grade.pg_linear,
                            nodes._working_space())
)
assert_grade_graph(stale_shader_graph)
assert_grade_graph(stale_compositor_graph)
assert not stale_node.get(nodes._NODE_ERROR)
assert not stale_node.get(nodes._NODE_PENDING)
assert not stale_node.use_custom_color
assert not stale_compositor_node.get(nodes._NODE_ERROR)
assert not stale_compositor_node.get(nodes._NODE_PENDING)
assert not stale_compositor_node.use_custom_color

# A failed kernel replacement restores the original group, external links,
# and socket defaults after the candidate was temporarily selected.
rollback_kernel = stale_node.node_tree
candidate_kernel = rollback_kernel.copy()
restore_calls = []
original_restore_snapshot = nodes._restore_kernel_snapshot


def fail_once_after_candidate_restore(node, kernel, snapshot):
    original_restore_snapshot(node, kernel, snapshot)
    restore_calls.append(kernel)
    if node == stale_node and kernel == candidate_kernel and len(restore_calls) == 1:
        raise RuntimeError("simulated post-install verification failure")


nodes._restore_kernel_snapshot = fail_once_after_candidate_restore
try:
    try:
        nodes._replace_node_kernel(stale_node, candidate_kernel)
    except RuntimeError as error:
        assert "simulated post-install verification failure" in str(error)
    else:
        raise AssertionError("a failed candidate replacement must be reported")
finally:
    nodes._restore_kernel_snapshot = original_restore_snapshot
assert restore_calls == [candidate_kernel, rollback_kernel]
assert stale_node.node_tree == rollback_kernel
assert_grade_graph(stale_shader_graph)
assert_grade_graph(stale_compositor_graph)
if candidate_kernel.users == 0:
    bpy.data.node_groups.remove(candidate_kernel, do_unlink=True)

# An old source completion cannot become a preview after Grade reassignment.
retired_started = threading.Event()
release_retired = threading.Event()
retired_grade = bpy.data.node_groups.new("Retired Preparation Grade", nodes.PGGradeData.bl_idname)
retired_grade.pg_linear.exposure = 0.3125
replacement_grade = bpy.data.node_groups.new("Replacement Grade", nodes.PGGradeData.bl_idname)
replacement_grade.pg_linear.exposure = 0.9375


async def delay_retired(payload):
    settings = payload.linear
    if settings.exposure == 0.3125:
        retired_started.set()
        assert release_retired.wait(10)
    return await original_prepare(payload)


runtime.prepare = delay_retired
try:
    stale_node.pg_grade = retired_grade
    assert retired_started.wait(10)
    retired_source = nodes._record_for(stale_node)["source"]
    stale_node.pg_grade = replacement_grade
    assert nodes._record_for(stale_node)["source"] is not retired_source
    replacement_pending_tree = stale_node.node_tree
    replacement_pending_state = nodes._record_for(stale_node)["state"]
    retired_result = object()
    assert not nodes._handle_preparation_result(
        retired_source, "retired", retired_result, None,
    )
    assert stale_node.node_tree == replacement_pending_tree
    assert nodes._record_for(stale_node)["state"] == replacement_pending_state
    assert stale_node.node_tree.get(nodes._ERROR_KERNEL_KIND) is None
    release_retired.set()
    failures = nodes._drain_preparations()
    assert not failures, failures
finally:
    release_retired.set()
    runtime.prepare = original_prepare
assert stale_node.node_tree.get(nodes._KERNEL_SIGNATURE) == nodes._kernel_signature(
    nodes.SHADER_TREE, replacement_grade.pg_linear, active_space)

# A deleted node's pending receipt cannot publish into a same-name replacement,
# even when both nodes requested the exact same settings and signatures.
pending_deleted_node = nodes.create_node(shader_tree)
pending_deleted_name = pending_deleted_node.name
pending_deleted_record = nodes._record_for(pending_deleted_node)
pending_deleted_source = pending_deleted_record["source"]
pending_deleted_signature = pending_deleted_record["state"].desired_preparation_signature
assert not nodes.node_policy.output_allowed(pending_deleted_record["state"])
pending_deleted_result = object()
shader_tree.nodes.remove(pending_deleted_node)
del pending_deleted_node, pending_deleted_record
replacement_node = nodes.create_node(shader_tree)
assert replacement_node.name == pending_deleted_name
replacement_record = nodes._record_for(replacement_node)
assert replacement_record["source"] is not pending_deleted_source
replacement_pending_state = replacement_record["state"]
replacement_pending_tree = replacement_node.node_tree
assert not nodes._handle_preparation_result(
    pending_deleted_source, pending_deleted_signature, pending_deleted_result, None
)
assert nodes._record_for(replacement_node)["state"] == replacement_pending_state
assert replacement_node.node_tree == replacement_pending_tree
failures = nodes._refresh_nodes((replacement_node,))
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert_grade_current(replacement_node)
shader_tree.nodes.remove(replacement_node)
del replacement_node, replacement_record, replacement_pending_tree, pending_deleted_result

# A worker failure is visible and the next reconciliation can recover it.
worker_failure_grade = bpy.data.node_groups.new(
    "Worker Failure Grade", nodes.PGGradeData.bl_idname
)
worker_failure_grade.pg_linear.exposure = 1.25
worker_failure_node = nodes.create_node(shader_tree)
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations()
assert not failures, failures
original_prepare = runtime.prepare
failure_calls = []


async def fail_first_preparation(payload):
    settings = payload.linear
    if settings.exposure == 1.25:
        failure_calls.append(threading.get_ident())
        if len(failure_calls) == 1:
            raise RuntimeError("simulated preparation worker failure")
    return await original_prepare(payload)


runtime.prepare = fail_first_preparation
try:
    worker_failure_node.pg_grade = worker_failure_grade
    nodes._drain_preparations()
    assert worker_failure_node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
    assert worker_failure_node.get(nodes._NODE_ERROR)
    failures = nodes._refresh_nodes((worker_failure_node,))
    assert not failures, failures
    failures = nodes._drain_preparations()
    assert not failures, failures
finally:
    runtime.prepare = original_prepare
assert len(failure_calls) == 2, failure_calls
assert all(thread != main_thread for thread in failure_calls)
assert worker_failure_node.node_tree.get(nodes._KERNEL_SIGNATURE) == nodes._kernel_signature(
    nodes.SHADER_TREE, worker_failure_grade.pg_linear, nodes._working_space()
)
assert not worker_failure_node.get(nodes._NODE_ERROR)

# A failed render barrier cannot leave a pending preview in the render graph.
original_wait = runtime.wait
shared_grade.pg_linear.exposure = 2.625
assert shared_shader_nodes[0].get(nodes._NODE_PENDING)


def fail_barrier(_sources=None):
    raise RuntimeError("simulated render barrier failure")


runtime.wait = fail_barrier
try:
    failures = nodes._ensure_all_kernels()
    assert not failures, failures
    nodes._drain_preparations()
    assert all(node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
               and node.get(nodes._NODE_ERROR) for node in shared_shader_nodes)
finally:
    runtime.wait = original_wait
failures = nodes._ensure_all_kernels()
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert all(not node.get(nodes._NODE_PENDING) and not node.get(nodes._NODE_ERROR)
           for node in shared_shader_nodes)

# A replacement kernel with no successful node assignment is retired.
failed_assignment_grade = bpy.data.node_groups.new(
    "Failed Kernel Assignment Grade", nodes.PGGradeData.bl_idname
)
failed_assignment_grade.pg_linear.exposure = 4.125


class AssignmentFailureNode:
    bl_idname = "PGShaderGrade"
    id_data = SimpleNamespace(bl_idname=nodes.SHADER_TREE, links=[], nodes=[])

    def __init__(self):
        self._pointer = id(self)
        self._node_tree = None
        self._properties = {}
        self.use_custom_color = False
        self.color = (0.0, 0.0, 0.0)
        self.pg_grade = failed_assignment_grade
        self.inputs = []

    def as_pointer(self):
        return self._pointer

    @property
    def node_tree(self):
        return self._node_tree

    @node_tree.setter
    def node_tree(self, value):
        if value is not None and value.get(nodes._KERNEL_KIND) == nodes._KERNEL_SCHEMA:
            raise RuntimeError("simulated node-tree assignment failure")
        self._node_tree = value

    def __contains__(self, name):
        return name in self._properties

    def __getitem__(self, name):
        return self._properties[name]

    def __setitem__(self, name, value):
        self._properties[name] = value

    def __delitem__(self, name):
        del self._properties[name]

    def get(self, name, default=None):
        return self._properties.get(name, default)


failure_node = AssignmentFailureNode()
original_is_grade_node = nodes._is_grade_node
original_settings_for_node = nodes._settings_for_node
original_kernel_builder = nodes._kernel
candidate_names = []


def recognize_failure_node(node):
    return node is failure_node or original_is_grade_node(node)


def settings_for_failure_node(node, working_space=None):
    if node is failure_node:
        return nodes._grade_settings(failed_assignment_grade, working_space or active_space)
    return original_settings_for_node(node, working_space)


def capture_candidate(*args, **kwargs):
    candidate = original_kernel_builder(*args, **kwargs)
    if candidate.get(nodes._KERNEL_KIND) == nodes._KERNEL_SCHEMA:
        candidate_names.append(candidate.name)
    return candidate


nodes._is_grade_node = recognize_failure_node
nodes._settings_for_node = settings_for_failure_node
nodes._kernel = capture_candidate
try:
    assignment_failures = nodes._refresh_nodes((failure_node,), active_space)
    assert not assignment_failures
    nodes._drain_preparations()
    assert failure_node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
    assert failure_node.use_custom_color
    assert all(abs(actual - expected) < 1e-6
               for actual, expected in zip(failure_node.color, (0.65, 0.04, 0.04)))
    assert candidate_names
    assert all(bpy.data.node_groups.get(name) is None for name in candidate_names)
finally:
    nodes._is_grade_node = original_is_grade_node
    nodes._settings_for_node = original_settings_for_node
    nodes._kernel = original_kernel_builder
bpy.data.node_groups.remove(failed_assignment_grade)

# The composed consumer still attempts the error-kernel operation if applying
# the node presentation operation raises.
blocked_state, blocked_effect = nodes.node_policy.step(
    nodes.node_policy.new(),
    nodes.node_policy.Event("request", "effect-test"),
)
assert blocked_state.desired_signature is not None
blocked_state, blocked_effect = nodes.node_policy.step(
    blocked_state,
    nodes.node_policy.Event(
        "preparation_result", "effect-test", "simulated preparation failure"
    ),
)
assert blocked_effect.output_mode == "error"
original_presentation = nodes._apply_output_presentation
original_output_kernel = nodes._apply_output_kernel
kernel_effect_calls = []


def fail_presentation(*_args):
    raise RuntimeError("simulated presentation failure")


def record_kernel_operation(node, mode):
    kernel_effect_calls.append(mode)
    return original_output_kernel(node, mode)


nodes._apply_output_presentation = fail_presentation
nodes._apply_output_kernel = record_kernel_operation
try:
    try:
        nodes._apply_output_effect(failure_node, blocked_effect)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a failed output effect must be reported")
finally:
    nodes._apply_output_presentation = original_presentation
    nodes._apply_output_kernel = original_output_kernel
assert kernel_effect_calls == ["error"]
assert failure_node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA

presentation_effect_calls = []
kernel_attempts = []


def record_presentation(node, allowed, error):
    presentation_effect_calls.append(allowed)
    return original_presentation(node, allowed, error)


def fail_output_kernel(*_args):
    kernel_attempts.append(False)
    raise RuntimeError("simulated error-kernel failure")


nodes._apply_output_presentation = record_presentation
nodes._apply_output_kernel = fail_output_kernel
try:
    try:
        nodes._apply_output_effect(failure_node, blocked_effect)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a failed error-kernel operation must be reported")
finally:
    nodes._apply_output_presentation = original_presentation
    nodes._apply_output_kernel = original_output_kernel
assert presentation_effect_calls == ["error"]
assert kernel_attempts == [False]
assert failure_node.use_custom_color
assert failure_node.get(nodes._NODE_ERROR)
nodes._forget_node(failure_node)

# Grade creation precedes editing. Undoing completed gestures restores each
# setting value independently and leaves the explicitly created Grade linked.
_start_timing_section("undo and teardown")
bpy.context.preferences.edit.use_global_undo = True
shader_tree_name_for_cleanup = shader_tree.name
compositor_tree_name_for_cleanup = compositor_tree.name
material_name_for_cleanup = material.name

# Native undo remaps the containing material ID used by local ownership.
# Reacquire nodes after undo/redo instead of retaining invalid RNA wrappers.
assert_local_grade_resources(local_grade_identities)
assert bpy.ops.ed.undo_push(message="Local material Grade baseline") == {"FINISHED"}
local_undo_node = bpy.data.materials[first_material_name].node_tree.nodes[first_node_name]
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=local_undo_node)) == {"FINISHED"}
local_undo_grade_name = local_undo_node.pg_grade.name
reconcile_for_render(bpy.context.scene)
failures = nodes._drain_preparations_in_scope((local_undo_node,))
assert not failures, failures
assert_grade_current(local_undo_node)
assert bpy.ops.ed.undo_push(message="Create material Grade datablock") == {"FINISHED"}
del local_undo_node
assert bpy.ops.ed.undo.poll()
assert bpy.ops.ed.undo() == {"FINISHED"}
assert bpy.app.timers.is_registered(nodes._undo_redo_reconcile_tick)
nodes._undo_redo_reconcile_tick()
nodes._drain_preparations()
assert_local_grade_resources(local_grade_identities)
assert bpy.ops.ed.redo.poll()
assert bpy.ops.ed.redo() == {"FINISHED"}
assert bpy.app.timers.is_registered(nodes._undo_redo_reconcile_tick)
nodes._undo_redo_reconcile_tick()
nodes._drain_preparations()
local_undo_node = bpy.data.materials[first_material_name].node_tree.nodes[first_node_name]
assert local_undo_node.pg_grade.name == local_undo_grade_name
assert_grade_current(local_undo_node)
assert local_undo_node.node_tree.get(nodes.PARAMETER_OWNER) == local_undo_node.pg_grade
assert nodes.PG_OT_unlink_grade.execute(
    None, SimpleNamespace(pg_node=local_undo_node)) == {"FINISHED"}
del local_undo_node
failures = nodes._ensure_all_kernels()
assert not failures, failures
failures = nodes._drain_preparations()
assert not failures, failures
assert_local_grade_resources(local_grade_identities)

undo_tree = bpy.data.node_groups.new("Gesture Undo Regression", nodes.SHADER_TREE)
undo_tree.use_fake_user = True
undo_tree_name = undo_tree.name
undo_node = nodes.create_node(undo_tree)
undo_node_name = undo_node.name
assert nodes.PG_OT_new_grade.execute(
    None, SimpleNamespace(pg_node=undo_node)) == {"FINISHED"}
undo_grade_name = undo_node.pg_grade.name
assert bpy.ops.ed.undo_push(message="Gesture undo baseline") == {"FINISHED"}


def commit_test_gesture(node, window_key, exposure):
    nodes._arm_gesture(window_key, node, (0, 0))
    token = nodes._gesture_token(window_key)
    nodes._activate_gesture(window_key, token)
    assert node.pg_grade is not None
    settings = node.pg_grade.pg_linear
    settings.exposure = exposure
    nodes._end_gesture(window_key, token)
    del settings


def reconcile_after_test_undo(node_name):
    node = bpy.data.node_groups[undo_tree_name].nodes[node_name]
    pointer = node.as_pointer()
    assert pointer not in nodes._node_stores
    del node
    assert bpy.app.timers.is_registered(nodes._undo_redo_reconcile_tick)
    nodes._undo_redo_reconcile_tick()
    nodes._drain_preparations()
    node = bpy.data.node_groups[undo_tree_name].nodes[node_name]
    record = nodes._node_stores[node.as_pointer()]
    signature = nodes._kernel_signature(
        nodes.SHADER_TREE, nodes._settings_for_node(node), nodes._working_space()
    )
    assert record["state"].applied_signature == signature
    assert nodes.node_policy.output_allowed(record["state"])
    assert node.node_tree.get(nodes._KERNEL_SIGNATURE) == signature
    del node


commit_test_gesture(undo_node, 9001, 0.5)
assert undo_node.pg_grade is not None
assert bpy.ops.ed.undo_push(message="First Grade gesture") == {"FINISHED"}
del undo_node, undo_tree
assert bpy.ops.ed.undo.poll()
assert bpy.ops.ed.undo() == {"FINISHED"}
undo_node = bpy.data.node_groups[undo_tree_name].nodes[undo_node_name]
assert undo_node.pg_grade is not None
assert undo_node.pg_grade.name == undo_grade_name
assert abs(undo_node.pg_grade.pg_linear.exposure) < 1e-6
del undo_node
reconcile_after_test_undo(undo_node_name)

undo_node = bpy.data.node_groups[undo_tree_name].nodes[undo_node_name]
commit_test_gesture(undo_node, 9002, 0.625)
assert undo_node.pg_grade is not None
first_grade_name = undo_node.pg_grade.name
assert bpy.ops.ed.undo_push(message="First of two Grade gestures") == {"FINISHED"}
undo_node = bpy.data.node_groups[undo_tree_name].nodes[undo_node_name]
commit_test_gesture(undo_node, 9003, 1.0)
assert abs(undo_node.pg_grade.pg_linear.exposure - 1.0) < 1e-6
assert bpy.ops.ed.undo_push(message="Second of two Grade gestures") == {"FINISHED"}
del undo_node
assert bpy.ops.ed.undo() == {"FINISHED"}
undo_node = bpy.data.node_groups[undo_tree_name].nodes[undo_node_name]
assert undo_node.pg_grade is not None
assert undo_node.pg_grade.name == first_grade_name
assert abs(undo_node.pg_grade.pg_linear.exposure - 0.625) < 1e-6
del undo_node
reconcile_after_test_undo(undo_node_name)
assert bpy.ops.ed.undo() == {"FINISHED"}
undo_node = bpy.data.node_groups[undo_tree_name].nodes[undo_node_name]
assert undo_node.pg_grade is not None
assert undo_node.pg_grade.name == undo_grade_name
assert abs(undo_node.pg_grade.pg_linear.exposure) < 1e-6
del undo_node
reconcile_after_test_undo(undo_node_name)
undo_node = bpy.data.node_groups[undo_tree_name].nodes[undo_node_name]
undo_tree = bpy.data.node_groups[undo_tree_name]
nodes._forget_node(undo_node)
undo_tree.nodes.remove(undo_node)
bpy.data.node_groups.remove(undo_tree)
del undo_node, undo_tree

shader_tree = bpy.data.node_groups[shader_tree_name_for_cleanup]
compositor_tree = bpy.data.node_groups[compositor_tree_name_for_cleanup]
material = bpy.data.materials[material_name_for_cleanup]

for tree in (shader_tree, compositor_tree):
    for node in tuple(tree.nodes):
        if node.bl_idname in (*nodes.GRADE_NODE_TYPES, *nodes.STACK_NODE_TYPES.values()):
            tree.nodes.remove(node)
for node in tuple(material.node_tree.nodes):
    if node.bl_idname in nodes.GRADE_NODE_TYPES:
        material.node_tree.nodes.remove(node)
for collection, owner_name in dict.fromkeys(
        (collection, owner_name) for collection, owner_name, _node_name
        in local_grade_identities):
    owner = getattr(bpy.data, collection)[owner_name]
    for node in tuple(owner.node_tree.nodes):
        if node.bl_idname in nodes.GRADE_NODE_TYPES:
            owner.node_tree.nodes.remove(node)
    getattr(bpy.data, collection).remove(owner)

for group in tuple(bpy.data.node_groups):
    if (group.get("_perceptual_grade_grade_kernel")
            or group.get("_perceptual_grade_stack_kernel")) and group.users == 0:
        bpy.data.node_groups.remove(group)
    elif group.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA and group.users == 0:
        bpy.data.node_groups.remove(group)
    elif group.bl_idname == nodes.PGGradeData.bl_idname and group.users == 0:
        bpy.data.node_groups.remove(group)
bpy.data.node_groups.remove(shader_tree)
bpy.data.node_groups.remove(compositor_tree)
bpy.data.materials.remove(material)

addon_utils.disable(extension.__name__, default_set=False)
assert not localization._registered
assert not nodes.PGShaderGrade.is_registered
assert not nodes.PGCompositorGrade.is_registered
assert not nodes.PGShaderGradePerNode.is_registered
assert not nodes.PGCompositorGradePerNode.is_registered
assert not nodes.PGGradeData.is_registered
assert not nodes.PGLinearSettings.is_registered
assert not nodes.PGToneSettings.is_registered
assert not nodes.PG_OT_add_per_node_grade.is_registered
assert not nodes.PG_PT_linear.is_registered
assert not bpy.app.timers.is_registered(nodes._startup_reconcile_tick)
for menu_type in nodes.MENU_TYPES:
    assert nodes.draw_add_menu not in menu_type.draw._draw_funcs
for handler, callback in (
    (bpy.app.handlers.load_post, nodes._load_post),
    (bpy.app.handlers.undo_pre, nodes._undo_redo_pre),
    (bpy.app.handlers.redo_pre, nodes._undo_redo_pre),
    (bpy.app.handlers.undo_post, nodes._undo_redo_post),
    (bpy.app.handlers.redo_post, nodes._undo_redo_post),
    (bpy.app.handlers.render_pre, nodes._render_pre),
    (bpy.app.handlers.depsgraph_update_post, nodes._depsgraph_update_post),
):
    assert callback not in handler, (
        callback.__name__, id(callback), [(id(item), repr(item)) for item in handler]
    )

scans_before_reenable = len(initial_scans)
enable_errors = []
enabled_extension = addon_utils.enable(
    extension.__name__, default_set=False, handle_error=enable_errors.append
)
assert enabled_extension is extension and not enable_errors, enable_errors
assert localization._registered
assert len(initial_scans) == scans_before_reenable
assert bpy.app.timers.is_registered(nodes._startup_reconcile_tick)
with restricted.RestrictBlend():
    assert nodes._startup_reconcile_tick() == 0.1
assert len(initial_scans) == scans_before_reenable
addon_utils.disable(extension.__name__, default_set=False)
assert not localization._registered
assert not bpy.app.timers.is_registered(nodes._startup_reconcile_tick)
nodes._ensure_all_kernels = original_ensure_all_kernels

_complete_timing_report()
