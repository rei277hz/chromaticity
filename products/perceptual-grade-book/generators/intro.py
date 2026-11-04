"""Convert the required Rec.709 / Gamma 2.4 introductory MP4 to looping sRGB WebP."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image
from pg_book_generators.demos import ffmpeg_executable, finite_number, srgb_profile
from pg_book_generators.figure_common import digest, write_json


def gamma24_to_srgb(values):
    linear = np.clip(np.asarray(values, dtype=np.float64), 0, 1) ** 2.4
    encoded = np.where(linear <= .0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - .055)
    return np.rint(np.clip(encoded, 0, 1) * 255).astype(np.uint8)


def frame_durations(count, fps):
    fps = finite_number(fps, 'frame rate')
    if not 0 < fps <= 1000:
        raise ValueError('Frame rate must be positive and representable in WebP milliseconds.')
    boundaries = [round(i * 1000 / fps) for i in range(count+1)]
    return [b-a for a,b in zip(boundaries, boundaries[1:])]


def build(spec_path, recordings, output):
    spec_path, recordings, output = map(Path, (spec_path, recordings, output))
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    expected = {'primaries':'bt709', 'matrix':'bt709', 'transfer':'gamma2.4', 'loop':0}
    for key, value in expected.items():
        if spec.get(key) != value:
            raise ValueError(f'Introduction recording requires {key}={value!r}.')
    if not isinstance(spec.get('lossless'),bool) or not 1 <= finite_number(spec.get('quality'),'quality') <= 100:
        raise ValueError('Specify lossless as a boolean and quality from 1 to 100.')
    if spec.get('range') not in ('full','limited'):
        raise ValueError('Introduction video range must be explicit: full or limited.')
    source = (recordings/spec['file']).resolve()
    if not source.is_relative_to(recordings.resolve()) or source.suffix.lower() != '.mp4':
        raise ValueError('Introduction source must be an MP4 within its recordings directory.')
    if not source.is_file():
        raise ValueError('Missing required introductory MP4: '+spec['file'])
    start = finite_number(spec.get('start',0), 'start')
    end = spec.get('end')
    if start < 0 or (end is not None and finite_number(end,'end') <= start):
        raise ValueError('Trim must start at or after zero and end after start.')
    executable = ffmpeg_executable()
    probe = imageio_ffmpeg.read_frames(str(source), pix_fmt='rgb48le', bpp=6)
    try:
        metadata = next(probe)
    finally:
        probe.close()
    duration = finite_number(metadata['duration'], 'duration')
    stop = duration if end is None else end
    if duration <= 0 or start >= duration or stop > duration + .001 or stop-start > 60:
        raise ValueError('Trim must lie within the video and last at most 60 seconds.')
    width, height = metadata['source_size']
    if width < 1 or height < 1:
        raise ValueError('Invalid introduction frame dimensions.')
    fps = metadata['fps']
    pixel_format = metadata['pix_fmt']
    rgb_input = pixel_format.startswith(('rgb','bgr','gbr','argb','abgr','rgba','bgra'))
    matrix = '' if rgb_input else ':in_color_matrix=bt709'
    # Decode legal-range YCbCr to full-range nonlinear RGB before applying
    # Gamma 2.4. No spatial resize or frame-rate conversion is requested.
    filters = f'scale=iw:ih{matrix}:in_range={spec["range"]}:out_range=full'
    reader = imageio_ffmpeg.read_frames(str(source), pix_fmt='rgb48le', bpp=6,
        output_params=['-ss',str(start),'-t',str(stop-start),'-vf',filters,'-vsync','0'])
    frames = []
    try:
        next(reader)
        for frame in reader:
            values = np.frombuffer(frame,dtype='<u2').reshape(height,width,3)/65535
            frames.append(Image.fromarray(gamma24_to_srgb(values)))
    finally:
        reader.close()
    if not frames:
        raise ValueError('Introduction trim contains no decoded frames.')
    durations = frame_durations(len(frames),fps)
    output.mkdir(parents=True,exist_ok=True)
    profile=srgb_profile()
    frames[0].save(output/'match-three-images.webp',save_all=True,append_images=frames[1:],
                   duration=durations,loop=0,lossless=spec['lossless'],quality=spec['quality'],method=4,icc_profile=profile)
    frames[0].save(output/'match-three-images-still.webp',lossless=True,method=4,icc_profile=profile)
    version=subprocess.run([str(executable),'-version'],capture_output=True,text=True,check=True).stdout.splitlines()[0]
    manifest={
        'schema':1,'invocation':'buck2' if os.environ.get('PG_BUCK_ACTION')=='1' else 'authoring-preview',
        'source':{'file':spec['file'],'sha256':digest(source),'size':[width,height],
                  'fps':fps,'duration_seconds':duration,'pixel_format':pixel_format},
        'settings':spec,'color':{'primaries':'Rec.709','matrix':'RGB identity' if rgb_input else 'BT.709',
                              'input_power_exponent':2.4,'output':'sRGB','icc_profile':True},
        'frames':len(frames),'frame_durations_ms':durations,'loop':0,'ffmpeg':version,
        'spec_sha256':digest(spec_path),'generator_sha256':digest(Path(__file__)),
        'shared_decoder_sha256':digest(Path(__file__).with_name('demos.py')),
        'outputs':{name:digest(output/name) for name in ('match-three-images.webp','match-three-images-still.webp')},
    }
    write_json(output/'manifest.json',manifest)
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--recordings',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    result=build(args.spec,args.recordings,args.output_dir)
    print(f'Built looping introduction: {result["frames"]} frames, original size and speed, Gamma 2.4 to sRGB.')


if __name__=='__main__':main()
