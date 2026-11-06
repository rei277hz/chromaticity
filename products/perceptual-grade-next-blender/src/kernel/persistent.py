"""Fixed-topology native grades with guarded, synchronous parameter updates.

The caller excludes native readers while applying an update.  Preparation is
portable; this module owns no scheduler, global cache, or workflow authority.
"""
from dataclasses import dataclass, fields, replace
import math
import time
from numbers import Real
from types import SimpleNamespace
import numpy as np

from .graph import (Graph, BuiltGrade, AppearanceSockets, DecodeSockets,
                    FLOAT_MAX, TREE_TYPES, _interface, _socket, count_nodes)
from .color_graph import ColorSockets, INVERSE, TAU, SQRT_HK
from .guard_graph import hk_guard, output_guard
from .layouts import LAYOUT_SCHEMA
from .color_prepare import _validate_color_schema


FIELD_NAMES = ('coefficient_table', 'web_table', 'web_toe_table',
               'adaptance_table')


class _Binding:
    """Host value or routing decision; never a per-pixel Python evaluator."""
    def __init__(self, resolve):
        self.resolve = resolve

    def as_pointer(self):
        # Graph caches identify the semantic binding, never its initial value.
        return -id(self)


def _active(values):
    return any(value != 0 for row in values for value in row)


def _resolve(value, prepared):
    while isinstance(value, _Binding):
        value = value.resolve(prepared)
    return value


def _source_key(value):
    if _socket(value):
        return ('socket', value.as_pointer())
    if isinstance(value, Real):
        return ('scalar', float(value))
    return ('vector', tuple(map(float, value)))


class _Matrix:
    def __init__(self, graph, getter):
        self.graph, self.getter = graph, getter

    def __matmul__(self, right):
        return _Matrix(self.graph, lambda p: self.getter(p) @ right)

    def __iter__(self):
        return iter(tuple(_Binding(lambda p, i=i: tuple(self.getter(p)[i])) for i in range(3)))


