"""Controlled scope raster path for native execution transport tests."""
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType


def main():
    config = json.loads(Path(sys.argv[-2]).read_text())
    mode = sys.argv[-1]
    name = '_perceptual_grade_scope_helper'
    module = ModuleType(name)
    module.__path__ = [config['package']]
    module.__package__ = name
    sys.modules[name] = module

    cloud = importlib.import_module(name + '.perceptual_grade_blender.model.scope_cloud_gpu')
    original = cloud.render

    def controlled(result, views=(), use_gpu=True, checkpoint=None):
        if use_gpu and mode == 'fail_gpu':
            raise RuntimeError('Forced Warp GPU helper failure')
        records = original(result, views, use_gpu=False, checkpoint=checkpoint)
        if not use_gpu:
            return records
        return tuple(dict(record, backend='gpu') for record in records)

    cloud.render = controlled
    bake = importlib.import_module(name + '.perceptual_grade_blender.jobs.handlers.bake')
    bake._device = lambda: 'Controlled scope renderer'
    importlib.import_module(name + '.blender_runtime.execution.worker').run(config, name)


if __name__ == '__main__':
    main()
