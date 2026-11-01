"""Exercise the actual packaged extension in pinned Blender."""

import addon_utils
from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import uuid

import bpy


def _enable(repository):
    repository = Path(repository).resolve()
    bpy.context.preferences.extensions.repos.new(
        name="Perceptual Grade Next installed acceptance",
        module="pg_next_acceptance",
        custom_directory=str(repository),
    )
    name = "bl_ext.pg_next_acceptance.perceptual_grade"
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    if addon is None or errors:
        raise RuntimeError("Could not enable packaged Next extension: %r" % errors)
    package = repository / "perceptual_grade" / "__init__.py"
    if Path(addon.__file__).resolve() != package:
        raise RuntimeError("Blender imported Next from outside the packaged extension")
    return name, addon


def _owner(bpy):
    for tree in bpy.data.node_groups:
        for node in tree.nodes:
            if node.get("perceptual_grade_next_backend") == "native_grade_graph":
                return tree, node
    summary = [
        (tree.name, tree.bl_idname, tree.users,
         tuple((node.name, node.get("perceptual_grade_next_backend", ""))
               for node in tree.nodes
               if node.get("perceptual_grade_next_backend")))
        for tree in bpy.data.node_groups
    ]
    raise RuntimeError("Saved file has no native Next Grade owner: %r" % (summary,))


def _stack_owner(bpy):
    for tree in bpy.data.node_groups:
        for node in tree.nodes:
            if node.get("perceptual_grade_next_backend") == "native_stack_lut":
                return tree, node
    raise RuntimeError("Saved file has no native Next Stack owner")


def _record(report, mode, **values):
    report.write_text(json.dumps({
        "passed": True,
        "mode": mode,
        "blender": list(bpy.app.version),
        **values,
    }, sort_keys=True), encoding="utf8")


def _image_digest(image):
    import numpy as np

    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return hashlib.sha256(pixels.tobytes(order="C")).hexdigest()


def _grade_settings_with_different_tone(settings):
    tone = replace(settings.tone, fit=0.5)
    return replace(settings, tone=tone)


