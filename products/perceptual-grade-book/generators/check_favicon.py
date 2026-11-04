"""Verify exact supplied PNG payloads and a separate, unscaled maskable composition."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile
from unittest.mock import patch
from PIL import Image, UnidentifiedImageError
from pg_book_generators.favicon import build, digest, SIZES, SOURCES, COPIES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--icons',type=Path,required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='pg-icon-test-') as temporary:
        root=Path(temporary);sources=root/'sources';shutil.copytree(args.icons,sources,copy_function=shutil.copyfile)
        # NativeLink inputs can be read-only; these are private mutable fixtures.
        for directory in [sources, *(p for p in sources.rglob('*') if p.is_dir())]:
            directory.chmod(directory.stat().st_mode | 0o700)
        with patch.object(Image.Image,'resize',side_effect=AssertionError('Icon resampling is forbidden')):
            original=build(sources,root/'original')
        data=original.read_bytes()
        assert struct.unpack('<HHH',data[:6])==(0,1,len(SIZES))
        with Image.open(original) as icon:
            assert icon.ico.sizes()==set(SIZES)
            for i,size in enumerate(SIZES):
                fields=struct.unpack('<BBBBHHII',data[6+i*16:22+i*16]);length,offset=fields[-2:]
                source=sources/f'perceptual-grade-{size[0]}-transparent.png'
                assert data[offset:offset+length]==source.read_bytes()
                with Image.open(source) as png:
                    assert icon.ico.getimage(size).convert('RGBA').tobytes()==png.convert('RGBA').tobytes()
        for target,source in COPIES.items():
            assert (root/'original'/target).read_bytes()==(sources/source).read_bytes()
        with Image.open(root/'original/android-512-maskable.png') as tile, Image.open(sources/'perceptual-grade-256-opaque.png') as source:
            assert tile.size==(512,512) and tile.mode=='RGB'
            assert tile.crop((128,128,384,384)).tobytes()==source.convert('RGB').tobytes()
            assert 2*128**2 < (512*.4)**2
            assert tile.getpixel((0,0))==source.getpixel((0,0))
        manifest=json.loads((root/'original/site.webmanifest').read_text())
        assert [x['purpose'] for x in manifest['icons']]==['any','any','maskable']
        assert [x['sizes'] for x in manifest['icons']]==['192x192','512x512','512x512']
        assert build(sources,root/'repeat').read_bytes()==data
        name='perceptual-grade-32-transparent.png'
        with Image.open(sources/name) as original_png: replacement=original_png.copy()
        replacement.putpixel((16,16),(255,0,0,255));replacement.save(sources/name)
        assert build(sources,root/'changed').read_bytes()!=data
        for name in SOURCES:
            payload=(sources/name).read_bytes();(sources/name).unlink();output=root/(name+'-missing')
            try: build(sources,output)
            except ValueError as error: assert name in str(error) and not output.exists()
            else: raise AssertionError('Missing artwork accepted: '+name)
            (sources/name).write_bytes(payload)
        name='perceptual-grade-64-transparent.png'
        for kind in ('small','opaque','jpeg','corrupt'):
            if kind=='small':Image.new('RGBA',(32,32)).save(sources/name)
            elif kind=='opaque':Image.new('RGB',(64,64)).save(sources/name)
            elif kind=='jpeg':Image.new('RGB',(64,64)).save(sources/name,format='JPEG')
            else:(sources/name).write_bytes(b'not a PNG')
            output=root/kind
            try:build(sources,output)
            except (ValueError,UnidentifiedImageError):assert not output.exists()
            else:raise AssertionError('Invalid artwork accepted: '+kind)
    print('PASS all 16 required icons, exact ICO PNG payloads, byte-preserving copies, unscaled maskable artwork and missing-source failures')


if __name__=='__main__':main()
