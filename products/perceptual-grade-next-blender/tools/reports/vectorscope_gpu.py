"""GPU reducers used by the isolated vectorscope latency report."""

from threading import current_thread, main_thread
import time

import numpy as np


_LOCAL_SIZE = 64
_MAX_PIXELS = 512 * 512
_MAP_SHADER = None
_ACCUMULATION_SHADER = None
_ACCUMULATION_BATCH = None
_CORNERS = np.asarray(
    ((0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)),
    dtype=np.float32,
)


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Vectorscope GPU reduction must run on Blender's main thread")


def _gpu():
    import gpu

    _require_main_thread()
    gpu.init()
    if not gpu.capabilities.compute_shader_support_get():
        raise RuntimeError("Vectorscope GPU reduction requires compute-shader support")
    return gpu


def _map_shader(gpu):
    global _MAP_SHADER
    if _MAP_SHADER is not None:
        return _MAP_SHADER

    info = gpu.types.GPUShaderCreateInfo()
    info.local_group_size(_LOCAL_SIZE, 1, 1)
    info.sampler(0, "FLOAT_2D", "input_pixels")
    info.image(0, "RGBA32F", "FLOAT_2D", "mapped_pixels", qualifiers={"WRITE"})
    for name in ("input_width", "sample_count", "output_size"):
        info.push_constant("INT", name)
    info.push_constant("FLOAT", "chroma_limit")
    for name in ("transform_red", "transform_green", "transform_blue"):
        info.push_constant("VEC3", name)
    info.compute_source(r"""
void main() {
    int id = int(gl_GlobalInvocationID.x);
    if (id >= sample_count) return;

    ivec2 at = ivec2(id % input_width, id / input_width);
    vec4 pixel = texelFetch(input_pixels, at, 0);
    vec3 rgb = vec3(
        dot(transform_red, pixel.rgb),
        dot(transform_green, pixel.rgb),
        dot(transform_blue, pixel.rgb)
    );
    float weight = 0.0;
    vec2 bins = vec2(0.0);
    if (all(not(isnan(rgb))) && all(not(isinf(rgb)))
            && !isnan(pixel.a) && !isinf(pixel.a) && pixel.a > 0.0) {
        vec3 magnitude = abs(rgb);
        vec3 code = sign(rgb) * mix(
            1.099 * pow(magnitude, vec3(0.45)) - 0.099,
            4.5 * magnitude,
            lessThan(magnitude, vec3(0.018))
        );
        float luma = dot(code, vec3(0.2126, 0.7152, 0.0722));
        float cb = (code.b - luma) / 1.8556;
        float cr = (code.r - luma) / 1.5748;
        if (!isnan(cb) && !isinf(cb) && !isnan(cr) && !isinf(cr)
                && abs(cb) <= chroma_limit && abs(cr) <= chroma_limit) {
            vec2 normalized = vec2(cb, cr) / (2.0 * chroma_limit) + 0.5;
            bins = min(floor(normalized * float(output_size)),
                       vec2(output_size - 1));
            weight = clamp(pixel.a, 0.0, 1.0);
        }
    }
    imageStore(mapped_pixels, at, vec4(bins, weight, 1.0));
}
""")
    _MAP_SHADER = gpu.shader.create_from_info(info)
    return _MAP_SHADER


