"""Blender integration for the independent Perceptual Grade Next product."""

from .native_grade import NativeGrade, build_native_grade
from .stack import StackDatablock, StackPreparation, prepare_stack, refine_stack

__all__ = (
    "NativeGrade", "StackDatablock", "StackPreparation", "build_native_grade",
    "prepare_stack", "refine_stack", "NativeStack", "build_native_stack",
    "BakeResult", "BakeSource", "BakeRoute", "BakeRouteFacts", "BakeRouteVerdict",
    "FrozenBakeInput", "capture_grade", "capture_stack", "freeze_bake_input",
    "inspect_bake_route",
    "ImagePublication", "BlenderImageBackupStore", "publish_blender_image",
    "EvaluatorBinding", "OutputGateway", "OutputRequest",
    "bind_grade_evaluator", "bind_stack_evaluator",
    "ProjectWorkflow", "RestartSupervisor", "ScopeActor", "ScopeSubmission",
    "RestartController", "RestartStatus", "request_restart",
    "ViewAuthority", "ViewDisplay",
    "ScopeContext", "ScopeDemand", "ScopeRuntime", "ScopeVisual",
    "context_owner",
    "OwnerReadiness", "ProjectReadiness", "ReadinessSnapshot",
    "inspect_project_owners", "project_readiness_runtime",
    "refresh_project_readiness",
    "RecoveryResult", "recover_document", "last_recovery",
    "read_image_rgba", "write_image_rgba", "image_source_from_owner",
    "NativeShaderEvaluator", "NativeStackShaderEvaluator", "image_texture_from_owner",
)