class _PersistentGraph(Graph):
    def __init__(self, tree, prepared, candidate_identity=None):
        super().__init__(tree, prepared)
        self.candidate_identity = candidate_identity
        self.actual = prepared
        self.bindings = []
        self.binding_links = {}
        self.uniforms = {}
        self.image_slots = {}
        self._bound_cache = None
        self._legacy_safe = False
        tone = SimpleNamespace(active=True)
        for name in ('black', 'span', 'slope', 'high'):
            setattr(tone, name, self.parameter('tone.'+name, lambda p, n=name: getattr(p.tone, n)))
        self.prepared = SimpleNamespace(
            fl=prepared.fl, aw=prepared.aw, gamma=prepared.gamma,
            tone=tone, table=self._table('tone'),
            linear_to_cones=_Matrix(self, lambda p:p.linear_to_cones),
            from_cones=_Matrix(self, lambda p: p.from_cones), boundary=prepared.boundary)
        color = SimpleNamespace(active=True)
        for name in FIELD_NAMES:
            setattr(color, name, self._table(name))
        self.prepared.color = color

    def parameter(self, name, getter):
        if name not in self.uniforms:
            self.uniforms[name] = _Binding(getter)
        return self.uniforms[name]

    def _table(self, name):
        data = self.actual.table if name == 'tone' else getattr(self.actual.color, name)
        if data is None:
            raise ValueError('Persistent grades require full_fields=True preparation')
        table = SimpleNamespace(**vars(data))
        table.domain = self.parameter(name+'.domain', lambda p, n=name:
            p.table.domain if n == 'tone' else getattr(p.color, n).domain)
        self.image_slots[name] = (data, None)
        return table

    def connect(self, value, target):
        if isinstance(value, _Binding):
            record = [value, target, None]
            self.bindings.append(record)
            self._write_binding(record, self.actual)
        else:
            super().connect(value, target)

    def _write_binding(self, record, prepared):
        value, target, previous = record
        source = _resolve(value, prepared)
        key = _source_key(source)
        if key == previous:
            return False
        target_pointer=target.as_pointer()
        link=self.binding_links.pop(target_pointer,None)
        if link is not None:self.tree.links.remove(link)
        if _socket(source):
            self.binding_links[target_pointer]=self.tree.links.new(source, target)
        else:
            target.default_value = source
        record[2] = key
        return True

    def route(self, predicate, yes, no):
        if yes is no:
            return yes
        return _Binding(lambda p: yes if predicate(p) else no)

    def route_state(self, predicate, yes, no):
        # Explicitly materialize lazy carried values before construction ends.
        if isinstance(yes, AppearanceSockets):
            names = ('J_A', 'raw_a', 'raw_b', 'achromatic', 'factor', 'chroma')
            return AppearanceSockets(self, *(self.route(predicate, getattr(yes,n), getattr(no,n)) for n in names))
        return replace(yes, **{name:self.route(predicate, getattr(yes,name), getattr(no,name))
            for name in ('H','a','b','energy','saturated')},
            chroma_value=self.route(predicate, yes.chroma, no.chroma),
            offset_value=self.route(predicate, yes.offset, no.offset))

    def _bounds(self, prepared):
        key=(id(prepared.tone),id(prepared.color))
        if self._bound_cache is None or self._bound_cache[0]!=key:
            rho = sum(math.hypot(a,b) for a,b in ((.0582,.1475),(.0258,.0308),(.1347,.0385),(.0289,.0096)))
            ja = 100*(1220/prepared.aw)**prepared.gamma
            c = 1204*(1+rho)/prepared.aw*400*math.hypot(24/11,4/9)
            height = float(prepared.tone.remap(math.sqrt(ja*ja+66*c)))
            pixels=prepared.color.adaptance_table.pixels
            self._bound_cache = key, prepared.color.finite_bounds(height), height, {
                'log_bound':float(abs(pixels[...,:3]).max()),
                'max_log':max(0.,float(pixels[...,:3].max())),
                'max_k':max(0.,float(pixels[...,3].max())),
            }
        return self._bound_cache[1]

    def fact(self,prepared,name):
        self._bounds(prepared)
        return self._bound_cache[3][name]

    def bounded(self, *names, limit=2.**120):
        return lambda p: all(math.isfinite(self._bounds(p)[n]) and self._bounds(p)[n] < limit for n in names)

    def _squares_safe(self, p):
        self._bounds(p)
        return self._bound_cache[2] < math.sqrt(66.)*2.**29

    @property
    def _color_source_squares_safe(self): return self._legacy_safe

    @property
    def _color_safe(self): return self._legacy_safe

    def _color_bounded(self, *names, limit=2.**120):
        return self._legacy_safe(names,limit) if callable(self._legacy_safe) else self._legacy_safe

    def _legacy(self, safe, function, *args):
        old = self._legacy_safe
        self._legacy_safe = safe
        try:
            return function(*args)
        finally:
            self._legacy_safe = old

    def _packed_image(self, pixels, *, key=None, label='Perceptual Grade coefficients'):
        for name, (table, image) in self.image_slots.items():
            if pixels is table.pixels:
                if image is None:
                    image = self._create_field_image(
                        pixels, key=('persistent', name), label=label,
                    )
                    image['perceptual_grade_nodes_field_role'] = name
                    image['perceptual_grade_nodes_field_schema'] = LAYOUT_SCHEMA
                    self.image_slots[name] = table, image
                # Legacy sample_field retrieves this alias after sampling.
                self.cache[('packed_image', key)] = image
                return image
        image = self._create_field_image(pixels, key=key, label=label)
        if key == 'output_boundary_seed':
            image['perceptual_grade_nodes_field_role'] = 'boundary_seed'
            image['perceptual_grade_nodes_field_schema'] = LAYOUT_SCHEMA
        return image

    def _create_field_image(self, pixels, *, key=None, label='Perceptual Grade coefficients'):
        if self.candidate_identity is not None:
            import bpy

            cache_key = ('packed_image', id(pixels) if key is None else key)
            if cache_key in self.cache:
                return self.cache[cache_key]
            height, width, channels = pixels.shape
            if channels != 4:
                raise ValueError('Packed coefficient data must have four channels')
            owner, revision = self.candidate_identity
            image = bpy.data.images.new(
                '.PG Next Candidate Image %s %s %s' % (owner, revision, label),
                width=width, height=height, alpha=True, float_buffer=True,
            )
            self.images.append(image)
            image['perceptual_grade_next_candidate_owner'] = owner
            image['perceptual_grade_next_candidate_revision'] = revision
            image.colorspace_settings.name = 'Non-Color'
            image.alpha_mode = 'CHANNEL_PACKED'
            image.use_half_precision = False
            image.file_format = 'OPEN_EXR'
            image.pixels.foreach_set(pixels.ravel())
            image.update()
            image.pack()
            self.cache[cache_key] = image
            return image
        return super()._packed_image(pixels, key=key, label=label)

    def matrix(self, vector, matrix):
        if not isinstance(matrix, _Matrix):
            return super().matrix(vector, matrix)
        red, green, blue = self.split(vector)
        column = lambda i: _Binding(lambda p: tuple(matrix.getter(p)[:,i]))
        total = _Binding(lambda p: tuple(math.fsum(map(float,row)) for row in matrix.getter(p)))
        return self.vadd(self.vadd(self.vscale(column(0),self.sub(red,green)),
                                  self.vscale(column(2),self.sub(blue,green))),self.vscale(total,green))

    def tone(self, state):
        computed = super().tone(state)
        return self.route_state(lambda p:p.tone.active, computed, state)

    def _color_norm_result(self,a,b):
        direct=self.sqrt(self.madd(a,a,self.mul(b,b)))
        stable=self.hypot(a,b)
        value=self.route(self.bounded('C','pre_adaptance_C',limit=2.**58),direct,stable)
        result,flag=self._color_positive_saturate(value)
        safe=self.bounded('C','pre_adaptance_C')
        return self.route(safe,value,result),self.route(safe,0.,flag)

    def _color_mul(self,a,b,bound='C'):
        value=self.mul(a,b); result,flag=self.saturate(value); safe=self.bounded(bound)
        return self.route(safe,value,result),self.route(safe,0.,flag)

    def _color_positive_mul(self,a,b,bound='C'):
        value=self.mul(a,b); result,flag=self._color_positive_saturate(value); safe=self.bounded(bound)
        return self.route(safe,value,result),self.route(safe,0.,flag)

    def _color_vsat(self,value,bound='response'):
        result,flag=self.vsaturate(value); safe=self.bounded(bound)
        return self.route(safe,value,result),self.route(safe,0.,flag)

    def _color_sat(self,value):
        result,flag=self.saturate(value)
        safe=self.bounded('H','C','energy','response','parameter',limit=2.**58)
        return self.route(safe,value,result),self.route(safe,0.,flag)

    def _color_magnitude(self,energy,chroma):
        simple=self.sqrt(self.madd(66.,chroma,self.abs(energy)))
        scale=self.maximum(self.abs(energy),chroma)
        stable=self.mul(self.sqrt(scale),self.sqrt(self.madd(66.,self.div(chroma,scale),self.div(self.abs(energy),scale))))
        return self.route(self.bounded('C','pre_adaptance_C',limit=2.**96),simple,stable)

    def _color_exp(self,value,upper,base=math.e):
        exponential=self.op('EXPONENT',value) if base==math.e else self.power(base,value)
        result,flag=self._color_positive_saturate(exponential)
        safe=lambda p:float(_resolve(upper,p))*math.log(base)<88.
        return self.route(safe,exponential,result),self.route(safe,0.,flag)

    def _color_drivers(self,state):
        simple=self._legacy(True,super()._color_drivers,state)
        stable=self._legacy(False,super()._color_drivers,state)
        return tuple(self.route(self._squares_safe,a,b) for a,b in zip(simple,stable))

    def _color_terms(self,state):
        table=self.prepared.color.coefficient_table
        x=self._color_height(table,state.tonal_h);drivers=self._color_drivers(state)
        light=self.sample_field(table,x,0); chroma=self.sample_field(table,x,1)
        h=self.route(lambda p:p.color.lightness_active,self.add(state.H,self._color_dot4(light,drivers)),state.H)
        gain0=self.parameter('global_gain',lambda p:p.color.settings.global_gain)
        exponent=self.route(lambda p:_active(p.color.settings.chroma),self.add(gain0,self._color_dot4(chroma,drivers)),gain0)
        upper=self.parameter('chroma_upper',lambda p:p.color.settings.global_gain+max(max(abs(row[0]),abs(row[1]))+math.hypot(*row[2:]) for row in p.color.settings.chroma))
        gain,fs=self._color_exp(exponent,upper,2.)
        a,fa=self._color_mul(state.a,gain);b,fb=self._color_mul(state.b,gain)
        active=lambda p:p.color.chroma_active
        a,b=self.route(active,a,state.a),self.route(active,b,state.b)
        flag=self.route(active,self._color_flag(state.saturated,fs,fa,fb),state.saturated)
        c,fc=self._color_norm_result(a,b);flag=self._color_flag(flag,fc)
        energy,fe,offset=self._color_carry(state,h,c)
        nonblack=self.lt(0.,state.tonal_h)
        changed=replace(state,H=self.safe_select(nonblack,h,state.H),a=self.safe_select(nonblack,a,state.a),
            b=self.safe_select(nonblack,b,state.b),energy=self.safe_select(nonblack,energy,state.energy),
            chroma_value=c,offset_value=offset,saturated=self._color_flag(state.saturated,self.mul(nonblack,self._color_flag(flag,fe))))
        return self.route_state(lambda p:p.color.lightness_active or p.color.chroma_active,changed,state)

    def _color_web(self,state):
        table=self.prepared.color.web_table;toe_table=self.prepared.color.web_toe_table
        x=self._color_height(table,state.tonal_h)
        toes=self.sample_field(toe_table,self._color_height(toe_table,state.tonal_h),0)
        angle=self.op('ARCTAN2',state.b,state.a);c=state.chroma
        angles=self._color_field(table,x,'angles');local,index=self._color_sector(angle,angles)
        row=self.madd(2.,index,table.angular_row)
        left,width,target,slope=self.sample_field(table,x,row)
        c3,c4,c5,_=self.sample_field(table,x,self.add(row,1.))
        u=self.div(self.sub(local,left),width)
        value=self.madd(u,self.add(slope,self.mul(self.mul(u,u),self.madd(u,self.madd(u,c5,c4),c3))),target)
        fade=self._color_smoother(self.div(c,toes[0]))
        hue=lambda p:_active(p.color.settings.web.hue_degrees)
        out_angle=self.route(hue,self.madd(fade,self.sub(value,local),angle),angle)
        targets=self._color_field(table,x,'target_angles');local,index=self._color_sector(out_angle,targets)
        row=self.madd(2.,index,table.radial_row)
        left,width,gc0,gc1=self.sample_field(table,x,row)
        delta=self.op('FLOORED_MODULO',self.sub(out_angle,left),TAU)
        delta=self.select(self.lt(self.mul(.5,self.add(width,TAU)),delta),0.,delta)
        blend=self._color_smoother(self.div(delta,width))
        chroma_log=self.madd(blend,self.sub(gc1,gc0),gc0)
        gs0,gs1,_,_=self.sample_field(table,x,self.add(row,1.))
        scale_log=self.madd(blend,self.sub(gs1,gs0),gs0)
        chroma_active=lambda p:_active(p.color.settings.web.log_chroma)
        scale_active=lambda p:_active(p.color.settings.web.log_scale)
        cu=self.parameter('web_chroma_upper',lambda p:max(0.,math.log(2.)*max(v for row in p.color.settings.web.log_chroma for v in row)-math.log(.9)))
        su=self.parameter('web_scale_upper',lambda p:max(0.,math.log(2.)*max(v for row in p.color.settings.web.log_scale for v in row)-math.log(.9)))
        gc,fg=self._color_exp(chroma_log,cu);calculated,fc=self._color_radial(c,gc,toes[1])
        c1=self.route(chroma_active,calculated,c)
        flag=self.route(chroma_active,self._color_flag(state.saturated,fg,fc),state.saturated)
        gs,fg=self._color_exp(scale_log,su);c2,fc=self._color_radial(c1,gs,toes[2])
        scale=self.route(scale_active,self.select(self.lt(0.,c1),self.div(c2,c1),1.),1.)
        scale_flag=self.route(scale_active,self._color_flag(fg,fc),0.)
        radial=self.select(self.lt(0.,c),self.div(c1,c),1.)
        radial_a,radial_b=self.mul(state.a,radial),self.mul(state.b,radial)
        same=self.op('COMPARE',out_angle,angle,0.)
        a=self.route(hue,self.select(same,radial_a,self.mul(c1,self.op('COSINE',out_angle))),radial_a)
        b=self.route(hue,self.select(same,radial_b,self.mul(c1,self.op('SINE',out_angle))),radial_b)
        energy,fe,offset=self._color_carry(state,state.H,c1)
        changed=replace(state,a=a,b=b,energy=self.route(chroma_active,energy,state.energy),
            saturated=self.route(chroma_active,self._color_flag(flag,fe),flag),chroma_value=c1,
            offset_value=self.route(chroma_active,offset,state.offset))
        return self.route_state(lambda p:p.color.web_active,changed,state),scale,scale_flag

    def _color_response_delta(self,responses,logs,gains,log_bound):
        stable=self._legacy(True,super()._color_response_delta,responses,logs,gains,math.inf)
        robust=self._legacy(False,super()._color_response_delta,responses,logs,gains,math.inf)
        choice=self.bounded('transformed_response')
        return tuple(self.route(choice,a,b) for a,b in zip(stable,robust))

    def _color_adaptance(self,state):
        table=self.prepared.color.adaptance_table
        s=self.mul(math.sqrt(self.prepared.aw/(3.05*400.)),self.power(self.mul(.01,state.tonal_h),1/(2*self.prepared.gamma)))
        chosen=self.sample_field(table,self.mul(table.cells,self.div(s,self.add(1.,s))),0)
        half=self.parameter('adaptance_half',lambda p:p.color.settings.adaptance_half_saturation)
        half2=self.parameter('adaptance_half2',lambda p:p.color.settings.adaptance_half_saturation**2)
        a2=self.mul(half2,self.abs(state.source_energy));c2=self.mul(state.source_chroma,state.source_chroma)
        scale=self.maximum(a2,c2);an,cn=self.div(a2,scale),self.div(c2,scale)
        simple=(self.mul(an,an),self.mul(cn,cn))
        a=self.mul(half,self.sqrt(self.abs(state.source_energy)));scale=self.maximum(a,state.source_chroma)
        an,cn=self.div(a,scale),self.div(state.source_chroma,scale);a2,c2=self.mul(an,an),self.mul(cn,cn)
        a4,c4=(self.route(self._squares_safe,x,y) for x,y in zip(simple,(self.mul(a2,a2),self.mul(c2,c2))))
        reach=self.select(self.lt(0.,state.source_chroma),self.div(a4,self.add(a4,c4)),1.)
        logs=self.vscale(self.vector(chosen[:3]),reach)
        scalar=self.vector(tuple(self.op('EXPONENT',v) for v in self.split(logs)))
        vector=self.vop('POWER',(math.e,)*3,logs)
        gain=self.route(lambda p:self.fact(p,'log_bound')>1,scalar,vector)
        saturated,gf=self.vsaturate(gain)
        overflow=lambda p:self.fact(p,'max_log')>=88.
        gain=self.route(overflow,saturated,gain);gf=self.route(overflow,gf,0.)
        upper=self.parameter('adaptance_k_upper',lambda p:self.fact(p,'max_k'))
        factor,ff=self._color_exp(self.mul(reach,chosen[3]),upper)
        es=self._eccentricity(state.a,state.b,robust=False)[0]
        er=self._eccentricity(state.a,state.b,robust=True)[0]
        eccentricity=self.route(self.bounded('pre_adaptance_C',limit=2.**58),es,er)
        opponent_scale=self.div(self.prepared.aw/1204.,eccentricity)
        achromatic=self.mul(self.prepared.aw/100.**(1/self.prepared.gamma),self.mul(self.sign(state.energy),self.power(self.abs(state.energy),1/(2*self.prepared.gamma))))
        opponent=self.vadd(self.vscale(tuple(row[1] for row in INVERSE),state.a),self.vscale(tuple(row[2] for row in INVERSE),state.b))
        neutral_response=self.mul(1/3.05,achromatic)
        response,rf=self._color_vsat(self.vop('MULTIPLY_ADD',opponent,self.vector((opponent_scale,)*3),self.vector((neutral_response,)*3)),'input_response')
        delta,tf=self._color_response_delta(response,logs,gain,math.inf)
        absolute=self.split(self.vop('ABSOLUTE',delta));m=self.maximum(absolute[0],self.maximum(*absolute[1:]))
        bounded=self.bounded('response');magnitude=self.route(bounded,1.,m)
        normalized=self.route(bounded,delta,self.vdiv(delta,self.vector((m,)*3)))
        r,g,b=self.split(normalized)
        da,fac=self._color_mul(magnitude,self.madd(2.,r,self.madd(.05,b,g)),'response')
        un=self.madd(1/11,self.sub(b,g),self.sub(r,g));wn=self.div(self.add(self.sub(r,b),self.sub(g,b)),9.)
        du,fu=self._color_mul(magnitude,un,'response');dw,fw=self._color_mul(magnitude,wn,'response')
        ac=self.add(achromatic,da);u=self.madd(state.a,opponent_scale,du);w=self.madd(state.b,opponent_scale,dw)
        flags=[state.saturated,ff,tf,rf,gf,fac,fu,fw]
        def sat_optional(value):
            safe,flag=self.saturate(value);flags.append(self.route(bounded,0.,flag));return self.route(bounded,value,safe)
        ac,u,w=map(sat_optional,(ac,u,w))
        ac,fa=self._color_mul(ac,factor,'response');u,fu=self._color_mul(u,factor,'response');w,fw=self._color_mul(w,factor,'response')
        flags.extend((fa,fu,fw))
        es=self._eccentricity(u,w,robust=False)[0];er=self._eccentricity(u,w,robust=True)[0]
        eccentricity=self.route(self.bounded('response',limit=2.**58),es,er)
        chroma_factor=self.mul(1204/self.prepared.aw,eccentricity)
        a,fa=self._color_mul(u,chroma_factor);b,fb=self._color_mul(w,chroma_factor)
        ja,fj=self._color_positive_mul(100.,self.power(self.div(self.abs(ac),self.prepared.aw),self.prepared.gamma),'post_adaptance_H')
        energy,fe=self._color_positive_mul(ja,ja,'post_adaptance_energy');energy=self.mul(self.sign(ac),energy)
        neutral=self.mul(self.sub(1.,self.lt(0.,state.source_chroma)),self.sub(1.,self.lt(0.,state.chroma)))
        energy=self.safe_select(neutral,state.energy,energy)
        chroma,fc=self._color_norm_result(a,b);height=self._color_h(energy,chroma)
        active=self.mul(self.lt(0.,reach),self.lt(0.,state.tonal_h))
        changed=self._color_flag(*flags,fa,fb,fj,fe,fc)
        result=replace(state,H=self.safe_select(active,height,state.H),a=self.safe_select(active,a,state.a),b=self.safe_select(active,b,state.b),
            energy=self.safe_select(active,energy,state.energy),chroma_value=self.select(active,chroma,state.chroma),offset_value=None,
            saturated=self._color_flag(state.saturated,self.mul(active,changed)))
        return self.route_state(lambda p:p.color.adaptance_active,result,state)

    def color(self,appearance):
        original=self._color_input(appearance)
        state=self._color_terms(original)
        state,scale,flag=self._color_web(state)
        state=self._color_adaptance(state)
        result=self._color_scale(state,scale,flag)
        state=self.route_state(lambda p:_active(p.color.settings.web.log_scale),result,state)
        return self.route_state(lambda p:p.color.active,state,original)

    def hk_guard(self,state):
        # Both precision variants remain permanently present; native rewiring
        # chooses the same grade-derived policy as the specialized builder.
        safe=self._legacy(True,hk_guard,self,state)
        mixed=self._legacy(lambda names,limit:limit==2.**60,hk_guard,self,state)
        robust=self._legacy(False,hk_guard,self,state)
        small=lambda p:self.bounded('H',limit=2.**28)(p) and self.bounded('energy','C',limit=2.**58)(p)
        square=self.bounded('H',limit=2.**60)
        def choose(a,b,c):return self.route(small,a,self.route(square,b,c))
        return replace(safe,**{n:choose(getattr(safe,n),getattr(mixed,n),getattr(robust,n))
            for n in ('H','a','b','energy','saturated')},chroma_value=choose(safe.chroma,mixed.chroma,robust.chroma))


