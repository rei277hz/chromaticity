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
from .kernel.stage2_graph import (
    build_stage2_group, PARAMETER_IMAGE, PARAMETER_BANK_BINDINGS,
    PARAMETER_ACTIVE_BANK, PARAMETER_GENERATION, PARAMETER_SELECTOR,
    PARAMETER_SAMPLE_SELECTOR, PARAMETER_SAMPLE_ID, PARAMETER_SAMPLE_KIND,
    PARAMETER_SAMPLE_BANK,
    PARAMETER_READER, PARAMETER_READER_BANK,
)
from .kernel.stage2_parameters import PARAMETER_SCHEMA, PARAMETER_SHAPE, prepare_parameters
from .kernel.stage2_parameters import (
    PARAMETER_CONTENT_SIGNATURE, parameter_content_signature,
    parameter_image_matches,
)
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
from .policy import render_preflight as render_preflight_policy
from .runtime import gesture_coordinator as gesture_policy
from .runtime.preparation import PreparationRuntime
from .runtime.grade_preparation import GradePreparer
from .runtime.grade_resources import (
    GradeResources, SIGNATURE as PARAMETER_SIGNATURE, OWNER as PARAMETER_OWNER,
    OWNER_NODE as PARAMETER_OWNER_NODE,
)
from .runtime.publication import PublicationDeferred
from .runtime.compositor_receipts import CompositorReceipts
from .runtime.resource_lifecycle import run_resource_lifecycle
from .runtime.node_conversion_animation import NodeAnimationConversion
from .runtime.stack_observations import grade_is_referenced, stack_changed
from .runtime.image_publication import (
    pack_image_for_save, write_metadata,
)
from .runtime.bank_publication import run_bank_publication
from . import localization


SHADER_TREE = "ShaderNodeTree"
COMPOSITOR_TREE = "CompositorNodeTree"
NODE_TYPES = {
    SHADER_TREE: "PGShaderGrade",
    COMPOSITOR_TREE: "PGCompositorGrade",
}
PER_NODE_NODE_TYPES = {
    SHADER_TREE: "PGShaderGradePerNode",
    COMPOSITOR_TREE: "PGCompositorGradePerNode",
}
GRADE_NODE_TYPES = (*NODE_TYPES.values(), *PER_NODE_NODE_TYPES.values())
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
_grade_consumers = {}
_stack_entry_owners = {}
_indexed_node_grades = {}
_indexed_node_entries = {}
_indexed_output_nodes = {}
_output_registry_ready = False
_node_reset_pending = False
_preparation_runtime = None
_grade_preparer = None
_grade_resources = None
_preparation_sources = {}
_gesture_state = gesture_policy.new()
_gesture_node_serial = count(1)
_gesture_nodes = {}
_gesture_invocations = {}
_gesture_keyframe_baselines = {}
_compositor_receipts = CompositorReceipts()
_frame_change_active = False
_frame_reconcile_pending = False
_frame_reconcile_scenes = {}
_KERNEL_SCHEMA = 6
_KERNEL_KIND = "_perceptual_grade_kernel"
_KERNEL_SIGNATURE = "_perceptual_grade_signature"
_KERNEL_QUALITY = "_perceptual_grade_quality"
_IDENTITY_KERNEL_KIND = "_perceptual_grade_identity_kernel"
_ERROR_KERNEL_KIND = "_perceptual_grade_error_kernel"
_NODE_ERROR = "_perceptual_grade_kernel_error"
_NODE_ERROR_REASON = "_perceptual_grade_kernel_error_reason"
_NODE_PENDING = "_perceptual_grade_kernel_pending"
_NODE_ANIMATION_ERROR = "_perceptual_grade_animation_error"
_CONVERSION_BACKUP = "_perceptual_grade_conversion_backup"
_render_validated_scenes = set()
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
_ANIMATABLE_TONE_FIELDS = tuple(name for name in _TONE_FIELDS if name != "peak_nits")


def _is_grade_node(node):
    return getattr(node, "bl_idname", None) in GRADE_NODE_TYPES


def _is_per_node_grade_node(node):
    return getattr(node, "bl_idname", None) in PER_NODE_NODE_TYPES.values()


def _is_shared_grade_node(node):
    return getattr(node, "bl_idname", None) in NODE_TYPES.values()


def _is_stack_node(node):
    return getattr(node, "bl_idname", None) in STACK_NODE_TYPES.values()


def _is_output_node(node):
    return _is_grade_node(node) or _is_stack_node(node)


def _holder(settings):
    try:
        if _is_per_node_grade_node(settings):
            return settings
        owner = settings.id_data
        if getattr(owner, "bl_idname", None) == PGGradeData.bl_idname:
            return owner
        if _is_shared_grade_node(owner):
            return owner
        pointer = settings.as_pointer()
        for node in getattr(owner, "nodes", ()):
            if _is_shared_grade_node(node) and any(
                    getattr(node, name).as_pointer() == pointer
                    for name in ("pg_linear", "pg_tone")):
                return node
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None
    return None


def _linear_controls(owner):
    return owner if _is_per_node_grade_node(owner) else owner.pg_linear


def _tone_controls(owner):
    return owner if _is_per_node_grade_node(owner) else owner.pg_tone


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
    grade = bpy.data.node_groups.new(
        localization.tr("node.grade.title"), PGGradeData.bl_idname
    )
    try:
        if source is not None:
            if _is_shared_grade_node(source):
                source = source.pg_grade
            if source is None:
                return grade
            _copy_linear(_linear_controls(source), grade.pg_linear)
            _copy_tone(_tone_controls(source), grade.pg_tone)
    except BaseException:
        if grade.users == 0:
            bpy.data.node_groups.remove(grade)
        raise
    return grade


def _animated_values_for_node(node):
    if not _is_per_node_grade_node(node):
        return ()
    return tuple((name, float(getattr(node, name)))
                 for name in (*_LINEAR_FIELDS, *_ANIMATABLE_TONE_FIELDS))


def _insert_node_keyframes(node, fields, frame):
    failures = []
    for data_path in fields:
        try:
            inserted = node.keyframe_insert(data_path=data_path, frame=frame)
            if not inserted:
                failures.append(RuntimeError("Blender rejected a Per-Node Grade keyframe"))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
            failures.append(error)
    if failures:
        raise ExceptionGroup("Could not insert Auto Key Per-Node Grade values", failures)


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
    return Settings(linear=_linear_settings(_linear_controls(owner)),
                    tone=_tone_settings(_tone_controls(owner)), space=working_space)


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


def _kernel(tree_type, prepared, working_space, signature, parameter_images=None,
            active_bank=0, generation=0):
    built = build_stage2_group(
        prepared, tree_type, parameter_images=parameter_images,
        active_bank=active_bank, generation=generation,
    )
    tree = built.tree
    try:
        tree[_KERNEL_KIND] = _KERNEL_SCHEMA
        tree["_perceptual_grade_grade_kernel"] = True
        tree[_KERNEL_SIGNATURE] = signature
        tree[_KERNEL_QUALITY] = "full"
        tree["_perceptual_grade_tree_type"] = tree_type
        tree["_perceptual_grade_working_space"] = working_space
        for image in built.images:
            if image not in built.borrowed_images:
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
    tree = bpy.data.node_groups.new(
        localization.tr("datablock.stack"), tree_type
    )
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
    if _is_shared_grade_node(node) and node.pg_grade is not None:
        return _grade_settings(node.pg_grade, working_space)
    return _grade_settings(node, working_space)


def _kernel_is_current(kernel, tree_type, signature, quality="full", stack=None,
                       *, validate_graph=True):
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
            if validate_graph:
                valid = _parameter_kernel_valid(kernel)
            else:
                valid = _parameter_kernel_receipt_current(kernel)
            if not valid:
                return False
            active = kernel.get(PARAMETER_ACTIVE_BANK)
            image = kernel.get(PARAMETER_BANK_BINDINGS[active])
            if (kernel.get(PARAMETER_SIGNATURE) is None
                    or kernel.get(PARAMETER_SIGNATURE) != image.get(PARAMETER_SIGNATURE)):
                return False
        return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _kernel_error_text(node):
    return localization.tr("error.output_magenta") if node.get(_NODE_ERROR) else ""


def _animation_error_text(node):
    return localization.tr("error.autokey_failed") if node.get(_NODE_ANIMATION_ERROR) else ""


_LEGACY_PENDING_MESSAGES = {
    "Updating - waiting for compositor result": "status.waiting_compositor",
    "Updating - showing last-good result": "status.showing_last_good",
    "Preparing Grade - showing identity preview": "status.preparing_identity",
}


def _pending_message(node):
    pending = node.get(_NODE_PENDING)
    if not pending:
        return None
    if isinstance(pending, str) and pending in localization.CATALOGS["en"]:
        message_id = pending
    else:
        legacy = _LEGACY_PENDING_MESSAGES.get(pending) if isinstance(pending, str) else None
        message_id = legacy or "status.updating"
    return localization.tr(message_id)


def _draw_node_status(node, layout):
    pending = _pending_message(node)
    if pending:
        layout.label(text=pending, icon="TIME")
    if node.get(_NODE_ERROR):
        layout.label(text=_kernel_error_text(node), icon="ERROR")
    if node.get(_NODE_ANIMATION_ERROR):
        layout.label(text=_animation_error_text(node), icon="ERROR")


def _visible_compositor_scenes(record):
    """Scenes with a visible Viewer/backdrop or an observed evaluation."""
    scenes = {scene.as_pointer() for scene in _compositor_scenes((record,))}
    if not scenes:
        return ()
    expected = set()
    if _grade_resources is not None:
        evaluation = _grade_resources.gate.current_compositor()
        if evaluation is not None and evaluation[0] in scenes:
            expected.add(evaluation[0])
    for manager in tuple(bpy.data.window_managers):
        for window in tuple(manager.windows):
            try:
                scene = window.scene.as_pointer()
                if scene not in scenes:
                    continue
                for area in tuple(window.screen.areas):
                    space = area.spaces.active
                    backdrop = (area.type == "NODE_EDITOR"
                                and space.tree_type == COMPOSITOR_TREE
                                and space.show_backdrop)
                    image = getattr(space, "image", None) if area.type == "IMAGE_EDITOR" else None
                    viewer = image is not None and image.type == "COMPOSITING"
                    if backdrop or viewer:
                        expected.add(scene)
                        break
            except (AttributeError, ReferenceError, RuntimeError):
                continue
    return tuple(expected)


def _compositor_output_pending(node):
    try:
        if node.id_data.bl_idname != COMPOSITOR_TREE:
            return False
        pointer = node.as_pointer()
        record = _node_stores.get(pointer)
        if record is None:
            return False
        return _compositor_receipts.awaiting(pointer, _visible_compositor_scenes(record))
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _refresh_compositor_presentation(record):
    """Consume presentation authorization without rebuilding a Grade graph."""
    state, effects = node_policy.step(record["state"], node_policy.Event("presentation"))
    record["state"] = state
    if effects.output_mode is not None:
        _apply_output_presentation(record["node"], effects.output_mode, effects.error)


def _record_compositor_bindings(records, generation):
    """Record successful bindings only after their version is activated."""
    nodes_by_scene = {}
    for record in records:
        node = record["node"]
        if node.id_data.bl_idname != COMPOSITOR_TREE:
            continue
        pointer = node.as_pointer()
        for scene in _compositor_scenes((record,)):
            nodes_by_scene.setdefault(scene.as_pointer(), []).append(pointer)
    # Resolve every RNA identity before changing the plain map, then return
    # rollback facts before the caller dispatches fallible presentation work.
    return _compositor_receipts.bind(nodes_by_scene, generation)


def _restore_compositor_bindings(previous):
    _compositor_receipts.restore(previous)
    failures = []
    for pointer in {pointer for _scene, pointer in previous}:
        record = _node_stores.get(pointer)
        if record is not None:
            try:
                _refresh_compositor_presentation(record)
            except Exception as error:
                failures.append(error)
    if failures:
        raise RuntimeError("Could not restore Grade compositor presentation: "
                           + "; ".join(str(error) for error in failures)) from failures[0]


def _forget_compositor_node(pointer):
    _compositor_receipts.forget(pointer)


def _reset_compositor_receipts():
    _compositor_receipts.reset()


def _collect_compositor_receipts():
    if _node_reset_pending:
        return
    _compositor_receipts.collect()
    # Reconcile visibility changes too: a hidden Viewer must not leave the
    # node permanently marked Updating when no evaluation is expected.
    for pointer in _compositor_receipts.node_identities():
        record = _node_stores.get(pointer)
        if record is not None:
            try:
                _refresh_compositor_presentation(record)
            except (AttributeError, ReferenceError, RuntimeError) as error:
                print("Perceptual Grade compositor presentation failed:", error)


def _apply_output_presentation(node, mode, error):
    awaiting_compositor = mode == "current" and _compositor_output_pending(node)
    values = {}
    if mode == "error":
        print("Perceptual Grade output failed:", error)
        values[_NODE_ERROR] = True
    elif awaiting_compositor:
        values[_NODE_PENDING] = "status.waiting_compositor"
    elif mode != "current":
        values[_NODE_PENDING] = (
            "status.showing_last_good" if mode == "preview"
            else "status.preparing_identity"
        )
    for key in (_NODE_ERROR, _NODE_PENDING, _NODE_ERROR_REASON):
        if key in values:
            if node.get(key) != values[key]:
                node[key] = values[key]
        elif key in node:
            del node[key]
    custom = mode != "current" or awaiting_compositor
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
    node.node_tree = kernel
    _restore_node_connections(node, snapshot)
    if node.node_tree != kernel:
        raise RuntimeError("Kernel replacement did not select the requested group")


