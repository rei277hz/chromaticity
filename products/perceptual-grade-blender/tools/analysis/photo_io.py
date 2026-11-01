"""Pinned photographic samples, Blender OCIO processors, and tagged RGB PNGs."""
import hashlib
from importlib.resources import files
from io import BytesIO
import json
from pathlib import Path
import struct
import sys
import zlib
import numpy as np


def load_fixtures():
    """Return named, unmodified linear Rec.2020 samples with verified provenance."""
    resources=files('perceptual_grade_photographs')
    manifest=json.loads(resources.joinpath('manifest.json').read_text())
    common={key:value for key,value in manifest.items() if key!='images'}
    result=[]
    for record in manifest['images']:
        data=resources.joinpath(record['sample_file']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=record['sample_sha256']:
            raise ValueError(f"Photograph checksum mismatch: {record['sample_file']}")
        rgb=np.load(BytesIO(data),allow_pickle=False)
        if rgb.dtype!=np.dtype('<f4') or list(rgb.shape)!=record['sample_shape'] or not np.isfinite(rgb).all():
            raise ValueError(f"Invalid photograph array: {record['sample_file']}")
        result.append(dict(name=record['name'],rgb=rgb,metadata={**common,**record}))
    return result


def ocio_processors():
    """Return convert, displays (SDR100/HDR1000), and pinned-config metadata.

    Processors accept linear ACEScg except convert, which accepts linear
    Rec.2020. Display values are encoded sRGB and Rec.2020 PQ respectively.
    """
    import bpy
    resources=Path(bpy.utils.resource_path('LOCAL'))
    site=resources/'python/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    previous=sys.path
    try:
        sys.path=[str(site),*previous]
        import PyOpenColorIO as ocio
    finally:
        sys.path=previous
    config_path=resources/'datafiles/colormanagement/config.ocio'
    config=ocio.Config.CreateFromFile(str(config_path))
    definitions={'SDR100':dict(display='sRGB',view='ACES 2.0',code_max=255),
                 'HDR1000':dict(display='Rec.2100-PQ',view='ACES 2.0 - HDR 1000 nits',code_max=1023)}
    displays={name:config.getProcessor(ocio.DisplayViewTransform(src='ACEScg',
        display=value['display'],view=value['view'])).getDefaultCPUProcessor()
        for name,value in definitions.items()}
    return dict(convert=config.getProcessor('Linear Rec.2020','ACEScg').getDefaultCPUProcessor(),
        displays=displays,metadata=dict(config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
            blender_version=bpy.app.version_string,ocio_version=ocio.__version__,
            source_space='Linear Rec.2020',grading_space='ACEScg',displays=definitions,
            display_exposure_stops=0,display_looks=[]))


def apply_processor(processor,rgb):
    """Apply an OCIO CPU processor to a separate contiguous float32 RGB array."""
    result=np.array(rgb,dtype='f4',order='C',copy=True)
    if result.ndim<1 or result.shape[-1]!=3 or not np.isfinite(result).all():
        raise ValueError('Expected finite RGB values with a final dimension of three')
    if result.size:
        processor.applyRGB(result.reshape(-1,3))
    if not np.isfinite(result).all():
        raise ArithmeticError('OCIO produced nonfinite display values')
    return result


def save_display(path,rgb,view):
    """Save encoded RGB as sRGB PNG8 or PQ/Rec.2020 PNG16; return write metrics.

    Clipping is limited to PNG storage. The caller retains its floating-point
    encoded arrays for unclipped error measurements. HDR diagnostic code units
    are ten-bit; the PNG itself retains all sixteen storage bits.
    """
    if view not in ('SDR100','HDR1000'):
        raise ValueError(f'Unknown display: {view}')
    value=np.asarray(rgb,dtype=float)
    if value.ndim!=3 or value.shape[-1]!=3 or not all(value.shape[:2]) or not np.isfinite(value).all():
        raise ValueError('Expected a finite, nonempty H x W x 3 image')
    depth=8 if view=='SDR100' else 16
    maximum=2**depth-1
    clipped=(value<0)|(value>1)
    encoded=np.floor(np.clip(value,0,1)*maximum+.5).astype('u1' if depth==8 else '>u2')
    height,width=value.shape[:2]
    def chunk(kind,payload):
        return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload))
    rows=b''.join(b'\0'+row.tobytes() for row in encoded)
    header=struct.pack('>IIBBBBB',width,height,depth,2,0,0,0)
    # PNG cICP: BT.2020 primaries, ST 2084 transfer, RGB matrix, full range.
    color=chunk(b'sRGB',b'\0') if depth==8 else chunk(b'cICP',bytes((9,16,0,1)))
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+color+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return dict(file=path.name,bit_depth=depth,png_code_max=maximum,
        quantization_error_bound=.5/maximum,clipped_channels=int(np.count_nonzero(clipped)),
        clipped_pixels=int(np.count_nonzero(np.any(clipped,axis=-1))),bytes=len(data))
