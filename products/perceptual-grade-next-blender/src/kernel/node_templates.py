"""Runtime loading and binding of Buck-generated native node templates.

The Blender graph emitters live in the build-only template generator.  Runtime
instantiation appends one private group from the bundled library, binds its
mutable images, and validates the persisted template contract before the
caller publishes it.  No graph topology is emitted here.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from importlib import resources
import math
from pathlib import Path
from typing import Mapping, Optional

from .stage2_bindings import (
    PARAMETER_ACTIVE_BANK, PARAMETER_BANK_BINDINGS, PARAMETER_GENERATION,
    PARAMETER_IMAGE, PARAMETER_READER, PARAMETER_READER_BANK,
    PARAMETER_SAMPLE_BANK, PARAMETER_SAMPLE_ID, PARAMETER_SAMPLE_KIND,
    PARAMETER_SAMPLE_SELECTOR, PARAMETER_SELECTOR,
    TEMPLATE_KIND as TEMPLATE_KIND_KEY,
    TEMPLATE_SCHEMA as TEMPLATE_MARKER_SCHEMA,
    TEMPLATE_VARIANT as TEMPLATE_VARIANT_KEY,
)
from .stage2_parameters import (
    PARAMETER_CONTENT_SIGNATURE, PARAMETER_SCHEMA, PARAMETER_SHAPE,
    parameter_content_signature, parameter_image_matches, prepare_parameters,
)


SCHEMA = 1
MANIFEST_NAME = "node_templates.json"
BLEND_NAME = "node_templates.blend"
STACK_SHADER_NAME = "grade_stack.glsl"
TREE_TYPES = ("ShaderNodeTree", "CompositorNodeTree")
STACK_SIZES = (33, 65)

TEMPLATE_SCHEMA = TEMPLATE_MARKER_SCHEMA
TEMPLATE_KIND = TEMPLATE_KIND_KEY
TEMPLATE_VARIANT = TEMPLATE_VARIANT_KEY
TEMPLATE_SPACE = "_pg_template_space"
TEMPLATE_SIZE = "_pg_template_size"
TEMPLATE_SOURCE = "_pg_template_source"
TEMPLATE_CLONE = "_pg_template_clone"
TEMPLATE_SLOT = "_pg_template_slot"

SLOT_PARAMETER_0 = "parameter:0"
SLOT_PARAMETER_1 = "parameter:1"
SLOT_BOUNDARY = "boundary"
SLOT_LUT = "lut"
SLOT_LIVE = "live"
SLOT_BAKE = "bake"

STACK_KERNEL = "_perceptual_grade_stack_kernel"
STACK_LUT_SIGNATURE = "_perceptual_grade_lut_signature"
STACK_IMAGE = "_perceptual_grade_stack_image"
KERNEL_QUALITY = "_perceptual_grade_quality"
KERNEL_TREE_TYPE = "_perceptual_grade_tree_type"
KERNEL_WORKING_SPACE = "_perceptual_grade_working_space"
BAKE_WRAPPER = "_pg_next_bake_wrapper"
BAKE_LIVE = "_pg_next_bake_live"
BAKE_READER = "_pg_next_bake_reader"


class TemplateAssetError(RuntimeError):
    """A missing, stale, or structurally incompatible bundled asset."""


@dataclass(frozen=True)
class TemplateVariant:
    kind: str
    tree_type: str
    space: Optional[str] = None
    size: Optional[int] = None

    @property
    def key(self):
        if self.kind == "wrapper":
            return f"wrapper:{self.tree_type}"
        if self.kind == "grade" and self.space:
            return f"grade:{self.tree_type}:{self.space}"
        if self.kind == "stack" and self.space and self.size is not None:
            return f"stack:{self.tree_type}:{self.space}:{self.size}"
        raise ValueError(f"Incomplete template variant: {self!r}")


@dataclass(frozen=True)
class TemplateRecord:
    key: str
    name: str
    kind: str
    tree_type: str
    space: Optional[str]
    size: Optional[int]
    node_count: int
    link_count: int
    structure_sha256: str
    slots: Mapping[str, tuple[str, ...]]


@dataclass
class TemplateInstance:
    """A private appended tree and the images owned by that tree."""

    tree: object
    images: tuple = ()
    borrowed_images: tuple = ()
    retire: object = None
    helper_groups: tuple = ()

    def dispose(self, unlink=True):
        """Retire the candidate IDs after failed publication or test teardown."""
        _retire("group", self.tree, self.retire, unlink=unlink)
        for group in self.helper_groups:
            _retire("group", group, self.retire)
        borrowed = tuple(self.borrowed_images)
        for image in self.images:
            if image not in borrowed:
                _retire("image", image, self.retire)


def _retire(kind, resource, callback=None, *, unlink=False):
    if resource is None:
        return
    try:
        if not resource.as_pointer():
            return
        if callback is not None:
            callback(kind, resource)
            return
        import bpy
        resource.use_fake_user = False
        collection = bpy.data.images if kind == "image" else bpy.data.node_groups
        if unlink or resource.users == 0:
            collection.remove(resource, do_unlink=unlink)
    except ReferenceError:
        return


def _resource(package, name):
    try:
        return resources.files(package).joinpath(name)
    except (AttributeError, ModuleNotFoundError, TypeError) as error:
        raise TemplateAssetError(f"Template resource package is unavailable: {package}") from error


def _read_bytes(package, name):
    try:
        return _resource(package, name).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise TemplateAssetError(f"Bundled template resource is missing: {name}") from error


def _read_json(package, name):
    try:
        return json.loads(_read_bytes(package, name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TemplateAssetError(f"Bundled template manifest is invalid: {name}") from error


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _finite(value, label):
    result = float(value)
    if not math.isfinite(result):
        raise TemplateAssetError(f"Template context is not finite: {label}")
    return result


def _plain(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _plain(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_plain(item) for item in value)
    try:
        return tuple(_plain(item) for item in value)
    except TypeError:
        return str(value)


def _socket_value(socket):
    try:
        return _plain(socket.default_value)
    except (AttributeError, TypeError, ValueError):
        return None


def structure_digest(tree):
    """Digest topology and semantic node settings, excluding bank selection."""
    try:
        interface = tuple(
            (item.item_type, item.in_out, item.name, item.socket_type,
             _socket_value(item))
            for item in tree.interface.items_tree
        )
        nodes = []
        for node in tree.nodes:
            properties = {}
            for name in (
                "operation", "blend_type", "data_type", "factor_mode",
                "clamp_factor", "clamp", "mode", "interpolation",
                "extension", "projection", "is_active_output", "use_clamp",
                "use_alpha", "mute",
            ):
                if hasattr(node, name):
                    properties[name] = _plain(getattr(node, name))
            mutable_selector = bool(node.get(PARAMETER_SELECTOR))
            live = node.get(TEMPLATE_SLOT) == SLOT_LIVE
            nodes.append({
                "name": node.name,
                "type": node.bl_idname,
                "label": node.label,
                "properties": properties,
                "inputs": tuple(
                    (None if mutable_selector or live else _socket_value(socket), socket.name)
                    for socket in node.inputs
                ),
                "outputs": tuple((None if mutable_selector or live else _socket_value(socket), socket.name)
                                 for socket in node.outputs),
                "slot": node.get(TEMPLATE_SLOT),
            })
        links = tuple(sorted(
            (link.from_node.name, tuple(link.from_node.outputs).index(link.from_socket),
             link.to_node.name, tuple(link.to_node.inputs).index(link.to_socket))
            for link in tree.links
        ))
        payload = json.dumps(
            {"tree_type": tree.bl_idname, "interface": interface,
             "nodes": tuple(nodes), "links": links},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
        raise TemplateAssetError("Could not inspect template structure") from error
    return _digest(payload)


def _slots(value):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TemplateAssetError("Template slots must be a mapping")
    result = {}
    for role, names in value.items():
        if isinstance(names, str):
            names = (names,)
        if not isinstance(names, (tuple, list)) or not all(isinstance(name, str) for name in names):
            raise TemplateAssetError(f"Invalid template slot {role!r}")
        result[str(role)] = tuple(names)
    return result


def _record(key, raw):
    if not isinstance(raw, Mapping):
        raise TemplateAssetError(f"Invalid template record: {key}")
    required = ("name", "kind", "tree_type", "node_count", "link_count", "structure_sha256")
    if any(name not in raw for name in required):
        raise TemplateAssetError(f"Incomplete template record: {key}")
    kind, tree_type = str(raw["kind"]), str(raw["tree_type"])
    if kind not in {"grade", "stack", "wrapper"} or tree_type not in TREE_TYPES:
        raise TemplateAssetError(f"Unsupported template identity: {key}")
    space = raw.get("space")
    size = raw.get("size")
    if space is not None and not isinstance(space, str):
        raise TemplateAssetError(f"Invalid template space: {key}")
    if size is not None and (type(size) is not int or size not in STACK_SIZES):
        raise TemplateAssetError(f"Invalid template size: {key}")
    node_count, link_count = raw["node_count"], raw["link_count"]
    digest = raw["structure_sha256"]
    if (type(node_count) is not int or node_count < 1
            or type(link_count) is not int or link_count < 0
            or not isinstance(digest, str) or len(digest) != 64):
        raise TemplateAssetError(f"Invalid template structure receipt: {key}")
    return TemplateRecord(
        key=key, name=str(raw["name"]), kind=kind, tree_type=tree_type,
        space=space, size=size, node_count=node_count, link_count=link_count,
        structure_sha256=digest, slots=_slots(raw.get("slots")),
    )


def load_manifest(package=None, name=MANIFEST_NAME):
    """Read the generated manifest without importing Blender."""
    package = __package__ if package is None else package
    manifest = _read_json(package, name)
    if not isinstance(manifest, Mapping) or manifest.get("schema") != SCHEMA:
        raise TemplateAssetError(f"Unsupported template manifest schema: {name}")
    for field in ("blend_sha256", "shader_sha256", "shader_context", "variants"):
        if field not in manifest:
            raise TemplateAssetError(f"Template manifest is missing {field}")
    if (not isinstance(manifest["blend_sha256"], str)
            or len(manifest["blend_sha256"]) != 64
            or not isinstance(manifest["shader_sha256"], str)
            or len(manifest["shader_sha256"]) != 64
            or not isinstance(manifest["variants"], Mapping)):
        raise TemplateAssetError("Template manifest has invalid receipts")
    records = {str(key): _record(str(key), value)
               for key, value in manifest["variants"].items()}
    if not records:
        raise TemplateAssetError("Template manifest has no variants")
    for key, record in records.items():
        try:
            expected = TemplateVariant(record.kind, record.tree_type, record.space, record.size).key
        except ValueError as error:
            raise TemplateAssetError(f"Template identity is incomplete: {key}") from error
        if key != expected:
            raise TemplateAssetError(f"Template key does not match record: {key}")
    return manifest, records


def _variant_record(records, variant):
    try:
        record = records[variant.key]
    except KeyError as error:
        raise TemplateAssetError(f"No bundled template for {variant.key}") from error
    if (record.kind, record.tree_type, record.space, record.size) != (
            variant.kind, variant.tree_type, variant.space, variant.size):
        raise TemplateAssetError(f"Template context mismatch for {variant.key}")
    return record


def _check_context(manifest, prepared):
    context = manifest.get("shader_context")
    if not isinstance(context, Mapping) or set(context) != {"fl", "aw", "gamma"}:
        raise TemplateAssetError("Generated appearance context is incomplete")
    for field in ("fl", "aw", "gamma"):
        if _finite(context[field], field) != _finite(getattr(prepared, field), field):
            raise TemplateAssetError(f"Generated appearance context mismatch: {field}")


def _validate_tree(tree, record, *, source=False):
    try:
        if tree is None or tree.bl_idname != record.tree_type:
            raise TemplateAssetError(f"Template {record.key} has the wrong tree type")
        if tree.get(TEMPLATE_SCHEMA) != TEMPLATE_MARKER_SCHEMA:
            raise TemplateAssetError(f"Template {record.key} has the wrong schema marker")
        if tree.get(TEMPLATE_VARIANT) != record.key or tree.get(TEMPLATE_KIND) != record.kind:
            raise TemplateAssetError(f"Template {record.key} has the wrong identity marker")
        if record.space is not None and tree.get(TEMPLATE_SPACE) != record.space:
            raise TemplateAssetError(f"Template {record.key} has the wrong space marker")
        if record.size is not None and tree.get(TEMPLATE_SIZE) != record.size:
            raise TemplateAssetError(f"Template {record.key} has the wrong size marker")
        if len(tree.nodes) != record.node_count or len(tree.links) != record.link_count:
            raise TemplateAssetError(f"Template {record.key} topology changed")
        for role, names in record.slots.items():
            for name in names:
                node = tree.nodes.get(name)
                if node is None or node.get(TEMPLATE_SLOT) != role:
                    raise TemplateAssetError(f"Template {record.key} lost slot {name}")
        if structure_digest(tree) != record.structure_sha256:
            raise TemplateAssetError(f"Template {record.key} structure receipt changed")
        if source and tree.get(TEMPLATE_SOURCE) is not True:
            raise TemplateAssetError(f"Template {record.key} is not a source asset")
    except TemplateAssetError:
        raise
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
        raise TemplateAssetError(f"Could not validate template {record.key}") from error


class TemplateStore:
    """Stateless native append store; manifest bytes are the only cache."""

    def __init__(self, package=None, *, manifest_name=MANIFEST_NAME,
                 blend_name=BLEND_NAME):
        self.package = __package__ if package is None else package
        self.manifest_name = manifest_name
        self.blend_name = blend_name
        self._manifest = None
        self._records = None

    def _contract(self):
        if self._records is None:
            self._manifest, self._records = load_manifest(self.package, self.manifest_name)
        return self._manifest, self._records

    def record(self, variant):
        return _variant_record(self._contract()[1], variant)

    @contextmanager
    def _blend_path(self):
        try:
            with resources.as_file(_resource(self.package, self.blend_name)) as path:
                yield Path(path)
        except (FileNotFoundError, OSError) as error:
            raise TemplateAssetError(f"Bundled template asset is missing: {self.blend_name}") from error

    def _verify_assets(self):
        manifest, _ = self._contract()
        blend_digest = _digest(_read_bytes(self.package, self.blend_name))
        shader_digest = _digest(_read_bytes(self.package, STACK_SHADER_NAME))
        if blend_digest != manifest["blend_sha256"]:
            raise TemplateAssetError("Node-template blend digest mismatch")
        if shader_digest != manifest["shader_sha256"]:
            raise TemplateAssetError("Generated Stack shader digest mismatch")

    def append(self, variant, *, retire=None):
        """Append exactly one private group and validate the returned ID."""
        import bpy

        record = self.record(variant)
        self._verify_assets()
        before_groups = {item.as_pointer() for item in bpy.data.node_groups}
        before_images = {item.as_pointer() for item in bpy.data.images}
        loaded = None
        try:
            with self._blend_path() as path:
                with bpy.data.libraries.load(str(path), link=False) as (data_from, data_to):
                    if record.name not in data_from.node_groups:
                        raise TemplateAssetError(f"Template group is absent: {record.name}")
                    data_to.node_groups = [record.name]
                loaded = data_to.node_groups[0]
            if loaded is None:
                raise TemplateAssetError(f"Template group could not be appended: {record.key}")
            if loaded.as_pointer() in before_groups:
                raise TemplateAssetError("Template append returned an existing datablock")
            _validate_tree(loaded, record, source=True)
            groups = tuple(item for item in bpy.data.node_groups
                           if item.as_pointer() not in before_groups and item != loaded)
            images = tuple(item for item in bpy.data.images
                           if item.as_pointer() not in before_images)
            for item in (loaded, *groups, *images):
                item.use_fake_user = False
            loaded[TEMPLATE_SOURCE] = False
            loaded[TEMPLATE_CLONE] = True
            return TemplateInstance(loaded, images, retire=retire, helper_groups=groups)
        except TemplateAssetError:
            self._cleanup_new_ids(before_groups, before_images, root=loaded, retire=retire)
            raise
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
            self._cleanup_new_ids(before_groups, before_images, root=loaded, retire=retire)
            raise TemplateAssetError(f"Could not append template {record.key}") from error

    @staticmethod
    def _cleanup_new_ids(before_groups, before_images, *, root=None, retire=None):
        import bpy
        groups = tuple(tree for tree in bpy.data.node_groups
                       if tree.as_pointer() not in before_groups)
        images = tuple(image for image in bpy.data.images
                       if image.as_pointer() not in before_images)
        for item in (*groups, *images):
            item.use_fake_user = False
        # Policy retirement deliberately refuses in-use resources.  Release
        # the appended root before its live-interface stub, regardless of the
        # alphabetical order of Blender's datablock collection.
        ordered = sorted(groups, key=lambda tree: (tree != root, tree.users))
        for tree in ordered:
            _retire("group", tree, retire, unlink=True)
        for image in images:
            _retire("image", image, retire)

    def clear(self):
        self._manifest = self._records = None


_STORE = TemplateStore()


def _bind(tree, record, bindings):
    for role, image in bindings.items():
        names = record.slots.get(role)
        if not names:
            raise TemplateAssetError(f"Template has no slot {role}")
        for name in names:
            node = tree.nodes.get(name)
            if node is None or not hasattr(node, "image"):
                raise TemplateAssetError(f"Template slot is not an image reader: {name}")
            node.image = image


def _make_image(name, pixels, marker=None, *, retire=None):
    import bpy
    import numpy as np

    data = np.asarray(pixels, dtype=np.float32)
    if data.ndim != 3 or data.shape[-1] != 4:
        raise TemplateAssetError(f"Invalid RGBA image shape for {name}")
    height, width, _ = data.shape
    image = bpy.data.images.new(name, width=width, height=height, alpha=True, float_buffer=True)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        image.file_format = "OPEN_EXR"
        image.pixels.foreach_set(data.ravel())
        image.update()
        image.pack()
        if image.packed_file is None or image.is_dirty:
            raise TemplateAssetError(f"Could not pack template image: {name}")
        for key, value in (marker or {}).items():
            image[key] = value
        return image
    except BaseException:
        _retire("image", image, retire)
        raise


def _parameter_banks(prepared, supplied, *, retire=None):
    parameters = prepared.parameters or prepare_parameters(prepared)
    signature = parameter_content_signature(parameters.pixels)
    if supplied is not None:
        # A publication transaction can bind the old active bank and a newly
        # staged candidate before its selector operation is authorized.  Both
        # supplied banks must be internally valid, but need not contain the
        # same settings as `prepared` or as each other.
        banks = tuple(supplied)
        if len(banks) != 2 or banks[0] == banks[1]:
            raise TemplateAssetError("Grade templates require two distinct parameter banks")
        for image in banks:
            try:
                valid = (
                    image.library is None
                    and image.source in {"FILE", "GENERATED"}
                    and image.is_float
                    and image.packed_file is not None
                    and not image.is_dirty
                    and image.colorspace_settings.name == "Non-Color"
                    and image.alpha_mode == "CHANNEL_PACKED"
                    and not image.use_half_precision
                    and image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA
                    and tuple(image.size) == (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])
                    and parameter_image_matches(image)
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                valid = False
            if not valid:
                raise TemplateAssetError("Grade template parameter bank is invalid")
        return banks, banks
    banks = []
    try:
        for bank in (0, 1):
            banks.append(_make_image(
                f"Perceptual Grade parameters bank {bank}", parameters.pixels,
                marker={PARAMETER_IMAGE: PARAMETER_SCHEMA,
                        PARAMETER_CONTENT_SIGNATURE: signature,
                        "_perceptual_grade_image": True},
                retire=retire,
            ))
        return tuple(banks), ()
    except BaseException:
        for image in banks:
            _retire("image", image, retire)
        raise


def instantiate_grade(prepared, tree_type, parameter_images=None, active_bank=0, generation=0,
                      *, store=None, retire=None):
    if tree_type not in TREE_TYPES or not isinstance(getattr(prepared, "space", None), str):
        raise TemplateAssetError("Grade template context is invalid")
    if active_bank not in (0, 1) or type(generation) is not int or generation < 0:
        raise TemplateAssetError("Grade publication metadata is invalid")
    store = _STORE if store is None else store
    if (getattr(prepared, "table", None) is None
            or getattr(prepared, "boundary", None) is None
            or getattr(prepared.color, "active", True)
            or prepared.tone.reference != 203.):
        raise TemplateAssetError("Grade templates require complete neutral-Color Stage 2 preparation")
    prepare_parameters(prepared)
    _check_context(store._contract()[0], prepared)
    _check_context(store._contract()[0], prepared.boundary)
    variant = TemplateVariant("grade", tree_type, prepared.space)
    record = store.record(variant)
    appended = store.append(variant, retire=retire)
    tree = appended.tree
    images, borrowed = list(appended.images), []
    try:
        banks, borrowed_banks = _parameter_banks(prepared, parameter_images, retire=retire)
        images.extend(banks)
        borrowed.extend(borrowed_banks)
        boundary_nodes = record.slots.get(SLOT_BOUNDARY, ())
        source = next((tree.nodes[name].image for name in boundary_nodes
                       if tree.nodes.get(name) is not None
                       and getattr(tree.nodes[name], "image", None) is not None), None)
        if source is None:
            raise TemplateAssetError(f"Grade template has no boundary image: {variant.key}")
        # The freshly appended boundary image is already private to this tree.
        boundary = source
        boundary["_perceptual_grade_image"] = True
        _bind(tree, record, {
            SLOT_PARAMETER_0: banks[0], SLOT_PARAMETER_1: banks[1],
            SLOT_BOUNDARY: boundary,
        })
        for bank, image in enumerate(banks):
            tree[PARAMETER_BANK_BINDINGS[bank]] = image
            for node in tree.nodes:
                if node.get(TEMPLATE_SLOT) == f"parameter:{bank}":
                    node[PARAMETER_READER] = True
                    node[PARAMETER_READER_BANK] = bank
        tree[PARAMETER_ACTIVE_BANK] = active_bank
        tree[PARAMETER_GENERATION] = generation
        selector = next((node for node in tree.nodes if node.get(PARAMETER_SELECTOR)), None)
        if selector is None:
            raise TemplateAssetError(f"Grade template has no parameter selector: {variant.key}")
        if tree_type == "ShaderNodeTree":
            selector.outputs["Value"].default_value = float(active_bank)
        else:
            selector.inputs[0].default_value = float(active_bank)
            selector.inputs[1].default_value = 0.0
        _validate_tree(tree, record)
        appended.images = tuple(images)
        appended.borrowed_images = tuple(borrowed)
        return appended
    except BaseException:
        appended.images = tuple(images)
        appended.borrowed_images = tuple(borrowed)
        appended.dispose()
        raise


def instantiate_stack(prepared, tree_type, quality=None, *, store=None, retire=None):
    if tree_type not in TREE_TYPES:
        raise TemplateAssetError(f"Unsupported Stack tree type: {tree_type}")
    cube, space = getattr(prepared, "cube", None), getattr(prepared, "space", None)
    if cube is None or cube.size not in STACK_SIZES or not isinstance(space, str):
        raise TemplateAssetError("Stack template context is invalid")
    from .lut import ATLAS_WIDTH, atlas_height, basis
    import numpy as np
    expected_quality = "preview" if cube.size == 33 else "full"
    if quality is not None and quality != expected_quality:
        raise TemplateAssetError("Stack quality does not match its cube size")
    to_lut, from_lut = basis(space)
    if (cube.space != space or not np.array_equal(cube.to_lut, to_lut)
            or not np.array_equal(cube.from_lut, from_lut)
            or not isinstance(cube.signature, str) or not cube.signature):
        raise TemplateAssetError("Stack template requires its canonical working-space basis")
    store = _STORE if store is None else store
    variant = TemplateVariant("stack", tree_type, space, int(cube.size))
    record = store.record(variant)
    appended = store.append(variant, retire=retire)
    tree = appended.tree
    images = list(appended.images)
    try:
        pixels = cube.compositor_pixels() if tree_type == "CompositorNodeTree" else cube.shader_pixels()
        if (pixels.shape != (atlas_height(cube.size), ATLAS_WIDTH, 4)
                or not np.isfinite(pixels).all()):
            raise TemplateAssetError("Stack LUT atlas does not match its template dimensions")
        image = _make_image(
            f"Perceptual Grade Stack LUT {cube.size}", pixels,
            marker={STACK_IMAGE: cube.signature, "_perceptual_grade_image": True,
                    STACK_LUT_SIGNATURE: cube.signature}, retire=retire,
        )
        images.append(image)
        _bind(tree, record, {SLOT_LUT: image})
        tree[STACK_KERNEL] = True
        tree[KERNEL_TREE_TYPE] = tree_type
        tree[KERNEL_WORKING_SPACE] = space
        tree[STACK_LUT_SIGNATURE] = cube.signature
        tree[KERNEL_QUALITY] = expected_quality
        _validate_tree(tree, record)
        appended.images = tuple(images)
        return appended
    except BaseException:
        appended.images = tuple(images)
        appended.dispose()
        raise


def instantiate_wrapper(tree_type, kernel, *, store=None, retire=None):
    if tree_type not in TREE_TYPES:
        raise TemplateAssetError(f"Unsupported wrapper tree type: {tree_type}")
    store = _STORE if store is None else store
    variant = TemplateVariant("wrapper", tree_type)
    record = store.record(variant)
    appended = store.append(variant, retire=retire)
    tree = appended.tree
    try:
        live_names = record.slots.get(SLOT_LIVE, ())
        if len(live_names) != 1:
            raise TemplateAssetError(f"Wrapper live slot is not unique: {variant.key}")
        live = tree.nodes.get(live_names[0])
        links = tuple((link.from_node, link.from_socket.name, link.to_node, link.to_socket.name)
                      for link in tree.links if link.from_node == live or link.to_node == live)
        live.node_tree = kernel
        for origin, output, target, input_ in links:
            source, destination = origin.outputs[output], target.inputs[input_]
            if not any(link.from_socket == source and link.to_socket == destination
                       for link in tree.links):
                tree.links.new(source, destination)
        tree[BAKE_WRAPPER] = 1
        _validate_tree(tree, record)
        for helper in appended.helper_groups:
            if helper != kernel:
                _retire("group", helper, retire)
        appended.helper_groups = ()
        return tree
    except BaseException:
        appended.dispose()
        raise


def validate_stack_instance(tree, *, store=None):
    """Check a saved Stack instance's topology and complete atlas binding."""
    from .lut import ATLAS_WIDTH, atlas_height

    try:
        store = _STORE if store is None else store
        variant = TemplateVariant(
            "stack", tree.bl_idname, tree.get(TEMPLATE_SPACE), tree.get(TEMPLATE_SIZE),
        )
        record = store.record(variant)
        _validate_tree(tree, record)
        if (tree.get(KERNEL_WORKING_SPACE) != variant.space
                or tree.get(KERNEL_QUALITY) != ("preview" if variant.size == 33 else "full")):
            return False
        readers = tuple(tree.nodes[name] for name in record.slots.get(SLOT_LUT, ()))
        if not readers:
            return False
        image = readers[0].image
        if (image is None or any(node.image != image for node in readers)
                or image.library is not None or image.packed_file is None
                or image.is_dirty or not image.is_float
                or image.colorspace_settings.name != "Non-Color"
                or image.alpha_mode != "CHANNEL_PACKED"
                or image.use_half_precision
                or tuple(image.size) != (ATLAS_WIDTH, atlas_height(variant.size))
                or image.get(STACK_LUT_SIGNATURE) != tree.get(STACK_LUT_SIGNATURE)
                or not tree.get(STACK_LUT_SIGNATURE)):
            return False
        return all(getattr(node, "image", None) in (None, image)
                   for node in tree.nodes)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def shader_source(boundary=None, *, package=None, name=STACK_SHADER_NAME):
    package = __package__ if package is None else package
    manifest, _ = load_manifest(package)
    actual = _digest(_read_bytes(package, name))
    if actual != manifest["shader_sha256"]:
        raise TemplateAssetError("Generated Stack shader digest mismatch")
    context = manifest.get("shader_context", {})
    if not isinstance(context, Mapping):
        raise TemplateAssetError("Generated Stack shader context is invalid")
    if boundary is not None:
        _check_context(manifest, boundary)
    try:
        return _read_bytes(package, name).decode("utf-8")
    except UnicodeDecodeError as error:
        raise TemplateAssetError(f"Generated Stack shader is not UTF-8: {name}") from error


def reset_cache():
    _STORE.clear()


__all__ = (
    "BLEND_NAME", "MANIFEST_NAME", "STACK_SHADER_NAME", "SCHEMA",
    "TemplateAssetError", "TemplateInstance", "TemplateRecord", "TemplateStore",
    "TemplateVariant", "instantiate_grade", "instantiate_stack",
    "instantiate_wrapper", "load_manifest", "reset_cache", "shader_source",
    "structure_digest", "validate_stack_instance",
)
