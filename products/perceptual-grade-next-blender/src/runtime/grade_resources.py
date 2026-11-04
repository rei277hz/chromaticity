"""Lifecycle-owned lookup of writable Grade resources, never by settings hash."""

from dataclasses import dataclass, field
from typing import Optional
from ..kernel.stage2_graph import PARAMETER_BINDING, PARAMETER_IMAGE
from ..kernel.stage2_parameters import PARAMETER_SCHEMA
from ..policy import resources as resource_policy
from .publication import PublicationGate


OWNER = "_perceptual_grade_parameter_owner"
OWNER_NODE = "_perceptual_grade_parameter_owner_node"
SIGNATURE = "_perceptual_grade_parameter_signature"


@dataclass
class GradeResource:
    image: Optional[object] = None
    trees: dict = field(default_factory=dict)


class GradeResources:
    """Cache only live host identities; reset after load and native undo."""

    def __init__(self, bpy):
        self.bpy = bpy
        self._resources = {}
        self.pending = {}
        self.gate = PublicationGate(bpy)

    def owner(self, node):
        if node.pg_grade is not None:
            return node.pg_grade, None
        tree = node.id_data
        if not tree.is_embedded_data:
            return tree, node.name
        # Embedded node trees cannot be stored in ID-valued custom properties.
        # Persist their containing datablock instead; the node name identifies
        # the local Grade within that owner's tree across save/load and undo.
        for collection in ("materials", "worlds", "lights", "scenes", "linestyles"):
            for owner in getattr(self.bpy.data, collection, ()):
                if getattr(owner, "node_tree", None) == tree:
                    return owner, node.name
        raise RuntimeError(
            f"Cannot resolve the containing datablock for Grade node {node.name!r} "
            f"in embedded node tree {tree.name!r}"
        )

    def resource(self, node, space):
        owner, owner_node = self.owner(node)
        key = (owner.as_pointer(), owner_node, space)
        resource = self._resources.get(key)
        if resource is None:
            resource = GradeResource()
            # Adopt persisted bindings only at an ownership/lifecycle boundary.
            # Ordinary lookups validate the cached trees without a scene scan.
            trees = self.bpy.data.node_groups
        else:
            trees = tuple(resource.trees.values())
            resource.trees.clear()
            resource.image = None
        for tree in trees:
            image = self._owned_image(tree, owner, owner_node, space, resource.image)
            if image is None:
                continue
            resource.image = image
            resource.trees[tree.bl_idname] = tree
        self._resources[key] = resource
        return resource

    @staticmethod
    def _owned_image(tree, owner, owner_node, space, selected_image=None):
        try:
            image = tree.get(PARAMETER_BINDING)
            observation = resource_policy.Adoption(
                owner_matches=tree.get(OWNER) == owner,
                node_matches=tree.get(OWNER_NODE) == owner_node,
                space_matches=tree.get("_perceptual_grade_working_space") == space,
                complete=bool(tree.get("_perceptual_grade_stage2_complete")),
                image_valid=(image is not None
                             and image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA),
                image_agrees=selected_image is None or selected_image == image,
            )
            if resource_policy.may_adopt(observation):
                return image
        except (AttributeError, ReferenceError):
            # A native deletion can invalidate wrappers without clearing this
            # Python cache. Rebuild derived data instead of reusing dead IDs.
            pass
        return None

    def remember(self, node, space, tree):
        resource = self.resource(node, space)
        owner, owner_node = self.owner(node)
        tree[OWNER] = owner
        if owner_node is not None:
            tree[OWNER_NODE] = owner_node
        if self._owned_image(tree, owner, owner_node, space, resource.image) is None:
            raise RuntimeError("Cannot adopt invalid Grade resources")
        resource.trees[tree.bl_idname] = tree
        resource.image = tree[PARAMETER_BINDING]
        return resource

    def clear(self):
        self.pending.clear()
        self._resources.clear()

    def retire(self, tree):
        for resource in self._resources.values():
            for kind, existing in tuple(resource.trees.items()):
                if existing == tree:
                    del resource.trees[kind]
            if not resource.trees:
                resource.image = None

    def retire_image(self, image):
        """Evict every dependent lookup before the image's native deletion."""
        for resource in self._resources.values():
            if resource.image is image or resource.image == image:
                resource.image = None
                resource.trees.clear()

    def forget(self, source):
        for key in tuple(self.pending):
            if key[0] is source:
                del self.pending[key]
