"""Required graphics initialization and focused shader capability profiles."""
import sys


def initialize():
    import bpy
    import gpu
    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    gpu.init()
    if not gpu.capabilities.compute_shader_support_get():
        raise RuntimeError('Required compute-shader support is unavailable')
    print('GPU:', gpu.platform.backend_type_get(), gpu.platform.renderer_get(), flush=True)
    return gpu