def __getattr__(name):
    if name in {"NativeStack", "build_native_stack"}:
        from .stack_graph import NativeStack, build_native_stack
        return {"NativeStack": NativeStack, "build_native_stack": build_native_stack}[name]
    if name in {"BakeResult", "BakeSource", "BakeRoute", "BakeRouteFacts", "BakeRouteVerdict",
                "FrozenBakeInput", "capture_grade", "capture_stack",
                "freeze_bake_input", "inspect_bake_route"}:
        from .bake import (
            BakeResult, BakeSource, BakeRoute, BakeRouteFacts, BakeRouteVerdict,
            FrozenBakeInput,
            capture_grade, capture_stack, freeze_bake_input, inspect_bake_route,
        )
        return {
            "BakeResult": BakeResult, "BakeSource": BakeSource,
            "BakeRoute": BakeRoute, "BakeRouteFacts": BakeRouteFacts,
            "BakeRouteVerdict": BakeRouteVerdict,
            "FrozenBakeInput": FrozenBakeInput,
            "capture_grade": capture_grade, "capture_stack": capture_stack,
            "freeze_bake_input": freeze_bake_input,
            "inspect_bake_route": inspect_bake_route,
        }[name]
    if name in {"ImagePublication", "BlenderImageBackupStore", "publish_blender_image"}:
        from .image_publication import (
            ImagePublication, BlenderImageBackupStore, publish_blender_image,
        )
        return {
            "ImagePublication": ImagePublication,
            "BlenderImageBackupStore": BlenderImageBackupStore,
            "publish_blender_image": publish_blender_image,
        }[name]
    if name in {"EvaluatorBinding", "OutputGateway", "OutputRequest"}:
        from .output_gateway import EvaluatorBinding, OutputGateway, OutputRequest
        return {"EvaluatorBinding": EvaluatorBinding, "OutputGateway": OutputGateway,
                "OutputRequest": OutputRequest}[name]
    if name in {"bind_grade_evaluator", "bind_stack_evaluator"}:
        from .native_capture import bind_grade_evaluator, bind_stack_evaluator
        return {"bind_grade_evaluator": bind_grade_evaluator,
                "bind_stack_evaluator": bind_stack_evaluator}[name]
    if name in {"ProjectWorkflow", "RestartSupervisor", "ScopeActor", "ScopeSubmission",
                "ViewAuthority", "ViewDisplay"}:
        from .lifecycle import (
            ProjectWorkflow, RestartSupervisor, ScopeActor, ScopeSubmission,
            ViewAuthority, ViewDisplay,
        )
        return {"ProjectWorkflow": ProjectWorkflow, "RestartSupervisor": RestartSupervisor,
                "ScopeActor": ScopeActor, "ScopeSubmission": ScopeSubmission,
                "ViewAuthority": ViewAuthority, "ViewDisplay": ViewDisplay}[name]
    if name in {"RestartController", "RestartStatus", "request_restart"}:
        from .restart import RestartController, RestartStatus, request_restart
        return {
            "RestartController": RestartController,
            "RestartStatus": RestartStatus,
            "request_restart": request_restart,
        }[name]
    if name in {"ScopeContext", "ScopeDemand", "ScopeRuntime", "ScopeVisual", "context_owner"}:
        from .scope_runtime import ScopeContext, ScopeDemand, ScopeRuntime, ScopeVisual, context_owner
        return {"ScopeContext": ScopeContext, "ScopeDemand": ScopeDemand,
                "ScopeRuntime": ScopeRuntime, "ScopeVisual": ScopeVisual,
                "context_owner": context_owner}[name]
    if name in {"OwnerReadiness", "ProjectReadiness", "ReadinessSnapshot",
                "inspect_project_owners", "project_readiness_runtime",
                "refresh_project_readiness"}:
        from .project_readiness import (
            OwnerReadiness, ProjectReadiness, ReadinessSnapshot,
            inspect_project_owners, project_readiness_runtime,
            refresh_project_readiness,
        )
        return {
            "OwnerReadiness": OwnerReadiness,
            "ProjectReadiness": ProjectReadiness,
            "ReadinessSnapshot": ReadinessSnapshot,
            "inspect_project_owners": inspect_project_owners,
            "project_readiness_runtime": project_readiness_runtime,
            "refresh_project_readiness": refresh_project_readiness,
        }[name]
    if name in {"RecoveryResult", "recover_document", "last_recovery"}:
        from .recovery import RecoveryResult, recover_document, last_recovery
        return {
            "RecoveryResult": RecoveryResult,
            "recover_document": recover_document,
            "last_recovery": last_recovery,
        }[name]
    if name in {"read_image_rgba", "write_image_rgba", "image_source_from_owner",
                "image_texture_from_owner", "NativeShaderEvaluator",
                "NativeStackShaderEvaluator"}:
        from .native_bake import (
            NativeShaderEvaluator, NativeStackShaderEvaluator,
            image_source_from_owner, image_texture_from_owner,
            read_image_rgba, write_image_rgba,
        )
        return {
            "read_image_rgba": read_image_rgba,
            "write_image_rgba": write_image_rgba,
            "image_source_from_owner": image_source_from_owner,
            "image_texture_from_owner": image_texture_from_owner,
            "NativeShaderEvaluator": NativeShaderEvaluator,
            "NativeStackShaderEvaluator": NativeStackShaderEvaluator,
        }[name]
    if name in {"OutputActionController", "SaveOptions", "RenderOptions"}:
        from .output_operators import OutputActionController, SaveOptions, RenderOptions
        return {
            "OutputActionController": OutputActionController,
            "SaveOptions": SaveOptions,
            "RenderOptions": RenderOptions,
        }[name]
    raise AttributeError(name)


def register():
    from . import scope_runtime
    scope_runtime.register()
    from . import operators
    operators.register()
    from . import bake_operators
    bake_operators.register()
    from . import output_operators
    output_operators.register()
    from . import recovery
    recovery.register()
    from . import restart
    restart.register()


def unregister():
    from . import restart
    restart.unregister()
    from . import recovery
    recovery.unregister()
    from . import output_operators
    output_operators.unregister()
    from . import bake_operators
    bake_operators.unregister()
    from . import operators
    operators.unregister()
    from . import scope_runtime
    scope_runtime.unregister()
