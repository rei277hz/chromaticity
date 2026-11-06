"""Small Shader and Compositor nodes for comparing helper image publication."""

from dataclasses import dataclass, field
import math
import sys
import threading
from typing import Optional
from uuid import uuid4

import bpy
from bpy.app.handlers import persistent
from bpy.props import FloatProperty, PointerProperty

from .policy import bank_publication, image_publication, parameter_publication
from .runtime.compositor_receipts import CompositorReceipts
from .runtime.image_publication import (
    ImageSnapshot,
    run_image_publication,
    write_metadata,
)
from .runtime.parameter_publication import run_parameter_publication
from .runtime.bank_publication import run_bank_publication
from .runtime.publication_compare_diagnostics import Capture
from .runtime.publication import PublicationDeferred, PublicationGate


SHADER_TREE = "ShaderNodeTree"
COMPOSITOR_TREE = "CompositorNodeTree"
VERSIONED_IDS = {SHADER_TREE: "PGDemoShaderVersioned",
                 COMPOSITOR_TREE: "PGDemoCompositorVersioned"}
ORIGINAL_IDS = {SHADER_TREE: "PGDemoShaderOriginal",
                COMPOSITOR_TREE: "PGDemoCompositorOriginal"}
BANKED_IDS = {SHADER_TREE: "PGDemoShaderBanked",
              COMPOSITOR_TREE: "PGDemoCompositorBanked"}
NODE_IDS = frozenset((*VERSIONED_IDS.values(), *ORIGINAL_IDS.values(), *BANKED_IDS.values()))
_TREE_MARKER = "_pg_publication_compare"
_VARIANT = "_pg_publication_variant"
_OWNER = "_pg_publication_owner"
_BINDING = "_pg_publication_helper"
_SIGNATURE = "_pg_publication_exposure"
_READER = "_pg_publication_reader"
_ERROR_READER = "_pg_publication_error_reader"
_BANK_INDEX = "_pg_publication_bank"
_BANK_SELECTOR = "_pg_publication_bank_selector"
_registered_classes = []
_registered_menus = []
_registered_handlers = []
_pending = {}
_pools = {}
_publication_trace = None
_gate = PublicationGate(bpy)
_receipts = CompositorReceipts()
_generation = 1
_loading = False
_reset_pending = False
_startup_reconcile = False


@dataclass
class Version:
    image: object
    generation: int
    exposed: bool = False


@dataclass
class VersionPool:
    tree: object
    current: Version
    candidate: Optional[Version] = None
    retained: list = field(default_factory=list)

    @property
    def versions(self):
        values = [self.current, self.candidate, *self.retained]
        return tuple({id(value): value for value in values if value is not None}.values())


def _tree_type(node):
    return node.id_data.bl_idname


def _new_image(tree, variant, exposure, bank_index=None):
    image = bpy.data.images.new(
        "Publication Compare helper", width=1, height=1,
        alpha=True, float_buffer=True,
    )
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    image.use_half_precision = False
    image["_pg_publication_owner"] = tree.get(_OWNER)
    image[_VARIANT] = variant
    image[_SIGNATURE] = float(exposure)
    if bank_index is not None:
        image[_BANK_INDEX] = bank_index
    if variant == "versioned":
        image["_pg_publication_generation"] = 1
    image.pixels.foreach_set((exposure, exposure, exposure, 1.0))
    image.update()
    image.pack()
    if image.packed_file is None or image.is_dirty:
        raise RuntimeError("Could not pack the helper image")
    return image


def _bank_selector(tree):
    return next((node for node in tree.nodes if node.get(_BANK_SELECTOR)), None)


def _active_bank(tree):
    selector = _bank_selector(tree)
    if selector is None:
        return 0
    if selector.bl_idname == "ShaderNodeValue":
        value = float(selector.outputs["Value"].default_value)
    elif selector.bl_idname == "CompositorNodeSwitch":
        value = float(selector.inputs["Switch"].default_value)
    else:
        value = float(selector.inputs[0].default_value + selector.inputs[1].default_value)
    if value not in (0.0, 1.0):
        raise RuntimeError("Banked helper selector is invalid")
    return int(value)


def _set_active_bank(tree, index):
    if index not in (0, 1):
        raise ValueError("Bank index must be 0 or 1")
    selector = _bank_selector(tree)
    if selector is None:
        raise RuntimeError("Banked helper selector is missing")
    if selector.bl_idname == "ShaderNodeValue":
        selector.outputs["Value"].default_value = float(index)
    elif selector.bl_idname == "CompositorNodeSwitch":
        selector.inputs["Switch"].default_value = bool(index)
    else:
        selector.inputs[0].default_value = float(index)


def _helper_readers(tree):
    readers = tuple(node for node in tree.nodes if node.get(_READER))
    if tree.get(_VARIANT) != "banked":
        return readers[:1]
    if len(readers) != 2:
        raise RuntimeError("Banked helper readers are incomplete")
    by_bank = {int(node.get(_BANK_INDEX, -1)): node for node in readers}
    if set(by_bank) != {0, 1}:
        raise RuntimeError("Banked helper reader indices are invalid")
    return tuple(by_bank[index] for index in range(2))


def _helper_reader(tree):
    readers = _helper_readers(tree)
    if not readers:
        return None
    if tree.get(_VARIANT) == "banked":
        return readers[_active_bank(tree)]
    return readers[0]


def _helper_image(tree):
    reader = _helper_reader(tree)
    return None if reader is None else getattr(reader, "image", None)


def _error_value_node(tree):
    return next((node for node in tree.nodes if node.get(_ERROR_READER)), None)


