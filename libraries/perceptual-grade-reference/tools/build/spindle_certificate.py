"""Directed certificates for exact J_A rays and the one-dimensional spindle.

Certificates concern real equations with stored constants. Float64 execution
is checked independently; interval powers do not assume a libm error bound.
"""
import numpy as np
from color_tools.perceptual_grade_reference.spindle import white_response, MAXIMUM
from color_tools.perceptual_grade_reference.responses import INVERSE, GAMMA
from .appearance_certificate import I, trig, down, up


def integer(x,n):
    result=I(np.ones_like(x.lo))
    while n:
        if n&1:result=result*x
        n//=2
        if n:x=x*x
    return result


def power(x,n=21,d=50):
    """Enclose a rational power by checking integer-power inequalities."""
    if np.any(x.lo<0):raise ValueError('Negative rational-power input')
    lo=np.power(x.lo,n/d);hi=np.where(x.hi>0,np.maximum(np.power(x.hi,n/d),np.finfo(float).smallest_subnormal),0.)
    def raised(v,k):
        mantissa,exponent=np.frexp(v)
        return integer(I(mantissa),k),exponent*k
    def aligned(v,k,exponent):
        value,e=raised(v,k)
        with np.errstate(over='ignore',under='ignore'):
            return I(down(np.ldexp(value.lo,e-exponent)),up(np.ldexp(value.hi,e-exponent)))
    target_lo,elo=raised(x.lo,n);target_hi,ehi=raised(x.hi,n)
    for _ in range(128):
        left=aligned(lo,d,elo);right=aligned(hi,d,ehi)
        good_lo=(left.hi<=target_lo.lo)|(lo==0)
        good_hi=(right.lo>=target_hi.hi)|(x.hi==0)
        if np.all(good_lo&good_hi):return I(lo,hi)
        lo=np.where(good_lo,lo,np.maximum(0.,down(lo)))
        hi=np.where(good_hi,hi,up(hi))
    raise ValueError('Rational power enclosure did not converge')


def matrix_image(v,m):
    rows=[]
    for row in m:
        rows.append(v[:,1]+(v[:,0]-v[:,1])*row[0]+(v[:,2]-v[:,1])*row[2])
    return I(np.stack([x.lo for x in rows],-1),np.stack([x.hi for x in rows],-1))


def inverse_matrix(m):
    a=[[I(m[i,j]) if j!=1 else I(1)-m[i,0]-m[i,2] for j in range(3)] for i in range(3)]
    cof=[[a[(i+1)%3][(j+1)%3]*a[(i+2)%3][(j+2)%3]-
          a[(i+1)%3][(j+2)%3]*a[(i+2)%3][(j+1)%3] for j in range(3)] for i in range(3)]
    det=sum((a[0][j]*cof[0][j] for j in range(3)),I(0))
    result=[[cof[j][i]/det for j in range(3)] for i in range(3)]
    if any(v.lo<=0 for row in result for v in row):raise ValueError('Native cone matrix is not positive')
    return result


def neutral_weights():
    a,b=INVERSE[:,1],INVERSE[:,2]
    cross=[I(a[(i+1)%3])*b[(i+2)%3]-I(a[(i+2)%3])*b[(i+1)%3] for i in range(3)]
    denominator=sum(cross,I(0))
    return [v/denominator for v in cross]


