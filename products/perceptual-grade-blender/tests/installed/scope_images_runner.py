"""Generated native movie verifies source-only decoding in an installed extension."""
import importlib
import json
from pathlib import Path
import struct
import zlib
import sys
import traceback
import time
import addon_utils
import bpy
import numpy as np


def movie(path,stereo=False):
    """Three lossless RGB frames in an uncompressed AVI; no encoder dependency."""
    def chunk(tag,data):
        return tag+struct.pack('<I',len(data))+data+(b'\0' if len(data)%2 else b'')
    def listing(tag,data):return chunk(b'LIST',tag+data)
    width,height=4,2
    colors=((128,0,0),(0,64,0),(0,0,192)) if stereo else ((255,0,0),(0,255,0),(0,0,255))
    frames=[];rgb_frames=[]
    for index,(r,g,b) in enumerate(colors):
        right=colors[(index+1)%3] if stereo else (r,g,b)
        row=bytes((b,g,r))*2+bytes(reversed(right))*2
        second=bytes(reversed(right))*2+bytes((b,g,r))*2 if stereo else row
        frames.append(row+second)
        rgb_row=bytes((r,g,b,255))*2+bytes((*right,255))*2
        rgb_second=bytes((*right,255))*2+bytes((r,g,b,255))*2 if stereo else rgb_row
        # Positive-height AVI stores bottom-up rows; PNG stores top-down.
        rgb_frames.append(rgb_second+rgb_row)
    avih=struct.pack('<14I',1000000,24,0,0x10,3,0,1,24,width,height,0,0,0,0)
    strh=struct.pack('<4s4sIHH8I4h',b'vids',b'DIB ',0,0,0,0,1,1,0,3,24,0xffffffff,0,0,0,width,height)
    strf=struct.pack('<IiiHHIIiiII',40,width,height,1,24,0,24,0,0,0,0)
    header=listing(b'hdrl',chunk(b'avih',avih)+listing(b'strl',chunk(b'strh',strh)+chunk(b'strf',strf)))
    chunks=[chunk(b'00db',frame) for frame in frames]
    offsets=[];offset=4
    for frame in chunks:offsets.append(offset);offset+=len(frame)
    index=b''.join(struct.pack('<4sIII',b'00db',0x10,offset,len(frame)) for offset,frame in zip(offsets,frames))
    payload=b'AVI '+header+listing(b'movi',b''.join(chunks))+chunk(b'idx1',index)
    path.write_bytes(b'RIFF'+struct.pack('<I',len(payload))+payload)
    return rgb_frames


def png(path,pixels,width=4,height=2):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+pixels[y*width*4:(y+1)*width*4] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))


def float_movie(path):
    """Sixteen-bit RGBA PNG frames in AVI, with no external encoder dependency."""
    def chunk(tag,data):return tag+struct.pack('<I',len(data))+data+(b'\0' if len(data)%2 else b'')
    def listing(tag,data):return chunk(b'LIST',tag+data)
    def png_chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    width,height=4,2;frames=[]
    for frame in range(3):
        left=(12345+frame*2000,23456,34567,65535);right=(54321,43210-frame*2000,32109,65535)
        top=left*2+right*2;bottom=right*2+left*2
        rows=b'\0'+struct.pack('>16H',*top)+b'\0'+struct.pack('>16H',*bottom)
        frames.append(b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',struct.pack('>2I5B',width,height,16,6,0,0,0))+
                      png_chunk(b'IDAT',zlib.compress(rows))+png_chunk(b'IEND',b''))
    size=max(map(len,frames))
    avih=struct.pack('<14I',1000000,size,0,0x10,3,0,1,size,width,height,0,0,0,0)
    strh=struct.pack('<4s4sIHH8I4h',b'vids',b'MPNG',0,0,0,0,1,1,0,3,size,0xffffffff,0,0,0,width,height)
    strf=struct.pack('<IiiHHIIiiII',40,width,height,1,64,int.from_bytes(b'MPNG','little'),width*height*8,0,0,0,0)
    header=listing(b'hdrl',chunk(b'avih',avih)+listing(b'strl',chunk(b'strh',strh)+chunk(b'strf',strf)))
    chunks=[chunk(b'00dc',frame) for frame in frames];offsets=[];offset=4
    for frame in chunks:offsets.append(offset);offset+=len(frame)
    index=b''.join(struct.pack('<4sIII',b'00dc',0x10,offset,len(frame)) for offset,frame in zip(offsets,frames))
    payload=b'AVI '+header+listing(b'movi',b''.join(chunks))+chunk(b'idx1',index)
    path.write_bytes(b'RIFF'+struct.pack('<I',len(payload))+payload)