def _set_pending(tree, pending):
    try:
        pointer = tree.as_pointer()
        if pointer:
            was_pending = pointer in _pending
            if pending:
                _pending[pointer] = tree
            else:
                _pending.pop(pointer, None)
            if was_pending != bool(pending) and _publication_trace is not None:
                _publication_trace.lifecycle("publication_pending", tree,
                                             pending=bool(pending),
                                             exposure=float(tree.pg_publication.exposure))
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    for node in _outer_users(tree):
        node.use_custom_color = bool(tree.get("_pg_publication_error"))
        if node.use_custom_color:
            node.color = (0.9, 0.08, 0.8)
    for area in _node_areas():
        try:
            area.tag_redraw()
        except (ReferenceError, RuntimeError):
            pass


def _set_error(tree, error):
    if error:
        tree["_pg_publication_error"] = str(error)[:240]
    elif "_pg_publication_error" in tree:
        del tree["_pg_publication_error"]
    value = _error_value_node(tree)
    if value is not None:
        if value.bl_idname == "CompositorNodeRGB":
            gate = 1.0 if error else 0.0
            value.outputs[0].default_value = (gate, gate, gate, 1.0)
        else:
            value.outputs[0].default_value = 1.0 if error else 0.0
    if _publication_trace is not None:
        _publication_trace.lifecycle("publication_gate", tree,
                                     closed=bool(error),
                                     error=str(error)[:240] if error else "")
    tree.update_tag()
    _set_pending(tree, False)
    _tag_outputs(tree)


def _all_user_node_trees():
    trees = list(bpy.data.node_groups)
    for collection_name in ("materials", "worlds", "lights", "linestyles"):
        for owner in getattr(bpy.data, collection_name, ()):
            tree = getattr(owner, "node_tree", None)
            if tree is not None and tree not in trees:
                trees.append(tree)
    for scene in bpy.data.scenes:
        tree = getattr(scene, "compositing_node_group", None)
        if tree is not None and tree not in trees:
            trees.append(tree)
    return tuple(trees)


def _outer_users(tree):
    result = []
    for owner_tree in _all_user_node_trees():
        try:
            result.extend(node for node in owner_tree.nodes
                          if getattr(node, "node_tree", None) == tree)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    return tuple(result)


def _node_areas():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "NODE_EDITOR":
                yield area


def _trace_operations(tree, operations):
    capture = _publication_trace
    if capture is None:
        return operations
    try:
        return capture.wrap_operations(tree, operations)
    except Exception as error:
        capture.lifecycle("diagnostic_error", tree, operation="wrap_operations",
                          error=str(error))
        return operations


def _compositor_users(root, target, found=None, visited=None):
    found = [] if found is None else found
    visited = set() if visited is None else visited
    try:
        pointer = root.as_pointer()
    except (AttributeError, ReferenceError):
        return found
    if pointer in visited:
        return found
    visited.add(pointer)
    for node in root.nodes:
        child = getattr(node, "node_tree", None)
        if child is None:
            continue
        if child == target:
            found.append(node.as_pointer())
        _compositor_users(child, target, found, visited)
    return found


def _scenes_for_tree(tree):
    result = []
    for scene in bpy.data.scenes:
        root = getattr(scene, "compositing_node_group", None)
        if root is None:
            continue
        users = _compositor_users(root, tree)
        if users:
            result.append((scene, tuple(users)))
    return tuple(result)


def _tag_outputs(tree):
    tree.update_tag()
    for node in _outer_users(tree):
        try:
            node.id_data.update_tag()
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    for scene, _nodes in _scenes_for_tree(tree):
        try:
            scene.compositing_node_group.update_tag()
            scene.update_tag()
        except (AttributeError, ReferenceError, RuntimeError):
            pass


def _record_compositor_bindings(tree, generation):
    bindings = {}
    for scene, nodes in _scenes_for_tree(tree):
        identity = scene.as_pointer()
        if identity:
            bindings[identity] = nodes
    return _receipts.bind(bindings, generation)


def _restore_compositor_bindings(previous):
    _receipts.restore(previous)


def _image_valid(image, variant):
    try:
        return (image is not None and image.as_pointer() != 0
                and image.get(_VARIANT) == variant
                and image.packed_file is not None and not image.is_dirty
                and tuple(image.size) == (1, 1))
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _image_matches(image, exposure):
    if image is None:
        return False
    try:
        if not _image_valid(image, image.get(_VARIANT)):
            return False
        expected = float(exposure)
        return (abs(float(image.pixels[0]) - expected) <= max(1e-6, abs(expected) * 1e-6)
                and abs(float(image.get(_SIGNATURE, math.nan)) - float(exposure)) <= 1e-6)
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return False


def _write_helper(image, exposure):
    exposure = float(exposure)
    image.pixels.foreach_set((exposure, exposure, exposure, 1.0))
    image.update()


def _pack_helper(image):
    image.pack()


def _metadata(tree, image, exposure):
    return ((tree, _BINDING, image), (tree, _SIGNATURE, float(exposure)),
            (image, _SIGNATURE, float(exposure)))


def _next_generation():
    global _generation
    _generation += 1
    return _generation


