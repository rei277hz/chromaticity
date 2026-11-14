"""Build and render the Perceptual Grade icon package inside Blender.

This is intentionally a Blender-native script.  It has no dependency on the
checked-in reference renders: the compact JSON config is the authored input,
and every scene, texture, render, and report is derived in one action.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import struct
import sys
import zlib
from pathlib import Path
from typing import Iterable

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    # Blender keeps its own options in sys.argv.  The arguments after `--`
    # are the generator's contract (Buck appends --output-dir there).
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    return parser.parse_args(argv)


def load_model(path: Path):
    spec = importlib.util.spec_from_file_location("perceptual_grade_modcam16", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load modCAM16 model from {path}")
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    return model


def read_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("sizes") != [16, 32, 48, 64, 180, 192, 256, 512]:
        raise ValueError("icon sizes must remain the published set")
    if config.get("blender_version") != "5.3.0" or config.get("cycles_samples") != 256:
        raise ValueError("canonical icon generation requires Blender 5.3.0 and 256 Cycles samples")
    return config


def reset_blender() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def look_at(obj: bpy.types.Object, target: Iterable[float]) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def background_linear(config: dict) -> tuple[float, float, float, float]:
    encoded = config["background_srgb_hex"].removeprefix("#")
    if len(encoded) != 6:
        raise ValueError("background_srgb_hex must be a six-digit RGB color")
    channels = [int(encoded[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    return (*[srgb_to_linear(channel) for channel in channels], 1.0)


def appearance_to_linear(model, lightness, a, b):
    return model.cam16_to_linear(100 * lightness, 100 * a, 100 * b)


def max_chroma(model, lightness, hue, iterations=25):
    import numpy as np

    lightness, hue = np.broadcast_arrays(lightness, hue)
    lo = np.zeros_like(lightness, dtype=float)
    hi = np.full_like(lightness, 1.50, dtype=float)
    ca, cb = np.cos(hue), np.sin(hue)
    for _ in range(iterations):
        mid = (lo + hi) * 0.5
        rgb = appearance_to_linear(model, lightness, mid * ca, mid * cb)
        valid = np.all((rgb >= -1e-9) & (rgb <= 1.0 + 1e-9), axis=-1)
        lo = np.where(valid, mid, lo)
        hi = np.where(valid, hi, mid)
    return lo


def find_cusp(model, hue):
    import numpy as np

    hue = np.asarray(hue)
    sample_lightness = np.linspace(0.001, 0.999, 257)
    chroma = max_chroma(model, sample_lightness[:, None], hue[None, :], 20)
    index = chroma.argmax(axis=0)
    lo = sample_lightness[np.maximum(index - 1, 0)]
    hi = sample_lightness[np.minimum(index + 1, len(sample_lightness) - 1)]
    for _ in range(23):
        lightness1 = (2 * lo + hi) / 3
        lightness2 = (lo + 2 * hi) / 3
        chroma1 = max_chroma(model, lightness1, hue, 22)
        chroma2 = max_chroma(model, lightness2, hue, 22)
        go_right = chroma1 < chroma2
        lo = np.where(go_right, lightness1, lo)
        hi = np.where(go_right, hi, lightness2)
    lightness = (lo + hi) * 0.5
    return lightness, max_chroma(model, lightness, hue)


def color_field(model, radius, hue, cusp_lightness, cusp_chroma, neutral_lightness):
    import numpy as np

    q = np.asarray(radius) ** 1.45
    lightness = neutral_lightness + (cusp_lightness - neutral_lightness) * q
    chroma = cusp_chroma * 0.994 * q
    linear = appearance_to_linear(model, lightness, chroma * np.cos(hue), chroma * np.sin(hue))
    outside = np.any((linear < -2e-7) | (linear > 1 + 2e-7), axis=-1)
    if outside.any():
        chroma = np.minimum(chroma, max_chroma(model, lightness, hue, 23) * 0.997)
        linear = appearance_to_linear(model, lightness, chroma * np.cos(hue), chroma * np.sin(hue))
    linear = np.clip(linear, 0, 1)
    return np.where(linear <= 0.0031308, linear * 12.92,
                    1.055 * linear ** (1 / 2.4) - 0.055)


def make_shell_mesh(name: str, config: dict, model):
    import numpy as np

    shell = config["shell"]
    hues = int(shell["hue_segments"])
    radial = int(shell["radial_segments"])
    bevel = int(shell["bevel_segments"])
    thickness = float(shell["thickness"])
    shoulder = float(shell["shoulder_radius"])
    form_scale = float(shell["form_scale"])
    rotation = math.radians(float(shell["rotation_degrees"]))
    neutral = float(model.linear_to_cam16(np.array([0.30, 0.30, 0.30]))[0] / 100)
    hue = np.arange(hues) * (2 * np.pi / hues)
    cusp_lightness, cusp_chroma = find_cusp(model, hue)
    frequency = np.fft.fftfreq(hues, d=1 / hues)
    smooth_lightness = np.sqrt(cusp_lightness ** 2 + 0.66 * cusp_chroma)
    smooth_lightness = np.fft.ifft(np.fft.fft(smooth_lightness) * np.exp(-0.5 * (0.15 * frequency) ** 2)).real
    smooth_chroma = 0.84 * np.fft.ifft(np.fft.fft(cusp_chroma) * np.exp(-0.5 * (0.13 * frequency) ** 2)).real + 0.16 * np.mean(cusp_chroma)

    points: list[list[float]] = []
    faces: list[list[int]] = []
    vertex_uvs: list[tuple[float, float]] = []
    face_uvs: list[tuple[float, float]] = []
    def add_center(z):
        index = len(points)
        points.append([0.0, 0.0, 0.09 + z])
        vertex_uvs.append((0.5, 0.0))
        return index
    def add_ring(radius, z):
        indices = list(range(len(points), len(points) + hues))
        fraction = np.arange(hues) / hues
        angle = hue + rotation
        q = radius ** 1.08
        outline = form_scale * smooth_chroma * q
        bend = radius ** 2.2
        height = (0.09 + 0.84 * (smooth_lightness - neutral) * bend
                  + 0.255 * radius ** 2 + 0.022 * np.sin(2 * hue + 0.4) * bend + z)
        points.extend(np.stack((outline * np.cos(angle), outline * np.sin(angle), height), axis=-1).tolist())
        vertex_uvs.extend((float(index / hues), float(radius)) for index in range(hues))
        return indices
    def add_face(ids, face_uv):
        faces.append(ids)
        face_uvs.extend(face_uv)
    def join(inner, outer, inner_radius, outer_radius, reverse=False):
        for index in range(hues):
            next_index = (index + 1) % hues
            ids = [inner[index], outer[index], outer[next_index], inner[next_index]]
            face_uv = [(index / hues, inner_radius), (index / hues, outer_radius),
                       ((index + 1) / hues, outer_radius), ((index + 1) / hues, inner_radius)]
            if reverse:
                ids.reverse()
                face_uv.reverse()
            add_face([ids[0], ids[1], ids[2]], [face_uv[0], face_uv[1], face_uv[2]])
            add_face([ids[0], ids[2], ids[3]], [face_uv[0], face_uv[2], face_uv[3]])

    radius_values = np.linspace(0, shoulder, radial + 1)[1:]
    top_center = add_center(thickness / 2)
    top = [add_ring(radius, thickness / 2) for radius in radius_values]
    for index in range(hues):
        next_index = (index + 1) % hues
        add_face([top_center, top[0][index], top[0][next_index]],
                 [((index + 0.5) / hues, 0), (index / hues, radius_values[0]),
                  ((index + 1) / hues, radius_values[0])])
    for index in range(radial - 1):
        join(top[index], top[index + 1], radius_values[index], radius_values[index + 1])

    previous, previous_radius = top[-1], shoulder
    for bevel_index in range(1, bevel + 1):
        angle = np.pi * bevel_index / bevel
        radius = shoulder + (1 - shoulder) * np.sin(angle)
        z = thickness / 2 * np.cos(angle)
        current = add_ring(radius, z)
        join(previous, current, previous_radius, radius)
        previous, previous_radius = current, radius
    bottom_outer = previous
    bottom_center = add_center(-thickness / 2)
    bottom = [add_ring(radius, -thickness / 2) for radius in radius_values[:-1]] + [bottom_outer]
    for index in range(hues):
        next_index = (index + 1) % hues
        add_face([bottom_center, bottom[0][next_index], bottom[0][index]],
                 [((index + 0.5) / hues, 0), ((index + 1) / hues, radius_values[0]),
                  (index / hues, radius_values[0])])
    for index in range(radial - 1):
        join(bottom[index], bottom[index + 1], radius_values[index], radius_values[index + 1], True)

    vertices = np.asarray(points, dtype=np.float32)
    indices = np.asarray(faces, dtype=np.int32)
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata(vertices.tolist(), [], indices.tolist())
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    uv_layer = mesh.uv_layers.new(name="st")
    for loop_index, uv in enumerate(face_uvs):
        uv_layer.data[loop_index].uv = uv
    return mesh


def write_image(image: bpy.types.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.filepath_raw = str(path)
    image.save()


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def write_rgb16_png(path: Path, rgb) -> None:
    import numpy as np

    height, width, channels = rgb.shape
    if channels != 3:
        raise ValueError("16-bit texture writer expects RGB pixels")
    rows = np.round(np.clip(rgb, 0.0, 1.0) * 65535).astype(">u2")
    raw = b"".join(b"\0" + rows[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 16, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header)
                     + _png_chunk(b"IDAT", zlib.compress(raw, 9))
                     + _png_chunk(b"IEND", b""))


def load_texture(name: str, path: Path, output: Path) -> bpy.types.Image:
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name = name
    image.colorspace_settings.name = "sRGB"
    image.filepath = bpy.path.relpath(str(path), start=str(output))
    return image


def make_textures(output: Path, config: dict, model) -> tuple[bpy.types.Image, bpy.types.Image]:
    import numpy as np

    size = int(config["texture_size"])
    hue = (np.arange(size, dtype=float) + 0.5) * (2 * np.pi / size)
    cusp_lightness, cusp_chroma = find_cusp(model, hue)
    neutral = float(model.linear_to_cam16(np.array([0.30, 0.30, 0.30]))[0] / 100)
    spectral = np.empty((size, size, 3), dtype=np.float32)
    for start in range(0, size, 64):
        rows = np.arange(start, min(start + 64, size), dtype=float)
        radius = (1 - (rows + 0.5) / size)[:, None]
        spectral[start : start + len(rows)] = color_field(
            model, radius, hue[None, :], cusp_lightness[None, :],
            cusp_chroma[None, :], neutral,
        )
    # Tone is derived from the spectral layer's linear Rec.709 luminance.  It
    # is encoded as neutral sRGB, so lighting remains a Blender concern.
    linear = np.where(spectral <= 0.04045, spectral / 12.92,
                     ((spectral + 0.055) / 1.055) ** 2.4)
    luminance = np.sum(linear * np.array([0.2126, 0.7152, 0.0722]), axis=-1)
    tone_linear = np.repeat(luminance[:, :, None], 3, axis=-1)
    tone = np.where(tone_linear <= 0.0031308, tone_linear * 12.92,
                    1.055 * tone_linear ** (1 / 2.4) - 0.055).astype(np.float32)
    spectral_path = output / "textures" / "spectral-basecolor.png"
    tone_path = output / "textures" / "tone-basecolor.png"
    write_rgb16_png(spectral_path, spectral)
    write_rgb16_png(tone_path, tone)
    spectral_image = load_texture("Spectral Base Color", spectral_path, output)
    tone_image = load_texture("Tone Base Color", tone_path, output)
    return spectral_image, tone_image


def make_material(name: str, image: bpy.types.Image | None, color: tuple[float, float, float, float]):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.72
    shader.inputs["Metallic"].default_value = 0.0
    if image is None:
        shader.inputs["Base Color"].default_value = color
    else:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Linear"
        links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def make_scene(output: Path, config: dict, model) -> bpy.types.Scene:
    scene = bpy.data.scenes.new("Perceptual Grade | Three-stage Fan")
    bpy.context.window.scene = scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = int(config["cycles_samples"])
    scene.cycles.seed = int(config["cycles_seed"])
    scene.cycles.use_animated_seed = False
    scene.cycles.use_denoising = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("Olive Charcoal")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = background_linear(config)
    background.inputs["Strength"].default_value = 0.35

    spectral_image, tone_image = make_textures(output, config, model)
    materials = [
        make_material("Correction Neutral", None, (0.32, 0.32, 0.32, 1.0)),
        make_material("Tone Neutral Lightness", tone_image, (0.4, 0.4, 0.4, 1.0)),
        make_material("Color modCAM16 Spectrum", spectral_image, (0.4, 0.4, 0.4, 1.0)),
    ]
    mesh = make_shell_mesh("Spectral Shell", config, model)
    import numpy as np
    np.savez(
        output / "model-mesh.npz",
        vertices=np.asarray([tuple(vertex.co) for vertex in mesh.vertices], dtype=np.float32),
        faces=np.asarray([tuple(polygon.vertices) for polygon in mesh.polygons], dtype=np.int32),
        face_uvs=np.asarray([tuple(loop.uv) for loop in mesh.uv_layers.active.data], dtype=np.float32),
    )
    materials_by_kind = {"neutral": materials[0], "tone": materials[1], "spectral": materials[2]}
    for index, stage in enumerate(config["stages"]):
        label = stage["name"]
        location = stage["offset"]
        obj = bpy.data.objects.new(label, mesh.copy() if index else mesh)
        scene.collection.objects.link(obj)
        obj.location = location
        obj.data.materials.append(materials_by_kind[stage["material"]])

    camera_data = bpy.data.cameras.new("Icon Camera")
    camera = bpy.data.objects.new("Icon Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = tuple(config["camera"]["location"])
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = float(config["camera"]["ortho_scale"])
    look_at(camera, config["camera"]["target"])
    scene.camera = camera

    for light_config in config["lights"]:
        name = light_config["name"]
        location = light_config["location"]
        energy = light_config["power"]
        size = light_config["size"]
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.shape, data.size = energy, "DISK", size
        light = bpy.data.objects.new(name, data)
        scene.collection.objects.link(light)
        light.location = location
        look_at(light, (0.0, 0.0, 0.0))

    scene.render.resolution_percentage = 100
    return scene


def write_usda(output: Path, scene: bpy.types.Scene) -> None:
    content_path = output / "perceptual-grade-icon-content.usd"
    export = bpy.ops.wm.usd_export
    if not hasattr(export, "get_rna_type"):
        raise RuntimeError("This Blender build does not expose the USD exporter")
    supported = {item.identifier for item in export.get_rna_type().properties}
    options = {
        "filepath": str(content_path),
        "export_animation": False,
        "export_materials": True,
        "export_cameras": True,
        "export_lights": True,
        "export_textures": True,
        "relative_paths": True,
        "selected_objects_only": False,
        "visible_objects_only": True,
        "generate_preview_surface": True,
    }
    result = export(**{key: value for key, value in options.items() if key in supported})
    if "FINISHED" not in result or not content_path.is_file():
        raise RuntimeError("Blender failed to export the icon USD content layer")
    entry = """#usda 1.0