def _accumulation_shader(gpu):
    global _ACCUMULATION_SHADER, _ACCUMULATION_BATCH
    if _ACCUMULATION_SHADER is not None:
        return _ACCUMULATION_SHADER, _ACCUMULATION_BATCH

    from gpu_extras.batch import batch_for_shader

    interface = gpu.types.GPUStageInterfaceInfo("pg_vectorscope_accumulation")
    interface.flat("FLOAT", "sample_weight")
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, "VEC2", "corner")
    info.vertex_out(interface)
    info.sampler(0, "FLOAT_2D", "mapped_pixels")
    info.push_constant("INT", "input_width")
    info.push_constant("INT", "sample_count")
    info.push_constant("FLOAT", "target_size")
    info.fragment_out(0, "VEC4", "fragment_color")
    info.vertex_source(r"""
void main() {
    int id = gpu_InstanceIndex;
    ivec2 at = ivec2(id % input_width, id / input_width);
    vec4 mapped = texelFetch(mapped_pixels, at, 0);
    sample_weight = mapped.z;
    if (id >= sample_count || !(sample_weight > 0.0)) {
        gl_Position = vec4(-2.0, -2.0, 0.0, 1.0);
        return;
    }
    vec2 cell = floor(mapped.xy + vec2(0.5));
    gl_Position = vec4(2.0 * (cell + corner) / target_size - 1.0,
                       0.0, 1.0);
}
""")
    info.fragment_source(r"""
void main() {
    fragment_color = vec4(sample_weight, 0.0, 0.0, 1.0);
}
""")
    _ACCUMULATION_SHADER = gpu.shader.create_from_info(info)
    _ACCUMULATION_BATCH = batch_for_shader(
        _ACCUMULATION_SHADER, "TRIS", {"corner": _CORNERS},
    )
    return _ACCUMULATION_SHADER, _ACCUMULATION_BATCH


def _texture(gpu, pixels, pixel_format):
    pixels = np.ascontiguousarray(pixels, dtype=np.float32)
    height, width, channels = pixels.shape
    if channels != 4:
        raise ValueError("Vectorscope GPU textures require RGBA pixels")
    return gpu.types.GPUTexture(
        (width, height), format=pixel_format,
        data=gpu.types.Buffer("FLOAT", pixels.shape, pixels),
    )


def _validate_mapped(mapped_rgba):
    pixels = np.asarray(mapped_rgba, dtype=np.float32)
    if (pixels.ndim != 3 or pixels.shape[-1] != 4
            or min(pixels.shape[:2]) < 1 or pixels.shape[0] * pixels.shape[1] > _MAX_PIXELS):
        raise ValueError("Mapped vectorscope samples must be bounded nonempty RGBA pixels")
    if not np.isfinite(pixels).all():
        raise ValueError("Mapped vectorscope samples must be finite")
    bins = pixels[..., :2]
    if np.any(bins != np.floor(bins)):
        raise ValueError("Mapped vectorscope bin coordinates must be integers")
    if np.any(pixels[..., 2] < 0.0) or np.any(pixels[..., 2] > 1.0):
        raise ValueError("Mapped vectorscope sample weights must be between zero and one")
    return np.ascontiguousarray(pixels)


def _restore_gpu_state(gpu, saved):
    blend, viewport, depth, scissor = saved
    gpu.state.blend_set(blend)
    gpu.state.viewport_set(*viewport)
    gpu.state.depth_test_set(depth)
    gpu.state.scissor_set(*scissor)


