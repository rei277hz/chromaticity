"""Optional Blender GPU host adapter for the reference-owned shader builders.

Importing this module is host-independent. Constructing a program requires an
initialized Blender GPU context; errors propagate without a CPU fallback.
"""

import time
import numpy as np

from . import bake_gpu, bake_inverse_gpu, boundary_gpu
from ..perceptual_grade_core.model.boundary_polynomial import expand

WIDTH=boundary_gpu.WIDTH
BATCH=boundary_gpu.BATCH


class BoundaryProgram:
    """Small actual compute harness; callers initialize Blender's GPU context."""
    def __init__(self,data,source_builder=boundary_gpu.source,with_parameters=False,expanded=None):
        import gpu
        self.gpu=gpu
        expanded=expand(data) if expanded is None else expanded
        values,offsets=boundary_gpu.pack(data,expanded)
        codes=expanded['face_codes'];size=codes.shape[-1]
        # Blender accepts FLOAT upload buffers. R16 stores normalized uint16;
        # rounding a fetched value times 65535 recovers the original code.
        atlas=codes.reshape(-1,size).astype(np.float32)/np.float32(65535)
        self.lookup_bytes=values.nbytes+codes.nbytes
        if self.lookup_bytes>1024*1024:raise MemoryError('Boundary lookup exceeds 1 MiB')
        self.cache=gpu.types.GPUTexture((WIDTH,len(values)),format='RGBA32F',
            data=gpu.types.Buffer('FLOAT',values.shape,values))
        self.face_atlas=gpu.types.GPUTexture((size,len(atlas)),format='R16',
            data=gpu.types.Buffer('FLOAT',atlas.shape,atlas))
        info=gpu.types.GPUShaderCreateInfo();info.local_group_size(64,1,1)
        info.sampler(0,'FLOAT_2D','input_pixels');info.sampler(1,'FLOAT_2D','boundary_cache')
        info.sampler(3,'FLOAT_2D','face_atlas')
        info.image(0,'RGBA32F','FLOAT_2D','output_pixels',qualifiers={'WRITE'})
        self.with_parameters=with_parameters
        if with_parameters:
            info.sampler(2,'FLOAT_2D','grade_parameters')
            info.push_constant('INT','operation')
        info.push_constant('INT','sample_count');info.compute_source(source_builder(data,offsets,expanded))
        start=time.perf_counter();self.shader=gpu.shader.create_from_info(info)
        self.compile_seconds=time.perf_counter()-start
        self.output=gpu.types.GPUTexture((WIDTH,BATCH//WIDTH),format='RGBA32F')

    def evaluate(self,points,operation=2):
        gpu=self.gpu;points=np.asarray(points,dtype=np.float32);points=points.reshape(-1,points.shape[-1]);output=[]
        for start in range(0,len(points),BATCH):
            part=points[start:start+BATCH]
            values=np.zeros((BATCH//WIDTH,WIDTH,4),dtype=np.float32)
            values.reshape(-1,4)[:len(part),:part.shape[-1]]=part
            image=gpu.types.GPUTexture((WIDTH,BATCH//WIDTH),format='RGBA32F',
                data=gpu.types.Buffer('FLOAT',values.shape,values))
            self.shader.bind();self.shader.uniform_sampler('input_pixels',image)
            self.shader.uniform_sampler('boundary_cache',self.cache)
            self.shader.uniform_sampler('face_atlas',self.face_atlas)
            if self.with_parameters:
                self.shader.uniform_sampler('grade_parameters',self.parameters)
                self.shader.uniform_int('operation',operation)
            self.shader.image('output_pixels',self.output);self.shader.uniform_int('sample_count',len(part))
            gpu.compute.dispatch(self.shader,(len(part)+63)//64,1,1)
            output.append(np.array(self.output.read(),dtype=np.float32).reshape(-1,4)[:len(part)].copy())
        return np.concatenate(output) if output else np.empty((0,4),dtype=np.float32)


class ForwardProgram(BoundaryProgram):
    def __init__(self,kernel):
        super().__init__(kernel.data,bake_gpu.source,True,kernel.table.expanded)
        self.set_kernel(kernel)

    def set_kernel(self,kernel):
        values=bake_gpu.parameters(kernel)
        self.parameters=self.gpu.types.GPUTexture((256,1),format='R32F',
            data=self.gpu.types.Buffer('FLOAT',(1,256),values))


class InverseProgram(BoundaryProgram):
    def __init__(self,inverse):
        k=inverse.kernel
        super().__init__(k.data,bake_inverse_gpu.source,True,k.table.expanded)
        self.set_inverse(inverse)

    def evaluate(self,points,operation=0):
        if operation in (0,1,5) and self.missing_tone_table:
            raise RuntimeError('Inverse tone table must be prepared before compute evaluation')
        return super().evaluate(points,operation)

    def set_inverse(self,inverse):
        start=time.perf_counter()
        k=inverse.kernel;values=bake_gpu.parameters(k)
        layout=bake_gpu.LAYOUT
        def put(name,value):
            value=np.asarray(value,dtype='f4').reshape(-1);start=layout[name]
            values[start:start+len(value)]=value
        put('CANONICAL_FIRST',inverse.canonical[:,0]);put('CANONICAL_LAST',inverse.canonical[:,2])
        put('Y_WEIGHTS',inverse.weights);put('INVERSE_SIMPLE',inverse.simple)
        put('DIRECTIONAL',k.directional_drivers)
        table=inverse.tone_table
        self.missing_tone_table=k.tone.active and table is None
        self.tone_lookup_bytes=0 if table is None else table.bytes
        if table is not None:
            put('TONE_TABLE',[table.scale,table.tail_h,table.slope,table.intercept,len(table.nodes)])
            packed=np.zeros((1+(table.nodes.size+255)//256,256),dtype='f4')
            packed[0]=values;packed[1:].reshape(-1)[:table.nodes.size]=table.nodes.ravel()
        else:packed=values.reshape(1,256)
        self.parameter_bytes=packed.nbytes
        self.parameters=self.gpu.types.GPUTexture((256,len(packed)),format='R32F',
            data=self.gpu.types.Buffer('FLOAT',packed.shape,packed))
        self.parameter_upload_seconds=time.perf_counter()-start
        self.parameter_upload_total_seconds=getattr(self,'parameter_upload_total_seconds',0.)+self.parameter_upload_seconds
