"""Lifecycle-owned fixed parameter-image banks for each Grade owner."""

from dataclasses import dataclass, field
from typing import Optional

from ..kernel.stage2_bindings import (
    PARAMETER_ACTIVE_BANK, PARAMETER_BANK_BINDINGS, PARAMETER_GENERATION,
    PARAMETER_IMAGE, PARAMETER_READER, PARAMETER_READER_BANK,
    PARAMETER_READER_ROLE, PARAMETER_ROLE, PARAMETER_SELECTOR,
)
from ..kernel.stage2_parameters import (
    PARAMETER_SCHEMA, PARAMETER_ROLES, PARAMETER_ROLE_SHAPES,
    parameter_bank_images, parameter_bundle_receipt_matches,
)
from ..policy import resources as resource_policy
from .publication import PublicationDeferred, PublicationGate


OWNER = "_perceptual_grade_parameter_owner"
OWNER_NODE = "_perceptual_grade_parameter_owner_node"
SIGNATURE = "_perceptual_grade_parameter_signature"


@dataclass(eq=False)
class GradeResource:
    banks: Optional[tuple[object, object]] = None
    active_bank: Optional[int] = None
    generation: Optional[int] = None
    trees: dict = field(default_factory=dict)
    retiring_images: Optional[tuple[object, ...]] = None

    @property
    def images(self):
        if self.retiring_images is not None:
            return self.retiring_images
        if self.banks is None:
            return ()
        images = []
        for primary in self.banks:
            try:
                bundle = parameter_bank_images(primary)
            except (AttributeError, ReferenceError, RuntimeError):
                # External ID deletion also removes its role bindings. Keep
                # the wrapper available for eviction without dereferencing it;
                # surviving native readers protect their remaining images.
                images.append(primary)
                continue
            images.extend(image for role in PARAMETER_ROLES
                          if (image := bundle.get(role)) is not None)
        return tuple(images)

    @property
    def image(self):
        if self.banks is None or self.active_bank not in (0, 1):
            return None
        return self.banks[self.active_bank]

    @property
    def candidate_bank(self):
        if self.banks is None or self.active_bank not in (0, 1):
            return None
        return 1 - self.active_bank


