"""Lifecycle-owned bounded parameter versions, never keyed by settings hash."""

from dataclasses import dataclass, field
from typing import Optional
from ..kernel.stage2_graph import PARAMETER_BINDING, PARAMETER_IMAGE
from ..kernel.stage2_parameters import PARAMETER_SCHEMA
from ..policy import resources as resource_policy
from ..policy import parameter_publication as parameter_policy
from .publication import PublicationDeferred, PublicationGate


OWNER = "_perceptual_grade_parameter_owner"
OWNER_NODE = "_perceptual_grade_parameter_owner_node"
SIGNATURE = "_perceptual_grade_parameter_signature"


@dataclass(eq=False)
class ParameterVersion:
    generation: int
    image: object
    # A failed partial binding is already an exposure, even before activation.
    exposed: bool = False


@dataclass(eq=False)
class GradeResource:
    current: Optional[ParameterVersion] = None
    candidate: Optional[ParameterVersion] = None
    retained: list[ParameterVersion] = field(default_factory=list)
    trees: dict = field(default_factory=dict)

    @property
    def image(self):
        return None if self.current is None else self.current.image

    @property
    def generation(self):
        return None if self.current is None else self.current.generation

    @property
    def versions(self):
        versions = list(self.retained)
        for version in (self.current, self.candidate):
            if version is not None and version not in versions:
                versions.append(version)
        return tuple(versions)


class GradeResources:
    """Cache only live host identities; reset after load and native undo."""

    def __init__(self, bpy):
        self.bpy = bpy
        self._resources = {}
        self.pending = {}
        self.gate = PublicationGate(bpy)
        self._serial = 0

    def _version(self, image, *, exposed=False):
        self._serial += 1
        return ParameterVersion(self._serial, image, exposed)

    @staticmethod
    def _same_image(first, second):
        try:
            return first is second or first == second
        except (ReferenceError, AttributeError):
            return first is second

    def _adopt_current(self, resource, image):
        if image is None:
            if resource.current is not None:
                if resource.current not in resource.retained:
                    resource.retained.append(resource.current)
                resource.current = None
            return
        if resource.current is not None and self._same_image(resource.image, image):
            return
        version = next((version for version in resource.versions
                        if self._same_image(version.image, image)), None)
        if version is None:
            if len(resource.versions) >= 3:
                raise RuntimeError("Grade parameter binding escaped its bounded version pool")
            version = self._version(image, exposed=True)
        if resource.current is not None and resource.current not in resource.retained:
            resource.retained.append(resource.current)
        if version in resource.retained:
            resource.retained.remove(version)
        if resource.candidate is version:
            resource.candidate = None
        version.exposed = True
        resource.current = version

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
        selected_image = None
        selected_trees = {}
        for tree in trees:
            image = self._owned_image(tree, owner, owner_node, space, selected_image)
            if image is None:
                continue
            selected_image = image
            selected_trees[tree.bl_idname] = tree
        self._adopt_current(resource, selected_image)
        resource.trees = selected_trees
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
        self._adopt_current(resource, tree[PARAMETER_BINDING])
        return resource

    def acquire_candidate(self, resource, create_image):
        """Consume the pool grant; an exposed candidate must first be aborted."""
        effects = parameter_policy.candidate_effect(
            len(resource.versions), resource.candidate is not None,
            resource.candidate.exposed if resource.candidate is not None else False,
        )
        if effects.action == "reuse":
            return resource.candidate
        if effects.action == "allocate":
            image = create_image()
            resource.candidate = self._version(image)
            return resource.candidate
        raise PublicationDeferred("Grade parameter version pool is full or awaiting rollback")

    @staticmethod
    def expose(resource, version):
        if resource.candidate is not version or version.exposed:
            raise RuntimeError("Grade parameter candidate is not unpublished")
        version.exposed = True

    @staticmethod
    def publish(resource, version):
        if resource.candidate is not version or not version.exposed:
            raise RuntimeError("Grade parameter candidate has not been bound")
        if resource.current is not None:
            resource.retained.append(resource.current)
        resource.current = version
        resource.candidate = None

    @staticmethod
    def abort(resource, version):
        if version is not None and resource.candidate is version and version.exposed:
            resource.candidate = None
            resource.retained.append(version)

    @staticmethod
    def restore_current(resource, previous):
        """Restore bookkeeping after binding rollback, retaining exposed images."""
        if resource.current is previous:
            return
        if previous is not None and previous not in resource.retained:
            raise RuntimeError("Previous Grade parameter version is no longer retained")
        if resource.current is not None:
            resource.retained.append(resource.current)
        resource.current = previous
        if previous is not None:
            resource.retained.remove(previous)

    def protected(self, image):
        return any(self._same_image(version.image, image)
                   for resource in self._resources.values()
                   for version in resource.versions)

    def generations(self):
        """Plain immutable receipt suitable for worker-side evaluation capture."""
        return tuple(resource.generation for resource in self._resources.values()
                     if resource.generation is not None)

    @staticmethod
    def _retirement_observation(resource, version, quiescent):
        image = version.image
        try:
            live = bool(image.as_pointer())
            users = image.users if live else 0
            protected = image.use_fake_user if live else False
        except (ReferenceError, AttributeError):
            live, users, protected = False, 0, False
        return parameter_policy.retirement_effect(
            live, quiescent, version is resource.current,
            version is resource.candidate, users, protected,
        )

    def reclaim(self, resource, remove_image):
        """Retire only when readers are quiescent or parked before evaluation."""
        failures = []
        for version in tuple(resource.retained):
            effects = self._retirement_observation(resource, version, self.gate.retirement_allowed())
            if effects.action == "evict":
                resource.retained.remove(version)
            elif effects.action == "remove":
                # Fresh observation immediately precedes the native mutation.
                effects = self._retirement_observation(resource, version, self.gate.retirement_allowed())
                if effects.action != "remove":
                    continue
                try:
                    remove_image(version.image)
                except Exception as error:
                    failures.append(error)
                    if version not in resource.versions:
                        resource.retained.append(version)
                else:
                    if version in resource.retained:
                        resource.retained.remove(version)
        return tuple(failures)

    def reclaim_all(self, remove_image):
        failures = []
        for resource in tuple(self._resources.values()):
            failures.extend(self.reclaim(resource, remove_image))
        return tuple(failures)

    def clear(self):
        if not self.gate.quiescent():
            raise PublicationDeferred("Cannot release Grade parameter versions while native readers are active")
        self.pending.clear()
        self._resources.clear()

    def retire(self, tree):
        for resource in self._resources.values():
            for kind, existing in tuple(resource.trees.items()):
                if existing == tree:
                    del resource.trees[kind]
            if not resource.trees:
                self._adopt_current(resource, None)

    def retire_image(self, image):
        """Evict every dependent lookup before the image's native deletion."""
        for resource in self._resources.values():
            if self._same_image(resource.image, image):
                resource.current = None
                resource.trees.clear()
            if (resource.candidate is not None
                    and self._same_image(resource.candidate.image, image)):
                resource.candidate = None
            resource.retained[:] = [version for version in resource.retained
                                    if not self._same_image(version.image, image)]

    def forget(self, source):
        for key in tuple(self.pending):
            if key[0] is source:
                del self.pending[key]
