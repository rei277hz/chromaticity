"""Emit the existing D65 coefficient resource as bounded DCTL constant arrays."""
import numpy as np
from color_tools.perceptual_grade_core.model.creases import topology
from color_tools.perceptual_grade_core.model import linear


def number(value):
    text=format(float(np.float32(value)),'.9g')
    return text+('' if '.' in text or 'e' in text else '.0')+'f'


def generate(data):
    heights,rings=topology(data['vertex_t'],data['edges'],data['edge_faces'],data['face_limits'])
    arrays={name.upper():np.asarray(data[name],dtype='f4') for name in
        ('edge_knots','edge_coefficients','vertex_t','sector_t','sector_s','sectors',
         'guard_knots','guard_coefficients','knots','profile') if name in data}
    arrays['HEIGHTS']=heights.astype('f4')
    arrays['EDGES']=np.sum(data['edges'].astype('u4')<<np.array([0,8],dtype='u4'),axis=-1,dtype='u4')
    arrays['TOPOLOGY']=np.sum(rings.astype('u4')<<np.array([0,8,16,24],dtype='u4'),axis=-1,dtype='u4')
    limits=data['vertex_t'][data['face_limits']]
    arrays['FACE_BOUNDS']=np.column_stack((limits[:,0],limits[:,1]-limits[:,0])).astype('f4')
    # Budget all declared arrays with independent 16-byte alignment. Scalar
    # contexts/matrices below are immediate expressions, not extra data tables.
    size=sum((v.nbytes+15)//16*16 for v in arrays.values())
    if size>=65536:raise ValueError('DCTL constants exceed 64 KiB')
    source=f'// Declared boundary constants, including 16-byte array alignment: {size} bytes.\n#define PG_CONSTANT_BYTES {size}\n'
    for name,value in [('EDGE_KNOT_COUNT',len(data['edge_knots'])),('EDGE_COEFFICIENT_COUNT',data['edge_coefficients'].shape[1]),
                       ('HEIGHT_KNOT_COUNT',data['sector_t'].shape[1]),('HUE_KNOT_COUNT',len(data['sector_s'])),
                       ('HEIGHT_COEFFICIENT_COUNT',data['sectors'].shape[1]),('HUE_COEFFICIENT_COUNT',data['sectors'].shape[2]),
                       ('GUARD_KNOT_COUNT',len(data.get('guard_knots',[]))),('PROFILE_COUNT',len(data.get('knots',[])))]:
        if value>512 or (name=='PROFILE_COUNT' and value>64):raise ValueError('DCTL spline addressing budget exceeded')
        source+=f'#define PG_{name} {value}\n'
    for name,value in arrays.items():
        integer=value.dtype==np.dtype('u4');kind='unsigned int' if integer else 'float'
        encode=(lambda x:str(int(x))+'u') if integer else number
        flat=list(map(encode,value.ravel()))
        source+=f'__CONSTANT__ {kind} PG_{name}[{len(flat)}] = {{\n'
        source+='\n'.join('    '+','.join(flat[i:i+12])+',' for i in range(0,len(flat),12))+'\n};\n'
    for name,value in [('WHITE',data['white']),('FL',data['fl']),('AW',data['aw']),
                       ('GAMMA',.525*(1.48+np.sqrt(.1)))]:
        source+=f'#define PG_{name} {number(value)}\n'
    p=np.float32(data['fl'])*np.float32(1024);p=np.power(p,np.float32(.42))
    source+=f'#define PG_RW {number(400*p/(27.13+p))}\n'
    to_xyz=np.asarray(linear.mm(linear.bradford(linear.ACES_WHITE,linear.D65),linear.rgb_to_xyz('ACEScg')))
    matrices={'to_rgb':data['matrices'][0],'to_cones':np.linalg.inv(data['matrices'][0]),
              'native_to_xyz':to_xyz,'xyz_to_native':np.linalg.inv(to_xyz),
              'canonical':np.asarray(linear.xyz_to_rgb('Linear Rec.709'))@to_xyz}
    vec=lambda x:'make_float3('+','.join(map(number,x))+')'
    for name,matrix in matrices.items():
        rows=','.join(vec(row) for row in matrix)
        source+=f'__DEVICE__ ColorMat pg_{name}_matrix() {{ return color_mat({rows}); }}\n'
    source+='__DEVICE__ float3 pg_y_weights() { return '+vec(linear.rgb_to_xyz('ACEScg')[1])+'; }\n'
    m=np.asarray(data['matrices'][0],dtype='f4')
    effective=np.column_stack((m[:,0],1-m[:,0]-m[:,2],m[:,2])).astype(float)
    inverse=np.linalg.inv(effective)
    limits=np.stack((1024*np.minimum(inverse,0).sum(axis=1),1024*np.maximum(inverse,0).sum(axis=1)))
    power=np.power(abs(limits)*float(np.float32(data['fl'])),.42)
    limits=np.sign(limits)*400*power/(27.13+power)
    source+='__DEVICE__ float3 pg_response_low() {return '+vec(limits[0])+';}\n'
    source+='__DEVICE__ float3 pg_response_high() {return '+vec(limits[1])+';}\n' 
    return source,size
