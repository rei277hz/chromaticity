"""This package owns its workers, storage, and operation vocabulary."""
from ...blender_runtime.execution.contracts import RuntimeProfile
from ...blender_runtime.execution.values import seal

storage_name = 'hdr_color_picker'
profile = RuntimeProfile(lanes=('bulk',), gpu_probes=(), fallback_lane='bulk', dispatcher='hdr_color_picker_blender.jobs.operations')
