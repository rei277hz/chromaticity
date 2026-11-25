"""Reversible cyclic edits and ownership use one immutable transaction."""

from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from color_tools.kernel.color_resolution import float32, hue_source_angles, resolve_settings
from color_tools.kernel.settings import ColorSettings, Settings, ToneSettings, WebSettings
from color_tools.features.grade import color_authoring as authoring


class ColorAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.claims = authoring.EMPTY_CLAIMS
        # Equal spacing makes exact push/restore and takeover expectations
        # independent of viewing calibration; separate tests use real geometry.
        self.sources = tuple(tuple(60. * handle for handle in range(6)) for _ in range(4))
        self.patcher = patch.object(authoring, "hue_source_angles", return_value=self.sources)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.resolver = patch.object(authoring, "resolve_settings", side_effect=lambda value: value)
        self.resolver.start()
        self.addCleanup(self.resolver.stop)

    def edit(self, handle, value, row=0):
        effects = authoring.edit_hue(self.settings, self.claims, row, handle, value)
        if effects.settings is not None:
            self.settings = effects.settings
        if effects.claims is not None:
            self.claims = effects.claims
        self.valid(row)
        return effects

    def valid(self, row):
        offsets = self.settings.color.web.hue_degrees[row]
        targets = tuple(a + b for a, b in zip(self.sources[row], offsets))
        gaps = [targets[index + 1] - targets[index] for index in range(5)]
        gaps.append(targets[0] + 360. - targets[5])
        self.assertGreaterEqual(min(gaps), 4.)
        self.assertTrue(all(-360. <= value <= 360. for value in offsets))

    def test_transitive_push_and_return_restore_in_same_transaction(self):
        self.edit(0, 130.)
        self.assertEqual(self.claims[0][1], authoring.Claim(0, 0.))
        self.assertEqual(self.claims[0][2], authoring.Claim(0, 0.))
        self.edit(0, 100.)
        self.assertIsNone(self.claims[0][2])
        self.assertEqual(self.settings.color.web.hue_degrees[0][2], 0.)
        self.assertGreater(self.settings.color.web.hue_degrees[0][1], 0.)
        self.edit(0, 0.)
        self.assertEqual(self.settings, Settings())
        self.assertEqual(self.claims, authoring.EMPTY_CLAIMS)

    def test_same_owner_retains_first_baseline(self):
        self.edit(0, 80.)
        baseline = self.claims[0][1]
        self.edit(0, 130.)
        self.assertEqual(self.claims[0][1], baseline)

    def test_capture_uses_owner_from_policy_result(self):
        claims = [list(row) for row in self.claims]
        event = authoring.ownership.Event("push", 0)
        decision = authoring.ownership.State(3), authoring.ownership.Effects("capture")
        with patch.object(authoring.ownership, "step", return_value=decision):
            authoring._claim_event(claims, 0, 1, event, offset=12.)
        self.assertEqual(claims[0][1], authoring.Claim(3, 12.))

    def test_same_value_is_idempotent(self):
        self.edit(0, 130.)
        effects = self.edit(0, 130.)
        self.assertEqual(effects, authoring.Effects())

    def test_restoration_reaches_nearest_valid_float32_boundary(self):
        source = (0., 60.000003, 120., 180., 240., 300.)
        current = (0.,) * 6
        candidate = (0., 4. - source[1], 0., 0., 0., 0.)
        self.assertFalse(authoring._valid(source, tuple(float32(x) for x in candidate)))
        restored = authoring._stored_restoration(source, current, candidate)
        self.assertTrue(authoring._valid(source, restored))
        self.assertEqual(restored, (0., -56., 0., 0., 0., 0.))

    def test_manual_neighbor_takes_over_only_handles_it_pushes(self):
        self.edit(0, 130.)
        green = self.settings.color.web.hue_degrees[0][2]
        self.edit(1, 140.)
        self.assertIsNone(self.claims[0][1])
        self.assertEqual(self.claims[0][2], authoring.Claim(1, green))
        owned_position = self.settings.color.web.hue_degrees[0][2]
        self.edit(0, 0.)
        self.assertEqual(self.settings.color.web.hue_degrees[0][2], owned_position)
        self.assertEqual(self.claims[0][2].origin_handle, 1)

    def test_direct_manual_edit_detaches_only_its_claim(self):
        self.edit(0, 130.)
        position = self.settings.color.web.hue_degrees[0][2]
        self.edit(2, position)
        self.assertIsNone(self.claims[0][2])
        self.assertEqual(self.claims[0][1].origin_handle, 0)

    def test_blocked_restoration_retains_baseline(self):
        self.edit(0, 250.)
        self.edit(1, 180.)
        self.edit(0, 0.)
        # The manually placed Yellow blocks Green's old baseline. Red keeps
        # the claim and can finish restoring it after Yellow moves away.
        self.assertIsNotNone(self.claims[0][2])
        self.assertEqual(self.claims[0][2].origin_handle, 0)
        self.assertGreater(self.settings.color.web.hue_degrees[0][2], 0.)
        self.edit(1, 0.)
        self.edit(0, 1.)
        self.assertIsNone(self.claims[0][2])

    def test_pushes_both_directions_across_seam(self):
        self.edit(0, -130.)
        self.assertEqual(self.claims[0][5], authoring.Claim(0, 0.))
        self.assertEqual(self.claims[0][4], authoring.Claim(0, 0.))
        self.edit(0, 0.)
        self.assertEqual(self.claims, authoring.EMPTY_CLAIMS)
        self.edit(5, 130.)
        self.assertEqual(self.claims[0][0], authoring.Claim(5, 0.))
        self.assertEqual(self.claims[0][1], authoring.Claim(5, 0.))
        self.edit(5, 0.)
        self.assertEqual(self.settings, Settings())

    def test_all_five_neighbors_push_within_storage_domain(self):
        self.edit(0, 360.)
        self.assertTrue(all(claim.origin_handle == 0 for claim in self.claims[0][1:]))
        self.edit(0, -360.)
        self.assertTrue(any(claim is not None for claim in self.claims[0][1:]))
        self.edit(0, 0.)
        self.assertEqual(self.claims, authoring.EMPTY_CLAIMS)

    def test_rows_and_metadata_changes_are_independent(self):
        self.edit(0, 130., row=2)
        self.assertEqual(self.settings.color.web.hue_degrees[0], (0.,) * 6)
        cleared = authoring.clear_claims(self.claims, rows=(1,))
        self.assertEqual(cleared, authoring.Effects())
        cleared = authoring.clear_claims(self.claims, rows=(2,))
        self.assertIsNone(cleared.settings)
        self.assertEqual(cleared.claims, authoring.EMPTY_CLAIMS)

    def test_nonfinite_requests_fail_without_effects(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                authoring.edit_hue(self.settings, self.claims, 0, 0, value)
            with self.assertRaises(ValueError):
                authoring.edit_adaptance(self.settings, self.claims, 0, 0, value)
        self.assertEqual(self.settings, Settings())
        self.assertEqual(self.claims, authoring.EMPTY_CLAIMS)

    def test_adaptance_edit_limits_both_axes_preserving_direction(self):
        rows = ((3., 4.),) + ((0., 0.),) * 3
        settings = replace(self.settings, color=ColorSettings(adaptance=rows))
        effects = authoring.edit_adaptance(settings, self.claims, 0, 0, 1.e6)
        pair = effects.settings.color.adaptance[0]
        self.assertLess(pair[0], 1.e6)
        self.assertLess(pair[1], 4.)
        self.assertAlmostEqual(pair[1] / pair[0], 4.e-6, delta=1.e-12)
        self.assertIsNone(effects.claims)
        self.assertEqual(resolve_settings(effects.settings), effects.settings)

    def test_real_geometry_edits_remain_valid_at_all_peaks(self):
        self.patcher.stop()
        self.resolver.stop()
        for peak in (500., 1000., 2000., 4000.):
            settings = Settings(tone=ToneSettings(peak_nits=peak))
            claims = authoring.EMPTY_CLAIMS
            for row in range(4):
                for handle, request in ((0, 150.), (2, -170.), (5, 300.), (0, -300.)):
                    effects = authoring.edit_hue(settings, claims, row, handle, request)
                    settings = effects.settings or settings
                    claims = effects.claims if effects.claims is not None else claims
                    self.assertEqual(resolve_settings(settings), settings)
                for handle in range(6):
                    for request in (-360., 360.):
                        effects = authoring.edit_hue(settings, claims, row, handle, request)
                        settings = effects.settings or settings
                        claims = effects.claims if effects.claims is not None else claims
                        self.assertEqual(resolve_settings(settings), settings)
        self.patcher.start()
        self.resolver.start()

    def test_rebase_repairs_sample_and_clears_claims_without_mutating_input(self):
        self.edit(0, 130.)
        self.resolver.stop()
        invalid = ((150., 0., 0., 0., 0., 0.),) + ((0.,) * 6,) * 3
        raw = replace(self.settings, color=replace(self.settings.color,
                      web=WebSettings(hue_degrees=invalid)))
        effects = authoring.rebase(raw, self.claims)
        self.assertEqual(effects.claims, authoring.EMPTY_CLAIMS)
        self.assertEqual(resolve_settings(effects.settings), effects.settings)
        self.assertEqual(raw.color.web.hue_degrees, invalid)


if __name__ == "__main__":
    unittest.main()
