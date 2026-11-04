"""Lifecycle-owned lookup of writable Grade resources, never by settings hash."""

from dataclasses import dataclass, field
from typing import Optional
from ..kernel.stage2_graph import PARAMETER_BINDING, PARAMETER_IMAGE
from ..kernel.stage2_parameters import PARAMETER_SCHEMA
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

    @staticmethod
    def owner(node):
        if node.pg_grade is not None:
            return node.pg_grade, None
        return node.id_data, node.name

    def resource(self, node, space):
        owner, owner_node = self.owner(node)
        key = (owner.as_pointer(), owner_node, space)
        resource = self._resources.get(key)
        if resource is not None:
            return resource
        resource = GradeResource()
        # This is adoption at an ownership/lifecycle boundary, not a per-edit
        # scene scan. ID-valued properties survive save/load and native undo.
        for tree in self.bpy.data.node_groups:
            if (tree.get(OWNER) != owner
                    or tree.get(OWNER_NODE) != owner_node
                    or tree.get("_perceptual_grade_working_space") != space
                    or not tree.get("_perceptual_grade_stage2_complete")):
                continue
            image = tree.get(PARAMETER_BINDING)
            if image is None or image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA:
                continue
            if resource.image is not None and resource.image != image:
                continue
            resource.image = image
            resource.trees[tree.bl_idname] = tree
        self._resources[key] = resource
        return resource

    def remember(self, node, space, tree):
        resource = self.resource(node, space)
        owner, owner_node = self.owner(node)
        tree[OWNER] = owner
        if owner_node is not None:
            tree[OWNER_NODE] = owner_node
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

    def forget(self, source):
        for key in tuple(self.pending):
            if key[0] is source:
                del self.pending[key]
