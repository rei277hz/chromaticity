"""Process entrypoint for native Bake and vectorscope capture."""

from .capture_host import register_snapshot_node_types


class CaptureWorker:
    def dispatch(self, operation, inputs, context):
        context.checkpoint()
        if operation == "gpu_probe":
            import bpy

            register_snapshot_node_types()
            return {"conformance": True, "backend": "NODE_TREE", "blender": tuple(bpy.app.version)}
        if operation == "bake":
            from .bake_worker import bake

            return bake(inputs, context)
        if operation == "vectorscope_capture":
            from ..scopes.vectorscope.capture import capture

            return capture(inputs, context)
        raise ValueError("Unknown capture helper operation: " + str(operation))


def create():
    return CaptureWorker()
