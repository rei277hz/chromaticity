import unittest
from unittest.mock import patch

import bpy

from color_tools.perceptual_grade_next_blender import restart, scope_runtime, bake_operators, output_operators


class RestartControllerTests(unittest.TestCase):
    def test_missing_scope_adapter_does_not_supply_retirement_receipt(self):
        with patch.object(scope_runtime, "runtime", side_effect=RuntimeError("scope unavailable")):
            self.assertFalse(restart._observe_blender("scope"))

    def test_missing_bake_gateway_does_not_supply_retirement_receipt(self):
        with patch.object(bake_operators, "_GATEWAY", None):
            self.assertFalse(restart._observe_blender("bake:17"))

    def test_missing_output_controller_does_not_supply_retirement_receipt(self):
        with patch.object(output_operators, "_CONTROLLER", None):
            self.assertFalse(restart._observe_blender("output:17"))

    def test_recovery_waits_for_every_exact_cleanup_receipt(self):
        recovered = []
        observations = {"scope": False, "updates": False}
        controller = restart.RestartController(
            drain=lambda _generation, _required: None,
            observe=lambda identity: observations[identity],
            recover=lambda generation: recovered.append(generation),
        )

        status = controller.request(("scope", "updates"))
        self.assertEqual(status.phase, "draining")
        self.assertEqual(recovered, [])
        observations["scope"] = True
        self.assertEqual(controller.poll().retired, ("scope",))
        self.assertEqual(recovered, [])
        observations["updates"] = True
        status = controller.poll()
        self.assertEqual(status.phase, "active")
        self.assertEqual(recovered, [status.generation])

    def test_failed_recovery_keeps_retryable_status(self):
        calls = []

        def recover(generation):
            calls.append(generation)
            if len(calls) == 1:
                raise RuntimeError("recovery failed")

        controller = restart.RestartController(recover=recover)
        status = controller.request(())
        self.assertEqual(status.phase, "failed")
        self.assertEqual(status.error, "recovery failed")
        status = controller.retry()
        self.assertEqual(status.phase, "active")
        self.assertEqual(len(calls), 2)

    def test_request_restart_reuses_failed_cleanup_ledger(self):
        def fail_recovery(_generation):
            raise RuntimeError("recovery failed")

        controller = restart.RestartController(
            drain=lambda _generation, _required: None,
            observe=lambda _identity: True,
            recover=fail_recovery,
        )
        self.assertEqual(controller.request(("scope",)).phase, "failed")
        self.assertEqual(controller.status.phase, "failed")
        controller.recover = lambda _generation: None
        with patch.object(restart, "_CONTROLLER", controller), \
                patch.object(restart, "_runtime_obligations",
                             side_effect=AssertionError("must reuse retained ledger")):
            status = restart.request_restart()
        self.assertEqual(status.phase, "active")
        self.assertEqual(status.generation, 2)

    def test_unrelated_or_duplicate_receipts_do_not_finish_restart(self):
        controller = restart.RestartController()
        status = controller.request(("scope",))
        self.assertEqual(status.phase, "draining")
        self.assertFalse(controller.receipt("updates"))
        self.assertEqual(controller.poll().phase, "draining")
        self.assertTrue(controller.receipt("scope"))
        self.assertEqual(controller.status.phase, "active")

    def test_rejected_project_receipt_remains_failed_with_cleanup_debt(self):
        controller = restart.RestartController(
            on_receipt=lambda _generation, _identity: False,
        )
        self.assertEqual(controller.request(("scope",)).phase, "draining")
        self.assertFalse(controller.receipt("scope"))
        self.assertEqual(controller.status.phase, "failed")
        self.assertEqual(controller.status.required, ("scope",))
        self.assertEqual(controller.status.retired, ("scope",))


class RestartRegistrationTests(unittest.TestCase):
    def test_operator_and_menu_hook_unregister_cleanly(self):
        restart.unregister()
        menu = bpy.types.TOPBAR_MT_file
        before = tuple(getattr(menu.draw, "_draw_funcs", ()))
        classes = restart.register()
        self.assertEqual(len(classes), 1)
        self.assertTrue(classes[0].is_registered)
        self.assertEqual(classes[0].bl_idname, "wm.pg_next_restart")
        after = tuple(getattr(menu.draw, "_draw_funcs", ()))
        self.assertTrue(any(callback not in before for callback in after))
        installed = tuple(callback for _menu, callback in restart._MENU_ENTRIES)
        restart.unregister()
        current = tuple(getattr(menu.draw, "_draw_funcs", ()))
        self.assertTrue(all(callback not in current for callback in installed))

    def test_restart_recovery_does_not_reenter_restart_registration(self):
        controller = restart.RestartController()
        with patch.object(restart, "_CONTROLLER", controller), \
                patch.object(restart, "_runtime_obligations", return_value=()), \
                patch.object(restart, "_recover_blender") as recover:
            controller.recover = recover
            self.assertEqual(controller.request(()).phase, "active")
        recover.assert_called_once_with(controller.status.generation)


if __name__ == "__main__":
    unittest.main()
