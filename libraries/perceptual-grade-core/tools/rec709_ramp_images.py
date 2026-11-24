"""Write and verify the linear Rec.709 ramp texture and its sRGB preview."""

from pathlib import Path
import struct
import subprocess

import imageio_ffmpeg
from imageio_ffmpeg._definitions import FNAME_PER_PLATFORM, get_platform
import numpy as np
from PIL import Image, PngImagePlugin

from color_tools.color_core.linear import D65, REC709


EXR_MAGIC = 20000630
EXR_VERSION = 2
CHANNELS = ('B', 'G', 'R')
CHROMATICITIES = (*REC709[0], *REC709[1], *REC709[2], *D65)


def _exr_attribute(name, tag, payload):
    return name.encode('ascii') + b'\0' + tag.encode('ascii') + b'\0' + struct.pack('<I', len(payload)) + payload


def _write_exr(path, rgb):
    height, width, _ = rgb.shape
    window = struct.pack('<4i', 0, 0, width - 1, height - 1)
    channel_spec = struct.pack('<iB3xii', 2, 0, 1, 1)  # FLOAT, pLinear, x/y sampling
    channels = b''.join(name.encode('ascii') + b'\0' + channel_spec for name in CHANNELS) + b'\0'
    attributes = (
        ('channels', 'chlist', channels),
        ('compression', 'compression', b'\0'),
        ('dataWindow', 'box2i', window),
        ('displayWindow', 'box2i', window),
        ('lineOrder', 'lineOrder', b'\0'),
        ('pixelAspectRatio', 'float', struct.pack('<f', 1.)),
        ('screenWindowCenter', 'v2f', struct.pack('<2f', 0., 0.)),
        ('screenWindowWidth', 'float', struct.pack('<f', 1.)),
        ('chromaticities', 'chromaticities', struct.pack('<8f', *CHROMATICITIES)),
    )
    header = (struct.pack('<2I', EXR_MAGIC, EXR_VERSION)
              + b''.join(_exr_attribute(*attribute) for attribute in attributes) + b'\0')
    scanline_bytes = width * 3 * 4
    first_offset = len(header) + 8 * height
    offsets = first_offset + np.arange(height, dtype='<u8') * (scanline_bytes + 8)
    with path.open('wb') as stream:
        stream.write(header)
        stream.write(offsets.astype('<u8', copy=False).tobytes())
        for y, row in enumerate(rgb):
            stream.write(struct.pack('<2i', y, scanline_bytes))
            stream.write(row[:, ::-1].T.astype('<f4', copy=False).tobytes())


def _read_c_string(stream):
    value = bytearray()
    while True:
        char = stream.read(1)
        if char == b'\0':
            return bytes(value)
        if not char:
            raise ValueError('Truncated OpenEXR header')
        value.extend(char)


def _check_exr(path, rgb):
    height, width, _ = rgb.shape
    with path.open('rb') as stream:
        if struct.unpack('<2I', stream.read(8)) != (EXR_MAGIC, EXR_VERSION):
            raise ValueError('Unexpected OpenEXR signature or version')
        attributes = {}
        while name := _read_c_string(stream):
            tag = _read_c_string(stream)
            length, = struct.unpack('<I', stream.read(4))
            attributes[name] = (tag, stream.read(length))
        window = (b'box2i', struct.pack('<4i', 0, 0, width - 1, height - 1))
        if (attributes.get(b'chromaticities') != (b'chromaticities', struct.pack('<8f', *CHROMATICITIES))
                or attributes.get(b'dataWindow') != window or attributes.get(b'displayWindow') != window):
            raise ValueError('OpenEXR readback has different dimensions or chromaticities')

    binaries = Path(imageio_ffmpeg.__file__).resolve().parent / 'binaries'
    ffmpeg = binaries / FNAME_PER_PLATFORM[get_platform()]
    decoded = subprocess.run([
        str(ffmpeg), '-v', 'error', '-nostdin', '-i', str(path), '-frames:v', '1',
        '-pix_fmt', 'gbrpf32le', '-c:v', 'rawvideo', '-threads:v', '1', '-f', 'rawvideo', '-',
    ], capture_output=True)
    if decoded.returncode:
        raise ValueError(f'OpenEXR decode failed: {decoded.stderr.decode(errors="replace")}')
    if len(decoded.stdout) != rgb.size * 4:
        raise ValueError('OpenEXR decoder produced an unexpected number of pixels')
    # FFmpeg stores its three planes in G, B, R order.
    planes = np.frombuffer(decoded.stdout, dtype='<f4').reshape(3, height, width)
    if not np.array_equal(planes[[2, 0, 1]].transpose(1, 2, 0), rgb):
        raise ValueError('OpenEXR decoder changed pixel values or orientation')


def write_preview(path, rgb):
    """Write a tagged sRGB PNG and verify its encoded pixels on readback."""
    linear = rgb.astype(np.float64)
    encoded = np.where(linear <= .0031308, 12.92 * linear,
                       1.055 * linear ** (1 / 2.4) - .055)
    pixels = np.rint(encoded * 255).astype(np.uint8)
    metadata = PngImagePlugin.PngInfo()
    metadata.add(b'sRGB', b'\0')  # Perceptual rendering intent.
    Image.fromarray(pixels).save(path, pnginfo=metadata)
    with Image.open(path) as preview:
        if (preview.mode != 'RGB' or preview.info.get('srgb') != 0
                or not np.array_equal(np.asarray(preview), pixels)):
            raise ValueError('PNG readback changed pixels, orientation, or sRGB metadata')


def write_images(output_dir: Path, linear_rgb: np.ndarray) -> None:
    """Export top-left-origin float32 RGB pixels to EXR and sRGB PNG."""
    if (linear_rgb.ndim != 3 or linear_rgb.shape[-1] != 3 or not linear_rgb.size
            or linear_rgb.dtype != np.float32 or not np.isfinite(linear_rgb).all()
            or np.any((linear_rgb < 0) | (linear_rgb > 1))):
        raise ValueError('Expected a nonempty bounded float32 RGB image')
    output_dir.mkdir(parents=True, exist_ok=True)
    texture = output_dir / 'texture.exr'
    _write_exr(texture, linear_rgb)
    _check_exr(texture, linear_rgb)
    write_preview(output_dir / 'preview.png', linear_rgb)
