"""Grade Publication Compare Blender extension."""

from . import nodes


def register():
    nodes.register()


def unregister():
    nodes.unregister()