def _new_group(tree_type, variant):
    tree = bpy.data.node_groups.new("Publication Compare", tree_type)
    tree[_TREE_MARKER] = True
    tree[_VARIANT] = variant
    tree[_OWNER] = uuid4().hex
    tree.interface.new_socket(name="Color", in_out="INPUT", socket_type="NodeSocketColor")
    tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    if tree_type == SHADER_TREE:
        tree.interface.items_tree[0].default_value = (0.0, 0.0, 0.0, 1.0)
        alpha_input = tree.interface.new_socket(
            name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat",
        )
        alpha_input.default_value = 1.0
        tree.interface.new_socket(name="Alpha", in_out="OUTPUT",
                                  socket_type="NodeSocketFloat")

    exposure_value = float(tree.pg_publication.exposure)
    banked = variant == "banked"
    images = (tuple(_new_image(tree, variant, exposure_value, index)
                    for index in range(2)) if banked
              else (_new_image(tree, variant, exposure_value),))
    group_input = tree.nodes.new("NodeGroupInput")
    group_output = tree.nodes.new("NodeGroupOutput")
    group_output.is_active_output = True
    readers = []
    for index, image in enumerate(images):
        reader = tree.nodes.new("ShaderNodeTexImage" if tree_type == SHADER_TREE
                                else "CompositorNodeImage")
        reader.image = image
        reader[_READER] = True
        if banked:
            reader[_BANK_INDEX] = index
        readers.append(reader)

    if tree_type == SHADER_TREE:
        for reader in readers:
            reader.interpolation = "Closest"
        input_split = tree.nodes.new("ShaderNodeSeparateColor")
        tree.links.new(group_input.outputs["Color"], input_split.inputs["Color"])
        graded_colors = []
        for reader in readers:
            helper_split = tree.nodes.new("ShaderNodeSeparateColor")
            helper_split.mode = "RGB"
            tree.links.new(reader.outputs["Color"], helper_split.inputs["Color"])
            factor = tree.nodes.new("ShaderNodeMath")
            factor.operation = "POWER"
            factor.inputs[0].default_value = 2.0
            tree.links.new(helper_split.outputs["Red"], factor.inputs[1])
            channels = []
            for name in ("Red", "Green", "Blue"):
                multiply = tree.nodes.new("ShaderNodeMath")
                multiply.operation = "MULTIPLY"
                tree.links.new(input_split.outputs[name], multiply.inputs[0])
                tree.links.new(factor.outputs[0], multiply.inputs[1])
                channels.append(multiply.outputs[0])
            combine = tree.nodes.new("ShaderNodeCombineColor")
            combine.mode = "RGB"
            for name, channel in zip(("Red", "Green", "Blue"), channels):
                tree.links.new(channel, combine.inputs[name])
            graded_colors.append(combine.outputs["Color"])
        if banked:
            selector = tree.nodes.new("ShaderNodeValue")
            selector[_BANK_SELECTOR] = True
            selector.outputs["Value"].default_value = 0.0
            select = tree.nodes.new("ShaderNodeMixRGB")
            select.blend_type = "MIX"
            tree.links.new(selector.outputs["Value"], select.inputs[0])
            tree.links.new(graded_colors[0], select.inputs[1])
            tree.links.new(graded_colors[1], select.inputs[2])
            graded_color = select.outputs["Color"]
        else:
            graded_color = graded_colors[0]
        error = tree.nodes.new("ShaderNodeValue")
        error.name = "Publication error gate"
        error[_ERROR_READER] = True
        magenta = tree.nodes.new("ShaderNodeRGB")
        magenta.outputs["Color"].default_value = (1.0, 0.0, 1.0, 1.0)
        normal = tree.nodes.new("ShaderNodeMixRGB")
        normal.blend_type = "MIX"
        tree.links.new(error.outputs["Value"], normal.inputs[0])
        tree.links.new(graded_color, normal.inputs[1])
        tree.links.new(magenta.outputs["Color"], normal.inputs[2])
        tree.links.new(normal.outputs["Color"], group_output.inputs["Color"])
        tree.links.new(group_input.outputs["Alpha"], group_output.inputs["Alpha"])
    else:
        helper_image = readers[0].outputs["Image"]
        if banked:
            selector = tree.nodes.new("CompositorNodeSwitch")
            selector[_BANK_SELECTOR] = True
            selector.inputs["Switch"].default_value = False
            tree.links.new(readers[0].outputs["Image"], selector.inputs["Off"])
            tree.links.new(readers[1].outputs["Image"], selector.inputs["On"])
            helper_image = selector.outputs["Image"]
        sample = tree.nodes.new("CompositorNodeMapUV")
        sample.inputs["UV"].default_value = (0.5, 0.5, 1.0)
        sample.inputs["Interpolation"].default_value = "Nearest"
        sample.inputs["Extension X"].default_value = "Extend"
        sample.inputs["Extension Y"].default_value = "Extend"
        tree.links.new(helper_image, sample.inputs["Image"])
        exposure_value = tree.nodes.new("CompositorNodeRGBToBW")
        tree.links.new(sample.outputs["Image"], exposure_value.inputs["Image"])
        input_split = tree.nodes.new("CompositorNodeSeparateColor")
        input_split.mode = "RGB"
        tree.links.new(group_input.outputs["Color"], input_split.inputs["Image"])
        exposure = tree.nodes.new("CompositorNodeExposure")
        tree.links.new(group_input.outputs["Color"], exposure.inputs["Image"])
        tree.links.new(exposure_value.outputs["Val"], exposure.inputs["Exposure"])
        error = tree.nodes.new("CompositorNodeRGB")
        error.name = "Publication error gate"
        error.outputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        error[_ERROR_READER] = True
        error_value = tree.nodes.new("CompositorNodeRGBToBW")
        tree.links.new(error.outputs[0], error_value.inputs["Image"])
        magenta = tree.nodes.new("CompositorNodeRGB")
        magenta.outputs[0].default_value = (1.0, 0.0, 1.0, 1.0)
        select = tree.nodes.new("CompositorNodeSwitch")
        tree.links.new(error_value.outputs["Val"], select.inputs["Switch"])
        tree.links.new(exposure.outputs["Image"], select.inputs["Off"])
        tree.links.new(magenta.outputs[0], select.inputs["On"])
        restore = tree.nodes.new("CompositorNodeSetAlpha")
        restore.inputs["Type"].default_value = "Replace Alpha"
        tree.links.new(select.outputs["Image"], restore.inputs["Image"])
        tree.links.new(input_split.outputs["Alpha"], restore.inputs["Alpha"])
        tree.links.new(restore.outputs["Image"], group_output.inputs["Color"])
    tree[_BINDING] = images[0]
    tree[_SIGNATURE] = 0.0
    if variant == "versioned":
        _pools[tree.as_pointer()] = VersionPool(
            tree, Version(image, 1, exposed=True),
        )
    return tree


