"""Native H-K export repair and actual-decoder AP1 boundary projection."""
from dataclasses import dataclass
from functools import cached_property
import math
from ..kernel.boundary import P, INVERSE, prepare_boundary


@dataclass(frozen=True)
class GuardedSockets:
    graph: object
    H: object
    a: object
    b: object
    energy: object
    reference_energy: object
    saturated: object = 0.
    chroma_value: object = None

    @cached_property
    def chroma(self): return self.chroma_value if self.chroma_value is not None else self.graph.hypot(self.a,self.b)
    @cached_property
    def J_A(self): return self.graph.mul(self.graph.sign(self.energy),self.graph.sqrt(self.graph.abs(self.energy)))
    @cached_property
    def q(self): return self.graph.vector((self.H,self.a,self.b))


@dataclass(frozen=True)
class GuardResult:
    color: object
    valid: object
    pole_margin: object
    saturated: object
    native_color: object
    radius: object


def hk_guard(g,state):
    """One export repair, retaining the frozen post-Tone signed energy."""
    if state.graph is not g: raise ValueError('Guard sockets belong to another Graph')
    h,a,b,e,e0=state.H,state.a,state.b,state.energy,state.reference_energy
    flag=getattr(state,'saturated',0.)
    c=state.chroma if hasattr(state,"chroma") else g.hypot(a,b)
    known=hasattr(state,"source_chroma")
    safe=known and g._color_bounded("H",limit=2.**60)
    x,x_flag=(g.mul(h,h),0.) if safe else g.saturate(g.mul(h,h))
    base=g.mul(math.sqrt(66),g.sqrt(c))
    u=state.offset if hasattr(state,"offset") else g.div(e,g.add(g.hypot(g.sqrt(g.abs(e)),base),base))
    absolute=g.abs(u);twice_base=g.mul(2,base)
    ratio=g.div(g.sub(twice_base,absolute),g.add(twice_base,absolute))
    d=g.select(g.lt(e,0),g.mul(e,ratio),e)
    ref=g.maximum(0,e0);low=g.minimum(ref,x);high=g.maximum(ref,x)
    delta=g.div(low,g.add(1,g.div(low,high)))
    active=g.mul(g.sub(1,g.lt(h,0)),g.lt(d,delta))
    v=g.div(delta,g.add(delta,g.maximum(0,g.sub(delta,d))))
    w=g.sub(1,v)
    denominator=g.sqrt(g.sqrt(g.madd(v,v,g.mul(w,g.madd(4,v,g.mul(10,w))))))
    repaired=g.div(g.mul(delta,g.sqrt(v)),denominator)
    z=g.maximum(0,g.sub(repaired,d));allocation=g.mul(.44,x)
    twice=g.mul(2,allocation)
    bounded=known and g._color_bounded('H',limit=2.**28) and g._color_bounded('energy','C',limit=2.**58)
    if bounded:
        norm=g.sqrt(g.madd(twice,twice,g.mul(z,z)))
    else:
        scale=g.maximum(twice,z)
        xn,zn=g.div(twice,scale),g.div(z,scale)
        norm=g.mul(scale,g.sqrt(g.madd(xn,xn,g.mul(zn,zn))))
    lift=g.mul(allocation,g.div(z,norm))
    new_x,new_flag=(g.add(x,lift),0.) if safe else g.saturate(g.add(x,lift))
    flag=g.maximum(flag,g.mul(active,g.maximum(x_flag,new_flag)))
    new_c=g.minimum(c,g.maximum(0,g.div(g.sub(new_x,repaired),66)))
    gain=g.select(active,g.div(new_c,c),1.)
    return GuardedSockets(g,g.select(active,g.sqrt(new_x),h),g.mul(a,gain),g.mul(b,gain),
                          g.select(active,repaired,e),e0,flag,g.select(active,new_c,c))


def _boundary(g):
    data=g.cache.get('prepared_boundary')
    if data is None:
        data=getattr(g.prepared,'boundary',None)
        if data is None: data=prepare_boundary(g.prepared.fl,g.prepared.aw,g.prepared.gamma)
        g.cache['prepared_boundary']=data
    return data


def _native(g,vector,matrix):
    red,green,blue=g.split(vector)
    a=g.vscale(tuple(matrix[:,0]),g.sub(red,green))
    b=g.vscale(tuple(matrix[:,2]),g.sub(blue,green))
    return g.vadd(g.vadd(a,b),g.vector((green,)*3))


def _linear_map(g,vector,matrix):
    """Compact constant-row map, separate from neutral-preserving decodes."""
    return g.vector(tuple(g.dot(vector,row) for row in matrix))


