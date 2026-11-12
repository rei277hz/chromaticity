"""Accelerated reference execution with the corrected Warp ordering."""
import numpy as np
from .model import Model
from .grading import ColorSettings
from .stack import Stack,FROM_NATIVE,matrix_native
from .bake import Kernel
from ..perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from ..perceptual_grade_core.model.stack_kernel import StackKernel
from ..perceptual_grade_core.model.tone_table import ToneTable


class BakeStack(StackKernel,Stack):
    def __init__(self,settings,directions=None,table=None,*,hk_guard=True, program_factory=None):
        settings = tuple(settings)
        for setting in settings:
            if not isinstance(setting.color, ColorSettings):
                raise ValueError('Unknown reference color settings schema')
            for name in ('lightness', 'chroma'):
                controls = np.asarray(getattr(setting.color, name))
                if controls.shape != (4, 4) or not np.isfinite(controls).all():
                    raise ValueError(f'{name} must be finite with shape (4, 4)')
        self.program_factory=program_factory
        Stack.__init__(self,settings,directions,hk_guard=hk_guard)
        self.hk_guard=bool(hk_guard)
        model=self.models[0] if self.models else Model(hk_guard=hk_guard)
        data=model.boundary.cache
        self.table=PolynomialTable(data) if table is None else table
        kernels=tuple(Kernel(data,m.tone,m.color,self.table,hk_guard=self.hk_guard) for m in self.models)
        StackKernel.__init__(self,kernels,[matrix_native(m) for m in self.models],self.inverses,
            self.directions,FROM_NATIVE,model.acescg_y,
            [(m.settings.tone,m.settings.color,self.hk_guard) for m in self.models],tone_factory=ToneTable)

    def prepare_gpu(self):
        if self.program is None:
            if not self.solvers:raise ValueError('An empty Stack has no compute program')
            factory=self.program_factory
            if factory is None:
                from .blender_gpu import InverseProgram
                factory=InverseProgram
            self.program=factory(self.solvers[0])
        return self.program

    def bake_native(self, values, backend='CPU', checkpoint=None, program=None):
        if backend == 'GPU' and self.solvers and program is None:
            program = self.prepare_gpu()
        return super().bake_native(values, backend, checkpoint, program)
