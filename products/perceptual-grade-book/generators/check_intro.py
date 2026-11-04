"""Check the MP4's declared interpretation, original speed, color profile and strict failures."""
import argparse
import json
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
from pg_book_generators.intro import build, gamma24_to_srgb, frame_durations
from pg_book_generators.figure_common import digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--recordings',type=Path,required=True)
    parser.add_argument('--built',type=Path,required=True)
    args=parser.parse_args()
    spec=json.loads(args.spec.read_text());manifest=json.loads((args.built/'manifest.json').read_text())
    assert manifest['source']['sha256']==digest(args.recordings/spec['file'])
    assert manifest['spec_sha256']==digest(args.spec)
    assert manifest['color']['input_power_exponent']==2.4 and manifest['color']['output']=='sRGB'
    assert gamma24_to_srgb([0,.5,1]).tolist()==[0,120,255]
    assert sum(frame_durations(90,30))==3000 and len(set(frame_durations(90,30)))==2
    total=0
    with Image.open(args.built/'match-three-images.webp') as image:
        assert image.size==tuple(manifest['source']['size'])
        assert image.info['loop']==0 and image.info.get('icc_profile')
        assert image.n_frames>1
        for i in range(image.n_frames):
            image.seek(i);image.load();total+=image.info['duration']
    assert total==sum(manifest['frame_durations_ms'])
    assert abs(total/1000-manifest['frames']/manifest['source']['fps'])<=.001
    for name,expected in manifest['outputs'].items():assert digest(args.built/name)==expected
    with tempfile.TemporaryDirectory(prefix='pg-intro-test-') as temporary:
        root=Path(temporary);missing=root/'recordings';missing.mkdir()
        try:build(args.spec,missing,root/'out')
        except ValueError as error:assert 'Missing required' in str(error) and not (root/'out').exists()
        else:raise AssertionError('Missing introductory MP4 accepted')
        for key,value in [('transfer','rec709-a'),('range','auto'),('loop',1),('quality',0),('start',-1),('end',-2)]:
            altered={**spec,key:value};path=root/'spec.json';path.write_text(json.dumps(altered))
            try:build(path,args.recordings,root/'out')
            except ValueError:assert not (root/'out').exists()
            else:raise AssertionError('Invalid setting accepted: '+key)
    print('PASS introductory MP4 provenance, Gamma 2.4 conversion, sRGB profile, original speed, infinite loop and missing-input failures')


if __name__=='__main__':main()