def _pool_for(tree):
    global _generation
    pointer = tree.as_pointer()
    pool = _pools.get(pointer)
    if pool is not None:
        try:
            if pool.tree.as_pointer() == pointer:
                return pool
        except ReferenceError:
            pass
    current = _helper_image(tree)
    if current is None:
        raise RuntimeError("Versioned helper binding is missing")
    owner = tree.get(_OWNER)
    retained = []
    for image in bpy.data.images:
        if (image != current and image.get("_pg_publication_owner") == owner
                and image.get(_VARIANT) == "versioned"):
            generation = int(image.get("_pg_publication_generation", 0))
            retained.append(Version(image, generation, generation > 0))
    pool = VersionPool(tree, Version(current, int(current.get("_pg_publication_generation", 1)), True),
                       retained=retained)
    _generation = max([_generation, *(version.generation for version in pool.versions)])
    _pools[pointer] = pool
    return pool


def _reclaim(pool):
    failures = []
    for version in tuple(pool.retained):
        image = version.image
        try:
            live = bool(image.as_pointer())
            users = image.users if live else 0
            protected = image.use_fake_user if live else False
        except (AttributeError, ReferenceError):
            live, users, protected = False, 0, False
        effect = parameter_publication.retirement_effect(
            live, _gate.retirement_allowed(), version is pool.current,
            version is pool.candidate, users, protected,
        )
        if effect.action == "evict":
            pool.retained.remove(version)
        elif effect.action == "remove":
            try:
                live = bool(image.as_pointer())
                users = image.users if live else 0
                protected = image.use_fake_user if live else False
            except (AttributeError, ReferenceError):
                live, users, protected = False, 0, False
            effect = parameter_publication.retirement_effect(
                live, _gate.retirement_allowed(), version is pool.current,
                version is pool.candidate, users, protected,
            )
            if effect.action != "remove":
                continue
            try:
                bpy.data.images.remove(image, do_unlink=False)
            except Exception as error:
                failures.append(error)
            else:
                pool.retained.remove(version)
    if failures:
        raise ExceptionGroup("Helper image retirement failed", failures)


def _candidate_grant(pool):
    candidate = pool.candidate
    effect = parameter_publication.candidate_effect(
        len(pool.versions), candidate is not None,
        candidate.exposed if candidate is not None else False,
    )
    return effect.action


def _versioned_transaction(tree, exposure, live_scope=None):
    pool = _pool_for(tree)
    _reclaim(pool)
    grant = _candidate_grant(pool)
    if grant is None:
        _enqueue(tree)
        return ()
    context = {}

    def stage(_errors):
        if grant == "reuse":
            candidate = pool.candidate
        else:
            image = bpy.data.images.new("Publication Compare helper", 1, 1,
                                        alpha=True, float_buffer=True)
            image.colorspace_settings.name = "Non-Color"
            image.alpha_mode = "CHANNEL_PACKED"
            image.use_half_precision = False
            image["_pg_publication_owner"] = tree.get(_OWNER)
            image[_VARIANT] = "versioned"
            candidate = Version(image, 0, False)
            pool.candidate = candidate
        candidate.image[_VARIANT] = "versioned"
        candidate.image["_pg_publication_owner"] = tree.get(_OWNER)
        _write_helper(candidate.image, exposure)
        _pack_helper(candidate.image)
        clean = candidate.image.packed_file is not None and not candidate.image.is_dirty
        generation = _next_generation()
        candidate.generation = generation
        context.update(candidate=candidate, previous=pool.current,
                       generation=generation,
                       metadata=(*_metadata(tree, candidate.image, exposure),
                                 (candidate.image, "_pg_publication_generation", generation)))
        return {"clean": clean}

    def snapshot(_errors):
        image = context["candidate"].image
        context["bindings_before"] = tuple(
            (reader, reader.image) for reader in tree.nodes if reader.get(_READER)
        )
        context["metadata_before"] = tuple(
            (owner, key, owner.get(key)) for owner, key, _value in context["metadata"]
        )
        context["receipt_before"] = {}

    def bind(_errors):
        candidate = context["candidate"]
        if candidate.exposed:
            raise RuntimeError("Versioned candidate is already exposed")
        candidate.exposed = True
        for reader, _previous in context["bindings_before"]:
            reader.image = candidate.image

    def commit(_errors):
        write_metadata(context["metadata"])

    def activate(_errors):
        candidate = context["candidate"]
        previous = pool.current
        if previous is not None:
            pool.retained.append(previous)
        pool.current = candidate
        pool.candidate = None
        context["activated"] = True

    def restore_bindings(_errors):
        failures = []
        for reader, previous in context.get("bindings_before", ()):
            try:
                reader.image = previous
            except Exception as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup("Helper image binding restoration failed", failures)

    def restore_metadata(_errors):
        write_metadata(context.get("metadata_before", ()))

    def restore_resource(_errors):
        if context.get("activated"):
            failed_current = pool.current
            previous = context["previous"]
            if failed_current is not None and failed_current is not previous:
                pool.retained.append(failed_current)
            if previous in pool.retained:
                pool.retained.remove(previous)
            pool.current = previous
        _restore_compositor_bindings(context.get("receipt_before", {}))

    def fail(errors):
        _set_error(tree, errors[0] if errors else "Helper image publication failed")

    def deliver(_errors):
        resource = pool.current
        resource.image.update_tag()
        _set_error(tree, None)
        before = _record_compositor_bindings(tree, resource.generation)
        context["receipt_before"] = before
        _tag_outputs(tree)
        if live_scope is not None:
            _gate.superseded(*live_scope)

    def retire(_errors):
        candidate = context.get("candidate")
        if candidate is not None and pool.candidate is candidate and candidate.exposed:
            pool.candidate = None
            pool.retained.append(candidate)
        _reclaim(pool)

    errors = run_parameter_publication(_trace_operations(tree, {
        "stage": stage, "snapshot": snapshot, "bind": bind,
        "commit": commit, "activate": activate,
        "restore_bindings": restore_bindings,
        "restore_metadata": restore_metadata,
        "restore_resource": restore_resource,
        "fail": fail, "deliver": deliver, "retire": retire,
    }))
    return errors