def _legal(g,vector):
    r,gc,b=g.split(vector)
    low=g.minimum(r,g.minimum(gc,b));high=g.maximum(r,g.maximum(gc,b))
    return g.mul(g.sub(1,g.lt(low,0)),g.sub(1,g.lt(1024,high)))


def _inverse_vector(g,responses):
    """Finite operand bounds protect unused trials; never clip output RGB."""
    absolute=g.vop('MINIMUM',g.vop('ABSOLUTE',responses),(399.999969482421875,)*3)
    p=g.vdiv(g.vscale(absolute,27.13),g.vsub((400.,)*3,absolute))
    value=g.vscale(g.vop('POWER',p,(P,)*3),1/g.prepared.fl)
    return g.vmul(g.vop('SIGN',responses),value)


def _near_zero_mask(g,vector):
    # The component Mix clamps its factor, so -1 already selects the direct
    # branch and does not need a separate vector maximum with zero.
    return g.vop('SIGN',g.vsub((.1,)*3,g.vop('ABSOLUTE',vector)))


def _white_decode(g,t,radius,direction,data,delta):
    """Decode cone deficits so the white vertex remains exactly representable."""
    one=(1.,)*3;k=data.response_white/(400-data.response_white)
    deficit=g.vsub(g.vector((delta,)*3),g.vscale(direction,g.div(radius,data.response_white)))
    z=g.vdiv(g.vscale(deficit,1+k),g.vadd(one,g.vscale(deficit,k)))
    base=g.vop('MAXIMUM',g.vsub(one,z),(0.,)*3)
    direct=g.vsub(one,g.vop('POWER',base,(P,)*3))
    poly=g.vop('MULTIPLY_ADD',(P*(P-1)*(P-2)*(P-3)*(P-4)/120,)*3,z,(-P*(P-1)*(P-2)*(P-3)/24,)*3)
    poly=g.vop('MULTIPLY_ADD',poly,z,(P*(P-1)*(P-2)/6,)*3)
    poly=g.vop('MULTIPLY_ADD',poly,z,(-P*(P-1)/2,)*3)
    poly=g.vop('MULTIPLY_ADD',poly,z,(P,)*3)
    stable=g.vmul(z,poly)
    values=g.vselect_components(_near_zero_mask(g,z),stable,direct)
    return g.vsub((1024.,)*3,g.vscale(_native(g,values,data.matrix),1024.))


def output_guard(g,state):
    """Preserve legal raw decodes; otherwise project at fixed J_A and hue."""
    if state.graph is not g: raise ValueError('Guard sockets belong to another Graph')
    data=_boundary(g)
    e=state.energy
    t=g.minimum(1,g.power(g.div(g.maximum(0,e),data.white*data.white),1/(2*g.prepared.gamma)))
    # A compensated white-energy constant retains the small distance to the
    # white tip when a rounded power would give t == 1.
    square=data.white*data.white
    hi=float(data.pixels.dtype.type(square));lo=square-hi
    deficit=g.maximum(0,g.div(g.add(g.sub(hi,e),lo),square))
    return _output_projection(g,state,data,t,deficit,e,square)


def compositor_stage2_output_guard(g,state):
    """Project Color-free Stage 2 without transporting squared energy.

    Interactive GPU compositing can materialize any shared arithmetic result
    in a half-float image. J_A and its distance to white fit that transport;
    white energy and even the subtraction preceding its normalization do not.
    """
    if state.graph is not g: raise ValueError('Guard sockets belong to another Graph')
    data=_boundary(g)
    j=state.J_A
    bounded=g.clamp(j,0.,data.white)
    t=g.power(g.div(bounded,data.white),1/g.prepared.gamma)
    # Compensate the float32 white constant before forming the bounded
    # energy deficit: 1-(J_A/J_white)^2 = delta_j*(2-delta_j).
    hi=float(data.pixels.dtype.type(data.white));lo=data.white-hi
    delta_j=g.clamp(g.add(g.div(g.sub(hi,bounded),data.white),lo/data.white))
    deficit=g.mul(delta_j,g.sub(2.,delta_j))
    return _output_projection(g,state,data,t,deficit,j,data.white)