class GradeResources:
    """Adopt persistent image identities at load/undo and own their retirement."""

    def __init__(self, bpy):
        self.bpy = bpy
        self._resources = {}
        self._lifecycle_images = {}
        self.pending = {}
        self.gate = PublicationGate(bpy)
        self._serial = 0

    @staticmethod
    def _same_image(first, second):
        try:
            return first is second or first == second
        except (ReferenceError, AttributeError):
            return first is second

    @staticmethod
    def _same_banks(first, second):
        return (first is not None and second is not None and len(first) == 2
                and len(second) == 2
                and all(GradeResources._same_image(a, b)
                        for a, b in zip(first, second)))

    @staticmethod
    def _valid_bank_index(bank):
        return type(bank) is int and bank in (0, 1)

    def next_generation(self, resource):
        self._serial = max(self._serial, resource.generation or 0) + 1
        return self._serial

    def owner(self, node):
        grade = getattr(node, "pg_grade", None)
        if grade is not None:
            return grade, None
        tree = node.id_data
        if not tree.is_embedded_data:
            return tree, node.name
        # Embedded trees cannot store their owner as an ID-valued property.
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
            # Scan persisted node groups only at an ownership/lifecycle boundary.
            trees = self.bpy.data.node_groups
        else:
            trees = tuple(resource.trees.values())

        selected_banks = None
        selected_active = None
        selected_generation = None
        selected_trees = {}
        invalid_cached_tree = False
        for tree in trees:
            observed = self._owned_banks(
                tree, owner, owner_node, space, selected_banks,
                selected_active, selected_generation,
            )
            if observed is None:
                if resource is not None and any(
                        tree == tracked for tracked in resource.trees.values()):
                    invalid_cached_tree = True
                independent = self._owned_banks(tree, owner, owner_node, space)
                if independent is not None and selected_banks is not None:
                    banks, active, generation = independent
                    if (not self._same_banks(selected_banks, banks)
                            or selected_active != active
                            or selected_generation != generation):
                        raise RuntimeError(
                            "Grade parameter banks, selectors, or generations disagree "
                            "across kernels"
                        )
                continue
            banks, active, generation = observed
            selected_banks = banks
            selected_active = active
            selected_generation = generation
            selected_trees[tree.bl_idname] = tree

        if selected_banks is None and invalid_cached_tree:
            resource.banks = None
            resource.active_bank = None
            resource.generation = None
        if selected_banks is not None:
            if resource.banks is not None and not self._same_banks(resource.banks, selected_banks):
                raise RuntimeError("Grade parameter bank identities changed unexpectedly")
            if (resource.active_bank is not None
                    and resource.active_bank != selected_active):
                raise RuntimeError("Grade parameter selectors disagree across kernels")
            if (resource.generation is not None
                    and resource.generation != selected_generation):
                raise RuntimeError("Grade parameter generations disagree across kernels")
            resource.banks = selected_banks
            resource.active_bank = selected_active
            resource.generation = selected_generation
            self._serial = max(self._serial, selected_generation)
        resource.trees = selected_trees
        self._resources[key] = resource
        return resource

    @classmethod
    def _owned_banks(cls, tree, owner, owner_node, space,
                     selected_banks=None, selected_active=None,
                     selected_generation=None):
        try:
            banks = tuple(tree.get(key) for key in PARAMETER_BANK_BINDINGS)
            active = tree.get(PARAMETER_ACTIVE_BANK)
            generation = tree.get(PARAMETER_GENERATION)
            valid_banks = (
                len(banks) == 2 and banks[0] is not None and banks[1] is not None
                and cls._valid_pair(banks)
            )
            observation = resource_policy.Adoption(
                owner_matches=tree.get(OWNER) == owner,
                node_matches=tree.get(OWNER_NODE) == owner_node,
                space_matches=tree.get("_perceptual_grade_working_space") == space,
                complete=bool(tree.get("_perceptual_grade_stage2_complete")),
                image_valid=(valid_banks and cls._valid_bank_index(active)
                             and type(generation) is int and generation >= 0
                             and cls._selector_matches(tree, banks, active)),
                image_agrees=(
                    (selected_banks is None or cls._same_banks(selected_banks, banks))
                    and (selected_active is None or selected_active == active)
                    and (selected_generation is None
                         or selected_generation == generation)
                ),
            )
            if resource_policy.may_adopt(observation):
                return banks, active, generation
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            # A deleted ID may leave a stale wrapper in the Python cache.
            pass
        return None

    @classmethod
    def _valid_image(cls, image, role):
        try:
            shape = PARAMETER_ROLE_SHAPES[role]
            return (image.as_pointer() != 0
                    and image.get(PARAMETER_IMAGE) == PARAMETER_SCHEMA
                    and image.get(PARAMETER_ROLE) == role
                    and tuple(image.size) == (shape[1], shape[0]))
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return False

    @classmethod
    def _valid_bundle(cls, primary):
        try:
            images = parameter_bank_images(primary)
            if set(images) != set(PARAMETER_ROLES):
                return False
            values = tuple(images[role] for role in PARAMETER_ROLES)
            pointers = tuple(image.as_pointer() for image in values)
            return (all(pointers) and len(set(pointers)) == len(PARAMETER_ROLES)
                    and all(cls._valid_image(image, role)
                            for role, image in zip(PARAMETER_ROLES, values))
                    and parameter_bundle_receipt_matches(primary))
        except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

    @classmethod
    def _valid_pair(cls, banks):
        try:
            if len(banks) != 2 or not all(cls._valid_bundle(image) for image in banks):
                return False
            pointers = tuple(image.as_pointer() for primary in banks
                             for image in parameter_bank_images(primary).values())
            return len(set(pointers)) == 2 * len(PARAMETER_ROLES)
        except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

    @staticmethod
    def _selector_matches(tree, banks, active):
        try:
            selectors = tuple(node for node in tree.nodes
                              if node.get(PARAMETER_SELECTOR))
            if len(selectors) != 1:
                return False
            selector = selectors[0]
            if tree.bl_idname == "ShaderNodeTree":
                value = float(selector.outputs["Value"].default_value)
                if value not in (0., 1.) or int(value) != active:
                    return False
            elif tree.bl_idname == "CompositorNodeTree":
                value = float(selector.inputs[0].default_value)
                if (selector.bl_idname != "ShaderNodeMath"
                        or selector.operation != "ADD"
                        or selector.inputs[0].is_linked
                        or selector.inputs[1].is_linked
                        or float(selector.inputs[1].default_value) != 0.0
                        or value not in (0., 1.) or int(value) != active):
                    return False
            else:
                return False
            readers = tuple(node for node in tree.nodes
                            if node.get(PARAMETER_READER))
            observed = set()
            for reader in readers:
                bank = reader.get(PARAMETER_READER_BANK)
                role = reader.get(PARAMETER_READER_ROLE)
                if bank not in (0, 1) or role not in PARAMETER_ROLES:
                    return False
                bundle = parameter_bank_images(banks[bank])
                if not GradeResources._same_image(
                        getattr(reader, "image", None), bundle.get(role)):
                    return False
                observed.add((bank, role))
            return observed == {
                (bank, role) for bank in (0, 1) for role in PARAMETER_ROLES
            }
        except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False

    def remember(self, node, space, tree):
        resource = self.resource(node, space)
        owner, owner_node = self.owner(node)
        tree[OWNER] = owner
        if owner_node is not None:
            tree[OWNER_NODE] = owner_node
        observed = self._owned_banks(
            tree, owner, owner_node, space, resource.banks,
            resource.active_bank, resource.generation,
        )
        if observed is None:
            raise RuntimeError("Cannot adopt invalid Grade parameter banks")
        banks, active, generation = observed
        if resource.banks is None:
            self.set_banks(resource, banks, active, generation)
        resource.trees[tree.bl_idname] = tree
        return resource

    def set_banks(self, resource, banks, active_bank, generation):
        banks = tuple(banks)
        if (not self._valid_pair(banks)
                or not self._valid_bank_index(active_bank)
                or type(generation) is not int or generation < 0):
            raise ValueError("Grade resources require two valid banks and a selector")
        if resource.banks is not None and not self._same_banks(resource.banks, banks):
            raise RuntimeError("Grade parameter banks have fixed identities and cannot be replaced")
        resource.banks = banks
        resource.active_bank = active_bank
        resource.generation = generation
        resource.retiring_images = None
        self._serial = max(self._serial, generation)

    def publish(self, resource, bank, generation):
        if resource.banks is None or bank != resource.candidate_bank:
            raise RuntimeError("Grade publication must select the inactive fixed bank")
        if type(generation) is not int or generation <= (resource.generation or 0):
            raise RuntimeError("Grade publication generation must increase")
        resource.active_bank = bank
        resource.generation = generation
        self._serial = max(self._serial, generation)

    @staticmethod
    def restore(resource, active_bank, generation):
        """Restore bookkeeping after the caller has restored native selectors."""
        if resource.banks is None or not GradeResources._valid_bank_index(active_bank):
            raise RuntimeError("Cannot restore a Grade resource without its fixed banks")
        if type(generation) is not int or generation < 0:
            raise RuntimeError("Cannot restore an invalid Grade parameter generation")
        resource.active_bank = active_bank
        resource.generation = generation

    def protected(self, image):
        return self._lifecycle_protected(image) or any(self._same_image(bank, image)
                   for resource in self._resources.values()
                   for bank in resource.images)

    def _lifecycle_protected(self, image):
        return any(self._same_image(previous, image)
                   for previous in self._lifecycle_images.values())

    def generations(self):
        """Plain immutable evaluation receipt data for compositor workers."""
        return tuple(sorted({resource.generation for resource in self._resources.values()
                             if resource.generation is not None}))

    @staticmethod
    def _removable(image, retirement_allowed):
        try:
            if not image.as_pointer():
                return True
            if not retirement_allowed():
                return False
            if image.users != 0 or image.use_fake_user:
                return False
            # Re-observe gate and native references immediately before removal.
            return (retirement_allowed() and image.as_pointer() != 0
                    and image.users == 0 and not image.use_fake_user)
        except (AttributeError, ReferenceError, RuntimeError):
            return False

    def reclaim(self, resource, remove_image):
        """Delete a pair only after every tracked reader tree has been retired."""
        if (resource.banks is None and resource.retiring_images is None) or resource.trees:
            return ()
        failures = []
        removed = set()
        if resource.retiring_images is None:
            resource.retiring_images = tuple(resource.images)
        images = resource.retiring_images
        for image in images:
            try:
                pointer = image.as_pointer()
            except (AttributeError, ReferenceError, RuntimeError):
                removed.add(id(image))
                continue
            if pointer == 0:
                removed.add(id(image))
                continue
            if (self._lifecycle_protected(image)
                    or not self._removable(image, self.gate.retirement_allowed)):
                continue
            try:
                remove_image(image)
            except Exception as error:
                failures.append(error)
                continue
            try:
                still_live = image.as_pointer() != 0
            except (AttributeError, ReferenceError, RuntimeError):
                still_live = False
            if still_live:
                failures.append(RuntimeError("Grade parameter bank removal was not confirmed"))
            else:
                removed.add(id(image))
        if not failures and len(removed) == len(images):
            resource.banks = None
            resource.active_bank = None
            resource.generation = None
            resource.retiring_images = None
        return tuple(failures)

    def reclaim_all(self, remove_image):
        failures = []
        for resource in tuple(self._resources.values()):
            failures.extend(self.reclaim(resource, remove_image))
        return tuple(failures)

    def invalidate(self):
        """Fence pre-load/undo banks from adoption while keeping every role pinned."""
        for resource in self._resources.values():
            for image in resource.images:
                self._lifecycle_images[id(image)] = image
        self.pending.clear()
        self._resources.clear()

    def release_lifecycle_images(self):
        if not self.gate.quiescent():
            raise PublicationDeferred(
                "Cannot release Grade parameter banks while native readers are active"
            )
        self._lifecycle_images.clear()

    def clear(self):
        self.release_lifecycle_images()
        self.pending.clear()
        self._resources.clear()

    def retire(self, tree):
        for resource in self._resources.values():
            for kind, existing in tuple(resource.trees.items()):
                if existing == tree:
                    del resource.trees[kind]

    def retire_image(self, image):
        """Evict every cache reference before a helper image is deleted."""
        for resource in self._resources.values():
            if any(self._same_image(bank, image) for bank in resource.images):
                resource.retiring_images = tuple(resource.images)
                resource.banks = None
                resource.active_bank = None
                resource.generation = None
                resource.trees.clear()

    def forget(self, source):
        for key in tuple(self.pending):
            if key[0] is source:
                del self.pending[key]
