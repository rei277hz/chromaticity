"""Audit current DCTL controls against independent float64 grading and cube geometry."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import numpy as np
from color_tools.perceptual_grade_core.model import linear, tone
from tests.support import oracle, dctl_controls
from tests.support.dctl_reference import Model, Settings, ColorSettings
from color_tools.perceptual_grade_reference.grading import ToneSettings
from tools.build.boundary_oracle import exact_geometry


def cases():
    """Current DCTL controls, independent of Blender's Warp schema."""
    yield 'reset',Settings()
    yield 'tone',Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))
    for gain in (1.,10.):
        chroma=np.zeros((4,4));chroma[2,1]=gain
        yield f'white_chroma_{gain:g}',Settings(color=ColorSettings(chroma=tuple(map(tuple,chroma))))
    yield 'hue',Settings(color=ColorSettings(global_hues=(30.,-90.)))
    yield 'adaptance',Settings(color=ColorSettings(adaptance=((20.,-10.),)*4))
    yield 'darken',Settings(color=ColorSettings(lightness=((-20.,-50.,0.,0.),)*4))
    yield 'concentration',Settings(color=ColorSettings(concentration=((.2,-.3),)*4,hue=(10.,20.,30.,40.)))
    for fit in (-2.,6.):
        yield f'combined_fit_{fit:g}',Settings(tone=ToneSettings(input_nits=(0.,7.,42.,203.,1000.),fit=fit),
            color=ColorSettings(lightness=((5.,-10.,2.,-3.),)*4,chroma=((.2,.5,-.1,.1),)*4,
                hue=(20.,-30.,10.,-5.),concentration=((.2,-.1),)*4,adaptance=((5.,-3.),)*4,
                lightness_fit=fit,chroma_fit=fit,hue_fit=fit,adaptance_fit=fit))


def controls(value):
    p=value.color;t=value.tone
    fields=dict(global_gain=p.global_gain,global_low_hue=p.global_hues[0],
        global_high_hue=p.global_hues[1],adaptance_strength=p.adaptance_strength,
        j_fit=p.lightness_fit,c_fit=p.chroma_fit,hue_fit=p.hue_fit,adaptance_fit=p.adaptance_fit)
    for stem,name,axes in (('j','lightness',('low','high','a','b')),('c','chroma',('low','high','a','b')),
            ('concentration','concentration',('a','b')),('adaptance','adaptance',('a','b'))):
        for i,row in enumerate(getattr(p,name)):
            fields.update({f'{stem}_{axis}_{i}':v for axis,v in zip(axes,row)})
    fields.update({f'hue_{i}':v for i,v in enumerate(p.hue)})
    tp=tone.Parameters(**dict(zip(tone.LEVEL_FIELDS,t.input_nits)),fit=t.fit,
        reference_nits=t.reference_nits,peak_nits=t.peak_nits)
    return oracle.settings(linear.Parameters(),tp,dctl_controls.Parameters(**fields),'Linear Rec.709')


def samples(size):
    axis=.01*np.expm1(np.linspace(0,1,size)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
    rows=[np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3)]
    face=np.stack(np.meshgrid(np.linspace(0,1024,size),np.linspace(0,1024,size),indexing='ij'),-1).reshape(-1,2)
    for fixed in range(3):
        for value in (0.,1024.):
            rgb=np.full((len(face),3),value);rgb[:,[i for i in range(3) if i!=fixed]]=face;rows.append(rgb)
    for varying in range(3):
        for a in (0.,1024.):
            for b in (0.,1024.):
                rgb=np.empty((33,3));rgb[:,varying]=np.linspace(0,1024,33)
                other=[i for i in range(3) if i!=varying];rgb[:,other[0]]=a;rgb[:,other[1]]=b;rows.append(rgb)
    rows.append(np.array([[0,1,0],[2,0,128],[1e-8]*3,[1e-5,2e-5,3e-5],
        [.0253184813856082,.0071734681614134,.0043407546657122],[1024,1024,.0019752890009854]]))
    return np.unique(np.vstack(rows).astype('f4'),axis=0)


def metrics(actual,expected,source):
    actual=np.asarray(actual,dtype=float);expected=np.asarray(expected,dtype=float)
    error=np.max(abs(actual-expected),axis=-1);limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
    ratio=error/limit;i=int(np.argmax(ratio))
    return dict(maximum_tolerance_fraction=float(ratio[i]),failed_pixels=int(np.count_nonzero(ratio>1)),
        finite=bool(np.isfinite(actual).all()),escaped_pixels=int(np.count_nonzero(np.any((actual<0)|(actual>1024),axis=-1))),
        expected_escaped_pixels=int(np.count_nonzero(np.any((expected<0)|(expected>1024),axis=-1))),
        black_mismatches=int(np.count_nonzero(np.any(actual[np.all(expected==0,axis=-1)]!=0,axis=-1))),
        output_minimum=float(np.min(actual)),output_maximum=float(np.max(actual)),
        worst=dict(index=i,source=source[i].tolist(),actual=actual[i].tolist(),expected=expected[i].tolist(),
                   absolute_error=float(error[i]),allowed_error=float(limit[i])))


