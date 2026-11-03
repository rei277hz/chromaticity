"""Independent native GPU gates for H-K repair and the AP1 output boundary."""
import hashlib
import json
from pathlib import Path
import numpy as np
from color_tools.kernel import prepare
from color_tools.kernel.boundary import prepare_boundary
from color_tools.perceptual_grade_reference.model import Model
from .guard_cases import guard_builder, hk_probes, boundary_probes
from .native import NativeFixture
from .oracle import metrics, exact_boundary


def _render(prepared, values, context, mode):
    fixture=NativeFixture(prepared,values,context,
        engine='BLENDER_EEVEE' if context=='shader' else 'CYCLES',
        device='CPU' if context=='shader' else 'GPU',builder=guard_builder(mode))
    try:
        return fixture.render()
    finally:
        fixture.close()


def _finite(actual):
    return all(np.isfinite(actual[name]).all() for name in ('rgb','alpha','valid','margin'))


def _receipt(values):
    return hashlib.sha256(np.asarray(values,dtype=np.float32).tobytes()).hexdigest()


def run(output_dir, boundary=None):
    """Run in an initialized Blender GPU process; write guard-internal.json.

    Every local fixture receives the same float32 values as its independent
    reference. This gate complements the complete guarded RGB report, where
    an export fallback could otherwise obscure a bad internal radius.
    """
    from .evaluate import evidence_hashes
    from .gpu_report import _json_values
    identities=evidence_hashes()
    prepared=prepare()
    if boundary is None:
        boundary=prepare_boundary(prepared.fl,prepared.aw,prepared.gamma)
    prepared=prepare(boundary=boundary)
    reference=exact_boundary(Model())
    rows=[]
    values,expected,energy=hk_probes()
    for context in ('shader','compositor'):
        for mode in ('hk','hk_color'):
            actual=_render(prepared,values,context,mode)
            coordinates=metrics(actual['rgb'],expected)
            energy_error=abs(actual['valid']-energy)/(1+abs(energy))
            worst=int(np.argmax(energy_error))
            row=dict(kind='hk',context=context,mode=mode,samples=len(values),
                pixels_sha256=_receipt(values),coordinates=coordinates,
                energy_max_normalized=float(energy_error[worst]),
                energy_worst_index=worst,energy_worst_actual=float(actual['valid'][worst]),
                energy_worst_reference=float(energy[worst]),finite=_finite(actual),
                stats=actual['stats'])
            row['passed']=bool(row['finite'] and coordinates['max_normalized']<=1e-5
                               and row['energy_max_normalized']<=1e-5)
            rows.append(row)
    probes=boundary_probes(boundary,reference)
    values=probes['values']
    for space in ('Linear Rec.709','Linear Rec.2020','ACEScg'):
        candidate=prepare(space=space,boundary=boundary)
        native=probes['native'];adapter=candidate.from_cones@boundary.inverse
        expected=native[:,1,None]+(native-native[:,1,None])@adapter.T
        for context in ('shader','compositor'):
            actual=_render(candidate,values,context,'boundary')
            rgb=metrics(actual['rgb'],expected)
            row=dict(kind='boundary_rgb',context=context,space=space,samples=len(values),
                pixels_sha256=_receipt(values),rgb=rgb,finite=_finite(actual),
                invalid_samples=int(np.count_nonzero(actual['valid']<.5)),stats=actual['stats'])
            row['passed']=bool(row['finite'] and not row['invalid_samples'] and rgb['max_normalized']<=1e-4)
            rows.append(row)
    energy,chroma,radius,radial=(probes[name] for name in ('energy','chroma','radius','radial'))
    endpoints=(energy<=0)|(energy>=boundary.white*boundary.white)
    direct=(~endpoints)&(chroma<=radius+1e-10)
    for context in ('shader','compositor'):
        actual=_render(prepared,values,context,'boundary_native')
        errors=abs(actual['margin']-radius)/(1+radius)
        worst=int(np.argmax(np.where(radial,errors,-1)))
        row=dict(kind='boundary_native',context=context,samples=len(values),
            pixels_sha256=_receipt(values),finite=_finite(actual),stats=actual['stats'],
            radius_max_normalized=float(np.max(errors[radial],initial=0)),
            radius_worst_index=worst,radius_worst_input=values[worst].tolist(),
            radius_worst_actual=float(actual['margin'][worst]),radius_worst_reference=float(radius[worst]),
            direct_radius_max_normalized=float(np.max(errors[direct],initial=0)),
            endpoint_radius_max_absolute=float(np.max(abs(actual['margin'][endpoints]),initial=0)),
            native_minimum=float(np.min(actual['rgb'])),native_maximum=float(np.max(actual['rgb'])),
            invalid_samples=int(np.count_nonzero(actual['valid']<.5)))
        row['passed']=bool(row['finite'] and not row['invalid_samples'] and
            row['radius_max_normalized']<=2e-5 and row['direct_radius_max_normalized']<=2e-5 and
            row['endpoint_radius_max_absolute']==0 and row['native_minimum']>=0 and row['native_maximum']<=1024)
        rows.append(row)
    # The explicit fallback must report the returned neutral, including its
    # radius and pole margin. Force only the trial-legality decision to fail.
    energy=.25*boundary.white*boundary.white
    angles=np.arange(256)*(2*np.pi/256)
    values=np.column_stack((np.full(256,energy),1e6*np.cos(angles),
                            1e6*np.sin(angles),np.ones(256))).astype(np.float32)
    t=(float(values[0,0])/(boundary.white*boundary.white))**(1/(2*boundary.gamma))
    pole=400-boundary.response_white*t
    for context in ('shader','compositor'):
        actual=_render(prepared,values,context,'boundary_native_fallback')
        row=dict(kind='boundary_fallback',context=context,samples=len(values),
            pixels_sha256=_receipt(values),finite=_finite(actual),stats=actual['stats'],
            radius_max_absolute=float(np.max(abs(actual['margin']))),
            pole_margin_max_relative=float(np.max(abs(actual['alpha']-pole))/pole),
            neutral_max_difference=float(np.max(abs(actual['rgb']-actual['rgb'][:,1,None]))),
            native_minimum=float(np.min(actual['rgb'])),native_maximum=float(np.max(actual['rgb'])),
            invalid_samples=int(np.count_nonzero(actual['valid']<.5)))
        row['passed']=bool(row['finite'] and not row['invalid_samples'] and
            row['radius_max_absolute']==0 and row['pole_margin_max_relative']<=2e-7 and
            row['neutral_max_difference']==0 and row['native_minimum']>0 and row['native_maximum']<1024)
        rows.append(row)
    stable=identities==evidence_hashes()
    report=dict(schema=1,**identities,reference='independent float64; identical float32 local inputs',
        hk_limit=1e-5,radius_limit=2e-5,rgb_limit=1e-4,native_cube=[0,1024],
        source_stable_during_run=stable,passed=bool(stable and all(row['passed'] for row in rows)),cases=rows)
    destination=Path(output_dir)/'guard-internal.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(_json_values(report),indent=2,allow_nan=False)+'\n')
    for row in rows:
        print(f"GPU guard {row['kind']}/{row['context']}/{row.get('space',row.get('mode',''))}: pass={row['passed']}",flush=True)
    return report