def _restore_node_connections(node, snapshot):
    tree = node.id_data
    for link in tuple(tree.links):
        touches_node = link.from_node == node or link.to_node == node
        touches_multi_input = any(
            link.to_node == target and link.to_socket.name == input_name
            for target, input_name, _sources in snapshot["multi_input_groups"]
        )
        if touches_node or touches_multi_input:
            tree.links.remove(link)

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


def _remap_node_snapshot(snapshot, source, replacement):
    def remap(node):
        return replacement if node == source else node

    return dict(snapshot, links=tuple(
        (remap(origin), output, remap(target), input_)
        for origin, output, target, input_ in snapshot["links"]
    ), multi_input_groups=tuple(
        (remap(target), input_, tuple((remap(origin), output)
                                     for origin, output in sources))
        for target, input_, sources in snapshot["multi_input_groups"]
    ))


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
    grade = node.pg_grade if _is_shared_grade_node(node) else None
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
    _index_output_node(node)
    record = _node_stores.get(pointer)
    if record is not None and (source is None or record.get("source") is source):
        record["node"] = node
        return record
    previous_state = record["state"] if record is not None else None
    gesture_active = _gesture_is_active(pointer)
    if record is not None:
        del _node_stores[pointer]
        _forget_compositor_node(pointer)
        _release_source(record.get("source"))

    applied_signature = None
    applied_quality = None
    kernel = getattr(node, "node_tree", None)
    kernel_quality = kernel.get(_KERNEL_QUALITY, "full") if kernel is not None else "full"
    # This is an adoption boundary, not the hot existing-record lookup above.
    # Validate the full reader set once before treating a persisted graph as
    # applied; slider callbacks keep the cheap signature check below.
    readers_valid = _is_stack_node(node) or _parameter_kernel_valid(kernel)
    if readers_valid and previous_state is not None \
            and previous_state.error is None \
            and previous_state.applied_signature is not None \
            and _kernel_belongs_to_node(node, kernel) \
            and _kernel_is_current(
                kernel, node.id_data.bl_idname, previous_state.applied_signature,
                previous_state.applied_quality or "full", stack=_is_stack_node(node)):
        applied_signature = previous_state.applied_signature
        applied_quality = previous_state.applied_quality or "full"
    elif (readers_valid and desired_signature is not None
            and _kernel_belongs_to_node(node, kernel) and _kernel_is_current(
            kernel, node.id_data.bl_idname, desired_signature,
            kernel_quality, stack=_is_stack_node(node))):
        applied_signature = desired_signature
        applied_quality = kernel_quality
    stack_grade_ids = _stack_grade_ids(node) if _is_stack_node(node) else ()
    state = node_policy.new(
        desired_signature=desired_signature,
        applied_signature=applied_signature,
        applied_quality=applied_quality,
        gesture_active=gesture_active,
    )
    record = {"node": node, "state": state, "source": source,
              "stack": _is_stack_node(node),
              "stack_grade_ids": stack_grade_ids}
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
    if _node_reset_pending:
        return ()
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
    if _node_reset_pending:
        return ()
    if _is_shared_grade_node(node) and node.pg_grade is None:
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
    needs_compositor_adoption = (
        not record["stack"] and node.id_data.bl_idname == COMPOSITOR_TREE
        and state.applied_signature is not None
        and not _compositor_receipts.known(node.as_pointer())
    )
    current = True
    if state.applied_signature is not None:
        current = _kernel_is_current(
            node.node_tree, node.id_data.bl_idname, state.applied_signature,
            state.applied_quality or "full", stack=_is_stack_node(node),
            validate_graph=needs_compositor_adoption,
        )
    if needs_compositor_adoption and current:
        resource = _grade_resources.resource(node, working_space)
        if (resource.generation is not None
                and tuple(node.node_tree.get(key) for key in PARAMETER_BANK_BINDINGS)
                == resource.banks
                and node.node_tree.get(PARAMETER_ACTIVE_BANK) == resource.active_bank):
            # Loaded/undone graphs can already satisfy kernel demand and skip
            # publication entirely. Seed their plain evaluation facts before
            # the request's presentation effect claims the result is current.
            _record_compositor_bindings((record,), resource.generation)
    if not current:
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
                               quality="full", lane="grade", admitted=False):
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
            failures.extend(_publish_grade_parameters(
                source, tuple(grade_records), prepared, admitted=admitted))
    finally:
        _reconciling = previous_reconciling
    return tuple(failures)


def _write_grade_parameters(image, pixels):
    """Populate an unpublished candidate; published image bytes are immutable."""
    image.pixels.foreach_set(pixels.ravel())
    image.update()


def _pack_grade_parameters(image):
    # Blender checks dirty images before save_pre runs. Keep this small derived
    # snapshot packed before any reader can be rebound to it.
    image.pack()


def _invalidate_grade_parameters(image):
    image.update_tag()


def _compositor_scenes(records):
    owners = []
    for record in records:
        try:
            tree = record["node"].id_data
            if tree.bl_idname == COMPOSITOR_TREE:
                owners.append(tree)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    scenes = []
    for scene in tuple(bpy.data.scenes):
        try:
            root = scene.compositing_node_group
            if root is not None and any(root == tree or root.contains_tree(tree)
                                        for tree in owners):
                scenes.append(scene)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return tuple(scenes)


def _tag_compositor_outputs(records):
    """Invalidate compositor graphs that consume successfully published Grades."""
    owners = {}
    kernels = {}
    for record in records:
        try:
            node = record["node"]
            tree = node.id_data
            if tree.bl_idname != COMPOSITOR_TREE:
                continue
            tree_pointer = tree.as_pointer()
            if tree_pointer:
                owners[tree_pointer] = tree
            kernel = node.node_tree
            if kernel is not None:
                kernel_pointer = kernel.as_pointer()
                if kernel_pointer:
                    kernels[kernel_pointer] = kernel
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    if not owners:
        return

    tagged_trees = set()

    def tag_tree(tree):
        pointer = tree.as_pointer()
        if pointer and pointer not in tagged_trees:
            tree.update_tag()
            tagged_trees.add(pointer)

    for tree in owners.values():
        tag_tree(tree)
    for kernel in kernels.values():
        tag_tree(kernel)

    scenes = {}
    roots = {}
    for scene in tuple(bpy.data.scenes):
        try:
            root = scene.compositing_node_group
            if root is None:
                continue
            if any(root == tree or root.contains_tree(tree)
                   for tree in owners.values()):
                scenes[scene.as_pointer()] = scene
                roots[root.as_pointer()] = root
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    for root in roots.values():
        tag_tree(root)
    for scene in scenes.values():
        scene.update_tag()

    tagged_areas = set()
    for screen in tuple(bpy.data.screens):
        try:
            areas = tuple(screen.areas)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for area in areas:
            try:
                if area.type not in {"NODE_EDITOR", "IMAGE_EDITOR"}:
                    continue
                pointer = area.as_pointer()
                if pointer and pointer not in tagged_areas:
                    area.tag_redraw()
                    tagged_areas.add(pointer)
            except (AttributeError, ReferenceError, RuntimeError):
                continue


def _parameter_selector_node(kernel):
    selectors = tuple(node for node in kernel.nodes if node.get(PARAMETER_SELECTOR))
    if len(selectors) != 1:
        raise RuntimeError("Grade kernel must contain exactly one parameter selector")
    return selectors[0]


def _read_parameter_selector(kernel):
    selector = _parameter_selector_node(kernel)
    if kernel.bl_idname == SHADER_TREE:
        value = float(selector.outputs["Value"].default_value)
        if value not in (0., 1.):
            raise RuntimeError("Shader Grade selector is not a bank index")
        return int(value)
    if kernel.bl_idname == COMPOSITOR_TREE:
        if (selector.bl_idname != "ShaderNodeMath" or selector.operation != "ADD"
                or any(socket.is_linked for socket in selector.inputs)
                or float(selector.inputs[1].default_value) != 0.0):
            raise RuntimeError("Compositor Grade selector has an invalid scalar source")
        value = float(selector.inputs[0].default_value)
        if value not in (0., 1.):
            raise RuntimeError("Compositor Grade selector is not a bank index")
        return int(value)
    raise RuntimeError("Grade selector belongs to an unsupported tree")


def _set_parameter_selector(kernel, bank):
    selector = _parameter_selector_node(kernel)
    if kernel.bl_idname == SHADER_TREE:
        selector.outputs["Value"].default_value = float(bank)
    elif kernel.bl_idname == COMPOSITOR_TREE:
        selector.inputs[0].default_value = float(bank)
    else:
        raise RuntimeError("Grade selector belongs to an unsupported tree")


