"""Independent Blender extension entrypoint; dependencies are privately bundled."""


def register():
    from .hdr_color_picker_blender import register as enable
    enable()


def unregister():
    from .hdr_color_picker_blender import unregister as disable
    disable()
