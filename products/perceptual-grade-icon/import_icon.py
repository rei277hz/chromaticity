"""Run in Blender's Text Editor to import the icon into a new scene.

Existing scenes and objects are kept. Uses only Blender's bundled Python.
"""
from pathlib import Path
import json
import bpy

ASSET_DIR = None  # Optional: set to the extracted package folder.


def package_dir():
    if ASSET_DIR:
        return Path(ASSET_DIR).resolve()
    if '__file__' in globals():
        return Path(__file__).resolve().parent
    text = getattr(bpy.context.space_data, 'text', None)
    if text and text.filepath:
        return Path(bpy.path.abspath(text.filepath)).resolve().parent
    raise RuntimeError('Set ASSET_DIR to the extracted package folder.')


def run(directory=None):
    directory = Path(directory).resolve() if directory else package_dir()
    manifest = json.loads((directory / 'icon-manifest.json').read_text())
    scene = bpy.data.scenes.new('Perceptual Grade | Three-stage Fan')
    if bpy.context.window:
        bpy.context.window.scene = scene
    previous = set(bpy.data.objects)
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        bpy.ops.wm.usd_import(
            filepath=str(directory / 'perceptual-grade-icon.usd'),
            import_materials=True, import_usd_preview=True,
            import_cameras=True, import_lights=True, set_frame_range=False)
    created = set(bpy.data.objects) - previous
    camera = next(obj for obj in created if obj.type == 'CAMERA')
    # USD orthographic apertures use tenths of a scene unit. Applying the
    # intended Blender scale avoids Blender 5.2's aperture conversion issue.
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = manifest['framing']['ortho_scale']
    scene.camera = camera
    # World nodes and color management do not travel through USD.
    with bpy.data.libraries.load(str(directory / 'perceptual-grade-icon.blend'), link=False) as (source, target):
        target.worlds = [name for name in source.worlds if 'Olive Charcoal' in name]
    scene.world = target.worlds[0]
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 256
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.film_transparent = False
    scene.render.filepath = str(directory / 'perceptual-grade-icon.png')
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    print('Perceptual Grade icon imported into a new scene; press F12 to render.')
    return scene, created


if __name__ == '__main__':
    run()