def _publish_grade_parameters(source, authorized_records, prepared, *, admitted):
    """Stage one fixed inactive bank, select it, and deliver its generation."""
    users = tuple(record for record in authorized_records
                  if record.get("source") is source
                  and _node_stores.get(record["node"].as_pointer()) is record)
    if not users:
        return ()
    created, context, failures = [], {}, []
    resource = _grade_resources.resource(users[0]["node"], prepared.space)
    settings = Settings(linear=prepared.linear.settings, tone=prepared.tone.settings,
                        space=prepared.space)
    preparation_signature = _preparation_signature(settings, prepared.space)
    old_active = resource.active_bank if resource.active_bank in (0, 1) else 0
    old_generation = resource.generation if resource.generation is not None else 0
    candidate_bank = 1 - old_active
    generation = _grade_resources.next_generation(resource)
    active_valid = (resource.banks is None
                    or _parameter_image_content_matches(resource.banks[old_active]))
    context.update(
        resource=resource, banks=resource.banks, old_active=old_active,
        old_generation=old_generation, candidate_bank=candidate_bank,
        generation=generation, previous_trees=dict(resource.trees),
        repairing=not active_valid,
        outer_before=tuple((record["node"], record["node"].node_tree)
                           for record in users),
        receipt_before=None, metadata_before=(),
    )

    def make_image(bank):
        image = bpy.data.images.new(
            f"Perceptual Grade parameters bank {bank}",
            width=PARAMETER_SHAPE[1], height=PARAMETER_SHAPE[0],
            alpha=True, float_buffer=True,
        )
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        image.file_format = "OPEN_EXR"
        image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        image["_perceptual_grade_image"] = True
        return image

    def pack_image(image, pixels, signature):
        image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        image["_perceptual_grade_image"] = True
        _write_grade_parameters(image, pixels)
        _pack_grade_parameters(image)
        if image.packed_file is None or image.is_dirty:
            return False
        image[PARAMETER_SIGNATURE] = signature
        image[PARAMETER_CONTENT_SIGNATURE] = parameter_content_signature(pixels)
        return True

    def stage(_bank, _errors, *, repair=False):
        parameters = prepared.parameters or prepare_parameters(prepared)
        banks = resource.banks
        fresh = banks is None
        if fresh:
            allocated = []
            try:
                allocated.append(make_image(0))
                allocated.append(make_image(1))
                banks = tuple(allocated)
                # No graph can read this pair yet. Initialize both so a schema
                # repair can safely install either branch before activation.
                for image in banks:
                    if not pack_image(image, parameters.pixels, preparation_signature):
                        for allocated_image in allocated:
                            if allocated_image.users == 0:
                                bpy.data.images.remove(allocated_image, do_unlink=True)
                        return {"clean": False}
                _grade_resources.set_banks(resource, banks, old_active, old_generation)
            except BaseException:
                for image in allocated:
                    if image.users == 0:
                        bpy.data.images.remove(image, do_unlink=True)
                raise
        elif repair:
            if (not pack_image(banks[old_active], parameters.pixels,
                               preparation_signature)
                    or not pack_image(banks[candidate_bank], parameters.pixels,
                                      preparation_signature)):
                return {"clean": False}
        else:
            if not pack_image(banks[candidate_bank], parameters.pixels,
                              preparation_signature):
                return {"clean": False}

        context.update(banks=banks, fresh=fresh)
        kernels = dict(resource.trees)
        owner, owner_node = _grade_resources.owner(users[0]["node"])
        tree_types = set(kernels) | {record["node"].id_data.bl_idname for record in users}
        for tree_type in tree_types:
            kernel = kernels.get(tree_type)
            structure_valid = _parameter_kernel_structure_valid(kernel)
            if not structure_valid:
                kernel = _kernel(
                    tree_type, prepared, prepared.space,
                    _signature(tree_type, _snapshot_values(settings), prepared.space),
                    banks, old_active, old_generation,
                )
                created.append(kernel)
                kernel[PARAMETER_OWNER] = owner
                if owner_node is not None:
                    kernel[PARAMETER_OWNER_NODE] = owner_node
                kernels[tree_type] = kernel
                structure_valid = _parameter_kernel_structure_valid(kernel)
            if not structure_valid:
                return {"clean": False}
            # Kernel generations describe the selected bank, which is still
            # the previous bank until the selector operation succeeds.
            kernel[PARAMETER_ACTIVE_BANK] = old_active
            kernel[PARAMETER_GENERATION] = old_generation
            kernel[PARAMETER_SIGNATURE] = banks[old_active].get(PARAMETER_SIGNATURE)
        context["kernels"] = kernels
        context["metadata_before"] = tuple(
            (kernel, key, kernel.get(key))
            for kernel in kernels.values()
            for key in (PARAMETER_ACTIVE_BANK, PARAMETER_GENERATION,
                        PARAMETER_SIGNATURE, _KERNEL_SIGNATURE)
        )
        verified_banks = (banks if fresh or repair else (banks[candidate_bank],))
        return {"clean": all(
            not image.is_dirty and image.packed_file is not None
            and _parameter_image_content_matches(image)
            for image in verified_banks
        )}

    def select(bank, _errors):
        kernels = context["kernels"]
        for kernel in kernels.values():
            _set_parameter_selector(kernel, bank)
            kernel[PARAMETER_ACTIVE_BANK] = bank
            kernel[PARAMETER_GENERATION] = generation
            kernel[PARAMETER_SIGNATURE] = preparation_signature
            tree_type = kernel.bl_idname
            kernel[_KERNEL_SIGNATURE] = _signature(
                tree_type, _snapshot_values(settings), prepared.space,
            )
        for node, _previous in context["outer_before"]:
            kernel = kernels[node.id_data.bl_idname]
            if node.node_tree != kernel:
                _replace_node_kernel(node, kernel)
        selected = {_read_parameter_selector(kernel) for kernel in kernels.values()}
        if selected != {bank} or any(
                kernel.get(PARAMETER_ACTIVE_BANK) != bank
                or kernel.get(PARAMETER_GENERATION) != generation
                or kernel.get(PARAMETER_SIGNATURE) != preparation_signature
                or kernel.get(PARAMETER_SIGNATURE)
                != kernel.get(PARAMETER_BANK_BINDINGS[bank]).get(PARAMETER_SIGNATURE)
                or kernel.get(_KERNEL_SIGNATURE) != _signature(
                    kernel.bl_idname, _snapshot_values(settings), prepared.space)
                for kernel in kernels.values()):
            raise RuntimeError("Grade parameter selector readback did not match the staged bank")
        return {"selected_bank": selected.pop()}

    def deliver(_bank, _errors):
        resource = context["resource"]
        _grade_resources.publish(resource, candidate_bank, generation)
        resource.trees = context["kernels"]
        _invalidate_grade_parameters(resource.image)
        _tag_compositor_outputs(users)
        context["receipt_before"] = _record_compositor_bindings(users, generation)
        delivery_errors = []
        for record in users:
            event_kind = "recovery_result" if context["repairing"] else "installation_result"
            delivery_errors.extend(_dispatch(record["node"], node_policy.Event(
                event_kind, _publication_signature(record, prepared))))
        if delivery_errors:
            raise ExceptionGroup("Grade installation delivery failed", delivery_errors)
        return {"delivered": True}

    def restore_selector(bank, _errors):
        restoration_errors = []
        for kernel in context.get("kernels", {}).values():
            try:
                _set_parameter_selector(kernel, bank)
                for key, value in ((PARAMETER_ACTIVE_BANK, old_active),
                                   (PARAMETER_GENERATION, old_generation)):
                    write_metadata(((kernel, key, value),))
            except Exception as error:
                restoration_errors.append(error)
        for node, previous in context["outer_before"]:
            try:
                if node.node_tree != previous:
                    _replace_node_kernel(node, previous)
            except Exception as error:
                restoration_errors.append(error)
        for entry in context.get("metadata_before", ()):
            try:
                write_metadata((entry,))
            except Exception as error:
                restoration_errors.append(error)
        try:
            _grade_resources.restore(resource, old_active, old_generation)
            resource.trees = context["previous_trees"]
        except Exception as error:
            restoration_errors.append(error)
        if context.get("receipt_before") is not None:
            try:
                _restore_compositor_bindings(context["receipt_before"])
            except Exception as error:
                restoration_errors.append(error)
        if restoration_errors:
            raise ExceptionGroup("Grade bank selector restoration failed", restoration_errors)
        return {"selected_bank": old_active}

    def fail_closed(_bank, errors):
        error = errors[0] if errors else RuntimeError("Grade bank publication failed")
        affected = tuple(record for record in _node_stores.values()
                         if record.get("source") is source)
        installation_errors = []
        for record in affected or users:
            try:
                pointer = record["node"].as_pointer()
                if not pointer or _node_stores.get(pointer) is not record:
                    continue
                installation_errors.extend(_fail_installation((record,), None, error))
            except Exception as failure:
                installation_errors.append(failure)
        if installation_errors:
            resource.trees = context.get("kernels", context["previous_trees"])
            raise ExceptionGroup("Could not establish the Grade error output",
                                 installation_errors)
        resource.trees = {}
        return {"closed": True}

    operations = {
        "stage": stage,
        "repair": lambda bank, errors: stage(bank, errors, repair=True),
        "select": select,
        "deliver": deliver,
        "restore_selector": restore_selector,
        "fail_closed": fail_closed,
    }
    publication = run_bank_publication(
        old_active, candidate_bank, operations,
        admitted=admitted,
        active_valid=active_valid,
    )
    transaction_errors = list(publication.errors)

    if publication.outcome == "committed":
        previous = [tree for node, tree in context["outer_before"]
                    if tree is not context.get("kernels", {}).get(
                        node.id_data.bl_idname)]
        previous.extend(tree for kind, tree in context["previous_trees"].items()
                        if tree is not context["kernels"].get(kind))
        errors = list(_retire_kernels(previous))
        errors.extend(_grade_resources.reclaim(resource, _remove_parameter_image))
        transaction_errors.extend(errors)
    elif publication.outcome == "failed_closed":
        if not transaction_errors:
            transaction_errors.append(RuntimeError(
                "Grade bank publication ended " + publication.outcome
            ))
        previous = [tree for _node, tree in context["outer_before"]]
        errors = list(_retire_kernels((*created, *previous)))
        errors.extend(_grade_resources.reclaim(resource, _remove_parameter_image))
        transaction_errors.extend(errors)
    else:
        resource.trees = context.get("kernels", context["previous_trees"])
        transaction_errors.append(RuntimeError(
            "Grade bank publication could not establish a reliable output"
        ))

    diagnostic_nodes = []
    for record in tuple(_node_stores.values()):
        if record.get("source") != source:
            continue
        try:
            if record["node"].as_pointer():
                diagnostic_nodes.append(record["node"])
        except ReferenceError:
            continue
    for error in transaction_errors:
        failures.append((tuple(diagnostic_nodes), error))
        message = ("recovered during" if publication.outcome == "committed"
                   else "failed during")
        print(f"Perceptual Grade bank publication {message} publication:", error)
    return tuple(failures)


def _linked_from(socket, node, output_name):
    links = tuple(socket.links)
    return (len(links) == 1 and links[0].from_node == node
            and links[0].from_socket == node.outputs[output_name])


def _linked_output(socket):
    links = tuple(socket.links)
    return links[0].from_socket if len(links) == 1 else None


def _shader_parameter_samples_valid(kernel, selector, readers):
    grouped = {}
    for node in kernel.nodes:
        if not node.get(PARAMETER_SAMPLE_SELECTOR):
            continue
        sample_id, kind = node.get(PARAMETER_SAMPLE_ID), node.get(PARAMETER_SAMPLE_KIND)
        if type(sample_id) is not int or kind not in {"vector", "alpha"}:
            return False
        group = grouped.setdefault(sample_id, {})
        if kind in group:
            return False
        group[kind] = node
    if not grouped:
        return False

    for group in grouped.values():
        if set(group) != {"vector", "alpha"}:
            return False
        vector, alpha = group["vector"], group["alpha"]
        if (vector.bl_idname != "ShaderNodeMix" or vector.data_type != "VECTOR"
                or vector.factor_mode != "UNIFORM" or not vector.clamp_factor
                or alpha.bl_idname != "ShaderNodeMix" or alpha.data_type != "FLOAT"
                or not alpha.clamp_factor
                or not vector.outputs[1].links):
            return False
        if not _linked_from(vector.inputs[0], selector, "Value"):
            return False
        if not _linked_from(alpha.inputs[0], selector, "Value"):
            return False
        for socket, bank, output in (
                (vector.inputs[4], 0, "Color"), (vector.inputs[5], 1, "Color"),
                (alpha.inputs[2], 0, "Alpha"), (alpha.inputs[3], 1, "Alpha")):
            source = _linked_output(socket)
            if (source is None or source.node not in readers[bank]
                    or source.node.bl_idname != "ShaderNodeTexImage"
                    or source != source.node.outputs[output]):
                return False

    return all(link.to_node.get(PARAMETER_SAMPLE_SELECTOR)
               and link.to_socket == link.to_node.inputs[0]
               for link in selector.outputs["Value"].links)


def _compositor_parameter_samples_valid(kernel, selector, readers):
    selectors = tuple(node for node in kernel.nodes
                      if node.get(PARAMETER_SAMPLE_SELECTOR))
    if not selectors:
        return False

    sample_ids = []
    for sample_selector in selectors:
        sample_id = sample_selector.get(PARAMETER_SAMPLE_ID)
        if (type(sample_id) is not int
                or sample_selector.bl_idname != "CompositorNodeSetAlpha"):
            return False
        sample_ids.append(sample_id)
    if len(set(sample_ids)) != len(sample_ids):
        return False

    map_uvs, separates = {}, {}
    for node in kernel.nodes:
        sample_id, bank = node.get(PARAMETER_SAMPLE_ID), node.get(PARAMETER_SAMPLE_BANK)
        if node.bl_idname == "CompositorNodeMapUV" and sample_id is not None:
            if type(sample_id) is not int or type(bank) is not int or bank not in (0, 1):
                return False
            key = (sample_id, bank)
            if key in map_uvs:
                return False
            map_uvs[key] = node
        elif node.bl_idname == "CompositorNodeSeparateColor" and sample_id is not None:
            if type(sample_id) is not int or type(bank) is not int or bank not in (0, 1):
                return False
            key = (sample_id, bank)
            if key in separates:
                return False
            separates[key] = node

    if (set(key[0] for key in map_uvs) != set(sample_ids)
            or set(key[0] for key in separates) != set(sample_ids)
            or any(len(readers[bank]) != 1 for bank in (0, 1))
            or any((sample_id, bank) not in map_uvs or (sample_id, bank) not in separates
                   for sample_id in sample_ids for bank in (0, 1))):
        return False

    def is_selector_weight(socket):
        return _linked_from(socket, selector, "Value")

    def is_inactive_weight(socket):
        source = _linked_output(socket)
        if (source is None or source.node.bl_idname != "ShaderNodeMath"
                or source.node.operation != "SUBTRACT"
                or source != source.node.outputs["Value"]):
            return False
        inverse = source.node
        return (not inverse.inputs[0].is_linked
                and float(inverse.inputs[0].default_value) == 1.0
                and _linked_from(inverse.inputs[1], selector, "Value"))

    def is_weighted_channel(socket, sample_id, channel):
        add_output = _linked_output(socket)
        if (add_output is None or add_output.node.bl_idname != "ShaderNodeMath"
                or add_output.node.operation != "ADD"
                or add_output != add_output.node.outputs["Value"]):
            return False
        add = add_output.node
        branches = []
        for input_socket in add.inputs[:2]:
            multiply_output = _linked_output(input_socket)
            if (multiply_output is None or multiply_output.node.bl_idname != "ShaderNodeMath"
                    or multiply_output.node.operation != "MULTIPLY"
                    or multiply_output != multiply_output.node.outputs["Value"]):
                return False
            multiply = multiply_output.node
            operands = [
                (index, _linked_output(multiply.inputs[index]))
                for index in (0, 1)
            ]
            signal = [(index, source) for index, source in operands
                      if source is not None and source.node == separates[(sample_id, 0)]
                      and source.name == channel]
            signal += [(index, source) for index, source in operands
                       if source is not None and source.node == separates[(sample_id, 1)]
                       and source.name == channel]
            if len(signal) != 1:
                return False
            signal_index, signal_source = signal[0]
            bank = 0 if signal_source.node == separates[(sample_id, 0)] else 1
            weight_socket = multiply.inputs[1 - signal_index]
            if not (is_inactive_weight(weight_socket) if bank == 0
                    else is_selector_weight(weight_socket)):
                return False
            branches.append(bank)
        return sorted(branches) == [0, 1]

    for sample_selector in selectors:
        sample_id = sample_selector[PARAMETER_SAMPLE_ID]
        combine_link = tuple(sample_selector.inputs["Image"].links)
        alpha_link = tuple(sample_selector.inputs["Alpha"].links)
        if (len(combine_link) != 1 or len(alpha_link) != 1
                or sample_selector.inputs["Type"].default_value
                not in {"Replace Alpha", "REPLACE_ALPHA"}
                or not sample_selector.outputs["Image"].links):
            return False
        combine_link = combine_link[0]
        combine = combine_link.from_node
        if (combine.bl_idname != "CompositorNodeCombineColor"
                or combine.mode != "RGB"
                or combine_link.from_socket != combine.outputs["Image"]):
            return False
        for name in ("Red", "Green", "Blue"):
            if not is_weighted_channel(combine.inputs[name], sample_id, name):
                return False
        alpha_source = _linked_output(sample_selector.inputs["Alpha"])
        if (alpha_source is None or alpha_source.node.bl_idname != "ShaderNodeMath"
                or alpha_source.node.operation != "ADD"
                or alpha_source != alpha_source.node.outputs["Value"]
                or not is_weighted_channel(
                    sample_selector.inputs["Alpha"], sample_id, "Alpha")):
            return False

        uv_source = None
        for bank in (0, 1):
            map_uv = map_uvs[(sample_id, bank)]
            separate = separates[(sample_id, bank)]
            uv_links = tuple(map_uv.inputs["UV"].links)
            if len(uv_links) != 1:
                return False
            observed_uv = (uv_links[0].from_node, uv_links[0].from_socket)
            if uv_source is None:
                uv_source = observed_uv
            if (map_uv.bl_idname != "CompositorNodeMapUV"
                    or map_uv.inputs["Interpolation"].default_value
                    not in {"Nearest", "NEAREST"}
                    or map_uv.inputs["Extension X"].default_value
                    not in {"Extend", "EXTEND"}
                    or map_uv.inputs["Extension Y"].default_value
                    not in {"Extend", "EXTEND"}
                    or observed_uv != uv_source
                    or separate.mode != "RGB"
                    or not _linked_from(map_uv.inputs["Image"], readers[bank][0], "Image")
                    or not _linked_from(separate.inputs["Image"], map_uv, "Image")):
                return False

    return True


