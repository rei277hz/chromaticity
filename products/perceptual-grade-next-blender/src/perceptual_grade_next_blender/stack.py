"""Reference-generated Stack preparation and persistent readiness metadata.

The Stack adapter owns preparation identity and host-side LUT artifacts.  It
does not install a separate analytic pixel grader into Blender.  Only a
completed 65^3 ``StackLUT`` is exposed as the Stack Bake evaluator; the 33^3
preview is display-only.
"""

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

import numpy as np


STACK_METADATA_SCHEMA = 1
PREVIEW_EVALUATOR = "stack_preview_33_lut"
FINAL_EVALUATOR = "stack_65_lut"


def _core_stack_types():
    from ..perceptual_grade_next_core import StackModel, StackSettings
    from ..perceptual_grade_next_core.model.lut import (
        FinalLattice,
        PreviewLattice,
        StackLUT,
        make_recipe,
        refine_final,
        sample_preview,
    )
    return (StackModel, StackSettings, FinalLattice, PreviewLattice, StackLUT,
            make_recipe, refine_final, sample_preview)


def _payload_digest(values):
    array = np.asarray(values, dtype=np.float32)
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _image_payload_digest(image, size):
    pixels = np.empty(size**3 * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return _payload_digest(pixels.reshape(-1, 4)[:, :3])


def _settings_key(settings):
    return hashlib.sha256(repr(settings).encode("utf8")).hexdigest()


def _settings_data(settings):
    """Return the current authored recipe in a JSON-safe, portable shape."""
    def convert(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [convert(item) for item in value]
        return value

    return convert(asdict(settings))


def _settings_from_data(data):
    from ..perceptual_grade_next_core import (
        ColorSettings, Direction, GradeSettings, LinearSettings,
        StackEntry, StackSettings, ToneSettings, WebSettings,
    )

    entries = []
    for item in data["entries"]:
        grade = item["settings"]
        color = dict(grade["color"])
        color["web"] = WebSettings(**color.get("web", {}))
        settings = GradeSettings(
            linear=LinearSettings(**grade["linear"]),
            tone=ToneSettings(**grade["tone"]),
            color=ColorSettings(**color),
            grading_white=grade["grading_white"],
            working_space=grade["working_space"],
        )
        entries.append(StackEntry(settings=settings, direction=Direction(item["direction"])))
    return StackSettings(tuple(entries))


def _recipe_for(settings, model_key=None):
    StackModel, _, _, _, _, make_recipe, *_ = _core_stack_types()
    model = StackModel(settings)
    input_matrix, output_matrix = model.lut_endpoint_matrices
    return make_recipe(
        working_space=(settings.entries[0].settings.working_space
                       if settings.entries else "ACEScg"),
        directions=tuple(entry.direction for entry in settings.entries),
        input_matrix=input_matrix,
        output_matrix=output_matrix,
        model_key=_settings_key(settings) if model_key is None else model_key,
    )


def _settings_property(tree):
    raw = tree.get("perceptual_grade_next_stack_settings", "")
    if not raw:
        raise RuntimeError("Persistent Stack has no authored settings to reconstruct")
    try:
        return _settings_from_data(json.loads(raw))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Persistent Stack authored settings are invalid") from error


def _find_resource_node(tree, role):
    node_name = tree.get(f"perceptual_grade_next_stack_{role}_binding", "")
    node = tree.nodes.get(node_name) if node_name else None
    if (node is not None
            and node.get("perceptual_grade_next_stack_binding") == role
            and getattr(node, "image", None) is not None):
        return node
    # A real node reference is the durable owner. The name metadata is only a
    # lookup hint, so recover after Blender renames the hidden binding node.
    for node in tree.nodes:
        if (node.get("perceptual_grade_next_stack_binding") == role
                and getattr(node, "image", None) is not None):
            return node
    return None


def _create_resource_node(tree, role, image):
    node_type = ("ShaderNodeTexImage" if tree.bl_idname == "ShaderNodeTree"
                 else "CompositorNodeImage")
    node = tree.nodes.new(node_type)
    node.name = f"PGN Stack {role.title()} Resource"
    node.label = f"Stack {role.title()} resource (internal)"
    node.hide = True
    node.mute = True
    node["perceptual_grade_next_stack_binding"] = role
    node.image = image
    return node


def _load_lattice(image, size):
    rgba = np.empty(size**3 * 4, dtype=np.float32)
    image.pixels.foreach_get(rgba)
    return rgba.reshape(-1, 4)[:, :3].reshape(size, size, size, 3).copy()


@dataclass(frozen=True)
class StackPreparation:
    """Immutable Stack artifacts for one authored recipe revision."""

    settings: object
    recipe: object
    preview: object
    final: object = None

    @property
    def preview_ready(self):
        return self.preview is not None

    @property
    def final_ready(self):
        return self.final is not None and self.final.final_ready

    @property
    def preview_digest(self):
        return None if self.preview is None else _payload_digest(self.preview.values)

    @property
    def final_digest(self):
        return None if not self.final_ready else _payload_digest(self.final.values)

    @property
    def evaluator_kind(self):
        return FINAL_EVALUATOR if self.final_ready else None

    @property
    def bake_lut(self):
        """Return the accepted LUT evaluator; preview cannot be a Bake source."""
        if not self.final_ready:
            raise RuntimeError("Stack Bake requires an accepted 65^3 final LUT")
        _, _, _, _, StackLUT, *_ = _core_stack_types()
        return StackLUT(self.final)

    def metadata(self):
        """Return saveable identity/readiness metadata, without pixel payloads."""
        return {
            "schema": STACK_METADATA_SCHEMA,
            "recipe_digest": self.recipe.digest,
            "preview_size": 33,
            "preview_ready": self.preview_ready,
            "preview_digest": self.preview_digest,
            "final_size": 65 if self.final_ready else 0,
            "final_ready": self.final_ready,
            "final_digest": self.final_digest,
            "evaluator": self.evaluator_kind,
            "preview_is_bake_source": False,
        }


def prepare_stack(settings=None, *, block_size=4096, checkpoint=None):
    """Generate the reference Stack's 33^3 interactive preview."""
    StackModel, StackSettings, _, _, _, make_recipe, _, sample_preview = _core_stack_types()
    settings = StackSettings() if settings is None else settings
    if not isinstance(settings, StackSettings):
        raise TypeError("settings must be a Next core StackSettings value")
    recipe = _recipe_for(settings)
    model = StackModel(settings)
    preview = sample_preview(
        model.apply_lut_core_ap1,
        recipe,
        block_size=block_size,
        checkpoint=checkpoint,
    )
    return StackPreparation(settings, recipe, preview)


def refine_stack(preparation, *, block_size=4096, checkpoint=None):
    """Complete the 65^3 final LUT, evaluating only non-preview vertices."""
    StackModel, StackSettings, _, PreviewLattice, _, _, refine_final, _ = _core_stack_types()
    if not isinstance(preparation, StackPreparation):
        raise TypeError("refinement requires a StackPreparation")
    if not isinstance(preparation.settings, StackSettings):
        raise TypeError("preparation settings must be a Next core StackSettings value")
    model = StackModel(preparation.settings)
    final = refine_final(
        preparation.preview,
        model.apply_lut_core_ap1,
        preparation.recipe,
        block_size=block_size,
        checkpoint=checkpoint,
    )
    return StackPreparation(preparation.settings, preparation.recipe, preparation.preview, final)


def reopen_stack(tree, *, rebuild=True, block_size=4096, checkpoint=None):
    """Reconstruct Stack authority from packed data in the opened .blend."""
    settings = _settings_property(tree)
    recipe = _recipe_for(settings)
    try:
        import bpy

        metadata = json.loads(tree.get("perceptual_grade_next_stack_metadata", "{}"))
        if (metadata.get("schema") != STACK_METADATA_SCHEMA
                or metadata.get("recipe_digest") != recipe.digest):
            raise RuntimeError("Persistent Stack manifest is stale")
        preview = bpy.data.images.get(
            tree.get("perceptual_grade_next_stack_preview_resource", "")
        )
        if preview is None:
            raise RuntimeError("Persistent Stack preview image is missing")
        _, _, FinalLattice, PreviewLattice, _, *_ = _core_stack_types()
        preview_lattice = PreviewLattice(_load_lattice(preview, 33), recipe)
        if _payload_digest(preview_lattice.values) != metadata.get("preview_digest"):
            raise RuntimeError("Persistent Stack preview payload digest is invalid")
        preparation = StackPreparation(settings, recipe, preview_lattice)
        if metadata.get("final_ready"):
            final = bpy.data.images.get(
                tree.get("perceptual_grade_next_stack_final_resource", "")
            )
            if final is None:
                raise RuntimeError("Persistent Stack final image is missing")
            final_lattice = FinalLattice(_load_lattice(final, 65), recipe, preview_lattice)
            if _payload_digest(final_lattice.values) != metadata.get("final_digest"):
                raise RuntimeError("Persistent Stack final payload digest is invalid")
            preparation = StackPreparation(settings, recipe, preview_lattice, final_lattice)
        if metadata != preparation.metadata():
            raise RuntimeError("Persistent Stack readiness differs from its packed data")
        owner = StackDatablock.__new__(StackDatablock)
        owner.tree = tree
        owner.preparation = preparation
        owner.validate_persistent()
        return owner
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        if not rebuild:
            raise
    preparation = prepare_stack(settings, block_size=block_size, checkpoint=checkpoint)
    if bool(tree.get("perceptual_grade_next_stack_final_ready", False)):
        preparation = refine_stack(preparation, block_size=block_size, checkpoint=checkpoint)
    return StackDatablock(tree, preparation)


class StackDatablock:
    """Blender-owned packed metadata for distinct preview/final artifacts."""

    def __init__(self, tree, preparation):
        self.tree = tree
        self.preparation = None
        self.update(preparation)

    @staticmethod
    def _find_image(role, recipe_digest, payload_digest):
        import bpy

        size = 33 if role == "preview" else 65
        for image in bpy.data.images:
            if (image.get("perceptual_grade_next_stack_role") == role
                    and image.get("perceptual_grade_next_stack_recipe") == recipe_digest
                    and image.get("perceptual_grade_next_stack_digest") == payload_digest
                    and tuple(image.size) == (size * size, size)
                    and image.packed_file
                    and not image.use_half_precision):
                try:
                    if _image_payload_digest(image, size) == payload_digest:
                        return image
                except (AttributeError, RuntimeError, ValueError):
                    pass
        return None

    @staticmethod
    def _image_is_referenced(image):
        import bpy

        name = image.name
        return any(
            tree.get(key, "") == name
            for tree in bpy.data.node_groups
            for key in (
                "perceptual_grade_next_stack_preview_resource",
                "perceptual_grade_next_stack_final_resource",
            )
        )

    @staticmethod
    def _create_image(role, size, values, recipe_digest, payload_digest):
        import bpy

        width, height = size * size, size
        image = bpy.data.images.new(
            f"PGN Stack {role} {recipe_digest[:12]}",
            width=width,
            height=height,
            alpha=True,
            float_buffer=True,
        )
        try:
            image.colorspace_settings.name = "Non-Color"
            image.alpha_mode = "CHANNEL_PACKED"
            image.use_half_precision = False
            rgba = np.ones((size**3, 4), dtype=np.float32)
            rgba[:, :3] = np.asarray(values, dtype=np.float32).reshape(-1, 3)
            image.pixels.foreach_set(rgba.ravel())
            image.update()
            image.pack()
            readback = np.empty(rgba.size, dtype=np.float32)
            image.pixels.foreach_get(readback)
            readback = readback.reshape(-1, 4)
            if not np.array_equal(readback[:, :3], rgba[:, :3]):
                raise RuntimeError(f"Packed Stack {role} image readback failed")
            if not image.packed_file or image.use_half_precision:
                raise RuntimeError(f"Packed Stack {role} image metadata failed")
            image["perceptual_grade_next_stack_schema"] = STACK_METADATA_SCHEMA
            image["perceptual_grade_next_stack_role"] = role
            image["perceptual_grade_next_stack_size"] = size
            image["perceptual_grade_next_stack_recipe"] = recipe_digest
            image["perceptual_grade_next_stack_digest"] = payload_digest
            image["perceptual_grade_next_stack_layout"] = "x-major-yz-contiguous-rgba32f"
            return image
        except BaseException:
            bpy.data.images.remove(image)
            raise

    def update(self, preparation):
        if not isinstance(preparation, StackPreparation):
            raise TypeError("StackDatablock requires a StackPreparation")
        metadata = preparation.metadata()
        old_preview_name = self.tree.get("perceptual_grade_next_stack_preview_resource", "")
        old_final_name = self.tree.get("perceptual_grade_next_stack_final_resource", "")
        images = []
        preview_image = self._find_image(
            "preview", preparation.recipe.digest, metadata["preview_digest"]
        )
        if preview_image is None:
            preview_image = self._create_image(
                "preview", 33, preparation.preview.values,
                preparation.recipe.digest, metadata["preview_digest"],
            )
            images.append(preview_image)
        final_image = None
        try:
            if preparation.final_ready:
                final_image = self._find_image(
                    "final", preparation.recipe.digest, metadata["final_digest"]
                )
                if final_image is None:
                    final_image = self._create_image(
                        "final", 65, preparation.final.values,
                        preparation.recipe.digest, metadata["final_digest"],
                    )
                    images.append(final_image)
        except BaseException:
            import bpy
            for image in images:
                if image.users == 0:
                    bpy.data.images.remove(image, do_unlink=True)
            raise
        properties = {
            "perceptual_grade_next_stack_schema": metadata["schema"],
            "perceptual_grade_next_stack_recipe": metadata["recipe_digest"],
            "perceptual_grade_next_stack_preview_size": metadata["preview_size"],
            "perceptual_grade_next_stack_preview_ready": metadata["preview_ready"],
            "perceptual_grade_next_stack_preview_digest": metadata["preview_digest"] or "",
            "perceptual_grade_next_stack_final_size": metadata["final_size"],
            "perceptual_grade_next_stack_final_ready": metadata["final_ready"],
            "perceptual_grade_next_stack_final_digest": metadata["final_digest"] or "",
            "perceptual_grade_next_stack_evaluator": metadata["evaluator"] or "",
            "perceptual_grade_next_stack_preview_is_bake_source": False,
            "perceptual_grade_next_stack_preview_resource": preview_image.name,
            "perceptual_grade_next_stack_final_resource": (
                "" if final_image is None else final_image.name
            ),
            "perceptual_grade_next_stack_metadata": json.dumps(
                metadata, sort_keys=True, separators=(",", ":")
            ),
            "perceptual_grade_next_stack_settings": json.dumps(
                _settings_data(preparation.settings), sort_keys=True, separators=(",", ":")
            ),
        }
        bindings = []
        if hasattr(self.tree, "nodes"):
            bindings.append(("preview", preview_image))
            if final_image is not None:
                bindings.append(("final", final_image))
        bound_nodes = []
        previous_node_images = {}
        stale_final_node = None
        try:
            for role, image in bindings:
                node = _find_resource_node(self.tree, role)
                if node is None:
                    node = _create_resource_node(self.tree, role, image)
                else:
                    previous_node_images[node.as_pointer()] = (node, node.image)
                    node.image = image
                node_name = node.name
                node["perceptual_grade_next_stack_recipe"] = preparation.recipe.digest
                properties[f"perceptual_grade_next_stack_{role}_binding"] = node_name
                bound_nodes.append(node)
            # A preview-only update must release the final resource node after
            # the new metadata is committed; keeping it would make stale data
            # look like a current final evaluator after reopen.
            if hasattr(self.tree, "nodes") and final_image is None:
                stale_final_node = _find_resource_node(self.tree, "final")
                properties["perceptual_grade_next_stack_final_binding"] = ""
        except BaseException:
            for node in bound_nodes:
                previous = previous_node_images.get(node.as_pointer())
                if previous is not None:
                    try:
                        node.image = previous[1]
                    except (AttributeError, RuntimeError):
                        pass
                else:
                    try:
                        self.tree.nodes.remove(node)
                    except (AttributeError, RuntimeError):
                        pass
            import bpy
            for image in images:
                if image.users == 0:
                    bpy.data.images.remove(image, do_unlink=True)
            raise
        previous = {key: self.tree.get(key) for key in properties}
        had_previous = {key: key in self.tree for key in properties}
        try:
            for key, value in properties.items():
                self.tree[key] = value
        except BaseException:
            for key in properties:
                try:
                    if had_previous[key]:
                        self.tree[key] = previous[key]
                    elif key in self.tree:
                        del self.tree[key]
                except BaseException:
                    pass
            for node, old_image in previous_node_images.values():
                try:
                    node.image = old_image
                except (AttributeError, RuntimeError):
                    pass
            for node in bound_nodes:
                if node.as_pointer() not in previous_node_images:
                    try:
                        self.tree.nodes.remove(node)
                    except (AttributeError, RuntimeError):
                        pass
            import bpy
            for image in images:
                if image.users == 0:
                    bpy.data.images.remove(image, do_unlink=True)
            raise
        if stale_final_node is not None:
            self.tree.nodes.remove(stale_final_node)
        self.preparation = preparation
        import bpy
        for old_name in (old_preview_name, old_final_name):
            if old_name and old_name not in {
                preview_image.name,
                "" if final_image is None else final_image.name,
            }:
                old_image = bpy.data.images.get(old_name)
                if (old_image is not None and old_image.users == 0
                        and not self._image_is_referenced(old_image)):
                    bpy.data.images.remove(old_image)
        return metadata

    def validate_persistent(self):
        """Recheck packed image IDs, dimensions, payload and readiness metadata."""
        import bpy

        metadata = self.preparation.metadata()
        expected = {
            "perceptual_grade_next_stack_schema": metadata["schema"],
            "perceptual_grade_next_stack_recipe": metadata["recipe_digest"],
            "perceptual_grade_next_stack_preview_size": metadata["preview_size"],
            "perceptual_grade_next_stack_preview_ready": metadata["preview_ready"],
            "perceptual_grade_next_stack_preview_digest": metadata["preview_digest"] or "",
            "perceptual_grade_next_stack_final_size": metadata["final_size"],
            "perceptual_grade_next_stack_final_ready": metadata["final_ready"],
            "perceptual_grade_next_stack_final_digest": metadata["final_digest"] or "",
            "perceptual_grade_next_stack_evaluator": metadata["evaluator"] or "",
            "perceptual_grade_next_stack_preview_is_bake_source": False,
            "perceptual_grade_next_stack_metadata": json.dumps(
                metadata, sort_keys=True, separators=(",", ":")
            ),
            "perceptual_grade_next_stack_settings": json.dumps(
                _settings_data(self.preparation.settings), sort_keys=True, separators=(",", ":")
            ),
        }
        if any(self.tree.get(key) != value for key, value in expected.items()):
            raise RuntimeError("Persistent Stack readiness metadata does not match its recipe")

        preview = bpy.data.images.get(self.tree.get("perceptual_grade_next_stack_preview_resource", ""))
        if preview is None:
            raise RuntimeError("Persistent Stack preview image is missing")
        if (tuple(preview.size) != (33 * 33, 33)
                or not preview.packed_file
                or preview.use_half_precision
                or preview.get("perceptual_grade_next_stack_role") != "preview"
                or preview.get("perceptual_grade_next_stack_size") != 33
                or preview.get("perceptual_grade_next_stack_recipe") != self.preparation.recipe.digest
                or preview.get("perceptual_grade_next_stack_digest") != self.preparation.preview_digest
                or _image_payload_digest(preview, 33) != self.preparation.preview_digest):
            raise RuntimeError("Persistent Stack preview image does not match its recipe")
        if hasattr(self.tree, "nodes"):
            preview_node = _find_resource_node(self.tree, "preview")
            if (preview_node is None or preview_node.image != preview
                    or self.tree.get("perceptual_grade_next_stack_preview_binding") != preview_node.name):
                raise RuntimeError("Persistent Stack preview has no native image owner")
        final_name = self.tree.get("perceptual_grade_next_stack_final_resource", "")
        if not self.final_ready:
            if final_name or self.tree.get("perceptual_grade_next_stack_final_ready"):
                raise RuntimeError("Preview-only Stack cannot carry final readiness")
            if hasattr(self.tree, "nodes") and _find_resource_node(self.tree, "final") is not None:
                raise RuntimeError("Preview-only Stack retains a stale final image owner")
            return True
        final = bpy.data.images.get(final_name)
        if final is None:
            raise RuntimeError("Persistent Stack final image is missing")
        if (tuple(final.size) != (65 * 65, 65)
                or not final.packed_file
                or final.use_half_precision
                or final.get("perceptual_grade_next_stack_role") != "final"
                or final.get("perceptual_grade_next_stack_size") != 65
                or final.get("perceptual_grade_next_stack_recipe") != self.preparation.recipe.digest
                or final.get("perceptual_grade_next_stack_digest") != self.preparation.final_digest
                or _image_payload_digest(final, 65) != self.preparation.final_digest
                or self.tree.get("perceptual_grade_next_stack_evaluator") != FINAL_EVALUATOR
                or self.tree.get("perceptual_grade_next_stack_preview_is_bake_source")):
            raise RuntimeError("Persistent Stack final image does not match its accepted LUT")
        if hasattr(self.tree, "nodes"):
            final_node = _find_resource_node(self.tree, "final")
            if (final_node is None or final_node.image != final
                    or self.tree.get("perceptual_grade_next_stack_final_binding") != final_node.name):
                raise RuntimeError("Persistent Stack final has no native image owner")
        return True

    @property
    def preview_ready(self):
        return self.preparation.preview_ready

    @property
    def final_ready(self):
        return self.preparation.final_ready

    @property
    def bake_evaluator(self):
        self.validate_persistent()
        return self.preparation.bake_lut
