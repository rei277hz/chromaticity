"""Isolated native evaluation fixtures for this library, with raw signed AOVs."""
from dataclasses import asdict
from pathlib import Path
import tempfile
import time
import numpy as np


def _image(bpy, name, values, width, height):
    image = bpy.data.images.new(name, width=width, height=height, float_buffer=True, alpha=True)
    image.colorspace_settings.name = 'Non-Color'
    image.alpha_mode = 'CHANNEL_PACKED'
    image.use_half_precision = False
    image.pixels.foreach_set(np.asarray(values,dtype=np.float32).ravel())
    image.update()
    return image


def _file_output(tree, directory, name, socket):
    node = tree.nodes.new('CompositorNodeOutputFile')
    node.directory = str(directory)
    node.file_name = name
    node.format.media_type = 'IMAGE'
    node.format.file_format = 'OPEN_EXR'
    node.format.color_depth = '32'
    node.format.color_mode = 'RGBA'
    node.format.exr_codec = 'ZIP'
    node.save_as_render = False
    node.file_output_items.new('RGBA','Image')
    tree.links.new(socket,node.inputs['Image'])


def _half_precision_split(tree, socket):
    """Encode float32 values into three EEVEE float16 AOVs for faithful readback.

    EEVEE 5.2 stores color AOVs as RGBA16F. A raw AOV comparison therefore
    measures half precision, not the shader graph's float arithmetic. Store an
    exactly representable coarse mantissa, a scaled residual, and integer
    exponent. This avoids half overflow for valid HDR output as well as half
    underflow near black. These nodes belong to readback, not the grade graph.
    """
    separate=tree.nodes.new('ShaderNodeSeparateXYZ')
    tree.links.new(socket,separate.inputs[0])
    high=[];low=[];exponents=[]
    def math_node(operation,*values):
        node=tree.nodes.new('ShaderNodeMath');node.operation=operation
        for inp,value in zip(node.inputs,values):
            if hasattr(value,'as_pointer'):tree.links.new(value,inp)
            else:inp.default_value=float(value)
        return node.outputs[0]
    for value in separate.outputs:
        absolute=math_node('ABSOLUTE',value)
        safe=math_node('MAXIMUM',absolute,2.**-126)
        exponent=math_node('MINIMUM',127.,math_node('FLOOR',math_node('LOGARITHM',safe,2.)))
        scale=math_node('POWER',2.,exponent)
        normalized=math_node('MULTIPLY',math_node('DIVIDE',value,scale),1024.)
        coarse=math_node('FLOOR',normalized)
        residual=math_node('MULTIPLY',math_node('SUBTRACT',normalized,coarse),1024.)
        high.append(coarse);low.append(residual);exponents.append(exponent)
    outputs=[]
    for values in (high,low,exponents):
        combine=tree.nodes.new('ShaderNodeCombineXYZ')
        for value,socket_out in zip(values,combine.inputs):tree.links.new(value,socket_out)
        outputs.append(combine.outputs[0])
    return tuple(outputs)