def _parameter_kernel_receipt_current(kernel):
    """Check cached publication receipts without traversing a graph or image buffer."""
    try:
        active = kernel.get(PARAMETER_ACTIVE_BANK)
        generation = kernel.get(PARAMETER_GENERATION)
        if (kernel.get("_perceptual_grade_stage2_complete") is not True
                or type(active) is not int or active not in (0, 1)
                or type(generation) is not int or generation < 0):
            return False
        images = tuple(kernel.get(key) for key in PARAMETER_BANK_BINDINGS)
        if (len(images) != 2 or images[0] is None or images[1] is None
                or images[0] == images[1]):
            return False
        if any(
                image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])
                or not image.as_pointer() or image.is_dirty
                or image.packed_file is None
                for image in images):
            return False
        image = images[active]
        return (kernel.get(PARAMETER_SIGNATURE) is not None
                and kernel.get(PARAMETER_SIGNATURE) == image.get(PARAMETER_SIGNATURE)
                and image.get(PARAMETER_CONTENT_SIGNATURE) is not None)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _parameter_kernel_structure_valid(kernel):
    try:
        if (kernel is None or kernel.get(_KERNEL_KIND) != _KERNEL_SCHEMA
                or not kernel.get("_perceptual_grade_stage2_complete")):
            return False
        active = kernel.get(PARAMETER_ACTIVE_BANK)
        generation = kernel.get(PARAMETER_GENERATION)
        if (type(active) is not int or active not in (0, 1)
                or type(generation) is not int or generation < 0):
            return False
        images = tuple(kernel.get(key) for key in PARAMETER_BANK_BINDINGS)
        if (any(image is None or image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])
                or not image.as_pointer() for image in images)
                or images[0] == images[1]):
            return False
        selectors = []
        readers = [[], []]
        for reader in kernel.nodes:
            image = getattr(reader, "image", None)
            if reader.get(PARAMETER_READER):
                bank = reader.get(PARAMETER_READER_BANK)
                if bank not in (0, 1) or image != images[bank]:
                    return False
                readers[bank].append(reader)
            elif image is not None and image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA:
                return False
            if reader.get(PARAMETER_SELECTOR):
                selectors.append(reader)
        if not readers[0] or not readers[1] or len(selectors) != 1:
            return False
        selector = selectors[0]
        if kernel.bl_idname == SHADER_TREE:
            value = float(selector.outputs["Value"].default_value)
            if value not in (0., 1.):
                return False
            selected = int(value)
            if not _shader_parameter_samples_valid(kernel, selector, readers):
                return False
        elif kernel.bl_idname == COMPOSITOR_TREE:
            value = float(selector.inputs[0].default_value)
            if (selector.bl_idname != "ShaderNodeMath"
                    or selector.operation != "ADD"
                    or selector.inputs[0].is_linked
                    or selector.inputs[1].is_linked
                    or float(selector.inputs[1].default_value) != 0.0
                    or value not in (0., 1.)):
                return False
            selected = int(value)
            if not _compositor_parameter_samples_valid(kernel, selector, readers):
                return False
        else:
            return False
        if not selector.outputs["Value"].links:
            return False
        return selected == active
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _parameter_kernel_valid(kernel):
    if not _parameter_kernel_structure_valid(kernel):
        return False
    try:
        active = kernel.get(PARAMETER_ACTIVE_BANK)
        image = kernel.get(PARAMETER_BANK_BINDINGS[active])
        return _parameter_image_content_matches(image)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _parameter_image_content_matches(image):
    return parameter_image_matches(image)


def _remove_parameter_image(image):
    bpy.data.images.remove(image, do_unlink=False)


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


def _publication_demand(publication):
    if hasattr(publication, "source"):
        return (publication.source, publication.prepared, publication.error,
                getattr(publication, "lane", "grade"))
    source, _signature, prepared, error = publication
    return source, prepared, error, "grade"


def _admit_parameter_candidate(publication):
    """Check backpressure before consuming the mailbox or node-policy result."""
    source, prepared, error, lane = _publication_demand(publication)
    if lane != "grade" or error is not None:
        return False
    if not _grade_resources.gate.retirement_allowed():
        raise PublicationDeferred("Grade bank publication requires quiescent readers")
    records = tuple(record for record in _node_stores.values()
                    if record.get("source") is source and not record["stack"])
    if records:
        _grade_resources.resource(records[0]["node"], prepared.space)
    return True


def _publish_pending_preparations(*, drain=False, sources=None):
    """Consume mailboxes only inside an admitted publication/preflight scope."""
    if _node_reset_pending:
        raise PublicationDeferred("Grade lifecycle reconciliation is pending")
    failures = []
    # One complete source per foreground turn, with no settling delay or rate cap.
    keys = tuple(key for key in _grade_resources.pending
                 if sources is None or key[0] in sources)
    deferred = None
    for key in keys:
        publication = _grade_resources.pending[key]
        try:
            admitted = _admit_parameter_candidate(publication)
        except PublicationDeferred as error:
            if drain:
                raise
            deferred = error
            continue
        del _grade_resources.pending[key]
        failures.extend(_consume_preparation_publication(publication, admitted=admitted))
        if not drain:
            return tuple(failures)
    if deferred is not None:
        raise deferred
    return tuple(failures)


def _handle_preparation_completions(completions):
    if _node_reset_pending:
        return ()
    _queue_preparation_completions(completions)
    if _grade_resources is None or not _grade_resources.pending:
        return ()
    try:
        with _grade_resources.gate.commit():
            return _publish_pending_preparations()
    except PublicationDeferred as error:
        reason = str(error)
    return ()


def _consume_preparation_publication(publication, *, admitted=False):
    if hasattr(publication, "quality"):
        return _handle_preparation_result(
            publication.source, publication.signature, publication.prepared,
            publication.error, publication.quality, publication.lane, admitted,
        )
    source, signature, prepared, error = publication
    return _handle_preparation_result(source, signature, prepared, error)


def _preparation_tick():
    if _preparation_runtime is None:
        return None
    if _node_reset_pending:
        return 0.02
    try:
        _collect_compositor_receipts()
        _preparation_runtime.pump_main_thread()
        _handle_preparation_completions(_preparation_runtime.collect())
    except Exception as error:
        _block_nodes(tuple(_all_grade_nodes()), error)
        print("Perceptual Grade asynchronous preparation failed:", error)
    pending = _preparation_runtime.pending or bool(_grade_resources and _grade_resources.pending)
    if not pending:
        return None
    if _grade_resources is not None and _grade_resources.gate.blocked():
        gate = _grade_resources.gate
        if gate.current_compositor() is not None:
            return 0.02
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
            protected = resource.use_fake_user
            if image:
                parameter_image = resource.get(PARAMETER_IMAGE) is not None
                if _grade_resources is None:
                    protected = protected or parameter_image
                else:
                    protected = (protected or _grade_resources.protected(resource)
                                 or (parameter_image
                                     and not _grade_resources.gate.retirement_allowed()))
            return {"live": True, "owned": owned, "users": resource.users,
                    "protected": protected}
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
    if _grade_resources is not None:
        failures.extend(_grade_resources.reclaim_all(_remove_parameter_image))
    for image in tuple(bpy.data.images):
        errors = run_resource_lifecycle(_resource_retirement_operations(image, image=True))
        failures.extend(errors)
        for error in errors:
            print("Perceptual Grade image retirement failed:", error)
    return tuple(failures)


def _refresh_nodes(nodes, working_space=None, *, defer_failure_mutations=False):
    if _node_reset_pending:
        return ()
    nodes = tuple(node for node in nodes if _is_output_node(node))
    if not nodes:
        return ()

    try:
        working_space = working_space or _working_space()
    except Exception as error:
        if defer_failure_mutations:
            return tuple(((node,), error) for node in nodes)
        return _block_nodes(nodes, error)
    failures = []
    snapshots = {}
    for node in nodes:
        try:
            failures.extend(((node,), error) for error in _request_node(node, working_space, snapshots))
        except Exception as error:
            if defer_failure_mutations:
                failures.append(((node,), error))
            else:
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
        pointer = node.as_pointer()
    except (AttributeError, ReferenceError, RuntimeError):
        return
    _forget_node_pointer(pointer)


def _forget_node_pointer(pointer):
    record = _node_stores.pop(pointer, None)
    _unindex_output_node(pointer)
    _forget_compositor_node(pointer)
    if record is not None:
        _release_source(record.get("source"))


def _finalize_conversion_source(pointer, kernel, record=None):
    def fence():
        failures = []
        for operation in (
                lambda: _forget_node_pointer(pointer),
                lambda: _forget_gesture_pointer(pointer)):
            try:
                operation()
            except Exception as error:
                failures.append(error)
        source = None if record is None else record.get("source")
        if source is not None:
            try:
                _release_source(source)
            except Exception as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup("Grade conversion disposal fence failed", failures)

    try:
        return _run_node_disposal_lifecycle(kernel, fence, lambda: None)
    except Exception as error:
        return (error,)


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
            if _is_shared_grade_node(node):
                node.pg_grade = None
            node.node_tree = None
        finally:
            _syncing.discard(pointer)

    failures = _run_node_disposal_lifecycle(kernel, fence, detach)
    if failures:
        raise ExceptionGroup("Grade resource disposal failed", list(failures))


def _run_node_disposal_lifecycle(kernel, fence, detach):
    operations = _resource_retirement_operations(kernel)
    evict = operations["evict"]

    def evict_if_live():
        try:
            if kernel is None or kernel.as_pointer() == 0:
                return
        except (AttributeError, ReferenceError, RuntimeError):
            return
        evict()

    operations.update(fence=fence, detach=detach, evict=evict_if_live)
    failures = list(run_resource_lifecycle(operations, disposal=True))
    if failures:
        try:
            if kernel is not None and kernel.as_pointer() != 0:
                failures.extend(run_resource_lifecycle(
                    _resource_retirement_operations(kernel),
                ))
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    if not failures:
        failures.extend(_retire_images())
    return tuple(failures)


def _dispose_node(node):
    failures = _dispatch(node, node_policy.Event("dispose"))
    if failures:
        raise RuntimeError("Could not dispose Grade resources: "
                           + "; ".join(map(str, failures))) from failures[0]


def _reset_node_stores():
    global _node_reset_pending, _frame_reconcile_pending
    _node_reset_pending = True
    _frame_reconcile_pending = False
    _frame_reconcile_scenes.clear()
    _render_validated_scenes.clear()
    if _grade_resources is not None:
        # Load/undo invalidates callback identities, but only actual host
        # quiescence permits releasing the retained native image versions.
        _grade_resources.gate.reset()
        _grade_resources.clear()
    sources = tuple(_preparation_sources.values())
    _node_stores.clear()
    _clear_output_registry()
    _preparation_sources.clear()
    if _preparation_runtime is not None:
        for source in sources:
            _preparation_runtime.forget(source)
    _reset_compositor_receipts()
    _node_reset_pending = False


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


def _consumer_grade_ids(node):
    if _is_shared_grade_node(node):
        grade = node.pg_grade
        return (grade.as_pointer(),) if grade is not None else ()
    if _is_stack_node(node):
        return tuple(
            entry.grade.as_pointer()
            for entry in node.pg_stack_entries
            if entry.enabled and entry.grade is not None
        )
    return ()


def _clear_output_registry():
    global _output_registry_ready
    _grade_consumers.clear()
    _stack_entry_owners.clear()
    _indexed_node_grades.clear()
    _indexed_node_entries.clear()
    _indexed_output_nodes.clear()
    _output_registry_ready = False


def _unindex_output_node(pointer):
    node_grades = _indexed_node_grades.pop(pointer, ())
    for grade_pointer in node_grades:
        consumers = _grade_consumers.get(grade_pointer)
        if consumers is None:
            continue
        consumers.pop(pointer, None)
        if not consumers:
            _grade_consumers.pop(grade_pointer, None)
    for entry_pointer in _indexed_node_entries.pop(pointer, ()):
        owner = _stack_entry_owners.get(entry_pointer)
        if owner is not None and owner[0] == pointer:
            _stack_entry_owners.pop(entry_pointer, None)
    _indexed_output_nodes.pop(pointer, None)


def _index_output_node(node):
    """Maintain the derived Grade-consumer and stack-entry owner indexes."""
    global _output_registry_ready
    try:
        if not _is_output_node(node):
            return True
        pointer = node.as_pointer()
        if not pointer:
            return True
        _unindex_output_node(pointer)
        _indexed_output_nodes[pointer] = node
        grades = tuple(grade_pointer for grade_pointer in _consumer_grade_ids(node)
                       if grade_pointer)
        _indexed_node_grades[pointer] = grades
        for grade_pointer in grades:
            _grade_consumers.setdefault(grade_pointer, {})[pointer] = node
        entries = ()
        if _is_stack_node(node):
            entries = tuple(entry.as_pointer() for entry in node.pg_stack_entries
                            if entry.as_pointer())
            for entry_pointer in entries:
                _stack_entry_owners[entry_pointer] = (pointer, node)
        _indexed_node_entries[pointer] = entries
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # RNA objects can disappear while Blender is editing or undoing a tree.
        # The next lifecycle reconciliation rebuilds the complete index.
        _output_registry_ready = False
        return False