def _output_projection(g,state,data,t,deficit,endpoint,white_point):
    """Shared actual-decoder projection from bounded solver coordinates."""
    rw=data.response_white
    small=g.minimum(.1,deficit)
    exponent=1/(2*g.prepared.gamma)
    poly=g.madd(exponent*(exponent-1)*(exponent-2)*(exponent-3)*(exponent-4)/120,small,-exponent*(exponent-1)*(exponent-2)*(exponent-3)/24)
    poly=g.madd(poly,small,exponent*(exponent-1)*(exponent-2)/6)
    poly=g.madd(poly,small,-exponent*(exponent-1)/2)
    poly=g.madd(poly,small,exponent)
    physical_delta=g.select(g.lt(deficit,.1),g.mul(small,poly),g.sub(1,t))
    # A GPU power can round t by multiple ulps near white. Carry the stable
    # energy-derived deficit into the solver too, rather than amplifying that
    # error through 1-t. The fifth-order remainder at deficit=.1 is <2.2e-8.
    t=g.select(g.lt(deficit,.1),g.sub(1,physical_delta),t)
    # Solver inputs include limiting geometry at both tips. Endpoint policy
    # still uses the original signed coordinate rather than this solver clamp.
    ts=g.clamp(t,1e-9,.9999999);delta=g.sub(1,ts)
    chroma=state.chroma if hasattr(state,"chroma") else g.hypot(state.a,state.b)
    ca,sa=g.div(state.a,chroma),g.div(state.b,chroma)
    polynomial=g.madd(g.madd(g.madd(g.madd(.2312,ca,-.5388),ca,-.2828),ca,.3459),ca,1.0547)
    quadrature=g.madd(g.madd(g.madd(.0768,ca,.154),ca,-.1),ca,-.186)
    ecc=g.madd(sa,quadrature,polynomial)
    factor=g.div(g.prepared.aw,g.mul(1204,ecc))
    direction_vector=g.vscale(g.vadd(g.vscale(tuple(INVERSE[:,1]),ca),g.vscale(tuple(INVERSE[:,2]),sa)),factor)
    direction=g.split(direction_vector)
    neutral=g.mul(rw,t)
    direct_responses=tuple(g.madd(chroma,d,neutral) for d in direction)
    max_response=g.maximum(g.abs(direct_responses[0]),g.maximum(g.abs(direct_responses[1]),g.abs(direct_responses[2])))
    direct_native=_native(g,_inverse_vector(g,g.vector(direct_responses)),data.matrix)
    legal=g.mul(g.lt(max_response,400),_legal(g,direct_native))
    hue=g.op('ARCTAN2',sa,ca)
    hue=g.sub(g.div(hue,2*math.pi),g.op('FLOOR',g.div(hue,2*math.pi)))
    height,width,_=data.pixels.shape
    split=data.seed_split
    row=g.add(g.mul(data.seed_low_cells/split,g.minimum(ts,split)),g.mul(data.seed_high_cells/(1-split),g.maximum(0,g.sub(ts,split))))
    coordinates=({'pixel_coordinates':(g.mul(width-1,hue),row)}
                 if g.tree.bl_idname=='ShaderNodeTree' else
                 {'u':g.madd((width-1)/width,hue,.5/width),'v':g.madd(1/height,row,.5/height)})
    sampled,_=g.sample_texture(data.pixels,**coordinates,key='output_boundary_seed',interpolation='Linear',label='AP1 boundary root seed')
    samples=g.split(sampled)
    u=g.minimum(samples[0],g.minimum(samples[1],samples[2]))
    high=g.lt(.5,ts);k=rw/(400-rw)
    aa=g.div(g.mul(rw,ts),g.sub(400,g.mul(rw,ts)))
    slope=g.select(high,g.mul(-1,ts),delta)
    offset=g.select(high,1,g.add(1,aa))
    den_slope=g.select(high,g.mul(k,delta),g.mul(-1,aa))
    zscale=g.mul(1+k,delta)
    derivative_scale=g.mul(P,g.mul(slope,g.mul(offset,g.select(high,1+k,1))))
    lower_upper=g.power(g.div(g.sub(400,g.mul(rw,ts)),g.mul(400-rw,ts)),P)
    upper=g.select(high,g.div(1,delta),lower_upper)
    derivative_vector=g.vscale(direction_vector,derivative_scale)
    offset_vector=g.vector((offset,)*3)
    inverse_delta=g.div(1,delta)
    curvature_scale=g.mul((P-1)/P,g.select(high,g.mul(-1,delta),1.))
    denominator_derivative=g.vscale(direction_vector,g.mul(2,g.mul(den_slope,slope)))
    one=(1.,)*3
    # Halley uses both actual-decoder derivatives. Limit the correction
    # denominator so a distant, inactive cube face cannot attract the root.
    for _ in range(data.correction_steps):
        rel=g.vadd(g.vscale(direction_vector,g.mul(slope,u)),one)
        den=g.vadd(g.vscale(rel,den_slope),offset_vector)
        y=g.vdiv(rel,den);z=g.vscale(y,zscale)
        base=g.vop('MAXIMUM',g.vselect(high,g.vsub(one,z),y),(0.,)*3)
        power=g.vop('POWER',base,(P,)*3)
        high_value=g.vscale(g.vsub(one,power),inverse_delta)
        polynomial=g.vop('MULTIPLY_ADD',(P*(P-1)*(P-2)*(P-3)*(P-4)/120,)*3,z,(-P*(P-1)*(P-2)*(P-3)/24,)*3)
        polynomial=g.vop('MULTIPLY_ADD',polynomial,z,(P*(P-1)*(P-2)/6,)*3)
        polynomial=g.vop('MULTIPLY_ADD',polynomial,z,(-P*(P-1)/2,)*3)
        polynomial=g.vop('MULTIPLY_ADD',polynomial,z,(P,)*3)
        stable=g.vmul(g.vscale(y,1+k),polynomial)
        high_value=g.vselect_components(_near_zero_mask(g,z),stable,high_value)
        value=g.vselect(high,high_value,power)
        derivative=g.vdiv(g.vmul(derivative_vector,g.vdiv(power,base)),g.vmul(den,den))
        curvature=g.vmul(derivative,g.vsub(g.vscale(g.vdiv(derivative,power),curvature_scale),g.vdiv(denominator_derivative,den)))
        values=_linear_map(g,value,data.matrix)
        derivatives=_linear_map(g,derivative,data.matrix)
        curvatures=_linear_map(g,curvature,data.matrix)
        positive=g.vop('MAXIMUM',g.vop('SIGN',derivatives),(0.,)*3)
        target=g.vscale(positive,upper)
        step=g.vdiv(g.vsub(target,values),derivatives)
        denominator=g.vadd(one,g.vscale(g.vmul(step,g.vdiv(curvatures,derivatives)),.5))
        denominator=g.vop('MINIMUM',g.vop('MAXIMUM',denominator,(.5,)*3),(1.5,)*3)
        candidates=g.split(g.vadd(g.vector((u,)*3),g.vdiv(step,denominator)))
        u=g.maximum(0,g.minimum(candidates[0],g.minimum(candidates[1],candidates[2])))
    radius=g.minimum(chroma,g.mul(rw,g.mul(g.mul(t,physical_delta),u)))
    # One inward float32 allowance prevents a converged boundary root from
    # rounding across a face. This acts on radius, preserving energy and hue.
    radius=g.mul(radius,.999988)
    final_responses=tuple(g.madd(radius,d,neutral) for d in direction)
    native=_native(g,_inverse_vector(g,g.vector(final_responses)),data.matrix)
    native=g.vselect(g.lt(.5,t),_white_decode(g,t,radius,direction_vector,data,physical_delta),native)
    final_legal=_legal(g,native)
    # A final decoded check is authoritative. A rare ill-conditioned corner
    # uses the interior neutral rather than returning an illegal RGB value.
    neutral_fraction=g.div(g.mul(t,400-rw),g.sub(400,neutral))
    neutral_cone=g.minimum(1024,g.mul(1024,g.power(neutral_fraction,P)))
    native=g.vselect(final_legal,native,g.vector((neutral_cone,)*3))
    native=g.vselect(legal,direct_native,native)
    positive=g.lt(0,endpoint);white=g.sub(1,g.lt(endpoint,white_point))
    native=g.vselect(white,g.vector((1024.,)*3),native)
    native=g.vscale(native,positive)
    # Report the radius of the returned value, including neutral fallback and
    # endpoint policies, rather than the radius of an abandoned solver trial.
    returned_radius=g.select(legal,chroma,g.select(final_legal,radius,0.))
    returned_radius=g.mul(positive,g.select(white,0.,returned_radius))
    # Keep the tested native value; do not perform another appearance decode.
    adapter=g.prepared.from_cones@data.inverse
    color=_linear_map(g,native,adapter)
    trial_max=g.maximum(g.abs(final_responses[0]),g.maximum(g.abs(final_responses[1]),g.abs(final_responses[2])))
    returned_max=g.select(legal,max_response,g.select(final_legal,trial_max,neutral))
    returned_max=g.mul(positive,g.select(white,rw,returned_max))
    chosen_margin=g.sub(400,returned_max)
    return GuardResult(color,1.,chosen_margin,getattr(state,'saturated',0.),native,returned_radius)