def main(mode, repository, project, report_path, boundary="binding_only"):
    report = Path(report_path)
    project = Path(project)
    name, _addon = _enable(repository)
    if tuple(bpy.app.version) != (5, 2, 2):
        raise RuntimeError("Installed acceptance requires Blender 5.2.2")
    output_operators = importlib.import_module(
        name + ".perceptual_grade_next_blender.output_operators"
    )
    wrapped_menus = tuple(
        getattr(menu, "__name__", "")
        for menu, _original, _wrapper, _had_draw_funcs
        in output_operators._MENU_WRAPPERS
    )
    if set(wrapped_menus) != {"TOPBAR_MT_file", "TOPBAR_MT_render"}:
        raise RuntimeError("Installed Save/Render menu hooks are missing: %r" % (wrapped_menus,))

    if mode == "create":
        module = importlib.import_module(name + ".perceptual_grade_next_blender.native_grade")
        controls = importlib.import_module(name + ".perceptual_grade_next_blender.controls")
        updates = importlib.import_module(name + ".perceptual_grade_next_blender.updates")
        native = module.build_native_grade(name="Installed Next Grade")
        host = bpy.data.node_groups.new("Installed Next Owner", "ShaderNodeTree")
        host.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor",
        )
        host.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        source = host.nodes.new("NodeGroupInput")
        sink = host.nodes.new("NodeGroupOutput")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        host.links.new(source.outputs["Color"], node.inputs["Color"])
        host.links.new(node.outputs["Color"], sink.inputs["Color"])
        node["perceptual_grade_next_backend"] = "native_grade_graph"
        node["perceptual_grade_next_schema"] = 1
        node["perceptual_grade_next_settings"] = native.tree[
            "perceptual_grade_next_settings"
        ]
        node["perceptual_grade_next_edit_revision"] = 0
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "READY"
        node["perceptual_grade_next_preparation_error"] = ""
        controls.attach_controls(node, native.settings)
        readiness = importlib.import_module(
            name + ".perceptual_grade_next_blender.project_readiness"
        )
        readiness.accept_grade_manifest(node, native)
        updates.register_native_owner(node, native, "grade")
        if not all(image.packed_file for image in native.images):
            raise RuntimeError("Installed Grade fields are not packed")
        material = bpy.data.materials.new("Installed Next Acceptance Material")
        material.use_nodes = True
        material_tree = material.node_tree
        principled = material_tree.nodes.get("Principled BSDF")
        if principled is None:
            principled = material_tree.nodes.new("ShaderNodeBsdfPrincipled")
        material_grade = material_tree.nodes.new("ShaderNodeGroup")
        material_grade.node_tree = host
        material_tree.links.new(
            material_grade.outputs["Color"], principled.inputs["Base Color"],
        )
        mesh = bpy.data.meshes.new("Installed Next Acceptance Mesh")
        obj = bpy.data.objects.new("Installed Next Acceptance Object", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.data.materials.append(material)
        bpy.ops.wm.save_as_mainfile(
            filepath=str(project), check_existing=False, compress=False,
        )
        _record(
            report, mode,
            extension_origin=str(Path(_addon.__file__).resolve()),
            packed_field_count=len(native.images),
            recovery_complete=True,
            owner_tree=host.name,
            owner_tree_users=host.users,
            scene_object=obj.name,
        )
        return

    if mode == "create_stack":
        stack_graph = importlib.import_module(
            name + ".perceptual_grade_next_blender.stack_graph"
        )
        controls = importlib.import_module(name + ".perceptual_grade_next_blender.controls")
        updates = importlib.import_module(name + ".perceptual_grade_next_blender.updates")
        native = stack_graph.build_native_stack(
            name="Installed Next Stack", block_size=32768,
        )
        host = bpy.data.node_groups.new("Installed Next Stack Owner", "ShaderNodeTree")
        host.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor",
        )
        host.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        source = host.nodes.new("NodeGroupInput")
        sink = host.nodes.new("NodeGroupOutput")
        node = host.nodes.new("ShaderNodeGroup")
        node.node_tree = native.tree
        host.links.new(source.outputs["Color"], node.inputs["Color"])
        host.links.new(node.outputs["Color"], sink.inputs["Color"])
        node["perceptual_grade_next_backend"] = "native_stack_lut"
        node["perceptual_grade_next_schema"] = 1
        node["perceptual_grade_next_stack_settings"] = native.tree[
            "perceptual_grade_next_stack_settings"
        ]
        node["perceptual_grade_next_stack_evaluator"] = "stack_65_lut"
        node["perceptual_grade_next_stack_quality_tier"] = "65^3"
        node["perceptual_grade_next_edit_revision"] = 0
        node["perceptual_grade_next_applied_revision"] = 0
        node["perceptual_grade_next_preparation_state"] = "READY"
        node["perceptual_grade_next_preparation_error"] = ""
        controls.attach_stack_controls(node, native.preparation.settings)
        updates.register_native_owner(node, native, "stack")
        bpy.ops.wm.save_as_mainfile(
            filepath=str(project), check_existing=False, compress=False,
        )
        _record(
            report, mode,
            extension_origin=str(Path(_addon.__file__).resolve()),
            owner_tree=host.name,
            evaluator=node["perceptual_grade_next_stack_evaluator"],
            quality_tier=node["perceptual_grade_next_stack_quality_tier"],
            packed_image_count=len(native.images),
        )
        return

    if mode == "crash_stack_replacement":
        if "FINISHED" not in bpy.ops.wm.open_mainfile(filepath=str(project)):
            raise RuntimeError("Blender did not reopen the saved Stack project")
        tree, node = _stack_owner(bpy)
        stack_module = importlib.import_module(name + ".perceptual_grade_next_blender.stack")
        stack_graph = importlib.import_module(
            name + ".perceptual_grade_next_blender.stack_graph"
        )
        updates = importlib.import_module(name + ".perceptual_grade_next_blender.updates")
        preparation_ledger = importlib.import_module(
            name + ".perceptual_grade_next_blender.preparation_ledger"
        )
        prior = stack_module.reopen_stack(node.node_tree, rebuild=False)
        previous = node.node_tree
        transaction = uuid.uuid4().hex
        candidate = stack_graph.build_native_stack(
            preparation=prior.preparation,
            tree_type=previous.bl_idname,
            name=".PG Next Candidate Installed Stack",
            block_size=32768,
        )
        candidate.tree[preparation_ledger.CANDIDATE_OWNER_KEY] = str(node.as_pointer())
        candidate.tree[preparation_ledger.CANDIDATE_REVISION_KEY] = int(
            node.get("perceptual_grade_next_edit_revision", 0)
        ) + 1
        property_keys = (
            "perceptual_grade_next_stack_settings",
            "perceptual_grade_next_stack_evaluator",
            "perceptual_grade_next_stack_quality_tier",
            "perceptual_grade_next_applied_revision",
            "perceptual_grade_next_preparation_state",
            "perceptual_grade_next_preparation_error",
        )
        preparation_ledger.stage_tree_backing(
            tree, node, previous, candidate.tree, transaction,
            defaults={socket.name: updates._copy_socket_value(socket.default_value)
                      for socket in node.inputs if hasattr(socket, "default_value")},
            properties={key: (key in node, node.get(key)) for key in property_keys},
        )
        updates._write_ledger(
            node, kind="stack", revision=int(node.get(
                "perceptual_grade_next_edit_revision", 0)) + 1,
            stage="committing", prior_revision=int(node.get(
                "perceptual_grade_next_applied_revision", 0)),
            prior_settings=node.get("perceptual_grade_next_stack_settings", ""),
            transaction_id=transaction,
        )
        node.node_tree = candidate.tree
        node["perceptual_grade_next_stack_settings"] = candidate.tree[
            "perceptual_grade_next_stack_settings"
        ]
        node["perceptual_grade_next_stack_evaluator"] = candidate.tree[
            "perceptual_grade_next_stack_bake_evaluator"
        ]
        node["perceptual_grade_next_stack_quality_tier"] = candidate.tree[
            "perceptual_grade_next_stack_quality_tier"
        ]
        node["perceptual_grade_next_preparation_state"] = "PENDING"
        if "perceptual_grade_next_preparation_ledger" in node:
            del node["perceptual_grade_next_preparation_ledger"]
        bpy.ops.wm.save_as_mainfile(
            filepath=str(project), check_existing=False, compress=False,
        )
        _record(
            report, mode, transaction=transaction,
            prior_tree_name=previous.name,
            candidate_tree_name=candidate.tree.name,
        )
        os._exit(99)

    if mode == "reopen_stack_replacement":
        if "FINISHED" not in bpy.ops.wm.open_mainfile(filepath=str(project)):
            raise RuntimeError("Blender did not reopen the interrupted Stack project")
        tree, node = _stack_owner(bpy)
        crash = json.loads(Path(report_path).read_text(encoding="utf8"))
        if node.node_tree.name != crash["prior_tree_name"]:
            raise RuntimeError("Interrupted Stack replacement did not restore its prior tree")
        scope_runtime = importlib.import_module(
            name + ".perceptual_grade_next_blender.scope_runtime"
        )
        readiness = importlib.import_module(
            name + ".perceptual_grade_next_blender.project_readiness"
        )
        snapshot = readiness.inspect_project_owners(
            tuple(scope_runtime._project_node_trees(bpy))
        )
        if len(snapshot.owners) != 1 or not snapshot.ready:
            raise RuntimeError("Reopened prior Stack is not ready: %r" % (snapshot.owners,))
        stack_module = importlib.import_module(name + ".perceptual_grade_next_blender.stack")
        stack_module.reopen_stack(node.node_tree, rebuild=False)
        _record(
            report, mode, recovered_tree=node.node_tree.name,
            evaluator=snapshot.owners[0].evaluator,
            ready=snapshot.ready,
        )
        return

    if mode in {"crash_partial", "crash_boundary"}:
        boundary = "binding_only" if mode == "crash_partial" else boundary
        supported = {
            "field_upload", "binding_only", "metadata_publication",
            "structural_replacement", "committed_replacement",
        }
        if boundary not in supported:
            raise ValueError("Unknown installed crash boundary: " + boundary)
        if "FINISHED" not in bpy.ops.wm.open_mainfile(filepath=str(project)):
            raise RuntimeError("Blender did not reopen the saved Grade project")
        tree, node = _owner(bpy)
        updates = importlib.import_module(name + ".perceptual_grade_next_blender.updates")
        module = importlib.import_module(name + ".perceptual_grade_next_blender.native_grade")
        preparation_ledger = importlib.import_module(
            name + ".perceptual_grade_next_blender.preparation_ledger"
        )
        updates.process_pending_updates()
        live = updates._live_owner(updates._key(tree, node))
        if live is None or live[0] != "grade":
            raise RuntimeError("Reopened Grade owner did not have a live native controller")
        native = live[1]
        prior_tree_settings = native.tree.get("perceptual_grade_next_settings")
        prior_revision = native.tree.get("perceptual_grade_nodes_revision")
        expected_tree_name = native.tree.name
        prior_owner_settings = node.get("perceptual_grade_next_settings")
        ledger_data = None
        field_backups = []
        candidate_tree_name = ""
        if boundary in {"structural_replacement", "committed_replacement"}:
            settings, prepared = native.settings, native.controller.prepared
            transaction = uuid.uuid4().hex
            candidate = module.install_native_grade(
                settings, prepared, tree_type=tree.bl_idname,
                name=".PG Next Candidate Installed %s" % boundary,
                candidate_owner=str(node.as_pointer()),
                candidate_revision=int(node.get("perceptual_grade_next_edit_revision", 0)) + 1,
            )
            candidate_tree_name = candidate.tree.name
            preparation_ledger.stage_tree_backing(
                tree, node, native.tree, candidate.tree, transaction,
                defaults={socket.name: updates._copy_socket_value(socket.default_value)
                          for socket in node.inputs
                          if hasattr(socket, "default_value")},
                properties={
                    key: (key in node, node.get(key)) for key in (
                        "perceptual_grade_next_settings",
                        "perceptual_grade_next_applied_revision",
                        "perceptual_grade_next_preparation_state",
                        "perceptual_grade_next_preparation_error",
                        "perceptual_grade_next_accepted_grade_manifest",
                    )
                },
            )
            updates._write_ledger(
                node, kind="grade", revision=int(node.get(
                    "perceptual_grade_next_edit_revision", 0)) + 1,
                stage="committing", prior_revision=int(node.get(
                    "perceptual_grade_next_applied_revision", 0)),
                prior_settings=prior_owner_settings,
                transaction_id=transaction,
            )
            node.node_tree = candidate.tree
            node["perceptual_grade_next_settings"] = candidate.tree[
                "perceptual_grade_next_settings"
            ]
            node["perceptual_grade_next_edit_revision"] = int(
                node.get("perceptual_grade_next_edit_revision", 0)
            ) + 1
            node["perceptual_grade_next_applied_revision"] = int(
                node["perceptual_grade_next_edit_revision"]
            )
            node["perceptual_grade_next_preparation_state"] = "READY"
            readiness = importlib.import_module(
                name + ".perceptual_grade_next_blender.project_readiness"
            )
            readiness.accept_grade_manifest(node, candidate)
            if boundary == "committed_replacement":
                preparation_ledger.commit_tree_backing(node, transaction)
        else:
            prepared = native.controller.prepared
            if boundary == "field_upload":
                _settings, prepared = module.prepare_native_grade(
                    _grade_settings_with_different_tone(native.settings),
                    previous=native.controller.prepared,
                )
            transaction, slots = preparation_ledger.stage_grade_backing(
                tree, node, native, prepared,
                "installed-crash-" + boundary,
            )
            if boundary == "field_upload" and not slots:
                raise RuntimeError("Field-upload boundary staged no changed fields")
            if boundary != "field_upload" and slots:
                raise RuntimeError("Non-field boundary unexpectedly staged field backups")
            ledger = node.perceptual_grade_next_controls.preparation_ledger
            ledger_data = json.loads(ledger[
                "perceptual_grade_next_preparation_ledger_data"
            ])
            grade_snapshot = ledger_data["grade_snapshot"]
            if boundary == "field_upload":
                by_role = {}
                for item in ledger.nodes:
                    role = item.get(preparation_ledger.LEDGER_ROLE_KEY, "")
                    slot = item.get(preparation_ledger.LEDGER_SLOT_KEY, "")
                    if role in {"backup", "target"}:
                        by_role.setdefault(slot, {})[role] = item.image
                for slot in slots:
                    backup = by_role[slot]["backup"]
                    target_image = by_role[slot]["target"]
                    field_backups.append({
                        "slot": slot,
                        "image": target_image.name,
                        "digest": _image_digest(backup),
                    })
                    target_image.pixels[0] = float(target_image.pixels[0]) + 3.0
                    target_image.update()
            elif boundary == "binding_only":
                binding = grade_snapshot["bindings"][0]
                target_node = native.tree.nodes.get(binding["target_node"])
                target = target_node.inputs[binding["target_socket"]["index"]]
                for link in tuple(native.tree.links):
                    if link.to_socket == target:
                        native.tree.links.remove(link)
                try:
                    target.default_value = float(target.default_value) + 3.0
                except TypeError:
                    target.default_value = tuple(float(value) + 3.0
                                                 for value in target.default_value)
            elif boundary == "metadata_publication":
                native.tree["perceptual_grade_next_settings"] = "partial-crash-settings"
                native.tree["perceptual_grade_nodes_revision"] = int(prior_revision) + 100
                node["perceptual_grade_next_settings"] = "partial-crash-owner-settings"
                node["perceptual_grade_next_applied_revision"] = int(prior_revision) + 100
            else:
                raise AssertionError(boundary)
        if boundary != "committed_replacement":
            node["perceptual_grade_next_preparation_state"] = "PENDING"
        if "perceptual_grade_next_preparation_ledger" in node:
            del node["perceptual_grade_next_preparation_ledger"]
        bpy.ops.wm.save_as_mainfile(
            filepath=str(project), check_existing=False, compress=False,
        )
        snapshot_data = ledger_data or {}
        grade_snapshot = snapshot_data.get("grade_snapshot", {})
        _record(
            report, mode, boundary=boundary,
            transaction=transaction,
            prior_owner_settings=prior_owner_settings,
            prior_tree_name=expected_tree_name,
            candidate_tree_name=candidate_tree_name,
            prior_native_settings=prior_tree_settings,
            prior_native_revision=prior_revision,
            grade_snapshot=grade_snapshot,
            field_backups=field_backups,
        )
        # Deliberately bypass Blender/extension cleanup to model process loss.
        os._exit(99)

    if mode != "reopen":
        raise ValueError("Unknown installed acceptance mode: " + mode)

    # Load after extension registration so its PropertyGroups and persistent
    # load handlers are installed when Blender restores the file's RNA data.
    if "FINISHED" not in bpy.ops.wm.open_mainfile(filepath=str(project)):
        raise RuntimeError("Blender did not reopen the saved Grade project")
    tree, node = _owner(bpy)
    recovery = importlib.import_module(name + ".perceptual_grade_next_blender.recovery")
    updates = importlib.import_module(name + ".perceptual_grade_next_blender.updates")
    crash_report_path = Path(report_path)
    crash_report = (json.loads(crash_report_path.read_text(encoding="utf8"))
                    if crash_report_path.is_file() else {})
    if crash_report.get("mode") in {"crash_partial", "crash_boundary"}:
        native_tree = node.node_tree
        snapshot = crash_report["grade_snapshot"]
        boundary = crash_report.get("boundary", "binding_only")
        if boundary in {"structural_replacement", "committed_replacement"}:
            expected_name = (crash_report["prior_tree_name"]
                             if boundary == "structural_replacement"
                             else crash_report["candidate_tree_name"])
            if native_tree.name != expected_name:
                raise RuntimeError("Interrupted Grade replacement selected the wrong tree")
        else:
            for key, (present, expected) in snapshot.get("tree_properties", {}).items():
                if present and native_tree.get(key) != expected:
                    raise RuntimeError("Interrupted Grade tree property was not restored: " + key)
            for key, (present, expected) in snapshot.get("owner_properties", {}).items():
                actual = node.get(key)
                if key == "perceptual_grade_next_edit_revision":
                    restored = type(actual) is int and actual >= expected
                elif key == "perceptual_grade_next_preparation_state":
                    restored = actual in {expected, "PENDING"}
                else:
                    restored = actual == expected
                if present and not restored:
                    raise RuntimeError("Interrupted Grade owner property was not restored: " + key)
            for binding in snapshot.get("bindings", ()):
                target_node = native_tree.nodes.get(binding["target_node"])
                if target_node is None:
                    raise RuntimeError("Interrupted Grade binding target disappeared")
                target = target_node.inputs[binding["target_socket"]["index"]]
                links = [link for link in native_tree.links if link.to_socket == target]
                if len(links) != len(binding["sources"]):
                    raise RuntimeError("Interrupted Grade binding link count was not restored")
                if [link.from_node.name for link in links] != [
                        source["node"] for source in binding["sources"]]:
                    raise RuntimeError("Interrupted Grade binding source was not restored")
                if isinstance(binding["default"], list):
                    actual_default = [float(value) for value in target.default_value]
                else:
                    actual_default = float(target.default_value)
                if actual_default != binding["default"]:
                    raise RuntimeError("Interrupted Grade binding default was not restored")
            for field in crash_report.get("field_backups", ()):
                image = bpy.data.images.get(field["image"])
                if image is None or _image_digest(image) != field["digest"]:
                    raise RuntimeError("Interrupted Grade field upload was not restored")
    observed = recovery.last_recovery()
    if observed is None:
        scope_runtime = importlib.import_module(
            name + ".perceptual_grade_next_blender.scope_runtime"
        )
        observed = recovery.recover_document(
            tuple(scope_runtime._project_node_trees(bpy)),
        )
    failures = updates.process_pending_updates()
    if failures:
        raise RuntimeError("Reopen preparation failed: %r" % (failures,))
    tree, node = _owner(bpy)
    images = tuple(node.node_tree.nodes)
    fields = {
        image.image for image in images
        if getattr(image, "bl_idname", "") == "ShaderNodeTexImage"
        and getattr(image, "image", None) is not None
    }
    if not fields or not all(image.packed_file for image in fields):
        raise RuntimeError("Reopened Grade does not retain packed prepared fields")
    if node.get("perceptual_grade_next_preparation_state") != "READY":
        raise RuntimeError("Reopened Grade did not reach READY")
    if node.get("perceptual_grade_next_applied_revision") != node.get(
            "perceptual_grade_next_edit_revision"):
        raise RuntimeError("Reopened Grade revision did not settle")
    restart = importlib.import_module(name + ".perceptual_grade_next_blender.restart")
    readiness = importlib.import_module(
        name + ".perceptual_grade_next_blender.project_readiness"
    )
    prior_revision = node.get("perceptual_grade_next_applied_revision")
    prior_settings = node.get("perceptual_grade_next_settings")
    prior_field_count = len(fields)
    prior_generation = restart.controller().status.generation
    restart_result = bpy.ops.wm.pg_next_restart("EXEC_DEFAULT")
    if restart_result != {"FINISHED"}:
        raise RuntimeError("Idle installed Restart did not finish: %r" % (restart_result,))
    restart_failures = updates.process_pending_updates()
    if restart_failures:
        raise RuntimeError("Post-Restart preparation failed: %r" % (restart_failures,))
    restart_status = restart.controller().status
    if restart_status.phase != "active" or restart_status.generation <= prior_generation:
        raise RuntimeError("Idle installed Restart did not advance to active: %r" % (restart_status,))
    workflow = readiness.project_readiness_runtime().workflow
    if workflow.state.phase != "active":
        raise RuntimeError("Project workflow did not return to active after Restart")
    tree, node = _owner(bpy)
    fields_after_restart = {
        image.image for image in node.node_tree.nodes
        if getattr(image, "bl_idname", "") == "ShaderNodeTexImage"
        and getattr(image, "image", None) is not None
    }
    if (node.get("perceptual_grade_next_preparation_state") != "READY"
            or node.get("perceptual_grade_next_settings") != prior_settings
            or node.get("perceptual_grade_next_applied_revision") != node.get(
                "perceptual_grade_next_edit_revision"
            )
            or int(node.get("perceptual_grade_next_applied_revision", 0)) < prior_revision
            or len(fields_after_restart) != prior_field_count
            or not all(image.packed_file for image in fields_after_restart)):
        raise RuntimeError(
            "Idle Restart did not restore the accepted Grade and packed fields: "
            "state=%r applied=%r edit=%r prior_revision=%r prior_fields=%r "
            "new_fields=%r settings_match=%r packed=%r" % (
                node.get("perceptual_grade_next_preparation_state"),
                node.get("perceptual_grade_next_applied_revision"),
                node.get("perceptual_grade_next_edit_revision"), prior_revision,
                prior_field_count,
                len(fields_after_restart),
                node.get("perceptual_grade_next_settings") == prior_settings,
                [bool(image.packed_file) for image in fields_after_restart],
            )
        )

    action = restart.controller()
    recover = action.recover
    original_obligations = restart._runtime_obligations
    recovery_failed = False

    def fail_once(generation):
        nonlocal recovery_failed
        if not recovery_failed:
            recovery_failed = True
            raise RuntimeError("installed acceptance recovery fault")
        return recover(generation)

    action.recover = fail_once
    restart._runtime_obligations = lambda: ("scope",)
    failed_status = restart.request_restart()
    restart._runtime_obligations = original_obligations
    retried_restart = bpy.ops.wm.pg_next_restart("EXEC_DEFAULT")
    action.recover = recover
    retry_failures = updates.process_pending_updates()
    if (failed_status.phase != "failed"
            or failed_status.error != "installed acceptance recovery fault"):
        raise RuntimeError("Injected Restart recovery fault did not remain retryable: "
                           "%r" % (failed_status,))
    if (retry_failures or retried_restart != {"FINISHED"}
            or action.status.phase != "active"):
        raise RuntimeError("Restart operator did not retry its retained cleanup ledger: "
                           "%r %r %r" % (retried_restart, action.status, retry_failures))
    if action.status.generation <= restart_status.generation:
        raise RuntimeError("Restart retry did not advance its generation")
    workflow = readiness.project_readiness_runtime().workflow
    if workflow.state.phase != "active":
        raise RuntimeError("Project workflow did not recover after Restart retry")
    tree, node = _owner(bpy)
    fields_after_retry = {
        image.image for image in node.node_tree.nodes
        if getattr(image, "bl_idname", "") == "ShaderNodeTexImage"
        and getattr(image, "image", None) is not None
    }
    if (node.get("perceptual_grade_next_preparation_state") != "READY"
            or node.get("perceptual_grade_next_settings") != prior_settings
            or len(fields_after_retry) != prior_field_count
            or not all(image.packed_file for image in fields_after_retry)):
        raise RuntimeError("Restart retry did not preserve the authored Grade and fields")
    _record(
        report, mode,
        extension_origin=str(Path(importlib.import_module(name).__file__).resolve()),
        packed_field_count=len(fields),
        restart_result=sorted(restart_result),
        restart_generation=restart_status.generation,
        restart_phase=restart_status.phase,
        wrapped_menus=wrapped_menus,
        project_phase=workflow.state.phase,
        grade_ready_after_restart=True,
        grade_revision_after_restart=node.get("perceptual_grade_next_applied_revision"),
        packed_fields_retained=len(fields_after_restart),
        restart_recovery_fault_observed=(failed_status.error
                                         == "installed acceptance recovery fault"),
        restart_recovery_retry_succeeded=(retried_restart == {"FINISHED"}
                                          and action.status.phase == "active"),
        packed_fields_retained_after_retry=len(fields_after_retry),
        recovery_complete=(not observed.invalid and not failures
                           and node.get("perceptual_grade_next_preparation_state") == "READY"),
        crash_rollback_verified=(crash_report.get("mode") in {
            "crash_partial", "crash_boundary",
        }),
        crash_boundary=crash_report.get("boundary", "binding_only"),
    )


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(*args)
