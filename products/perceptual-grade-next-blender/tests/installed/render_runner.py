"""Exercise the packaged Render controller and native terminal receipts."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys

import bpy


def main(repository, report_path):
    if tuple(bpy.app.version) != (5, 2, 2):
        raise RuntimeError("Installed Render acceptance requires Blender 5.2.2")
    repository = Path(repository).resolve()
    bpy.context.preferences.extensions.repos.new(
        name="Perceptual Grade Next Render acceptance",
        module="pg_next_render_acceptance",
        custom_directory=str(repository),
    )
    module = "bl_ext.pg_next_render_acceptance.perceptual_grade"
    errors = []
    addon = addon_utils.enable(module, default_set=False, handle_error=errors.append)
    if addon is None or errors:
        raise RuntimeError("Could not enable packaged Next extension: %r" % errors)
    package = repository / "perceptual_grade" / "__init__.py"
    if Path(addon.__file__).resolve() != package:
        raise RuntimeError("Blender imported Render code outside the packaged extension")

    modules = module + ".perceptual_grade_next_blender."
    operators = importlib.import_module(modules + "output_operators")
    gateway_type = importlib.import_module(modules + "output_gateway").OutputGateway
    options_type = operators.RenderOptions
    gateway = gateway_type()
    if not gateway.dispatch("open", generation=1, owners=(), owner_evaluators=()):
        raise RuntimeError("Could not open the no-owner Render fixture")
    controller = operators.OutputActionController(gateway)
    operators._CONTROLLER = controller
    invocation_count = 0

    def pending_render(_options):
        nonlocal invocation_count
        invocation_count += 1
        return {"RUNNING_MODAL"}

    scene = bpy.context.scene
    result = controller.render(
        pending_render,
        options_type(scene=scene.name),
    )
    operation = controller.active_render_operation
    if result != {"RUNNING_MODAL"} or operation is None:
        raise RuntimeError("Render did not retain its modal operation")
    if not gateway.state.publication_hold:
        raise RuntimeError("Render released the publication hold before its terminal receipt")

    repeated = controller.continue_render(operation)
    if repeated != {"RUNNING_MODAL"} or invocation_count != 1:
        raise RuntimeError("A modal Render was invoked a second time")
    wrong_scene_rejected = not operators.native_render_terminal(
        committed=True, scene="Different Scene",
    )
    if not wrong_scene_rejected or not gateway.state.publication_hold:
        raise RuntimeError("A different scene's terminal callback released Render")
    completed = operators.native_render_terminal(committed=True, scene=scene)
    completed_hold_released = completed and not gateway.state.publication_hold
    duplicate_terminal_rejected = not operators.native_render_terminal(
        committed=True, scene=scene,
    )
    if not completed_hold_released or not duplicate_terminal_rejected:
        raise RuntimeError("Render completion did not consume exactly one matching receipt")

    cancelled = controller.render(
        pending_render,
        options_type(scene=scene.name, animation=True),
    )
    cancelled_operation = controller.active_render_operation
    if (cancelled != {"RUNNING_MODAL"} or cancelled_operation is None
            or not gateway.state.publication_hold):
        raise RuntimeError("Animation Render did not retain its modal hold")
    cancelled_terminal = operators.native_render_terminal(
        committed=False, scene=scene,
    )
    cancelled_hold_released = cancelled_terminal and not gateway.state.publication_hold
    if not cancelled_hold_released:
        raise RuntimeError("Matching cancelled Render receipt did not release its hold")

    data = {
        "passed": (
            invocation_count == 2 and wrong_scene_rejected
            and completed_hold_released and duplicate_terminal_rejected
            and cancelled_hold_released and gateway.state.phase == "active"
        ),
        "blender": list(bpy.app.version),
        "extension_origin": str(Path(addon.__file__).resolve()),
        "invocation_count": invocation_count,
        "wrong_scene_receipt_rejected": wrong_scene_rejected,
        "completed_hold_released": bool(completed_hold_released),
        "duplicate_terminal_rejected": duplicate_terminal_rejected,
        "cancelled_hold_released": bool(cancelled_hold_released),
        "workflow_phase": gateway.state.phase,
    }
    Path(report_path).write_text(json.dumps(data, sort_keys=True), encoding="utf8")
    if not data["passed"]:
        raise RuntimeError("Owned Render acceptance failed: %r" % data)


if __name__ == "__main__":
    main(*sys.argv[sys.argv.index("--") + 1:])
