import unittest
from types import SimpleNamespace
from unittest.mock import patch

from color_tools.perceptual_grade_next_blender.output_gateway import OutputGateway
from color_tools.perceptual_grade_next_blender.output_operators import (
    OutputActionController, RenderOptions, SaveOptions, modified_images_choice,
    modified_image_warning, _menu_redirect_target, _native_save, _redirect_target,
    _RedirectingMenuLayout,
)


class OutputActionTests(unittest.TestCase):
    def test_keymap_redirects_cover_only_owned_native_actions(self):
        self.assertEqual(_redirect_target("wm.save_mainfile"), "wm.pg_next_save")
        self.assertEqual(_redirect_target("wm.save_as_mainfile"), "wm.pg_next_save_as")
        self.assertEqual(
            _redirect_target("render.render", animation=False),
            "render.pg_next_render_image",
        )
        self.assertEqual(
            _redirect_target("render.render", animation=True),
            "render.pg_next_render_animation",
        )
        self.assertIsNone(_redirect_target("wm.open_mainfile"))

    def test_keymap_redirects_leave_incremental_copy_and_sequencer_actions_alone(self):
        self.assertIsNone(_redirect_target("wm.save_mainfile", incremental=True))
        self.assertIsNone(_redirect_target("wm.save_as_mainfile", copy=True))
        self.assertIsNone(_redirect_target("render.render", sequencer_scene=True))

    def test_menu_redirects_only_the_four_agreed_native_entries(self):
        self.assertEqual(
            _menu_redirect_target("wm.save_mainfile", text="Save"),
            ("wm.pg_next_save", {"show_save_modified_images_dialog"}),
        )
        self.assertEqual(
            _menu_redirect_target("wm.save_as_mainfile", text="Save As..."),
            ("wm.pg_next_save_as", {"show_save_modified_images_dialog"}),
        )
        self.assertEqual(
            _menu_redirect_target("render.render", text="Render Image"),
            ("render.pg_next_render_image", set()),
        )
        self.assertEqual(
            _menu_redirect_target("render.render", text="Render Animation"),
            ("render.pg_next_render_animation", {"animation"}),
        )
        self.assertIsNone(_menu_redirect_target("wm.save_mainfile", text="Save Incremental"))
        self.assertIsNone(_menu_redirect_target("wm.save_as_mainfile", text="Save Copy..."))
        self.assertIsNone(_menu_redirect_target("render.render", text="Render Sequencer Image"))

    def test_layout_proxy_preserves_options_and_operator_context(self):
        class Layout:
            operator_context = "EXEC_AREA"

            def __init__(self):
                self.calls = []

            def operator(self, operator_id, **kwargs):
                self.calls.append((self.operator_context, operator_id, kwargs))
                return type("Properties", (), {})()

        layout = Layout()
        props = _RedirectingMenuLayout(layout).operator(
            "render.render", text="Render Animation", icon="RENDER_ANIMATION",
        )
        props.use_viewport = True
        props.animation = True
        self.assertEqual(layout.operator_context, "EXEC_AREA")
        self.assertEqual(layout.calls, [(
            "INVOKE_AREA", "render.pg_next_render_animation",
            {"text": "Render Animation", "icon": "RENDER_ANIMATION"},
        )])
        self.assertTrue(props.use_viewport)
        self.assertFalse(hasattr(props, "animation"))

    def test_layout_proxy_forwards_unrelated_native_entries(self):
        class Layout:
            operator_context = "INVOKE_AREA"

            def __init__(self):
                self.calls = []

            def operator(self, operator_id, **kwargs):
                self.calls.append((operator_id, kwargs))
                return "native-properties"

        layout = Layout()
        result = _RedirectingMenuLayout(layout).operator(
            "wm.save_as_mainfile", text="Save Copy...",
        )
        self.assertEqual(result, "native-properties")
        self.assertEqual(layout.calls, [(
            "wm.save_as_mainfile", {"text": "Save Copy..."},
        )])

    def test_modified_image_preference_is_respected_without_mutating_it(self):
        self.assertTrue(modified_images_choice("ALWAYS", False))
        self.assertFalse(modified_images_choice("NEVER", True))
        self.assertTrue(modified_images_choice("ASK", True))
        self.assertFalse(modified_images_choice("ASK", False))
        with self.assertRaises(ValueError):
            modified_images_choice("OTHER", True)

    def test_modified_image_warning_keeps_project_save_success_distinct(self):
        self.assertEqual(modified_image_warning(()), "")
        self.assertEqual(
            modified_image_warning(("Paint",)),
            "Project saved, but 1 modified Image(s) could not be saved: Paint",
        )
        self.assertTrue(modified_image_warning(("A", "B", "C", "D")).endswith(
            "A, B, C, and 1 more"
        ))

    def test_native_save_records_image_failure_and_still_saves_project(self):
        image = SimpleNamespace(
            name="Paint", is_dirty=True,
            filepath_raw="/no/such/image.png", filepath="/no/such/image.png",
            packed_file=None, packed_files=(),
        )
        image_save = lambda *_args: (_ for _ in ()).throw(RuntimeError("Image path failed"))
        save_calls = []
        fake_bpy = SimpleNamespace(
            data=SimpleNamespace(images=(image,)),
            path=SimpleNamespace(abspath=lambda path: path),
            ops=SimpleNamespace(
                image=SimpleNamespace(save_all_modified=image_save),
                wm=SimpleNamespace(save_as_mainfile=lambda *args, **kwargs: (
                    save_calls.append((args, kwargs)) or {"FINISHED"}
                )),
            ),
        )
        options = SaveOptions(filepath="scene.blend", save_as=True)
        with patch.dict("sys.modules", {"bpy": fake_bpy}):
            result = _native_save(options)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(options.diagnostics.unsaved_images, ("Paint",))
        self.assertEqual(len(save_calls), 1)

    @staticmethod
    def _ready_gateway():
        gateway = OutputGateway()
        gateway.dispatch(
            "open", generation=1, owners=("grade",),
            owner_evaluators=(("grade", "native_grade_graph"),),
        )
        gateway.dispatch("intent", revision=1)
        gateway.dispatch("prepare_begin", revision=1, attempt=1)
        gateway.dispatch(
            "owner_ready", revision=1, attempt=1, owner="grade",
            evaluator="native_grade_graph", evaluator_id="graph",
            manifest_id="manifest", final_ready=True,
        )
        return gateway

    def test_confirmation_cancellation_does_not_enter_save_machine(self):
        gateway = self._ready_gateway()
        calls = []
        controller = OutputActionController(
            gateway, confirm=lambda kind, options: False,
        )
        result = controller.save(lambda options: calls.append(options), SaveOptions())
        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(calls, [])
        self.assertEqual(gateway.state.phase, "active")

    def test_save_is_invoked_once_after_confirmation_and_refresh(self):
        gateway = self._ready_gateway()
        calls = []
        refreshed = []
        controller = OutputActionController(
            gateway,
            confirm=lambda kind, options: kind == "save",
            refresh=lambda: refreshed.append(True) or True,
        )
        result = controller.save(
            lambda options: calls.append(options) or {"FINISHED"},
            SaveOptions(filepath="scene.blend", save_as=True),
        )
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].filepath, "scene.blend")
        self.assertEqual(refreshed, [True, True])
        self.assertEqual(gateway.state.phase, "active")

    def test_native_save_cancellation_releases_publication_hold(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway)
        calls = []
        result = controller.save(
            lambda options: calls.append(options) or {"CANCELLED"},
        )
        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)
        self.assertEqual(controller.pending_save_operation, None)

    def test_native_save_exception_releases_publication_hold_and_propagates(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway)
        calls = []

        def fail(_options):
            calls.append(True)
            raise OSError("native project write failed")

        with self.assertRaisesRegex(OSError, "native project write failed"):
            controller.save(fail)
        self.assertEqual(calls, [True])
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)
        self.assertEqual(controller.pending_save_operation, None)

    def test_refresh_exception_cancels_pending_save_before_native_invocation(self):
        gateway = self._ready_gateway()
        refresh_count = 0

        def refresh():
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count == 1:
                return False
            raise RuntimeError("readiness observation failed")

        calls = []
        controller = OutputActionController(gateway, refresh=refresh)
        with self.assertRaisesRegex(RuntimeError, "readiness observation"):
            controller.save(lambda options: calls.append(options) or {"FINISHED"})
        self.assertEqual(calls, [])
        self.assertIsNone(controller.pending_save_operation)
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)

    def test_render_modal_result_keeps_publication_hold_until_terminal_receipt(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway)
        result = controller.render(
            lambda options: {"RUNNING_MODAL"}, RenderOptions(animation=True),
        )
        self.assertEqual(result, {"RUNNING_MODAL"})
        self.assertEqual(gateway.state.phase, "rendering")
        self.assertTrue(gateway.state.publication_hold)
        controller.complete_render(committed=True)
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)

    def test_failed_refresh_blocks_before_gateway_transition(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway, refresh=lambda: False)
        result = controller.render(lambda options: {"FINISHED"})
        self.assertEqual(result, {"RUNNING_MODAL"})
        self.assertEqual(gateway.state.phase, "rendering")
        self.assertTrue(gateway.state.publication_hold)

    def test_save_enters_hold_before_waiting_for_preparation(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway, refresh=lambda: False)
        result = controller.save(lambda options: {"FINISHED"})
        self.assertEqual(result, {"RUNNING_MODAL"})
        self.assertEqual(gateway.state.phase, "saving")
        self.assertTrue(gateway.state.publication_hold)

    def test_cancelled_save_wait_releases_its_hold_without_native_invocation(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway, refresh=lambda: False)
        calls = []
        self.assertEqual(controller.save(lambda options: calls.append(options)), {"RUNNING_MODAL"})
        operation = controller.pending_save_operation
        controller.cancel_save_wait(operation)
        self.assertIsNone(controller.pending_save_operation)
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)
        self.assertEqual(calls, [])

    def test_refresh_exception_cancels_pending_render_before_native_invocation(self):
        gateway = self._ready_gateway()
        refresh_count = 0

        def refresh():
            nonlocal refresh_count
            refresh_count += 1
            if refresh_count == 2:
                raise RuntimeError("readiness observation failed")
            return True

        calls = []
        controller = OutputActionController(gateway, refresh=refresh)
        with self.assertRaisesRegex(RuntimeError, "readiness observation"):
            controller.render(lambda options: calls.append(options) or {"FINISHED"})
        self.assertEqual(calls, [])
        self.assertIsNone(controller.pending_render_operation)
        self.assertEqual(gateway.state.phase, "active")
        self.assertFalse(gateway.state.publication_hold)

    def test_render_continuation_invokes_native_at_most_once(self):
        gateway = self._ready_gateway()
        controller = OutputActionController(gateway, refresh=lambda: True)
        calls = []
        result = controller.render(
            lambda options: calls.append(options) or {"RUNNING_MODAL"},
        )
        self.assertEqual(result, {"RUNNING_MODAL"})
        operation = controller.active_render_operation
        self.assertEqual(controller.continue_render(operation), {"RUNNING_MODAL"})
        self.assertEqual(len(calls), 1)
        controller.complete_render(operation=operation)


if __name__ == "__main__":
    unittest.main()
