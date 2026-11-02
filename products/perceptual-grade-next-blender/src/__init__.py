"""Perceptual Grade Blender registration hooks."""

def register():
    from . import nodes
    nodes.register()


def unregister():
    from . import nodes
    nodes.unregister()