def face_velocity(box,component,swap,upper,matrix,fl):
    """RGB face = scale*(0,1,u), or white minus that; factor out scale."""
    z,u=I(box[:,0],box[:,1]),I(box[:,2],box[:,3])
    others=[j for j in range(3) if j!=component]
    if swap:others.reverse()
    inv=inverse_matrix(matrix)
    ell=[row[others[0]]+row[others[1]]*u for row in inv]
    weights=neutral_weights();K=(I(400)-white_response(fl))/white_response(fl)
    values=[]
    if not upper:
        p=[power(v) for v in ell]
        for i in range(3):
            difference=sum((weights[j]*(p[i]-p[j])/(K+z*p[j]) for j in range(3) if j!=i),I(np.zeros(len(box))))
            values.append(ell[i]/(I(21)/50)*(K+z*p[i])/p[i]*difference)
    else:
        x=[(1-z*v).positive() for v in ell];p=[power(v) for v in x]
        for i in range(3):
            total=I(np.zeros(len(box)))
            for j in range(3):
                if j==i:continue
                # Mean-value bounds cover the removable equal-cone/white limits.
                low=np.minimum(x[i].lo,x[j].lo);high=np.maximum(x[i].hi,x[j].hi)
                sec=(I(21)/50)/power(I(low,high),29,50)
                denom=x[i]-x[j]
                separate=(denom.lo>0)|(denom.hi<0)
                if separate.any():
                    exact=(p[i][separate]-p[j][separate])/denom[separate]
                    sec.lo[separate]=np.maximum(sec.lo[separate],exact.lo)
                    sec.hi[separate]=np.minimum(sec.hi[separate],exact.hi)
                total=total-weights[j]*(ell[i]-ell[j])*sec/(K+p[j])
            values.append(x[i]/(I(21)/50)*(K+p[i])/p[i]*total)
    v=I(np.stack([a.lo for a in values],-1),np.stack([a.hi for a in values],-1))
    rgb=matrix_image(v,matrix)
    return rgb[:,component] if upper else -rgb[:,component]


def certify_faces(fl,matrices):
    count=0;minimum=np.inf
    for mi,matrix in enumerate(matrices):
        for component in range(3):
            for upper in (False,True):
                for swap in (False,True):
                    pending=[(np.array([[0.,1.,0.,1.]]),np.zeros(1,dtype=int))]
                    while pending:
                        box,depth=pending.pop()
                        if len(box)>4096:
                            pending.extend((box[i:i+4096],depth[i:i+4096]) for i in range(0,len(box),4096));continue
                        v=face_velocity(box,component,swap,upper,matrix,fl)
                        good=v.lo>0;count+=len(box)
                        minimum=min(minimum,float(np.min(v.lo[good],initial=np.inf)))
                        if np.any(~good&(depth>=28)):
                            i=np.flatnonzero(~good&(depth>=28))[0]
                            raise ValueError(f'Unresolved outward face certificate: {mi,component,upper,swap,box[i].tolist(),v.lo[i],v.hi[i]}')
                        box=box[~good];depth=depth[~good]
                        if not len(box):continue
                        axis=np.argmax(box[:,[1,3]]-box[:,[0,2]],axis=-1)*2;row=np.arange(len(box))
                        middle=(box[row,axis]+box[row,axis+1])/2
                        left,right=box.copy(),box.copy();left[row,axis+1]=middle;right[row,axis]=middle
                        pending.append((np.stack((left,right),1).reshape(-1,4),np.repeat(depth+1,2)))
                    print(f'Face certificate: adapter {mi}, face {component}, upper={upper}, triangle={int(swap)}; {count} boxes',flush=True)
    return {'certified':True,'interval_boxes':count,'minimum_normalized_outward_velocity':minimum,
            'scope':'all six faces, including normalized black/white limits, for both stored adapters'}


def profile_parts(knots):
    radius=np.r_[0.,.25*np.minimum(np.diff(knots)[:-1],np.diff(knots)[1:]),0.]
    parts=[]
    for i in range(len(knots)-1):
        left,right=knots[i]+radius[i],knots[i+1]-radius[i+1]
        parts.append((left,right,i,0))
        if i+1<len(knots)-1:
            k=i+1
            parts.extend([(knots[k]-radius[k],knots[k],k,-1),(knots[k],knots[k]+radius[k],k,1)])
    return sorted(parts)


