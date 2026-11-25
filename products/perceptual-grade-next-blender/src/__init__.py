"""Perceptual Grade Blender registration hooks."""

def register():
    from . import application
    application.register()


def unregister():
    from . import application
    application.unregister()


def invalidate_image(image):
    """Invalidate bake receipts after an external script edits Image pixels."""
    from .application import invalidate_image as invalidate
    return invalidate(image)
