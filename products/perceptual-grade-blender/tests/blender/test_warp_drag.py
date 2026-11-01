"""Actual-model gesture crossings, continuity and transactional publication."""
from tests.support.session import component as _component, SessionTest, patch
from dataclasses import replace
from copy import deepcopy
from types import SimpleNamespace
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model import color, tone
warp = _component('ui.warp'); warp_drag = _component('ui.warp_drag'); warp_scale = _component('ui.warp_scale')
pass


class WarpDragTests(SessionTest):
    def setup_drag(self, params=None, handle=0, scale=1.):
        model = color.Model(tone.model(tone.Parameters()), params or color.Parameters())
        plot = _component('ui.color_geometry').ABPlot((0., 0., 400*scale, 400*scale), -1.4, 1.4, -1.4, 1.4)
        point = model.guarded_saturation_targets(1)[handle+1]
        action = dict(tone=1, handle=handle, fields=warp.fields(1, handle),
                      plot=plot, target=point.copy(), scale=scale)
        warp_drag.reset(model, action)
        return model, action

    def move(self, model, action, delta, accept=True):
        p = action['plot']; speed = .2 if action['handle'] < 0 else .5
        dx = -delta[1]*p.rect[2]/((p.xmax-p.xmin)*speed)
        dy = delta[0]*p.rect[3]/((p.ymax-p.ymin)*speed)
        values = warp.drag(model, action, dx, dy)
        if accept:
            self.assertTrue(values)
            return color.Model(model.tone, replace(model.params, **values))
        return values

    def boundary(self, model, action):
        values = model.guarded_boundary_values(1, action['handle'])
        boundary = color.Model(model.tone, replace(model.params, **values))
        point = boundary.guarded_saturation_targets(1)[action['handle']+1]
        return boundary, point

    def test_crossing_one_event_matches_split_events_and_reverses(self):
        for params in (None, color.Parameters(adaptance_a_1=7., adaptance_b_1=-3., web_scale_1_0=.3)):
            first, a = self.setup_drag(params)
            second, b = self.setup_drag(params)
            initial = first.guarded_saturation_targets(1)[1]
            boundary, rim = self.boundary(first, a)
            direction = rim/np.linalg.norm(rim)
            delta = rim-initial+.12*direction
            first = self.move(first, a, delta)
            self.assertEqual(a['mode'], 'stops')
            self.assertTrue(a['rim_active'])
            self.assertLess(first.warp_targets(1).energy[1], 0)
            self.assertGreater(np.linalg.norm(a['cursor']), np.linalg.norm(a['target']))
            second = self.move(second, b, delta*.4)
            second = self.move(second, b, delta*.6)
            np.testing.assert_allclose(first.guarded_saturation_targets(1), second.guarded_saturation_targets(1), atol=2e-8)
            self.assertAlmostEqual(first.params.web_chroma_1_0, second.params.web_chroma_1_0, places=6)
            # Retracing the complete segment consumes Stops then position mode.
            first = self.move(first, a, -delta)
            self.assertEqual(a['mode'], 'position')
            self.assertFalse(a['rim_active'])
            np.testing.assert_allclose(first.guarded_saturation_targets(1)[1], initial, atol=2e-8)

    def test_tangent_chord_first_exit_matches_split_events_with_adaptance(self):
        configurations = (
            color.Parameters(web_scale_1_0=.3),
            color.Parameters(adaptance_a_1=7., adaptance_b_1=-3., web_scale_1_0=.3),
        )
        for params in configurations:
            seed, seed_action = self.setup_drag(params)
            boundary, _ = self.boundary(seed, seed_action)
            outside = replace(boundary.params,
                web_chroma_1_0=boundary.params.web_chroma_1_0+1.e-5)
            one, one_action = self.setup_drag(outside)
            split, split_action = self.setup_drag(outside)
            self.assertEqual(one_action['mode'], 'stops')
            start = one_action['cursor'].copy()
            angle = .05
            rotation = np.array([[np.cos(angle), -np.sin(angle)],
                                [np.sin(angle), np.cos(angle)]])
            end = rotation@start
            midpoint = (start+end)/2
            # The endpoint stays just outside, while the chord bows inside the
            # contextual rim. The midpoint's raw E sign confirms the crossing.
            probe = one.guarded_corner_evaluator(1, 0)
            origin = (np.linalg.norm(start), one.params.web_chroma_1_0)
            units_per_stop=.5*(one_action['plot'].ymax-one_action['plot'].ymin)/one_action['plot'].rect[3]*40
            midpoint_probe = warp_drag._stops(probe, midpoint, origin, units_per_stop)
            endpoint_probe = warp_drag._stops(probe, end, origin, units_per_stop)
            self.assertGreater(float(midpoint_probe.raw.energy), 0.)
            self.assertLess(float(endpoint_probe.raw.energy), 0.)
            delta=end-start
            one=self.move(one,one_action,delta)
            split=self.move(split,split_action,delta/2)
            split=self.move(split,split_action,delta/2)
            np.testing.assert_allclose(one.guarded_saturation_targets(1),
                                       split.guarded_saturation_targets(1),atol=3.e-7)
            self.assertAlmostEqual(one.params.web_chroma_1_0,split.params.web_chroma_1_0,places=6)
            self.assertAlmostEqual(one.params.web_hue_1_0,split.params.web_hue_1_0,places=5)

    def test_stops_use_40_ui_pixels_per_stop_and_keep_scale(self):
        for ui_scale in (1., 2.):
            original, action = self.setup_drag(scale=ui_scale)
            boundary, rim = self.boundary(original, action)
            model, action = self.setup_drag(replace(boundary.params, web_chroma_1_0=boundary.params.web_chroma_1_0+.3), scale=ui_scale)
            self.assertEqual(action['mode'], 'stops')
            start = model.params.web_chroma_1_0
            direction = action['cursor']/np.linalg.norm(action['cursor'])
            delta = direction*(.5*2.8/(400*ui_scale))*40*ui_scale
            model = self.move(model, action, delta)
            self.assertAlmostEqual(model.params.web_chroma_1_0, start+1, places=10)
            self.assertEqual(model.params.web_scale_1_0, original.params.web_scale_1_0)
            self.assertLess(np.linalg.norm(action['target']), 1.)
            self.assertGreater(np.linalg.norm(action['cursor']), 1.)

    def test_stops_hue_follows_cursor_with_active_adaptance(self):
        base, action = self.setup_drag(color.Parameters(adaptance_a_1=10., adaptance_b_1=-5., web_scale_1_0=.5))
        boundary, _ = self.boundary(base, action)
        model, action = self.setup_drag(replace(boundary.params, web_chroma_1_0=boundary.params.web_chroma_1_0+.5))
        start = model.params.web_chroma_1_0
        cursor = action['cursor']; theta = .04
        rotated = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])@cursor
        model = self.move(model, action, rotated-cursor)
        self.assertAlmostEqual(model.params.web_chroma_1_0, start, places=10)
        actual = model.guarded_saturation_targets(1)[1]
        np.testing.assert_allclose(actual/np.linalg.norm(actual), rotated/np.linalg.norm(rotated), atol=1e-10)

    def test_rejection_and_reset_leave_no_stale_accumulation(self):
        model, action = self.setup_drag()
        snapshot = deepcopy(action)
        self.assertEqual(self.move(model, action, np.array([1.e8, 1.e8]), accept=False), {})
        for key in ('mode', 'rim_active'):
            self.assertEqual(action[key], snapshot[key])
        for key in ('cursor', 'target'):
            np.testing.assert_array_equal(action[key], snapshot[key])
        boundary, _ = self.boundary(model, action)
        exterior = color.Model(model.tone, replace(boundary.params, web_chroma_1_0=boundary.params.web_chroma_1_0+1))
        warp_drag.reset(exterior, action)
        self.assertEqual(action['mode'], 'stops')
        warp_drag.reset(model, action)
        self.assertEqual(action['mode'], 'position')
        self.assertNotIn('stops_origin', action)
        edited = self.move(model, action, np.array([.001, .001]))
        np.testing.assert_allclose(edited.guarded_saturation_targets(1)[1], snapshot['target']+.001, atol=1e-9)

    def test_low_scale_stops_keep_true_marker_and_virtual_angular_lever(self):
        for ui_scale,adapted in ((1.,False),(2.,False),(1.,True),(2.,True)):
            for row in range(4):
                for handle in range(6):
                    with self.subTest(ui_scale=ui_scale, adapted=adapted, row=row, handle=handle):
                        values={f'web_chroma_{row}_{handle}':3., f'web_scale_{row}_{handle}':-8.}
                        if adapted:values.update({f'adaptance_a_{row}':3.,f'adaptance_b_{row}':-1.})
                        params=color.Parameters(**values)
                        model=color.Model(tone.model(tone.Parameters()),params)
                        plot=_component('ui.color_geometry').ABPlot((0.,0.,400*ui_scale,400*ui_scale),-1.4,1.4,-1.4,1.4)
                        point=model.guarded_saturation_targets(row)[handle+1]
                        action=dict(tone=row,handle=handle,fields=warp.fields(row,handle),plot=plot,scale=ui_scale)
                        warp_drag.reset(model,action)
                        np.testing.assert_array_equal(action['target'],point)
                        self.assertEqual(action['mode'],'stops')
                        self.assertGreaterEqual(np.linalg.norm(action['cursor']),16.*2.8/400-1e-12)
                        self.assertEqual(warp.drag(model,action,0.,0.),{})
                        direction=action['cursor']/np.linalg.norm(action['cursor'])
                        edited=self.move(model,action,direction*.035)
                        self.assertGreater(getattr(edited.params,f'web_chroma_{row}_{handle}'),3.)
                        self.assertEqual(getattr(edited.params,f'web_scale_{row}_{handle}'),-8.)

    def test_low_scale_positive_energy_corners_remain_pickable_and_drag_outward(self):
        for adapted in (False,True):
            for row in range(4):
                for handle in range(6):
                    with self.subTest(adapted=adapted,row=row,handle=handle):
                        values={f'web_scale_{row}_{handle}':-8.}
                        if adapted:values.update({f'adaptance_a_{row}':3.,f'adaptance_b_{row}':-1.})
                        model=color.Model(tone.model(tone.Parameters()),color.Parameters(**values))
                        point=model.guarded_saturation_targets(row)[handle+1]
                        plot=_component('ui.color_geometry').ABPlot((0.,0.,400.,400.),-1.4,1.4,-1.4,1.4)
                        ui=SimpleNamespace(active_tone=row,active_handle=handle)
                        action=warp.hit(ui,model,plot,plot.screen(point),1.)
                        self.assertEqual(action['handle'],handle)
                        warp_drag.reset(model,action)
                        self.assertEqual(action['mode'],'position')
                        self.assertGreater(model.warp_targets(row).energy[handle+1],0.)
                        initial=np.linalg.norm(point)
                        if row<=2:self.assertLess(initial,16.*2.8/400.)
                        edited=self.move(model,action,point/initial*.005)
                        self.assertGreater(np.linalg.norm(edited.guarded_saturation_targets(row)[handle+1]),initial)


