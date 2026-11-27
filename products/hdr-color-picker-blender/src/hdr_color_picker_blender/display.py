"""Blender's selected display transform for an ACEScg picker texture.

Raw display encoding follows Blender's bundled OpenColorIO configuration.
Viewport drawing can additionally emulate the selected target display in the
window's extended-sRGB buffer.

All entry points run on Blender's main thread. Instances own only value data
and GPU objects, and never retain a Scene, Brush or other Blender ID.
"""
from dataclasses import dataclass
import copy
import os
from pathlib import Path
import re
import sys

import numpy as np


# Blender's OCIO_matrix.hh uses these matrices to cancel the display
# colorspace's transfer function before applying its emulated gamut limits.
_XYZ_TO_REC709 = np.array(((3.2409699419045217, -1.5373831775700935, -0.49861076029300355),
                          (-0.96924363628087973, 1.8759675015077204, 0.041555057407175626),
                          (0.055630079696993649, -0.20397695888897652, 1.0569715142428788)))
_XYZ_TO_P3 = np.array(((2.690225911625598, -1.0940019373661367, -0.4250823476747525),
                       (-0.82008218427349111, 1.7504809082920574, 0.026601954212205722),
                       (0.03624575465400464, -0.07858083680558868, 0.95874699366098559)))
_XYZ_TO_REC2020 = np.array(((1.716651187971268, -0.35567078377639244, -0.25336628137365991),
                            (-0.66668435183248875, 1.6164812366349386, 0.015768545813911128),
                            (0.01763985744531079, -0.04277061325780853, 0.94210312123547435)))

# OCIO interchange identifiers from the bundled configuration.
_EMULATED_SPACES = {
    'srgb_p3d65_display': (_XYZ_TO_P3, 1.0),
    'g24_rec709_display': (_XYZ_TO_REC709, 1.0),
    'g24_rec2020_display': (_XYZ_TO_REC2020, 1.0),
    'pq_rec2020_display': (_XYZ_TO_REC2020, 100.0),
    'hlg_rec2020_display': (_XYZ_TO_REC2020, 10.0),
}


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
    hdr_buffer: bool
    window_hdr: bool
    view_hdr: bool


def signature(scene, window=None):
    """Capture settings as values; changes invalidate pending presentation."""
    import bpy
    import gpu
    ocio = _ocio()
    config = ocio.GetCurrentConfig()
    view = scene.view_settings
    window = bpy.context.window if window is None else window
    try:
        hdr_buffer = bool(gpu.capabilities.hdr_support_get())
    except (SystemError, RuntimeError):
        # Background-only instances have no GPU drawing context.
        hdr_buffer = False
    window_hdr = bool(getattr(window, 'support_hdr_color', False))
    view_hdr = bool(getattr(view, 'is_hdr', False))
    return ViewIdentity(config.getCacheID(), config.getRoleColorSpace('scene_linear'),
                        scene.display_settings.display_device, view.view_transform,
                        view.look, float(view.exposure), float(view.gamma),
                        scene.display_settings.emulation, bool(view.use_curve_mapping),
                        bool(view.use_white_balance), hdr_buffer, window_hdr, view_hdr)


def _bundled_config():
    import bpy
    path = Path(bpy.utils.resource_path('LOCAL')) / 'datafiles/colormanagement/config.ocio'
    return _ocio().Config.CreateFromFile(str(path))


def _require_bundled_config(config):
    """Reject runtime config replacement as well as an OCIO environment override."""
    bundled = _bundled_config()
    normalized = copy.deepcopy(config)
    # Blender adjusts the scene-linear role and adds HDR display helpers at runtime.
    normalized.setRole('scene_linear', bundled.getRoleColorSpace('scene_linear'))
    for name in ('blender:pq_rec2020_display_203nits', 'blender:hlg_rec2020_display_203nits'):
        if bundled.getColorSpace(name) is None:
            normalized.removeColorSpace(name)
    if normalized.getCacheID() != bundled.getCacheID():
        raise DisplayUnavailable('Picker preview requires Blender\'s bundled OCIO configuration')


def _matrix_transform(ocio, matrix):
    affine = np.eye(4)
    affine[:3, :3] = matrix
    return ocio.MatrixTransform(matrix=affine.ravel().tolist())


def _clamp(ocio, limit):
    return ocio.RangeTransform(minInValue=0.0, minOutValue=0.0,
                               maxInValue=limit, maxOutValue=limit)