(
    defaultPrim = \"PerceptualGrade\"
    subLayers = [@perceptual-grade-icon-content.usd@]
    upAxis = \"Z\"
)

def Xform \"PerceptualGrade\" (
    customData = { string appearanceModel = \"Perceptual Grade 1.11.10 modCAM16\" }
) {}
"""
    (output / "perceptual-grade-icon.usd").write_text(entry, encoding="utf-8")


def render_one(scene: bpy.types.Scene, output: Path, size: int, transparent: bool) -> str:
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = transparent
    filename = f"perceptual-grade-{size}-{'transparent' if transparent else 'opaque'}.png"
    scene.render.filepath = str(output / filename)
    bpy.ops.render.render(write_still=True)
    return filename


def render_icons(scene: bpy.types.Scene, output: Path, sizes: list[int]) -> list[str]:
    names: list[str] = []
    for size in sizes:
        for variant, transparent in (("opaque", False), ("transparent", True)):
            names.append(render_one(scene, output, size, transparent))
    import shutil

    shutil.copyfile(output / "perceptual-grade-256-opaque.png", output / "perceptual-grade-icon.png")
    render_one(scene, output, 1024, False)
    shutil.copyfile(output / "perceptual-grade-1024-opaque.png", output / "perceptual-grade-icon-preview.png")
    (output / "perceptual-grade-1024-opaque.png").unlink()
    return names


def write_reports(output: Path, config_path: Path, model_path: Path, config: dict, filenames: list[str]) -> None:
    config_bytes = config_path.read_bytes()
    model_bytes = model_path.read_bytes()
    generated = filenames + [
        "perceptual-grade-icon.png",
        "perceptual-grade-icon-preview.png",
        "perceptual-grade-icon.blend",
        "perceptual-grade-icon.usd",
        "perceptual-grade-icon-content.usd",
        "model-mesh.npz",
        "textures/spectral-basecolor.png",
        "textures/tone-basecolor.png",
    ]
    provenance = {
        "generator": "source/generate_icon.py",
        "config": "source/icon_config.json",
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "model": "source/modcam16.py",
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "blender": bpy.app.version_string,
        "render_engine": "CYCLES",
        "device": "CPU",
        "cycles_samples": config["cycles_samples"],
        "cycles_seed": config["cycles_seed"],
        "use_animated_seed": False,
        "derived_outputs": generated,
        "output_sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in generated
        },
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "title": config["title"],
        "sizes": config["sizes"],
        "variants": ["opaque", "transparent"],
        "files": filenames,
        "preview": "perceptual-grade-icon-preview.png",
        "scene": "perceptual-grade-icon.blend",
        "usd": "perceptual-grade-icon.usd",
        "content_layer": "perceptual-grade-icon-content.usd",
        "framing": {"ortho_scale": config["camera"]["ortho_scale"]},
        "textures": ["textures/spectral-basecolor.png", "textures/tone-basecolor.png"],
    }
    (output / "icon-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validation = {
        "render_engine": "CYCLES",
        "device": "CPU",
        "blender": bpy.app.version_string,
        "cycles_samples": config["cycles_samples"],
        "cycles_seed": config["cycles_seed"],
        "use_animated_seed": False,
        "sizes": config["sizes"],
        "variants": ["opaque", "transparent"],
        "outputs": len(filenames),
        "all_outputs_exist": all((output / name).is_file() for name in filenames),
        "transparent_alpha": "film_transparent",
        "scene_saved": (output / "perceptual-grade-icon.blend").is_file(),
        "usd_saved": (output / "perceptual-grade-icon.usd").is_file(),
        "content_usd_saved": (output / "perceptual-grade-icon-content.usd").is_file(),
        "mesh_saved": (output / "model-mesh.npz").is_file(),
        "fixed_seed": config["cycles_seed"],
        "use_animated_seed": False,
    }
    (output / "validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = read_config(args.config)
    model = load_model(args.model)
    reset_blender()
    if bpy.app.version != (5, 3, 0):
        raise RuntimeError(f"icon generation requires Blender 5.3.0, got {bpy.app.version_string}")
    scene = make_scene(output, config, model)
    filenames = render_icons(scene, output, config["sizes"])
    # Keep the editable scene at the canonical inspection frame after the
    # final 1024px preview render.
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.film_transparent = False
    scene.render.filepath = str(output / "perceptual-grade-icon.png")
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "perceptual-grade-icon.blend"))
    write_usda(output, scene)
    write_reports(output, args.config, args.model, config, filenames)


if __name__ == "__main__":
    main()
