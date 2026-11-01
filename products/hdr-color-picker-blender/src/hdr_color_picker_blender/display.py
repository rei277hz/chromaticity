"""Active Blender view transform for an ACEScg picker texture.

Uses Blender's bundled OpenColorIO configuration and generated GPU processor,
never an independently fitted view LUT. The initial validated presentation is
SDR sRGB. Unsupported native display features fail closed rather than silently
substituting the palette project's fixed presentation.

All entry points run on Blender's main thread. Instances own only value data
and GPU objects, and never retain a Scene, Brush or other Blender ID.
"""
from dataclasses import dataclass
import copy
import os
from pathlib import Path
import re

import numpy as np


class DisplayUnavailable(RuntimeError):
    """The selected display path has not passed the native fidelity gate."""


def _ocio():
    try:
        import PyOpenColorIO
    except ImportError as exc:
        raise DisplayUnavailable('This Blender build has no OpenColorIO Python module') from exc
    return PyOpenColorIO


@dataclass(frozen=True)
class ViewIdentity:
    config: str
    working_space: str
    display: str
    view: str
    look: str
    exposure: float
    gamma: float
    emulation: str
    curves: bool
    white_balance: bool


def signature(scene):
    """Capture settings as values; changes invalidate pending presentation."""
    ocio = _ocio()
    config = ocio.GetCurrentConfig()
    view = scene.view_settings
    return ViewIdentity(config.getCacheID(), config.getRoleColorSpace('scene_linear'),
                        scene.display_settings.display_device, view.view_transform,
                        view.look, float(view.exposure), float(view.gamma),
                        scene.display_settings.emulation, bool(view.use_curve_mapping),
                        bool(view.use_white_balance))


def _bundled_config():
    import bpy
    path = Path(bpy.utils.resource_path('LOCAL')) / 'datafiles/colormanagement/config.ocio'
    return _ocio().Config.CreateFromFile(str(path))


def _require_bundled_config(config):
    """Reject runtime config replacement as well as an OCIO environment override."""
    bundled = _bundled_config()
    normalized = copy.deepcopy(config)
    # Blender adjusts the scene-linear role and adds these HDR display helpers
    # to its loaded configuration. Neither helper participates in our sRGB path.
    normalized.setRole('scene_linear', bundled.getRoleColorSpace('scene_linear'))
    for name in ('blender:pq_rec2020_display_203nits', 'blender:hlg_rec2020_display_203nits'):
        if bundled.getColorSpace(name) is None:
            normalized.removeColorSpace(name)
    if normalized.getCacheID() != bundled.getCacheID():
        raise DisplayUnavailable('Picker preview requires Blender\'s bundled OCIO configuration')


def _processor(identity):
    ocio = _ocio()
    if os.environ.get('OCIO'):
        import bpy
        builtin = Path(bpy.utils.resource_path('LOCAL')) / 'datafiles/colormanagement/config.ocio'
        if Path(os.environ['OCIO']).resolve() != builtin.resolve():
            raise DisplayUnavailable('Picker preview has not validated a custom OCIO configuration')
    if identity.display != 'sRGB':
        raise DisplayUnavailable('Picker preview currently requires the sRGB display device')
    if identity.working_space not in ('ACEScg', 'Linear Rec.709'):
        raise DisplayUnavailable('Picker preview requires ACEScg or Linear Rec.709 working space')
    if identity.curves:
        raise DisplayUnavailable('Picker preview does not yet support view curves')
    if identity.white_balance:
        raise DisplayUnavailable('Picker preview does not yet support view white balance')
    config = ocio.GetCurrentConfig()
    if config.getCacheID() != identity.config:
        raise DisplayUnavailable('Color configuration changed while preparing the picker')
    _require_bundled_config(config)
    group = ocio.GroupTransform()
    # Data views such as Raw bypass normal colorspace conversion. Convert to
    # the actual working space first, matching the values Blender displays.
    source = identity.working_space
    group.appendTransform(ocio.ColorSpaceTransform(src='ACEScg', dst=source))
    scale = float(np.float32(2.0 ** identity.exposure))
    if scale != 1:
        group.appendTransform(ocio.MatrixTransform(matrix=[
            scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1]))
    use_look = identity.look not in ('', 'None')
    if use_look:
        look = config.getLook(identity.look)
        if look is None:
            raise DisplayUnavailable('The active view look is unavailable')
        target = look.getProcessSpace()
        view_space = config.getColorSpace(config.getDisplayViewColorSpaceName(
            identity.display, identity.view))
        if view_space is not None and view_space.isData():
            target = source
        group.appendTransform(ocio.LookTransform(src=source, dst=target, looks=identity.look))
        source = target
    group.appendTransform(ocio.DisplayViewTransform(
        src=source, display=identity.display, view=identity.view, looksBypass=use_look))
    if identity.gamma != 1:
        exponent = min(100.0, 1.0 / max(float(np.finfo(np.float32).eps), identity.gamma))
        group.appendTransform(ocio.ExponentTransform(value=[exponent] * 3 + [1]))
    # Blender's sRGB SDR display-emulation stage clamps the display encoding.
    # With emulation OFF the native pipeline retains its unbounded result.
    if identity.emulation != 'OFF':
        group.appendTransform(ocio.RangeTransform(minInValue=0, minOutValue=0,
                                                  maxInValue=1, maxOutValue=1))
    try:
        return config.getProcessor(group)
    except Exception as exc:
        raise DisplayUnavailable('The active view cannot process ACEScg picker colors') from exc


