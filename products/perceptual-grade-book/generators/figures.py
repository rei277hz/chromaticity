"""Generate numerical illustrations directly from the production grading model."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pg_book_legacy.model import linear as lm, tone as tm, color as cm, lut
from pg_book_generators.figure_common import benchmark_data, manifest, write_json

COLORS = ['#265787', '#e87d0d', '#54834f', '#aa4773']
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.prop_cycle': matplotlib.cycler(color=COLORS), 'savefig.facecolor': '#fafaf8',
                     'figure.facecolor': '#fafaf8', 'axes.facecolor': '#fafaf8', 'axes.grid': True,
                     'grid.alpha': .18, 'figure.dpi': 120, 'savefig.dpi': 180})



def save(fig, directory, name):
    fig.tight_layout(pad=1.5)
    fig.savefig(directory / (name + '.png'))
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output_dir; images = out / 'images'; fragments = out / 'fragments'
    images.mkdir(parents=True, exist_ok=True); fragments.mkdir(parents=True, exist_ok=True)
    t = tm.model(tm.Parameters()); base = cm.model(tm.Parameters(), cm.Parameters())
    H = np.linspace(0, t.plot_max * 100, 600)

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    x = np.linspace(-1, 1, 301); refs = lm.references('Linear Rec.709')
    for i, ref in enumerate(refs):
        vector = np.asarray(lm.xyz(ref))-np.asarray(lm.xyz(lm.D65))
        axes[0].plot(x, 1+x*vector[1], label=('Cyan–Red','Yellow–Blue')[i]+' / default')
        param = replace(lm.neutral_parameters('Linear Rec.709'), **{('cr','yb')[i]+'_balance': -.4})
        matrix = np.asarray(lm.directional_matrix(param, 'Linear Rec.709'))
        a = np.asarray(lm.xyz(lm.D65))[None,:] + x[:,None]*vector
        axes[0].plot(x, (a@matrix.T)[:,1], '--', label=('Cyan–Red','Yellow–Blue')[i]+' / UI +0.4')
    source = (0.38, .35); cat = np.asarray(lm.adaptation(source, lm.D65))
    cone = np.asarray(lm.CAT16)@cat@np.asarray(lm.ICAT16)
    axes[1].bar(['Cone 1','Cone 2','Cone 3'], np.diag(cone), color=COLORS[:3])
    axes[1].axhline(1, color='#555555', linestyle='--')
    axes[0].set(xlabel='Position around white along a basis vector', ylabel='Relative Y', title='Balance tilts the luminance response'); axes[0].legend(fontsize=7)
    axes[1].set(ylabel='CAT16 adaptation gain', title='Source white (0.38, 0.35) → D65')
    save(fig, images, 'linear-basis')

    fig, ax = plt.subplots(figsize=(7.5, 4))
    for fit in (-1, 0, 2, 4):
        m = tm.model(replace(tm.Parameters(), input_midtones=55, input_white=280, input_highlights=1400, fit=fit))
        ax.plot(H/100, m.remap(H/100), label=f'Fit {fit}')
    ax.plot(H/100, H/100, '--', color='#777777', label='Identity')
    ax.scatter(m.source, m.target, marker='x', color='#343434', label='Soft landmark targets')
    ax.axvline(1, color='#777777', alpha=.5); ax.axhline(1,color='#777777',alpha=.5)
    ax.set(xlabel='Input normalized H / 100', ylabel='Output normalized H / 100', title='Monotone tone curve and adjustable Fit')
    ax.legend(fontsize=8); save(fig, images, 'tone-curves')
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    targets = np.linspace(20,180,400); h = 100.; c = 20.; ja = math.sqrt(h*h-66*c)
    gain = tm.saturation_gain(h,ja,c,targets)
    axes[0].plot(targets,c*gain,label='Preserve modCAM16 saturation'); axes[0].plot(targets,c*(targets/h)**2,'--',label='Squared-H coupling')
    axes[1].plot(targets,75*c/ja*np.ones_like(targets),label='Preserve modCAM16 saturation'); axes[1].plot(targets,75*c/ja*targets/h,'--',label='Squared-H coupling')
    axes[0].set(xlabel='Mapped H',ylabel='Resulting C',title='Input H = 100, C = 20'); axes[1].set(xlabel='Mapped H',ylabel='Saturation s',title='Saturation stays constant'); axes[0].legend(fontsize=8)
    save(fig, images, 'tone-saturation')

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.7))
    for i, name in enumerate(cm.TONES):
        axes[0].plot(H,base.weights(H,0)[:,i],label=name)
    for fit in (-1,0,2,4):
        m=cm.model(tm.Parameters(),replace(cm.Parameters(),j_low_1=6,j_fit=fit))
        axes[1].plot(H,m.curve(H,'j_low'),label=f'Fit {fit}')
    axes[0].set(xlabel='H',ylabel='Coefficient weight',title='Tones blend smoothly'); axes[1].set(xlabel='H',ylabel='Cₗ → J coefficient',title='One Midtones adjustment across lightness')
    axes[0].legend(fontsize=8); axes[1].legend(fontsize=8); save(fig, images, 'color-tone-weights')
    fig, axes = plt.subplots(1,2,figsize=(9,3.7)); c=np.linspace(0,50**2/66,600)
    d=cm.chroma_drivers(c,np.sqrt(np.maximum(0,50**2-66*c)))
    axes[0].plot(c,d[:,0],label='Low-chroma driver Cₗ'); axes[0].plot(c,d[:,1],label='High-chroma driver Cₕ')
    axes[0].set(xlabel='Chroma C',ylabel='Driver weight',title='At H = 50 / p = 2 / s₀ = 35'); axes[0].legend(fontsize=8)
    hue=np.linspace(-180,180,400);radius=20;den=math.hypot(radius,2)
    axes[1].plot(hue,radius*np.cos(np.deg2rad(hue))/den,label='a driver'); axes[1].plot(hue,radius*np.sin(np.deg2rad(hue))/den,label='b driver')
    axes[1].axhline(0,color='#777777'); axes[1].set(xlabel='Hue h (degrees)',ylabel='Signed driver weight',title='Opponent drivers choose opposite sides'); axes[1].legend(fontsize=8)
    save(fig, images, 'color-drivers')
    fig, axes=plt.subplots(1,2,figsize=(9,3.7));a=np.linspace(0,2*np.pi,500); ab=20*np.stack([np.cos(a),np.sin(a)],axis=-1)
    for value in (0,.25,.75):
        result=cm.hue_concentration(ab,np.broadcast_to([value,0],ab.shape)); angle=np.unwrap(np.arctan2(result[:,1],result[:,0]))
        axes[0].plot(np.rad2deg(a),np.rad2deg(angle),label=f'a concentration {value}')
        axes[1].plot(np.rad2deg(a),np.gradient(angle,a),label=f'a concentration {value}')
    axes[0].set(xlabel='Input hue (degrees)',ylabel='Output hue (degrees)',title='Positive values gather hue around +a');axes[1].set(xlabel='Input hue (degrees)',ylabel='Local hue spacing ratio',title='Hue ordering remains continuous');axes[0].legend(fontsize=8)
    save(fig,images,'color-hue-concentration')

    C=np.linspace(0,180,650);requested=np.stack([np.full_like(C,50),C,np.zeros_like(C)],axis=-1);ref=np.broadcast_to([50,20,0],requested.shape)
    safe=cm.project_hk(requested,ref);energy=cm.hk_energy(requested,ref)
    fig,ax=plt.subplots(figsize=(7.5,4)); ax.plot(C,np.full_like(C,50),'--',label='Requested H');ax.plot(C,safe[:,0],label='Repaired H');ax.axhline(60,linestyle=':',label='20% lift bound')
    second=ax.twinx();second.plot(C,safe[:,1],color=COLORS[2],label='Repaired C');second.set_ylabel('Repaired C');ax.set(xlabel='Requested C',ylabel='H',title='Bounded lift shares the repair with chroma reduction');ax.legend(loc='upper left',fontsize=8);second.legend(loc='lower right',fontsize=8)
    save(fig,images,'guard-boundary')
    fig,axes=plt.subplots(1,2,figsize=(9,3.7));D=2500-66*C;delta=(2500-66*20)*2500/(2500+(2500-66*20))
    axes[0].plot(D,energy);axes[0].axvline(delta,color='#777777',linestyle='--',label='Knee δ');axes[0].set(xlabel='Requested energy D = H² − 66 C',ylabel='Repaired energy E',title='A smooth positive achromatic-energy floor');axes[0].legend(fontsize=8)
    axes[1].plot(safe[:,1],safe[:,0],label='Guarded points');cc=np.linspace(0,max(safe[:,1])+5,400);axes[1].plot(cc,np.sqrt(66*cc),'--',label='H² = 66 C boundary');axes[1].set(xlabel='C',ylabel='H',title='Repaired points admit a real J_A');axes[1].legend(fontsize=8)
    save(fig,images,'guard-energy')

    fig,axes=plt.subplots(1,2,figsize=(9,3.8)); grid=lut.axis()
    axes[0].plot(np.arange(lut.SIZE),grid,'.-',markersize=3);axes[0].set(xlabel='Grid index',ylabel='Linear ACEScg component',title='65 samples / 0…128 coverage')
    axes[1].plot(np.arange(lut.SIZE),grid,'.-',markersize=3);axes[1].set(xlabel='Grid index',ylabel='Linear RGB component',title='Extra density near black',ylim=(-.025,.25));axes[1].axhline(0,color='#555555')
    save(fig,images,'lut-input-grid')
    fig,axes=plt.subplots(1,2,figsize=(9,3.7));x=np.linspace(.01,.99,500)
    axes[0].plot(x,lut.decode(x));axes[0].set(xlabel='Shaped coordinate',ylabel='Linear ACEScg component',title='Input shaper locates a nonuniform cell')
    lo,hi=.03,.12;points=np.linspace(lo,hi,200);f=(points-lo)/(hi-lo)
    axes[1].plot(points,2.4*points-.1,label='Affine reference');axes[1].plot(points,(1-f)*(2.4*lo-.1)+f*(2.4*hi-.1),'--',label='Physical-cell interpolation')
    axes[1].set(xlabel='Linear component between two vertices',ylabel='Output component',title='Linear-RGB fractions reproduce affine transforms');axes[1].legend(fontsize=8)
    save(fig,images,'lut-interpolation')

    benchmark=benchmark_data(args.data/'benchmark.json'); rows=benchmark['cases']
    fig,axes=plt.subplots(1,2,figsize=(9,3.8));labels=['Shader / small','Shader / full','Compositor'];pos=np.arange(3);width=.34
    lines=['| Workload | Method | Preparation (s) | Median render (s) |','| --- | --- | ---: | ---: |']
    for index,method in enumerate(('LUT','DIRECT')):
        selected=[next(r for r in rows if r['workload']==work and r['method']==method) for work in ('shader-small','shader-full','compositor-full')]
        axes[0].bar(pos+(index-.5)*width,[statistics.median(r['render_seconds']) for r in selected],width,label={'LUT':'Baked LUT','DIRECT':'Direct'}[method])
        axes[1].bar(pos+(index-.5)*width,[r['prepare_seconds'] for r in selected],width,label={'LUT':'Baked LUT','DIRECT':'Direct'}[method])
        for label,row in zip(labels,selected):lines.append(f'| {label} | {method} | {row["prepare_seconds"]:.3f} | {statistics.median(row["render_seconds"]):.3f} |')
    for ax in axes:ax.set_xticks(pos,labels);ax.legend(fontsize=8)
    axes[0].set(ylabel='Seconds',title='Steady render');axes[1].set(ylabel='Seconds',title='Graph and grade preparation')
    fig.suptitle(('ILLUSTRATIVE DATA — replace with workstation measurements' if benchmark['status']=='illustrative' else 'Measured on '+benchmark['environment']['device']),fontsize=11)
    save(fig,images,'render-benchmark')
    label='Illustrative data. These values demonstrate the reporting layout.' if benchmark['status']=='illustrative' else 'Workstation measurements. See the linked JSON for settings and every trial.'
    (fragments/'benchmark.md').write_text(label+'\n\n'+'\n'.join(lines)+'\n',encoding='utf-8')
    write_json(out/'numerical-data.json',{'reference_nits':t.reference,'peak_nits':t.peak,'tone_targets':t.target.tolist(),'chroma_drivers':{'p':2,'s0':cm.CHROMA_SATURATION,'Cn':cm.CHROMA_NEUTRAL},'guard_sample_50_80':cm.project_hk(np.array([50.,80.,0.]),np.array([50.,20.,0.])).tolist()})
    manifest(out,[args.data/'benchmark.json',Path(__file__),
                  *(Path(module.__file__) for module in (lm,tm,cm,lut))],
             'Perceptual Grade 1.23.2 numerical figures',
             {'docs/data': args.data, 'generators': Path(__file__).parent,
              'legacy': Path(lm.__file__).parent.parent})


if __name__=='__main__':main()