def profile_interval(knots,values,part,t,derivative=False):
    _,_,k,side=part
    if side==0:
        m=(I(values[k+1])-values[k])/(I(knots[k+1])-knots[k])
        return I(np.broadcast_to(m.lo,t.lo.shape),np.broadcast_to(m.hi,t.hi.shape)) if derivative else values[k]+m*(t-knots[k])
    r=I(.25*min(knots[k]-knots[k-1],knots[k+1]-knots[k]))
    ml=(I(values[k])-values[k-1])/(I(knots[k])-knots[k-1])
    mr=(I(values[k+1])-values[k])/(I(knots[k+1])-knots[k])
    z=t-knots[k]
    if side<0:
        v=(z+r).positive()
        hinge=v*v/(2*r*r) if derivative else v*v*v/(6*r*r)
    else:
        v=(r-z).positive()
        hinge=1-v*v/(2*r*r) if derivative else z+v*v*v/(6*r*r)
    return ml+(mr-ml)*hinge if derivative else values[k]+ml*z+(mr-ml)*hinge


_ANGLES={}

def directions(lo,hi,aw):
    pairs,index=np.unique(np.column_stack((lo,hi)),axis=0,return_inverse=True)
    keys=[(float(a),float(b),aw) for a,b in pairs]
    missing=[i for i,k in enumerate(keys) if k not in _ANGLES]
    if missing:
        h=I(pairs[missing,0],pairs[missing,1]);e=I(np.ones(len(missing)));de=I(np.zeros(len(missing)))
        for k,(a,b) in enumerate(zip((-.0582,-.0258,-.1347,.0289),(-.1475,-.0308,.0385,.0096)),1):
            c,s=trig(k*h,True),trig(k*h)
            e=e+a*c+b*s;de=de+k*(-a*s+b*c)
        c,s=trig(h,True),trig(h)
        v=[]
        for i in range(3):
            numerator=INVERSE[i,1]*c+INVERSE[i,2]*s
            derivative=-INVERSE[i,1]*s+INVERSE[i,2]*c
            v.extend([aw*numerator/(1204*e),aw*(derivative*e-numerator*de)/(1204*e*e)])
        low=np.stack([x.lo for x in v],-1).reshape(-1,3,2);high=np.stack([x.hi for x in v],-1).reshape(-1,3,2)
        for k,l,h in zip((keys[i] for i in missing),low,high):_ANGLES[k]=(l,h)
    a,b=zip(*(_ANGLES[k] for k in keys))
    return I(np.array(a)[index],np.array(b)[index])


def upper_values(q,gap,a,rw):
    qrange=I(np.minimum(q.lo,1.),np.maximum(q.hi,1.))
    v=MAXIMUM*a*cone_derivative(qrange,rw)
    separate=gap.lo[:,0]>0
    if separate.any():
        quotient=MAXIMUM*(1-power((q[separate]*(400-rw)/(400-rw*q[separate])).positive(),50,21))/gap[separate]
        v.lo[separate]=np.maximum(v.lo[separate],quotient.lo)
        v.hi[separate]=np.minimum(v.hi[separate],quotient.hi)
    return v


def cone_derivative(q,rw):
    return (I(50)/21)*(I(400)-rw)*I(400)*power((q*(400-rw)/(400-rw*q)).positive(),29,21)/(400-rw*q)/(400-rw*q)


def cone_second(q,rw):
    den=400-rw*q;base=(q*(400-rw)/den).positive();first=400*(400-rw)/(den*den)
    return (I(50)/21)*(I(29)/21)*power(base,8,21)*first*first+(I(50)/21)*power(base,29,21)*2*rw*first/den