def _original_transaction(tree, exposure):
    context = {}

    def prepare(_errors):
        image = _helper_image(tree)
        if image is None:
            image = _new_image(tree, "original", exposure)
            reader = _helper_reader(tree)
            if reader is None:
                raise RuntimeError("Original helper reader is missing")
            reader.image = image
            tree[_BINDING] = image
        context.update(image=image, metadata=_metadata(tree, image, exposure))

    def snapshot(_errors):
        image = context["image"]
        context["snapshot"] = ImageSnapshot.capture(image, context["metadata"])
        return {"matching": (_image_matches(image, exposure)
                             and abs(float(tree.get(_SIGNATURE, math.nan)) - exposure) <= 1e-6),
                "clean": image.packed_file is not None and not image.is_dirty}

    def upload(_errors):
        _write_helper(context["image"], exposure)

    def pack(_errors):
        _pack_helper(context["image"])
        image = context["image"]
        return {"clean": image.packed_file is not None and not image.is_dirty}

    def commit(_errors):
        write_metadata(context["metadata"])

    def restore_upload(_errors):
        context["image"].pixels.foreach_set(context["snapshot"].pixels)
        context["image"].update()

    def restore_metadata(_errors):
        write_metadata(context["snapshot"].metadata)

    def fail(errors):
        _set_error(tree, errors[0] if errors else "Helper image publication failed")

    def deliver(_errors):
        image = context["image"]
        image.update_tag()
        _set_error(tree, None)
        _tag_outputs(tree)

    return run_image_publication(_trace_operations(tree, {
        "prepare": prepare, "snapshot": snapshot, "upload": upload, "pack": pack,
        "commit": commit, "restore_upload": restore_upload, "restore_pack": pack,
        "restore_metadata": restore_metadata, "deliver": deliver,
        "fail": fail, "retire": lambda _errors: None,
    }))


def _banked_transaction(tree, exposure):
    active = _active_bank(tree)
    candidate = 1 - active
    readers = _helper_readers(tree)
    images = tuple(reader.image for reader in readers)
    if any(image is None or image.get(_VARIANT) != "banked"
           or int(image.get(_BANK_INDEX, -1)) != index
           for index, image in enumerate(images)):
        raise RuntimeError("Banked helper image layout is invalid")
    if len({image.as_pointer() for image in images}) != 2:
        raise RuntimeError("Banked helper images must be distinct")
    active_image = images[active]
    active_signature = float(active_image.get(_SIGNATURE, math.nan))
    active_valid = (
        _image_matches(active_image, active_signature)
        and abs(float(active_image.pixels[3]) - 1.0) <= 1e-6
    )
    context = {}

    def stage(bank, _errors):
        image = images[bank]
        _write_helper(image, exposure)
        _pack_helper(image)
        clean = image.packed_file is not None and not image.is_dirty
        pixel_matches = (abs(float(image.pixels[0]) - exposure) <= 1e-6
                         and abs(float(image.pixels[3]) - 1.0) <= 1e-6)
        return {"clean": clean and pixel_matches}

    def select(bank, _errors):
        image = images[bank]
        metadata = _metadata(tree, image, exposure)
        context["metadata_before"] = tuple(
            (owner, key, owner.get(key)) for owner, key, _value in metadata
        )
        _set_active_bank(tree, bank)
        selected = _active_bank(tree)
        if selected != bank:
            raise RuntimeError("Banked helper selector readback differs")
        return {"selected_bank": selected}

    def deliver(bank, _errors):
        image = images[bank]
        write_metadata(_metadata(tree, image, exposure))
        image.update_tag()
        _set_error(tree, None)
        return {"delivered": True}

    def restore_selector(bank, _errors):
        failures = []
        try:
            _set_active_bank(tree, bank)
            if _active_bank(tree) != bank:
                raise RuntimeError("Banked helper selector restoration differs")
        except Exception as error:
            failures.append(error)
        try:
            write_metadata(context.get("metadata_before", ()))
        except Exception as error:
            failures.append(error)
        try:
            _tag_outputs(tree)
        except Exception as error:
            failures.append(error)
        if failures:
            raise ExceptionGroup("Banked publication restoration failed", failures)
        return {"selected_bank": bank}

    def fail_closed(_bank, errors):
        _set_error(tree, errors[0] if errors else
                   "Banked helper image publication failed")
        return {"closed": True}

    operations = _trace_operations(tree, {
        "stage": stage,
        "select": select,
        "deliver": deliver,
        "restore_selector": restore_selector,
        "fail_closed": fail_closed,
    })
    result = run_bank_publication(active, candidate, operations,
                                  admitted=True, active_valid=active_valid)
    if result.outcome == "committed":
        return ()
    if result.errors:
        return result.errors
    if result.outcome == "failed_closed":
        return (RuntimeError("Banked publication failed closed"),)
    return (RuntimeError("Banked publication delivery is indeterminate"),)


def _enqueue(tree):
    try:
        pointer = tree.as_pointer()
        if not pointer:
            return
        if pointer not in _pending and _publication_trace is not None:
            _publication_trace.lifecycle("publication_enqueued", tree,
                                         exposure=float(tree.pg_publication.exposure))
        _pending[pointer] = tree
        _set_pending(tree, True)
        _ensure_timer()
    except (AttributeError, ReferenceError, RuntimeError):
        return


