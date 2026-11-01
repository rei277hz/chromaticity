import unittest
from types import SimpleNamespace

from color_tools.perceptual_grade_next_blender import scope_runtime


class _Layout:
    def __init__(self):
        self.labels = []
        self.operators = []

    def label(self, **values):
        self.labels.append(values)

    def row(self, **_values):
        return self

    def operator(self, identifier, **values):
        self.operators.append((identifier, values))
        return SimpleNamespace(page=None)


class ScopeUiTests(unittest.TestCase):
    def _context(self):
        return SimpleNamespace(
            window=SimpleNamespace(as_pointer=lambda: 11),
            area=SimpleNamespace(as_pointer=lambda: 22),
        )

    def _failed_runtime(self, context):
        runtime = scope_runtime.ScopeRuntime()
        runtime.open(scope_runtime.context_owner(context), app_owner="app")
        runtime.observe(1, "image-a")
        self.assertTrue(runtime.complete_capture(runtime.begin_capture()))
        visual = runtime.stage_display(payload="first-result")
        self.assertTrue(runtime.apply_display(visual))
        runtime.observe(2, "image-b")
        ticket = runtime.begin_capture()
        self.assertTrue(runtime.fail_capture(ticket, "native capture fault"))
        self.assertTrue(runtime.retire_capture(ticket))
        return runtime

    def test_panel_shows_retained_result_local_failure_and_retry(self):
        previous_runtime = scope_runtime._RUNTIME
        context = self._context()
        scope_runtime._RUNTIME = self._failed_runtime(context)
        try:
            layout = _Layout()
            scope_runtime._draw_scope_panel(layout, context)
            labels = [item["text"] for item in layout.labels]
            self.assertIn("Capture failed", labels)
            self.assertIn("Previous result retained", labels)
            self.assertIn("Details: native capture fault", labels)
            self.assertEqual([identifier for identifier, _values in layout.operators],
                             ["view3d.pg_next_scope_page"] * 3
                             + ["view3d.pg_next_retry_scope", "view3d.pg_next_close_scope"])

            self.assertEqual(scope_runtime._RUNTIME.retry().source_id, "image-b")
            self.assertFalse(scope_runtime._RUNTIME.presentation.can_retry)
        finally:
            scope_runtime._RUNTIME = previous_runtime

    def test_page_buttons_keep_displayed_provenance_and_do_not_request_capture(self):
        previous_runtime = scope_runtime._RUNTIME
        context = self._context()
        runtime = self._failed_runtime(context)
        scope_runtime._RUNTIME = runtime
        try:
            first = runtime.displayed_visual
            request = runtime.state.request
            begun = runtime.state.begun_request
            observation = runtime._observed
            self.assertTrue(runtime.select_page("waveform"))
            self.assertEqual(runtime.selected_page, "waveform")
            self.assertEqual(runtime.state.request, request)
            self.assertEqual(runtime.state.begun_request, begun)
            self.assertEqual(runtime._observed, observation)
            self.assertIs(runtime.displayed_visual, first)
            self.assertEqual(runtime.presentation.displayed.source_id, first.source_id)

            layout = _Layout()
            scope_runtime._draw_scope_panel(layout, context)
            page_operators = [values for identifier, values in layout.operators
                              if identifier == "view3d.pg_next_scope_page"]
            self.assertEqual(len(page_operators), 3)
            self.assertEqual(
                [identifier for identifier, _values in layout.operators][-1],
                "view3d.pg_next_close_scope",
            )
        finally:
            scope_runtime._RUNTIME = previous_runtime


if __name__ == "__main__":
    unittest.main()