def _view_colorspace(config, display, view):
    name = config.getDisplayViewColorSpaceName(display, view)
    if name == '<USE_DISPLAY_NAME>':
        name = display
    return config.getColorSpace(name) if name else None


def _display_is_hdr(config, display):
    for view in config.getViews(display):
        colorspace = _view_colorspace(config, display, view)
        if colorspace is not None and colorspace.getEncoding() in ('hdr-video', 'edr-video'):
            return True
    return False


def _look_view(name):
    return name.split(' - ', 1)[0] if ' - ' in name else ''


def _view_look_family(config, view_name):
    look_views = {_look_view(name) for name in config.getLookNames()}
    if view_name in look_views:
        return view_name
    short_name = view_name.split(' - ', 1)[0]
    return short_name if short_name in look_views else ''


def _look_compatible(config, look_name, view_name):
    look = config.getLook(look_name)
    if look is None:
        raise DisplayUnavailable('The active view look is unavailable')
    return _look_view(look_name) == _view_look_family(config, view_name)


def _gamma_exponent(gamma):
    return float(np.float32(1.0 / max(float(np.finfo(np.float32).eps), gamma)))


def _append_viewport_emulation(group, config, identity, view_space, ocio):
    """Follow Blender's selected-display to window-buffer transform."""
    if view_space.getReferenceSpaceType() != ocio.REFERENCE_SPACE_DISPLAY:
        # Blender clamps Raw and Filmic Log on SDR targets. Raw on an HDR
        # target preserves the encoded values for custom view transforms.
        if not _display_is_hdr(config, identity.display):
            group.appendTransform(_clamp(ocio, 1.0))
        return

    interop = view_space.getInteropID().rsplit(':', 1)[-1]
    if interop == 'srgb_rec709_display':
        group.appendTransform(_clamp(ocio, 1.0))
        return
    if interop not in _EMULATED_SPACES:
        raise DisplayUnavailable('The selected view has an unsupported display encoding')

    matrix, limit = _EMULATED_SPACES[interop]
    xyz_space = config.getRoleColorSpace('cie_xyz_d65_interchange')
    group.appendTransform(ocio.ColorSpaceTransform(src=view_space.getName(), dst=xyz_space))
    group.appendTransform(_matrix_transform(ocio, matrix))
    group.appendTransform(_clamp(ocio, limit))
    if matrix is not _XYZ_TO_REC709:
        group.appendTransform(_matrix_transform(ocio, _XYZ_TO_REC709 @ np.linalg.inv(matrix)))

    # Blender uses signed gamma 2.2 for an HDR view in a Linux HDR buffer.
    # Other display buffers use the signed extended-sRGB transfer function.
    if sys.platform == 'linux' and identity.hdr_buffer and identity.view_hdr:
        encode = ocio.ExponentTransform(value=[2.2, 2.2, 2.2, 1.0])
    else:
        encode = ocio.ExponentWithLinearTransform(gamma=[2.4, 2.4, 2.4, 1.0],
                                                  offset=[0.055, 0.055, 0.055, 0.0])
    encode.setDirection(ocio.TRANSFORM_DIR_INVERSE)
    encode.setNegativeStyle(ocio.NEGATIVE_MIRROR)
    group.appendTransform(encode)


