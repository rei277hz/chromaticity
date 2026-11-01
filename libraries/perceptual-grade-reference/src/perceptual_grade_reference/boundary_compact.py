"""Original compact boundary coefficients, evaluated without runtime expansion.

The DCTL backend uses these splines directly. Unlike the Blender uint16 face
atlas, this keeps the fitted face field; the resource itself is unchanged.
"""
import numpy as np
from ..perceptual_grade_core.model.boundary_table import stencil
from ..perceptual_grade_core.model.creases import Selector


class CompactTable:
    def __init__(self,data,dtype=np.float32):
        self.data=data;self.dtype=np.dtype(dtype).type
        self.selector=Selector(data,dtype)
        # Format 16 retires the spindle profile/guard but retains the same
        # compact physical cube splines used by the portable backend.
        self.knots=np.asarray(data.get('knots',[]),dtype=dtype)
        self.profile=np.asarray(data.get('profile',[]),dtype=dtype)

    def capacity(self,t,hue):
        t,hue=np.broadcast_arrays(np.asarray(t,dtype=self.dtype),np.asarray(hue,dtype=self.dtype))
        face,s,_,_,left,right=self.selector.select(t,hue)
        low=self.data['vertex_t'][self.data['face_limits'][face,0]]
        high=self.data['vertex_t'][self.data['face_limits'][face,1]]
        x=(t-low)/(high-low);correction=np.empty(t.shape,dtype=self.dtype)
        for f in range(6):
            selected=face==f
            if not np.any(selected):continue
            i,a=stencil(self.data['sector_t'][f],x[selected])
            j,b=stencil(self.data['sector_s'],s[selected])
            c=np.asarray(self.data['sectors'][f],dtype=self.dtype)[i[...,None],j[...,None,:]]
            correction[selected]=np.sum(np.sum(c*b[...,None,:],axis=-1)*a,axis=-1)
        return 1/((1-s)*left+s*right+s*(1-s)*correction)

    def coefficient(self,t):
        t=np.asarray(t,dtype=self.dtype);k=self.knots;p=self.profile
        i=np.clip(np.searchsorted(k,t,side='right')-1,0,len(k)-2)
        slopes=np.diff(p)/np.diff(k)
        result=p[i]+slopes[i]*(t-k[i])
        radii=self.dtype(.25)*np.minimum(np.diff(k)[:-1],np.diff(k)[1:])
        for j,r in enumerate(radii,1):
            v=np.maximum(0,r-abs(t-k[j]))
            result+=(slopes[j]-slopes[j-1])*v*v*v/(6*r*r)
        return result

    def intersection(self,height,white,gamma,return_response=False):
        h=np.asarray(height,dtype=self.dtype);x=h/white
        i,w=stencil(self.data['guard_knots'],x)
        factor=np.sum(np.asarray(self.data['guard_coefficients'],dtype=self.dtype)[i]*w,axis=-1)
        t=np.minimum(x*x*factor,1);ja=np.minimum(h,white*t**gamma)
        result=((h-ja)*(h+ja)/66,ja*ja)
        return (*result,t) if return_response else result
