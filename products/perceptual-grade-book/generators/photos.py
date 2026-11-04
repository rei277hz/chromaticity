"""Rebuild photographic guard comparisons from the packaged sampled fixtures."""
import argparse
import json
import math
from pathlib import Path
import struct
import tempfile
import zlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import bpy
from pg_book_legacy.model import linear as lm, tone as tm, color as cm, lut
from pg_book_generators.figure_common import manifest, write_json


def read_pq_png(path):
    """Full 16-bit RGBA decoding, including all five PNG scanline filters."""
    raw=path.read_bytes()
    if raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid fixture PNG')
    offset=8;packed=[];header=None
    while offset<len(raw):
        n=struct.unpack('>I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8];value=raw[offset+8:offset+8+n]
        if zlib.crc32(kind+value)&0xffffffff!=struct.unpack('>I',raw[offset+8+n:offset+12+n])[0]:raise ValueError('PNG CRC mismatch')
        if kind==b'IHDR':header=struct.unpack('>IIBBBBB',value)
        if kind==b'IDAT':packed.append(value)
        offset+=n+12
        if kind==b'IEND':break
    width,height,depth,kind,compression,filtering,interlace=header
    if (depth,kind,compression,filtering,interlace)!=(16,6,0,0,0):raise ValueError('Expected noninterlaced RGBA16 fixture')
    data=zlib.decompress(b''.join(packed));stride=8*width;prior=np.zeros(stride,np.uint8);rows=[]
    if len(data)!=(stride+1)*height:raise ValueError('PNG pixel length mismatch')
    for y in range(height):
        start=y*(stride+1);filter_type=data[start];row=bytearray(data[start+1:start+1+stride])
        for i in range(stride):
            left=row[i-8] if i>=8 else 0;up=int(prior[i]);corner=int(prior[i-8]) if i>=8 else 0
            if filter_type==0:prediction=0
            elif filter_type==1:prediction=left
            elif filter_type==2:prediction=up
            elif filter_type==3:prediction=(left+up)//2
            elif filter_type==4:
                p=left+up-corner;dist=[abs(p-left),abs(p-up),abs(p-corner)];prediction=(left,up,corner)[dist.index(min(dist))]
            else:raise ValueError('Invalid PNG filter')
            row[i]=(row[i]+prediction)&255
        prior=np.frombuffer(bytes(row),np.uint8);rows.append(bytes(row))
    rgba=np.frombuffer(b''.join(rows),'>u2').reshape(height,width,4).astype(float)/65535
    code=rgba[...,:3];p=code**(1/(2523/32))
    nits=(np.maximum(p-3424/4096,0)/(2413/128-2392/128*p))**(1/(2610/16384))*10000
    # D65 is shared; this conversion retains signed RGB outside Rec.709.
    p3=((.68,.32),(.265,.69),(.15,.06));primaries=lm.columns(*(lm.xyz(p) for p in p3))
    scales=lm.mv(lm.inverse(primaries),lm.xyz(lm.D65))
    matrix=np.asarray(primaries)*np.asarray(scales)[None,:]
    rgb=(nits/203)@(np.asarray(lm.xyz_to_rgb('Linear Rec.709'))@matrix).T
    return rgb,rgba[...,3]>0


class RetainCComparator(cm.Model):
    """Historical energy-floor formula in the current surrounding pipeline."""
    def decode(self,q,reference=None):
        q=np.asarray(q,dtype=float);H,a,b=np.moveaxis(q,-1,0);C=np.hypot(a,b);D=H*H-66*C
        E0=H*H if reference is None else np.maximum(0,reference[...,0]**2-66*np.hypot(reference[...,1],reference[...,2]))
        low=np.minimum(E0,H*H);high=np.maximum(E0,H*H)
        ratio=np.divide(low,high,out=np.zeros_like(D),where=high>0);delta=low/(1+ratio)
        v=np.divide(delta,delta+np.maximum(delta-D,0),out=np.zeros_like(D),where=delta>0)
        E=np.where(D>=delta,D,delta*v*v/(1-v+v*v))
        ja=np.sqrt(np.maximum(E,0));ach=self.tone.aw*(ja/100)**(1/tm.GAMMA)
        co=np.divide(a,C,out=np.zeros_like(a),where=C>0);si=np.divide(b,C,out=np.zeros_like(b),where=C>0)
        scale=self.tone.aw/(1204*tm.eccentricity(co,si));ar=a*scale;br=b*scale
        s=np.stack([(460*ach+451*ar+288*br)/1403,(460*ach-891*ar-261*br)/1403,(460*ach-220*ar-6300*br)/1403],axis=-1)
        out=tm.unresponse(np.clip(s,-399.998,399.998),self.tone.fl)
        valid=(H>=0)&(E>=0)&(np.max(np.abs(s),axis=-1)<399.998)&np.isfinite(out).all(axis=-1)
        return out,valid


def metric(reference,result,mask):
    delta=np.max(np.abs(result-reference),axis=-1)[mask]
    relative=delta/np.maximum(.01,np.max(np.abs(reference),axis=-1)[mask])
    return {'relative_rgb_p50':float(np.percentile(relative,50)), 'relative_rgb_p99':float(np.percentile(relative,99)),
            'relative_rgb_max':float(np.max(relative)), 'absolute_rgb_max':float(np.max(delta))}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,required=True);parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--samples',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args(argv)
    out=args.output_dir;images=out/'images';images.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.set_working_color_space(working_space='Linear Rec.709',convert_colors=False)
    scene=bpy.context.scene;scene.view_settings.view_transform='ACES 2.0';scene.view_settings.look='None'
    scene.display_settings.display_device='sRGB';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB';scene.render.image_settings.color_depth='8'
    scene.render.image_settings.color_management='FOLLOW_SCENE'
    meta=json.loads((args.fixtures/'exr/metadata.json').read_text());sources=[]
    conversion=np.asarray(lm.xyz_to_rgb('Linear Rec.709'))@np.asarray(lm.rgb_to_xyz('Linear Rec.2020'))
    for record in meta['images']:
        rgb=np.load(args.samples/record['sample_file']).astype(float)@conversion.T
        sources.append((Path(record['name']).stem,rgb,np.ones(rgb.shape[:2],bool)))
    rgb,mask=read_pq_png(args.fixtures/'pq/IMG_0221.PNG');sources.append(('P3-D65 / PQ',rgb,mask))
    settings=json.loads((args.data/'photo-grades.json').read_text());font=ImageFont.load_default(size=18);small=ImageFont.load_default(size=14)
    rows=[]
    with tempfile.TemporaryDirectory(prefix='pg-book-photo-') as temporary:
        def display(rgb,mask):
            h,w=rgb.shape[:2];image=bpy.data.images.new('Book display probe',width=w,height=h,float_buffer=True,alpha=True)
            rgba=np.concatenate([rgb,np.ones((h,w,1))],axis=-1).astype('f4');rgba[~mask,:3]=0
            image.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).ravel());image.update()
            path=Path(temporary)/'view.png';image.save_render(str(path),scene=scene);bpy.data.images.remove(image)
            with Image.open(path) as rendered:return rendered.convert('RGB').copy()
        for grade in settings['grades']:
            tone=tm.model(tm.Parameters(**grade.get('tone',{})));params=cm.Parameters(**grade['color'])
            model=cm.Model(tone,params);earlier=RetainCComparator(tone,params);cube=lut.Baker(model).finish()
            width=310;gap=14;top=78;heights=[round(width*rgb.shape[0]/rgb.shape[1]) for _,rgb,_ in sources]
            sheet=Image.new('RGB',(4*width+5*gap,top+sum(h+28 for h in heights)+30),'#282828');draw=ImageDraw.Draw(sheet)
            draw.text((gap,12),'Perceptual Grade / '+grade['title'],font=font,fill='#e6e6e6')
            for j,label in enumerate(('Source','Historical guard formula','Current analytic','Current 65 x 65 x 65 LUT')):
                draw.text((gap+j*(width+gap),46),label,font=small,fill='#cccccc')
            y=top
            for (name,rgb,mask),height in zip(sources,heights):
                current=model.apply(rgb);old=earlier.apply(rgb);lookup=cube.apply(rgb)
                if not all(np.isfinite(x).all() for x in (current,old,lookup)):raise ArithmeticError('Nonfinite photo result')
                for j,result in enumerate((rgb,old,current,lookup)):
                    image=display(result,mask).resize((width,height),Image.Resampling.LANCZOS);sheet.paste(image,(gap+j*(width+gap),y))
                draw.text((gap,y+height+3),name,font=small,fill='#aaaaaa');y+=height+28
                rows.append({'grade':grade['name'],'fixture':name,'pixels':int(mask.sum()),'lut':metric(current,lookup,mask),
                             'guard_difference':metric(current,old,mask),'all_results_finite':True})
            draw.text((gap,sheet.height-23),'Sampled fixtures / same ACES 2.0 / sRGB view / Linear Rec.709 working space',font=small,fill='#bcbcbc')
            sheet.save(images/('photo-'+grade['name']+'.png'))
    write_json(out/'metrics.json',{'view':'Blender ACES 2.0 / sRGB','blender_version':bpy.app.version_string,
                                  'comparison':'Historical retain-C energy floor in current pipeline; not original archived measurements',
                                  'working_space':'Linear Rec.709','rows':rows})
    inputs=[args.data/'photo-grades.json',*sorted(args.fixtures.rglob('*')), *sorted(args.samples.glob('*.npy'))]
    manifest(out,[p for p in inputs if p.is_file()]+[Path(__file__),
                 *(Path(module.__file__) for module in (lm,tm,cm,lut))],
             'Perceptual Grade 1.23.2 sampled-fixture guard and LUT comparisons',
             {'docs/data': args.data, 'fixtures': args.fixtures, 'fixtures/exr': args.samples,
              'generators': Path(__file__).parent, 'legacy': Path(lm.__file__).parent.parent})


if __name__=='__main__':main()
