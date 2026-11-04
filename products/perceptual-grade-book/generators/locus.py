"""Render the CIE 1931 spectral locus as a transparent, ordinary RGBA PNG.

Coordinates span x/y=0..0.9, y increasing upwards. The line of purples closes
360..830 nm. Dynamic axes, handles and triangles are drawn by the gizmo.
"""
from pathlib import Path
import sys
import numpy as np
import colour
from PIL import Image,ImageDraw,PngImagePlugin
import argparse

CMFS_NAME='CIE 1931 2 Degree Standard Observer'
FIRST_WAVELENGTH_NM=360
LAST_WAVELENGTH_NM=830
INTERVAL_NM=1
SIZE=1024
SUPERSAMPLE=4


def sample_locus():
    wavelengths=np.arange(FIRST_WAVELENGTH_NM,LAST_WAVELENGTH_NM+1,INTERVAL_NM,dtype=np.int16)
    values=np.asarray(colour.MSDS_CMFS[CMFS_NAME][wavelengths],dtype=np.float64)
    sums=values.sum(axis=1)
    if values.shape!=(len(wavelengths),3) or np.any(sums<=0):raise ValueError('CMF table has an invalid domain')
    return wavelengths,values[:,:2]/sums[:,None]


def build(output):
    wavelengths,xy=sample_locus();n=SIZE*SUPERSAMPLE
    image=Image.new('RGBA',(n,n),(0,0,0,0))
    points=[(x/.9*n-.5,(1-y/.9)*n-.5) for x,y in xy]
    ImageDraw.Draw(image).line(points+[points[0]],fill=(170,170,170,255),width=5*SUPERSAMPLE,joint='curve')
    image=image.resize((SIZE,SIZE),Image.Resampling.LANCZOS)
    metadata=PngImagePlugin.PngInfo()
    metadata.add_text('Description','CIE 1931 2-degree xy locus, 360-830 nm at 1 nm; x/y 0..0.9, y upwards; line of purples included')
    metadata.add_text('Generator','tools/assets/locus.py; colour-science CMFs; RGBA artwork')
    destination=Path(output)
    destination.parent.mkdir(parents=True,exist_ok=True)
    image.save(destination,pnginfo=metadata)
    return destination,wavelengths,xy


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args=parser.parse_args()
    path,wavelengths,_=build(args.output_dir/'cie_1931_xy_locus.png')
    print(f'wrote {path}: {SIZE} x {SIZE} RGBA, {wavelengths[0]}-{wavelengths[-1]} nm')