class PersistentGrade:
    """Caller-owned fixed tree. Apply only while native readers are excluded."""
    def __init__(self,graph,built):
        self._graph=graph
        self.tree,self.images,self.helper_groups=built.tree,built.images,built.helper_groups
        self.prepared,self.stats=built.prepared,built.stats
        self.revision=0
        self.valid=True
        self._disposed=False
        self._applying=False
        self._node_ids=tuple(node.as_pointer() for node in self.tree.nodes)
        self._image_ids=tuple(image.as_pointer() for image in self.images)

    def _validate(self,prepared):
        if self.tree.get('perceptual_grade_nodes_schema') != LAYOUT_SCHEMA:
            raise ValueError('Persistent grading layout schema is obsolete; rebuild the tree')
        _validate_color_schema(prepared.color)
        if (prepared.fl,prepared.aw,prepared.gamma)!=(self.prepared.fl,self.prepared.aw,self.prepared.gamma):
            raise ValueError('Persistent grading context cannot change')
        if prepared.boundary is not self.prepared.boundary:
            raise ValueError('Persistent boundary resource cannot change')
        if len(self.tree.nodes)!=self.stats.top_level_nodes:
            raise ValueError('Persistent native node inventory changed')
        if tuple(node.as_pointer() for node in self.tree.nodes)!=self._node_ids:
            raise ValueError('Persistent native node identities changed')
        if tuple(image.as_pointer() for image in self.images)!=self._image_ids:
            raise ValueError('Persistent native image identities changed')
        for name,(original,image) in self._graph.image_slots.items():
            if (tuple(image.size)!=(original.pixels.shape[1],original.pixels.shape[0])
                    or image.colorspace_settings.name!='Non-Color' or image.alpha_mode!='CHANNEL_PACKED'
                    or image.use_half_precision or not image.packed_file):
                raise ValueError('Persistent native field resource changed: '+name)
            table=prepared.table if name=='tone' else getattr(prepared.color,name)
            previous=self.prepared.table if name=='tone' else getattr(self.prepared.color,name)
            if table is previous:
                continue
            if table is None or table.pixels.shape!=original.pixels.shape or table.cells!=original.cells:
                raise ValueError('Persistent field layout changed: '+name)
            if not np.isfinite(table.pixels).all():
                raise ValueError('Persistent field contains nonfinite pixels: '+name)
            if table.pixels.dtype!=np.float32:
                raise ValueError('Persistent field is not float32: '+name)
            for attr in ('segments','segment_cells','semantic_rows','mapping','schema'):
                if getattr(table,attr,None)!=getattr(original,attr,None):
                    raise ValueError('Persistent field layout changed: '+name+'.'+attr)
            if getattr(table,'fields',None)!=getattr(original,'fields',None):
                raise ValueError('Persistent field schema changed: '+name)

    def _write(self,prepared):
        changed=[]
        upload=packing=readback=0.
        for name,(_,image) in self._graph.image_slots.items():
            previous=self.prepared.table if name=='tone' else getattr(self.prepared.color,name)
            table=prepared.table if name=='tone' else getattr(prepared.color,name)
            if table is previous:
                continue
            start=time.perf_counter()
            image.pixels.foreach_set(table.pixels.ravel());image.update()
            upload+=time.perf_counter()-start
            start=time.perf_counter();image.pack();packing+=time.perf_counter()-start
            start=time.perf_counter()
            native=np.empty(table.pixels.size,dtype=np.float32)
            image.pixels.foreach_get(native)
            if not np.array_equal(native.reshape(table.pixels.shape),table.pixels):
                raise RuntimeError('Persistent native image readback failed: '+name)
            if not image.packed_file:
                raise RuntimeError('Persistent native image pack readback failed: '+name)
            readback+=time.perf_counter()-start
            changed.append(name)
        start=time.perf_counter()
        bindings=[]
        for record in self._graph.bindings:
            if self._graph._write_binding(record,prepared):bindings.append(record)
        return changed,bindings,dict(image_upload=upload,image_pack=packing,image_readback=readback,
                                     bindings=time.perf_counter()-start)

    @staticmethod
    def _readback_bindings(records,prepared):
        if not records:return
        targets={record[1].as_pointer() for record in records}
        incoming={}
        for link in records[0][1].id_data.links:
            pointer=link.to_socket.as_pointer()
            if pointer in targets:incoming.setdefault(pointer,[]).append(link.from_socket.as_pointer())
        for value,target,_ in records:
            source=_resolve(value,prepared)
            sources=incoming.get(target.as_pointer(),[])
            if _socket(source):
                if sources!=[source.as_pointer()]:
                    raise RuntimeError('Persistent native link readback failed')
            elif sources or not np.array_equal(np.asarray(target.default_value,dtype=np.float32),np.asarray(source,dtype=np.float32)):
                raise RuntimeError('Persistent native parameter readback failed')

    def _assert_current_bindings(self):
        self._readback_bindings(self._graph.bindings,self.prepared)

    def apply(self,prepared,*,expected_revision):
        started=time.perf_counter()
        if self._disposed or not self.valid:
            raise ValueError('Persistent grade is disposed or requires recovery')
        if self._applying:
            raise ValueError('Persistent grade update is already applying')
        if expected_revision!=self.revision:
            raise ValueError('Persistent grade revision mismatch')
        self._assert_current_bindings()
        self._validate(prepared)
        previous=self.prepared
        self._applying=True
        try:
            changed,bindings,phases=self._write(prepared)
            start=time.perf_counter()
            self._readback_bindings(bindings,prepared)
            self.tree['perceptual_grade_nodes_revision']=self.revision+1
            if self.tree['perceptual_grade_nodes_revision']!=self.revision+1:
                raise RuntimeError('Persistent revision readback failed')
            phases['readback_commit']=time.perf_counter()-start
        except BaseException:
            try:
                # Force restoration of every image: a native write may fail
                # after partially changing an image but before returning.
                for name,(_,image) in self._graph.image_slots.items():
                    table=previous.table if name=='tone' else getattr(previous.color,name)
                    image.pixels.foreach_set(table.pixels.ravel());image.update();image.pack()
                    native=np.empty(table.pixels.size,dtype=np.float32)
                    image.pixels.foreach_get(native)
                    if not np.array_equal(native.reshape(table.pixels.shape),table.pixels):
                        raise RuntimeError('Persistent image rollback readback failed: '+name)
                for record in self._graph.bindings:
                    record[2]=None
                    self._graph._write_binding(record,previous)
                self._readback_bindings(self._graph.bindings,previous)
                self.tree['perceptual_grade_nodes_revision']=self.revision
            except BaseException:
                self.valid=False
            raise
        finally:
            self._applying=False
        self.prepared=prepared;self._graph.actual=prepared;self.revision+=1
        phases['total']=time.perf_counter()-started
        return dict(revision=self.revision,changed_fields=tuple(changed),changed_bindings=len(bindings),phase_seconds=phases)

    def dispose(self,*,unlink=False):
        BuiltGrade(self.tree,self.images,self.helper_groups,self.prepared,self.stats).dispose(unlink=unlink)
        self._disposed=True


