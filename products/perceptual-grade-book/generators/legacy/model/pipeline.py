"""Reusable Stage 2 coordinates for CPU inspector previews, never image output."""
import numpy as np
from . import color as cm; from . import curves as lm


class BoundModel(cm.Model):
    def curve(self,H,stem):
        return self.context.weights(self,'hue' if stem.startswith('concentration_') else stem.split('_')[0])@self.heights(stem)

    def drivers(self,q,JA=None):
        return self.context.drivers(self)


class Coordinates:
    def __init__(self,model,n,neutral=False):
        self.n=n;self.neutral=neutral
        self.original,self.valid,ach,*_=model.tone.attributes(n)
        JA=100*(np.maximum(ach,0)/model.tone.aw)**cm.tm.GAMMA
        self.q,self.JA=model.stage2_with_ja(self.original,JA)
        self._weights={};self._drivers=None

    def weights(self,model,family):
        fit=getattr(model.params,family+'_fit')
        key=(family,fit)
        if key not in self._weights:
            # Shape keys omit heights. Keep only the newest shape per family.
            self._weights={k:v for k,v in self._weights.items() if k[0]!=family}
            H=self.q[...,0]
            if isinstance(getattr(model,'lut',None),lm.BasisTable):
                w=model.lut.weights(H/model.tone.high_j,family)
            else:w=model.weights(H,fit,family=='adaptance')
            self._weights[key]=w
        return self._weights[key]

    def drivers(self,model):
        if self._drivers is None:self._drivers=cm.Model.drivers(model,self.q,self.JA)
        return self._drivers

    def transform(self,model):
        bound=BoundModel.__new__(BoundModel);bound.__dict__.update(model.__dict__);bound.context=self;bound.source=model
        if self.neutral:
            # Neutral offsets use the same envelope: C=0 gives alpha*H/100.
            target=self.q.copy();H=target[...,0]
            weight=cm.adaptance_weight(H,0,model.params.adaptance_strength)
            target[...,1]=weight*bound.curve(H,'adaptance_a');target[...,2]=weight*bound.curve(H,'adaptance_b')
            target=np.where((H==0)[...,None],self.q,target)
        else:target=bound.stage3(self.q,self.JA)
        changed=np.any(self.original!=target,axis=-1)
        out=self.n.copy();valid=self.valid.copy()
        # Exact unchanged values need no inverse or validation. For a positive
        # image this also skips the whole zero-offset inverse calculation.
        if np.any(changed):
            decoded,ok=model.decode(target[changed],self.q[changed]);out[changed]=decoded;valid[changed]&=ok
        return out,valid


class Prepared:
    def __init__(self,base,model):
        self.base=base;self.rgb=base['stage1_rgb'];self.fallback=base['stage2_rgb']
        n=model.tone.cones(self.rgb);lift=np.maximum(0,-np.min(n,axis=-1))
        lifted=n+lift[...,None]
        lifted=np.where(np.abs(lifted)<=4e-7*(np.abs(n)+lift[...,None]),0,lifted)
        self.main=Coordinates(model,lifted)
        self.offset=Coordinates(model,np.broadcast_to(lift[...,None],n.shape),True)

    def apply(self,model):
        if not model.active:return self.fallback
        if hasattr(model,'lut') and not isinstance(model.lut,lm.BasisTable):return model.apply(self.rgb)
        out,valid=self.main.transform(model);offset,ov=self.offset.transform(model)
        rgb=(out-offset)@model.tone.from_cone.T
        return np.where((valid&ov&np.isfinite(rgb).all(axis=-1))[...,None],rgb,self.fallback)