class GPUHistogram:
    """Accumulate mapped (Cb bin, Cr bin, alpha weight, unused) samples."""

    def __init__(self, *, size=144, limit=0.65):
        if type(size) is not int or size < 1:
            raise ValueError("Vectorscope histogram size must be a positive integer")
        if not np.isfinite(limit) or limit <= 0.0:
            raise ValueError("Vectorscope chroma limit must be finite and positive")
        self.size = size
        self.limit = float(limit)

    def accumulate(self, mapped_rgba):
        histogram, _timings = self.accumulate_timed(mapped_rgba)
        return histogram

    def accumulate_timed(self, mapped_rgba):
        """Return raw alpha-weighted bins and upload, accumulation, readback times."""
        _require_main_thread()
        pixels = _validate_mapped(mapped_rgba)
        height, width = pixels.shape[:2]
        gpu = _gpu()
        upload_started = time.perf_counter()
        mapped_texture = _texture(gpu, pixels, "RGBA32F")
        upload_ms = (time.perf_counter() - upload_started) * 1000.0
        return self._accumulate_texture(gpu, mapped_texture, width, height,
                                        upload_ms=upload_ms)

    def _accumulate_texture(self, gpu, mapped_texture, width, height, *, upload_ms):
        shader, batch = _accumulation_shader(gpu)
        target = gpu.types.GPUTexture((self.size, self.size), format="R32F")
        framebuffer = gpu.types.GPUFrameBuffer(color_slots=(target,))
        saved = (
            gpu.state.blend_get(), gpu.state.viewport_get(),
            gpu.state.depth_test_get(), gpu.state.scissor_get(),
        )
        accumulation_started = time.perf_counter()
        try:
            with framebuffer.bind():
                gpu.state.viewport_set(0, 0, self.size, self.size)
                gpu.state.scissor_set(0, 0, self.size, self.size)
                gpu.state.depth_test_set("NONE")
                framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0))
                gpu.state.blend_set("ADDITIVE")
                shader.bind()
                shader.uniform_sampler("mapped_pixels", mapped_texture)
                shader.uniform_int("input_width", width)
                shader.uniform_int("sample_count", width * height)
                shader.uniform_float("target_size", float(self.size))
                if width * height:
                    batch.draw_instanced(shader, instance_count=width * height)
            accumulation_ms = (time.perf_counter() - accumulation_started) * 1000.0
            readback_started = time.perf_counter()
            histogram = np.asarray(target.read(), dtype=np.float32).reshape(self.size, self.size)
            readback_ms = (time.perf_counter() - readback_started) * 1000.0
        finally:
            _restore_gpu_state(gpu, saved)
        if not np.isfinite(histogram).all():
            raise ArithmeticError("Vectorscope GPU histogram returned nonfinite bins")
        return histogram, {
            "upload_ms": upload_ms,
            "accumulation_ms": accumulation_ms,
            "readback_ms": readback_ms,
        }


def _map_pixels(rgba, matrix_to_rec709, *, size, limit):
    _require_main_thread()
    values = np.asarray(rgba, dtype=np.float32)
    matrix = np.asarray(matrix_to_rec709, dtype=np.float32)
    if (values.ndim != 3 or values.shape[-1] != 4
            or min(values.shape[:2]) < 1 or values.shape[0] * values.shape[1] > _MAX_PIXELS):
        raise ValueError("Vectorscope input must be bounded nonempty RGBA pixels")
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("Vectorscope RGB transform must be a finite 3 by 3 matrix")
    height, width = values.shape[:2]
    gpu = _gpu()
    upload_started = time.perf_counter()
    source_texture = _texture(gpu, np.ascontiguousarray(values), "RGBA32F")
    upload_ms = (time.perf_counter() - upload_started) * 1000.0
    mapped_texture = gpu.types.GPUTexture((width, height), format="RGBA32F")
    shader = _map_shader(gpu)
    shader.bind()
    shader.uniform_sampler("input_pixels", source_texture)
    shader.uniform_int("input_width", width)
    shader.uniform_int("sample_count", width * height)
    shader.uniform_int("output_size", size)
    shader.uniform_float("chroma_limit", float(limit))
    for name, row in zip(("transform_red", "transform_green", "transform_blue"), matrix):
        shader.uniform_float(name, row)
    shader.image("mapped_pixels", mapped_texture)
    mapping_started = time.perf_counter()
    gpu.compute.dispatch(shader, (width * height + _LOCAL_SIZE - 1) // _LOCAL_SIZE, 1, 1)
    mapping_ms = (time.perf_counter() - mapping_started) * 1000.0
    return gpu, mapped_texture, width, height, upload_ms, mapping_ms


def gpu_histogram(rgba, matrix_to_rec709, *, size=144, limit=0.65):
    """Map captured pixels and accumulate raw float bins on Blender's GPU."""
    reducer = GPUHistogram(size=size, limit=limit)
    gpu, mapped_texture, width, height, upload_ms, mapping_ms = _map_pixels(
        rgba, matrix_to_rec709, size=size, limit=limit,
    )
    histogram, timings = reducer._accumulate_texture(
        gpu, mapped_texture, width, height, upload_ms=0.0,
    )
    timings["upload_ms"] += upload_ms
    timings["mapping_ms"] = mapping_ms
    return histogram, timings


__all__ = ("GPUHistogram", "gpu_histogram")
