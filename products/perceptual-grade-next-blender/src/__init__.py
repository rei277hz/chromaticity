"""Perceptual Grade Blender registration hooks."""

def register():
    from . import nodes
    nodes.register()


def unregister():
    from . import nodes
    nodes.unregister()


def invalidate_image(image):
    """Invalidate bake receipts after an external script edits Image pixels."""
    from .nodes import invalidate_source
    return invalidate_source(image)
