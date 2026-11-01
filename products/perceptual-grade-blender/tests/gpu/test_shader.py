"""Required GPU native Shader LUT rendering against independent reference vertices."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import tempfile
import numpy as np
import bpy
nodes = _component('graph.nodes')
from color_tools.perceptual_grade_core.model import lut as cubes
from tests.support import reference as oracle
from tests.support.blender import BlenderTest, render, render_scene
from tests.support.gpu import initialize


class ShaderTests(BlenderTest):
    def test_eevee_complete_gpu_baked_lut_on_gpu(self):
        initialize()
        # Background shaders clamp negative scene components. Native AP1
        # keeps the valid export measurable, including colors outside Rec.709.
        bpy.ops.wm.set_working_color_space(working_space='ACEScg')
        scene,world=render_scene();scene.render.engine='BLENDER_EEVEE'
        grade=nodes.create_grade(world.node_tree)
        nodes.write_values(grade,{'exposure':.3,'cr_balance':.05})
        nodes.write_tone(grade,{'input_midtones':42,'input_white':230})
        nodes.write_chromatic(grade,{'global_gain':.2,'hue_1':8,'adaptance_a_1':.4})
        world.node_tree.links.new(grade.outputs['Color'],world.node_tree.nodes['Background'].inputs['Color'])
        probes=[cubes.lattice()[index]
                for index in (16*65**2+20*65+24,32*65**2+30*65+28,65**3-1)]
        native=np.array([[128,128,128],[512,200,50],[743.19103667,743.19103667,743.19103667],
                         [1024,400,100],[-.01,.4,1],[1026,1,.4]])
        probes.extend(native)
        with tempfile.TemporaryDirectory() as directory:
            for i,rgb in enumerate(probes):
                grade.inputs['Color'].default_value=(*rgb,1)
                probe=np.asarray(grade.inputs['Color'].default_value[:3])
                expected=oracle.lut(probe@cubes.FROM_LUT.T,nodes.settings(grade))@cubes.TO_LUT.T
                actual=render(Path(directory)/f'gpu-{i}.exr')[0,0,:3]
                self.assertLess(float(oracle.error(actual,expected)),.002)
        self.assertEqual(grade['_pg_cube_backend'],'GPU')