def _publish(tree, *, admitted=False):
    variant = tree.get(_VARIANT)
    exposure = float(tree.pg_publication.exposure)
    if variant not in ("versioned", "original", "banked"):
        raise RuntimeError("Publication Compare has an unknown publication variant")
    if _publication_trace is not None:
        _publication_trace.lifecycle("publication_requested", tree,
                                     exposure=exposure, admitted=bool(admitted))
    image = _helper_image(tree)
    if _image_matches(image, exposure):
        if (abs(float(tree.get(_SIGNATURE, math.nan)) - exposure) <= 1e-6
                and not tree.get("_pg_publication_error")):
            _set_pending(tree, False)
            if _publication_trace is not None:
                _publication_trace.lifecycle("publication_current", tree,
                                             exposure=exposure)
            return ()

    if admitted:
        if variant == "versioned":
            return _versioned_transaction(tree, exposure)
        if variant == "banked":
            return _banked_transaction(tree, exposure)
        return _original_transaction(tree, exposure)

    if variant == "versioned":
        lease = _gate.current_compositor()
        if lease is not None and any(scene.as_pointer() == lease[0]
                                     for scene, _nodes in _scenes_for_tree(tree)):
            try:
                with _gate.snapshot_commit(lease[0]) as epoch:
                    return _versioned_transaction(tree, exposure, (lease[0], epoch))
            except PublicationDeferred as error:
                if _publication_trace is not None:
                    _publication_trace.lifecycle("publication_deferred", tree,
                                                 reason=str(error), exposure=exposure)
                _enqueue(tree)
                return ()
    try:
        with _gate.commit():
            if variant == "versioned":
                return _versioned_transaction(tree, exposure)
            if variant == "banked":
                return _banked_transaction(tree, exposure)
            return _original_transaction(tree, exposure)
    except PublicationDeferred as error:
        if _publication_trace is not None:
            _publication_trace.lifecycle("publication_deferred", tree,
                                         reason=str(error), exposure=exposure)
        _enqueue(tree)
        return ()


def _reconcile_tree(tree, *, admitted=False):
    if not tree.get(_TREE_MARKER):
        return ()
    try:
        errors = _publish(tree, admitted=admitted)
    except Exception as error:
        _fail_closed(tree, error)
        if _publication_trace is not None:
            _publication_trace.lifecycle("publication_error", tree, error=str(error))
        return (error,)
    if _publication_trace is not None:
        _publication_trace.lifecycle("publication_reconciled", tree,
                                     error_count=len(errors),
                                     pending=tree.as_pointer() in _pending,
                                     current=_tree_is_current(tree))
    return errors


def _fail_closed(tree, error):
    failure = error if isinstance(error, BaseException) else RuntimeError(str(error))

    def fail(errors):
        _set_error(tree, errors[0] if errors else failure)

    def raise_error(_errors):
        raise failure

    if tree.get(_VARIANT) == "versioned":
        return run_parameter_publication(_trace_operations(tree, {
            "stage": raise_error, "fail": fail, "retire": lambda _errors: None,
        }))
    return run_image_publication(_trace_operations(tree, {
        "prepare": raise_error, "fail": fail, "retire": lambda _errors: None,
    }))


def _demo_trees():
    return tuple(tree for tree in bpy.data.node_groups if tree.get(_TREE_MARKER))


def _reconcile_all(*, admitted=False):
    failures = []
    for tree in _demo_trees():
        failures.extend(_reconcile_tree(tree, admitted=admitted))
    return tuple(failures)


def _tree_is_current(tree):
    try:
        return (_image_matches(_helper_image(tree), tree.pg_publication.exposure)
                and abs(float(tree.get(_SIGNATURE, math.nan))
                        - tree.pg_publication.exposure) <= 1e-6
                and not tree.get("_pg_publication_error"))
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return False


def _timer_tick():
    if not _registered_classes:
        return None
    global _reset_pending, _loading, _receipts, _startup_reconcile
    if _startup_reconcile:
        _startup_reconcile = False
        _enqueue_all()
    if _reset_pending:
        try:
            _gate.reset()
        except PublicationDeferred:
            return 0.02
        _reset_pending = False
        _receipts = CompositorReceipts()
        _pools.clear()
        _pending.clear()
        for tree in _demo_trees():
            if tree.get(_VARIANT) == "versioned":
                try:
                    _pool_for(tree)
                except Exception as error:
                    _fail_closed(tree, error)
        _loading = False
        _enqueue_all()
    try:
        _service_render_preflight()
    except Exception as error:
        for tree in _demo_trees():
            _fail_closed(tree, error)
    for pointer, tree in tuple(_pending.items()):
        try:
            if not tree.as_pointer():
                _pending.pop(pointer, None)
                continue
            errors = _reconcile_tree(tree)
            if errors or _tree_is_current(tree):
                _pending.pop(pointer, None)
        except (AttributeError, ReferenceError, RuntimeError):
            _pending.pop(pointer, None)
    for pool in tuple(_pools.values()):
        try:
            _reclaim(pool)
        except Exception as error:
            _fail_closed(pool.tree, error)
    _collect_compositor_receipts()
    return 0.02 if _pending or _gate.has_render_preflight else 0.1


def _ensure_timer():
    if (_registered_classes and not bpy.app.timers.is_registered(_timer_tick)):
        bpy.app.timers.register(_timer_tick, first_interval=0.02, persistent=True)


def _collect_compositor_receipts():
    _receipts.collect()


def _service_render_preflight(*, defer=True):
    ticket = _gate.take_render_preflight()
    if ticket is None:
        return
    try:
        with _gate.render_preflight(ticket, defer=defer):
            errors = _reconcile_all(admitted=True)
            not_ready = tuple(
                tree for tree in _demo_trees()
                if not _tree_is_current(tree)
            )
            for tree in not_ready:
                _fail_closed(tree, "Publication Compare output is not current for rendering")
            errors += tuple(RuntimeError("Publication Compare output did not reconcile")
                            for _tree in not_ready)
            if errors:
                raise RuntimeError("Publication Compare could not reconcile before render: "
                                   + "; ".join(str(error) for error in errors))
    except PublicationDeferred:
        if not defer:
            raise