def _read(bpy, directory, name, count):
    paths = list(Path(directory).glob(name+'Image*.exr'))
    if len(paths) != 1:
        raise AssertionError(f'Expected one {name} float output, found {paths}')
    image = bpy.data.images.load(str(paths[0]),check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        return np.asarray(image.pixels[:],dtype=np.float64).reshape(-1,4)[:count]
    finally:
        bpy.data.images.remove(image)


class NativeFixture:
    """Disposable scene, never a product registration or a user's project."""
    def __init__(self, prepared, values, context='compositor', *, engine='CYCLES', device='CPU',
                 precision='FULL', threads=None, builder=None):
        import bpy
        from color_tools.kernel.graph import build_group
        initialization_start = time.perf_counter()
        self.bpy = bpy
        self.values = np.asarray(values,dtype=np.float32)
        if self.values.ndim != 2 or self.values.shape[1] != 4:
            raise ValueError('Native input must be Nx4 float pixels')
        self.count = len(values)
        self.width = int(np.ceil(np.sqrt(self.count)))
        self.height = int(np.ceil(self.count/self.width))
        padded = np.zeros((self.width*self.height,4),dtype=np.float32)
        padded[:self.count] = values
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        self.scene = scene
        scene.render.engine = engine
        if threads is not None:
            if threads < 1:
                raise ValueError('Native render thread count must be positive')
            scene.render.threads_mode = 'FIXED'
            scene.render.threads = threads
        if engine in {'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'}:
            # This is a pixel-parity fixture, not a presentation render. TAA's
            # subpixel jitter selects neighboring nearest-filter texels across
            # samples, and the normal reconstruction filter blends edge pixels;
            # both corrupt the one-input-pixel/one-shader-evaluation mapping.
            scene.eevee.taa_samples = 1
            scene.eevee.taa_render_samples = 1
            scene.eevee.use_taa_reprojection = False
            scene.render.filter_size = .01
        if engine == 'CYCLES':
            scene.cycles.device = 'CPU'
            scene.cycles.samples = 1
            scene.cycles.use_denoising = False
            scene.cycles.use_adaptive_sampling = False
            scene.cycles.filter_width = .01
        scene.render.resolution_x, scene.render.resolution_y = self.width,self.height
        scene.render.resolution_percentage = 100
        scene.render.compositor_device = device
        scene.render.compositor_precision = precision
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_depth = '32'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_management = 'OVERRIDE'
        scene.render.image_settings.linear_colorspace_settings.name = 'scene_linear'
        scene.view_settings.exposure = 0
        scene.view_settings.gamma = 1
        camera = bpy.data.objects.new('Evaluation Camera',bpy.data.cameras.new('Evaluation Camera'))
        scene.collection.objects.link(camera)
        scene.camera = camera
        camera.location = (0,0,2)
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = 2
        world = bpy.data.worlds.new('Evaluation World')
        world.use_nodes = True
        world.node_tree.nodes['Background'].inputs['Color'].default_value = (0,0,0,1)
        scene.world = world
        self.input_image = _image(bpy,'Evaluation Inputs',padded,self.width,self.height)
        self.split_aov = context == 'shader' and engine in {'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'}
        comp = bpy.data.node_groups.new('Evaluation Output','CompositorNodeTree')
        comp.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        out = comp.nodes.new('NodeGroupOutput')
        scene.compositing_node_group = comp
        self.comp = comp
        tree_type = 'CompositorNodeTree' if context == 'compositor' else 'ShaderNodeTree'
        graph_start = time.perf_counter()
        self.built = (build_group if builder is None else builder)(prepared,tree_type=tree_type)
        graph_end = time.perf_counter()
        if context == 'compositor':
            source = comp.nodes.new('CompositorNodeImage')
            source.image = self.input_image
            node = comp.nodes.new('CompositorNodeGroup')
            node.node_tree = self.built.tree
            comp.links.new(source.outputs['Image'],node.inputs['Color'])
            color = node.outputs['Color']
            diagnostic = comp.nodes.new('ShaderNodeCombineXYZ')
            for input_name,output_name in zip(('X','Y','Z'),('Decode Valid','Pole Margin','Alpha')):
                comp.links.new(node.outputs[output_name],diagnostic.inputs[input_name])
            diag = diagnostic.outputs[0]
            saturation = node.outputs.get('Saturated')
            if saturation is not None:
                # A constant scalar has no image domain and File Output skips
                # it. A second, ignored channel anchors diagnostic transport
                # to the input image without changing the saturation value.
                domain = comp.nodes.new('ShaderNodeCombineXYZ')
                comp.links.new(saturation, domain.inputs['X'])
                comp.links.new(source.outputs['Image'], domain.inputs['Y'])
                saturation = domain.outputs[0]
        elif context == 'shader':
            mesh = bpy.data.meshes.new('Evaluation Plane')
            aspect = self.height/self.width
            mesh.from_pydata([(-1,-aspect,0),(1,-aspect,0),(1,aspect,0),(-1,aspect,0)],[],[(0,1,2,3)])
            mesh.update()
            uv = mesh.uv_layers.new()
            for loop,coords in zip(uv.data,((0,0),(1,0),(1,1),(0,1))): loop.uv=coords
            obj=bpy.data.objects.new('Evaluation Plane',mesh)
            scene.collection.objects.link(obj)
            material=bpy.data.materials.new('Evaluation Shader')
            material.use_nodes=True
            obj.data.materials.append(material)
            tree=material.node_tree
            tree.nodes.clear()
            source=tree.nodes.new('ShaderNodeTexImage')
            source.image=self.input_image
            source.interpolation='Closest'
            coordinate=tree.nodes.new('ShaderNodeTexCoord')
            tree.links.new(coordinate.outputs['UV'],source.inputs['Vector'])
            node=tree.nodes.new('ShaderNodeGroup')
            node.node_tree=self.built.tree
            tree.links.new(source.outputs['Color'],node.inputs['Color'])
            tree.links.new(source.outputs['Alpha'],node.inputs['Alpha'])
            emission=tree.nodes.new('ShaderNodeEmission')
            output=tree.nodes.new('ShaderNodeOutputMaterial')
            tree.links.new(emission.outputs[0],output.inputs['Surface'])
            diagnostic=tree.nodes.new('ShaderNodeCombineXYZ')
            for input_name,output_name in zip(('X','Y','Z'),('Decode Valid','Pole Margin','Alpha')):
                tree.links.new(node.outputs[output_name],diagnostic.inputs[input_name])
            if self.split_aov:
                raw_high,raw_low,raw_exponent=_half_precision_split(tree,node.outputs['Color'])
                diagnostic_high,diagnostic_low,diagnostic_exponent=_half_precision_split(tree,diagnostic.outputs[0])
                aov_sources=(('RawGradeHigh',raw_high),('RawGradeLow',raw_low),('RawGradeExponent',raw_exponent),
                             ('GradeDiagnosticHigh',diagnostic_high),('GradeDiagnosticLow',diagnostic_low),
                             ('GradeDiagnosticExponent',diagnostic_exponent))
            else:
                aov_sources=(('RawGrade',node.outputs['Color']),('GradeDiagnostic',diagnostic.outputs[0]))
            has_saturation = node.outputs.get('Saturated') is not None
            if has_saturation:
                aov_sources += (('GradeSaturation', node.outputs['Saturated']),)
            for name,socket in aov_sources:
                aov=bpy.context.view_layer.aovs.add()
                aov.name=name
                aov.type='COLOR'
                sink=tree.nodes.new('ShaderNodeOutputAOV')
                sink.aov_name=name
                tree.links.new(socket,sink.inputs['Color'])
            bpy.context.view_layer.update_render_passes()
            passes=comp.nodes.new('CompositorNodeRLayers')
            if self.split_aov:
                color,diag=passes.outputs['RawGradeHigh'],passes.outputs['GradeDiagnosticHigh']
                self.color_low,self.diag_low=passes.outputs['RawGradeLow'],passes.outputs['GradeDiagnosticLow']
                self.color_exponent,self.diag_exponent=passes.outputs['RawGradeExponent'],passes.outputs['GradeDiagnosticExponent']
            else:
                color,diag=passes.outputs['RawGrade'],passes.outputs['GradeDiagnostic']
            saturation = passes.outputs['GradeSaturation'] if has_saturation else None
        else:
            raise ValueError('context must be compositor or shader')
        comp.links.new(color,out.inputs['Image'])
        self.directory=tempfile.TemporaryDirectory(prefix='grade-nodes-')
        _file_output(comp,self.directory.name,'color',color)
        _file_output(comp,self.directory.name,'diagnostic',diag)
        self.has_saturation = saturation is not None
        if self.has_saturation:
            _file_output(comp,self.directory.name,'saturation',saturation)
        if self.split_aov:
            _file_output(comp,self.directory.name,'colorlow',self.color_low)
            _file_output(comp,self.directory.name,'diagnosticlow',self.diag_low)
            _file_output(comp,self.directory.name,'colorexponent',self.color_exponent)
            _file_output(comp,self.directory.name,'diagnosticexponent',self.diag_exponent)
        self.context=context
        initialization_end = time.perf_counter()
        self.initialization_timings = dict(
            scene_and_input_seconds=graph_start-initialization_start,
            grade_graph_seconds=graph_end-graph_start,
            output_fixture_seconds=initialization_end-graph_end,
            total_seconds=initialization_end-initialization_start)

    def render(self):
        start=time.perf_counter()
        self.bpy.ops.render.render()
        elapsed=time.perf_counter()-start
        color=_read(self.bpy,self.directory.name,'color',self.count)
        diag=_read(self.bpy,self.directory.name,'diagnostic',self.count)
        if self.split_aov:
            color_low=_read(self.bpy,self.directory.name,'colorlow',self.count)
            diag_low=_read(self.bpy,self.directory.name,'diagnosticlow',self.count)
            color_exponent=_read(self.bpy,self.directory.name,'colorexponent',self.count)
            diag_exponent=_read(self.bpy,self.directory.name,'diagnosticexponent',self.count)
            color[:,:3]=(color[:,:3]+color_low[:,:3]/1024.)*np.exp2(color_exponent[:,:3]-10.)
            diag[:,:3]=(diag[:,:3]+diag_low[:,:3]/1024.)*np.exp2(diag_exponent[:,:3]-10.)
        result = dict(rgb=color[:,:3],alpha=diag[:,2],valid=diag[:,0],margin=diag[:,1],
                    saturated=(_read(self.bpy,self.directory.name,'saturation',self.count)[:,0]
                               if self.has_saturation else np.zeros(self.count)),
                    embedded_alpha=color[:,3],seconds=elapsed,stats=asdict(self.built.stats))
        result['readback_seconds'] = time.perf_counter()-start-elapsed
        result['fixture_seconds'] = time.perf_counter()-start
        return result

    def close(self):
        self.bpy.ops.wm.read_factory_settings(use_empty=True)
        self.directory.cleanup()


def evaluate(prepared,values,context='compositor',**kwargs):
    fixture=NativeFixture(prepared,values,context,**kwargs)
    try:
        return fixture.render()
    finally:
        fixture.close()
