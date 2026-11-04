"""Guarded Grade nodes and their shared Linear and Tone settings UI."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from itertools import count
import hashlib
import json
import threading
from uuid import uuid4

import bpy
import numpy as np
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
    Settings,
    ToneSettings,
    prepare_linear,
    project_source_white_component,
)
from .kernel.graph import Graph
from .kernel.stage2_graph import build_stage2_group, PARAMETER_IMAGE, PARAMETER_BINDING
from .kernel.stage2_parameters import PARAMETER_SCHEMA, prepare_parameters
from .kernel.lut import (
    append_lut_lookup,
)
from .lut_gpu import PreparedStack as _PreparedStack
from .lut_helper import StackHelperBackend
from .kernel.settings import D65, SPACES
from .kernel.tone_ui import (
    TONE_DEFAULTS, TONE_FIELDS, TONE_LEVEL_FIELDS, TONE_LIMITS, TONE_PEAKS,
    clamp_tone_anchor,
)
from .policy import node as node_policy
from .runtime import gesture_coordinator as gesture_policy
from .runtime.preparation import PreparationRuntime
from .runtime.grade_preparation import GradePreparer
from .runtime.grade_resources import (
    GradeResources, SIGNATURE as PARAMETER_SIGNATURE, OWNER as PARAMETER_OWNER,
    OWNER_NODE as PARAMETER_OWNER_NODE,
)
from .runtime.publication import PublicationDeferred
from .runtime.resource_lifecycle import run_resource_lifecycle
from .runtime.image_publication import (
    ImageSnapshot, pack_image_for_save, run_image_publication, write_metadata,
)


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
_preparation_runtime = None
_grade_preparer = None
_grade_resources = None
_preparation_sources = {}
_gesture_state = gesture_policy.new()
_gesture_node_serial = count(1)
_gesture_nodes = {}
_gesture_invocations = {}
_KERNEL_SCHEMA = 3
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

_TONE_FIELDS = TONE_FIELDS


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
            if _is_grade_node(node) and any(
                    getattr(node, name).as_pointer() == pointer
                    for name in ("pg_linear", "pg_tone")):
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


def _copy_tone(source, target):
    with _suspend(target):
        for name in _TONE_FIELDS:
            setattr(target, name, getattr(source, name))


def _reset_tone(settings):
    with _suspend(settings):
        for name in _TONE_FIELDS:
            if settings.is_property_set(name):
                settings.property_unset(name)


def _make_grade(source=None):
    grade = bpy.data.node_groups.new("Grade", PGGradeData.bl_idname)
    try:
        if source is not None:
            if _is_grade_node(source):
                source = source.pg_grade
            if source is None:
                return grade
            _copy_linear(source.pg_linear, grade.pg_linear)
            _copy_tone(source.pg_tone, grade.pg_tone)
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
    if isinstance(settings, Settings):
        return _signature(tree_type, _snapshot_values(settings), working_space)
    owner = _holder(settings)
    snapshot = (_grade_settings(owner, working_space) if owner is not None
                else Settings(linear=_linear_settings(settings), space=working_space))
    return _signature(tree_type, _snapshot_values(snapshot), working_space)


def _signature(kind, values, working_space):
    payload = json.dumps(
        (_KERNEL_SCHEMA, kind, working_space, values),
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _tone_settings(settings):
    # RNA stores binary32 defaults; retain their exact declared portable values.
    defaults = ToneSettings()
    values = []
    import struct
    for name, default in zip(TONE_LEVEL_FIELDS, defaults.input_nits):
        value = float(getattr(settings, name))
        # Use the same binary32 round-trip as Blender's RNA storage.
        native_default = struct.unpack("f", struct.pack("f", default))[0]
        values.append(default if value == native_default else value)
    return ToneSettings(tuple(values), float(settings.fit), 203., float(settings.peak_nits))


def _grade_settings(owner, working_space):
    return Settings(linear=_linear_settings(owner.pg_linear),
                    tone=_tone_settings(owner.pg_tone), space=working_space)


def _snapshot_values(settings):
    if isinstance(settings, LinearSettings):
        settings = Settings(linear=settings)
    linear = settings.linear
    tone = settings.tone
    return tuple(float(value).hex() for value in (
        linear.exposure, *linear.source_xy,
        -linear.balance[0], -linear.balance[1],
        *linear.spread, *linear.heading,
        *tone.input_nits, tone.fit, tone.reference_nits, tone.peak_nits,
    ))


def _preparation_signature(settings, working_space):
    return _signature("grade-preparation", _snapshot_values(settings), working_space)


def _kernel(tree_type, prepared, working_space, signature, parameter_image=None):
    built = build_stage2_group(prepared, tree_type, parameter_image=parameter_image)
    tree = built.tree
    try:
        tree[_KERNEL_KIND] = _KERNEL_SCHEMA
        tree["_perceptual_grade_grade_kernel"] = True
        tree[_KERNEL_SIGNATURE] = signature
        tree[_KERNEL_QUALITY] = "full"
        tree["_perceptual_grade_tree_type"] = tree_type
        tree["_perceptual_grade_working_space"] = working_space
        for image in built.images:
            image["_perceptual_grade_image"] = signature
    except BaseException:
        built.dispose(unlink=True)
        raise
    return tree


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


def _settings_for_node(node, working_space=None):
    working_space = working_space or _working_space()
    if _is_stack_node(node):
        return tuple(
            _grade_settings(entry.grade, working_space)
            for entry in node.pg_stack_entries
            if entry.enabled and entry.grade is not None
        )
    if node.pg_grade is not None:
        return _grade_settings(node.pg_grade, working_space)
    return Settings(linear=_linear_settings(node.pg_linear),
                    tone=_tone_settings(node.pg_tone), space=working_space)


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
        if not kernel.get("_perceptual_grade_stack_kernel"):
            image = kernel.get(PARAMETER_BINDING)
            if (image is None or image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                    or kernel.get(PARAMETER_SIGNATURE) is None
                    or kernel.get(PARAMETER_SIGNATURE) != image.get(PARAMETER_SIGNATURE)):
                return False
        return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _kernel_error_text(node):
    return "Grade output is magenta" if node.get(_NODE_ERROR) else ""


def _apply_output_presentation(node, mode, error):
    values = {}
    if mode == "error":
        values[_NODE_ERROR] = str(error)[:240]
    elif mode != "current":
        values[_NODE_PENDING] = (
            "Updating - showing last-good result" if mode == "preview"
            else "Preparing Grade - showing identity preview"
        )
    for key in (_NODE_ERROR, _NODE_PENDING):
        if key in values:
            if node.get(key) != values[key]:
                node[key] = values[key]
        elif key in node:
            del node[key]
    custom = mode != "current"
    if node.use_custom_color != custom:
        node.use_custom_color = custom
    if custom:
        color = (0.65, 0.04, 0.04) if mode == "error" else (0.65, 0.32, 0.04)
        if any(abs(a-b) > 1e-6 for a, b in zip(node.color, color)):
            node.color = color


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
    if effects.output_mode is None:
        return
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
    if _grade_resources is not None:
        _grade_resources.forget(source)


def _kernel_belongs_to_node(node, kernel):
    if _is_stack_node(node):
        return True
    if kernel is None:
        return False
    owner, owner_node = _grade_resources.owner(node)
    return (kernel.get(PARAMETER_OWNER) == owner
            and kernel.get(PARAMETER_OWNER_NODE) == owner_node)


def _record_for(node, desired_signature=None, source=None):
    pointer = node.as_pointer()
    record = _node_stores.get(pointer)
    if record is not None and (source is None or record.get("source") is source):
        record["node"] = node
        return record
    previous_state = record["state"] if record is not None else None
    gesture_active = _gesture_is_active(pointer)
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
            and _kernel_belongs_to_node(node, kernel) \
            and _kernel_is_current(
                kernel, node.id_data.bl_idname, previous_state.applied_signature,
                previous_state.applied_quality or "full", stack=_is_stack_node(node)):
        applied_signature = previous_state.applied_signature
        applied_quality = previous_state.applied_quality or "full"
    elif (desired_signature is not None and _kernel_belongs_to_node(node, kernel) and _kernel_is_current(
            kernel, node.id_data.bl_idname, desired_signature,
            kernel_quality, stack=_is_stack_node(node))):
        applied_signature = desired_signature
        applied_quality = kernel_quality
    state = node_policy.new(
        desired_signature=desired_signature,
        applied_signature=applied_signature,
        applied_quality=applied_quality,
        gesture_active=gesture_active,
        grade_ids=_stack_grade_ids(node) if _is_stack_node(node) else (),
    )
    record = {"node": node, "state": state, "source": source,
              "stack": _is_stack_node(node)}
    _node_stores[pointer] = record
    return record


def _ensure_timer():
    if (_preparation_runtime is not None
            and (_preparation_runtime.pending or (_grade_resources is not None and _grade_resources.pending))
            and not bpy.app.timers.is_registered(_preparation_tick)):
        bpy.app.timers.register(_preparation_tick, first_interval=0.0)


def _consume_effects(node, effects, preparation=None, record=None, defer_build=False):
    if effects.dispose:
        try:
            _apply_node_disposal(node)
        except Exception as error:
            return (error,)
        return ()
    failures = []
    try:
        _apply_output_effect(node, effects)
    except Exception as error:
        failures.append(error)
        if effects.error is None and record is not None:
            record["state"], failed_effects = node_policy.step(
                record["state"], node_policy.Event(
                    "installation_result", None, str(error)))
            try:
                _apply_output_effect(node, failed_effects)
            except Exception as fallback_error:
                failures.append(fallback_error)
            return tuple(failures)

    if effects.rebuild:
        failures.extend(
            error for failed_nodes, error in _refresh_nodes((node,))
        )

    if effects.prepare_signature is not None:
        try:
            if preparation is None or _preparation_runtime is None:
                raise RuntimeError("Grade preparation inputs or runtime are unavailable")
            source, signature, settings, working_space, lane, progressive = preparation
            if signature != effects.prepare_signature:
                raise RuntimeError("Preparation effect does not match its snapshot")
            payload = settings if lane == "grade" else (settings, working_space)
            _preparation_runtime.request(
                source, signature, payload, lane=lane, progressive=progressive,
            )
            _ensure_timer()
        except Exception as error:
            failures.extend(_dispatch(node, node_policy.Event(
                "preparation_result", error=str(error),
                preparation_signature=effects.prepare_signature)))

    if effects.build_signature is not None and not defer_build:
        failures.extend(_fail_installation(
            (record or _record_for(node),), effects.build_signature,
            RuntimeError("Prepared Grade data is unavailable")))
    return tuple(failures)


def _dispatch_transition(node, record, event, preparation=None, defer_build=False):
    record["state"], effects = node_policy.step(record["state"], event)
    failures = _consume_effects(node, effects, preparation, record, defer_build=defer_build)
    return effects, failures


def _dispatch(node, event, preparation=None):
    global _reconciling
    desired_signature = event.signature if event.kind == "request" else None
    if event.kind == "dispose":
        # A free callback can also arrive for a node that never initialized.
        # Do not inspect its derived kernel or create a new subscription.
        record = _node_stores.get(node.as_pointer())
        if record is None:
            record = {"state": node_policy.new()}
    else:
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
        _reset_tone(node.pg_tone)
    source = _source_for(node, working_space)
    snapshot = None if snapshots is None else snapshots.get(source)
    if snapshot is None:
        snapshot = _settings_for_node(node, working_space)
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
        lane = "grade"
    record = _record_for(node, signature, source)
    state = record["state"]
    failures = []
    if (state.applied_signature is not None and not _kernel_is_current(
            node.node_tree, node.id_data.bl_idname, state.applied_signature,
            state.applied_quality or "full", stack=_is_stack_node(node))):
        failures.extend(_dispatch(node, node_policy.Event(
            "installation_result", None, "Installed Grade kernel is missing or stale")))
    failures.extend(_dispatch(
        node, node_policy.Event(
            "request", signature,
            preparation_signature=preparation_signature,
        ),
        (source, preparation_signature, snapshot, working_space, lane,
         lane == "lut" and bool(state.gesture_active)),
    ))
    return tuple(failures)


def _publication_signature(record, prepared):
    if record["stack"]:
        if not isinstance(prepared, _PreparedStack):
            raise TypeError("LUT preparation returned an invalid Stack result")
        return _stack_signature(prepared.settings, prepared.space)
    prepared_settings = Settings(
        linear=prepared.linear.settings,
        tone=prepared.tone.settings,
        space=prepared.space,
    )
    return _signature(
        record["node"].id_data.bl_idname,
        _snapshot_values(prepared_settings),
        prepared.space,
    )


def _handle_preparation_result(source, preparation_signature, prepared, error,
                               quality="full", lane="grade"):
    global _reconciling
    failures = []
    authorized_builds = {}
    previous_reconciling = _reconciling
    _reconciling = True
    try:
        for record in tuple(_node_stores.values()):
            if record.get("source") is not source:
                continue
            if ((record["stack"] and lane != "lut")
                    or (not record["stack"] and lane != "grade")):
                continue
            if error is not None:
                signature = None
            else:
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
                node_policy.Event("preparation_result", signature,
                                       None if error is None else str(error),
                                       quality=quality,
                                       preparation_signature=preparation_signature),
                defer_build=True,
            )
            failures.extend(transition_failures)
            if effects.build_signature is not None:
                build_quality = effects.build_quality
                authorized_builds.setdefault(
                    (effects.build_signature, build_quality), []
                ).append(record)
        grade_records = []
        for (signature, build_quality), records in authorized_builds.items():
            if records[0]["stack"]:
                failures.extend(_build_and_install(
                    signature, tuple(records), prepared, build_quality
                ))
            else:
                grade_records.extend(records)
        if grade_records:
            failures.extend(_publish_grade_parameters(source, tuple(grade_records), prepared))
    finally:
        _reconciling = previous_reconciling
    return tuple(failures)


def _write_grade_parameters(image, pixels):
    """The only ordinary Grade numerical mutation: update one bound image."""
    image.pixels.foreach_set(pixels.ravel())
    image.update()


def _pack_grade_parameters(image):
    # Blender checks dirty images before save_pre runs. Keep this small derived
    # snapshot packed at publication, including restoration after a failed write.
    image.pack()


def _publish_grade_parameters(source, authorized_records, prepared):
    """Consume publication effects once for all users of an authoritative Grade."""
    users = tuple(record for record in authorized_records
                  if record.get("source") is source
                  and _node_stores.get(record["node"].as_pointer()) is record)
    if not users:
        return ()
    created = []
    context = {}
    failures = []

    def prepare(_errors):
        parameters = prepared.parameters or prepare_parameters(prepared)
        resource = _grade_resources.resource(users[0]["node"], prepared.space)
        for record in users:
            tree_type = record["node"].id_data.bl_idname
            kernel = resource.trees.get(tree_type)
            if kernel is not None:
                # Native undo may have replaced a cached host identity.
                try:
                    valid = (kernel.get(_KERNEL_KIND) == _KERNEL_SCHEMA
                             and kernel.get("_perceptual_grade_stage2_complete"))
                except ReferenceError:
                    valid = False
                if valid:
                    continue
            kernel = _kernel(
                tree_type, prepared, prepared.space,
                _publication_signature(record, prepared), resource.image,
            )
            created.append(kernel)
            resource = _grade_resources.remember(record["node"], prepared.space, kernel)
        image = resource.image
        preparation_signature = _preparation_signature(
            Settings(linear=prepared.linear.settings, tone=prepared.tone.settings,
                     space=prepared.space), prepared.space)
        metadata = [(image, PARAMETER_SIGNATURE, preparation_signature)]
        for tree_type, kernel in resource.trees.items():
            signature = _signature(
                tree_type, _snapshot_values(Settings(
                    linear=prepared.linear.settings, tone=prepared.tone.settings,
                    space=prepared.space)), prepared.space)
            metadata.extend(((kernel, _KERNEL_SIGNATURE, signature),
                             (kernel, PARAMETER_SIGNATURE, preparation_signature)))
        context.update(resource=resource, image=image, parameters=parameters,
                       signature=preparation_signature, metadata=tuple(metadata))

    def snapshot(_errors):
        image = context["image"]
        context["snapshot"] = ImageSnapshot.capture(image, context["metadata"])
        return {"matching": image.get(PARAMETER_SIGNATURE) == context["signature"],
                "clean": image.packed_file is not None and not image.is_dirty}

    def upload(_errors):
        _write_grade_parameters(context["image"], context["parameters"].pixels)

    def pack(_errors):
        image = context["image"]
        _pack_grade_parameters(image)
        return {"clean": image.packed_file is not None and not image.is_dirty}

    def commit(_errors):
        write_metadata(context["metadata"])

    def restore_upload(_errors):
        _write_grade_parameters(context["image"], context["snapshot"].pixels)

    def restore_metadata(_errors):
        write_metadata(context["snapshot"].metadata)

    def fail(errors):
        error = errors[0]
        for secondary in errors[1:]:
            error.add_note(f"Additional Grade publication failure: {secondary}")
        affected = tuple(record for record in _node_stores.values()
                         if record.get("source") is source)
        for record in affected or users:
            try:
                pointer = record["node"].as_pointer()
                if not pointer or _node_stores.get(pointer) is not record:
                    continue
                failures.extend(((record["node"],), failure)
                                for failure in _fail_installation((record,), None, error))
            except ReferenceError as failure:
                # Removed RNA cannot receive presentation, but its failure is
                # still reported without putting a dead handle in diagnostics.
                failures.append(((), failure))
            except Exception as failure:
                # A dead native consumer must not prevent the same authorized
                # failure effect from reaching its surviving shared users.
                failures.append(((record["node"],), failure))
                print("Perceptual Grade failure presentation failed:", failure)

    def deliver(_errors):
        resource = context["resource"]
        for record in users:
            node = record["node"]
            signature = _publication_signature(record, prepared)
            try:
                kernel = resource.trees[node.id_data.bl_idname]
                if node.node_tree != kernel:
                    previous = _replace_node_kernel(node, kernel)
                    if previous != kernel:
                        failures.extend(((node,), error)
                                        for error in _retire_kernels((previous,)))
                failures.extend(((node,), failure) for failure in _dispatch(
                    node, node_policy.Event("installation_result", signature)))
            except Exception as error:
                failures.extend(((node,), failure) for failure in _dispatch(
                    node, node_policy.Event("installation_result", signature, str(error))))

    def retire(_errors):
        errors = _retire_kernels(created)
        if errors:
            raise ExceptionGroup("Grade resource retirement failed", list(errors))

    transaction_errors = run_image_publication({
        "prepare": prepare, "snapshot": snapshot, "upload": upload, "pack": pack,
        "commit": commit, "restore_upload": restore_upload, "restore_pack": pack,
        "restore_metadata": restore_metadata, "deliver": deliver, "fail": fail,
        "retire": retire,
    })
    diagnostic_nodes = []
    for record in tuple(_node_stores.values()):
        if record.get("source") is not source:
            continue
        try:
            if record["node"].as_pointer():
                diagnostic_nodes.append(record["node"])
        except ReferenceError:
            continue
    for error in transaction_errors:
        failures.append((tuple(diagnostic_nodes), error))
        print("Perceptual Grade image publication failed:", error)
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
                failures.extend(_dispatch(node, node_policy.Event(
                    "installation_result", signature, str(error), quality=quality)))
                continue
            if previous != kernel:
                _retire_kernels((previous,))
            failures.extend(_dispatch(node, node_policy.Event(
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
        failures.extend(_dispatch(record["node"], node_policy.Event(
            "installation_result", signature, str(error), quality=quality)))
    return tuple(failures)


def _queue_preparation_completions(completions):
    for publication in completions:
        if _grade_resources is not None:
            source = publication.source if hasattr(publication, "source") else publication[0]
            lane = getattr(publication, "lane", "grade")
            _grade_resources.pending[(source, lane)] = publication


def _publish_pending_preparations(*, drain=False):
    """Consume mailboxes only inside an admitted publication/preflight scope."""
    failures = []
    # One complete source per foreground turn. This bounds the amount of host
    # work without imposing a preview frequency or a settling delay.
    keys = tuple(_grade_resources.pending) if drain else tuple(_grade_resources.pending)[:1]
    for key in keys:
        publication = _grade_resources.pending.pop(key)
        failures.extend(_consume_preparation_publication(publication))
    return tuple(failures)


def _handle_preparation_completions(completions):
    _queue_preparation_completions(completions)
    if _grade_resources is None:
        return ()
    try:
        with _grade_resources.gate.commit():
            return _publish_pending_preparations()
    except PublicationDeferred:
        return ()


def _consume_preparation_publication(publication):
    if hasattr(publication, "quality"):
        return _handle_preparation_result(
            publication.source, publication.signature, publication.prepared,
            publication.error, publication.quality, publication.lane,
        )
    source, signature, prepared, error = publication
    return _handle_preparation_result(source, signature, prepared, error)


def _preparation_tick():
    if _preparation_runtime is None:
        return None
    try:
        _preparation_runtime.pump_main_thread()
        _handle_preparation_completions(_preparation_runtime.collect())
    except Exception as error:
        _block_nodes(tuple(_all_grade_nodes()), error)
        print("Perceptual Grade asynchronous preparation failed:", error)
    pending = _preparation_runtime.pending or bool(_grade_resources and _grade_resources.pending)
    if not pending:
        return None
    if _grade_resources is not None and _grade_resources.gate.blocked():
        return 0.02
    return 0.0


def _resource_retirement_operations(resource, *, image=False):
    def observe():
        try:
            if resource is None or resource.as_pointer() == 0:
                return {"live": False}
            owned = (bool(resource.get("_perceptual_grade_stack_image")
                          or resource.get("_perceptual_grade_image")) if image
                     else resource.get(_KERNEL_KIND) is not None)
            return {"live": True, "owned": owned, "users": resource.users,
                    "protected": resource.use_fake_user}
        except ReferenceError:
            return {"live": False}

    def evict():
        if _grade_resources is not None:
            if image:
                _grade_resources.retire_image(resource)
            else:
                _grade_resources.retire(resource)

    def remove():
        collection = bpy.data.images if image else bpy.data.node_groups
        collection.remove(resource, do_unlink=False)

    return {"observe": observe, "evict": evict, "recheck": observe, "remove": remove}


def _retire_kernels(kernels):
    failures = []
    seen = set()
    for kernel in kernels:
        if kernel is None:
            continue
        # Object identity remains usable after Blender invalidates its RNA wrapper.
        identity = id(kernel)
        if identity in seen:
            continue
        seen.add(identity)
        errors = run_resource_lifecycle(_resource_retirement_operations(kernel))
        failures.extend(errors)
        for error in errors:
            print("Perceptual Grade kernel retirement failed:", error)
    failures.extend(_retire_images())
    return tuple(failures)


def _retire_images():
    failures = []
    for image in tuple(bpy.data.images):
        errors = run_resource_lifecycle(_resource_retirement_operations(image, image=True))
        failures.extend(errors)
        for error in errors:
            print("Perceptual Grade image retirement failed:", error)
    return tuple(failures)


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
                node_policy.Event("installation_result", signature, message),
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


def _apply_node_disposal(node):
    """Consume disposal once, retiring cache entries before Blender data."""
    pointer = node.as_pointer()
    kernel = node.node_tree

    def fence():
        # Subscription identity is gone before cancellation/gesture callbacks run.
        _forget_node(node)
        _forget_gesture_node(node)

    def detach():
        _syncing.add(pointer)
        try:
            if _is_grade_node(node):
                node.pg_grade = None
            node.node_tree = None
        finally:
            _syncing.discard(pointer)

    operations = _resource_retirement_operations(kernel)
    operations.update(fence=fence, detach=detach)
    failures = run_resource_lifecycle(operations, disposal=True)
    if not failures:
        failures += _retire_images()
    if failures:
        raise ExceptionGroup("Grade resource disposal failed", list(failures))


def _dispose_node(node):
    failures = _dispatch(node, node_policy.Event("dispose"))
    if failures:
        raise RuntimeError("Could not dispose Grade resources: "
                           + "; ".join(map(str, failures))) from failures[0]


def _reset_node_stores():
    sources = tuple(_preparation_sources.values())
    _node_stores.clear()
    _preparation_sources.clear()
    if _grade_resources is not None:
        _grade_resources.clear()
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
    failures = _dispatch(node, node_policy.Event(
        "stack_replace", grade_ids=_stack_grade_ids(node)))
    if failures:
        print("Perceptual Grade Stack update failed:", failures[-1])


def _refresh_stack_policy(node):
    failures = _dispatch(node, node_policy.Event(
        "stack_replace", grade_ids=_stack_grade_ids(node)))
    if failures:
        print("Perceptual Grade Stack update failed:", failures[-1])


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
    identity = _gesture_identity_for_pointer(pointer)
    return identity is not None and gesture_policy.armed_for(_gesture_state, identity)


def _gesture_is_active(pointer):
    identity = _gesture_identity_for_pointer(pointer)
    return identity is not None and gesture_policy.active_for(_gesture_state, identity)


def _gesture_identity_for_pointer(pointer):
    for identity, node in _gesture_nodes.items():
        try:
            if node.as_pointer() == pointer:
                return identity
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return None


def _gesture_identity(node):
    identity = _gesture_identity_for_pointer(node.as_pointer())
    if identity is None:
        identity = next(_gesture_node_serial)
        _gesture_nodes[identity] = node
    return identity


def _gesture_node(identity):
    node = _gesture_nodes.get(identity)
    try:
        return node if node is not None and node.as_pointer() and _is_output_node(node) else None
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def _gesture_token(window_key):
    return gesture_policy.current_gesture(_gesture_state, window_key)


def _gesture_phase(window_key):
    return gesture_policy.gesture_phase(_gesture_state, window_key)


def _gesture_observer_token(window_key):
    return gesture_policy.current_observer(_gesture_state, window_key)


def _gesture_observations(window_key):
    observed = []
    for target in gesture_policy.gesture_targets(_gesture_state, window_key):
        node = _gesture_node(target.node_id)
        if node is not None:
            observed.append(gesture_policy.Target(target.node_id, _settings_signature_for(node)))
    return tuple(observed)


def _gesture_target_at(window, x, y):
    """Resolve a sidebar press in the window-level modal event context."""
    if window is None:
        return None
    for area in window.screen.areas:
        if area.type != "NODE_EDITOR":
            continue
        space = area.spaces.active
        if not space.show_region_ui:
            continue
        for region in area.regions:
            if (region.type == "UI" and region.width > 1 and region.height > 1
                    and region.x <= x < region.x + region.width
                    and region.y <= y < region.y + region.height):
                tree = space.edit_tree
                active = getattr(getattr(tree, "nodes", None), "active", None)
                return active if _is_output_node(active) else None
    return None


def _live_gesture_targets(targets):
    live = []
    for target in targets:
        try:
            if target.as_pointer() and _is_output_node(target):
                live.append(target)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return tuple(live)


def _forget_gesture_node(node):
    """Consume node disposal without ending gestures on surviving users."""
    identity = _gesture_identity_for_pointer(node.as_pointer())
    if identity is not None:
        _dispatch_gesture(gesture_policy.Event("node_disposed", node_id=identity))


def _settings_signature_for(node):
    try:
        space = _working_space()
        if _is_stack_node(node):
            settings = tuple(
                _grade_settings(entry.grade, space)
                for entry in node.pg_stack_entries
                if entry.enabled and entry.grade is not None
            )
            return _stack_signature(settings, space)
        return _signature(
            node.id_data.bl_idname,
            _snapshot_values(_settings_for_node(node, space)),
            space,
        )
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None


def _arm_gesture(window_key, node, position):
    """Explicit adapter entrypoint; native routing supplies its observer token."""
    _dispatch_gesture(gesture_policy.Event(
        "press", window_id=window_key, x=int(position[0]), y=int(position[1]),
        undo_owner="adapter",
        targets=tuple(gesture_policy.Target(_gesture_identity(target),
                                           _settings_signature_for(target))
                      for target in _live_gesture_targets(_gesture_related_nodes(node))),
        observed=_gesture_observations(window_key),
    ))
    return _gesture_token(window_key)


def _activate_gesture(window_key, token):
    _dispatch_gesture(gesture_policy.Event("activate", window_id=window_key,
                                          gesture_token=token))
    return None


def _begin_gesture(window_key, node):
    """Begin an explicit adapter-owned gesture."""
    token = _arm_gesture(window_key, node, (0, 0))
    _activate_gesture(window_key, token)
    return token


def _end_gesture(window_key, token):
    """Synchronous completion for explicit adapters with already-settled settings."""
    _dispatch_gesture(gesture_policy.Event("finish", window_id=window_key,
                                          gesture_token=token,
                                          observed=_gesture_observations(window_key)))
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


def _gesture_finished(event):
    return ((event.type == "LEFTMOUSE" and event.value == "RELEASE")
            or (event.type in {"ESC", "RIGHTMOUSE"} and event.value in {"PRESS", "RELEASE"})
            or event.type == "WINDOW_DEACTIVATE")


def _observe_gesture_finish(window_key, token):
    """Observe after the native widget has applied release/cancel restoration."""
    _dispatch_gesture(gesture_policy.Event(
        "finish_observed", window_id=window_key, gesture_token=token,
        observed=_gesture_observations(window_key),
    ))
    return None


def _handoff_gesture_router(window_key, router_token, gesture_token):
    """Observe the gesture after Blender installs its native button handler."""
    _dispatch_gesture(gesture_policy.Event(
        "handoff_due", window_id=window_key, token=router_token,
        gesture_token=gesture_token,
    ))
    return None


def _gesture_window(window_key):
    for manager in bpy.data.window_managers:
        for window in manager.windows:
            if window.as_pointer() == window_key:
                return window
    return None


def _invoke_gesture_observer(action):
    success = False
    receipt = {"observation": None, "error": None}
    _gesture_invocations[action.token] = receipt
    try:
        window = _gesture_window(action.window_id)
        if window is not None:
            with bpy.context.temp_override(window=window):
                result = bpy.ops.perceptual_grade.gesture_router(
                    "INVOKE_DEFAULT", observer_token=action.token,
                )
            success = result == {"RUNNING_MODAL"} and receipt["observation"] is not None
    except Exception as error:
        receipt["error"] = error
    observation = receipt["observation"]
    latest, x, y = observation if observation is not None else ("none", 0, 0)
    try:
        _dispatch_gesture(gesture_policy.Event(
            "observer_install_result", window_id=action.window_id, token=action.token,
            gesture_token=action.gesture_token, success=success, latest=latest, x=x, y=y,
        ))
    finally:
        _gesture_invocations.pop(action.token, None)


def _consume_gesture_effects(effects):
    refresh = []

    def flush_refresh():
        if refresh:
            _refresh_nodes(tuple(refresh))
            refresh.clear()

    for action in effects.actions:
        if action.kind in ("refresh", "node_begin"):
            node = _gesture_node(action.node_id)
            if node is not None:
                if action.kind == "node_begin":
                    failures = _dispatch(node, node_policy.Event("gesture_begin"))
                    if failures:
                        print("Perceptual Grade gesture transition failed:", failures[-1])
                refresh.append(node)
            continue
        flush_refresh()
        if action.kind == "invoke_observer":
            _invoke_gesture_observer(action)
        elif action.kind == "schedule_handoff":
            bpy.app.timers.register(partial(
                _handoff_gesture_router, action.window_id, action.token,
                action.gesture_token), first_interval=0.0)
        elif action.kind == "schedule_finish":
            bpy.app.timers.register(partial(
                _observe_gesture_finish, action.window_id, action.gesture_token),
                first_interval=0.0)
        elif action.kind == "node_release":
            node = _gesture_node(action.node_id)
            if node is not None:
                failures = _dispatch(node, node_policy.Event("gesture_release"))
                if failures:
                    print("Perceptual Grade gesture transition failed:", failures[-1])
        elif action.kind == "forget_node":
            _gesture_nodes.pop(action.node_id, None)
        elif action.kind == "clear_registry":
            _gesture_nodes.clear()
            _gesture_invocations.clear()
        elif action.kind == "report_install_failure":
            print("Perceptual Grade could not install gesture observer for window",
                  action.window_id, ":", _gesture_invocations.get(action.token, {}).get("error")
                  or "Blender did not retain the modal observer")
    flush_refresh()
    if effects.undo_window is not None:
        _push_gesture_undo(effects.undo_window)


def _dispatch_gesture(event):
    global _gesture_state
    _gesture_state, effects = gesture_policy.step(_gesture_state, event)
    _consume_gesture_effects(effects)


class PG_OT_gesture_router(bpy.types.Operator):
    bl_idname = "perceptual_grade.gesture_router"
    bl_label = "Perceptual Grade Gesture Router"
    bl_options = {"INTERNAL", "MODAL_PRIORITY"}

    observer_token: IntProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        window = context.window
        if window is None:
            return {"CANCELLED"}
        self.window_key = window.as_pointer()
        self.token = self.observer_token
        if (gesture_policy.observer_status(_gesture_state, self.window_key, self.token) != "pending"
                or self.token not in _gesture_invocations):
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        # INVOKE_DEFAULT observes the window's latest event. Installation is
        # acknowledged by the consumer before this observation affects policy.
        receipt = _gesture_invocations.get(self.token)
        if (receipt is None or gesture_policy.observer_status(
                _gesture_state, self.window_key, self.token) != "pending"):
            return {"CANCELLED"}
        latest = "finish" if _gesture_finished(event) else "move"
        receipt["observation"] = latest, int(event.mouse_x), int(event.mouse_y)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        admission = gesture_policy.observer_status(_gesture_state, self.window_key, self.token)
        if admission == "pending":
            return {"PASS_THROUGH"}
        if admission == "stale":
            return {"CANCELLED", "PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            active = _gesture_target_at(context.window, event.mouse_x, event.mouse_y)
            if active is not None:
                _dispatch_gesture(gesture_policy.Event(
                    "press", window_id=self.window_key, token=self.token,
                    x=int(event.mouse_x), y=int(event.mouse_y), undo_owner="native",
                    targets=tuple(gesture_policy.Target(_gesture_identity(target),
                                                       _settings_signature_for(target))
                                  for target in _live_gesture_targets(
                                      _gesture_related_nodes(active))),
                    observed=_gesture_observations(self.window_key),
                ))
        elif event.type == "MOUSEMOVE":
            _dispatch_gesture(gesture_policy.Event(
                "move", window_id=self.window_key, token=self.token,
                gesture_token=_gesture_token(self.window_key),
                x=int(event.mouse_x), y=int(event.mouse_y),
            ))
        elif _gesture_finished(event):
            _dispatch_gesture(gesture_policy.Event(
                "finish_requested", window_id=self.window_key, token=self.token,
                gesture_token=_gesture_token(self.window_key),
            ))
        return {"PASS_THROUGH"}

    def cancel(self, _context):
        if hasattr(self, "window_key") and hasattr(self, "token"):
            _dispatch_gesture(gesture_policy.Event(
                "observer_lost", window_id=self.window_key, token=self.token))


def _gesture_router_tick():
    if not _registered_classes or PG_OT_gesture_router not in _registered_classes:
        return None
    try:
        managers = tuple(bpy.data.window_managers)
    except (AttributeError, ReferenceError, RuntimeError):
        managers = (bpy.context.window_manager,)
    live_windows = set()
    for manager in managers:
        for window in tuple(getattr(manager, "windows", ())):
            key = window.as_pointer()
            live_windows.add(key)
            try:
                _dispatch_gesture(gesture_policy.Event("window_seen", window_id=key))
            except (AttributeError, ReferenceError, RuntimeError):
                continue
    for observer in _gesture_state.observers:
        if observer.window_id not in live_windows:
            _dispatch_gesture(gesture_policy.Event(
                "window_gone", window_id=observer.window_id,
                observed=_gesture_observations(observer.window_id),
            ))
    return 0.5


def _clear_gestures():
    _dispatch_gesture(gesture_policy.Event("reset"))


def _stack_active_grade(node):
    if not node.pg_stack_entries:
        return None
    index = min(max(0, node.pg_active_index), len(node.pg_stack_entries) - 1)
    item = node.pg_stack_entries[index]
    return item.grade if item.enabled else None


def _grade_changed(grade):
    users = []
    failures = []
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
                    failures.extend(
                        (node, error) for error in _dispatch(
                            node, node_policy.Event(
                                "grade_changed", grade_ids=(grade.as_pointer(),)
                            ),
                        )
                    )
            except (AttributeError, ReferenceError, RuntimeError):
                continue
    failures.extend(_refresh_nodes(tuple(node for node in users
                                         if not _gesture_is_armed(node.as_pointer()))))
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
        _clear_gestures()
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
def _render_pre(scene):
    if _grade_resources is None:
        return
    gate = _grade_resources.gate
    with gate.callback():
        ticket = gate.request_render_preflight(0)
    if threading.current_thread() is threading.main_thread():
        try:
            _service_render_preflight(defer=False)
        except PublicationDeferred as error:
            # A synchronous host call cannot wait for its own foreground
            # timer. Revoke output before evaluation without writing images.
            _block_nodes(tuple(_all_grade_nodes()), error)
    else:
        # Blender invokes this callback from its render worker. Release the GIL
        # while its pre-evaluation boundary waits for a foreground timer turn.
        ticket.wait()


def _service_render_preflight(*, defer=True):
    if _grade_resources is None:
        return
    gate = _grade_resources.gate
    ticket = gate.take_render_preflight()
    if ticket is not None:
        try:
            with gate.render_preflight(ticket, defer=defer):
                try:
                    _ensure_all_kernels()
                    _drain_preparations_in_scope()
                except Exception as error:
                    _block_nodes(tuple(_all_grade_nodes()), error)
                    raise
        except PublicationDeferred:
            if not defer:
                raise


def _render_preflight_tick():
    if _grade_resources is None:
        return None
    try:
        _service_render_preflight()
    except Exception as error:
        print("Perceptual Grade render preparation failed:", error)
    return 0.02 if _grade_resources.gate.has_render_preflight else 0.1


@persistent
def _render_init(scene, *_args):
    if _grade_resources is not None:
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_started("render", 0)


@persistent
def _render_finished(scene, *_args):
    if _grade_resources is not None:
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_finished("render", 0)


@persistent
def _compositor_pre(scene, *_args):
    if _grade_resources is not None:
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_started("compositor", 0)


@persistent
def _compositor_finished(scene, *_args):
    if _grade_resources is not None:
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_finished("compositor", 0)


@persistent
def _save_pre(_filepath):
    # Pixels are derived from authoritative settings. Save committed buffers;
    # file-load reconciliation repairs any saved preview against those settings.
    for image in bpy.data.images:
        pack_image_for_save(image, generated=image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA,
                            pack=_pack_grade_parameters)


def _drain_preparations():
    """Explicit synchronous bridge for quiescent, main-thread callers."""
    if _grade_resources is None:
        return ()
    with _grade_resources.gate.commit():
        return _drain_preparations_in_scope()


def _drain_preparations_in_scope():
    if _preparation_runtime is None:
        return ()
    failures = []
    sources = tuple({record["source"] for record in _node_stores.values()
                     if record.get("source") is not None})
    # The async barrier waits only for preparation, never for Blender mutation.
    try:
        _queue_preparation_completions(_preparation_runtime.wait(sources))
        failures.extend(_publish_pending_preparations(drain=True))
    except Exception as error:
        # Blender need not abort a render when a handler raises. Revoke output
        # through the machine before returning to the host.
        failures.extend(_block_nodes(tuple(record["node"] for record in _node_stores.values()), error))
    for record in tuple(_node_stores.values()):
        state = record["state"]
        node = record["node"]
        if (not node_policy.output_allowed(state)
                or not _kernel_is_current(
                    node.node_tree, node.id_data.bl_idname, state.desired_signature,
                    state.applied_quality or "full", stack=record["stack"])):
            failures.extend(_dispatch(node, node_policy.Event(
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


def _tone_changed(settings, _context):
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
        _reset_tone(settings)


def _tone_anchor_changed(index):
    def update(settings, context):
        pointer = settings.as_pointer()
        if pointer in _syncing:
            return
        holder = _holder(settings)
        if holder is None:
            return
        name = TONE_LEVEL_FIELDS[index]
        controls = _tone_settings(settings)
        value = clamp_tone_anchor(controls, index, float(getattr(settings, name)))
        if abs(value - getattr(settings, name)) > 1e-6:
            with _suspend(settings):
                setattr(settings, name, value)
        _tone_changed(settings, context)
    return update


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
        _reset_tone(node.pg_tone)
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


def _output_node_from_context(context):
    node = getattr(context, "pg_stack_node", None)
    if _is_stack_node(node):
        return node
    node = _node_from_context(context)
    if node is not None:
        return node
    space = getattr(context, "space_data", None)
    tree = getattr(space, "edit_tree", None)
    node = getattr(getattr(tree, "nodes", None), "active", None)
    return node if _is_output_node(node) else None


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


class PGToneSettings(bpy.types.PropertyGroup):
    input_black: FloatProperty(name="Black", default=TONE_DEFAULTS["input_black"],
        min=TONE_LIMITS[0][0], max=TONE_LIMITS[0][1], precision=3,
        update=_tone_anchor_changed(0))
    input_shadows: FloatProperty(name="Shadows", default=TONE_DEFAULTS["input_shadows"],
        min=TONE_LIMITS[1][0], max=TONE_LIMITS[1][1], precision=3,
        update=_tone_anchor_changed(1))
    input_midtones: FloatProperty(name="Midtones", default=TONE_DEFAULTS["input_midtones"],
        min=TONE_LIMITS[2][0], max=TONE_LIMITS[2][1], precision=2,
        update=_tone_anchor_changed(2))
    input_white: FloatProperty(name="White", default=TONE_DEFAULTS["input_white"],
        min=TONE_LIMITS[3][0], max=TONE_LIMITS[3][1], precision=2,
        update=_tone_anchor_changed(3))
    input_highlights: FloatProperty(name="Highlights", default=TONE_DEFAULTS["input_highlights"],
        min=TONE_LIMITS[4][0], max=TONE_LIMITS[4][1], precision=1,
        update=_tone_anchor_changed(4))
    fit: FloatProperty(name="Fit", default=0.0, min=-2.0, max=2.0,
        precision=2, update=_tone_changed)
    peak_nits: EnumProperty(name="Peak", default="1000",
        items=[(str(peak), f"{peak} nits", "") for peak in TONE_PEAKS],
        update=_tone_changed)


class PGGradeData(bpy.types.NodeTree):
    bl_idname = "PGGradeData"
    bl_label = "Grade"
    bl_icon = "COLOR"

    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_tone: PointerProperty(type=PGToneSettings)

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
        row.alignment = "EXPAND"
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
    pending = node.get(_NODE_PENDING)
    if pending:
        layout.label(text=pending, icon="TIME")
    error = node.get(_NODE_ERROR)
    if error:
        layout.label(text=_kernel_error_text(node), icon="ERROR")
        layout.label(text=error)


def _draw_stack_settings(node, layout):
    grade = _stack_active_grade(node)
    if grade is None:
        return
    layout.separator()
    layout.label(text=grade.name, icon="COLOR")
    settings = grade.pg_linear
    for field in _LINEAR_FIELDS:
        layout.prop(settings, field, slider=field not in {"source_x", "source_y"})


def _draw_tone_settings(node, layout):
    layout.context_pointer_set("pg_stack_node" if _is_stack_node(node) else "pg_node", node)
    grade = _stack_active_grade(node) if _is_stack_node(node) else node.pg_grade
    settings = grade.pg_tone if grade is not None else (
        node.pg_tone if _is_grade_node(node) else None
    )
    if settings is None:
        return
    column = layout.column()
    column.enabled = grade is not None
    for field in TONE_LEVEL_FIELDS:
        column.prop(settings, field, slider=True)
    column.prop(settings, "fit", slider=True)
    column.prop(settings, "peak_nits")
    column.label(text="Reference: 203 nits")
    column.operator(PG_OT_reset_tone.bl_idname, icon="LOOP_BACK")


class PGShaderGradeStack(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGradeStack"
    bl_label = "Grade Stack"
    bl_width_default = 320
    pg_stack_entries: CollectionProperty(type=PGStackEntry)
    pg_active_index: IntProperty(default=0, min=0, update=_stack_focus_changed)

    def init(self, _context):
        self["_perceptual_grade_stack"] = 1

    def draw_buttons(self, context, layout):
        _draw_stack_node(self, context, layout)

    def draw_buttons_ext(self, context, layout):
        _draw_stack_node(self, context, layout)

    def free(self):
        _dispose_node(self)


class PGCompositorGradeStack(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGradeStack"
    bl_label = "Grade Stack"
    bl_width_default = 320
    pg_stack_entries: CollectionProperty(type=PGStackEntry)
    pg_active_index: IntProperty(default=0, min=0, update=_stack_focus_changed)

    def init(self, _context):
        self["_perceptual_grade_stack"] = 1

    def draw_buttons(self, context, layout):
        _draw_stack_node(self, context, layout)

    def draw_buttons_ext(self, context, layout):
        _draw_stack_node(self, context, layout)

    def free(self):
        _dispose_node(self)


class PGShaderGrade(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGrade"
    bl_label = "Grade"
    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_tone: PointerProperty(type=PGToneSettings)
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
        _dispose_node(self)


class PGCompositorGrade(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGrade"
    bl_label = "Grade"
    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_tone: PointerProperty(type=PGToneSettings)
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
        _dispose_node(self)


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
        source = node.pg_grade
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


class PG_OT_reset_tone(bpy.types.Operator):
    bl_idname = "perceptual_grade.reset_tone"
    bl_label = "Reset Tone"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _output_node_from_context(context)
        if node is None:
            return False
        return (_stack_active_grade(node) if _is_stack_node(node)
                else node.pg_grade) is not None

    def execute(self, context):
        node = _output_node_from_context(context)
        if node is None:
            return {"CANCELLED"}
        grade = _stack_active_grade(node) if _is_stack_node(node) else node.pg_grade
        if grade is None:
            return {"CANCELLED"}
        _reset_tone(grade.pg_tone)
        _grade_changed(grade)
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
            _draw_stack_settings(node, self.layout)
            return
        node = _node_from_context(context)
        if node is None:
            space = getattr(context, "space_data", None)
            tree = getattr(space, "edit_tree", None)
            node = getattr(getattr(tree, "nodes", None), "active", None)
            if _is_stack_node(node):
                _draw_stack_node(node, context, self.layout)
                _draw_stack_settings(node, self.layout)
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


class PG_PT_tone(bpy.types.Panel):
    bl_idname = "PG_PT_tone"
    bl_label = "Tone"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Perceptual Grade"

    @classmethod
    def poll(cls, context):
        return PG_PT_linear.poll(context)

    def draw(self, context):
        node = _output_node_from_context(context)
        if _is_output_node(node):
            _draw_tone_settings(node, self.layout)


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
        (bpy.app.handlers.render_init, _render_init),
        (bpy.app.handlers.render_complete, _render_finished),
        (bpy.app.handlers.render_cancel, _render_finished),
        (bpy.app.handlers.composite_pre, _compositor_pre),
        (bpy.app.handlers.composite_post, _compositor_finished),
        (bpy.app.handlers.composite_cancel, _compositor_finished),
        (bpy.app.handlers.save_pre, _save_pre),
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
    global _preparation_runtime, _grade_preparer, _grade_resources
    classes = (
        PGLinearSettings,
        PGToneSettings,
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
        PG_OT_reset_tone,
        PG_OT_add_grade,
        PG_OT_add_stack,
        PG_OT_stack_action,
        PG_OT_new_stack_grade,
        PG_OT_gesture_router,
        PG_PT_linear,
        PG_PT_tone,
    )
    try:
        if _preparation_runtime is None:
            _grade_resources = GradeResources(bpy)
            _grade_preparer = GradePreparer(workers=3)
            _preparation_runtime = PreparationRuntime(default_lane="grade")
            _preparation_runtime.register_async_lane("grade", _grade_preparer.prepare)
            _preparation_runtime.register_polled_lane(
                "lut", StackHelperBackend(), progressive=True
            )
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
        if not bpy.app.timers.is_registered(_render_preflight_tick):
            bpy.app.timers.register(_render_preflight_tick, first_interval=0.02,
                                    persistent=True)
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
    global _preparation_runtime, _grade_preparer, _grade_resources
    errors = []
    _clear_gestures()
    try:
        if bpy.app.timers.is_registered(_render_preflight_tick):
            bpy.app.timers.unregister(_render_preflight_tick)
    except Exception as exc:
        errors.append(exc)
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
    if _grade_preparer is not None:
        try:
            _grade_preparer.close()
        except Exception as exc:
            errors.append(exc)
        _grade_preparer = None
    _reset_node_stores()
    _grade_resources = None

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