@persistent
def _render_pre(_scene, *_args):
    try:
        ticket = _gate.request_render_preflight(0)
        if threading.current_thread() is threading.main_thread():
            _service_render_preflight(defer=False)
        else:
            ticket.wait()
    except Exception as error:
        for tree in _demo_trees():
            _fail_closed(tree, error)


@persistent
def _render_init(_scene, *_args):
    with _gate.callback():
        _gate.evaluation_started("render", 0)


@persistent
def _render_finished(_scene, *_args):
    with _gate.callback():
        _gate.evaluation_finished("render", 0)
    _ensure_timer()


@persistent
def _compositor_pre(scene, *_args):
    with _gate.callback():
        identity = scene.as_pointer()
        _gate.evaluation_started("compositor", identity,
                                 snapshot=_receipts.snapshot(identity))


def _compositor_finished(scene, successful):
    with _gate.callback():
        receipt = _gate.evaluation_finished("compositor", scene.as_pointer(),
                                            successful=successful)
        _receipts.completed(receipt)
    _ensure_timer()


@persistent
def _compositor_post(scene, *_args):
    _compositor_finished(scene, True)


@persistent
def _compositor_cancel(scene, *_args):
    _compositor_finished(scene, False)


@persistent
def _load_post(_filepath):
    global _receipts, _loading, _reset_pending
    _loading = True
    try:
        _gate.reset()
    except PublicationDeferred:
        _reset_pending = True
        _loading = False
        _ensure_timer()
        return
    _reset_pending = False
    _receipts = CompositorReceipts()
    _pools.clear()
    _pending.clear()
    for tree in _demo_trees():
        if tree.get(_VARIANT) == "versioned":
            try:
                _pool_for(tree)
            except Exception as error:
                _fail_closed(tree, error)
    _loading = False
    _enqueue_all()


@persistent
def _undo_post(*_args):
    _enqueue_all()


def _enqueue_all():
    for tree in _demo_trees():
        _enqueue(tree)


def _exposure_changed(settings, _context):
    tree = settings.id_data
    if tree is not None and _publication_trace is not None:
        _publication_trace.property_callback(
            tree, settings.exposure, _context, "started", loading=bool(_loading),
        )
    if _loading:
        if tree is not None and _publication_trace is not None:
            _publication_trace.property_callback(tree, settings.exposure, _context,
                                                 "skipped", reason="loading")
        return
    if tree is None or not tree.get(_TREE_MARKER):
        return
    _set_pending(tree, True)
    errors = _reconcile_tree(tree)
    if _publication_trace is not None:
        _publication_trace.property_callback(
            tree, settings.exposure, _context, "finished",
            pending=tree.as_pointer() in _pending, current=_tree_is_current(tree),
            error_count=len(errors),
        )


def _stop_publication_trace():
    global _publication_trace
    capture, _publication_trace = _publication_trace, None
    if capture is None:
        return None, None
    return capture.recorder.path, capture.close()


class PG_OT_start_drag_trace(bpy.types.Operator):
    bl_idname = "publication_compare.start_drag_trace"
    bl_label = "Publication Compare: Start Drag Trace"
    bl_description = "Record slider callbacks and helper publication stages"

    def execute(self, _context):
        global _publication_trace
        if _publication_trace is not None:
            path = str(_publication_trace.recorder.path)
            self.report({"INFO"}, "Publication Compare trace already active: " + path)
            return {"CANCELLED"}
        try:
            _publication_trace = Capture(sys.modules[__name__])
        except Exception as error:
            self.report({"ERROR"}, "Could not start Publication Compare trace: " + str(error))
            return {"CANCELLED"}
        message = "Publication Compare trace started: " + str(_publication_trace.recorder.path)
        print(message)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class PG_OT_stop_drag_trace(bpy.types.Operator):
    bl_idname = "publication_compare.stop_drag_trace"
    bl_label = "Publication Compare: Stop Drag Trace"
    bl_description = "Save the trace and report its path"

    def execute(self, _context):
        path, error = _stop_publication_trace()
        if path is None:
            self.report({"INFO"}, "No Publication Compare trace is active")
            return {"CANCELLED"}
        message = (("Publication Compare trace failed: " + error + "; ")
                   if error else "Publication Compare trace saved: ") + str(path)
        print(message)
        self.report({"ERROR"} if error else {"INFO"}, message)
        return {"CANCELLED"} if error else {"FINISHED"}


class PGPublicationSettings(bpy.types.PropertyGroup):
    exposure: FloatProperty(name="Exposure", default=0.0, min=-6.0, max=6.0,
                             precision=2, update=_exposure_changed)


class PGDemoShaderVersioned(bpy.types.ShaderNodeCustomGroup):
    bl_idname = VERSIONED_IDS[SHADER_TREE]
    bl_label = "Versioned Exposure"
    bl_width_default = 180

    def init(self, _context):
        self.node_tree = _new_group(SHADER_TREE, "versioned")


class PGDemoCompositorVersioned(bpy.types.CompositorNodeCustomGroup):
    bl_idname = VERSIONED_IDS[COMPOSITOR_TREE]
    bl_label = "Versioned Exposure"
    bl_width_default = 180

    def init(self, _context):
        self.node_tree = _new_group(COMPOSITOR_TREE, "versioned")


class PGDemoShaderOriginal(bpy.types.ShaderNodeCustomGroup):
    bl_idname = ORIGINAL_IDS[SHADER_TREE]
    bl_label = "Original Exposure"
    bl_width_default = 180

    def init(self, _context):
        self.node_tree = _new_group(SHADER_TREE, "original")