def _processor(identity, *, viewport_overlay=False):
    ocio = _ocio()
    if os.environ.get('OCIO'):
        import bpy
        builtin = Path(bpy.utils.resource_path('LOCAL')) / 'datafiles/colormanagement/config.ocio'
        if Path(os.environ['OCIO']).resolve() != builtin.resolve():
            raise DisplayUnavailable('Picker preview has not validated a custom OCIO configuration')
    if identity.working_space not in ('ACEScg', 'Linear Rec.709'):
        raise DisplayUnavailable('Picker preview requires ACEScg or Linear Rec.709 working space')
    if identity.curves:
        raise DisplayUnavailable('Picker preview does not yet support view curves')
    if identity.white_balance:
        raise DisplayUnavailable('Picker preview does not yet support view white balance')
    if identity.emulation not in ('AUTO', 'OFF'):
        raise DisplayUnavailable('The active display emulation mode is unavailable')
    config = ocio.GetCurrentConfig()
    if config.getCacheID() != identity.config:
        raise DisplayUnavailable('Color configuration changed while preparing the picker')
    _require_bundled_config(config)
    if (identity.display not in config.getDisplays()
            or identity.view not in config.getViews(identity.display)):
        raise DisplayUnavailable('The active display and view combination is unavailable')
    view_space = _view_colorspace(config, identity.display, identity.view)
    if view_space is None:
        raise DisplayUnavailable('The active view has no display colorspace')
    group = ocio.GroupTransform()
    # Data views such as Raw bypass normal colorspace conversion. Convert to
    # the actual working space first, matching the values Blender displays.
    source = identity.working_space
    group.appendTransform(ocio.ColorSpaceTransform(src='ACEScg', dst=source))
    scale = float(np.float32(2.0 ** identity.exposure))
    if scale != 1:
        group.appendTransform(ocio.MatrixTransform(matrix=[
            scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1]))
    use_look = (identity.look not in ('', 'None')
                and _look_compatible(config, identity.look, identity.view))
    if use_look:
        look = config.getLook(identity.look)
        if look is None:
            raise DisplayUnavailable('The active view look is unavailable')
        target = source if view_space.isData() else look.getProcessSpace()
        group.appendTransform(ocio.LookTransform(src=source, dst=target, looks=identity.look))
        source = target
    group.appendTransform(ocio.DisplayViewTransform(
        src=source, display=identity.display, view=identity.view, looksBypass=use_look))
    if viewport_overlay and identity.emulation == 'AUTO':
        _append_viewport_emulation(group, config, identity, view_space, ocio)
    if not viewport_overlay and identity.gamma != 1:
        # OCIO's exponent transform supports exponents up to 100. The viewport
        # path evaluates the full signed Blender gamma directly in its shader.
        exponent = min(100.0, _gamma_exponent(identity.gamma))
        group.appendTransform(ocio.ExponentTransform(value=[exponent] * 3 + [1]))
    try:
        return config.getProcessor(group)
    except Exception as exc:
        raise DisplayUnavailable('The active view cannot process ACEScg picker colors') from exc


class DisplayTransform:
    def __init__(self, scene, window=None):
        self.identity = signature(scene, window)
        self._processors = {False: _processor(self.identity)}
        self._gpu = {}

    def _processor(self, viewport_overlay):
        if viewport_overlay not in self._processors:
            self._processors[viewport_overlay] = _processor(
                self.identity, viewport_overlay=viewport_overlay)
        return self._processors[viewport_overlay]

    def apply(self, rgba, *, viewport_overlay=False):
        """Encode straight RGBA for the selected device or pre-attachment viewport."""
        data = np.array(rgba, dtype=np.float32, order='C', copy=True)
        if data.shape[-1] != 4 or not np.isfinite(data).all():
            raise ValueError('Expected finite RGBA pixels')
        alpha = data[..., 3].copy()
        self._processor(viewport_overlay).getDefaultCPUProcessor().applyRGBA(data.reshape(-1, 4))
        if viewport_overlay and self.identity.gamma != 1:
            rgb = data[..., :3]
            rgb[:] = np.copysign(np.power(np.abs(rgb), _gamma_exponent(self.identity.gamma)), rgb)
        data[..., 3] = alpha
        return data

    def gpu(self, *, viewport_overlay=False):
        """Compile the processor for the selected destination."""
        if viewport_overlay not in self._gpu:
            self._gpu[viewport_overlay] = GPUView(
                self._processor(viewport_overlay),
                _gamma_exponent(self.identity.gamma) if viewport_overlay else None)
        return self._gpu[viewport_overlay]

    def close(self):
        self._gpu.clear()


def processor(scene, window=None):
    return DisplayTransform(scene, window)


class GPUView:
    """Private shader/LUT resources; no global registrations or native IDs."""
    def __init__(self, processor, overlay_exponent):
        import gpu
        self._overlay_exponent = overlay_exponent
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
        info.push_constant('FLOAT', 'overlayExponent')
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
    // Blender's OCIO viewport compositor merges UI overlays in gamma-2.2
    // linearized display space, then applies pow(1/2.2). The SRGBA overlay
    // attachment is decoded on sampling, so provide that merge-space value.
    if(viewportOverlay){
        vec3 exponent=vec3(2.2*overlayExponent);
        return vec4(sign(color.rgb)*pow(abs(color.rgb),exponent),color.a);
    }
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

    def draw(self, texture, origin, size):
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
        self.shader.uniform_bool('viewportOverlay', self._overlay_exponent is not None)
        self.shader.uniform_float('overlayExponent', self._overlay_exponent or 1.0)
        self.shader.uniform_float('ModelViewProjectionMatrix',
                                  gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix())
        self.shader.uniform_sampler('image', texture)
        for name, lut in self.textures:
            self.shader.uniform_sampler(name, lut)
        batch.draw(self.shader)
