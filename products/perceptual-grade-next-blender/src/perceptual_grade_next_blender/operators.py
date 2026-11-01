"""Small Blender adapter for inserting the accepted native Grade graph."""

_OPERATOR_CLASS = None
_STACK_OPERATOR_CLASS = None
_MENUS_REGISTERED = []


def _add_node_menu(self, context):
    space = getattr(context, "space_data", None)
    tree = getattr(space, "edit_tree", None)
    if tree is not None and tree.bl_idname in {"ShaderNodeTree", "CompositorNodeTree"}:
        self.layout.separator()
        self.layout.operator("node.pg_next_add_native_grade", icon="NODETREE")
        self.layout.operator("node.pg_next_add_native_stack", icon="NODETREE")


def register():
    global _OPERATOR_CLASS, _STACK_OPERATOR_CLASS
    import bpy
    from . import controls

    # Controls are registered before the operator so every newly inserted
    # Grade group gets its static authored property surface.
    controls.register()

    if _OPERATOR_CLASS is not None:
        return _OPERATOR_CLASS

    class PGNEXT_OT_add_native_grade(bpy.types.Operator):
        bl_idname = "node.pg_next_add_native_grade"
        bl_label = "Add Perceptual Grade Next"
        bl_description = "Insert the native forward Grade graph"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context):
            space = getattr(context, "space_data", None)
            tree = getattr(space, "edit_tree", None)
            return bool(tree and tree.bl_idname in {"ShaderNodeTree", "CompositorNodeTree"})

        def execute(self, context):
            from .native_grade import build_native_grade

            space = context.space_data
            tree = space.edit_tree
            native = None
            node = None
            try:
                native = build_native_grade(tree_type=tree.bl_idname)
                node_type = "ShaderNodeGroup" if tree.bl_idname == "ShaderNodeTree" else "CompositorNodeGroup"
                node = tree.nodes.new(node_type)
                node.node_tree = native.tree
                node.label = "Grade (Native)"
                node.location = space.cursor_location
                node["perceptual_grade_next_backend"] = "native_grade_graph"
                node["perceptual_grade_next_schema"] = 1
                node["perceptual_grade_next_settings"] = native.tree["perceptual_grade_next_settings"]
                node["perceptual_grade_next_edit_revision"] = 0
                node["perceptual_grade_next_applied_revision"] = 0
                node["perceptual_grade_next_preparation_state"] = "READY"
                node["perceptual_grade_next_preparation_error"] = ""
                controls.attach_controls(node, native.settings)
                from .project_readiness import accept_grade_manifest
                accept_grade_manifest(node, native)
                from .updates import register_native_owner
                register_native_owner(node, native, "grade")
                node["perceptual_grade_next_controls_static"] = True
            except Exception as error:
                if node is not None:
                    tree.nodes.remove(node)
                if native is not None and native.tree.users == 0:
                    native.controller.dispose(unlink=True)
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    class PGNEXT_OT_add_native_stack(bpy.types.Operator):
        bl_idname = "node.pg_next_add_native_stack"
        bl_label = "Add Perceptual Grade Stack Next"
        bl_description = "Insert a 33^3 preview that refines to the native 65^3 Stack LUT"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context):
            space = getattr(context, "space_data", None)
            tree = getattr(space, "edit_tree", None)
            return bool(tree and tree.bl_idname in {"ShaderNodeTree", "CompositorNodeTree"})

        def execute(self, context):
            from .stack_graph import build_native_stack

            space = context.space_data
            tree = space.edit_tree
            native = None
            node = None
            try:
                native = build_native_stack(tree_type=tree.bl_idname, final=False)
                node_type = "ShaderNodeGroup" if tree.bl_idname == "ShaderNodeTree" else "CompositorNodeGroup"
                node = tree.nodes.new(node_type)
                node.node_tree = native.tree
                node.label = "Grade Stack (Preview → Final)"
                node.location = space.cursor_location
                node["perceptual_grade_next_backend"] = "native_stack_lut"
                node["perceptual_grade_next_schema"] = 1
                node["perceptual_grade_next_stack_evaluator"] = native.tree.get(
                    "perceptual_grade_next_stack_bake_evaluator", ""
                )
                node["perceptual_grade_next_stack_quality_tier"] = native.tree.get(
                    "perceptual_grade_next_stack_quality_tier", ""
                )
                node["perceptual_grade_next_stack_settings"] = native.tree.get(
                    "perceptual_grade_next_stack_settings", ""
                )
                node["perceptual_grade_next_edit_revision"] = 0
                node["perceptual_grade_next_applied_revision"] = 0
                node["perceptual_grade_next_preparation_state"] = "PENDING"
                node["perceptual_grade_next_preparation_error"] = ""
                controls.attach_stack_controls(node, native.preparation.settings)
                from .updates import register_native_owner
                register_native_owner(node, native, "stack")
                from .updates import mark_node_dirty
                mark_node_dirty(node)
            except Exception as error:
                if node is not None:
                    tree.nodes.remove(node)
                if native is not None:
                    native.dispose(unlink=True)
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            return {"FINISHED"}

    bpy.utils.register_class(PGNEXT_OT_add_native_grade)
    bpy.utils.register_class(PGNEXT_OT_add_native_stack)
    _OPERATOR_CLASS = PGNEXT_OT_add_native_grade
    _STACK_OPERATOR_CLASS = PGNEXT_OT_add_native_stack
    for name in ("NODE_MT_category_shader_color", "NODE_MT_category_compositor_color"):
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(_add_node_menu)
            _MENUS_REGISTERED.append(menu)
    return _OPERATOR_CLASS


def unregister():
    global _OPERATOR_CLASS, _STACK_OPERATOR_CLASS
    import bpy

    while _MENUS_REGISTERED:
        menu = _MENUS_REGISTERED.pop()
        try:
            menu.remove(_add_node_menu)
        except ValueError:
            pass
    from .updates import cancel_pending_updates
    cancel_pending_updates()
    if _OPERATOR_CLASS is not None:
        bpy.utils.unregister_class(_OPERATOR_CLASS)
        _OPERATOR_CLASS = None
    if _STACK_OPERATOR_CLASS is not None:
        bpy.utils.unregister_class(_STACK_OPERATOR_CLASS)
        _STACK_OPERATOR_CLASS = None
    from . import controls
    controls.unregister()