class PGDemoCompositorOriginal(bpy.types.CompositorNodeCustomGroup):
    bl_idname = ORIGINAL_IDS[COMPOSITOR_TREE]
    bl_label = "Original Exposure"
    bl_width_default = 180

    def init(self, _context):
        self.node_tree = _new_group(COMPOSITOR_TREE, "original")


class PGDemoShaderBanked(bpy.types.ShaderNodeCustomGroup):
    bl_idname = BANKED_IDS[SHADER_TREE]
    bl_label = "Banked Exposure"
    bl_width_default = 180

    def init(self, _context):
        self.node_tree = _new_group(SHADER_TREE, "banked")


class PGDemoCompositorBanked(bpy.types.CompositorNodeCustomGroup):
    bl_idname = BANKED_IDS[COMPOSITOR_TREE]
    bl_label = "Banked Exposure"
    bl_width_default = 180

    def init(self, _context):
        self.node_tree = _new_group(COMPOSITOR_TREE, "banked")


def _active_demo_node(context):
    space = getattr(context, "space_data", None)
    tree = getattr(space, "edit_tree", None)
    node = getattr(getattr(tree, "nodes", None), "active", None)
    return node if node is not None and node.bl_idname in NODE_IDS else None


class PG_PT_publication(bpy.types.Panel):
    bl_idname = "PG_PT_publication"
    bl_label = "Publication"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Publication"

    @classmethod
    def poll(cls, context):
        return _active_demo_node(context) is not None

    def draw(self, context):
        node = _active_demo_node(context)
        if node is None:
            return
        tree = node.node_tree
        self.layout.prop(tree.pg_publication, "exposure", slider=True)
        if tree.as_pointer() in _pending:
            self.layout.label(text="Updating", icon="TIME")
        error = tree.get("_pg_publication_error")
        if error:
            self.layout.label(text="Output is magenta", icon="ERROR")
            self.layout.label(text=error)


def _draw_trace_menu(self, _context):
    self.layout.separator()
    self.layout.operator(PG_OT_start_drag_trace.bl_idname)
    self.layout.operator(PG_OT_stop_drag_trace.bl_idname)


def _draw_menu(tree_type, node_type, label):
    def draw(self, context):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None)
        if tree is None or tree.bl_idname != tree_type:
            return
        self.layout.separator()
        operator = self.layout.operator("node.add_node", text=label, icon="TEXTURE")
        operator.type = node_type
        operator.use_transform = True
    return draw


def _menu_types():
    return (
        (bpy.types.NODE_MT_category_shader_color, SHADER_TREE),
        (bpy.types.NODE_MT_category_compositor_color, COMPOSITOR_TREE),
    )


def _classes():
    return (PGPublicationSettings, PGDemoShaderVersioned, PGDemoCompositorVersioned,
            PGDemoShaderOriginal, PGDemoCompositorOriginal, PGDemoShaderBanked,
            PGDemoCompositorBanked, PG_OT_start_drag_trace, PG_OT_stop_drag_trace,
            PG_PT_publication)


def _handlers():
    return (
        (bpy.app.handlers, "render_pre", _render_pre),
        (bpy.app.handlers, "render_init", _render_init),
        (bpy.app.handlers, "render_complete", _render_finished),
        (bpy.app.handlers, "render_cancel", _render_finished),
        (bpy.app.handlers, "composite_pre", _compositor_pre),
        (bpy.app.handlers, "composite_post", _compositor_post),
        (bpy.app.handlers, "composite_cancel", _compositor_cancel),
        (bpy.app.handlers, "load_post", _load_post),
        (bpy.app.handlers, "undo_post", _undo_post),
        (bpy.app.handlers, "redo_post", _undo_post),
    )


def register():
    global _gate, _receipts, _startup_reconcile
    _gate = PublicationGate(bpy)
    _receipts = CompositorReceipts()
    _startup_reconcile = True
    try:
        for cls in _classes():
            if not cls.is_registered:
                bpy.utils.register_class(cls)
            _registered_classes.append(cls)
        bpy.types.NodeTree.pg_publication = PointerProperty(type=PGPublicationSettings)
        for menu_type, tree_type in _menu_types():
            for variant, node_type in (("Versioned", VERSIONED_IDS[tree_type]),
                                       ("Original", ORIGINAL_IDS[tree_type]),
                                       ("Banked", BANKED_IDS[tree_type])):
                callback = _draw_menu(tree_type, node_type, variant + " Exposure")
                menu_type.append(callback)
                _registered_menus.append((menu_type, callback))
        bpy.types.TOPBAR_MT_help.append(_draw_trace_menu)
        _registered_menus.append((bpy.types.TOPBAR_MT_help, _draw_trace_menu))
        for collection, name, callback in _handlers():
            handler = getattr(collection, name, None)
            if handler is not None and callback not in handler:
                handler.append(callback)
                _registered_handlers.append((handler, callback))
        _ensure_timer()
    except Exception:
        unregister()
        raise


def unregister():
    try:
        path, error = _stop_publication_trace()
        if path is not None:
            print("Publication Compare trace closed:", path, error or "")
    except Exception as error:
        print("Publication Compare trace cleanup failed:", error)
    for handler, callback in reversed(tuple(_registered_handlers)):
        try:
            handler.remove(callback)
        except ValueError:
            pass
        _registered_handlers.remove((handler, callback))
    for menu_type, callback in reversed(tuple(_registered_menus)):
        try:
            menu_type.remove(callback)
        except ValueError:
            pass
        _registered_menus.remove((menu_type, callback))
    try:
        if bpy.app.timers.is_registered(_timer_tick):
            bpy.app.timers.unregister(_timer_tick)
    except (AttributeError, RuntimeError):
        pass
    if hasattr(bpy.types.NodeTree, "pg_publication"):
        del bpy.types.NodeTree.pg_publication
    for cls in reversed(tuple(_registered_classes)):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
        _registered_classes.remove(cls)
    _pending.clear()
    _pools.clear()
