import unittest

from tools.perceptual_grade_nodes.gui_drag_report import summary, summarize_samples


class GuiDragReportTests(unittest.TestCase):
    def row(self, identity=1, drawn=True):
        row = dict(sample_id=identity, revision=identity+3, scenario='exposure',
                   accepted_seconds=10., phases={'prepare': .02})
        if drawn:
            row['draw'] = dict(sample_id=identity, revision=identity+3, at_seconds=10.2,
                               token_matches=True, preview_matches=True)
        return row

    def test_missing_draw_is_never_zero_latency(self):
        report = summarize_samples([self.row(), self.row(2, False)])
        self.assertEqual((report['drawn_count'], report['missing_count']), (1, 1))
        self.assertEqual(report['groups'][0]['accepted_to_matching_draw']['count'], 1)
        self.assertAlmostEqual(report['groups'][0]['accepted_to_matching_draw']['p95_seconds'], .2)

    def test_stale_draw_or_unverified_pixels_cannot_complete(self):
        for field, value in [('revision', 0), ('sample_id', 2),
                             ('token_matches', False), ('preview_matches', False), ('at_seconds', 9.)]:
            row = self.row()
            row['draw'][field] = value
            with self.assertRaises(ValueError):
                summarize_samples([row])

    def test_p95_is_nearest_rank_and_empty_is_missing(self):
        self.assertIsNone(summary([]))
        self.assertEqual(summary(range(1, 101))['p95_seconds'], 95)
        self.assertEqual(summary([1, 2, 3])['p50_seconds'], 2)

    def test_superseded_occurrence_cannot_claim_current_draw(self):
        row = self.row()
        row['outcome'] = 'superseded'
        with self.assertRaises(ValueError):
            summarize_samples([row])


if __name__ == '__main__':
    unittest.main()
