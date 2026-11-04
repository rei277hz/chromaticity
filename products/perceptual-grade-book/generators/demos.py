"""Build paired, looping sRGB WebP demonstrations from Rec.709-A screen MOVs.

Only the binary in the pinned imageio-ffmpeg wheel is used. The media are screen
recordings, including the Blender image and gizmo; HDR masters are not inputs.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess

import imageio_ffmpeg
from imageio_ffmpeg._definitions import FNAME_PER_PLATFORM, get_platform
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFont
from pg_book_generators.figure_common import digest, write_json


INPUT_EXPONENT = 1.961
MAX_SECONDS = 60


def ffmpeg_executable():
    if imageio_ffmpeg.__version__ != '0.6.0':
        raise ValueError('Install the pinned imageio-ffmpeg 0.6.0 wheel.')
    binaries = Path(imageio_ffmpeg.__file__).resolve().parent / 'binaries'
    platform = get_platform()
    if platform not in FNAME_PER_PLATFORM:
        raise ValueError(f'No pinned FFmpeg binary for {platform}.')
    executable = binaries / FNAME_PER_PLATFORM[platform]
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f'Missing executable in the pinned imageio-ffmpeg wheel: {executable}')
    if os.environ.get('IMAGEIO_FFMPEG_EXE', str(executable)) != str(executable):
        raise ValueError('IMAGEIO_FFMPEG_EXE must point to the binary in the pinned wheel.')
    # read_frames otherwise searches conda and PATH when the wheel binary is
    # absent. Select the checked binary explicitly, without probing either.
    os.environ['IMAGEIO_FFMPEG_EXE'] = str(executable)
    return executable


def srgb_profile():
    # LittleCMS stamps profile creation time; normalize it for repeatable outputs.
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    profile[24:36] = bytes.fromhex('07d000010001000000000000')
    profile[84:100] = bytes(16)
    return bytes(profile)


def rec709a_to_srgb(values):
    linear = np.clip(np.asarray(values, dtype=np.float64), 0, 1) ** INPUT_EXPONENT
    encoded = np.where(linear <= .0031308, 12.92 * linear,
                       1.055 * linear ** (1 / 2.4) - .055)
    return np.rint(np.clip(encoded, 0, 1) * 255).astype(np.uint8)


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    return value


def clip_path(root, config):
    name = config['file']
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix.lower() != '.mov':
        raise ValueError(f'Recordings must be MOV files within the recordings directory: {name}')
    return path


def decode_clip(root, config, settings):
    path = clip_path(root, config)
    start = finite_number(config.get('start', 0), 'start')
    end = config.get('end')
    if start < 0:
        raise ValueError(f'{config["file"]}: start must be nonnegative.')
    if end is not None and finite_number(end, 'end') <= start:
        raise ValueError(f'{config["file"]}: end must be after start.')
    source_range = config.get('range', 'auto')
    if source_range not in {'auto', 'full', 'limited'}:
        raise ValueError(f'{config["file"]}: range must be auto, full or limited.')
    # Metadata and decoding are from the same wheel-supplied executable.
    probe = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgb48le', bpp=6)
    try:
        metadata = next(probe)
    finally:
        probe.close()
    width, height = metadata['source_size']
    if width != height:
        raise ValueError(f'{config["file"]}: expected a square image-and-gizmo recording; got {width}×{height}.')
    duration = finite_number(metadata['duration'], 'recording duration')
    if duration <= 0:
        raise ValueError(f'{config["file"]}: recording duration is unavailable.')
    if start >= duration:
        raise ValueError(f'{config["file"]}: start is after the recording.')
    if end is not None and end > duration + .001:
        raise ValueError(f'{config["file"]}: end exceeds the recording duration.')
    stop = end if end is not None else duration
    length = stop - start
    if length > MAX_SECONDS:
        raise ValueError(f'{config["file"]}: trim to at most {MAX_SECONDS} seconds.')
    size, fps = settings['panel_size'], settings['fps']
    range_name = {'auto': 'auto', 'full': 'full', 'limited': 'limited'}[source_range]
    pixel_format = metadata['pix_fmt']
    rgb_input = pixel_format.startswith(('rgb','bgr','gbr','argb','abgr','rgba','bgra'))
    # Assign a YCbCr matrix only to YCbCr samples. Applying it to RGB samples
    # causes swscale to alter their already decoded channel relationships.
    matrix = '' if rgb_input else ':in_color_matrix=bt709'
    filters = f'scale={size}:{size}:flags=lanczos{matrix}:in_range={range_name}:out_range=full'
    reader = imageio_ffmpeg.read_frames(
        str(path), pix_fmt='rgb48le', bpp=6,
        output_params=['-ss', str(start), '-t', str(length), '-vf', filters, '-r', str(fps)])
    frames = []
    try:
        next(reader)
        for raw in reader:
            rgb = np.frombuffer(raw, dtype='<u2').reshape(size, size, 3)
            frames.append(Image.fromarray(rec709a_to_srgb(rgb / 65535)))
            if len(frames) > MAX_SECONDS * fps + 1:
                raise ValueError(f'{config["file"]}: decoded recording exceeds the duration limit.')
    finally:
        reader.close()
    if not frames:
        raise ValueError(f'{config["file"]}: the selected trim contains no video frames.')
    return frames, {
        'file': config['file'], 'sha256': digest(path), 'source_size': [width, height],
        'source_fps': metadata['fps'], 'source_duration_seconds': duration,
        'source_pixel_format':pixel_format, 'decode_matrix':'RGB identity' if rgb_input else 'bt709',
        'start': start, 'end': end, 'range': source_range,
        'decoded_frames': len(frames), 'playback_seconds': len(frames) / fps,
    }


def pair_frame(left, right, settings, dummy_sides=(False, False)):
    size = settings['panel_size']
    header = max(24, size // 14)
    image = Image.new('RGB', (size * 2, size + header), '#343434')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(12, size // 32))
    for i, label in enumerate(('Example A / SDR', 'Example B / HDR')):
        if dummy_sides[i]:
            label += ' / Dummy recording'
        draw.text((i*size+size/2, header/2), label, font=font, fill='white', anchor='mm')
    image.paste(left, (0, header))
    image.paste(right, (size, header))
    return image


def build(spec_file, recordings, output):
    spec = json.loads(spec_file.read_text())
    if spec.get('schema') != 1:
        raise ValueError('Unsupported demonstration schema.')
    interpretation = spec.get('input', {})
    if (interpretation.get('primaries'), interpretation.get('transfer'), interpretation.get('power_exponent')) != ('Rec.709', 'Rec.709-A', INPUT_EXPONENT):
        raise ValueError('Inputs must explicitly declare Rec.709 primaries and Rec.709-A transfer (1.961).')
    settings = spec['output']
    size, fps = settings['panel_size'], settings['fps']
    hold = finite_number(settings['end_hold_ms'], 'end_hold_ms')
    if type(size) is not int or not 64 <= size <= 1024:
        raise ValueError('panel_size must be an integer from 64 to 1024.')
    if type(fps) is not int or not 1 <= fps <= 60:
        raise ValueError('fps must be an integer from 1 to 60.')
    if not 0 <= hold <= 5000 or settings.get('loop') != 0:
        raise ValueError('Use infinite looping (loop = 0) and an end hold from 0 to 5000 ms.')
    if not spec['demos']:
        raise ValueError('At least one demonstration is required.')
    # Check the entire input set before producing any media. A missing pair
    # must fail just as a single missing side does.
    missing = []
    names = set()
    for demo in spec['demos']:
        name = demo['name']
        if name in names or not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in name):
            raise ValueError(f'Invalid or duplicate demonstration name: {name}')
        names.add(name)
        for side in ('sdr', 'hdr'):
            path = clip_path(recordings, demo[side])
            if not path.is_file():
                missing.append(demo[side]['file'])
    if missing:
        raise ValueError('Missing required MOV sources: ' + ', '.join(missing))
    executable = ffmpeg_executable()
    ffmpeg_version = subprocess.run([str(executable), '-version'], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    output.mkdir(parents=True, exist_ok=True)
    images = output / 'images'
    images.mkdir(exist_ok=True)
    profile = srgb_profile()
    records = []
    for demo in spec['demos']:
        name = demo['name']
        left, a = decode_clip(recordings, demo['sdr'], settings)
        right, b = decode_clip(recordings, demo['hdr'], settings)
        dummy_hash = spec.get('bundled_dummy', {}).get('sha256')
        for clip in (a, b):
            clip['dummy_recording'] = clip['sha256'] == dummy_hash
        count = max(len(left), len(right))
        frames = [pair_frame(left[min(i,len(left)-1)], right[min(i,len(right)-1)], settings,
                             (a['dummy_recording'], b['dummy_recording'])) for i in range(count)]
        times = [round((i+1)*1000/fps)-round(i*1000/fps) for i in range(count)]
        times[-1] += round(hold)
        record = {'name': name, 'dummy_recording': a['dummy_recording'] or b['dummy_recording'],
                  'clips': {'sdr': a, 'hdr': b}, 'timeline_frames': count, 'duration_ms': sum(times)}
        frames[0].save(images/(name+'-still.webp'), format='WEBP', lossless=True, method=4, icc_profile=profile)
        frames[0].save(images/(name+'.webp'), format='WEBP', save_all=True, append_images=frames[1:],
                       duration=times, loop=0, lossless=True, method=4, icc_profile=profile)
        records.append(record)
    write_json(output/'manifest.json', {
        'schema':1, 'producer':'paired screen-recording demonstrations',
        'invocation':'buck2' if os.environ.get('PG_BUCK_ACTION') == '1' else 'authoring-preview',
        'spec_sha256':digest(spec_file), 'generator_sha256':digest(Path(__file__)),
        'ffmpeg':ffmpeg_version, 'settings':settings,
        'color':{'input_primaries':'Rec.709 / D65','input_transfer':'Rec.709-A',
                 'input_power_exponent':INPUT_EXPONENT, 'ycbcr_matrix':'bt709',
                 'decode':'16-bit full-range RGB', 'output_transfer':'piecewise sRGB',
                 'output_icc':'sRGB','primary_conversion':'none; Rec.709 and sRGB share primaries'},
        'demos':records,
        'outputs':{p.relative_to(output).as_posix():digest(p) for p in sorted(images.glob('*.webp'))},
    })
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('spec','recordings','output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(argv)
    records = build(args.spec, args.recordings, args.output_dir)
    print(f'Built {len(records)} paired demonstrations ({sum(x["dummy_recording"] for x in records)} using bundled dummy recordings).')


if __name__ == '__main__':
    main()
