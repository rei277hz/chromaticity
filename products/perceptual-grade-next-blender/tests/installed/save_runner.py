"""Invoke the owned Save path against a deliberately unwritable Image."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys

import bpy


def main(repository, project_path, report_path):
    if tuple(bpy.app.version) != (5, 2, 2):
        raise RuntimeError("Installed Save acceptance requires Blender 5.2.2")
    repository = Path(repository).resolve()
    bpy.context.preferences.extensions.repos.new(
        name="Perceptual Grade Next Save acceptance",
        module="pg_next_save_acceptance",
        custom_directory=str(repository),
    )
    name = "bl_ext.pg_next_save_acceptance.perceptual_grade"
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    if addon is None or errors:
        raise RuntimeError("Could not enable packaged Next extension: %r" % errors)
    package = repository / "perceptual_grade" / "__init__.py"
    if Path(addon.__file__).resolve() != package:
        raise RuntimeError("Blender imported Save code outside the packaged extension")

    modules = name + ".perceptual_grade_next_blender."
    gateway_type = importlib.import_module(modules + "output_gateway").OutputGateway
    operators = importlib.import_module(modules + "output_operators")
    controller_type = operators.OutputActionController
    options_type = operators.SaveOptions
    gateway = gateway_type()
    if not gateway.dispatch("open", generation=1, owners=(), owner_evaluators=()):
        raise RuntimeError("Could not open the no-owner Save fixture")
    controller = controller_type(gateway)

    image_path = Path("/dev/null/cannot-save.png")
    image = bpy.data.images.new(
        "Unwritable Modified User Image", width=1, height=1,
        alpha=True, float_buffer=True,
    )
    image.pixels.foreach_set((0.25, 0.5, 0.75, 1.0))
    image.update()
    image.filepath_raw = str(image_path)
    image.file_format = "PNG"
    if not image.is_dirty:
        raise RuntimeError("Save fixture Image is not dirty")

    save_pre = []
    def on_save_pre(_scene):
        save_pre.append(True)

    bpy.app.handlers.save_pre.append(on_save_pre)
    options = options_type(
        filepath=str(project_path),
        save_as=True,
        use_compression=False,
        save_modified_images=True,
    )
    try:
        result = controller.save(
            lambda options: operators._native_save(options),
            options,
        )
    finally:
        while on_save_pre in bpy.app.handlers.save_pre:
            bpy.app.handlers.save_pre.remove(on_save_pre)

    failed_path = Path("/dev/null/cannot-create-project.blend")
    failed_options = options_type(
        filepath=str(failed_path),
        save_as=True,
        use_compression=False,
        save_modified_images=False,
    )
    try:
        failed_result = controller.save(
            lambda current: operators._native_save(current), failed_options,
        )
        failed_save_error = ""
    except RuntimeError as error:
        failed_result = {"RAISED"}
        failed_save_error = str(error)

    project_exists = Path(project_path).is_file()
    image_output_exists = image_path.exists()
    failed_save_released = (
        controller.gateway.state.phase == "active"
        and not controller.gateway.state.publication_hold
        and controller.pending_save_operation is None
        and not failed_path.exists()
    )
    data = {
        "passed": (
            result == {"FINISHED"} and project_exists
            and len(save_pre) == 1 and not image_output_exists
            and "Unwritable Modified User Image" in options.diagnostics.unsaved_images
            and failed_save_released
        ),
        "blender": list(bpy.app.version),
        "extension_origin": str(Path(addon.__file__).resolve()),
        "save_result": sorted(result),
        "unsaved_image_diagnostics": list(options.diagnostics.unsaved_images),
        "project_exists": project_exists,
        "save_pre_count": len(save_pre),
        "image_output_exists": image_output_exists,
        "workflow_phase": controller.gateway.state.phase,
        "image_path": image.filepath,
        "failed_save_result": sorted(failed_result),
        "failed_save_error": failed_save_error,
        "failed_save_hold_released": failed_save_released,
    }
    Path(report_path).write_text(json.dumps(data, sort_keys=True), encoding="utf8")
    if not data["passed"]:
        raise RuntimeError("Owned Save acceptance failed: %r" % data)


if __name__ == "__main__":
    main(*sys.argv[sys.argv.index("--") + 1:])
