"""Generated real-Image fixtures for source-only automatic scope reads."""
import os
import struct
import tempfile
import unittest
import zlib
import bpy
import numpy as np
from tests.support.session import SessionTest,component
from color_tools.perceptual_grade_core.scopes.samples import ordinary_layout,tiled_layout

images=component('scopes.images')


def png(path,width,height,rgba):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    pixels=bytes(rgba)
    if len(pixels)==4:pixels*=width*height
    data=b''.join(b'\0'+pixels[row*width*4:(row+1)*width*4] for row in range(height))
    with open(path,'wb') as stream:
        stream.write(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+
                     chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b''))


def exr_fixture(path,channels,views=(),width=3,height=2):
    def attr(name,kind,data):return name.encode()+b'\0'+kind.encode()+b'\0'+struct.pack('<I',len(data))+data
    names=sorted(channels)
    ch=b''.join(name.encode()+b'\0'+struct.pack('<iB3xii',2,0,1,1) for name in names)+b'\0'
    box=struct.pack('<4i',0,0,width-1,height-1)
    header=struct.pack('<II',20000630,2)+attr('channels','chlist',ch)+attr('compression','compression',b'\0')
    header+=attr('dataWindow','box2i',box)+attr('displayWindow','box2i',box)
    header+=attr('lineOrder','lineOrder',b'\0')+attr('pixelAspectRatio','float',struct.pack('<f',1.))
    header+=attr('screenWindowCenter','v2f',struct.pack('<2f',0.,0.))+attr('screenWindowWidth','float',struct.pack('<f',1.))
    if views:header+=attr('multiView','stringvector',b''.join(struct.pack('<I',len(v))+v.encode() for v in views))
    header+=b'\0';rows=[]
    for y in range(height):
        pixels=b''.join(struct.pack('<'+'f'*width,*([channels[name]]*width)) for name in names)
        rows.append(struct.pack('<iI',y,len(pixels))+pixels)
    offset=len(header)+8*height;offsets=[]
    for row in rows:offsets.append(offset);offset+=len(row)
    with open(path,'wb') as stream:stream.write(header+struct.pack('<'+'Q'*height,*offsets)+b''.join(rows))


