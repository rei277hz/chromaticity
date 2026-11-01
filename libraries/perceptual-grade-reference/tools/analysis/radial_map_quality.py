"""Measure the historical pole experiment on the adopted capacity-ratio range."""
import argparse
import json
from pathlib import Path

import numpy as np

from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.spindle import context as historical_context
from color_tools.perceptual_grade_reference.responses import GAMMA
from color_tools.perceptual_grade_reference.pole_spindle import (
    _release_radius, _compress_radius, RADIAL_POLE, RADIAL_BOUNDARY_SLOPE,
    _POLE_SQUARED, _RADIAL_A, _RADIAL_B,
)


def curvature(x, k):
    """Independent partial-fraction derivative of the normalized release."""
    p=_POLE_SQUARED;a=_RADIAL_A;b=_RADIAL_B;z=x*x
    f=-b-(a-b)/((p+1)*(1+z))+p*(a+b*p)/((p+1)*(p-z))
    df=(a-b)/((p+1)*(1+z)**2)+p*(a+b*p)/((p+1)*(p-z)**2)
    ddf=-2*(a-b)/((p+1)*(1+z)**3)+2*p*(a+b*p)/((p+1)*(p-z)**3)
    a=(k-1)*(k+1);g=1+a*f
    return a*x*((3*df+2*z*ddf)*g-a*z*df*df)/g**1.5


def generate(output_dir):
    model=Model()
    context=historical_context(model.fl,model.aw,model.native_matrix)
    t=np.unique(np.r_[np.geomspace(1e-12,.01,32),np.linspace(.01,.99,99),
                      1-np.geomspace(1e-12,.01,32)])
    angles=np.linspace(-np.pi,np.pi,721,endpoint=False)
    ja=context.white*t**GAMMA
    k=context.capacity(ja[:,None],angles)/context.body(ja)[:,None]
    ratios=np.quantile(k,[0,.1,.25,.5,.75,.9,1])
    x=np.linspace(.55,.95,4001)
    cases=[]
    for ratio in ratios:
        values=curvature(x,float(ratio));index=int(np.argmin(values))
        # Endpoint minima are not evidence for an interior shoulder.
        shoulder=float(x[index]) if 0<index<len(x)-1 else None
        raw=.9*float(ratio)
        cases.append(dict(k=float(ratio),curvature_minimum_x=shoulder,
                          compressed_90_percent_capacity=float(_compress_radius(raw,ratio)),
                          boundary_slope=float(ratio+RADIAL_BOUNDARY_SLOPE*(ratio-1/ratio)),
                          previous_boundary_slope=float(7*ratio-6/ratio)))
    radii=np.unique(np.r_[0.,np.geomspace(1e-300,.01,100),np.linspace(0,1,10001)])
    released=_release_radius(radii[:,None],ratios)
    restored=_compress_radius(released,ratios)
    error=np.abs(restored-radii[:,None])
    relative=np.divide(error,radii[:,None],out=np.zeros_like(error),where=radii[:,None]>0)
    report=dict(scope='historical p=1.001, d=20 pole experiment; active reference and production use cubic',
                pole=RADIAL_POLE,shape=1.,profile_boundary_derivative=RADIAL_BOUNDARY_SLOPE,
                previous_parameters=dict(pole=1.01,profile_boundary_derivative=6.),
                capacity_samples=int(k.size),
                capacity_quantiles=[0,.1,.25,.5,.75,.9,1],cases=cases,
                roundtrip_max_absolute=float(error.max()),
                roundtrip_max_relative=float(relative.max()),
                shoulder_definition='interior minimum of release second derivative on [0.55,0.95]; grid step 0.0001',
                limitation='Sampled curvature diagnostics, not a uniform shoulder or geometry certificate.')
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    rows=['# Historical pole-map diagnostics','',report['limitation'],'',
          '| k=U/B | Curvature minimum x | Compressed 0.9U / B | Boundary slope |',
          '| ---: | ---: | ---: | ---: |']
    for row in cases:
        shoulder=row['curvature_minimum_x']
        label=f'{shoulder:.4f}' if shoulder is not None else 'no interior minimum'
        rows.append(f"| {row['k']:.8g} | {label} | {row['compressed_90_percent_capacity']:.8f} | {row['boundary_slope']:.8g} |")
    rows.extend(['',f"Capacity samples: {k.size:,}; normalized roundtrip maximum relative error: {relative.max():.3g}.",
                 '',report['shoulder_definition']+'.',''])
    (output_dir/'summary.md').write_text('\n'.join(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    generate(parser.parse_args().output_dir)
