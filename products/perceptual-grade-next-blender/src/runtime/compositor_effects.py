"""Scene compositor roots across the supported Blender versions."""

from .capture_images import datablock_key


def compositor_occurrences(scene, *, mode=None):
    """Yield each (effect, root) in stack order or the legacy (None, root)."""
    if mode == "render" and not getattr(getattr(scene, "render", None), "use_compositing", True):
        return
    effects = getattr(scene, "compositor_effects", None)
    if effects is None:
        root = getattr(scene, "compositing_node_group", getattr(scene, "node_tree", None))
        if root is not None:
            yield None, root
        return
    for effect in effects:
        root = effect.node_group
        if (root is not None
                and (mode is None or getattr(effect, "enable_for_" + mode))):
            yield effect, root


def matching_compositor_occurrences(host, scene, route):
    """Match a saved Bake occurrence, including routes from single-root files."""
    name = route.get("effect_name")
    root_key = route.get("root_key")
    for effect, root in compositor_occurrences(scene):
        if name is not None and (effect is None or effect.name != name):
            continue
        if root_key is None or datablock_key(host, root) == tuple(root_key):
            yield effect, root