def classify(t,u,d,fl,matrix,center=None,slope=None,radius=None,tcenter=None,ucenter=None,uslope=None,tradius=None):
    """Inside/outside real cube, including normalized limits at both tips."""
    n=len(t.lo);inside=np.ones(n,bool);outside=np.zeros(n,bool);rw=white_response(fl)
    for top in (False,True):
        ids=np.arange(n)
        tt,uu,dd=t[ids,None],u[ids,None],d[ids]
        rel=1+(1-tt)*uu*dd
        if not top:
            domain=(rel.lo.min(-1)>0)&((tt*rel).hi.max(-1)<400/rw)
            outside[ids]|=rel.hi.min(-1)<0
            selected=ids[domain]
            if not len(selected):inside.fill(False);continue
            tt,uu,rel=tt[domain],uu[domain],rel[domain]
            con=power((rel/(1-rw*tt/(400-rw*tt)*(rel-1))).positive(),50,21)
            rgb=matrix_image(con,matrix)
            if center is not None:
                z=rw*tt/(400-rw*tt);den=1-z*(rel-1)
                derivative=(I(50)/21)*power((rel/den).positive(),29,21)*(1+z)/(den*den)*(1-tt)*uu*slope[selected]
                mt=tt if tcenter is None else tcenter[selected,None]
                mu=uu if ucenter is None else ucenter[selected,None]
                midrel=1+(1-mt)*mu*center[selected];mz=rw*mt/(400-rw*mt)
                middle=matrix_image(power((midrel/(1-mz*(midrel-1))).positive(),50,21),matrix)
                if tcenter is not None:
                    dr=(-uu+(1-tt)*uslope[selected,None])*d[selected]
                    dz=400*rw/(400-rw*tt)/(400-rw*tt)
                    dt=(I(50)/21)*power((rel/den).positive(),29,21)*(dr*(1+z)+rel*dz*(rel-1))/(den*den)
        else:
            gap=1-tt;a=1-tt*uu*dd;q=tt*rel
            domain=(rel.lo.min(-1)>0)&(q.hi.max(-1)<400/rw)
            outside[ids]|=(q.hi.min(-1)<0)|(q.lo.max(-1)>1)
            selected=ids[domain]
            if not len(selected):inside.fill(False);continue
            tt,uu,gap,a,q=tt[domain],uu[domain],gap[domain],a[domain],q[domain].positive()
            # The positive cone function is convex: its secant to white is
            # bounded by its derivatives. The quotient tightens away from white.
            rgb=matrix_image(upper_values(q,gap,a,rw),matrix)
            if center is not None:
                derivative=-MAXIMUM*tt*uu*slope[selected]*cone_derivative(q,rw)
                mt=tt if tcenter is None else tcenter[selected,None]
                mu=uu if ucenter is None else ucenter[selected,None]
                mg=1-mt;ma=1-mt*mu*center[selected];mq=(mt*(1+mg*mu*center[selected])).positive()
                middle=matrix_image(upper_values(mq,mg,ma,rw),matrix)
                if tcenter is not None:
                    da=-(uu+tt*uslope[selected,None])*d[selected]
                    qr=I(np.minimum(q.lo,1.),np.maximum(q.hi,1.))
                    # Integral divided differences retain the removable white
                    # limit; away from white the exact quotient tightens it.
                    dt=MAXIMUM*(da*cone_derivative(qr,rw)-a*(gap*da-a)*cone_second(qr,rw)/2)
                    separate=gap.lo[:,0]>0
                    if separate.any():
                        exact=(upper_values(q[separate],gap[separate],a[separate],rw)-MAXIMUM*cone_derivative(q[separate],rw)*(a-gap*da)[separate])/gap[separate]
                        dt.lo[separate]=np.maximum(dt.lo[separate],exact.lo);dt.hi[separate]=np.minimum(dt.hi[separate],exact.hi)
        if center is not None:
            derivative=matrix_image(derivative,matrix)
            error=I(-1,1)*I(np.maximum(abs(derivative.lo),abs(derivative.hi)))*radius[selected,None]
            if tcenter is not None:
                dt=matrix_image(dt,matrix)
                error=error+I(-1,1)*I(np.maximum(abs(dt.lo),abs(dt.hi)))*tradius[selected,None]
            tighter=middle+error
            rgb=I(np.maximum(rgb.lo,tighter.lo),np.minimum(rgb.hi,tighter.hi))
        # Lower-normalized RGB certifies the black faces; normalized distance
        # from white certifies the white faces. Recombining either with its
        # vanishing scale would discard their t correlation unnecessarily.
        if np.any(rgb.lo>rgb.hi):raise ValueError('Inconsistent interval intersection')
        good=np.zeros(n,bool);good[selected]=rgb.lo.min(-1)>=0;inside&=good
        outside[selected]|=rgb.hi.min(-1)<0
    return inside,outside


