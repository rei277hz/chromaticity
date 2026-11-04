"""Package exact-size rendered PNGs; never resample icon artwork."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

from PIL import Image, __version__ as pillow_version

SIZES = tuple((size, size) for size in (16, 32, 48, 64, 256))
SOURCES = {
    f'perceptual-grade-{size}-{variant}.png': (size, variant == 'transparent', variant + ' artwork')
    for size in (16, 32, 48, 64, 180, 192, 256, 512)
    for variant in ('transparent', 'opaque')
}
COPIES = {
    'apple-touch-icon.png': 'perceptual-grade-180-opaque.png',
    'android-192.png': 'perceptual-grade-192-transparent.png',
    'android-512.png': 'perceptual-grade-512-transparent.png',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(icons, output):
    icons, output = Path(icons), Path(output)
    images = {}
    for name, (size, transparent, role) in SOURCES.items():
        path = icons/name
        if not path.is_file():
            raise ValueError(f'Missing required icon PNG: {name}')
        with Image.open(path) as image:
            if image.format != 'PNG' or image.size != (size, size) or getattr(image, 'is_animated', False):
                raise ValueError(f'Icon source must be one static {size} x {size} PNG: {name}')
            image.load()
            rgba = image.convert('RGBA')
        alpha = rgba.getextrema()[3]
        if (transparent and alpha[0] == 255) or (not transparent and alpha != (255, 255)):
            raise ValueError(f'Incorrect transparency for icon role {role}: {name}')
        images[name] = rgba
    output.mkdir(parents=True, exist_ok=True)
    # ICO embeds each supplied PNG byte-for-byte. Pillow's ICO writer can
    # synthesize smaller images, so it is deliberately not used here.
    payloads = [(icons/f'perceptual-grade-{size}-transparent.png').read_bytes() for size, _ in SIZES]
    entries, offset = [], 6 + 16 * len(SIZES)
    for (size, _), payload in zip(SIZES, payloads):
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(payload), offset))
        offset += len(payload)
    icon = output/'favicon.ico'
    icon.write_bytes(struct.pack('<HHH', 0, 1, len(SIZES)) + b''.join(entries) + b''.join(payloads))
    for name, source in COPIES.items():
        shutil.copyfile(icons/source, output/name)
    # A distinct maskable composition: native 256px tile on a 512px canvas.
    # Even its corners lie inside the 40%-radius safe circle. No resize call.
    tile = images['perceptual-grade-256-opaque.png'].convert('RGB')
    maskable = Image.new('RGB', (512, 512), tile.getpixel((0, 0)))
    maskable.paste(tile, (128, 128))
    maskable.save(output/'android-512-maskable.png')
    webmanifest = {
        'id': './', 'name': 'Perceptual Grade', 'short_name': 'Perceptual Grade',
        'start_url': './', 'scope': './', 'display': 'browser',
        'background_color': '#ffffff', 'theme_color': '#343434',
        'icons': [
            {'src': 'android-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': 'android-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': 'android-512-maskable.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    (output/'site.webmanifest').write_text(json.dumps(webmanifest, indent=2)+'\n', encoding='utf-8')
    products = ['favicon.ico', *COPIES, 'android-512-maskable.png', 'site.webmanifest']
    manifest = {
        'schema': 3, 'producer': 'Exact-size PNG packaging and native-pixel maskable composition',
        'invocation': 'buck2' if os.environ.get('PG_BUCK_ACTION') == '1' else 'authoring-preview',
        'sources': {name: {'sha256': digest(icons/name), 'role': spec[2]} for name, spec in SOURCES.items()},
        'generator_sha256': digest(Path(__file__)), 'pillow_version': pillow_version,
        'sizes': SIZES, 'resampling': False,
        'maskable': {'source': 'perceptual-grade-256-opaque.png', 'canvas': [512, 512], 'offset': [128, 128], 'safe_radius': 204.8},
        'outputs': {name: digest(output/name) for name in products},
    }
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    return icon


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--icons', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    build(args.icons, args.output_dir)
    print('Packaged exact-size favicon, Apple and Android icons; maskable artwork uses native pixels.')


if __name__ == '__main__':
    main()
