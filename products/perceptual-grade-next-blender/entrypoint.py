"""Blender extension entrypoint for Perceptual Grade Next."""


def register():
    from .perceptual_grade_next_blender import register as enable
    enable()


def unregister():
    from .perceptual_grade_next_blender import unregister as disable
    disable()