class DisplayTransform:
    def __init__(self, scene):
        self.identity = signature(scene)
        self._processor = _processor(self.identity)
        self._gpu = None

    def apply(self, rgba):
        """CPU display-encoded reference; input/output are straight RGBA floats."""
        data = np.array(rgba, dtype=np.float32, order='C', copy=True)
        if data.shape[-1] != 4 or not np.isfinite(data).all():
            raise ValueError('Expected finite RGBA pixels')
        alpha = data[..., 3].copy()
        self._processor.getDefaultCPUProcessor().applyRGBA(data.reshape(-1, 4))
        data[..., 3] = alpha
        return data

    def gpu(self):
        """Compile the same processor using Blender's supported GPU API."""
        if self._gpu is None:
            self._gpu = GPUView(self._processor)
        return self._gpu

    def close(self):
        self._gpu = None


def processor(scene):
    return DisplayTransform(scene)


class GPUView:
    """Private shader/LUT resources; no global registrations or native IDs."""
    def __init__(self, processor):
        import gpu
        ocio = _ocio()
        desc = ocio.GpuShaderDesc.CreateShaderDesc()
        desc.setLanguage(ocio.GPU_LANGUAGE_GLSL_4_0)
        desc.setFunctionName('hdr_picker_view')
        desc.setResourcePrefix('hdr_picker_ocio_')
        desc.setAllowTexture1D(False)
        processor.getDefaultGPUProcessor().extractGpuShaderInfo(desc)
        if list(desc.getUniforms()):
            raise DisplayUnavailable('Dynamic OpenColorIO uniforms are not supported')
        interface = gpu.types.GPUStageInterfaceInfo('hdr_picker_display_interface')
        interface.smooth('VEC2', 'uv')
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, 'VEC2', 'position')
        info.vertex_in(1, 'VEC2', 'texCoord')
        info.vertex_out(interface)
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.push_constant('MAT4', 'ModelViewProjectionMatrix')
        # Blender binds this reserved uniform for the current render target.
        # The OCIO processor already returns display encoding; an sRGB target
        # encodes shader outputs, so undo that encoding before its write.
        info.push_constant('BOOL', 'srgbTarget')
        info.push_constant('BOOL', 'viewportOverlay')
        info.sampler(0, 'FLOAT_2D', 'image')
        self.textures = []
        for lut in desc.get3DTextures():
            n = lut.edgeLen
            values = np.asarray(lut.getValues(), dtype=np.float32).reshape(n, n, n, 3)
            texture = self._texture(values, (n, n, n))
            texture.filter_mode(lut.interpolation != ocio.INTERP_NEAREST)
            texture.extend_mode('EXTEND')
            self.textures.append((lut.samplerName, texture))
            info.sampler(len(self.textures), 'FLOAT_3D', lut.samplerName)
        for lut in desc.getTextures():
            channels = 1 if lut.channel == ocio.GpuShaderDesc.TEXTURE_RED_CHANNEL else 3
            values = np.asarray(lut.getValues(), dtype=np.float32).reshape(lut.height, lut.width, channels)
            texture = self._texture(values, (lut.width, lut.height))
            texture.filter_mode(lut.interpolation != ocio.INTERP_NEAREST)
            texture.extend_mode('EXTEND')
            self.textures.append((lut.samplerName, texture))
            info.sampler(len(self.textures), 'FLOAT_2D', lut.samplerName)
        source = re.sub(r'^\s*uniform\s+sampler\w+\s+\w+\s*;\s*$', '',
                        desc.getShaderText(), flags=re.MULTILINE)
        info.vertex_source('void main(){uv=texCoord;gl_Position=ModelViewProjectionMatrix*vec4(position,0.0,1.0);}')
        info.fragment_source(source + '''
vec4 hdr_picker_srgb_to_framebuffer(vec4 color){
    // Blender 5.2's OCIO viewport compositor merges UI overlays in gamma-2.2
    // linearized display space, then applies pow(1/2.2). The SRGBA overlay
    // attachment is decoded on sampling, so provide that merge-space value.
    if(viewportOverlay)return vec4(pow(max(color.rgb,vec3(0.0)),vec3(2.2)),color.a);
    if(!srgbTarget)return color;
    vec3 c=max(color.rgb,vec3(0.0));
    vec3 linear=mix(c/12.92,pow((c+0.055)/1.055,vec3(2.4)),
                    step(vec3(0.04045),c));
    return vec4(linear,color.a);
}
void main(){
    vec4 sampleColor=texture(image,uv);
    fragColor=hdr_picker_srgb_to_framebuffer(hdr_picker_view(sampleColor));
    fragColor.a=sampleColor.a;
}
''')
        self.shader = gpu.shader.create_from_info(info)

    @staticmethod
    def _texture(values, size):
        import gpu
        rgba = np.ones((*values.shape[:-1], 4), dtype=np.float32)
        if values.shape[-1] == 1:
            rgba[..., :3] = values
        else:
            rgba[..., :3] = values
        return gpu.types.GPUTexture(size, format='RGBA32F',
                                    data=gpu.types.Buffer('FLOAT', rgba.shape, rgba))

    def draw(self, texture, origin, size, *, viewport_overlay=False):
        """Draw into the active pixel-coordinate region without double encoding."""
        import gpu
        from gpu_extras.batch import batch_for_shader
        x, y = origin
        width, height = size
        batch = batch_for_shader(self.shader, 'TRI_FAN', {
            'position': [(x,y), (x+width,y), (x+width,y+height), (x,y+height)],
            'texCoord': [(0,0), (1,0), (1,1), (0,1)],
        })
        self.shader.bind()
        self.shader.uniform_bool('viewportOverlay', viewport_overlay)
        self.shader.uniform_float('ModelViewProjectionMatrix',
                                  gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix())
        self.shader.uniform_sampler('image', texture)
        for name, lut in self.textures:
            self.shader.uniform_sampler(name, lut)
        batch.draw(self.shader)