class WarpScaleTests(SessionTest):
    def test_regular_fractional_scale_does_not_create_chroma_compensation(self):
        model=color.Model(tone.model(tone.Parameters()),color.Parameters())
        for row in range(4):
            for handle in range(6):
                for requested in (.123456789, 1./3., -.123456789):
                    values=warp_scale.edit(model,row,handle,requested)
                    self.assertEqual(values,{f'web_scale_{row}_{handle}':requested,f'web_chroma_{row}_{handle}':0.})

    def test_all_corners_compensate_upward_and_darken_without_downward_compensation(self):
        for adapted in (False, True):
            for row in range(4):
                for handle in range(6):
                    with self.subTest(adapted=adapted, row=row, handle=handle):
                        names={kind:f'web_{kind}_{row}_{handle}' for kind in ('chroma','hue','scale')}
                        params=color.Parameters(**({f'adaptance_a_{row}':3.,f'adaptance_b_{row}':-1.} if adapted else {}))
                        model=color.Model(tone.model(tone.Parameters()),params)
                        boundary=model.guarded_boundary_values(row,handle)
                        params=replace(params,**boundary)
                        params=replace(params,**{names['chroma']:getattr(params,names['chroma'])+.7})
                        model=color.Model(model.tone,params)
                        self.assertLess(model.warp_targets(row).energy[handle+1],0.)
                        values=warp_scale.edit(model,row,handle,4.)
                        self.assertTrue(values)
                        self.assertLess(values[names['chroma']],getattr(params,names['chroma']))
                        self.assertEqual(values[names['scale']],4.)
                        saved=color.Model(model.tone,replace(params,**{n:float(np.float32(v)) for n,v in values.items()}))
                        raw=saved.warp_targets(row);q=raw.q[handle+1];e=raw.energy[handle+1]
                        self.assertGreater(q[0],0.)
                        self.assertTrue(e>=0 or -e<=warp_scale.TURNING_RATIO*np.hypot(*q[1:]))
                        self.assertTrue(np.isfinite(saved.guarded_saturation_targets(row)[handle+1]).all())
                        self.assertEqual(getattr(saved.params,names['hue']),getattr(params,names['hue']))
                        lower=warp_scale.edit(model,row,handle,-8.)
                        self.assertEqual(lower[names['chroma']],getattr(params,names['chroma']))
                        self.assertEqual(lower[names['scale']],-8.)

    def test_frozen_gesture_reversal_limits_and_saved_invalid_recovery(self):
        initial=color.Model(tone.model(tone.Parameters()),color.Parameters(web_chroma_1_0=3.))
        first=warp_scale.edit(initial,1,0,4.)
        self.assertTrue(first)
        settled=color.Model(initial.tone,replace(initial.params,**first))
        later_lower=warp_scale.edit(settled,1,0,0.)
        self.assertEqual(later_lower['web_chroma_1_0'],first['web_chroma_1_0'])
        intermediate=color.Model(initial.tone,replace(initial.params,**warp_scale.edit(initial,1,0,2.)))
        split=warp_scale.edit(intermediate,1,0,4.,start_params=initial.params)
        self.assertEqual(first,split)
        restored=warp_scale.edit(intermediate,1,0,0.,start_params=initial.params)
        self.assertEqual(restored,dict(web_chroma_1_0=3.,web_scale_1_0=0.))
        self.assertEqual(warp_scale.edit(initial,1,0,8.01),{})
        invalid=color.Model(initial.tone,replace(initial.params,web_scale_1_0=4.))
        self.assertLess(invalid.warp_targets(1).q[1,0],0.)
        self.assertEqual(warp_scale.edit(invalid,1,0,4.),dict(web_chroma_1_0=3.,web_scale_1_0=4.))
        recovered=warp_scale.edit(invalid,1,0,4.5)
        self.assertTrue(recovered)
        repaired=color.Model(invalid.tone,replace(invalid.params,**recovered))
        self.assertGreater(repaired.warp_targets(1).q[1,0],0.)


if __name__ == '__main__':
    unittest.main()
