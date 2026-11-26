"""Accelerated reference execution with the corrected Warp ordering."""
import numpy as np
from .model import Model
from .grading import ColorSettings
from .stack import Stack,FROM_NATIVE,matrix_native
from .bake import Kernel, Inverse
from .bake_inverse_gpu import RELEASE_NATIVE_OPERATION
from .export import OutputCompressionSettings
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
        kernels = tuple(
            Kernel(data, m.tone, m.color, self.table, hk_guard=self.hk_guard,
                   tone_chroma=m.tone_chroma,
                   output_compression=m.settings.output_compression if i == len(self.models) - 1
                   else OutputCompressionSettings())
            for i, m in enumerate(self.models)
        )
        StackKernel.__init__(self,kernels,[matrix_native(m) for m in self.models],self.inverses,
            self.directions,FROM_NATIVE,model.acescg_y,[m.nonlinear_key for m in self.models],
            tone_factory=ToneTable)
        # The reference kernel includes the integrated Unified Chroma stage.
        # Use its inverse around the shared accelerated solver, while leaving
        # legacy kernels on the portable inverse implementation.
        solvers=[]
        for kernel, solver in zip(self.kernels, self.solvers):
            if kernel.tone_chroma is None:
                solvers.append(solver)
                continue
            replacement=Inverse(kernel, FROM_NATIVE, model.acescg_y)
            replacement.tone_table=solver.tone_table
            solvers.append(replacement)
        self.solvers=tuple(solvers)
        # Terminal inverse release must see the final Stage 1 inverse matrix.
        # bake_native applies it before compression and AP1 projection.
        self.output_matrix = np.eye(3, dtype='f4')

    @staticmethod
    def matrix(rgb, matrix):
        if np.array_equal(matrix, np.eye(3, dtype=matrix.dtype)):
            return rgb
        return StackKernel.matrix(rgb, matrix)

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
        baked = super().bake_native(values, backend, checkpoint, program)
        if self.directions and self.directions[-1] == 'INVERSE':
            if checkpoint is not None:
                checkpoint()
            native = self.matrix(baked[..., :3], self.inverses[-1])
            if not np.isfinite(native).all():
                raise ArithmeticError('Nonfinite terminal inverse matrix result')
            kernel = self.kernels[-1]
            if backend == 'GPU':
                program.set_inverse(self.solvers[-1])
                rgb = program.evaluate(native, RELEASE_NATIVE_OPERATION)[..., :3].reshape(native.shape)
            else:
                rgb = kernel.final_export(kernel.enter(native), native)
            if not np.isfinite(rgb).all():
                raise ArithmeticError('Nonfinite terminal inverse release')
            baked[..., :3] = rgb
        return baked
