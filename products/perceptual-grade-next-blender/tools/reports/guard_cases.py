"""Shared native guard fixtures and independent reference probe corpora."""
from unittest import mock
import numpy as np
from color_tools.template_build import guard_graph
from color_tools.template_build.guard_graph import GuardedSockets,hk_guard,output_guard
from color_tools.template_build.color_graph import ColorSockets
from color_tools.template_build.graph import Graph,BuiltGrade,count_nodes
from color_tools.perceptual_grade_reference.responses import signed_hk
from color_tools.perceptual_grade_reference.cube_guard import guard as reference_cube
from color_tools.perceptual_grade_core.model.hk_guard import guard as reference_hk

def guard_builder(mode,reference_energy=100.):
    def build(prepared,tree_type):
        import bpy
        tree=bpy.data.node_groups.new('Isolated native guard',tree_type);g=Graph(tree,prepared)
        tree.interface.new_socket(name='Color',in_out='INPUT',socket_type='NodeSocketColor')
        if tree_type=='ShaderNodeTree':
            tree.interface.new_socket(name='Alpha',in_out='INPUT',socket_type='NodeSocketFloat')
        tree.interface.new_socket(name='Color',in_out='OUTPUT',socket_type='NodeSocketColor')
        for name in ('Alpha','Decode Valid','Pole Margin'):
            tree.interface.new_socket(name=name,in_out='OUTPUT',socket_type='NodeSocketFloat')
        source=tree.nodes.new('NodeGroupInput');out=tree.nodes.new('NodeGroupOutput')
        first,a,b=g.split(source.outputs['Color']);c=g.hypot(a,b)
        if mode.startswith('hk'):
            h=first;base=g.mul(np.sqrt(66),g.sqrt(c));u=g.sub(h,base)
            energy=g.mul(u,g.add(g.abs(u),g.mul(2,base)))
        else:
            energy=first;base=g.sqrt(g.mul(66,c))
            magnitude=g.sqrt(g.add(g.abs(energy),g.mul(66,c)))
            h=g.select(g.lt(energy,0),g.sub(g.mul(2,base),magnitude),magnitude)
        state=GuardedSockets(g,h,a,b,energy,reference_energy)
        if mode=='hk_color':
            state=ColorSockets(g,h,a,b,energy,reference_energy,h,c,energy,chroma_value=c,offset_value=u)
        if mode.startswith('hk'):
            result=hk_guard(g,state)
            color,valid,margin=result.q,result.energy,result.chroma
        else:
            if mode=='boundary_native_fallback':
                original=guard_graph._legal
                calls=0
                def reject_trial(graph,vector):
                    nonlocal calls
                    calls+=1
                    return original(graph,vector) if calls==1 else 0.
                with mock.patch.object(guard_graph,'_legal',side_effect=reject_trial):
                    result=output_guard(g,state)
                assert calls==2
            else:
                result=output_guard(g,state)
            color,valid,margin=(result.native_color,result.valid,result.radius) if mode.startswith('boundary_native') else (result.color,result.valid,result.pole_margin)
        alpha=result.pole_margin if mode=='boundary_native_fallback' else 1.
        for value,name in ((color,'Color'),(valid,'Decode Valid'),(margin,'Pole Margin'),(alpha,'Alpha')):
            g.connect(value,out.inputs[name])
        return BuiltGrade(tree,tuple(g.images),tuple(g.helper_groups),prepared,count_nodes(tree,g.images))
    return build


def hk_probes():
    rng=np.random.default_rng(812)
    h=10**rng.uniform(-2,3,256);ratio=rng.uniform(0,4,256);c=ratio*h*h/66;angle=rng.uniform(-np.pi,np.pi,256)
    q=np.column_stack((h,c*np.cos(angle),c*np.sin(angle))).astype(np.float32)
    q[:6]=[[0,0,0],[10,0,0],[-10,20,0],[5,20,0],[10,50/66,0],[10,50/66+.0001,0]]
    c=np.hypot(q[:,1].astype(float),q[:,2].astype(float));base=np.sqrt(66*c);u=q[:,0]-base;e=u*(abs(u)+2*base)
    expected,energy=reference_hk(q,e,100.)
    return np.column_stack((q,np.ones(256,np.float32))),expected,energy


def boundary_probes(boundary,reference):
    b=boundary;rng=np.random.default_rng(591)
    t=np.r_[rng.uniform(.0001,.9999,220),np.geomspace(1e-7,.001,18),1-np.geomspace(1e-7,.001,18)]
    hue=rng.uniform(-np.pi,np.pi,256)
    t[7:11]=[.509765625,.972265625,.974609375,.9692850682864027]
    hue[7:11]=[.9142525495798421,1.9123627155640994,1.9082721001297376,1.9289733852756097]
    ja=b.white*t**b.gamma
    cap=b.response_white*t*(1-t)*b.exact(t,hue);multiple=rng.uniform(.1,5,256);multiple[7:11]=3.;c=cap*multiple
    source=np.column_stack((ja,c*np.cos(hue),c*np.sin(hue))).astype(np.float32)
    source[:7]=[[0,1,0],[-10,4,1],[b.white*2,100,100],[50,0,0],[0,0,0],[b.white,0,0],[1e-12,1e-12,-1e-12]]
    source[11]=[1e-20,1e-12,-1e-12]
    source[:,0]=source[:,0]*abs(source[:,0])
    energy=source[:,0].astype(float);c=np.hypot(source[:,1].astype(float),source[:,2].astype(float))
    ja=np.sign(energy)*np.sqrt(abs(energy))
    q=np.column_stack((signed_hk(ja,c),source[:,1:]))
    projected,_,native=reference_cube(reference,q,energy)
    radius=np.hypot(projected[:,1],projected[:,2])
    radial=(energy>0)&(energy<b.white*b.white)&(c>radius+1e-10)
    values=np.column_stack((source,np.ones(256,np.float32)))
    return dict(values=values,energy=energy,chroma=c,radius=radius,radial=radial,native=native)