class SourceImageTests(SessionTest):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='pg-source-test-')
        self.addCleanup(self.directory.cleanup)
        self.original=set(bpy.data.images)
        self.addCleanup(self.remove_images)

    def remove_images(self):
        for image in list(bpy.data.images):
            if image not in self.original:bpy.data.images.remove(image)

    def fixture(self,name,color=(128,64,32,128),width=3,height=2):
        path=os.path.join(self.directory.name,name);png(path,width,height,color)
        return bpy.data.images.load(path,check_existing=False)

    def isolated_reader(self):
        """A delayed retirement receipt around the real isolated-source handler."""
        from types import SimpleNamespace
        from color_tools.perceptual_grade_blender.scopes import images as module
        from color_tools.perceptual_grade_blender.jobs.handlers import images as helper
        from color_tools.perceptual_grade_blender.integration.components import Component
        from color_tools.perceptual_grade_core.jobs.values import seal
        class Handle:
            released=False;cancelled=False
            def retired(self):return self.released
            def cancel(self):self.cancelled=True
            def result(self):return self.value
        handles=[]
        def submit(spec):
            self.assertEqual(spec.operation,'scope_image_read');self.assertEqual(spec.lane,'capture')
            handle=Handle();handle.request=seal(spec.inputs)
            handles.append(handle)
            return handle
        application=self.session
        class Adapter:
            def component(_,name):
                if name=='services':return Component({'get_runtime':lambda:SimpleNamespace(submit=submit)})
                if name=='graph.output_guard':
                    # Any use of the foreground buffer reader fails this test.
                    def forbidden():raise AssertionError('Foreground native Image buffer read')
                    return Component({'native_operation':forbidden,'require_available':forbidden})
                return application.component(name)
        reader=module.create(Adapter())
        def complete(handle):
            handle.value=helper.handle(handle.request,SimpleNamespace(checkpoint=lambda:None))
            handle.released=True
        return reader,handles,complete

    def test_async_packed_source_waits_for_retirement_and_never_reads_host_buffer(self):
        image=self.fixture('async-packed.png');image.pack();os.remove(image.filepath)
        reader,handles,complete=self.isolated_reader()
        class MetadataOnly:
            def __getattr__(_,name):
                if name in {'size','channels','is_float','frame_duration','pixels'}:
                    raise AssertionError('Discovery acquired native Image buffer: '+name)
                return getattr(image,name)
        descriptor=reader.describe(MetadataOnly())
        before=(image.filepath,image.source,image.is_dirty,len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups))
        for _ in range(3):
            with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,force=True,asynchronous=True)
        self.assertEqual(len(handles),1)
        self.assertFalse(reader.retired(descriptor))
        self.assertIsInstance(handles[0].request['packed'][0]['data'],np.ndarray)
        self.assertFalse(handles[0].request['packed'][0]['data'].flags.writeable)
        complete(handles[0]);result=reader.read(descriptor,force=True,asynchronous=True)
        self.assertTrue(reader.retired(descriptor))
        np.testing.assert_allclose(result.rgba[0,0,3],128/255)
        self.assertIs(reader.read(descriptor,asynchronous=True),result)
        self.assertEqual(before,(image.filepath,image.source,image.is_dirty,len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups)))
        with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,force=True,asynchronous=True)
        complete(handles[-1])
        self.assertIs(reader.read(descriptor,force=True,asynchronous=True),result)

    def test_async_receipt_rejects_source_settings_change_and_generation_retirement(self):
        image=self.fixture('async-fences.png');reader,handles,complete=self.isolated_reader()
        descriptor=reader.describe(image)
        with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,asynchronous=True)
        complete(handles[0]);image.alpha_mode='CHANNEL_PACKED'
        with self.assertRaisesRegex(ValueError,'decoding settings changed'):reader.read(descriptor,asynchronous=True)
        current=reader.describe(image)
        with self.assertRaises(reader.SourcePreparing):reader.read(current,asynchronous=True)
        reader.clear();self.assertTrue(handles[-1].cancelled)
        self.assertFalse(reader.retired(current))
        handles[-1].released=True
        self.assertTrue(reader.retired(current))
        with self.assertRaisesRegex(ReferenceError,'retired session'):reader.read(current,asynchronous=True)

    def test_async_disk_snapshot_rejects_changed_frozen_storage(self):
        image=self.fixture('async-storage.png');reader,handles,complete=self.isolated_reader()
        descriptor=reader.describe(image)
        with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,asynchronous=True)
        png(image.filepath,3,2,(0,255,0,255))
        with self.assertRaisesRegex(ValueError,'storage changed'):complete(handles[0])

    def test_async_packed_receipt_rejects_replaced_encoded_bytes(self):
        image=self.fixture('async-repacked.png');image.pack()
        reader,handles,complete=self.isolated_reader();descriptor=reader.describe(image)
        with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,asynchronous=True)
        complete(handles[0])
        path=os.path.join(self.directory.name,'replacement.png');png(path,3,2,(0,255,0,255))
        with open(path,'rb') as stream:data=stream.read()
        image.pack(data=data,data_len=len(data))
        with self.assertRaisesRegex(ValueError,'pixels changed'):reader.read(descriptor,asynchronous=True)

    def test_async_resident_snapshot_remains_usable_until_guard_reopens(self):
        image=bpy.data.images.new('resident cache',2,1,float_buffer=True)
        image.pixels[:]=(1.,0.,0.,1.,1.,0.,0.,1.)
        descriptor=images.describe(image);first=images.read(descriptor)
        image.pixels[0]=.25
        guard=component('graph.output_guard')
        with guard.native_callback():
            self.assertIs(images.read(descriptor,force=True,asynchronous=True),first)
        updated=images.read(descriptor,force=True,asynchronous=True)
        self.assertNotEqual(updated.revision,first.revision)
        self.assertEqual(updated.rgba[0,0,0],.25)

    def test_async_sequence_and_udim_private_decoding_matches_synchronous(self):
        image=self.fixture('async0001.png',(255,0,0,255));self.fixture('async0002.png',(0,255,0,255))
        image.source='SEQUENCE';reader,handles,complete=self.isolated_reader()
        descriptor=reader.describe(image,scene_frame=2,frame_settings=reader.FrameSettings(duration=2))
        with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,asynchronous=True)
        complete(handles[-1]);actual=reader.read(descriptor,asynchronous=True)
        expected=images.read(images.describe(image,scene_frame=2,frame_settings=images.FrameSettings(duration=2)))
        np.testing.assert_array_equal(actual.rgba,expected.rgba)
        image=self.fixture('async.1001.png',(255,0,0,255));self.fixture('async.1002.png',(0,255,0,255))
        image.source='TILED';image.filepath=image.filepath.replace('1001','<UDIM>');image.tiles.new(1002);image.pack()
        descriptor=reader.describe(image)
        with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,asynchronous=True)
        complete(handles[-1]);actual=reader.read(descriptor,asynchronous=True)
        np.testing.assert_array_equal(actual.rgba,images.read(images.describe(image)).rgba)

    def test_async_multilayer_and_multiview_preserve_selected_source_values(self):
        reader,handles,complete=self.isolated_reader()
        def compare(image,**selection):
            descriptor=reader.describe(image,**selection)
            with self.assertRaises(reader.SourcePreparing):reader.read(descriptor,asynchronous=True)
            complete(handles[-1]);actual=reader.read(descriptor,asynchronous=True)
            expected=images.read(images.describe(image,**selection))
            np.testing.assert_allclose(actual.rgba,expected.rgba,atol=3e-5)
        image=self.fixture('private_L.png',(255,0,0,128));self.fixture('private_R.png',(0,255,0,64))
        image.use_multiview=True;image.views_format='INDIVIDUAL'
        compare(image,view='right',channel='ALPHA')
        image=self.fixture('private-packed.png',(128,64,32,128),4,2)
        image.use_multiview=True;image.views_format='STEREO_3D';image.stereo_3d_format.display_mode='SIDEBYSIDE'
        compare(image,view='right')
        path=os.path.join(self.directory.name,'private-layer.exr')
        exr_fixture(path,{'Layer.Combined.'+name:value for name,value in zip('RGBA',(.2,.4,.6,1.))})
        image=bpy.data.images.load(path,check_existing=False)
        compare(image,layer='Layer',pass_name='Combined')

    def test_static_byte_source_ocio_alpha_and_no_metadata_mutation(self):
        image=self.fixture('color.png')
        before=(image.filepath,image.source,image.colorspace_settings.name,image.alpha_mode,image.is_dirty)
        desc=images.describe(image,premultiply=False)
        result=images.read(desc)
        rgb=np.array([[128/255,64/255,32/255]],np.float32)
        rgb=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        np.testing.assert_allclose(result.rgba[...,:3],np.broadcast_to(rgb,(*result.layout.shape,3)),rtol=3e-5,atol=2e-6)
        np.testing.assert_allclose(result.rgba[...,3],128/255)
        self.assertFalse(result.rgba.flags.writeable)
        self.assertEqual(before,(image.filepath,image.source,image.colorspace_settings.name,image.alpha_mode,image.is_dirty))
        premul=images.read(images.describe(image,premultiply=True))
        np.testing.assert_allclose(premul.rgba[...,:3],result.rgba[...,:3]*result.rgba[...,3,None])
        self.assertIs(images.read(desc,force=True),result)

    def test_generated_float_signed_hdr_and_clean_probing(self):
        image=bpy.data.images.new('generated',2,1,float_buffer=True)
        image.pixels[:]=(-2.,4.,8.,.5,3.,2.,1.,1.)
        desc=images.describe(image,premultiply=True)
        first=images.read(desc)
        np.testing.assert_array_equal(first.rgba,[((-2.,4.,8.,.5),(3.,2.,1.,1.))])
        image.pixels[0]=-7.
        second=images.read(desc,force=True)
        self.assertGreater(second.revision,first.revision)
        self.assertEqual(second.rgba[0,0,0],-7.)
        straight=images.read(images.describe(image,premultiply=False))
        self.assertEqual(straight.rgba[0,0,0],-14.)

    def test_working_space_change_cannot_reuse_previous_decoded_rgb(self):
        image=self.fixture('working-space.png',(200,100,50,255))
        original=bpy.data.colorspace.working_space
        try:
            bpy.ops.wm.set_working_color_space(working_space='Linear Rec.709')
            before=images.describe(image);rec709=images.read(before)
            bpy.ops.wm.set_working_color_space(working_space='ACEScg')
            after=images.describe(image);acescg=images.read(after)
            self.assertNotEqual(before.key,after.key)
            self.assertNotEqual(before.continuity,after.continuity)
            self.assertGreater(np.max(np.abs(rec709.rgba[...,:3]-acescg.rgba[...,:3])),.1)
            self.assertIs(images.read(after,force=True),acescg)
            with self.assertRaisesRegex(ValueError,'decoding settings changed'):
                images.read(before,force=True)
        finally:bpy.ops.wm.set_working_color_space(working_space=original)

    def test_float_straight_file_and_byte_premul_file_match_decoded_alpha(self):
        path=os.path.join(self.directory.name,'straight.exr')
        exr_fixture(path,dict(R=.5,G=.25,B=.125,A=.5))
        image=bpy.data.images.load(path,check_existing=False);image.alpha_mode='STRAIGHT'
        premul=images.read(images.describe(image,premultiply=True))
        straight=images.read(images.describe(image,premultiply=False))
        np.testing.assert_allclose(premul.rgba[0,0],(.25,.125,.0625,.5))
        np.testing.assert_allclose(straight.rgba[0,0],(.5,.25,.125,.5))
        data=self.fixture('data.png',(128,64,32,128));data.colorspace_settings.name='Non-Color'
        raw=images.read(images.describe(data,premultiply=True))
        np.testing.assert_allclose(raw.rgba[0,0],np.array((128,64,32,128))/255)

    def test_sequence_explicit_frame_order_offset_cycle_and_missing_frame(self):
        image=self.fixture('frame0001.png',(255,0,0,255))
        self.fixture('frame0002.png',(0,255,0,255))
        self.fixture('frame0003.png',(0,0,255,255))
        image.source='SEQUENCE'
        settings=images.FrameSettings(start=10,duration=3)
        base=None
        for scene_frame,color in ((10,(1,0,0)),(12,(0,0,1)),(11,(0,1,0)),(10,(1,0,0))):
            desc=images.describe(image,frame_settings=settings,scene_frame=scene_frame)
            if base is None:base=desc.continuity
            self.assertEqual(base,desc.continuity)
            self.assertTrue(desc.animated)
            result=images.read(desc)
            np.testing.assert_allclose(result.rgba[0,0,:3],color,atol=4e-5)
        self.assertEqual(images.FrameSettings(10,3,2,True).resolve(13),3)
        with self.assertRaisesRegex(ValueError,'missing'):
            images.read(images.describe(image,frame_settings=settings,scene_frame=9))

    def test_missing_frame_recovery_changes_content_key_but_not_continuity(self):
        image=self.fixture('missing0001.png');image.source='SEQUENCE'
        settings=images.FrameSettings(duration=2)
        before=images.describe(image,frame_settings=settings,scene_frame=2)
        with self.assertRaisesRegex(ValueError,'missing'):images.read(before)
        png(os.path.join(self.directory.name,'missing0002.png'),3,2,(0,255,0,255))
        after=images.describe(image,frame_settings=settings,scene_frame=2)
        self.assertEqual(before.continuity,after.continuity)
        self.assertNotEqual(before.key,after.key)
        np.testing.assert_allclose(images.read(after).rgba[0,0],(0,1,0,1),atol=4e-5)

    def test_stored_udim_mass_reference_mapping_and_dirty_rejection(self):
        self.fixture('tile.1001.png',(255,0,0,255),2,1)
        self.fixture('tile.1003.png',(0,255,0,255),4,2)
        image=bpy.data.images.load(os.path.join(self.directory.name,'tile.1001.png'),check_existing=False)
        image.source='TILED';image.filepath=os.path.join(self.directory.name,'tile.<UDIM>.png')
        image.tiles.new(1003)
        result=images.read(images.describe(image))
        self.assertEqual(result.layout.count,10)
        np.testing.assert_allclose(result.rgba[result.layout.tiles==1001,:3],[(1,0,0)]*2,atol=4e-5)
        np.testing.assert_allclose(result.rgba[result.layout.tiles==1003,:3],[(0,1,0)]*8,atol=4e-5)
        ordinary=images.read(images.describe(image),layout=ordinary_layout(2,1))
        np.testing.assert_allclose(ordinary.rgba[...,:3],[[(1,0,0)]*2],atol=4e-5)
        missing=images.read(images.describe(image),layout=tiled_layout(((1001,2,1),(1002,1,1))))
        self.assertTrue(missing.incomplete)
        self.assertTrue(np.all(missing.rgba[missing.layout.tiles==1002]==0))
        image.pixels[0]=.25
        with self.assertRaisesRegex(ValueError,'Save the painted'):
            images.read(images.describe(image),force=True)

    def test_packed_udim_survives_missing_files_and_reference_reads_keep_revision(self):
        self.fixture('packed.1001.png',(255,0,0,255),2,1)
        self.fixture('packed.1002.png',(0,255,0,255),1,1)
        image=bpy.data.images.load(os.path.join(self.directory.name,'packed.1001.png'),check_existing=False)
        image.source='TILED';image.filepath=os.path.join(self.directory.name,'packed.<UDIM>.png')
        image.tiles.new(1002);image.pack()
        self.assertEqual(len(image.packed_files),2)
        os.remove(os.path.join(self.directory.name,'packed.1001.png'))
        os.remove(os.path.join(self.directory.name,'packed.1002.png'))
        desc=images.describe(image)
        primary=images.read(desc);signature=images.signature(desc)
        alternate=ordinary_layout(1,1)
        images.read(desc,layout=alternate)
        self.assertEqual(images.signature(desc),signature)
        self.assertGreater(images.signature(desc,layout=alternate)[1],signature[1])
        np.testing.assert_allclose(primary.rgba[primary.layout.tiles==1002,:3],[(0,1,0)],atol=4e-5)

    def test_udim_pass_and_view_combinations_never_silently_select_default(self):
        image=self.fixture('view.1001.png');image.source='TILED'
        image.filepath=os.path.join(self.directory.name,'view.<UDIM>.png')
        image.use_multiview=True
        with self.assertRaisesRegex(ValueError,'per-tile pass or view selection'):
            images.read(images.describe(image,view='right'))
        path=os.path.join(self.directory.name,'layer.1001.exr')
        exr_fixture(path,{'Layer.Combined.'+name:value for name,value in zip('RGBA',(.2,.4,.6,1.))})
        layered=bpy.data.images.load(path,check_existing=False);layered.source='TILED'
        layered.filepath=os.path.join(self.directory.name,'layer.<UDIM>.exr')
        with self.assertRaisesRegex(ValueError,'per-tile pass or view selection'):
            images.read(images.describe(layered,layer='Layer'))

    def test_configured_separate_views_alpha_output_and_canonical_static_keys(self):
        left=self.fixture('stereo_L.png',(255,0,0,128))
        self.fixture('stereo_R.png',(0,255,0,64))
        ordinary=images.describe(left)
        self.assertEqual(ordinary.key,images.describe(left,layer=0,pass_name=0,view=0,
            frame_settings=images.FrameSettings(5,25,7,True),scene_frame=81).key)
        alpha=images.read(images.describe(left,channel='ALPHA'))
        np.testing.assert_allclose(alpha.rgba[0,0],(128/255,128/255,128/255,1.))
        left.use_multiview=True;left.views_format='INDIVIDUAL'
        first=images.read(images.describe(left))
        right=images.read(images.describe(left,view='right'))
        np.testing.assert_allclose(first.rgba[0,0],(1,0,0,128/255),atol=4e-5)
        np.testing.assert_allclose(right.rgba[0,0],(0,1,0,64/255),atol=4e-5)
        self.assertIn('right',right.label)
        with self.assertRaisesRegex(ValueError,'unavailable'):
            images.read(images.describe(left,view='missing'))

    def test_multilayer_selected_pass_and_view_use_private_source_only(self):
        path=os.path.join(self.directory.name,'layered.exr')
        channels={}
        for prefix,color in (('Alpha.Combined.left',(.5,0,0,.5)),
                             ('Alpha.Combined.right',(0,.5,0,.5)),
                             ('Alpha.Diffuse.left',(0,0,.5,.5)),
                             ('Alpha.Diffuse.right',(.5,.5,0,.5)),
                             ('Beta.Combined.left',(.25,.25,.25,.5)),
                             ('Beta.Combined.right',(.1,.2,.3,.5))):
            channels.update({prefix+'.'+channel:value for channel,value in zip('RGBA',color)})
        exr_fixture(path,channels,('left','right'))
        image=bpy.data.images.load(path,check_existing=False)
        before=(len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups),image.filepath,image.is_dirty)
        result=images.read(images.describe(image,layer='Alpha',pass_name='Diffuse',view='right',premultiply=True))
        np.testing.assert_allclose(result.rgba[0,0],(.5,.5,0,.5))
        self.assertIn('right',result.label)
        default=images.read(images.describe(image,layer=0,pass_name=0,view=0,premultiply=False))
        np.testing.assert_allclose(default.rgba[0,0],(1,0,0,.5))
        self.assertEqual(before,(len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups),image.filepath,image.is_dirty))
        with self.assertRaisesRegex(ValueError,'no RGB pixels'):
            images.read(images.describe(image,layer='Alpha',view='missing'))

    def test_dirty_uninitialized_multiview_refuses_stored_fallback_and_preserves_source(self):
        image=self.fixture('painted-stereo.png',(128,64,32,255),4,2)
        image.use_multiview=True;image.views_format='STEREO_3D'
        image.stereo_3d_format.display_mode='SIDEBYSIDE'
        image.pixels[0]=.25
        self.assertTrue(image.is_dirty)
        before=(tuple(image.pixels),image.filepath,image.file_format,image.is_dirty,
            len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups))
        with self.assertRaisesRegex(ValueError,'no initialized resident pixels'):
            images.read(images.describe(image,view='right'))
        self.assertEqual(before,(tuple(image.pixels),image.filepath,image.file_format,image.is_dirty,
            len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups)))

    def test_uninitialized_stereo_packing_decodes_both_views_without_user_mutation(self):
        colors=((128,0,0,128),(0,64,0,128))
        for mode,width,height,pixels in (
            ('SIDEBYSIDE',4,2,(colors[0]*2+colors[1]*2)*2),
            ('TOPBOTTOM',2,4,colors[0]*4+colors[1]*4),
            ('INTERLACE',2,2,colors[0]*2+colors[1]*2),
            ('ANAGLYPH',2,2,(128,64,0,128)*4)):
            with self.subTest(mode=mode):
                path=os.path.join(self.directory.name,mode+'.png');png(path,width,height,pixels)
                image=bpy.data.images.load(path,check_existing=False)
                tuple(image.size)
                image.use_multiview=True;image.views_format='STEREO_3D'
                image.stereo_3d_format.display_mode=mode
                before=(image.filepath,image.colorspace_settings.name,image.is_dirty,
                        len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups))
                for view in (0,1):
                    result=images.read(images.describe(image,view=view))
                    covered=result.rgba[result.rgba[...,3]>0]
                    self.assertGreater(len(covered),0)
                    expected=np.array(colors[view],np.float64)/255
                    expected[:3]=np.where(expected[:3]<=.04045,expected[:3]/12.92,((expected[:3]+.055)/1.055)**2.4)
                    np.testing.assert_allclose(covered,np.broadcast_to(expected,covered.shape),atol=3e-5)
                self.assertEqual(before,(image.filepath,image.colorspace_settings.name,image.is_dirty,
                    len(bpy.data.images),len(bpy.data.scenes),len(bpy.data.node_groups)))

    def test_stereo_sequence_decodes_requested_frame_before_view_selection(self):
        for frame,left,right in ((1,(255,0,0,255),(0,255,0,255)),(2,(0,0,255,255),(255,255,0,255))):
            png(os.path.join(self.directory.name,f'stereo{frame:04}.png'),4,2,(left*2+right*2)*2)
        image=bpy.data.images.load(os.path.join(self.directory.name,'stereo0001.png'),check_existing=False)
        tuple(image.size);image.source='SEQUENCE';image.use_multiview=True;image.views_format='STEREO_3D'
        image.stereo_3d_format.display_mode='SIDEBYSIDE'
        result=images.read(images.describe(image,frame_settings=images.FrameSettings(duration=2),scene_frame=2,view='right'))
        np.testing.assert_allclose(result.rgba[0,0],(1,1,0,1),atol=4e-5)
        self.assertIn('frame 2',result.label)
        self.assertIn('right',result.label)

    def test_unlayered_multiview_exr_uses_first_view_and_explicit_other_view(self):
        path=os.path.join(self.directory.name,'stereo.exr')
        channels={}
        for prefix,color in (('',(1,0,0,1)),('right.',(0,1,0,1))):
            channels.update({prefix+channel:value for channel,value in zip('RGBA',color)})
        exr_fixture(path,channels,('left','right'))
        image=bpy.data.images.load(path,check_existing=False)
        for view,color in ((0,(1,0,0,1)),('right',(0,1,0,1))):
            result=images.read(images.describe(image,layer=0,pass_name=0,view=view))
            np.testing.assert_allclose(result.rgba[0,0],color)

    def test_live_reads_defer_under_native_callback_and_detect_clean_reload(self):
        image=self.fixture('reload.png',(255,0,0,255));desc=images.describe(image)
        first=images.read(desc)
        guard=component('graph.output_guard')
        with guard.native_callback(),self.assertRaises(guard.PublicationDeferred):
            images.read(desc,force=True)
        png(image.filepath,3,2,(0,255,0,255));image.reload()
        self.assertFalse(image.is_dirty)
        result=images.read(desc,force=True)
        self.assertGreater(result.revision,first.revision)
        np.testing.assert_allclose(result.rgba[0,0],(0,1,0,1),atol=4e-5)

    def test_removed_and_retired_descriptors_do_not_rebind_names(self):
        image=self.fixture('source.png');desc=images.describe(image)
        bpy.data.images.remove(image)
        self.fixture('source.png')
        with self.assertRaises(ReferenceError):images.read(desc)
        image=self.fixture('another.png');desc=images.describe(image)
        images.clear()
        with self.assertRaises(ReferenceError):images.read(desc)