def representable_case(value):
    """Choose test values representable by DCTL's integer Highlight controls.

    This prepares a representable fixture, rather than claiming that DCTL and
    Blender have identical controls. Half-integer fixture ties round upward.
    """
    spec={item['name']:item for item in oracle.UI};changed={};families={}
    for family,target in (('lightness','J'),('chroma','C')):
        rows=[list(row) for row in getattr(value.color,family)]
        for i,tone in enumerate('SMWH'):
            for j,driver in enumerate(('Low','High','a','b')):
                name=f'tone{tone}{driver}To{target}';control=spec[name];requested=rows[i][j]
                if control['type']=='DCTLUI_SLIDER_INT':
                    tested=math.floor(requested+.5)
                    if tested!=requested:changed[name]=dict(requested=requested,tested=tested)
                    rows[i][j]=tested
        families[family]=tuple(map(tuple,rows))
    return replace(value,color=replace(value.color,**families)),changed


def run(output,size=9):
    if size<2:raise ValueError('The audit grid needs at least two points per axis')
    output.mkdir(parents=True,exist_ok=True);rgb=samples(size);base=Model();rows=[]
    to_xyz=base.cones_to_xyz@np.linalg.inv(base.boundary.matrix)
    canonical=base.xyz_to_canonical@to_xyz
    for name,value in cases():
        value,control_changes=representable_case(value)
        model=Model(value);control=controls(value)
        actual=oracle.run('forward_native',rgb,control)[:,:3]
        expected=model.forward_native(rgb.astype(float))
        with exact_geometry():
            exact=rgb.astype(float) if name=='reset' else model.release_state(model.grade_state(model.enter_native(rgb.astype(float))),guard=True)
        row=dict(case=name,control_changes=control_changes,
                 fitted_float64=metrics(actual,expected,rgb),
                 independent_float64_geometry=metrics(actual,exact,rgb))
        # These targets are generated by the DCTL itself. A forward image can
        # have several preimages; report solver reproduction separately from
        # differences in the selected inverse RGB or boundary representation.
        inverse=oracle.run('inverse_native',actual,control)
        reproduced=oracle.run('forward_native',inverse[:,:3],control)[:,:3]
        peak=np.max(abs(actual@canonical.T),axis=-1)
        error=np.max(abs((reproduced-actual)@canonical.T),axis=-1)
        limit=np.maximum(.0001*peak,.00003);normalized=error/np.maximum(peak,.0001)
        index=int(np.argmax(error/limit));status=inverse[:,3]>0
        row['inverse']=dict(found_roots=int(np.count_nonzero(status)),total=len(rgb),
            reproduced_roots=int(np.count_nonzero(error<=limit)),
            declared_root_reproduction_failures=int(np.count_nonzero(status&(error>limit*1.01))),
            max_reported_residual_difference=float(np.max(abs(normalized-inverse[:,4]))),
            finite=bool(np.isfinite(inverse).all()),
            escaped_pixels=int(np.count_nonzero(np.any((inverse[:,:3]<0)|(inverse[:,:3]>1024),axis=-1))),
            worst=dict(target=actual[index].tolist(),input=rgb[index].tolist(),inverse=inverse[index,:3].tolist(),
                reproduced=reproduced[index].tolist(),absolute_canonical_error=float(error[index]),
                allowed_error=float(limit[index]),found_root=bool(status[index])))
        rows.append(row);print(json.dumps(row),flush=True)
        report=dict(samples=len(rgb),size=size,constant_bytes=int(re.search(r'#define PG_CONSTANT_BYTES (\d+)',oracle.SOURCE).group(1)),resource_regenerated=False,
            float_sliders=sum(item['type']=='DCTLUI_SLIDER_FLOAT' for item in oracle.UI),
            scope='Direct native AP1 DCTL helpers; no LUT sampling. Full XYZ/Stage 1 adapters are tested separately.',
            inverse_note='Inverse quality measures self-forward reproduction and the declared root status; projected grades can have nonunique or unreachable inverses.',results=rows)
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Direct DCTL quality','',report['scope'],'',
        '| Case | Fitted f64 max / tolerance | Exact geometry max / tolerance | DCTL inverse roots |',
        '| --- | ---: | ---: | ---: |']
    for row in rows:
        values=[row[key]['maximum_tolerance_fraction'] for key in ('fitted_float64','independent_float64_geometry')]
        lines.append(f'| {row["case"]} | {values[0]:.6g} | {values[1]:.6g} | {row["inverse"]["found_roots"]}/{len(rgb)} |')
    lines+=['','Forward tolerance: max(0.1% of the expected pixel peak, 1e-7 ACEScg).',
        'The fitted comparison uses an independent float64 evaluator for current DCTL controls; the exact geometry comparison also includes fitted-surface error.',
        f'DCTL uses {report["float_sliders"]}/64 float sliders. J/C fixtures use Cartesian a/b controls; all four Highlight drivers (Low, High, a, b) use integers. report.json records each requested → tested change. All compared models receive the same tested grade.',
        report['inverse_note'],'','Actual Resolve execution is not available here; DCTL arithmetic executes through the compiled host harness.']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--size',type=int,default=9)
    args=parser.parse_args();run(args.output_dir,args.size)
