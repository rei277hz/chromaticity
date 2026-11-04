"""Exercise real MOV color conversion, elapsed timing, looping and failure cases."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms
from pg_book_generators.demos import build, decode_clip, ffmpeg_executable


def movie(path, count, offset=0, size=(64,64), yuv=False):
    width,height=size
    samples=[np.full((height,width,3),(35+i*5+offset,90+i,160-i),np.uint8) for i in range(count)]
    args=[str(ffmpeg_executable()),'-hide_banner','-loglevel','error','-y',
          '-f','rawvideo','-pixel_format','rgb24','-video_size',f'{width}x{height}',
          '-framerate','10','-i','-','-an']
    if yuv:
        args += ['-vf','scale=out_color_matrix=bt709:out_range=limited,format=yuv444p10le',
                 '-c:v','prores_ks','-profile:v','4','-color_range','tv',
                 '-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709']
    else:
        args += ['-c:v','qtrle','-pix_fmt','rgb24']
    subprocess.run(args+[str(path)],input=b''.join(x.tobytes() for x in samples),check=True)
    return samples


def expected_srgb(code):
    # Independent scalar reference, including the linear segment near black.
    values=[]
    for v in code:
        linear=(int(v)/255)**1.961
        encoded=linear*12.92 if linear<=.0031308 else 1.055*linear**(1/2.4)-.055
        values.append(round(encoded*255))
    return np.asarray(values)


def reject(spec, root, output, message):
    path=root/'bad.json';path.write_text(json.dumps(spec))
    try:build(path,root,output)
    except ValueError as error:
        assert message in str(error),str(error)
    else:raise AssertionError('Accepted invalid input: '+message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    args=parser.parse_args()
    base=json.loads(args.spec.read_text())
    with tempfile.TemporaryDirectory(prefix='pg-demo-tests-') as temporary:
        root=Path(temporary)
        spec=deepcopy(base);spec['demos']=spec['demos'][:1]
        spec['output'].update(panel_size=64,fps=10,end_hold_ms=700)
        demo=spec['demos'][0]
        for side in ('sdr','hdr'):
            demo[side]['file']=side+'.mov'
        path=root/'spec.json';path.write_text(json.dumps(spec))
        reject(spec,root,root/'missing','Missing required MOV sources: sdr.mov, hdr.mov')
        assert not (root/'missing').exists()
        a=movie(root/'sdr.mov',32)
        b=movie(root/'hdr.mov',40,5)
        demo['sdr'].update(start=.4,end=1.6,range='full')
        demo['hdr'].update(start=.7,end=2.7,range='full')
        path.write_text(json.dumps(spec))
        records=build(path,root,root/'first')
        record=records[0]
        assert not record['dummy_recording']
        assert record['clips']['sdr']['decoded_frames']==12,record
        assert record['clips']['hdr']['decoded_frames']==20,record
        assert record['duration_ms']==2700,record
        with Image.open(root/'first/images'/(demo['name']+'.webp')) as im:
            assert im.info['loop']==0 and 'icc_profile' in im.info
            ImageCms.ImageCmsProfile(__import__('io').BytesIO(im.info['icc_profile']))
            elapsed=0;seen=[]
            for i in range(im.n_frames):
                im.seek(i);im.load()
                l=np.asarray(im.convert('RGB'))[56,32]
                r=np.asarray(im.convert('RGB'))[56,96]
                seen.append((elapsed,l.copy(),r.copy()))
                elapsed+=im.info['duration']
            assert elapsed==2700
            assert np.max(np.abs(seen[0][1].astype(int)-expected_srgb(a[4][0,0])))<=1
            assert np.max(np.abs(seen[0][2].astype(int)-expected_srgb(b[7][0,0])))<=1
            # Shorter side holds, while the longer side keeps moving at its original speed.
            for time,left,right in seen:
                ai=min(round(time/100)+4,15)
                bi=min(round(time/100)+7,26)
                assert np.max(np.abs(left.astype(int)-expected_srgb(a[ai][0,0])))<=1,(time,left)
                assert np.max(np.abs(right.astype(int)-expected_srgb(b[bi][0,0])))<=1,(time,right)
        build(path,root,root/'repeat')
        for name in (demo['name']+'.webp',demo['name']+'-still.webp'):
            assert (root/'first/images'/name).read_bytes()==(root/'repeat/images'/name).read_bytes(),name
        # Real 10-bit limited-range YCbCr input, with explicit Rec.709 decoding.
        yuv=movie(root/'limited.mov',5,yuv=True)
        frames,meta=decode_clip(root,{'file':'limited.mov','start':0,'end':.5,'range':'limited'},spec['output'])
        assert len(frames)==5 and meta['range']=='limited'
        for frame,source in zip(frames,yuv):
            assert np.max(np.abs(np.asarray(frame)[32,32].astype(int)-expected_srgb(source[0,0])))<=2
        (root/'hdr.mov').unlink()
        reject(spec,root,root/'bad-pair','Missing required MOV sources: hdr.mov')
        assert not (root/'bad-pair').exists()
        movie(root/'hdr.mov',40,5)
        for start,end,message in [(-1,None,'nonnegative'),(.4,.4,'after start'),(0,9,'exceeds'),(float('nan'),None,'finite')]:
            bad=deepcopy(spec);bad['demos'][0]['sdr'].update(start=start,end=end)
            reject(bad,root,root/'bad-trim',message)
        bad=deepcopy(spec);bad['demos'][0]['sdr']['file']='../outside.mov'
        reject(bad,root,root/'bad-path','within')
        movie(root/'sdr.mov',10,size=(64,32))
        reject(spec,root,root/'bad-size','square')
        # Dummy status follows bytes, so overwriting a MOV needs no flag edit.
        import hashlib
        movie(root/'sdr.mov',32)
        spec['bundled_dummy']={'sha256':hashlib.sha256((root/'sdr.mov').read_bytes()).hexdigest()}
        path.write_text(json.dumps(spec))
        record=build(path,root,root/'dummy')[0]
        assert record['clips']['sdr']['dummy_recording'] and not record['clips']['hdr']['dummy_recording']
        movie(root/'sdr.mov',32,9)
        record=build(path,root,root/'replaced')[0]
        assert not record['dummy_recording']
        # Missing wheel binary must never probe a host/conda FFmpeg.
        with patch('imageio_ffmpeg.__file__',str(root/'absent-wheel/__init__.py')):
            try:ffmpeg_executable()
            except ValueError as error:assert 'Missing executable' in str(error)
            else:raise AssertionError('Missing pinned FFmpeg was accepted')
    print('PASS RGB and 10-bit YCbCr MOVs, Rec.709-A → sRGB, independent trims, original speed, end holds, ICC, looping, deterministic bytes and invalid inputs')


if __name__=='__main__':main()