def main(repository,destination):
    repository=Path(repository).resolve();destination=Path(destination)
    report=dict(passed=False,build=bpy.app.build_hash.decode(),frames=[])
    name='bl_ext.pg_scope_images.perceptual_grade'
    try:
        assert not bpy.app.background and tuple(bpy.app.version) in {(5, 2, 4), (5, 3, 0)}
        bpy.context.preferences.extensions.repos.new(name='Scope Image acceptance',
            module='pg_scope_images',custom_directory=str(repository))
        errors=[];addon=addon_utils.enable(name,default_set=False,handle_error=errors.append)
        assert addon is not None and not errors,errors
        lifecycle=importlib.import_module(name+'.perceptual_grade_blender.integration.lifecycle')
        assert Path(lifecycle.__file__).resolve().is_relative_to(repository/'perceptual_grade')
        application=lifecycle.registered_session();reader=application.component('scopes.images')
        def isolated(descriptor):
            deadline=time.monotonic()+30
            while True:
                try:return reader.read(descriptor,force=True,asynchronous=True)
                except reader.SourcePreparing:
                    if time.monotonic()>deadline:raise AssertionError('Stored Image helper did not retire')
                    time.sleep(.02)
        path=destination.parent/'source.avi';movie(path)
        image=bpy.data.images.load(str(path),check_existing=False)
        # Materialize Blender's initial metadata before checking that source
        # reads leave the configured, loaded Image unchanged.
        assert tuple(image.size)==(4,2)
        before=(image.filepath,image.source,image.is_dirty,image.colorspace_settings.name,image.alpha_mode)
        baseline=(len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups))
        for frame in (1,3,2,1,3):
            descriptor=reader.describe(image,scene_frame=frame,
                frame_settings=reader.FrameSettings(duration=3))
            result=isolated(descriptor)
            expected={1:(1,0,0),2:(0,1,0),3:(0,0,1)}[frame]
            np.testing.assert_allclose(result.rgba[...,:3],np.broadcast_to(expected,(*result.layout.shape,3)),atol=4e-5)
            assert not result.rgba.flags.writeable
            report['frames'].append(dict(frame=frame,pixel=result.rgba[0,0].tolist(),label=result.label))
            assert baseline==(len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups))
        report['source_unchanged']=before==(image.filepath,image.source,image.is_dirty,image.colorspace_settings.name,image.alpha_mode)
        assert report['source_unchanged']
        left_path=destination.parent/'individual_L.avi';right_path=destination.parent/'individual_R.avi'
        movie(left_path);movie(right_path)
        individual=bpy.data.images.load(str(left_path),check_existing=False)
        individual.use_multiview=True;individual.views_format='INDIVIDUAL'
        report['individual_cases']=[]
        for frame in (3,2):
            for view in ('left','right'):
                result=isolated(reader.describe(individual,view=view,scene_frame=frame,
                    frame_settings=reader.FrameSettings(duration=3)))
                expected=(0,0,1) if frame==3 else (0,1,0)
                np.testing.assert_allclose(result.rgba[...,:3],np.broadcast_to(expected,(*result.layout.shape,3)),atol=4e-5)
                report['individual_cases'].append([frame,view])
        stereo_path=destination.parent/'stereo.avi';frames=movie(stereo_path,True)
        stereo=bpy.data.images.load(str(stereo_path),check_existing=False);tuple(stereo.size)
        stereo.use_multiview=True;stereo.views_format='STEREO_3D'
        report['stereo_cases']=[]
        editor_state=tuple((area.as_pointer(),area.type,getattr(area.spaces.active,'image',None))
                           for screen in bpy.data.screens for area in screen.areas)
        stereo_before=(stereo.filepath,stereo.colorspace_settings.name,stereo.is_dirty)
        cases=[('SIDEBYSIDE',False),('SIDEBYSIDE',True),('TOPBOTTOM',False),('TOPBOTTOM',True),('INTERLACE',False),('ANAGLYPH',False)]
        for mode,squeezed in cases:
            stereo.stereo_3d_format.display_mode=mode
            stereo.stereo_3d_format.use_squeezed_frame=squeezed
            for frame in (3,1,2):
                still_path=destination.parent/f'frame{frame}.png';png(still_path,frames[frame-1])
                still=bpy.data.images.load(str(still_path),check_existing=False);tuple(still.size)
                still.use_multiview=True;still.views_format='STEREO_3D'
                still.stereo_3d_format.display_mode=mode
                still.stereo_3d_format.use_squeezed_frame=squeezed
                try:
                    for view in (0,1):
                        actual=isolated(reader.describe(stereo,view=view,scene_frame=frame,
                            frame_settings=reader.FrameSettings(duration=3)))
                        expected=reader.read(reader.describe(still,view=view),force=True)
                        np.testing.assert_allclose(actual.rgba,expected.rgba,atol=3e-5)
                        assert actual.layout.shape==expected.layout.shape
                        report['stereo_cases'].append([mode,squeezed,frame,view])
                finally:bpy.data.images.remove(still)
        assert editor_state==tuple((area.as_pointer(),area.type,getattr(area.spaces.active,'image',None))
                                   for screen in bpy.data.screens for area in screen.areas)
        assert stereo_before==(stereo.filepath,stereo.colorspace_settings.name,stereo.is_dirty)
        high_path=destination.parent/'high-depth.avi';float_movie(high_path)
        high=bpy.data.images.load(str(high_path),check_existing=False)
        assert tuple(high.size)==(4,2) and high.is_float,'High-depth fixture did not decode to floats'
        # Compare source precision, not the visible decoder's optional GPU
        # half-float texture storage (the helper exports full float EXR).
        high.use_half_precision=False
        high.colorspace_settings.name='Non-Color';high.use_multiview=True;high.views_format='STEREO_3D'
        report['float_stereo_cases']=[]
        for mode,squeezed in (('SIDEBYSIDE',True),('TOPBOTTOM',True),('INTERLACE',False)):
            high.stereo_3d_format.display_mode=mode;high.stereo_3d_format.use_squeezed_frame=squeezed
            for frame in (3,1,2):
                for view in (0,1):
                    descriptor=reader.describe(high,view=view,scene_frame=frame,
                        frame_settings=reader.FrameSettings(duration=3))
                    expected=reader.read(descriptor,force=True)
                    actual=isolated(descriptor)
                    np.testing.assert_allclose(actual.rgba,expected.rgba,atol=3e-5)
                    report['float_stereo_cases'].append([mode,squeezed,frame,view])
        addon_utils.disable(name,default_set=False)
        report['passed']=True
    except Exception:
        report['error']=traceback.format_exc()
    destination.write_text(json.dumps(report,indent=2))
    print('PG_SCOPE_IMAGES',json.dumps(report),flush=True)
    bpy.ops.wm.quit_blender()


args=sys.argv[sys.argv.index('--')+1:]
bpy.app.timers.register(lambda:main(*args),first_interval=.2)