def certify_profile(ctx,matrices,witnesses):
    """All-hue containment, a per-interval retention witness, and guard height."""
    parts=profile_parts(ctx.knots);count=0;smallest=np.inf
    for number,part in enumerate(parts):
        left,right,_,_=part
        cut=[left,right]
        for low,high in zip(cut[:-1],cut[1:]):
            edges=np.linspace(0,2*np.pi,33)
            boxes=np.column_stack((np.full(32,low),np.full(32,high),edges[:-1],edges[1:]))
            for retention in (False,True):
                if retention:
                    witness_angles=[float(witnesses(t)) for t in (low,(low+high)/2,high)]
                    angle=witness_angles[1]
                    boxes=np.array([[low,high,angle,angle]])
                pending=[(boxes,np.zeros(len(boxes),dtype=int))]
                while pending:
                    box,depth=pending.pop()
                    if len(box)>4096:
                        pending.extend((box[i:i+4096],depth[i:i+4096]) for i in range(0,len(box),4096));continue
                    t=I(box[:,0],box[:,1]);g=profile_interval(ctx.knots,ctx.profile,part,t)
                    u=g*ctx.white/white_response(ctx.fl)/(0.995 if retention else 1.)
                    directions_all=directions(box[:,2],box[:,3],ctx.aw)
                    d=directions_all[:,:,0]
                    midpoint=(box[:,2]+box[:,3])/2
                    center=directions(midpoint,midpoint,ctx.aw)[:,:,0]
                    radius=I(up(np.maximum(midpoint-box[:,2],box[:,3]-midpoint)))
                    tm=(box[:,0]+box[:,1])/2;tc=I(tm)
                    uc=profile_interval(ctx.knots,ctx.profile,part,tc)*ctx.white/white_response(ctx.fl)/(0.995 if retention else 1.)
                    du=profile_interval(ctx.knots,ctx.profile,part,t,True)*ctx.white/white_response(ctx.fl)/(0.995 if retention else 1.)
                    tr=I(up(np.maximum(tm-box[:,0],box[:,1]-tm)))
                    good=np.ones(len(box),bool)
                    for m in matrices:
                        inside,outside=classify(t,u,d,ctx.fl,m,center,directions_all[:,:,1],radius,tc,uc,du,tr)
                        if retention:
                            for angle in (witness_angles[0],witness_angles[2]):
                                a=np.full(len(box),angle)
                                _,alternative=classify(t,u,directions(a,a,ctx.aw)[:,:,0],ctx.fl,m)
                                outside|=alternative
                        good&=outside if retention else inside
                    count+=len(box)
                    if np.any(~good&(depth>=30)):
                        failed=box[~good&(depth>=30)]
                        return False,{'part':number,'retention':retention,'unresolved':failed[0].tolist(),'interval_boxes':count}
                    box=box[~good];depth=depth[~good]
                    if not len(box):continue
                    spans=(box[:,[1,3]]-box[:,[0,2]])/np.array([max(high-low,1e-30),2*np.pi/32])
                    axis=np.argmax(spans,axis=-1)*2;row=np.arange(len(box));mid=(box[row,axis]+box[row,axis+1])/2
                    a,b=box.copy(),box.copy();a[row,axis+1]=mid;b[row,axis]=mid
                    pending.append((np.stack((a,b),1).reshape(-1,4),np.repeat(depth+1,2)))
            # Height derivative is normalized by white, positive even at black.
            t=I(np.array([low]),np.array([high]));g=profile_interval(ctx.knots,ctx.profile,part,t)
            dg=profile_interval(ctx.knots,ctx.profile,part,t,True)
            derivative=2*GAMMA*ctx.white*t.power(2*GAMMA-1)+66*((1-2*t)*g+t*(1-t)*dg)
            if derivative.lo[0]<=0:return False,{'part':number,'height_derivative':derivative.lo.tolist(),'interval_boxes':count}
            smallest=min(smallest,float(derivative.lo[0]))
        print(f'Profile certificate: {number+1}/{len(parts)} pieces, {count} boxes',flush=True)
    return True,{'certified':True,'interval_boxes':count,'minimum_height_squared_derivative_over_white':smallest,
                 'minimum_round_radius_retention':.995,'scope':'continuous t and hue, both native adapters; normalized endpoint limits included'}