def build_persistent(prepared,tree_type='ShaderNodeTree',*,name='Perceptual Grade Persistent',
                     candidate_owner='',candidate_revision=0):
    """Build every optional path and helper image once; never create on apply."""
    if tree_type not in TREE_TYPES:
        raise ValueError('Expected a ShaderNodeTree or CompositorNodeTree')
    _validate_color_schema(prepared.color)
    import bpy
    tree=bpy.data.node_groups.new(name,tree_type)
    candidate_identity = None
    if candidate_owner:
        candidate_identity = (str(candidate_owner), int(candidate_revision))
        tree['perceptual_grade_next_candidate_owner'] = candidate_identity[0]
        tree['perceptual_grade_next_candidate_revision'] = candidate_identity[1]
    graph=None
    try:
        graph=_PersistentGraph(tree,prepared,candidate_identity)
        _interface(tree,'Color','INPUT','NodeSocketColor').default_value=(0,0,0,1)
        if tree_type=='ShaderNodeTree':_interface(tree,'Alpha','INPUT','NodeSocketFloat').default_value=1
        _interface(tree,'Color','OUTPUT','NodeSocketColor')
        for n in ('Alpha','Decode Valid','Pole Margin','Saturated'):_interface(tree,n,'OUTPUT','NodeSocketFloat')
        source=graph.node('NodeGroupInput');output=graph.node('NodeGroupOutput');output.is_active_output=True
        state=graph.encode_cones(graph.matrix(source.outputs['Color'],graph.prepared.linear_to_cones))
        state=graph.color(graph.tone(state));decoded=output_guard(graph,graph.hk_guard(state))
        if tree_type=='CompositorNodeTree':
            separate=graph.node('CompositorNodeSeparateColor');separate.mode='RGB'
            graph.connect(source.outputs['Color'],separate.inputs['Image']);alpha=separate.outputs['Alpha']
            restore=graph.node('CompositorNodeSetAlpha');restore.inputs['Type'].default_value='Replace Alpha'
            graph.connect(decoded.color,restore.inputs['Image']);graph.connect(alpha,restore.inputs['Alpha']);color=restore.outputs['Image']
        else:alpha=source.outputs['Alpha'];color=decoded.color
        for value,n in ((color,'Color'),(alpha,'Alpha'),(decoded.valid,'Decode Valid'),(decoded.pole_margin,'Pole Margin'),(decoded.saturated,'Saturated')):
            graph.connect(value,output.inputs[n])
        for slot,(table,image) in tuple(graph.image_slots.items()):
            if image is None:graph._packed_image(table.pixels,key=('persistent',slot),label=slot)
        tree['perceptual_grade_nodes_schema']=LAYOUT_SCHEMA
        tree['perceptual_grade_nodes_persistent']=True
        tree['perceptual_grade_nodes_revision']=0
        stats=count_nodes(tree,graph.images)
        built=BuiltGrade(tree,tuple(graph.images),tuple(graph.helper_groups),prepared,stats)
        for name,(_,image) in graph.image_slots.items():
            table=prepared.table if name=='tone' else getattr(prepared.color,name)
            current=np.empty(table.pixels.size,dtype=np.float32);image.pixels.foreach_get(current)
            if not np.array_equal(current.reshape(table.pixels.shape),table.pixels):
                raise RuntimeError('Persistent initial field readback failed: '+name)
        PersistentGrade._readback_bindings(graph.bindings,prepared)
        return PersistentGrade(graph,built)
    except BaseException:
        bpy.data.node_groups.remove(tree,do_unlink=True)
        if graph is not None:
            for image in graph.images:
                if not image.users:bpy.data.images.remove(image)
        raise
