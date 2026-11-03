"""Linear Grade nodes and their shared settings UI."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import hashlib
import json
from uuid import uuid4

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .kernel import (
    LinearSettings,
    prepare_linear,
    project_source_white_component,
)
from .kernel.graph import Graph
from .kernel.lut import (
    append_lut_lookup,
    bake_linear_stack,
    bake_linear_stack_progressive,
)
from .kernel.settings import D65, SPACES
from .policy import readiness as kernel_readiness
from .policy import preparation as preparation_policy
from .policy import stack as stack_policy
from .preparation_runtime import PreparationRuntime


SHADER_TREE = "ShaderNodeTree"
COMPOSITOR_TREE = "CompositorNodeTree"
NODE_TYPES = {
    SHADER_TREE: "PGShaderGrade",
    COMPOSITOR_TREE: "PGCompositorGrade",
}
STACK_NODE_TYPES = {
    SHADER_TREE: "PGShaderGradeStack",
    COMPOSITOR_TREE: "PGCompositorGradeStack",
}
MENU_TYPES = (
    bpy.types.NODE_MT_category_shader_color,
    bpy.types.NODE_MT_category_compositor_color,
)

_syncing = set()
_registered_classes = []
_registered_menus = []
_registered_handlers = []
_reconciling = False
_last_working_space = None
_node_stores = {}
_stack_stores = {}
_preparation_runtime = None
_preparation_sources = {}
_gesture_routers = {}
_gesture_targets = {}
_armed_gestures = {}
_active_gestures = {}
_gesture_settings = {}
_KERNEL_SCHEMA = 1
_KERNEL_KIND = "_perceptual_grade_kernel"
_KERNEL_SIGNATURE = "_perceptual_grade_signature"
_KERNEL_QUALITY = "_perceptual_grade_quality"
_IDENTITY_KERNEL_KIND = "_perceptual_grade_identity_kernel"
_ERROR_KERNEL_KIND = "_perceptual_grade_error_kernel"
_NODE_ERROR = "_perceptual_grade_kernel_error"
_NODE_PENDING = "_perceptual_grade_kernel_pending"
_LINEAR_FIELDS = (
    "exposure",
    "source_x",
    "source_y",
    "cr_balance",
    "yb_balance",
    "cr_spread",
    "yb_spread",
    "cr_heading",
    "yb_heading",
)
_LINEAR_DEFAULTS = {
    "exposure": 0.0,
    "source_x": D65[0],
    "source_y": D65[1],
    "cr_balance": 0.0,
    "yb_balance": 0.0,
    "cr_spread": 0.0,
    "yb_spread": 0.0,
    "cr_heading": 0.0,
    "yb_heading": 0.0,
}


def _is_grade_node(node):
    return getattr(node, "bl_idname", None) in NODE_TYPES.values()


def _is_stack_node(node):
    return getattr(node, "bl_idname", None) in STACK_NODE_TYPES.values()


def _is_output_node(node):
    return _is_grade_node(node) or _is_stack_node(node)


def _holder(settings):
    try:
        owner = settings.id_data
        if getattr(owner, "bl_idname", None) == PGGradeData.bl_idname:
            return owner
        if _is_grade_node(owner):
            return owner
        pointer = settings.as_pointer()
        for node in getattr(owner, "nodes", ()):
            if _is_grade_node(node) and node.pg_linear.as_pointer() == pointer:
                return node
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None
    return None


@contextmanager
def _suspend(settings):
    pointer = settings.as_pointer()
    _syncing.add(pointer)
    try:
        yield
    finally:
        _syncing.discard(pointer)


def _copy_linear(source, target):
    with _suspend(target):
        for name in _LINEAR_FIELDS:
            setattr(target, name, getattr(source, name))


def _reset_linear(settings):
    with _suspend(settings):
        for name in _LINEAR_FIELDS:
            if settings.is_property_set(name):
                settings.property_unset(name)


def _make_grade(source=None):
    grade = bpy.data.node_groups.new("Grade", PGGradeData.bl_idname)
    try:
        if source is not None:
            _copy_linear(source, grade.pg_linear)
    except BaseException:
        if grade.users == 0:
            bpy.data.node_groups.remove(grade)
        raise
    return grade


def _working_space():
    colorspace = getattr(bpy.data, "colorspace", None)
    if colorspace is None:
        return "Linear Rec.709"
    interop = getattr(colorspace, "working_space_interop_id", "")
    names = {
        "lin_rec709_scene": "Linear Rec.709",
        "lin_rec2020_scene": "Linear Rec.2020",
        "lin_ap1_scene": "ACEScg",
    }
    name = names.get(interop, getattr(colorspace, "working_space", "Linear Rec.709"))
    if name not in SPACES:
        raise ValueError("Unsupported Blender working color space: " + str(name))
    return name


def _linear_settings(settings):
    return LinearSettings(
        exposure=settings.exposure,
        source_xy=(settings.source_x, settings.source_y),
        balance=(-settings.cr_balance, -settings.yb_balance),
        spread=(settings.cr_spread, settings.yb_spread),
        heading=(settings.cr_heading, settings.yb_heading),
    )


def _kernel_signature(tree_type, settings, working_space):
    values = tuple(float(getattr(settings, name)).hex() for name in _LINEAR_FIELDS)
    return _signature(tree_type, values, working_space)


def _signature(kind, values, working_space):
    payload = json.dumps(
        (_KERNEL_SCHEMA, kind, working_space, values),
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_values(settings):
    return tuple(float(value).hex() for value in (
        settings.exposure, *settings.source_xy,
        -settings.balance[0], -settings.balance[1],
        *settings.spread, *settings.heading,
    ))


def _preparation_signature(settings, working_space):
    return _signature("linear-preparation", _snapshot_values(settings), working_space)


def _kernel(tree_type, prepared, working_space, signature):
    if tree_type not in (SHADER_TREE, COMPOSITOR_TREE):
        raise ValueError("Grade nodes require a Shader or Compositor tree")

    tree = bpy.data.node_groups.new("Perceptual Grade Linear", tree_type)
    try:
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor"
        )
        color_input.default_value = (0.0, 0.0, 0.0, 1.0)
        if tree_type == SHADER_TREE:
            alpha_input = tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            alpha_input.default_value = 1.0

        color_output = tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor"
        )
        alpha_output = None
        if tree_type == SHADER_TREE:
            alpha_output = tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat"
            )

        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        graph = Graph(tree, prepared)
        transformed = graph.matrix(source.outputs[color_input.name], prepared.rgb_matrix)

        if tree_type == SHADER_TREE:
            graph.connect(transformed, output.inputs[color_output.name])
            graph.connect(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
        else:
            separate = graph.node("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            graph.connect(source.outputs[color_input.name], separate.inputs["Image"])
            restore = graph.node("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            graph.connect(transformed, restore.inputs["Image"])
            graph.connect(separate.outputs["Alpha"], restore.inputs["Alpha"])
            graph.connect(restore.outputs["Image"], output.inputs[color_output.name])
        tree[_KERNEL_KIND] = _KERNEL_SCHEMA
        tree["_perceptual_grade_linear_kernel"] = True
        tree[_KERNEL_SIGNATURE] = signature
        tree[_KERNEL_QUALITY] = "full"
        tree["_perceptual_grade_tree_type"] = tree_type
        tree["_perceptual_grade_working_space"] = working_space
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        raise
    return tree


@dataclass(frozen=True)
class _PreparedStack:
    settings: tuple
    space: str
    cube: object


def _prepare_stack(settings, working_space, on_preview=None):
    matrices = tuple(prepare_linear(item, working_space).rgb_matrix for item in settings)
    if on_preview is None:
        cube = bake_linear_stack(matrices, working_space)
    else:
        def publish_preview(cube):
            on_preview(_PreparedStack(settings, working_space, cube))

        cube = bake_linear_stack_progressive(
            matrices, working_space, publish_preview
        )
    return _PreparedStack(
        settings, working_space, cube,
    )


def _stack_signature(settings, working_space):
    values = tuple(_snapshot_values(item) for item in settings)
    return _signature("forward-stack", values, working_space)


def _stack_kernel(tree_type, prepared, signature, quality):
    if tree_type not in (SHADER_TREE, COMPOSITOR_TREE):
        raise ValueError("Grade Stack nodes require a Shader or Compositor tree")
    tree = bpy.data.node_groups.new("Perceptual Grade Stack", tree_type)
    graph = Graph(tree, None)
    try:
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor"
        )
        color_output = tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor"
        )
        alpha_input = alpha_output = None
        if tree_type == SHADER_TREE:
            alpha_input = tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            alpha_input.default_value = 1.0
            alpha_output = tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat"
            )

        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        transformed = append_lut_lookup(
            graph, prepared.cube, source.outputs[color_input.name]
        )
        if tree_type == SHADER_TREE:
            graph.connect(transformed, output.inputs[color_output.name])
            graph.connect(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
        else:
            separate = graph.node("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            graph.connect(source.outputs[color_input.name], separate.inputs["Image"])
            restore = graph.node("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            graph.connect(transformed, restore.inputs["Image"])
            graph.connect(separate.outputs["Alpha"], restore.inputs["Alpha"])
            graph.connect(restore.outputs["Image"], output.inputs[color_output.name])

        tree[_KERNEL_KIND] = _KERNEL_SCHEMA
        tree["_perceptual_grade_stack_kernel"] = True
        tree[_KERNEL_SIGNATURE] = signature
        tree[_KERNEL_QUALITY] = quality
        tree["_perceptual_grade_tree_type"] = tree_type
        tree["_perceptual_grade_working_space"] = prepared.space
        tree["_perceptual_grade_lut_signature"] = prepared.cube.signature
        for image in graph.images:
            image["_perceptual_grade_stack_image"] = signature
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for image in graph.images:
            if image.users == 0:
                bpy.data.images.remove(image)
        raise
    return tree


def _error_kernel(tree_type):
    if tree_type not in (SHADER_TREE, COMPOSITOR_TREE):
        raise ValueError("Grade nodes require a Shader or Compositor tree")
    name = "Perceptual Grade Error " + ("Shader" if tree_type == SHADER_TREE else "Compositor")
    tree = bpy.data.node_groups.get(name)
    if tree is not None and tree.get(_ERROR_KERNEL_KIND) == _KERNEL_SCHEMA:
        return tree

    tree = bpy.data.node_groups.new(name, tree_type)
    try:
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor"
        )
        color_output = tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor"
        )
        if tree_type == SHADER_TREE:
            alpha_input = tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            alpha_input.default_value = 1.0
            alpha_output = tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat"
            )

        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        if tree_type == SHADER_TREE:
            output.inputs[color_output.name].default_value = (1.0, 0.0, 1.0, 1.0)
            tree.links.new(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
        else:
            separate = tree.nodes.new("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            tree.links.new(source.outputs[color_input.name], separate.inputs["Image"])
            magenta = tree.nodes.new("CompositorNodeRGB")
            magenta.outputs[0].default_value = (1.0, 0.0, 1.0, 1.0)
            restore = tree.nodes.new("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            tree.links.new(magenta.outputs[0], restore.inputs["Image"])
            tree.links.new(separate.outputs["Alpha"], restore.inputs["Alpha"])
            tree.links.new(restore.outputs["Image"], output.inputs[color_output.name])
        tree[_ERROR_KERNEL_KIND] = _KERNEL_SCHEMA
        tree["_perceptual_grade_tree_type"] = tree_type
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        raise
    return tree


def _identity_kernel(tree_type):
    if tree_type not in (SHADER_TREE, COMPOSITOR_TREE):
        raise ValueError("Grade nodes require a Shader or Compositor tree")
    name = "Perceptual Grade Pending " + (
        "Shader" if tree_type == SHADER_TREE else "Compositor"
    )
    tree = bpy.data.node_groups.get(name)
    if (tree is not None
            and tree.get(_IDENTITY_KERNEL_KIND) == _KERNEL_SCHEMA
            and tree.get("_perceptual_grade_tree_type") == tree_type):
        return tree

    tree = bpy.data.node_groups.new(name, tree_type)
    try:
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor"
        )
        color_output = tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor"
        )
        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        tree.links.new(source.outputs[color_input.name], output.inputs[color_output.name])
        if tree_type == SHADER_TREE:
            alpha_input = tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat"
            )
            alpha_input.default_value = 1.0
            alpha_output = tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat"
            )
            tree.links.new(source.outputs[alpha_input.name], output.inputs[alpha_output.name])
        tree[_IDENTITY_KERNEL_KIND] = _KERNEL_SCHEMA
        tree["_perceptual_grade_tree_type"] = tree_type
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        raise
    return tree


def _settings_for_node(node):
    if _is_stack_node(node):
        return tuple(
            _linear_settings(entry.grade.pg_linear)
            for entry in node.pg_stack_entries
            if entry.enabled and entry.grade is not None
        )
    return node.pg_grade.pg_linear if node.pg_grade is not None else node.pg_linear


def _kernel_is_current(kernel, tree_type, signature, quality="full", stack=None):
    try:
        if kernel is None or kernel.get(_KERNEL_KIND) != _KERNEL_SCHEMA:
            return False
        if (kernel.get("_perceptual_grade_tree_type") != tree_type
                or kernel.get(_KERNEL_SIGNATURE) != signature
                or kernel.get(_KERNEL_QUALITY, "full") != quality):
            return False
        if stack is not None and bool(kernel.get("_perceptual_grade_stack_kernel")) != stack:
            return False
        return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _kernel_error_text(node):
    return "Grade output is magenta" if node.get(_NODE_ERROR) else ""


def _apply_output_presentation(node, mode, error):
    for key in (_NODE_ERROR, _NODE_PENDING):
        if key in node:
            del node[key]
    node.use_custom_color = mode != "current"
    if mode == "current":
        return
    if mode == "error":
        node[_NODE_ERROR] = str(error)[:240]
        node.color = (0.65, 0.04, 0.04)
    else:
        node[_NODE_PENDING] = (
            "Updating - showing last-good result" if mode == "preview"
            else "Preparing Grade - showing identity preview"
        )
        node.color = (0.65, 0.32, 0.04)


def _socket_default_value(socket):
    value = socket.default_value
    if not isinstance(value, (str, bytes)) and hasattr(value, "__len__"):
        return tuple(value)
    return value


def _kernel_snapshot(node):
    tree = node.id_data
    tree_links = tuple(tree.links)
    links = tuple(
        (link.from_node, link.from_socket.name,
         link.to_node, link.to_socket.name)
        for link in tree_links
        if link.from_node == node or link.to_node == node
    )
    multi_input_groups = []
    for link in tree_links:
        if link.from_node != node or not getattr(link.to_socket, "is_multi_input", False):
            continue
        target = link.to_node
        input_name = link.to_socket.name
        if any(group[0] == target and group[1] == input_name
               for group in multi_input_groups):
            continue
        incoming = [
            (index, candidate)
            for index, candidate in enumerate(tree_links)
            if candidate.to_node == target and candidate.to_socket == link.to_socket
        ]
        incoming.sort(key=lambda item: (
            getattr(item[1], "multi_input_sort_id", item[0]), item[0]
        ))
        multi_input_groups.append((
            target,
            input_name,
            tuple((candidate.from_node, candidate.from_socket.name)
                  for _index, candidate in incoming),
        ))
    return {
        "kernel": node.node_tree,
        "values": tuple(
            (socket.name, _socket_default_value(socket))
            for socket in node.inputs if hasattr(socket, "default_value")
        ),
        "links": links,
        "multi_input_groups": tuple(multi_input_groups),
    }


def _restore_kernel_snapshot(node, kernel, snapshot):
    tree = node.id_data
    for link in tuple(tree.links):
        touches_node = link.from_node == node or link.to_node == node
        touches_multi_input = any(
            link.to_node == target and link.to_socket.name == input_name
            for target, input_name, _sources in snapshot["multi_input_groups"]
        )
        if touches_node or touches_multi_input:
            tree.links.remove(link)

    node.node_tree = kernel
    for name, value in snapshot["values"]:
        socket = node.inputs.get(name)
        if socket is None:
            raise RuntimeError("Kernel replacement lost input socket " + name)
        if hasattr(socket, "default_value"):
            socket.default_value = value

    for target, input_name, sources in snapshot["multi_input_groups"]:
        target_socket = target.inputs.get(input_name)
        if target_socket is None:
            raise RuntimeError("Kernel replacement lost a multi-input socket")
        for source, output in sources:
            source_socket = source.outputs.get(output)
            if source_socket is None:
                raise RuntimeError("Kernel replacement lost a connected socket")
            tree.links.new(source_socket, target_socket)

    for source, output, target, input_ in snapshot["links"]:
        if any(target == group_target and input_ == group_input
               for group_target, group_input, _sources
               in snapshot["multi_input_groups"]):
            continue
        source_socket = source.outputs.get(output)
        target_socket = target.inputs.get(input_)
        if source_socket is None or target_socket is None:
            raise RuntimeError("Kernel replacement lost a connected socket")
        tree.links.new(source_socket, target_socket)

    if node.node_tree != kernel:
        raise RuntimeError("Kernel replacement did not select the requested group")
    actual_values = tuple(
        (name, _socket_default_value(node.inputs[name]))
        for name, _value in snapshot["values"]
    )
    if actual_values != snapshot["values"]:
        raise RuntimeError("Kernel replacement did not preserve input values")
    expected_links = tuple(sorted(
        (source.as_pointer(), output, target.as_pointer(), input_)
        for source, output, target, input_ in snapshot["links"]
    ))
    actual_links = tuple(sorted(
        (link.from_node.as_pointer(), link.from_socket.name,
         link.to_node.as_pointer(), link.to_socket.name)
        for link in tree.links
        if link.from_node == node or link.to_node == node
    ))
    if actual_links != expected_links:
        raise RuntimeError("Kernel replacement did not preserve node links")
    for target, input_name, sources in snapshot["multi_input_groups"]:
        target_socket = target.inputs.get(input_name)
        actual_sources = [
            (index, link)
            for index, link in enumerate(tree.links)
            if link.to_node == target and link.to_socket == target_socket
        ]
        actual_sources.sort(key=lambda item: (
            getattr(item[1], "multi_input_sort_id", item[0]), item[0]
        ))
        actual_order = tuple(
            (link.from_node.as_pointer(), link.from_socket.name)
            for _index, link in actual_sources
        )
        expected_order = tuple(
            (source.as_pointer(), output) for source, output in sources
        )
        if actual_order != expected_order:
            raise RuntimeError("Kernel replacement changed multi-input link order")


def _replace_node_kernel(node, kernel):
    snapshot = _kernel_snapshot(node)
    previous = snapshot["kernel"]
    if previous == kernel:
        return previous
    try:
        _restore_kernel_snapshot(node, kernel, snapshot)
    except Exception as replacement_error:
        try:
            _restore_kernel_snapshot(node, previous, snapshot)
        except Exception as rollback_error:
            raise RuntimeError(
                "Kernel replacement failed and graph rollback failed: "
                + str(rollback_error)
            ) from replacement_error
        raise
    return previous


def _apply_output_kernel(node, mode):
    if mode == "pending":
        _replace_node_kernel(node, _identity_kernel(node.id_data.bl_idname))
    elif mode == "error":
        _replace_node_kernel(node, _error_kernel(node.id_data.bl_idname))


def _apply_output_effect(node, effects):
    failures = []
    previous = getattr(node, "node_tree", None)
    for operation, args in (
        (_apply_output_presentation, (node, effects.output_mode, effects.error)),
        (_apply_output_kernel, (node, effects.output_mode)),
    ):
        try:
            operation(*args)
        except Exception as failure:
            failures.append(failure)
    current = getattr(node, "node_tree", None)
    if previous != current:
        _retire_kernels((previous,))
    if failures:
        detail = "; ".join(str(failure) for failure in failures)
        raise RuntimeError("Could not apply Grade output policy: " + detail) from failures[0]


def _source_for(node, working_space):
    if _is_stack_node(node):
        key = ("stack-node", node.as_pointer(), working_space)
        return _preparation_sources.setdefault(key, object())
    grade = node.pg_grade
    owner = ("grade", grade.as_pointer()) if grade is not None else ("node", node.as_pointer())
    key = (*owner, working_space)
    return _preparation_sources.setdefault(key, object())


def _release_source(source):
    if source is None or any(record.get("source") is source for record in _node_stores.values()):
        return
    for key, token in tuple(_preparation_sources.items()):
        if token is source:
            del _preparation_sources[key]
    if _preparation_runtime is not None:
        _preparation_runtime.forget(source)


def _record_for(node, desired_signature=None, source=None):
    pointer = node.as_pointer()
    record = _node_stores.get(pointer)
    if record is not None and (source is None or record.get("source") is source):
        record["node"] = node
        return record
    previous_state = record["state"] if record is not None else None
    gesture_active = bool(_active_gestures.get(pointer))
    if record is not None:
        del _node_stores[pointer]
        _release_source(record.get("source"))

    applied_signature = None
    applied_quality = None
    kernel = getattr(node, "node_tree", None)
    kernel_quality = kernel.get(_KERNEL_QUALITY, "full") if kernel is not None else "full"
    if previous_state is not None \
            and previous_state.error is None \
            and previous_state.applied_signature is not None \
            and _kernel_is_current(
                kernel, node.id_data.bl_idname, previous_state.applied_signature,
                previous_state.applied_quality or "full", stack=_is_stack_node(node)):
        applied_signature = previous_state.applied_signature
        applied_quality = previous_state.applied_quality or "full"
    elif (desired_signature is not None and _kernel_is_current(
            kernel, node.id_data.bl_idname, desired_signature,
            kernel_quality, stack=_is_stack_node(node))):
        applied_signature = desired_signature
        applied_quality = kernel_quality
    state = kernel_readiness.new(
        desired_signature=desired_signature,
        applied_signature=applied_signature,
        applied_quality=applied_quality,
        gesture_active=gesture_active,
    )
    record = {"node": node, "state": state, "source": source,
              "preparation_signature": None, "stack": _is_stack_node(node)}
    _node_stores[pointer] = record
    return record


def _ensure_timer():
    if (_preparation_runtime is not None and _preparation_runtime.pending
            and not bpy.app.timers.is_registered(_preparation_tick)):
        bpy.app.timers.register(_preparation_tick, first_interval=0.02)


def _consume_effects(node, effects, preparation=None, record=None, defer_build=False):
    failures = []
    try:
        _apply_output_effect(node, effects)
    except Exception as error:
        failures.append(error)
        if effects.error is None and record is not None:
            record["state"], failed_effects = kernel_readiness.step(
                record["state"], kernel_readiness.Event(
                    "installation_result", None, str(error)))
            try:
                _apply_output_effect(node, failed_effects)
            except Exception as fallback_error:
                failures.append(fallback_error)
            return tuple(failures)

    if effects.prepare_signature is not None:
        try:
            if preparation is None or _preparation_runtime is None:
                raise RuntimeError("Grade preparation inputs or runtime are unavailable")
            source, signature, settings, working_space, lane, progressive = preparation
            _preparation_runtime.request(
                source, signature, settings, working_space, lane=lane,
                progressive=progressive,
            )
            _ensure_timer()
        except Exception as error:
            failures.extend(_dispatch(node, kernel_readiness.Event(
                "preparation_result", effects.prepare_signature, str(error))))

    if effects.build_signature is not None and not defer_build:
        failures.extend(_fail_installation(
            (record or _record_for(node),), effects.build_signature,
            RuntimeError("Prepared Grade data is unavailable")))
    return tuple(failures)


def _dispatch_transition(node, record, event, preparation=None, defer_build=False):
    record["state"], effects = kernel_readiness.step(record["state"], event)
    failures = _consume_effects(node, effects, preparation, record, defer_build=defer_build)
    return effects, failures


def _dispatch(node, event, preparation=None):
    global _reconciling
    desired_signature = event.signature if event.kind == "request" else None
    record = _record_for(node, desired_signature)
    previous_reconciling = _reconciling
    _reconciling = True
    try:
        _effects, failures = _dispatch_transition(node, record, event, preparation)
        return failures
    finally:
        _reconciling = previous_reconciling


def _request_node(node, working_space, snapshots=None):
    if _is_grade_node(node) and node.pg_grade is None:
        _reset_linear(node.pg_linear)
    elif _is_stack_node(node):
        _stack_transition(node, stack_policy.Event(
            "replace", _stack_grade_ids(node), 0))
    source = _source_for(node, working_space)
    snapshot = None if snapshots is None else snapshots.get(source)
    if snapshot is None:
        settings = _settings_for_node(node)
        snapshot = tuple(settings) if _is_stack_node(node) else _linear_settings(settings)
        if snapshots is not None:
            snapshots[source] = snapshot
    if _is_stack_node(node):
        snapshot = tuple(snapshot)
        signature = _stack_signature(snapshot, working_space)
        preparation_signature = signature
        lane = "lut"
    else:
        signature = _signature(node.id_data.bl_idname, _snapshot_values(snapshot), working_space)
        preparation_signature = _preparation_signature(snapshot, working_space)
        lane = "linear"
    record = _record_for(node, signature, source)
    record["preparation_signature"] = preparation_signature
    state = record["state"]
    failures = []
    if (state.applied_signature is not None and not _kernel_is_current(
            node.node_tree, node.id_data.bl_idname, state.applied_signature,
            state.applied_quality or "full", stack=_is_stack_node(node))):
        failures.extend(_dispatch(node, kernel_readiness.Event(
            "installation_result", None, "Installed Grade kernel is missing or stale")))
    failures.extend(_dispatch(
        node, kernel_readiness.Event("request", signature),
        (source, preparation_signature, snapshot, working_space, lane,
         lane == "lut" and bool(state.gesture_active)),
    ))
    return tuple(failures)


def _publication_signature(record, prepared):
    if record["stack"]:
        if not isinstance(prepared, _PreparedStack):
            raise TypeError("LUT preparation returned an invalid Stack result")
        return _stack_signature(prepared.settings, prepared.space)
    return _signature(
        record["node"].id_data.bl_idname,
        _snapshot_values(prepared.settings),
        prepared.space,
    )


def _handle_preparation_result(source, preparation_signature, prepared, error,
                               quality="full", lane="linear"):
    global _reconciling
    failures = []
    authorized_builds = {}
    previous_reconciling = _reconciling
    _reconciling = True
    try:
        for record in tuple(_node_stores.values()):
            if record.get("source") is not source:
                continue
            if error is not None:
                if record["preparation_signature"] != preparation_signature:
                    continue
                signature = record["state"].desired_signature
            else:
                if (record["stack"] and lane != "lut") or (not record["stack"] and lane != "linear"):
                    continue
                try:
                    signature = _publication_signature(record, prepared)
                except Exception as failure:
                    failures.extend(_fail_installation(
                        (record,), record["state"].desired_signature,
                        failure, quality,
                    ))
                    continue
            effects, transition_failures = _dispatch_transition(
                record["node"], record,
                kernel_readiness.Event("preparation_result", signature,
                                       None if error is None else str(error),
                                       quality=quality),
                defer_build=True,
            )
            failures.extend(transition_failures)
            if effects.build_signature is not None:
                build_quality = effects.build_quality
                authorized_builds.setdefault(
                    (effects.build_signature, build_quality), []
                ).append(record)
        for (signature, build_quality), records in authorized_builds.items():
            failures.extend(_build_and_install(
                signature, tuple(records), prepared, build_quality
            ))
    finally:
        _reconciling = previous_reconciling
    return tuple(failures)


def _build_and_install(signature, authorized_records, prepared, quality="full"):
    global _reconciling
    users = tuple(record for record in authorized_records
                  if _node_stores.get(record["node"].as_pointer()) is record)
    if not users:
        return ()
    tree_type = users[0]["node"].id_data.bl_idname
    stack = users[0]["stack"]
    kernel = next((record["node"].node_tree for record in tuple(_node_stores.values())
                   if record["stack"] == stack and _kernel_is_current(
                       record["node"].node_tree, tree_type, signature, quality,
                       stack=stack)), None)
    built_kernel = False
    previous_reconciling = _reconciling
    _reconciling = True
    try:
        if kernel is None:
            try:
                kernel = (_stack_kernel(tree_type, prepared, signature, quality) if stack
                          else _kernel(tree_type, prepared, prepared.space, signature))
                built_kernel = True
            except Exception as error:
                return _fail_installation(users, signature, error, quality)
        failures = []
        for record in users:
            node = record["node"]
            try:
                previous = _replace_node_kernel(node, kernel)
            except Exception as error:
                failures.extend(_dispatch(node, kernel_readiness.Event(
                    "installation_result", signature, str(error), quality=quality)))
                continue
            if previous != kernel:
                _retire_kernels((previous,))
            failures.extend(_dispatch(node, kernel_readiness.Event(
                "installation_result", signature, quality=quality)))
        return tuple(failures)
    finally:
        if built_kernel:
            try:
                if kernel.users == 0:
                    _retire_kernels((kernel,))
            except (AttributeError, ReferenceError, RuntimeError):
                pass
        _reconciling = previous_reconciling


def _fail_installation(users, signature, error, quality="full"):
    failures = []
    for record in users:
        failures.extend(_dispatch(record["node"], kernel_readiness.Event(
            "installation_result", signature, str(error), quality=quality)))
    return tuple(failures)


def _handle_preparation_completions(completions):
    failures = []
    for publication in completions:
        if hasattr(publication, "quality"):
            failures.extend(_handle_preparation_result(
                publication.source, publication.signature, publication.prepared,
                publication.error, publication.quality, publication.lane,
            ))
        else:
            source, signature, prepared, error = publication
            failures.extend(_handle_preparation_result(source, signature, prepared, error))
    return tuple(failures)


def _preparation_tick():
    if _preparation_runtime is None:
        return None
    try:
        _handle_preparation_completions(_preparation_runtime.collect())
    except Exception as error:
        _block_nodes(tuple(_all_grade_nodes()), error)
        print("Perceptual Grade asynchronous preparation failed:", error)
    return 0.02 if _preparation_runtime.pending else None


def _retire_kernels(kernels):
    seen = set()
    for kernel in kernels:
        try:
            pointer = kernel.as_pointer() if kernel is not None else 0
            if not pointer or pointer in seen:
                continue
            seen.add(pointer)
            if (kernel is not None and kernel.get(_KERNEL_KIND) == _KERNEL_SCHEMA
                    and kernel.users == 0 and not kernel.use_fake_user):
                bpy.data.node_groups.remove(kernel)
            for image in tuple(bpy.data.images):
                if image.get("_perceptual_grade_stack_image") and image.users == 0:
                    bpy.data.images.remove(image)
        except (AttributeError, ReferenceError, RuntimeError):
            continue


def _refresh_nodes(nodes, working_space=None):
    nodes = tuple(node for node in nodes if _is_output_node(node))
    if not nodes:
        return ()

    try:
        working_space = working_space or _working_space()
    except Exception as error:
        return _block_nodes(nodes, error)
    failures = []
    snapshots = {}
    for node in nodes:
        try:
            failures.extend(((node,), error) for error in _request_node(node, working_space, snapshots))
        except Exception as error:
            failures.extend(_block_nodes((node,), error))
    return tuple(failures)


def _block_nodes(nodes, error):
    failures = []
    message = f"{type(error).__name__}: {error}"[:240]
    for node in nodes:
        try:
            record = _record_for(node)
            signature = record["state"].desired_signature
            failures.extend(_dispatch(
                node,
                kernel_readiness.Event("installation_result", signature, message),
            ))
        except Exception as failure:
            failures.append(((node,), failure))
    return tuple(failures)


def _forget_node(node):
    try:
        record = _node_stores.pop(node.as_pointer(), None)
    except (AttributeError, ReferenceError, RuntimeError):
        return
    if record is not None:
        _release_source(record.get("source"))
    if _is_stack_node(node):
        _stack_stores.pop(node.as_pointer(), None)


def _reset_node_stores():
    sources = tuple(_preparation_sources.values())
    _node_stores.clear()
    _stack_stores.clear()
    _preparation_sources.clear()
    if _preparation_runtime is not None:
        for source in sources:
            _preparation_runtime.forget(source)


def _replace_kernel(node):
    if _gesture_is_armed(node.as_pointer()):
        return
    failures = _refresh_nodes((node,))
    if failures:
        _failed_nodes, error = failures[-1]
        print("Perceptual Grade kernel repair failed:", error)


def _stack_grade_ids(node):
    return tuple(
        entry.grade.as_pointer()
        for entry in node.pg_stack_entries
        if entry.enabled and entry.grade is not None
    )


def _stack_store(node):
    return _stack_stores.setdefault(node.as_pointer(), stack_policy.new())


def _stack_transition(node, event):
    state, effects = stack_policy.step(_stack_store(node), event)
    _stack_stores[node.as_pointer()] = state
    return effects


def _stack_owner(entry):
    pointer = entry.as_pointer()
    for tree in _all_node_trees():
        try:
            nodes = tuple(tree.nodes)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for node in nodes:
            if _is_stack_node(node) and any(item.as_pointer() == pointer
                                             for item in node.pg_stack_entries):
                return node
    return None


def _stack_changed(entry, _context):
    node = _stack_owner(entry)
    if node is None:
        return
    effects = _stack_transition(node, stack_policy.Event(
        "replace", _stack_grade_ids(node), 0))
    if effects.rebuild:
        _replace_kernel(node)


def _refresh_stack_policy(node):
    effects = _stack_transition(node, stack_policy.Event(
        "replace", _stack_grade_ids(node), 0))
    if effects.rebuild:
        _replace_kernel(node)


def _stack_focus_changed(node, _context):
    if _is_stack_node(node):
        node.id_data.nodes.active = node


def _gesture_related_nodes(node):
    grade = node.pg_grade if _is_grade_node(node) else _stack_active_grade(node)
    related = {node.as_pointer(): node}
    if grade is None:
        return tuple(related.values())
    for candidate in _all_grade_nodes():
        try:
            if _is_grade_node(candidate) and candidate.pg_grade == grade:
                related[candidate.as_pointer()] = candidate
            elif _is_stack_node(candidate) and any(
                    item.enabled and item.grade == grade
                    for item in candidate.pg_stack_entries):
                related[candidate.as_pointer()] = candidate
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return tuple(related.values())


def _gesture_is_armed(pointer):
    return any(pointer in pointers for pointers in _gesture_settings.values())


def _settings_signature_for(node):
    try:
        space = _working_space()
        if _is_stack_node(node):
            settings = tuple(
                _linear_settings(entry.grade.pg_linear)
                for entry in node.pg_stack_entries
                if entry.enabled and entry.grade is not None
            )
            return _stack_signature(settings, space)
        return _signature(
            node.id_data.bl_idname,
            _snapshot_values(_linear_settings(_settings_for_node(node))),
            space,
        )
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None


def _arm_gesture(window_key, node, position):
    previous = _gesture_targets.get(window_key)
    if previous is not None:
        _end_gesture(window_key, previous[0])
    previous = _armed_gestures.get(window_key)
    if previous is not None:
        _release_armed_gesture(window_key, previous[0])
    targets = _gesture_related_nodes(node)
    _armed_gestures[window_key] = (object(), targets, position)
    _gesture_settings[window_key] = {
        target.as_pointer(): _settings_signature_for(target) for target in targets
    }


def _activate_gesture(window_key, token):
    armed = _armed_gestures.get(window_key)
    if armed is None or armed[0] is not token:
        return None
    del _armed_gestures[window_key]
    before = _gesture_settings.pop(window_key, {})
    pointers = []
    for target in armed[1]:
        pointer = target.as_pointer()
        active = _active_gestures.setdefault(pointer, set())
        was_active = bool(active)
        active.add(token)
        if not was_active:
            failures = _dispatch(target, kernel_readiness.Event("gesture_begin"))
            if failures:
                print("Perceptual Grade gesture start failed:", failures[-1])
        pointers.append(pointer)
    _gesture_targets[window_key] = token, tuple(pointers), before
    _refresh_nodes(armed[1])
    return None


def _release_armed_gesture(window_key, token):
    armed = _armed_gestures.get(window_key)
    if armed is None or armed[0] is not token:
        return None
    del _armed_gestures[window_key]
    before = _gesture_settings.pop(window_key, {})
    changed = tuple(target for target in armed[1]
                    if before.get(target.as_pointer()) != _settings_signature_for(target))
    _refresh_nodes(changed)
    if changed:
        _push_gesture_undo(window_key)
    return None


def _begin_gesture(window_key, node):
    """Compatibility helper for tests and explicit adapter callers."""
    _arm_gesture(window_key, node, (0, 0))
    token = _armed_gestures[window_key][0]
    _activate_gesture(window_key, token)
    return token


def _end_gesture(window_key, token):
    target = _gesture_targets.get(window_key)
    if target is None or target[0] is not token:
        return None
    del _gesture_targets[window_key]
    changed = False
    for pointer in target[1]:
        active = _active_gestures.get(pointer)
        if active is None:
            continue
        active.discard(token)
        if active:
            continue
        del _active_gestures[pointer]
        record = _node_stores.get(pointer)
        if record is None:
            continue
        try:
            changed = (changed or
                       target[2].get(pointer) != _settings_signature_for(record["node"]))
            failures = _dispatch(record["node"], kernel_readiness.Event("gesture_release"))
            if failures:
                print("Perceptual Grade gesture release failed:", failures[-1])
        except (ReferenceError, RuntimeError):
            continue
    if changed:
        _push_gesture_undo(window_key)
    return None


def _push_gesture_undo(window_key):
    for manager in tuple(bpy.data.window_managers):
        for window in tuple(getattr(manager, "windows", ())):
            try:
                if window.as_pointer() != window_key:
                    continue
                area = next((item for item in window.screen.areas
                             if item.type == "NODE_EDITOR"), None)
                region = (None if area is None else next(
                    (item for item in area.regions if item.type == "WINDOW"), None
                ))
                override = {"window": window}
                if area is not None:
                    override["area"] = area
                if region is not None:
                    override["region"] = region
                with bpy.context.temp_override(**override):
                    result = bpy.ops.ed.undo_push(message="Perceptual Grade")
                if result != {"FINISHED"}:
                    raise RuntimeError("Blender did not record the Grade gesture")
                return True
            except (AttributeError, ReferenceError, RuntimeError, StopIteration) as error:
                print("Perceptual Grade undo checkpoint failed:", error)
                return False
    return False


class PG_OT_gesture_router(bpy.types.Operator):
    bl_idname = "perceptual_grade.gesture_router"
    bl_label = "Perceptual Grade Gesture Router"
    bl_options = {"INTERNAL"}

    def invoke(self, context, _event):
        window = context.window
        if window is None:
            return {"CANCELLED"}
        self.window_key = window.as_pointer()
        if self.window_key in _gesture_routers:
            return {"CANCELLED"}
        self.token = object()
        _gesture_routers[self.window_key] = self.token
        self.gesture_token = None
        self.dragging = False
        self.press_position = None
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if _gesture_routers.get(self.window_key) is not self.token:
            return {"CANCELLED", "PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            space = getattr(context, "space_data", None)
            tree = getattr(space, "edit_tree", None)
            active = getattr(getattr(tree, "nodes", None), "active", None)
            if context.area is not None and context.area.type == "NODE_EDITOR" \
                    and getattr(getattr(context, "region", None), "type", None) == "UI" \
                    and _is_output_node(active):
                _arm_gesture(self.window_key, active, (event.mouse_x, event.mouse_y))
                self.gesture_token = _armed_gestures[self.window_key][0]
                self.press_position = (event.mouse_x, event.mouse_y)
                self.dragging = False
        elif event.type == "MOUSEMOVE" and self.gesture_token is not None \
                and not self.dragging:
            if (abs(event.mouse_x - self.press_position[0]) >= 3
                    or abs(event.mouse_y - self.press_position[1]) >= 3):
                _activate_gesture(self.window_key, self.gesture_token)
                self.dragging = True
        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            token = self.gesture_token
            if token is not None:
                self.gesture_token = None
                callback = _end_gesture if self.dragging else _release_armed_gesture
                self.dragging = False
                bpy.app.timers.register(
                    partial(callback, self.window_key, token), first_interval=0.0
                )
        elif event.type == "WINDOW_DEACTIVATE" and self.gesture_token is not None:
            token = self.gesture_token
            self.gesture_token = None
            callback = _end_gesture if self.dragging else _release_armed_gesture
            self.dragging = False
            bpy.app.timers.register(
                partial(callback, self.window_key, token), first_interval=0.0
            )
        return {"PASS_THROUGH"}


def _gesture_router_tick():
    if not _registered_classes or PG_OT_gesture_router not in _registered_classes:
        return None
    try:
        managers = tuple(bpy.data.window_managers)
    except (AttributeError, ReferenceError, RuntimeError):
        managers = (bpy.context.window_manager,)
    for manager in managers:
        for window in tuple(getattr(manager, "windows", ())):
            key = window.as_pointer()
            if key in _gesture_routers:
                continue
            try:
                with bpy.context.temp_override(window=window):
                    bpy.ops.perceptual_grade.gesture_router("INVOKE_DEFAULT")
            except (AttributeError, ReferenceError, RuntimeError):
                continue
    return 0.5


def _clear_gestures():
    _active_gestures.clear()
    _armed_gestures.clear()
    _gesture_settings.clear()
    _gesture_targets.clear()
    _gesture_routers.clear()


def _stack_active_grade(node):
    if not node.pg_stack_entries:
        return None
    index = min(max(0, node.pg_active_index), len(node.pg_stack_entries) - 1)
    item = node.pg_stack_entries[index]
    return item.grade if item.enabled else None


def _grade_changed(grade):
    users = []
    for tree in _all_node_trees():
        try:
            nodes = tuple(tree.nodes)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for node in nodes:
            try:
                if (_is_grade_node(node) and node.pg_grade == grade):
                    users.append(node)
                elif _is_stack_node(node):
                    effects = _stack_transition(node, stack_policy.Event(
                        "grade_changed", _stack_grade_ids(node), grade.as_pointer()
                    ))
                    if effects.rebuild:
                        users.append(node)
            except (AttributeError, ReferenceError, RuntimeError):
                continue
    failures = _refresh_nodes(tuple(node for node in users
                                   if not _gesture_is_armed(node.as_pointer())))
    for failed_nodes, error in failures:
        print("Perceptual Grade kernel repair failed:", error)


def _all_node_trees():
    if not hasattr(bpy.data, "node_groups"):
        return
    seen = set()
    owners = [bpy.data.node_groups]
    owners.extend(getattr(bpy.data, name, ()) for name in (
        "materials", "worlds", "lights", "scenes", "linestyles",
    ))
    for collection in owners:
        for owner in tuple(collection):
            try:
                tree = owner if hasattr(owner, "nodes") else getattr(owner, "node_tree", None)
                if tree is None:
                    continue
                pointer = tree.as_pointer()
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            if pointer not in seen:
                seen.add(pointer)
                yield tree


def _all_grade_nodes():
    for tree in _all_node_trees():
        try:
            nodes = tuple(tree.nodes)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for node in nodes:
            if _is_output_node(node):
                yield node


def _ensure_all_kernels(working_space=None):
    global _last_working_space
    if not hasattr(bpy.data, "node_groups"):
        return ()
    nodes = tuple(_all_grade_nodes())
    try:
        working_space = working_space or _working_space()
    except Exception as error:
        _last_working_space = None
        failures = _block_nodes(nodes, error)
        for failed_nodes, failure in failures:
            names = ", ".join(getattr(node, "name", "Grade") for node in failed_nodes)
            print(f"Perceptual Grade output failed closed for {names}: {failure}")
        return tuple(failures)
    try:
        failures = _refresh_nodes(nodes, working_space)
    except Exception as error:
        failures = _block_nodes(nodes, error)
    _last_working_space = working_space
    if _preparation_runtime is not None:
        _ensure_timer()
    for nodes, error in failures:
        names = ", ".join(getattr(node, "name", "Grade") for node in nodes)
        print(f"Perceptual Grade output failed closed for {names}: {error}")
    return failures


def _startup_reconcile_tick():
    if PGShaderGrade not in _registered_classes:
        return None
    if not hasattr(bpy.data, "node_groups"):
        return 0.1
    _ensure_all_kernels()
    return None


@persistent
def _load_post(_filepath):
    try:
        _reset_node_stores()
        _ensure_all_kernels()
    except Exception as error:
        print("Perceptual Grade load repair failed:", error)


@persistent
def _undo_redo_pre(*_args):
    _clear_gestures()
    _reset_node_stores()


@persistent
def _undo_redo_post(*_args):
    if not bpy.app.timers.is_registered(_undo_redo_reconcile_tick):
        bpy.app.timers.register(_undo_redo_reconcile_tick, first_interval=0.0)


def _undo_redo_reconcile_tick():
    if PGShaderGrade not in _registered_classes:
        return None
    try:
        _reset_node_stores()
        _ensure_all_kernels()
    except Exception as error:
        print("Perceptual Grade undo repair failed:", error)
    return None


@persistent
def _render_pre(_scene):
    _ensure_all_kernels()
    _drain_preparations()


def _drain_preparations():
    if _preparation_runtime is None:
        return ()
    failures = []
    sources = tuple({record["source"] for record in _node_stores.values()
                     if record.get("source") is not None})
    # The async barrier waits only for preparation, never for Blender mutation.
    try:
        failures.extend(_handle_preparation_completions(_preparation_runtime.wait(sources)))
    except Exception as error:
        # Blender need not abort a render when a handler raises. Revoke output
        # through the machine before returning to the host.
        failures.extend(_block_nodes(tuple(record["node"] for record in _node_stores.values()), error))
    for record in tuple(_node_stores.values()):
        state = record["state"]
        node = record["node"]
        if (not kernel_readiness.output_allowed(state)
                or not _kernel_is_current(
                    node.node_tree, node.id_data.bl_idname, state.desired_signature,
                    state.applied_quality or "full", stack=record["stack"])):
            failures.extend(_dispatch(node, kernel_readiness.Event(
                "installation_result", state.desired_signature,
                state.error or "Grade did not become current for rendering")))
    return tuple(failures)


@persistent
def _depsgraph_update_post(_scene, _depsgraph=None):
    global _last_working_space
    try:
        working_space = _working_space()
    except Exception as error:
        _last_working_space = None
        _block_nodes(tuple(_all_grade_nodes()), error)
        return
    if working_space != _last_working_space and not _reconciling:
        _ensure_all_kernels(working_space)


def _linear_changed(settings, _context):
    pointer = settings.as_pointer()
    if pointer in _syncing:
        return
    holder = _holder(settings)
    if holder is None:
        return
    if holder.bl_idname == PGGradeData.bl_idname:
        _grade_changed(holder)
        return

    if holder.pg_grade is None:
        # Local settings only supply the disabled controls' neutral values.
        # A Grade must be explicitly created before its settings can be edited.
        _reset_linear(settings)


def _source_white_changed(axis):
    def update(settings, context):
        pointer = settings.as_pointer()
        if pointer in _syncing:
            return
        name = "source_x" if axis == 0 else "source_y"
        value = project_source_white_component(
            (settings.source_x, settings.source_y), axis
        )
        if abs(value - getattr(settings, name)) > 1e-7:
            with _suspend(settings):
                setattr(settings, name, value)
        _linear_changed(settings, context)
    return update


def _selection_changed(node, _context):
    if node.as_pointer() in _syncing:
        return
    if node.pg_grade is None:
        _reset_linear(node.pg_linear)
    else:
        _grade_changed(node.pg_grade)
        return
    _replace_kernel(node)


def _assign_values(node, values):
    if node.pg_grade is None:
        return
    settings = node.pg_grade.pg_linear
    with _suspend(settings):
        for name, value in values.items():
            setattr(settings, name, value)
    _grade_changed(node.pg_grade)


def _node_from_context(context):
    node = getattr(context, "pg_node", None)
    if _is_grade_node(node):
        return node
    space = getattr(context, "space_data", None)
    tree = getattr(space, "edit_tree", None)
    node = getattr(getattr(tree, "nodes", None), "active", None)
    return node if _is_grade_node(node) else None


class PGLinearSettings(bpy.types.PropertyGroup):
    exposure: FloatProperty(name="Exposure", default=0.0, min=-6.0, max=6.0,
                             precision=2, update=_linear_changed)
    source_x: FloatProperty(name="x", default=D65[0], min=0.0, max=0.9,
                            precision=5, update=_source_white_changed(0))
    source_y: FloatProperty(name="y", default=D65[1], min=0.0, max=0.9,
                            precision=5, update=_source_white_changed(1))
    cr_balance: FloatProperty(name="CR Balance", default=0.0, min=-2.0, max=2.0,
                              precision=3, update=_linear_changed)
    yb_balance: FloatProperty(name="YB Balance", default=0.0, min=-2.0, max=2.0,
                              precision=3, update=_linear_changed)
    cr_spread: FloatProperty(name="CR Spread", default=0.0, min=-100.0, max=150.0,
                             precision=1, update=_linear_changed)
    yb_spread: FloatProperty(name="YB Spread", default=0.0, min=-100.0, max=150.0,
                             precision=1, update=_linear_changed)
    cr_heading: FloatProperty(name="CR Heading", default=0.0, min=-180.0, max=180.0,
                              precision=1, update=_linear_changed)
    yb_heading: FloatProperty(name="YB Heading", default=0.0, min=-180.0, max=180.0,
                              precision=1, update=_linear_changed)


class PGGradeData(bpy.types.NodeTree):
    bl_idname = "PGGradeData"
    bl_label = "Grade"
    bl_icon = "COLOR"

    pg_linear: PointerProperty(type=PGLinearSettings)

    @classmethod
    def poll(cls, _context):
        return False


def _poll_grade_data(_node, value):
    return value is None or value.bl_idname == PGGradeData.bl_idname


class PGStackEntry(bpy.types.PropertyGroup):
    key: StringProperty(options={"HIDDEN"})
    enabled: BoolProperty(name="Enabled", default=True, update=_stack_changed)
    grade: PointerProperty(type=PGGradeData, name="Grade", poll=_poll_grade_data,
                           update=_stack_changed)


def _draw_stack_node(node, context, layout):
    layout.context_pointer_set("pg_stack_node", node)
    for index, entry in enumerate(node.pg_stack_entries):
        row = layout.row(align=True)
        row.prop(entry, "enabled", text="", icon="HIDE_OFF" if entry.enabled else "HIDE_ON",
                 toggle=True)
        row.template_ID(entry, "grade")
        op = row.operator(PG_OT_new_stack_grade.bl_idname, text="", icon="ADD")
        op.index = index
        op = row.operator(PG_OT_stack_action.bl_idname, text="", icon="GREASEPENCIL",
                          depress=node.pg_active_index == index)
        op.action, op.index = "SELECT", index
        op = row.operator(PG_OT_stack_action.bl_idname, text="", icon="TRIA_UP")
        op.action, op.index, op.direction = "MOVE", index, -1
        op = row.operator(PG_OT_stack_action.bl_idname, text="", icon="TRIA_DOWN")
        op.action, op.index, op.direction = "MOVE", index, 1
        op = row.operator(PG_OT_stack_action.bl_idname, text="", icon="X")
        op.action, op.index = "REMOVE", index
    op = layout.operator(PG_OT_stack_action.bl_idname, text="Add Grade", icon="ADD")
    op.action = "ADD"
    grade = _stack_active_grade(node)
    if grade is not None:
        layout.separator()
        layout.label(text=grade.name, icon="COLOR")
        settings = grade.pg_linear
        for field in _LINEAR_FIELDS:
            layout.prop(settings, field, slider=field not in {"source_x", "source_y"})
    pending = node.get(_NODE_PENDING)
    if pending:
        layout.label(text=pending, icon="TIME")
    error = node.get(_NODE_ERROR)
    if error:
        layout.label(text=_kernel_error_text(node), icon="ERROR")
        layout.label(text=error)


class PGShaderGradeStack(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGradeStack"
    bl_label = "Grade Stack"
    pg_stack_entries: CollectionProperty(type=PGStackEntry)
    pg_active_index: IntProperty(default=0, min=0, update=_stack_focus_changed)

    def init(self, _context):
        self["_perceptual_grade_stack"] = 1

    def draw_buttons(self, context, layout):
        _draw_stack_node(self, context, layout)

    def draw_buttons_ext(self, context, layout):
        _draw_stack_node(self, context, layout)

    def free(self):
        _forget_node(self)


class PGCompositorGradeStack(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGradeStack"
    bl_label = "Grade Stack"
    pg_stack_entries: CollectionProperty(type=PGStackEntry)
    pg_active_index: IntProperty(default=0, min=0, update=_stack_focus_changed)

    def init(self, _context):
        self["_perceptual_grade_stack"] = 1

    def draw_buttons(self, context, layout):
        _draw_stack_node(self, context, layout)

    def draw_buttons_ext(self, context, layout):
        _draw_stack_node(self, context, layout)

    def free(self):
        _forget_node(self)


class PGShaderGrade(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGrade"
    bl_label = "Grade"
    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_grade: PointerProperty(type=PGGradeData, poll=_poll_grade_data,
                              update=_selection_changed)

    def draw_buttons(self, context, layout):
        layout.context_pointer_set("pg_node", self)
        layout.template_ID(self, "pg_grade", new=PG_OT_new_grade.bl_idname,
                           unlink=PG_OT_unlink_grade.bl_idname)
        pending = self.get(_NODE_PENDING)
        if pending:
            layout.label(text=pending, icon="TIME")
        error = self.get(_NODE_ERROR)
        if error:
            layout.label(text=_kernel_error_text(self), icon="ERROR")
            layout.label(text=error)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)

    def free(self):
        pointer = self.as_pointer()
        _forget_node(self)
        _syncing.add(pointer)
        try:
            self.pg_grade = None
        finally:
            _syncing.discard(pointer)
        kernel = self.node_tree
        if (kernel is not None and kernel.get("_perceptual_grade_linear_kernel")
                and kernel.users <= 1):
            bpy.data.node_groups.remove(kernel, do_unlink=True)


class PGCompositorGrade(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGrade"
    bl_label = "Grade"
    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_grade: PointerProperty(type=PGGradeData, poll=_poll_grade_data,
                              update=_selection_changed)

    def draw_buttons(self, context, layout):
        layout.context_pointer_set("pg_node", self)
        layout.template_ID(self, "pg_grade", new=PG_OT_new_grade.bl_idname,
                           unlink=PG_OT_unlink_grade.bl_idname)
        pending = self.get(_NODE_PENDING)
        if pending:
            layout.label(text=pending, icon="TIME")
        error = self.get(_NODE_ERROR)
        if error:
            layout.label(text=_kernel_error_text(self), icon="ERROR")
            layout.label(text=error)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)

    def free(self):
        pointer = self.as_pointer()
        _forget_node(self)
        _syncing.add(pointer)
        try:
            self.pg_grade = None
        finally:
            _syncing.discard(pointer)
        kernel = self.node_tree
        if (kernel is not None and kernel.get("_perceptual_grade_linear_kernel")
                and kernel.users <= 1):
            bpy.data.node_groups.remove(kernel, do_unlink=True)


class PG_OT_new_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.new_grade"
    bl_label = "New Grade"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _node_from_context(context) is not None

    def execute(self, context):
        node = _node_from_context(context)
        if node is None:
            return {"CANCELLED"}
        source = node.pg_grade.pg_linear if node.pg_grade is not None else None
        grade = _make_grade(source)
        try:
            node.pg_grade = grade
        except BaseException:
            if grade.users == 0:
                bpy.data.node_groups.remove(grade)
            raise
        return {"FINISHED"}


class PG_OT_unlink_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.unlink_grade"
    bl_label = "Unlink Grade"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        return node is not None and node.pg_grade is not None

    def execute(self, context):
        node = _node_from_context(context)
        if node is None:
            return {"CANCELLED"}
        node.pg_grade = None
        return {"FINISHED"}


class PG_OT_match_white(bpy.types.Operator):
    bl_idname = "perceptual_grade.match_white"
    bl_label = "Match White"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        return node is not None and node.pg_grade is not None

    def execute(self, context):
        node = _node_from_context(context)
        if node is None or node.pg_grade is None:
            return {"CANCELLED"}
        _assign_values(node, {"source_x": D65[0], "source_y": D65[1]})
        return {"FINISHED"}


class PG_OT_reset_directions(bpy.types.Operator):
    bl_idname = "perceptual_grade.reset_directions"
    bl_label = "Reset Directions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        return node is not None and node.pg_grade is not None

    def execute(self, context):
        node = _node_from_context(context)
        if node is None or node.pg_grade is None:
            return {"CANCELLED"}
        _assign_values(node, {name: 0.0 for name in _LINEAR_FIELDS[3:]})
        return {"FINISHED"}


class PG_OT_add_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.add_grade"
    bl_label = "Grade"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None)
        return tree is not None and tree.bl_idname in NODE_TYPES

    def execute(self, context):
        space = context.space_data
        tree = space.edit_tree
        node = create_node(tree)
        node.location = space.cursor_location
        for item in tree.nodes:
            item.select = item == node
        tree.nodes.active = node
        return {"FINISHED"}


class PG_OT_add_stack(bpy.types.Operator):
    bl_idname = "perceptual_grade.add_stack"
    bl_label = "Grade Stack"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None)
        return tree is not None and tree.bl_idname in STACK_NODE_TYPES

    def execute(self, context):
        space = context.space_data
        tree = space.edit_tree
        node = create_stack_node(tree)
        node.location = space.cursor_location
        for item in tree.nodes:
            item.select = item == node
        tree.nodes.active = node
        return {"FINISHED"}


class PG_OT_stack_action(bpy.types.Operator):
    bl_idname = "perceptual_grade.stack_action"
    bl_label = "Edit Grade Stack"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(items=(("ADD", "Add", ""), ("REMOVE", "Remove", ""),
                                ("MOVE", "Move", ""), ("SELECT", "Select", "")))
    index: IntProperty(default=0, options={"SKIP_SAVE"})
    direction: IntProperty(default=0, min=-1, max=1, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        node = getattr(context, "pg_stack_node", None)
        if not _is_stack_node(node):
            space = getattr(context, "space_data", None)
            tree = getattr(space, "edit_tree", None)
            node = getattr(getattr(tree, "nodes", None), "active", None)
        return _is_stack_node(node)

    def execute(self, context):
        node = getattr(context, "pg_stack_node", None)
        if not _is_stack_node(node):
            node = context.space_data.edit_tree.nodes.active
        entries = node.pg_stack_entries
        if self.action == "ADD":
            entries.add().key = uuid4().hex
            node.pg_active_index = len(entries) - 1
            _refresh_stack_policy(node)
        elif not 0 <= self.index < len(entries):
            return {"CANCELLED"}
        elif self.action == "REMOVE":
            entries.remove(self.index)
            node.pg_active_index = min(max(0, self.index), max(0, len(entries) - 1))
            _refresh_stack_policy(node)
        elif self.action == "MOVE":
            target = self.index + self.direction
            if 0 <= target < len(entries):
                entries.move(self.index, target)
                if node.pg_active_index == self.index:
                    node.pg_active_index = target
                elif node.pg_active_index == target:
                    node.pg_active_index = self.index
                _refresh_stack_policy(node)
        elif self.action == "SELECT":
            node.pg_active_index = self.index
        return {"FINISHED"}


class PG_OT_new_stack_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.new_stack_grade"
    bl_label = "New Grade"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=0, min=0, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _is_stack_node(getattr(context, "pg_stack_node", None))

    def execute(self, context):
        node = getattr(context, "pg_stack_node", None)
        if not _is_stack_node(node) or not 0 <= self.index < len(node.pg_stack_entries):
            return {"CANCELLED"}
        grade = _make_grade()
        try:
            node.pg_stack_entries[self.index].grade = grade
            node.pg_active_index = self.index
        except BaseException:
            if grade.users == 0:
                bpy.data.node_groups.remove(grade)
            raise
        return {"FINISHED"}


class PG_PT_linear(bpy.types.Panel):
    bl_idname = "PG_PT_linear"
    bl_label = "Linear"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Perceptual Grade"

    @classmethod
    def poll(cls, context):
        node = getattr(context, "pg_stack_node", None)
        if _is_stack_node(node):
            return True
        node = _node_from_context(context)
        if node is not None:
            return True
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None)
        node = getattr(getattr(tree, "nodes", None), "active", None)
        return _is_stack_node(node)

    def draw(self, context):
        node = getattr(context, "pg_stack_node", None)
        if _is_stack_node(node):
            _draw_stack_node(node, context, self.layout)
            return
        node = _node_from_context(context)
        if node is None:
            space = getattr(context, "space_data", None)
            tree = getattr(space, "edit_tree", None)
            node = getattr(getattr(tree, "nodes", None), "active", None)
            if _is_stack_node(node):
                _draw_stack_node(node, context, self.layout)
                return
        if node is None:
            return
        settings = node.pg_grade.pg_linear if node.pg_grade is not None else node.pg_linear
        layout = self.layout.column()
        layout.enabled = node.pg_grade is not None
        layout.prop(settings, "exposure", slider=True)
        row = layout.row(align=True)
        row.prop(settings, "source_x")
        row.prop(settings, "source_y")
        layout.operator(PG_OT_match_white.bl_idname, text="Match White", icon="COLOR")
        row = layout.row()
        row.enabled = False
        row.label(text="Working White: D65")
        layout.separator()
        layout.prop(settings, "cr_balance", slider=True)
        layout.prop(settings, "yb_balance", slider=True)
        layout.prop(settings, "cr_spread", slider=True)
        layout.prop(settings, "yb_spread", slider=True)
        layout.prop(settings, "cr_heading", slider=True)
        layout.prop(settings, "yb_heading", slider=True)
        layout.operator(PG_OT_reset_directions.bl_idname, icon="LOOP_BACK")


def create_node(tree):
    try:
        node_type = NODE_TYPES[tree.bl_idname]
    except KeyError as exc:
        raise ValueError("Grade nodes require a Shader or Compositor tree") from exc

    node = tree.nodes.new(node_type)
    try:
        failures = _refresh_nodes((node,))
        if failures:
            print("Perceptual Grade kernel initialization failed:", failures[-1][1])
    except BaseException:
        tree.nodes.remove(node)
        raise
    return node


def create_stack_node(tree):
    try:
        node_type = STACK_NODE_TYPES[tree.bl_idname]
    except KeyError as exc:
        raise ValueError("Grade Stack nodes require a Shader or Compositor tree") from exc

    node = tree.nodes.new(node_type)
    try:
        _refresh_nodes((node,))
    except BaseException:
        tree.nodes.remove(node)
        raise
    return node


def draw_add_menu(self, context):
    space = getattr(context, "space_data", None)
    tree = getattr(space, "edit_tree", None)
    if tree is None or tree.bl_idname not in NODE_TYPES:
        return
    self.layout.separator()
    self.layout.operator(PG_OT_add_grade.bl_idname, text="Grade", icon="COLOR")
    self.layout.operator(PG_OT_add_stack.bl_idname, text="Grade Stack", icon="NODETREE")


def _register_handlers():
    for collection, callback in (
        (bpy.app.handlers.load_post, _load_post),
        (bpy.app.handlers.undo_pre, _undo_redo_pre),
        (bpy.app.handlers.redo_pre, _undo_redo_pre),
        (bpy.app.handlers.undo_post, _undo_redo_post),
        (bpy.app.handlers.redo_post, _undo_redo_post),
        (bpy.app.handlers.render_pre, _render_pre),
        (bpy.app.handlers.depsgraph_update_post, _depsgraph_update_post),
    ):
        if callback not in collection:
            collection.append(callback)
        if not any(owned_collection is collection and owned_callback is callback
                   for owned_collection, owned_callback in _registered_handlers):
            _registered_handlers.append((collection, callback))


def _unregister_handlers():
    for collection, callback in reversed(tuple(_registered_handlers)):
        try:
            while callback in collection:
                collection.remove(callback)
        except ValueError:
            pass
        except Exception:
            continue
        _registered_handlers[:] = [
            record for record in _registered_handlers
            if not (record[0] is collection and record[1] is callback)
        ]


def register():
    global _preparation_runtime
    if _preparation_runtime is None:
        _preparation_runtime = PreparationRuntime(prepare_linear, workers=1)
        _preparation_runtime.register_lane(
            "lut", _prepare_stack, workers=1, progressive=True
        )
    classes = (
        PGLinearSettings,
        PGGradeData,
        PGStackEntry,
        PGShaderGradeStack,
        PGCompositorGradeStack,
        PGShaderGrade,
        PGCompositorGrade,
        PG_OT_new_grade,
        PG_OT_unlink_grade,
        PG_OT_match_white,
        PG_OT_reset_directions,
        PG_OT_add_grade,
        PG_OT_add_stack,
        PG_OT_stack_action,
        PG_OT_new_stack_grade,
        PG_OT_gesture_router,
        PG_PT_linear,
    )
    try:
        for cls in classes:
            if cls not in _registered_classes:
                if not cls.is_registered:
                    bpy.utils.register_class(cls)
                _registered_classes.append(cls)

        for menu_type in MENU_TYPES:
            record = (menu_type, draw_add_menu)
            if record not in _registered_menus:
                if draw_add_menu not in getattr(menu_type.draw, "_draw_funcs", ()):
                    menu_type.append(draw_add_menu)
                _registered_menus.append(record)
        _register_handlers()
        if not bpy.app.timers.is_registered(_startup_reconcile_tick):
            bpy.app.timers.register(_startup_reconcile_tick, first_interval=0.1)
        if (not bpy.app.background
                and not bpy.app.timers.is_registered(_gesture_router_tick)):
            bpy.app.timers.register(_gesture_router_tick, first_interval=0.1)
    except Exception as registration_error:
        try:
            unregister()
        except Exception as cleanup_error:
            raise ExceptionGroup(
                "Grade node registration and rollback both failed",
                [registration_error, cleanup_error],
            ) from registration_error
        raise


def unregister():
    global _preparation_runtime
    errors = []
    _clear_gestures()
    try:
        if bpy.app.timers.is_registered(_startup_reconcile_tick):
            bpy.app.timers.unregister(_startup_reconcile_tick)
    except Exception as exc:
        errors.append(exc)
    try:
        if bpy.app.timers.is_registered(_gesture_router_tick):
            bpy.app.timers.unregister(_gesture_router_tick)
    except Exception as exc:
        errors.append(exc)
    try:
        if bpy.app.timers.is_registered(_undo_redo_reconcile_tick):
            bpy.app.timers.unregister(_undo_redo_reconcile_tick)
    except Exception as exc:
        errors.append(exc)
    try:
        _unregister_handlers()
    except Exception as exc:
        errors.append(exc)

    try:
        if bpy.app.timers.is_registered(_preparation_tick):
            bpy.app.timers.unregister(_preparation_tick)
    except Exception as exc:
        errors.append(exc)
    if _preparation_runtime is not None:
        try:
            _preparation_runtime.close()
        except Exception as exc:
            errors.append(exc)
        _preparation_runtime = None
    _reset_node_stores()

    for menu_type, callback in reversed(tuple(_registered_menus)):
        try:
            menu_type.remove(callback)
        except ValueError:
            pass
        except Exception as exc:
            errors.append(exc)
            continue
        _registered_menus.remove((menu_type, callback))

    for cls in reversed(tuple(_registered_classes)):
        try:
            if cls.is_registered:
                bpy.utils.unregister_class(cls)
        except Exception as exc:
            errors.append(exc)
            continue
        _registered_classes.remove(cls)

    if errors:
        raise ExceptionGroup("Grade node teardown failed", errors)
