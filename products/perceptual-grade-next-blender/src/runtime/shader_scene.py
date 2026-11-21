"""Original datablocks that can contribute shader graphs to a scene render."""

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ShaderSceneInventory:
    objects: tuple
    collections: tuple
    view_layers: tuple
    owners: tuple


def shader_scene_inventory(scene, *, view_layers=None):
    """Include collection instance sources that are absent from scene.objects."""
    view_layers = (tuple(layer for layer in getattr(scene, "view_layers", ())
                         if getattr(layer, "use", True))
                   if view_layers is None else tuple(view_layers))
    objects = {}
    collections = {}
    owners = {}

    def add_owner(kind, owner):
        if owner is not None:
            owners.setdefault((kind, owner.as_pointer()), (kind, owner))

    add_owner("world", getattr(scene, "world", None))
    pending = deque(getattr(scene, "objects", ()))
    while pending:
        obj = pending.popleft()
        pointer = obj.as_pointer()
        if pointer in objects:
            continue
        objects[pointer] = obj
        for slot in getattr(obj, "material_slots", ()):
            add_owner("material", slot.material)
        if getattr(obj, "type", None) == "LIGHT":
            add_owner("light", obj.data)
        instance = (getattr(obj, "instance_collection", None)
                    if getattr(obj, "instance_type", None) == "COLLECTION" else None)
        instance_collections = [] if instance is None else [instance]
        while instance_collections:
            collection = instance_collections.pop()
            pointer = collection.as_pointer()
            if pointer not in collections:
                collections[pointer] = collection
                pending.extend(collection.objects)
                instance_collections.extend(collection.children)

    for layer in view_layers:
        add_owner("material", getattr(layer, "material_override", None))
        add_owner("world", getattr(layer, "world_override", None))
    return ShaderSceneInventory(tuple(objects.values()), tuple(collections.values()),
                                view_layers, tuple(owners.values()))
