"""Study-only compositor addresses for the baseline and selected input shaper.

Only Address helpers differ. Production tetrahedra, physical RGB fractions,
four nearest RGBE base/edge reads and blending remain unchanged. The temporary
module patches are for sequential graph construction on Blender's main thread.
"""
from contextlib import contextmanager
import math

from tools.analysis.lut_shapers import Shaper


BASELINE=Shaper()
CANDIDATE=Shaper('log_tanh',kappa=.01,strength=2.,center=.25)


@contextmanager
def shaper_graph(lut,shaper):
    """Build isolated Address helpers, restoring this Session's exports afterward.

    Supported shapers are exactly ``BASELINE`` and ``CANDIDATE``. Helpers persist
    for the caller's render, but subsequent graph construction uses production
    functions again. The unchanged Blend helper is deliberately shared.
    """
    _GRAPH=lut.Graph
    _HELPER=lut.compositor_helper
    _SCHEMA=lut.SCHEMA

    class CandidateGraph(_GRAPH):
        """Analytic log/tanh addresses; no added texture or table lookup."""
        _a=CANDIDATE.strength
        _c=CANDIDATE.center
        _normal=math.sinh(_a)/math.cosh(_a*(1-_c))
        _log_range=math.log1p(lut.cm.MAXIMUM/CANDIDATE.kappa)

        def encode(self,x):
            z=self.div(self.op('LOGARITHM',self.add(1,self.div(x,CANDIDATE.kappa)),math.e),self._log_range)
            # Equivalent to the normalized centered tanh difference, with no
            # subtraction of two almost-equal tanh values near black.
            numerator=self.op('SINH',self.mul(self._a,z))
            denominator=self.mul(self._normal,self.op('COSH',self.mul(self._a,self.sub(z,self._c))))
            return self.div(numerator,denominator)

        def decode(self,y):
            a=self._normal*math.exp(self._a*self._c)
            b=self._normal*math.exp(-self._a*self._c)
            first=self.op('LOGARITHM',self.add(1,self.mul(a,y)),math.e)
            second=self.op('LOGARITHM',self.sub(1,self.mul(b,y)),math.e)
            z=self.div(self.sub(first,second),2*self._a)
            return self.mul(CANDIDATE.kappa,self.sub(self.exp(self.mul(self._log_range,z)),1))

        def cell(self,x):
            bounded=self.min(lut.cm.MAXIMUM,self.max(lut.cm.MINIMUM,x))
            cells=self.size-1
            position=self.mul(cells,self.encode(bounded))
            i=self.min(cells-1,self.max(0,self.op('FLOOR',position)))
            lo=self.decode(self.div(i,cells))
            hi=self.decode(self.div(self.add(i,1),cells))
            # The baked axis pins its upper endpoint. Preserve that endpoint in
            # float32 address arithmetic instead of relying on transcendental
            # round-trip rounding. The lower endpoint decodes exactly to zero.
            interior=self.lt(i,cells-1)
            hi=self.add(self.mul(interior,hi),self.mul(self.sub(1,interior),lut.cm.MAXIMUM))
            fraction=self.min(1,self.max(0,self.div(self.sub(x,lo),self.sub(hi,lo))))
            return i,self.max(fraction,self.sub(1,self.lt(x,lut.cm.MAXIMUM)))

    if shaper.to_dict() not in (BASELINE.to_dict(),CANDIDATE.to_dict()):
        raise ValueError('Compositor study supports only baseline and selected log_tanh shaper')
    graph=_GRAPH if shaper.to_dict()==BASELINE.to_dict() else CandidateGraph
    previous=lut.compositor_helper

    def helper(kind,size=lut.cm.SIZE,tree_type='CompositorNodeTree'):
        if kind!='Address':return _HELPER(kind,size,tree_type)
        old_graph,old_schema=lut.Graph,lut.SCHEMA
        try:
            lut.Graph=graph
            lut.SCHEMA=f'{_SCHEMA}:shaper-study:{shaper.key}'
            tree=_HELPER(kind,size,tree_type)
        finally:
            lut.Graph,lut.SCHEMA=old_graph,old_schema
        tree.name=f'PG Shaper Study · {shaper.key} · {size}'
        tree['_pg_study_shaper']=shaper.key
        return tree

    try:
        lut.compositor_helper=helper
        yield
    finally:
        lut.compositor_helper=previous
