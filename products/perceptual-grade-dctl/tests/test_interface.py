"""Localized direct forward/inverse controls and explicit failure contracts."""
import unittest
import re
import numpy as np
from color_tools.perceptual_grade_core.localization import catalogs as i18n
from color_tools.perceptual_grade_core.model import linear, tone
from tests.support import dctl_controls as color, dctl_controls as controls
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.export import input_repair
from tests.support import oracle
from tests.support.dctl import body,controls as parse_controls


class InterfaceTests(unittest.TestCase):
    def test_only_transform_token_is_the_seven_argument_entrypoint(self):
        # Some Resolve loaders appear to locate the entrypoint by suffix, so
        # even a prefixed helper must not contain another transform(...) token.
        expected='int p_Width,int p_Height,int p_X,int p_Y,float p_R,float p_G,float p_B'
        for filename in ('Perceptual-Grade.dctl','Perceptual-Grade-zh-HANS.dctl'):
            with self.subTest(filename=filename):
                source=(oracle.RESOURCES/filename).read_text()
                self.assertEqual(re.findall(r'transform\s*\(([^)]*)\)',source),[expected])
                self.assertEqual(len(re.findall(r'__DEVICE__\s+float3\s+transform\s*\(',source)),1)

    def test_entry_return_is_an_explicit_float3_constructor(self):
        # A direct helper-call return can confuse Resolve's source-level type
        # detection even when the helper compiles with a float3 return type.
        for filename in ('Perceptual-Grade.dctl','Perceptual-Grade-zh-HANS.dctl'):
            with self.subTest(filename=filename):
                source=(oracle.RESOURCES/filename).read_text()
                entry=source.split('/* PG_NUMERICAL_END */',1)[1]
                entry=re.sub(r'//[^\n]*|/\*.*?\*/','',entry,flags=re.S)
                self.assertEqual(re.findall(r'\breturn\s+([^;]+);',entry),
                                 ['make_float3(output.x,output.y,output.z)'])

    def test_helpers_do_not_shadow_ui_identifiers(self):
        # Standard C++/OpenCL allow these collisions; Resolve's UI injection
        # has been reported to reject them with a misleading return-type error.
        for filename in ('Perceptual-Grade.dctl','Perceptual-Grade-zh-HANS.dctl'):
            with self.subTest(filename=filename):
                source=(oracle.RESOURCES/filename).read_text()
                helpers=re.sub(r'//[^\n]*|/\*.*?\*/','',body(source),flags=re.S)
                # Member fields have their own namespace. Bare UI identifiers
                # must occur only in the public entry, never in helper code.
                helpers=re.sub(r'typedef\s+struct\s*\{[^}]*\}\s*\w+\s*;','',helpers)
                helpers=re.sub(r'\.\s*[A-Za-z_]\w*','',helpers)
                identifiers=set(re.findall(r'\b[A-Za-z_]\w*\b',helpers))
                self.assertFalse(identifiers & {item['name'] for item in parse_controls(source)})

    def test_localized_controls_and_numerical_body(self):
        en=oracle.UI;zh_source=(oracle.RESOURCES/'Perceptual-Grade-zh-HANS.dctl').read_text()
        zh=parse_controls(zh_source)
        self.assertEqual(body(oracle.SOURCE),body(zh_source));self.assertEqual(len(en),len(zh))
        for left,right in zip(en,zh):
            self.assertEqual({k:v for k,v in left.items() if k not in ('label','options')},
                             {k:v for k,v in right.items() if k not in ('label','options')})
            self.assertIn(right['label'],i18n.CATALOGS['zh_HANS'].values())
            if 'options' in left:self.assertEqual(left['options'][0],right['options'][0])
        self.assertEqual(len(en),len({item['label'] for item in en}))

    def test_dctl_bindings_and_fixed_context(self):
        by_name={item['name']:item for item in oracle.UI}
        neutral=oracle.settings(linear.Parameters(),tone.Parameters(),color.Parameters(),'Linear Rec.709')
        for name,*_ in color.CONTROLS:
            meta=controls.meta(name);dctl=by_name[meta[-1]]
            self.assertEqual((i18n.native(meta[1]),meta[2],meta[3],meta[4]),
                (dctl['label'],dctl['default'],dctl['min'],dctl['max']))
            self.assertEqual(neutral[meta[-1]],dctl['default'])
            if controls.step(name) is not None:self.assertEqual(dctl['step'],controls.step(name))
        self.assertEqual(controls.step('adaptance_strength'),by_name['adaptanceStrength']['step'])
        self.assertEqual(by_name['peakNits']['options'][1],[f'{peak} nits' for peak in tone.PEAKS])
        self.assertNotIn('dstWhite',by_name);self.assertNotIn('referenceNits',by_name)
        self.assertEqual(by_name['direction']['default'],0)
        self.assertEqual(len(by_name['direction']['options'][0]),2)

    def test_shadow_calibration_and_default_agree_at_dctl_precision(self):
        # The generator formats UI literals, while the kernel spells LOW_Y
        # directly. Both must round to the same calibrated float32 values.
        low_y=re.search(r'v\.lowJ=pg_neutral_j\(([^,]+)f,v\)',oracle.SOURCE)
        self.assertIsNotNone(low_y)
        self.assertEqual(np.float32(low_y.group(1)),np.float32(tone.LOW_Y))
        by_name={item['name']:item for item in oracle.UI}
        self.assertEqual(np.float32(by_name['inputShadows']['default']),
                         np.float32(tone.LOW_Y*203.))

    def test_float_slider_budget_and_integer_highlight_policy(self):
        self.assertEqual(sum(item['type']=='DCTLUI_SLIDER_FLOAT' for item in oracle.UI),62)
        self.assertEqual(sum(item['type']=='DCTLUI_SLIDER_INT' for item in oracle.UI),13)
        by_name={item['name']:item for item in oracle.UI}
        highlights={f'toneH{driver}To{target}' for driver in ('Low','High','a','b') for target in ('J','C')}
        for name in highlights:
            self.assertEqual(by_name[name]['type'],'DCTLUI_SLIDER_INT')
            self.assertEqual(by_name[name]['step'],1)

    def test_cartesian_response_controls_and_test_adapter(self):
        by_name={item['name']:item for item in oracle.UI}
        neutral=oracle.settings(linear.Parameters(),tone.Parameters(),color.Parameters(),'Linear Rec.709')
        for tone_id in 'SMWH':
            for target,axis_limit,step in (('J',50.,.1),('C',4.,.01)):
                expected_type='DCTLUI_SLIDER_INT' if tone_id=='H' else 'DCTLUI_SLIDER_FLOAT'
                expected_step=1 if tone_id=='H' else step
                for axis in 'ab':
                    control=by_name[f'tone{tone_id}{axis}To{target}']
                    self.assertEqual((control['type'],control['min'],control['max'],control['step']),
                                     (expected_type,-axis_limit,axis_limit,expected_step))
                    self.assertEqual(neutral[control['name']],0)
                self.assertNotIn(f'tone{tone_id}AngleTo{target}',by_name)
                self.assertNotIn(f'tone{tone_id}LengthTo{target}',by_name)
        cp=color.Parameters(j_a_0=3.1,j_b_0=-4.2,c_a_3=-4.,c_b_3=3.)
        adapted=oracle.settings(linear.Parameters(),tone.Parameters(),cp,'Linear Rec.709')
        self.assertEqual(adapted['toneSaToJ'],3.1)
        self.assertEqual(adapted['toneSbToJ'],-4.2)
        self.assertEqual(adapted['toneHaToC'],-4.)
        self.assertEqual(adapted['toneHbToC'],3.)

    def test_reset_repairs_native_cube_before_identity(self):
        model=Model();to_xyz=model.cones_to_xyz@np.linalg.inv(model.boundary.matrix)
        native=np.array([[0,0,0],[.2,.3,.4],[-1,3,128],[2048,3,4],[1024]*3])
        xyz=native@to_xyz.T;expected=input_repair(native,model.acescg_y)@to_xyz.T
        for mode in ('grade','inverse','inverse_nonlinear'):
            actual=oracle.run(mode,xyz)
            np.testing.assert_allclose(actual[:,:3],expected,rtol=4e-5,atol=2e-5)
            np.testing.assert_array_equal(actual[:,3],1)
            np.testing.assert_array_equal(actual[0,:3],0)

    def test_inverse_returns_current_found_root_and_residual(self):
        model=Model();to_xyz=model.cones_to_xyz@np.linalg.inv(model.boundary.matrix)
        xyz=np.array([[.1,.2,.3],[.7,.2,.1]])@to_xyz.T
        canonical=np.asarray(linear.xyz_to_rgb('Linear Rec.709'))
        for settings in (dict(globalChromaGain=.15,toneMHue=3,inputMidtones=45),
                         dict(globalChromaGain=.15,globalLowChromaHue=12,
                              globalHighChromaHue=-17,inputMidtones=45)):
            with self.subTest(settings=settings):
                target=oracle.run('grade',xyz,settings)[:,:3]
                inverse=oracle.run('inverse',target,settings)
                reproduced=oracle.run('grade',inverse[:,:3],settings)[:,:3]
                self.assertTrue(np.isfinite(inverse).all())
                self.assertTrue(np.all(inverse[:,4]>=0))
                # Reproduction in canonical RGB is the found-root contract.
                error=abs((reproduced-target)@canonical.T)
                limit=np.maximum(.0001*np.max(abs(target@canonical.T),axis=-1),.00003)
                self.assertTrue(np.all(np.max(error,axis=-1)<=limit*1.1),(error,limit))

    def test_selector_and_singular_inverse_are_explicit(self):
        target=np.array([[.2,.3,.4]])
        for direction,mode in ((0,'grade'),(1,'inverse')):
            settings=dict(direction=direction,globalChromaGain=.25)
            np.testing.assert_array_equal(oracle.run('selected',target,settings)[:,:3],
                                          oracle.run(mode,target,settings)[:,:3])
        forward=oracle.run('selected',target,dict(ls=-100,direction=0))
        inverse=oracle.run('selected',target,dict(ls=-100,direction=1))
        self.assertEqual(forward[0,3],1);self.assertEqual(inverse[0,3],0)
        self.assertFalse(np.array_equal(inverse[0,:3],target[0]))
        # An orientation reversal is invertible and remains supported.
        status=oracle.run('configuration',target,dict(la=180))
        np.testing.assert_array_equal(status[0,:2],[1,1])

    def test_invalid_configuration_diagnostic_ignores_overlay_toggle(self):
        samples=np.array([[.2,.3,.4,1000,1000,x,10] for x in range(0,64,4)])
        controls=dict(ls=-100,direction=1)
        off=oracle.run('pixel',samples,dict(controls,overlayMode=0))[:,:3]
        on=oracle.run('pixel',samples,dict(controls,overlayMode=2))[:,:3]
        np.testing.assert_array_equal(off,on)
        self.assertGreater(len(np.unique(off,axis=0)),1)
        self.assertTrue(np.isfinite(off).all())