def _rebuild_output_registry():
    global _output_registry_ready
    _clear_output_registry()
    complete = True
    for node in tuple(_all_grade_nodes()):
        complete = _index_output_node(node) and complete
    _output_registry_ready = complete


def _indexed_consumers(grade_pointer):
    if not _output_registry_ready:
        _rebuild_output_registry()
    if not _output_registry_ready:
        consumers = {}
        for node in _all_grade_nodes():
            try:
                if grade_pointer in _consumer_grade_ids(node):
                    _index_output_node(node)
                    consumers[node.as_pointer()] = node
            except (AttributeError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                continue
        return tuple(consumers.values())
    consumers = _grade_consumers.get(grade_pointer, {})
    live = []
    for pointer, node in tuple(consumers.items()):
        try:
            if node.as_pointer() != pointer or not _is_output_node(node):
                _unindex_output_node(pointer)
                continue
            grades = _consumer_grade_ids(node)
            if tuple(grades) != _indexed_node_grades.get(pointer, ()):
                _index_output_node(node)
                if grade_pointer not in _indexed_node_grades.get(pointer, ()):
                    continue
            if grade_pointer in _indexed_node_grades.get(pointer, ()):
                live.append(node)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            _unindex_output_node(pointer)
    return tuple(live)


def _stack_owner(entry):
    try:
        pointer = entry.as_pointer()
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    indexed = _stack_entry_owners.get(pointer)
    owner = indexed[1] if indexed is not None else None
    if owner is not None:
        try:
            if (owner.as_pointer() == indexed[0] and _is_stack_node(owner)
                    and any(item.as_pointer() == pointer
                            for item in owner.pg_stack_entries)):
                return owner
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        _stack_entry_owners.pop(pointer, None)
    try:
        tree = getattr(entry, "id_data", None)
        for candidate in tuple(getattr(tree, "nodes", ())):
            if not _is_stack_node(candidate):
                continue
            if any(item.as_pointer() == pointer
                   for item in candidate.pg_stack_entries):
                _index_output_node(candidate)
                return candidate
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    if not _output_registry_ready:
        _rebuild_output_registry()
        indexed = _stack_entry_owners.get(pointer)
        if indexed is not None:
            return indexed[1]
    else:
        _rebuild_output_registry()
        indexed = _stack_entry_owners.get(pointer)
        if indexed is not None:
            return indexed[1]
    return None


def _stack_changed(entry, _context):
    node = _stack_owner(entry)
    if node is None:
        return
    _index_output_node(node)
    failures = _dispatch_stack_replacement(node)
    if failures:
        print("Perceptual Grade Stack update failed:", failures[-1])


def _refresh_stack_policy(node):
    _index_output_node(node)
    failures = _dispatch_stack_replacement(node)
    if failures:
        print("Perceptual Grade Stack update failed:", failures[-1])


def _dispatch_stack_replacement(node):
    if _node_reset_pending:
        return ()
    record = _record_for(node)
    grade_ids = _stack_grade_ids(node)
    changed = stack_changed(record["stack_grade_ids"], grade_ids)
    record["stack_grade_ids"] = grade_ids
    return _dispatch(node, node_policy.Event("stack_replace", stack_changed=changed))


def _stack_focus_changed(node, _context):
    if _is_stack_node(node):
        node.id_data.nodes.active = node


def _gesture_related_nodes(node):
    related = {node.as_pointer(): node}
    if _is_per_node_grade_node(node):
        return tuple(related.values())
    grade = node.pg_grade if _is_shared_grade_node(node) else _stack_active_grade(node)
    if grade is None:
        return tuple(related.values())
    grade_pointer = grade.as_pointer()
    for candidate in _indexed_consumers(grade_pointer):
        try:
            if _is_shared_grade_node(candidate) and candidate.pg_grade == grade:
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


def _capture_gesture_keyframe_baseline(targets):
    values = {}
    for target in targets:
        node = _gesture_node(target.node_id)
        if node is None or not _is_per_node_grade_node(node):
            continue
        values[target.node_id] = dict(_animated_values_for_node(node))
    return values


def _keyframe_gesture(token, frame):
    baseline = _gesture_keyframe_baselines.pop(token, None)
    if baseline is None or frame is None:
        return
    for identity, fields in baseline.items():
        node = _gesture_node(identity)
        if node is None or not _is_per_node_grade_node(node):
            continue
        changed = []
        for field, before in fields.items():
            current = float(getattr(node, field))
            if current != before:
                changed.append(field)
        try:
            _insert_node_keyframes(node, changed, frame)
            if _NODE_ANIMATION_ERROR in node:
                del node[_NODE_ANIMATION_ERROR]
        except Exception as error:
            node[_NODE_ANIMATION_ERROR] = True
            print("Perceptual Grade Auto Key failed:", error)


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
    _forget_gesture_pointer(node.as_pointer())


def _forget_gesture_pointer(pointer):
    identity = _gesture_identity_for_pointer(pointer)
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
    scene = bpy.context.scene
    auto_key = bool(scene is not None and _is_per_node_grade_node(node)
                    and scene.tool_settings.use_keyframe_insert_auto)
    frame = (float(scene.frame_current + scene.frame_subframe)
             if auto_key else None)
    _dispatch_gesture(gesture_policy.Event(
        "press", window_id=window_key, x=int(position[0]), y=int(position[1]),
        undo_owner="adapter",
        auto_key=auto_key, frame=frame,
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
                    result = bpy.ops.ed.undo_push(
                        message=localization.tr("undo.gesture")
                    )
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
    _gesture_keyframe_baselines.pop(token, None)
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
        elif action.kind == "keyframe":
            _keyframe_gesture(action.gesture_token, action.frame)
        elif action.kind == "forget_node":
            _gesture_nodes.pop(action.node_id, None)
        elif action.kind == "clear_registry":
            _gesture_nodes.clear()
            _gesture_invocations.clear()
            _gesture_keyframe_baselines.clear()
        elif action.kind == "report_install_failure":
            print("Perceptual Grade could not install gesture observer for window",
                  action.window_id, ":", _gesture_invocations.get(action.token, {}).get("error")
                  or "Blender did not retain the modal observer")
    flush_refresh()
    if effects.undo_window is not None:
        _push_gesture_undo(effects.undo_window)


def _dispatch_gesture(event):
    global _gesture_state
    token = (event.gesture_token if event.gesture_token is not None else
             gesture_policy.current_gesture(_gesture_state, event.window_id)
             if event.window_id is not None else None)
    _gesture_state, effects = gesture_policy.step(_gesture_state, event)
    _consume_gesture_effects(effects)
    if event.kind in ("finish", "finish_observed", "window_gone"):
        _gesture_keyframe_baselines.pop(token, None)


class PG_OT_gesture_router(bpy.types.Operator):
    bl_idname = "perceptual_grade.gesture_router"
    bl_label = localization.native("operator.gesture_router")
    bl_translation_context = localization.CONTEXT
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
                targets = _live_gesture_targets(_gesture_related_nodes(active))
                scene = getattr(context, "scene", None)
                auto_key = bool(scene is not None and _is_per_node_grade_node(active)
                                and scene.tool_settings.use_keyframe_insert_auto)
                keyframe_frame = (float(scene.frame_current + scene.frame_subframe)
                                  if auto_key else None)
                _dispatch_gesture(gesture_policy.Event(
                    "press", window_id=self.window_key, token=self.token,
                    x=int(event.mouse_x), y=int(event.mouse_y), undo_owner="native",
                    targets=tuple(gesture_policy.Target(_gesture_identity(target),
                                                       _settings_signature_for(target))
                                  for target in targets),
                    observed=_gesture_observations(self.window_key),
                    auto_key=auto_key,
                    frame=keyframe_frame,
                ))
                gesture_token = _gesture_token(self.window_key)
                if gesture_token is not None and auto_key:
                    _gesture_keyframe_baselines[gesture_token] = (
                        _capture_gesture_keyframe_baseline(
                            tuple(gesture_policy.Target(_gesture_identity(target), None)
                                  for target in targets)
                        )
                    )
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


def _ensure_gesture_router_timer():
    """Keep interactive drag observation available across native file loads."""
    if (not bpy.app.background
            and PG_OT_gesture_router in _registered_classes
            and not bpy.app.timers.is_registered(_gesture_router_tick)):
        bpy.app.timers.register(_gesture_router_tick, first_interval=0.1,
                                persistent=True)


def _gesture_router_tick():
    if not _registered_classes or PG_OT_gesture_router not in _registered_classes:
        return None
    if _node_reset_pending:
        # Keep the timer alive until lifecycle recovery has fenced the old
        # node identities; only then install observers for the current file.
        return 0.1
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
    global _frame_reconcile_pending
    if _frame_change_active:
        _frame_reconcile_pending = True
        return
    grade_pointer = grade.as_pointer()
    users = []
    failures = []
    for node in _indexed_consumers(grade_pointer):
        try:
            if _is_shared_grade_node(node) and node.pg_grade == grade:
                users.append(node)
            elif _is_stack_node(node):
                record = _record_for(node)
                referenced = grade_is_referenced(
                    record["stack_grade_ids"], grade_pointer,
                )
                failures.extend(
                    (node, error) for error in _dispatch(
                        node, node_policy.Event(
                            "grade_changed", grade_referenced=referenced,
                        ),
                    )
                )
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    refresh = []
    for node in users:
        armed = _gesture_is_armed(node.as_pointer())
        if not armed:
            refresh.append(node)
    failures.extend(_refresh_nodes(tuple(refresh)))
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


@persistent
def _frame_change_pre(_scene, *_args):
    global _frame_change_active
    _frame_change_active = True


def _frame_reconcile_blocked(scene_identity):
    if _grade_resources is not None:
        gate = _grade_resources.gate
        if (gate.evaluation_active("render", scene_identity)
                or gate.evaluation_active("compositor", scene_identity)):
            return True
    return (bpy.app.is_job_running("RENDER")
            or bpy.app.is_job_running("RENDER_PREVIEW")
            or bpy.app.is_job_running("COMPOSITE"))


@persistent
def _frame_change_post(scene, *_args):
    global _frame_change_active, _frame_reconcile_pending
    _frame_change_active = False
    _frame_reconcile_pending = True
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        pointer = scene.as_pointer()
        _frame_reconcile_scenes[pointer] = scene
        if _frame_reconcile_blocked(pointer):
            return
        failures = _refresh_nodes(_scene_grade_nodes(scene))
        _frame_reconcile_scenes.pop(pointer, None)
        _frame_reconcile_pending = bool(_frame_reconcile_scenes)
        for nodes, error in failures:
            names = ", ".join(getattr(node, "name", "Grade") for node in nodes)
            print(f"Perceptual Grade frame update failed for {names}: {error}")
    except Exception as error:
        print("Perceptual Grade frame update failed:", error)


def _frame_reconcile_tick():
    global _frame_reconcile_pending
    if PGShaderGrade not in _registered_classes:
        return None
    if _frame_reconcile_pending and not _node_reset_pending:
        try:
            if not _frame_reconcile_scenes:
                scene = getattr(bpy.context, "scene", None)
                if scene is not None:
                    _frame_reconcile_scenes[scene.as_pointer()] = scene
            for pointer, scene in tuple(_frame_reconcile_scenes.items()):
                if _frame_reconcile_blocked(pointer):
                    continue
                try:
                    if scene.as_pointer() == pointer:
                        _refresh_nodes(_scene_grade_nodes(scene))
                except (AttributeError, ReferenceError, RuntimeError):
                    pass
                _frame_reconcile_scenes.pop(pointer, None)
            _frame_reconcile_pending = bool(_frame_reconcile_scenes)
        except PublicationDeferred:
            _frame_reconcile_pending = True
        except Exception as error:
            nodes = tuple(node for scene in _frame_reconcile_scenes.values()
                          for node in _scene_grade_nodes(scene))
            _block_nodes(nodes, error)
    return 0.1


def _ensure_all_kernels(working_space=None):
    global _last_working_space
    if _node_reset_pending:
        return ()
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
    failures = []
    try:
        # Lifecycle/render reconciliation also checks tracked graphs. Ordinary
        # slider requests deliberately keep their cheap signature check, but
        # rendering must not trust externally changed image-reader bindings.
        for node in nodes:
            record = _node_stores.get(node.as_pointer())
            if (record is not None and not record["stack"]
                    and record["state"].applied_signature is not None
                    and not _parameter_kernel_valid(node.node_tree)):
                failures.extend(((node,), error) for error in _dispatch(
                    node, node_policy.Event(
                        "installation_result", record["state"].desired_signature,
                        "Grade parameter readers are missing or have inconsistent bindings")))
        failures.extend(_refresh_nodes(nodes, working_space))
    except Exception as error:
        failures.extend(_block_nodes(nodes, error))
    _last_working_space = working_space
    if _preparation_runtime is not None:
        _ensure_timer()
    for nodes, error in failures:
        names = ", ".join(getattr(node, "name", "Grade") for node in nodes)
        print(f"Perceptual Grade output failed closed for {names}: {error}")
    return tuple(failures)


def _cleanup_conversion_backups():
    for tree in tuple(bpy.data.node_groups):
        if (tree.get(_CONVERSION_BACKUP)
                and tree.get(_CONVERSION_BACKUP + "_safe_to_cleanup")
                and tree.users == 0):
            try:
                bpy.data.node_groups.remove(tree, do_unlink=True)
            except Exception as error:
                print("Perceptual Grade conversion backup cleanup failed:", error)


def _startup_reconcile_tick():
    if PGShaderGrade not in _registered_classes:
        return None
    if not hasattr(bpy.data, "node_groups"):
        return 0.1
    _cleanup_conversion_backups()
    _rebuild_output_registry()
    _ensure_all_kernels()
    return None


@persistent
def _load_post(_filepath):
    try:
        _clear_gestures()
        _cleanup_conversion_backups()
        _reset_node_stores()
        _rebuild_output_registry()
        _ensure_all_kernels()
    except PublicationDeferred:
        _undo_redo_post()
    except Exception as error:
        print("Perceptual Grade load repair failed:", error)
    finally:
        _ensure_gesture_router_timer()


@persistent
def _undo_redo_pre(*_args):
    _clear_gestures()
    try:
        _reset_node_stores()
    except PublicationDeferred:
        # Preserve native-reader pins until the post-undo timer can reset.
        pass


@persistent
def _undo_redo_post(*_args):
    if not bpy.app.timers.is_registered(_undo_redo_reconcile_tick):
        bpy.app.timers.register(_undo_redo_reconcile_tick, first_interval=0.0)


def _undo_redo_reconcile_tick():
    if PGShaderGrade not in _registered_classes:
        return None
    try:
        _reset_node_stores()
        _rebuild_output_registry()
        _ensure_all_kernels()
    except PublicationDeferred:
        return 0.02
    except Exception as error:
        print("Perceptual Grade undo repair failed:", error)
    finally:
        _ensure_gesture_router_timer()
    return None


@persistent
def _render_pre(scene):
    if _grade_resources is None:
        return
    gate = _grade_resources.gate
    render_identity = scene.as_pointer()
    with gate.callback():
        ticket = gate.request_render_preflight(
            render_identity, render_identity, scene.frame_current,
            float(scene.frame_subframe).hex(),
        )
    if threading.current_thread() is threading.main_thread():
        try:
            _service_render_preflight(defer=False)
        except PublicationDeferred as error:
            _block_nodes(_scene_grade_nodes(scene), error)
            print("Perceptual Grade render preflight failed:", error)
    else:
        try:
            # Blender invokes this callback from its render worker. Release the
            # GIL while the main-thread timer prepares and validates this frame.
            ticket.wait()
        except Exception as error:
            print("Perceptual Grade render preflight failed:", error)


def _service_render_preflight(*, defer=True):
    if _grade_resources is None:
        return
    gate = _grade_resources.gate
    if _node_reset_pending:
        if defer:
            ticket = gate.take_render_preflight(failed_only=True)
            if ticket is not None:
                _fail_render_preflight(
                    ticket, RuntimeError(ticket.state.error or "Render preflight failed"))
            return
        ticket = gate.take_render_preflight()
        if ticket is None:
            raise PublicationDeferred("Grade lifecycle reconciliation is pending")
        _fail_render_preflight(
            ticket, PublicationDeferred("Grade lifecycle reconciliation is pending"))
        return
    ticket = gate.take_render_preflight()
    if ticket is not None:
        if ticket.failure_authorized:
            _fail_render_preflight(
                ticket, RuntimeError(ticket.state.error or "Render preflight failed"))
            return
        try:
            with gate.render_preflight(ticket, defer=defer, deliver_failure=False):
                try:
                    scene = next((candidate for candidate in bpy.data.scenes
                                  if candidate.as_pointer() == ticket.scene_identity), None)
                    if scene is None:
                        raise RuntimeError("Render scene no longer exists")
                    if (scene.frame_current != ticket.frame
                            or float(scene.frame_subframe).hex() != ticket.subframe):
                        raise RuntimeError("Render frame changed before Grade preflight")
                    # Native animation rendering may advance an evaluated scene
                    # copy while the original ID still exposes the previous
                    # frame's RNA values. Re-assert the exact ticket time on
                    # the main-thread scene before reading animated Grade data.
                    scene.frame_set(ticket.frame, subframe=float.fromhex(ticket.subframe))
                    nodes, _signatures, signature = _animation_snapshot(scene)
                    failures = []
                    first_frame = ticket.scene_identity not in _render_validated_scenes
                    failures.extend(_refresh_nodes(
                        nodes, defer_failure_mutations=True))
                    failures.extend(_drain_preparations_in_scope(
                        nodes, defer_failure_mutations=True))
                    current_nodes, current_signatures, current_signature = (
                        _animation_snapshot(scene))
                    if current_signature != signature:
                        raise RuntimeError(
                            "Evaluated Grade settings changed during frame preflight")
                    ready, error = _animation_outputs_current(
                        current_nodes, current_signatures,
                        validate_graph=first_frame)
                    node_ids = {node.as_pointer() for node in current_nodes}
                    relevant = [failure for failed_nodes, failure in failures
                                if any(node.as_pointer() in node_ids
                                       for node in failed_nodes)]
                    if relevant:
                        error = str(relevant[-1])
                        ready = False
                    if not ready:
                        failure = RuntimeError(error or
                            "Grade output did not become current for this render frame")
                        effects = ticket.resolve(render_preflight_policy.Event(
                            "published", ticket.render_identity,
                            ticket.scene_identity, ticket.frame, ticket.subframe,
                            ticket.generation, signature=signature,
                            error=str(failure),
                        ))
                        if effects.action != "fail":
                            raise RuntimeError(effects.error or
                                               "Render failure was not authorized")
                    else:
                        effects = ticket.resolve(render_preflight_policy.Event(
                            "published", ticket.render_identity,
                            ticket.scene_identity, ticket.frame, ticket.subframe,
                            ticket.generation, signature=signature,
                            published_signature=current_signature,
                        ))
                        if effects.action != "release":
                            raise RuntimeError(effects.error or
                                               "Grade render preflight was not authorized")
                        if first_frame:
                            _render_validated_scenes.add(ticket.scene_identity)
                except Exception as error:
                    ticket.fail(error)
                    print("Perceptual Grade frame output failed closed:", error)
        except PublicationDeferred as error:
            if not defer:
                _fail_render_preflight(ticket, error)
        except Exception as error:
            _fail_render_preflight(ticket, error)
        else:
            if ticket.failure_authorized:
                _fail_render_preflight(
                    ticket, RuntimeError(ticket.state.error or "Render preflight failed"))


def _fail_render_preflight(ticket, error):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Render failure reconciliation requires Blender's main thread")
    effects = ticket.fail(error)
    if ticket.failure_authorized:
        scene = next((candidate for candidate in bpy.data.scenes
                      if candidate.as_pointer() == ticket.scene_identity), None)
        if scene is not None:
            _block_nodes(_scene_grade_nodes(scene), error)
        _grade_resources.gate.finish_render_preflight_failure(ticket)
    elif effects.action == "release":
        ticket.deliver()


def _render_preflight_tick():
    if _grade_resources is None:
        return None
    try:
        _collect_compositor_receipts()
        _service_render_preflight()
    except Exception as error:
        print("Perceptual Grade render preparation failed:", error)
    return 0.02 if _grade_resources.gate.has_render_preflight else 0.1


@persistent
def _render_init(scene, *_args):
    if _grade_resources is not None:
        _render_validated_scenes.discard(scene.as_pointer())
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_started("render", scene.as_pointer())


@persistent
def _render_finished(scene, *_args):
    if _grade_resources is not None:
        _render_validated_scenes.discard(scene.as_pointer())
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_finished("render", scene.as_pointer())


@persistent
def _render_cancelled(scene, *_args):
    if _grade_resources is not None:
        _render_validated_scenes.discard(scene.as_pointer())
        with _grade_resources.gate.callback():
            _grade_resources.gate.evaluation_finished(
                "render", scene.as_pointer(), successful=False)


@persistent
def _compositor_pre(scene, *_args):
    if _grade_resources is not None:
        with _grade_resources.gate.callback():
            identity = scene.as_pointer()
            snapshot = _compositor_receipts.snapshot(identity)
            _grade_resources.gate.evaluation_started(
                "compositor", identity, snapshot=snapshot)


@persistent
def _compositor_finished(scene, *, successful):
    if _grade_resources is not None:
        with _grade_resources.gate.callback():
            receipt = _grade_resources.gate.evaluation_finished(
                "compositor", scene.as_pointer(), successful=successful)
            _compositor_receipts.completed(receipt)


@persistent
def _compositor_post(scene, *_args):
    _compositor_finished(scene, successful=True)


@persistent
def _compositor_cancel(scene, *_args):
    _compositor_finished(scene, successful=False)


@persistent
def _save_pre(_filepath):
    # Pixels are derived from authoritative settings. Save committed buffers;
    # file-load reconciliation repairs any saved preview against those settings.
    for image in bpy.data.images:
        pack_image_for_save(image, generated=image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA,
                            pack=_pack_grade_parameters)


def _drain_preparations(nodes=None):
    """Explicit synchronous bridge for quiescent, main-thread callers."""
    if _grade_resources is None:
        return ()
    with _grade_resources.gate.commit():
        return _drain_preparations_in_scope(nodes=nodes)


def _drain_preparations_in_scope(nodes=None, *, defer_failure_mutations=False):
    if _node_reset_pending:
        raise PublicationDeferred("Grade lifecycle reconciliation is pending")
    if _preparation_runtime is None:
        return ()
    failures = []
    records = (tuple(_node_stores.values()) if nodes is None else tuple(
        record for node in nodes
        if (record := _node_stores.get(node.as_pointer())) is not None
    ))
    sources = {record["source"] for record in records
               if record.get("source") is not None}
    # The async barrier waits only for preparation, never for Blender mutation.
    try:
        _queue_preparation_completions(_preparation_runtime.wait(sources))
        failures.extend(_publish_pending_preparations(drain=True, sources=sources))
    except Exception as error:
        failed_nodes = tuple(record["node"] for record in records)
        if defer_failure_mutations:
            failures.append((failed_nodes, error))
        else:
            # Blender need not abort a render when a handler raises. Revoke
            # output before returning to the host.
            failures.extend(_block_nodes(failed_nodes, error))
    for record in records:
        state = record["state"]
        node = record["node"]
        if (not node_policy.output_allowed(state)
                or not _kernel_is_current(
                    node.node_tree, node.id_data.bl_idname, state.desired_signature,
                    state.applied_quality or "full", stack=record["stack"],
                    validate_graph=False)):
            error = RuntimeError(
                state.error or "Grade did not become current for rendering")
            if defer_failure_mutations:
                failures.append(((node,), error))
            else:
                failures.extend(_dispatch(node, node_policy.Event(
                    "installation_result", state.desired_signature, str(error))))
    return tuple(failures)


@persistent
def _depsgraph_update_post(_scene, _depsgraph=None):
    global _last_working_space
    if _node_reset_pending:
        return
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

    if _is_per_node_grade_node(holder):
        _per_node_grade_changed(holder)
        return

    if _is_shared_grade_node(holder) and holder.pg_grade is None:
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
    if _is_per_node_grade_node(holder):
        _per_node_grade_changed(holder)
        return
    if _is_shared_grade_node(holder) and holder.pg_grade is None:
        _reset_tone(settings)


def _per_node_grade_changed(node):
    global _frame_reconcile_pending
    if _frame_change_active:
        _frame_reconcile_pending = True
        return
    if _gesture_is_armed(node.as_pointer()):
        return
    failures = _refresh_nodes((node,))
    if failures:
        print("Perceptual Grade kernel repair failed:", failures[-1][1])


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
    _index_output_node(node)
    if node.pg_grade is None:
        _reset_linear(node.pg_linear)
        _reset_tone(node.pg_tone)
    else:
        _grade_changed(node.pg_grade)
        return
    _replace_kernel(node)


def _assign_values(node, values):
    if _is_per_node_grade_node(node):
        settings = _linear_controls(node)
        with _suspend(settings):
            for name, value in values.items():
                setattr(settings, name, value)
        _per_node_grade_changed(node)
        return
    if not _is_shared_grade_node(node) or node.pg_grade is None:
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


def _float_setting(message_id, default, minimum, maximum, precision, update,
                   *, animatable):
    options = {"ANIMATABLE"} if animatable else set()
    return FloatProperty(
        name=localization.native(message_id),
        translation_context=localization.CONTEXT,
        description=localization.native("tooltip." + message_id.removeprefix("property.")),
        default=default, min=minimum, max=maximum, precision=precision,
        options=options, update=update,
    )


def _linear_setting_properties(*, animatable):
    return {
        "exposure": _float_setting("property.exposure", 0.0, -6.0, 6.0, 2,
                                    _linear_changed, animatable=animatable),
        "source_x": _float_setting("property.source_x", D65[0], 0.0, 0.9, 5,
                                    _source_white_changed(0), animatable=animatable),
        "source_y": _float_setting("property.source_y", D65[1], 0.0, 0.9, 5,
                                    _source_white_changed(1), animatable=animatable),
        "cr_balance": _float_setting("property.cr_balance", 0.0, -2.0, 2.0, 3,
                                      _linear_changed, animatable=animatable),
        "yb_balance": _float_setting("property.yb_balance", 0.0, -2.0, 2.0, 3,
                                      _linear_changed, animatable=animatable),
        "cr_spread": _float_setting("property.cr_spread", 0.0, -100.0, 150.0, 1,
                                     _linear_changed, animatable=animatable),
        "yb_spread": _float_setting("property.yb_spread", 0.0, -100.0, 150.0, 1,
                                     _linear_changed, animatable=animatable),
        "cr_heading": _float_setting("property.cr_heading", 0.0, -180.0, 180.0, 1,
                                      _linear_changed, animatable=animatable),
        "yb_heading": _float_setting("property.yb_heading", 0.0, -180.0, 180.0, 1,
                                      _linear_changed, animatable=animatable),
    }


def _tone_setting_properties(*, animatable):
    return {
        name: _float_setting(
            "property." + name, TONE_DEFAULTS[name], *TONE_LIMITS[index],
            3 if index < 2 else 2 if index < 4 else 1,
            _tone_anchor_changed(index), animatable=animatable,
        )
        for index, name in enumerate(TONE_LEVEL_FIELDS)
    } | {
        "fit": _float_setting("property.fit", 0.0, -2.0, 2.0, 2,
                              _tone_changed, animatable=animatable),
        "peak_nits": EnumProperty(
            name=localization.native("property.peak"),
            translation_context=localization.CONTEXT,
            description=localization.native("tooltip.peak"),
            default="1000",
            items=[(str(peak), localization.native(f"tone.peak.{peak}"), "")
                   for peak in TONE_PEAKS],
            options=set(), update=_tone_changed,
        ),
    }


class PGLinearSettings(bpy.types.PropertyGroup):
    __annotations__ = _linear_setting_properties(animatable=False)


class PGToneSettings(bpy.types.PropertyGroup):
    __annotations__ = _tone_setting_properties(animatable=False)


class PGGradeData(bpy.types.NodeTree):
    bl_idname = "PGGradeData"
    bl_label = localization.native("node.grade.title")
    bl_translation_context = localization.CONTEXT
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
    enabled: BoolProperty(
        name=localization.native("property.enabled"),
        translation_context=localization.CONTEXT,
        description=localization.native("tooltip.enabled"),
        default=True, update=_stack_changed)
    grade: PointerProperty(
                           type=PGGradeData,
                           name=localization.native("property.grade"),
                           translation_context=localization.CONTEXT,
                           poll=_poll_grade_data,
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
    op = layout.operator(
        PG_OT_stack_action.bl_idname,
        text=localization.tr("action.stack_add"), icon="ADD",
    )
    op.action = "ADD"
    _draw_node_status(node, layout)


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
    if _is_stack_node(node):
        grade = _stack_active_grade(node)
        settings = grade.pg_tone if grade is not None else None
        enabled = grade is not None
    elif _is_shared_grade_node(node):
        grade = node.pg_grade
        settings = grade.pg_tone if grade is not None else node.pg_tone
        enabled = grade is not None
    else:
        settings = _tone_controls(node)
        enabled = True
    if settings is None:
        return
    column = layout.column()
    column.enabled = enabled
    for field in TONE_LEVEL_FIELDS:
        column.prop(settings, field, slider=True)
    column.prop(settings, "fit", slider=True)
    column.prop(settings, "peak_nits")
    column.label(text=localization.tr("label.reference"))
    column.operator(PG_OT_reset_tone.bl_idname, icon="LOOP_BACK")


class PGShaderGradeStack(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGradeStack"
    bl_label = localization.native("node.stack.title")
    bl_translation_context = localization.CONTEXT
    bl_width_default = 320
    pg_stack_entries: CollectionProperty(type=PGStackEntry)
    pg_active_index: IntProperty(default=0, min=0, update=_stack_focus_changed)

    def init(self, _context):
        self["_perceptual_grade_stack"] = 1
        _index_output_node(self)

    def copy(self, _source):
        _index_output_node(self)

    def draw_buttons(self, context, layout):
        _draw_stack_node(self, context, layout)

    def draw_buttons_ext(self, context, layout):
        _draw_stack_node(self, context, layout)

    def free(self):
        _dispose_node(self)


class PGCompositorGradeStack(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGradeStack"
    bl_label = localization.native("node.stack.title")
    bl_translation_context = localization.CONTEXT
    bl_width_default = 320
    pg_stack_entries: CollectionProperty(type=PGStackEntry)
    pg_active_index: IntProperty(default=0, min=0, update=_stack_focus_changed)

    def init(self, _context):
        self["_perceptual_grade_stack"] = 1
        _index_output_node(self)

    def copy(self, _source):
        _index_output_node(self)

    def draw_buttons(self, context, layout):
        _draw_stack_node(self, context, layout)

    def draw_buttons_ext(self, context, layout):
        _draw_stack_node(self, context, layout)

    def free(self):
        _dispose_node(self)


class PGShaderGrade(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGrade"
    bl_label = localization.native("node.grade.title")
    bl_translation_context = localization.CONTEXT
    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_tone: PointerProperty(type=PGToneSettings)
    pg_grade: PointerProperty(type=PGGradeData, poll=_poll_grade_data,
                              update=_selection_changed)

    def init(self, _context):
        _index_output_node(self)

    def copy(self, _source):
        _index_output_node(self)

    def draw_buttons(self, context, layout):
        layout.context_pointer_set("pg_node", self)
        layout.template_ID(self, "pg_grade", new=PG_OT_new_grade.bl_idname,
                           unlink=PG_OT_unlink_grade.bl_idname)
        _draw_node_status(self, layout)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)

    def free(self):
        _dispose_node(self)


class PGCompositorGrade(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGrade"
    bl_label = localization.native("node.grade.title")
    bl_translation_context = localization.CONTEXT
    pg_linear: PointerProperty(type=PGLinearSettings)
    pg_tone: PointerProperty(type=PGToneSettings)
    pg_grade: PointerProperty(type=PGGradeData, poll=_poll_grade_data,
                              update=_selection_changed)

    def init(self, _context):
        _index_output_node(self)

    def copy(self, _source):
        _index_output_node(self)

    def draw_buttons(self, context, layout):
        layout.context_pointer_set("pg_node", self)
        layout.template_ID(self, "pg_grade", new=PG_OT_new_grade.bl_idname,
                           unlink=PG_OT_unlink_grade.bl_idname)
        _draw_node_status(self, layout)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)

    def free(self):
        _dispose_node(self)


class PGShaderGradePerNode(bpy.types.ShaderNodeCustomGroup):
    bl_idname = "PGShaderGradePerNode"
    bl_label = localization.native("node.grade.per_node_title")
    bl_translation_context = localization.CONTEXT
    bl_width_default = 260
    __annotations__ = (
        _linear_setting_properties(animatable=True)
        | _tone_setting_properties(animatable=True)
    )

    def init(self, _context):
        _index_output_node(self)

    def copy(self, _source):
        if _NODE_ANIMATION_ERROR in self:
            del self[_NODE_ANIMATION_ERROR]
        _index_output_node(self)

    def draw_buttons(self, _context, layout):
        _draw_node_status(self, layout)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)

    def free(self):
        _dispose_node(self)


class PGCompositorGradePerNode(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "PGCompositorGradePerNode"
    bl_label = localization.native("node.grade.per_node_title")
    bl_translation_context = localization.CONTEXT
    bl_width_default = 260
    __annotations__ = (
        _linear_setting_properties(animatable=True)
        | _tone_setting_properties(animatable=True)
    )

    def init(self, _context):
        _index_output_node(self)

    def copy(self, _source):
        if _NODE_ANIMATION_ERROR in self:
            del self[_NODE_ANIMATION_ERROR]
        _index_output_node(self)

    def draw_buttons(self, _context, layout):
        _draw_node_status(self, layout)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)

    def free(self):
        _dispose_node(self)


class PG_OT_new_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.new_grade"
    bl_label = localization.native("operator.new_grade")
    bl_description = localization.native("action.new_grade_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _is_shared_grade_node(_node_from_context(context))

    def execute(self, context):
        node = _node_from_context(context)
        if not _is_shared_grade_node(node):
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
    bl_label = localization.native("operator.unlink_grade")
    bl_description = localization.native("action.unlink_grade_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        return _is_shared_grade_node(node) and node.pg_grade is not None

    def execute(self, context):
        node = _node_from_context(context)
        if not _is_shared_grade_node(node):
            return {"CANCELLED"}
        node.pg_grade = None
        return {"FINISHED"}


class PG_OT_match_white(bpy.types.Operator):
    bl_idname = "perceptual_grade.match_white"
    bl_label = localization.native("operator.match_white")
    bl_description = localization.native("action.match_white_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        return (_is_per_node_grade_node(node)
                or (_is_shared_grade_node(node) and node.pg_grade is not None))

    def execute(self, context):
        node = _node_from_context(context)
        if not _is_per_node_grade_node(node) and (
                not _is_shared_grade_node(node) or node.pg_grade is None):
            return {"CANCELLED"}
        _assign_values(node, {"source_x": D65[0], "source_y": D65[1]})
        return {"FINISHED"}


class PG_OT_reset_directions(bpy.types.Operator):
    bl_idname = "perceptual_grade.reset_directions"
    bl_label = localization.native("operator.reset_directions")
    bl_description = localization.native("action.reset_directions_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        return (_is_per_node_grade_node(node)
                or (_is_shared_grade_node(node) and node.pg_grade is not None))

    def execute(self, context):
        node = _node_from_context(context)
        if not _is_per_node_grade_node(node) and (
                not _is_shared_grade_node(node) or node.pg_grade is None):
            return {"CANCELLED"}
        _assign_values(node, {name: 0.0 for name in _LINEAR_FIELDS[3:]})
        return {"FINISHED"}


class PG_OT_reset_tone(bpy.types.Operator):
    bl_idname = "perceptual_grade.reset_tone"
    bl_label = localization.native("operator.reset_tone")
    bl_description = localization.native("action.reset_tone_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = _output_node_from_context(context)
        if node is None:
            return False
        if _is_per_node_grade_node(node):
            return True
        return (_stack_active_grade(node) if _is_stack_node(node)
                else node.pg_grade) is not None

    def execute(self, context):
        node = _output_node_from_context(context)
        if node is None:
            return {"CANCELLED"}
        if _is_per_node_grade_node(node):
            _reset_tone(_tone_controls(node))
            _per_node_grade_changed(node)
            return {"FINISHED"}
        grade = _stack_active_grade(node) if _is_stack_node(node) else node.pg_grade
        if grade is None:
            return {"CANCELLED"}
        _reset_tone(grade.pg_tone)
        _grade_changed(grade)
        return {"FINISHED"}


class PG_OT_add_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.add_grade"
    bl_label = localization.native("operator.add_grade")
    bl_description = localization.native("action.add_grade_description")
    bl_translation_context = localization.CONTEXT
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


class PG_OT_convert_grade(bpy.types.Operator):
    bl_idname = "perceptual_grade.convert_grade"
    bl_label = localization.native("operator.convert_grade")
    bl_description = localization.native("action.convert_grade_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}
    target_kind: EnumProperty(
        items=(
            ("NODE", localization.native("action.convert_to_node"), ""),
            ("DATABLOCK", localization.native("action.convert_to_datablock"), ""),
        ),
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        node = _node_from_context(context)
        space = getattr(context, "space_data", None)
        return (node is not None and node.id_data.bl_idname in NODE_TYPES
                and getattr(space, "type", None) == "NODE_EDITOR"
                and space.edit_tree == node.id_data
                and node.id_data.is_editable and not _node_reset_pending)

    @classmethod
    def description(cls, _context, properties):
        message = ("action.convert_to_node_description"
                   if properties.target_kind == "NODE"
                   else "action.convert_to_datablock_description")
        return localization.tr(message, locale=localization.tooltip_language())

    def execute(self, context):
        node = _node_from_context(context)
        if node is None or not PG_OT_convert_grade.poll(context):
            return {"CANCELLED"}
        try:
            convert_grade_node(node, self.target_kind)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class PG_OT_add_stack(bpy.types.Operator):
    bl_idname = "perceptual_grade.add_stack"
    bl_label = localization.native("operator.add_stack")
    bl_description = localization.native("action.add_stack_description")
    bl_translation_context = localization.CONTEXT
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
    bl_label = localization.native("operator.stack_action")
    bl_description = localization.native("action.stack_action_description")
    bl_translation_context = localization.CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(
        name=localization.native("property.action"),
        translation_context=localization.CONTEXT,
        items=(("ADD", localization.native("enum.action.add"), ""),
               ("REMOVE", localization.native("enum.action.remove"), ""),
               ("MOVE", localization.native("enum.action.move"), ""),
               ("SELECT", localization.native("enum.action.select"), "")),
    )
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
            _index_output_node(node)
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
    bl_label = localization.native("operator.new_stack_grade")
    bl_description = localization.native("action.new_stack_grade_description")
    bl_translation_context = localization.CONTEXT
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


def _scene_grade_nodes(scene):
    roots = []
    for owner in (getattr(scene, "world", None),
                  getattr(scene, "compositing_node_group", None),
                  getattr(scene, "node_tree", None)):
        tree = getattr(owner, "node_tree", owner)
        if tree is not None:
            roots.append(tree)
    for obj in tuple(getattr(scene, "objects", ())):
        for slot in tuple(getattr(obj, "material_slots", ())):
            material = getattr(slot, "material", None)
            if material is not None and getattr(material, "use_nodes", False):
                roots.append(material.node_tree)
        data = getattr(obj, "data", None)
        if getattr(data, "use_nodes", False):
            tree = getattr(data, "node_tree", None)
            if tree is not None:
                roots.append(tree)

    outputs = {}
    seen = set()

    def visit(tree):
        if tree is None:
            return
        try:
            pointer = tree.as_pointer()
            if not pointer or pointer in seen:
                return
            seen.add(pointer)
            tree_nodes = tuple(tree.nodes)
        except (AttributeError, ReferenceError, RuntimeError):
            return
        for node in tree_nodes:
            if _is_output_node(node):
                outputs[node.as_pointer()] = node
                continue
            child = getattr(node, "node_tree", None)
            if child is not None:
                visit(child)

    for tree in roots:
        visit(tree)
    return tuple(outputs.values())


def _animation_snapshot(scene):
    nodes = _scene_grade_nodes(scene)
    signatures = []
    for node in nodes:
        signature = _settings_signature_for(node)
        if signature is None:
            raise RuntimeError("Could not read evaluated Grade settings")
        signatures.append((node.as_pointer(), signature))
    signatures = tuple(sorted(signatures))
    digest = hashlib.sha256(json.dumps(signatures, separators=(",", ":"))
                            .encode("ascii")).hexdigest()
    return nodes, dict(signatures), digest


def _animation_outputs_current(nodes, signatures, *, validate_graph=True):
    for node in nodes:
        pointer = node.as_pointer()
        signature = signatures.get(pointer)
        record = _node_stores.get(pointer)
        if record is None:
            return False, None
        state = record["state"]
        if state.error is not None:
            return False, state.error
        if (signature is None or state.desired_signature != signature
                or state.applied_signature != signature
                or state.applied_quality != "full"
                or not node_policy.output_allowed(state)):
            return False, None
        if not _kernel_is_current(
                node.node_tree, node.id_data.bl_idname, signature, "full",
                stack=_is_stack_node(node), validate_graph=validate_graph):
            return False, "Installed Grade kernel does not match the evaluated frame"
    return True, None


class PG_PT_linear(bpy.types.Panel):
    bl_idname = "PG_PT_linear"
    bl_label = localization.native("panel.linear")
    bl_translation_context = localization.CONTEXT
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = localization.native("panel.category")

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
        grade = node.pg_grade if _is_shared_grade_node(node) else None
        settings = _linear_controls(grade if grade is not None else node)
        layout = self.layout.column()
        layout.enabled = _is_per_node_grade_node(node) or grade is not None
        layout.prop(settings, "exposure", slider=True)
        row = layout.row(align=True)
        row.prop(settings, "source_x")
        row.prop(settings, "source_y")
        layout.operator(
            PG_OT_match_white.bl_idname,
            text=localization.tr("operator.match_white"), icon="COLOR",
        )
        row = layout.row()
        row.enabled = False
        row.label(text=localization.tr("label.working_white"))
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
    bl_label = localization.native("panel.tone")
    bl_translation_context = localization.CONTEXT
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = localization.native("panel.category")

    @classmethod
    def poll(cls, context):
        return PG_PT_linear.poll(context)

    def draw(self, context):
        node = _output_node_from_context(context)
        if _is_output_node(node):
            _draw_tone_settings(node, self.layout)


def convert_grade_node(node, target_kind):
    """Replace a Grade's ownership while retaining its graph and current values."""
    if not _is_grade_node(node) or target_kind not in {"NODE", "DATABLOCK"}:
        raise ValueError("Grade conversion requires a Grade node and an ownership kind")
    tree = node.id_data
    if not tree.is_editable or _node_reset_pending:
        raise RuntimeError("The Grade node tree is not currently editable")
    target_types = PER_NODE_NODE_TYPES if target_kind == "NODE" else NODE_TYPES
    if node.bl_idname == target_types[tree.bl_idname]:
        return node

    owner = node.pg_grade if _is_shared_grade_node(node) else node
    values = (_LINEAR_DEFAULTS | TONE_DEFAULTS) if owner is None else {
        name: getattr(controls, name)
        for controls, fields in ((_linear_controls(owner), _LINEAR_FIELDS),
                                 (_tone_controls(owner), _TONE_FIELDS))
        for name in fields
    }
    snapshot = _kernel_snapshot(node)
    name = node.name
    parent, location = node.parent, tuple(node.location)
    active = tree.nodes.active
    source_record = _node_stores.get(node.as_pointer())
    presentation = {
        field: getattr(node, field)
        for field in ("label", "width", "height", "hide", "mute", "select",
                      "show_options", "show_preview", "show_texture",
                      "use_custom_color")
    }
    presentation["color"] = tuple(node.color)
    custom = {}
    for key, value in node.items():
        if key.startswith("_perceptual_grade") or key in node.bl_rna.properties:
            continue
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        elif hasattr(value, "to_list"):
            value = value.to_list()
        custom[key] = value

    replacement = None
    grade = None
    animation = None
    source_pointer = node.as_pointer()
    replacement_temporary_name = None
    source_temporary_name = "_pg_conversion_" + uuid4().hex
    source_removed = False
    source_disposal_finalized = False
    try:
        replacement = tree.nodes.new(target_types[tree.bl_idname])
        replacement_temporary_name = replacement.name
        replacement.parent = parent
        replacement.location = location
        for field, value in presentation.items():
            setattr(replacement, field, value)
        for key, value in custom.items():
            replacement[key] = value
        if target_kind == "DATABLOCK":
            grade = _make_grade()
            with _suspend(replacement):
                replacement.pg_grade = grade
        destination = grade if grade is not None else replacement
        for controls, fields in ((_linear_controls(destination), _LINEAR_FIELDS),
                                 (_tone_controls(destination), _TONE_FIELDS)):
            with _suspend(controls):
                for field in fields:
                    setattr(controls, field, values[field])

        removed = (*_LINEAR_FIELDS, *_TONE_FIELDS) if target_kind == "DATABLOCK" else ()
        target_mapping = {}
        if target_kind == "DATABLOCK":
            target_mapping = {
                **{field: (grade, "pg_linear." + field)
                   for field in _LINEAR_FIELDS},
                **{field: (grade, "pg_tone." + field)
                   for field in _TONE_FIELDS},
            }
        else:
            target_mapping = {
                **{"pg_grade.pg_linear." + field:
                   (tree, replacement.path_from_id(field))
                   for field in _LINEAR_FIELDS},
                **{"pg_grade.pg_tone." + field:
                   (tree, replacement.path_from_id(field))
                   for field in _TONE_FIELDS},
            }
        animation = NodeAnimationConversion(
            tree, node, replacement, removed_properties=removed,
            property_target_mapping=target_mapping,
        )
        animation.prepare()
        tree.nodes.active = replacement if active == node else active

        # Rename both nodes while the original still exists. Every operation
        # that can fail remains reversible until the final native deletion.
        _rename_conversion_node(node, source_temporary_name)
        _rename_conversion_node(replacement, name)
        animation.finish()

        failures = _refresh_nodes((replacement,))
        if failures:
            raise RuntimeError("Could not finalize converted Grade: "
                               + str(failures[-1][1]))
        remapped = _remap_node_snapshot(snapshot, node, replacement)
        for link in tuple(tree.links):
            if link.from_node == node or link.to_node == node:
                tree.links.remove(link)
        _restore_node_connections(replacement, remapped)
        failures = _refresh_nodes((replacement,))
        if failures:
            raise RuntimeError("Could not reconcile converted Grade graph: "
                               + str(failures[-1][1]))
        failures = _drain_preparations((replacement,))
        if failures:
            raise RuntimeError("Could not prepare converted Grade: "
                               + str(failures[-1][1]))
        animation.remove_grade_drivers()

        # Native disposal is the final authoritative mutation. Blender can
        # raise from a free callback after it has already removed the node.
        try:
            _remove_conversion_source(tree, node)
        except Exception as error:
            source_removed = not _conversion_source_present(tree, source_pointer)
            if not source_removed:
                raise
            print("Perceptual Grade source cleanup failed after conversion:", error)
            disposal_errors = _finalize_conversion_source(
                source_pointer, snapshot["kernel"], source_record,
            )
            source_disposal_finalized = True
            for disposal_error in disposal_errors:
                print("Perceptual Grade source disposal failed after conversion:",
                      disposal_error)
        else:
            source_removed = not _conversion_source_present(tree, source_pointer)
            if not source_removed:
                raise RuntimeError("Blender did not remove the converted Grade node")

        for cleanup_error in animation.commit():
            print("Perceptual Grade conversion cleanup failed:", cleanup_error)
        return replacement
    except Exception as error:
        if source_removed or not _conversion_source_present(tree, source_pointer):
            # The source is gone, so preserve the completed replacement and
            # report failure through its normal fail-closed policy path.
            source_removed = True
            if not source_disposal_finalized:
                disposal_errors = _finalize_conversion_source(
                    source_pointer, snapshot["kernel"], source_record,
                )
                source_disposal_finalized = True
                for disposal_error in disposal_errors:
                    print("Perceptual Grade source disposal failed after conversion:",
                          disposal_error)
            if animation is not None:
                try:
                    for cleanup_error in animation.commit():
                        print("Perceptual Grade conversion cleanup failed:", cleanup_error)
                except Exception as cleanup_error:
                    print("Perceptual Grade conversion cleanup failed:", cleanup_error)
            print("Perceptual Grade conversion committed with cleanup error:", error)
            return replacement
        rollback_errors = []
        if replacement is not None and replacement_temporary_name is not None:
            try:
                _rename_conversion_node(replacement, replacement_temporary_name)
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        try:
            _rename_conversion_node(node, name)
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
        if animation is not None:
            try:
                animation.rollback()
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        if replacement is not None:
            try:
                tree.nodes.remove(replacement)
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        try:
            _restore_node_connections(node, snapshot)
            tree.nodes.active = active
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
            _block_nodes((node,), rollback_error)
        if grade is not None and grade.users == 0:
            bpy.data.node_groups.remove(grade)
        if rollback_errors:
            raise ExceptionGroup("Grade conversion rollback failed",
                                 [error, *rollback_errors]) from error
        raise


def _rename_conversion_node(node, name):
    node.name = name


def _remove_conversion_source(tree, node):
    tree.nodes.remove(node)


def _conversion_source_present(tree, pointer):
    return any(candidate.as_pointer() == pointer for candidate in tree.nodes)


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


def create_per_node_node(tree):
    try:
        node_type = PER_NODE_NODE_TYPES[tree.bl_idname]
    except KeyError as exc:
        raise ValueError("Per-Node Grade nodes require a Shader or Compositor tree") from exc

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
    self.layout.operator(
        PG_OT_add_grade.bl_idname,
        text=localization.tr("operator.add_grade"), icon="COLOR",
    )
    self.layout.operator(
        PG_OT_add_stack.bl_idname,
        text=localization.tr("operator.add_stack"), icon="NODETREE",
    )


def draw_context_menu(self, context):
    if not PG_OT_convert_grade.poll(context):
        return
    node = _node_from_context(context)
    target_kind = "NODE" if _is_shared_grade_node(node) else "DATABLOCK"
    message = "action.convert_to_node" if target_kind == "NODE" else "action.convert_to_datablock"
    self.layout.separator()
    self.layout.operator(
        PG_OT_convert_grade.bl_idname, text=localization.tr(message),
        icon="ANIM_DATA" if target_kind == "NODE" else "NODETREE",
    ).target_kind = target_kind


def _register_handlers():
    for collection, callback in (
        (bpy.app.handlers.load_post, _load_post),
        (bpy.app.handlers.undo_pre, _undo_redo_pre),
        (bpy.app.handlers.redo_pre, _undo_redo_pre),
        (bpy.app.handlers.undo_post, _undo_redo_post),
        (bpy.app.handlers.redo_post, _undo_redo_post),
        (bpy.app.handlers.frame_change_pre, _frame_change_pre),
        (bpy.app.handlers.frame_change_post, _frame_change_post),
        (bpy.app.handlers.render_pre, _render_pre),
        (bpy.app.handlers.render_init, _render_init),
        (bpy.app.handlers.render_complete, _render_finished),
        (bpy.app.handlers.render_cancel, _render_cancelled),
        (bpy.app.handlers.composite_pre, _compositor_pre),
        (bpy.app.handlers.composite_post, _compositor_post),
        (bpy.app.handlers.composite_cancel, _compositor_cancel),
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
        PGShaderGradePerNode,
        PGCompositorGradePerNode,
        PG_OT_new_grade,
        PG_OT_unlink_grade,
        PG_OT_match_white,
        PG_OT_reset_directions,
        PG_OT_reset_tone,
        PG_OT_add_grade,
        PG_OT_convert_grade,
        PG_OT_add_stack,
        PG_OT_stack_action,
        PG_OT_new_stack_grade,
        PG_OT_gesture_router,
        PG_PT_linear,
        PG_PT_tone,
    )
    try:
        localization.register()
        if _preparation_runtime is None:
            if _grade_resources is not None:
                # A failed prior shutdown may still own native-reader pins.
                _reset_node_stores()
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

        menus = tuple((menu_type, draw_add_menu) for menu_type in MENU_TYPES) + (
            (bpy.types.NODE_MT_context_menu, draw_context_menu),
        )
        for menu_type, callback in menus:
            record = (menu_type, callback)
            if record not in _registered_menus:
                if callback not in getattr(menu_type.draw, "_draw_funcs", ()):
                    menu_type.append(callback)
                _registered_menus.append(record)
        _register_handlers()
        if not bpy.app.timers.is_registered(_startup_reconcile_tick):
            bpy.app.timers.register(_startup_reconcile_tick, first_interval=0.1)
        _ensure_gesture_router_timer()
        if not bpy.app.timers.is_registered(_render_preflight_tick):
            bpy.app.timers.register(_render_preflight_tick, first_interval=0.02,
                                    persistent=True)
        if not bpy.app.timers.is_registered(_frame_reconcile_tick):
            bpy.app.timers.register(_frame_reconcile_tick, first_interval=0.1,
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
    if _grade_resources is not None:
        # Reject a busy shutdown before removing the callbacks that can
        # acknowledge existing readers and make a later retry safe.
        _grade_resources.gate.reset()
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
        if bpy.app.timers.is_registered(_frame_reconcile_tick):
            bpy.app.timers.unregister(_frame_reconcile_tick)
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
    try:
        _reset_node_stores()
    except Exception as exc:
        # Retain the pool and its image pins if host work started meanwhile.
        errors.append(exc)
    else:
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

    try:
        localization.unregister()
    except Exception as exc:
        errors.append(exc)

    if errors:
        raise ExceptionGroup("Grade node teardown failed", errors)
