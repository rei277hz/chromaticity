"""Photographic resource integrity and display-image interchange."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
import numpy as np
from tools.analysis import photo_io


def read_png(path):
    """Decode this experiment's unfiltered PNGs independently of the writer."""
    data=path.read_bytes()
    if data[:8]!=b'\x89PNG\r\n\x1a\n':
        raise ValueError('Bad PNG signature')
    offset=8;chunks={}
    while offset<len(data):
        size=struct.unpack_from('>I',data,offset)[0]
        kind=data[offset+4:offset+8];payload=data[offset+8:offset+8+size]
        crc=struct.unpack_from('>I',data,offset+8+size)[0]
        if crc!=zlib.crc32(kind+payload):
            raise ValueError('Bad PNG checksum')
        chunks[kind]=chunks.get(kind,b'')+payload;offset+=12+size
    width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',chunks[b'IHDR'])
    if (color,compression,filtering,interlace)!=(2,0,0,0):
        raise ValueError('Unexpected PNG representation')
    rows=np.frombuffer(zlib.decompress(chunks[b'IDAT']),dtype='u1').reshape(height,1+width*3*(depth//8))
    if np.any(rows[:,0]):
        raise ValueError('Unexpected row filter')
    pixels=np.frombuffer(rows[:,1:].tobytes(),dtype='u1' if depth==8 else '>u2').reshape(height,width,3)
    return depth,pixels,chunks


class PhotoIOTests(unittest.TestCase):
    def test_packaged_spatial_samples_keep_signed_values_and_provenance(self):
        photos=photo_io.load_fixtures()
        self.assertEqual([item['name'] for item in photos],['IMG_0436','IMG_0441','IMG_0446','IMG_0472'])
        self.assertEqual(sum(item['rgb'].shape[0]*item['rgb'].shape[1] for item in photos),338688)
        for index,item in enumerate(photos):
            with self.subTest(name=item['name']):
                self.assertEqual(item['rgb'].shape,(336,252,3) if index==3 else (252,336,3))
                self.assertEqual(item['rgb'].dtype,np.dtype('f4'))
                self.assertLess(item['rgb'].min(),0)
                self.assertEqual(item['metadata']['assumed_reference_nits'],203)
                self.assertFalse(item['metadata']['original_files_available'])
                self.assertEqual(len(item['metadata']['source_sha256']),64)

    def test_corrupted_sample_is_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'sample.npy').write_bytes(b'corrupted sample')
            (root/'manifest.json').write_text(json.dumps(dict(images=[dict(
                sample_file='sample.npy',sample_sha256='0'*64)])))
            with patch.object(photo_io,'files',return_value=root):
                with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                    photo_io.load_fixtures()

    def test_pinned_ocio_conversion_and_display_processors(self):
        processors=photo_io.ocio_processors()
        metadata=processors['metadata']
        self.assertEqual(metadata['config_sha256'],'f10891fc7d34e78e71b535e3f92b3c612177320f990641283247cb84bb8d62ad')
        self.assertEqual(metadata['displays']['SDR100']['display'],'sRGB')
        self.assertEqual(metadata['displays']['HDR1000']['display'],'Rec.2100-PQ')
        self.assertEqual(metadata['displays']['HDR1000']['view'],'ACES 2.0 - HDR 1000 nits')
        source=np.array([[[0,0,0],[1,1,1]],[[.25,.5,.75],[-.1,.2,.3]]],dtype='f4')
        original=source.copy()
        converted=photo_io.apply_processor(processors['convert'],source)
        np.testing.assert_array_equal(source,original)
        self.assertFalse(np.shares_memory(source,converted))
        self.assertEqual(converted.dtype,np.dtype('f4'))
        np.testing.assert_allclose(converted[0],source[0],rtol=0,atol=1e-5)
        for processor in processors['displays'].values():
            output=photo_io.apply_processor(processor,converted)
            self.assertEqual(output.shape,source.shape)
            self.assertTrue(np.isfinite(output).all())
            self.assertLess(np.max(abs(output[0,0])),1e-6)

    def test_png_encoding_precision_tags_and_storage_clipping(self):
        rgb=np.array([[[0,.5,1],[-.1,1.1,.125]],[[.01,.2,.3],[.4,.6,.8]]])
        original=rgb.copy()
        with tempfile.TemporaryDirectory() as directory:
            for view,depth in (('SDR100',8),('HDR1000',16)):
                with self.subTest(view=view):
                    path=Path(directory)/(view+'.png')
                    metadata=photo_io.save_display(path,rgb,view)
                    actual_depth,pixels,chunks=read_png(path)
                    self.assertEqual(actual_depth,depth)
                    maximum=2**depth-1
                    error=abs(pixels.astype(float)/maximum-np.clip(rgb,0,1))
                    self.assertLessEqual(float(error.max()),.5/maximum+1e-15)
                    self.assertEqual(int(pixels[0,0,2]),maximum)
                    self.assertEqual(int(pixels[0,0,1]),2**(depth-1))
                    if depth==8:self.assertEqual(chunks[b'sRGB'],b'\0')
                    else:self.assertEqual(chunks[b'cICP'],bytes((9,16,0,1)))
                    self.assertEqual(metadata['png_code_max'],maximum)
                    self.assertEqual(metadata['clipped_channels'],2)
                    self.assertEqual(metadata['clipped_pixels'],1)
        np.testing.assert_array_equal(rgb,original)

    def test_nonfinite_rgb_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'finite'):
            photo_io.apply_processor(None,[[np.nan,0,0]])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'invalid.png'
            with self.assertRaisesRegex(ValueError,'finite'):
                photo_io.save_display(path,[[[0,np.inf,1]]],'SDR100')
            self.assertFalse(path.exists())
