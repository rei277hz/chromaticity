from color_tools.perceptual_grade_blender.model.bake_inverse_gpu import Program as ReferenceGPUProgram
"""Reference inverse 65³ CPU/GLSL timings and fidelity, without LUT result caches."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack,contextmanager
from dataclasses import replace
from datetime import datetime
from functools import partial
import hashlib
from inspect import signature
import json
from pathlib import Path
from statistics import median
import sys
from threading import get_ident,local
import time
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_reference.model import Settings
from tests.reference.legacy_capacity import LegacyCapacityModel
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from color_tools.perceptual_grade_core.model import bake_inverse
from tests.reference import legacy_capacity


def current_policy(*,tone_table_tolerance=None):
    """Effective study values, including an enclosing study's tone factory."""
    if tone_table_tolerance is None:
        tone_table_tolerance=signature(legacy_capacity.ToneTable).parameters['tolerance'].default
    return dict(rgb_relative=float(bake_inverse.RGB_RELATIVE_TOLERANCE),
        rgb_absolute=float(bake_inverse.RGB_ABSOLUTE_TOLERANCE),
        raw_tolerance=float(bake_inverse.TOLERANCE),
        stage3_stopping=float(bake_inverse.SEARCH_TOLERANCE),
        stage3_iterations=int(bake_inverse.ITERATIONS),
        tone_table_tolerance=float(tone_table_tolerance))


@contextmanager
def study_policy(*,rgb_relative=None,rgb_absolute=None,raw_tolerance=None,
                 stage3_stopping=None,stage3_iterations=None,tone_table_tolerance=None):
    """Scope one CPU/GLSL study; compile a fresh Program inside this context.

    All worker jobs must finish before exit. No production default is changed.
    Unspecified values inherit the current policy, including nested contexts.
    """
    values=current_policy(tone_table_tolerance=tone_table_tolerance)
    updates=dict(rgb_relative=rgb_relative,rgb_absolute=rgb_absolute,raw_tolerance=raw_tolerance,
        stage3_stopping=stage3_stopping,stage3_iterations=stage3_iterations,
        tone_table_tolerance=tone_table_tolerance)
    values.update({name:value for name,value in updates.items() if value is not None})
    constants={'rgb_relative':'RGB_RELATIVE_TOLERANCE','rgb_absolute':'RGB_ABSOLUTE_TOLERANCE',
        'raw_tolerance':'TOLERANCE','stage3_stopping':'SEARCH_TOLERANCE'}
    for name in constants:
        value=float(values[name])
        if not np.isfinite(value) or (value<0 if name=='rgb_absolute' else value<=0):
            raise ValueError(f'{name} must be finite and '+('>= 0' if name=='rgb_absolute' else '> 0'))
        with np.errstate(over='ignore',under='ignore'):value=np.float32(value)
        if not np.isfinite(value) or (value<0 if name=='rgb_absolute' else value<=0):
            raise ValueError(f'{name} must be finite float32 and '+('>= 0' if name=='rgb_absolute' else '> 0'))
        values[name]=float(value)
    rounds=values['stage3_iterations']
    if not np.isfinite(rounds) or not 1<=rounds<=80 or int(rounds)!=rounds:
        raise ValueError('stage3_iterations must be an integer from 1 through 80')
    values['stage3_iterations']=int(rounds)
    tone=float(values['tone_table_tolerance'])
    if not np.isfinite(tone) or tone<=0:raise ValueError('tone_table_tolerance must be finite and > 0')
    values['tone_table_tolerance']=tone
    with ExitStack() as scope:
        for name,constant in constants.items():
            scope.enter_context(patch.object(bake_inverse,constant,np.float32(values[name])))
        scope.enter_context(patch.object(bake_inverse,'ITERATIONS',values['stage3_iterations']))
        scope.enter_context(patch.object(legacy_capacity,'ToneTable',partial(legacy_capacity.ToneTable,tolerance=tone)))
        yield values


def cases():
    reset=Settings();gain=lambda x:Settings(color=ColorSettings(global_gain=x))
    mixed=Settings(color=ColorSettings(global_gain=.15,web=WebSettings(
            hue_degrees=((0.,)*6,(3.,2.,1.,-1.,-2.,0.),(0.,)*6,(0.,)*6),
            log_chroma=((0.,)*6,(.03,0.,-.02,0.,.01,0.),(0.,)*6,(0.,)*6),
            log_scale=((0.,)*6,(0.,)*6,(.02,0.,0.,-.01,0.,0.),(0.,)*6)),
        adaptance=((0.,0.),(0.,0.),(0.,.01),(0.,0.)),
        lightness=((0.,0.,0.,0.),(0.,.1,0.,0.),(0.,0.,0.,0.),(0.,0.,0.,0.))))
    return {
        'reset':([reset],['INVERSE']),
        'tone':([Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))],['INVERSE']),
        'chroma':([gain(.25)],['INVERSE']),
        'unreachable_chroma':([gain(-1.)],['INVERSE']),
        'mixed':([mixed],['INVERSE']),
        'mixed_tone':([replace(mixed,tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)))],['INVERSE']),
        'raw_pair':([gain(.1),gain(.2)],['FORWARD','INVERSE']),
        'matching_pair':([mixed,mixed],['FORWARD','INVERSE']),
    }


def lattice(size):
    axis=.01*np.expm1(np.linspace(0,1,size)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
    return np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3).astype('f4')


def cpu_bake(stack,rgb,chunk):
    with ThreadPoolExecutor(max_workers=4,thread_name_prefix='PG inverse') as pool:
        return np.concatenate(list(pool.map(stack.bake_native,[rgb[i:i+chunk] for i in range(0,len(rgb),chunk)])))


PHASES={
    'prepare':'Input preparation, candidate ranking and assembly',
    'initial_import':'Initial RGB to appearance conversions',
    'initial_tone':'Forward tone for the central estimate',
    'stage3':'Stage 3 solver bookkeeping and reconstruction',
    'stage3_direct':'Direct Stage 3 inverse',
    'stage3_coefficients':'Stage 3 coefficient curves',
    'stage3_geometry':'Stage 3 residual geometry',
    'stage3_linear':'Stage 3 damped normal solve',
    'stage2':'Stage 2 scalar tone inverse and rescaling',
    'tone_lookup':'Stage 2 inverse tone table lookup',
    'candidate_rgb':'Candidate appearance to input RGB',
    'validation':'Validation comparison and normalization',
    'validation_import':'Validation: RGB to appearance',
    'validation_tone':'Validation: forward tone',
    'validation_grade':'Validation: forward creative grade',
    'validation_export':'Validation: appearance to RGB',
}


class PhaseProfile:
    """Exclusive phase intervals per worker; no tracing inside NumPy kernels."""
    def __init__(self):self.local=local();self.workers={}

    def wrap(self,function,event,phase,row_argument=0):
        def measured(*args,**kwargs):
            if not hasattr(self.local,'state'):
                self.local.state=dict(stack=[],seconds={key:0. for key in PHASES},calls={},last=None,active_chunks=[])
                self.workers[get_ident()]=self.local.state
            state=self.local.state;frames=state['stack']
            name=event(*args,**kwargs) if callable(event) else event
            if name=='chunk':state['active_rows']=[]
            group=phase(*args,**kwargs) if callable(phase) else phase
            # Split the complete forward check into exclusive operations.
            # Unclassified nested calls remain in their parent's phase.
            if frames and frames[-1][0].startswith('validation'):
                group={'enter':'validation_import','forward_tone':'validation_tone',
                       'forward_grade':'validation_grade','export':'validation_export'}.get(name,frames[-1][0])
            frame=[group,time.perf_counter(),0.];frames.append(frame)
            try:
                return function(*args,**kwargs)
            finally:
                end=time.perf_counter();duration=end-frame[1];frames.pop()
                state['seconds'][group]+=duration-frame[2]
                if frames:frames[-1][2]+=duration
                else:state['last']=end
                count=state['calls'].setdefault(name,dict(calls=0,rows=0))
                rows=len(args[row_argument]);count['calls']+=1;count['rows']+=rows
                if name=='normal_step':state['active_rows'].append(rows)
                if name=='chunk':state['active_chunks'].append(dict(input_rows=rows,active_rows=state['active_rows']))
                count['maximum_batch']=max(count.get('maximum_batch',0),rows)
                if name=='stage3_residual':
                    bucket=next((str(n) for n in (32,256,2048,16384,65536) if rows<=n),'larger')
                    batches=count.setdefault('batch_size_histogram',{})
                    batches[bucket]=batches.get(bucket,0)+1
        return measured

    def run(self,prepare,rgb,chunk,expected):
        start=time.perf_counter();stack=prepare();grade_setup=time.perf_counter()-start
        if len(stack.solvers)!=1 or stack.directions!=('INVERSE',):
            raise ValueError('Phase breakdown requires a single inverse')
        solver=stack.solvers[0]
        with ExitStack() as patches:
            targets=[
                (stack,'bake_native','chunk','prepare',0),
                (bake_inverse,'minimize','stage3_solve','stage3',1),
                (solver,'reduced',lambda *a,**k:'stage3_reconstruct' if (a[2] if len(a)>2 else k.get('output',False)) else 'stage3_residual','stage3',0),
                (solver,'direct_state','direct_inverse','stage3_direct',0),
                (solver,'undo_tone','tone_inverse','stage2',0),
                (solver,'residual','candidate_validation','validation',0),
                (solver,'forward_prior','prior_forward','validation',0),
                (solver.kernel,'enter','enter','initial_import',0),
                (solver.kernel,'tone_state','forward_tone','initial_tone',0),
                (solver.kernel,'grade','forward_grade','validation_grade',0),
                (solver.kernel,'export','export','candidate_rgb',0),
            ]
            targets.extend((owner,name,event,phase,0) for owner,name,event,phase in [
                (solver,'coefficients','stage3_coefficients','stage3_coefficients'),
                (solver,'geometry','stage3_geometry','stage3_geometry'),
                (bake_inverse,'normal_step','normal_step','stage3_linear'),
            ] if hasattr(owner,name))
            if solver.tone_table is not None:
                targets.append((solver.tone_table,'evaluate','tone_lookup','tone_lookup',0))
            for owner,name,event,phase,row in targets:
                patches.enter_context(patch.object(owner,name,self.wrap(getattr(owner,name),event,phase,row)))
            start=time.perf_counter();actual=cpu_bake(stack,rgb,chunk);wall=time.perf_counter()-start
        equal=bool(np.array_equal(actual,expected))
        if not equal:raise ArithmeticError('Phase instrumentation changed the inverse result')
        critical=max(self.workers.values(),key=lambda w:w['last'])
        path=dict(critical['seconds']);path['host_and_idle']=wall-sum(path.values())
        if min(path.values())< -1e-9:raise ArithmeticError('Overlapping phase accounting')
        totals={key:sum(w['seconds'][key] for w in self.workers.values()) for key in PHASES}
        calls={}
        for worker in self.workers.values():
            for name,value in worker['calls'].items():
                counter=calls.setdefault(name,dict(calls=0,rows=0,maximum_batch=0))
                for key in ('calls','rows'):counter[key]=counter.get(key,0)+value.get(key,0)
                counter['maximum_batch']=max(counter['maximum_batch'],value['maximum_batch'])
                for bucket,count in value.get('batch_size_histogram',{}).items():
                    histogram=counter.setdefault('batch_size_histogram',{})
                    histogram[bucket]=histogram.get(bucket,0)+count
        rows=lambda name:calls.get(name,{}).get('rows',0)
        stage3=rows('stage3_solve');direct=rows('direct_inverse');reconstructed=stage3+direct
        approximate=int(np.count_nonzero(actual[:,3]>solver.acceptance_limit(rgb)))
        return dict(wall_seconds=wall,grade_setup_seconds=grade_setup,total_seconds=grade_setup+wall,
            bit_identical=equal,critical_worker_seconds=path,
            stage3_total_seconds=sum(value for name,value in path.items() if name.startswith('stage3')),
            stage2_total_seconds=path['stage2']+path['tone_lookup'],
            validation_total_seconds=sum(value for name,value in path.items() if name.startswith('validation')),
            all_workers_seconds=totals,calls=calls,
            active_rows_by_chunk=[chunk for worker in self.workers.values() for chunk in worker['active_chunks']],
            routes=dict(prior_accepted=len(rgb)-reconstructed,stage3_pixels=stage3,direct_inverse_pixels=direct,
                accepted_after_reconstruction=reconstructed-approximate,approximate_pixels=approximate,
                complete_forward_pixel_evaluations=rows('enter'),
                tone_inverse_pixel_evaluations=rows('tone_inverse'),
                tone_lookup_pixel_evaluations=rows('tone_lookup')),
            limitations=[
                'One additional instrumented full bake; every vertex and candidate is recalculated.',
                'Critical-worker phases are exclusive elapsed intervals on the worker finishing last; host/idle completes the job timeline.',
                'Other workers overlap this timeline. All-worker sums include scheduling and are not bake wall time or CPU-cycle measurements.',
                'Wrappers add measurement overhead; compare the separate uninstrumented trials.',
                'Validation phases split the complete forward model; Stage 2 rescaling and inverse-table lookup are exclusive rows.',
                'Grade setup is measured before worker execution; adding it to the instrumented bake gives the full traced total.',
                'CPU phase durations do not measure the fused GPU shader phases.'])


def quality(values,rgb,limit,canonical_peak=None):
    index=int(np.argmax(values[:,3]));fraction=values[:,3]/limit;worst=int(np.argmax(fraction))
    result=dict(finite=bool(np.isfinite(values).all()),maximum_residual=float(values[:,3].max(initial=0)),
        approximate_pixels=int(np.count_nonzero(values[:,3]>limit)),
        maximum_acceptance_fraction=float(fraction[worst]),worst_acceptance_input=rgb[worst].tolist(),
        residual_percentiles=dict(zip(('50','90','95','99','99.9'),np.percentile(values[:,3],[50,90,95,99,99.9]).tolist())),
        minimum_rgb=float(values[:,:3].min()),maximum_rgb=float(values[:,:3].max()),
        worst_input=rgb[index].tolist(),worst_result=values[index,:3].tolist())
    if canonical_peak is not None:
        error=values[:,3].astype(float)*np.maximum(canonical_peak,np.float32(1e-4))
        result['rgb_max_channel_error']=dict(space='canonical linear Rec.709',
            mean=float(np.mean(error)),p50=float(np.percentile(error,50)),
            p90=float(np.percentile(error,90)),p99=float(np.percentile(error,99)),maximum=float(error.max()))
    return result


def candidate_routes(stack,rgb,direct=None):
    """Untimed CPU prior acceptance counts for the supported one-inverse cases."""
    if stack.directions==('INVERSE',):
        target=rgb;appearance=False
    elif stack.directions==('FORWARD','INVERSE'):
        if stack.matching(0,1):
            return dict(prior_sufficient=0,reconstructed=0,matching_pair_bypass=len(rgb))
        k=stack.kernels[0];target=k.grade(k.tone_state(k.enter(rgb)));appearance=True
    else:return None
    solver=stack.solvers[-1]
    if direct is not None:accepted=direct['prior_sufficient']
    else:
        prior=np.clip(solver.kernel.export(target),0,1024) if appearance else target
        error=np.max(abs(solver.residual(prior,target,appearance)),axis=-1)
        accepted=int(np.count_nonzero(error<=solver.acceptance_limit(target,appearance)))
    return dict(prior_sufficient=accepted,reconstructed=0 if solver.kernel.identity else len(rgb)-accepted,
        matching_pair_bypass=0)


def direct_diagnostics(stack,rgb):
    """Untimed classification; feasibility never substitutes for reproduction."""
    if len(stack.solvers)!=1 or stack.directions[0]!='INVERSE' or not stack.solvers[0].simple:return None
    solver=stack.solvers[0];k=solver.kernel;raw=k.enter(rgb);q=solver.direct_state(raw)
    feasible=solver.feasible(q);candidate=np.clip(k.export(q),0,1024)
    errors=[np.max(abs(solver.residual(v,rgb,False)),axis=1) for v in (rgb,np.zeros_like(rgb),candidate)]
    limit=solver.acceptance_limit(rgb)
    prior=errors[0]<=limit;direct=errors[2]<=limit
    unresolved=np.minimum.reduce(errors)>limit
    count=lambda v:int(np.count_nonzero(v))
    return dict(prior_sufficient=count(prior),direct_sufficient=count(~prior&direct),
        feasible_direct_states=count(feasible),feasible_but_reproduction_fails=count(feasible&~direct),
        outside_domain_but_reproduces=count(~feasible&direct),approximate_pixels=count(unresolved),
        candidate_evaluation_limit=3)


def compare(values,baseline,rgb,limit):
    if values.shape!=baseline.shape:raise ValueError('Saved baseline does not match the requested lattice')
    difference=values[:,3]-baseline[:,3];index=int(np.argmax(difference))
    expected=baseline[:,:3].astype(float);actual=values[:,:3].astype(float)
    selected_error=np.max(abs(actual-expected),axis=-1)
    selected_limit=np.maximum(.001*np.max(abs(expected),axis=-1),.0003)
    selected_worst=int(np.argmax(selected_error/selected_limit))
    roots_lost=int(np.count_nonzero((values[:,3]>limit)&(baseline[:,3]<=limit)))
    outside=int(np.count_nonzero(selected_error>selected_limit))
    return dict(acceptance='Both arrays classified with the current requested tolerance.',
        bit_identical=bool(values.dtype==baseline.dtype and np.array_equal(values.view('u1'),baseline.view('u1'))),
        passed=bool(outside==0 and roots_lost==0 and np.isfinite(values).all()),
        selected_rgb=dict(relative_tolerance=.001,absolute_tolerance=.0003,
            space='native ACEScg selected inverse RGB',outside_tolerance=outside,
            maximum_tolerance_fraction=float((selected_error/selected_limit)[selected_worst]),
            maximum_absolute_error=float(selected_error.max(initial=0)),
            worst_input=rgb[selected_worst].tolist(),expected=expected[selected_worst].tolist(),
            actual=actual[selected_worst].tolist(),absolute_error=float(selected_error[selected_worst])),
        previous_approximate_pixels=int(np.count_nonzero(baseline[:,3]>limit)),
        roots_lost=roots_lost,
        roots_gained=int(np.count_nonzero((values[:,3]<=limit)&(baseline[:,3]>limit))),
        reproduction_worse_by_more_than_0_001=int(np.count_nonzero(difference>.001)),
        maximum_residual_increase=float(difference[index]),worst_input=rgb[index].tolist(),
        previous_result=baseline[index].tolist(),current_result=values[index].tolist())


def run(output,size,repeats,selected,cpu_only,chunk,baseline_dir,breakdown=False,probe_batch=True):
    output.mkdir(parents=True,exist_ok=True);start=time.perf_counter();model=LegacyCapacityModel();data=model.boundary.cache
    table=PolynomialTable(data);setup=time.perf_counter()-start;rgb=lattice(size)
    report=dict(timestamp=datetime.now().astimezone().isoformat(),samples=len(rgb),size=size,python=sys.version.split()[0],
        numpy=np.__version__,lookup_preparation_s=setup,cpu_lookup_bytes=sum(v.nbytes for v in table.expanded.values()),
        policy=current_policy(),
        acceptance=dict(rgb_relative=float(bake_inverse.RGB_RELATIVE_TOLERANCE),rgb_absolute=float(bake_inverse.RGB_ABSOLUTE_TOLERANCE),
            rgb_space='canonical linear Rec.709',raw_normalized=float(bake_inverse.TOLERANCE)),
        cpu_chunk=chunk,cpu_workers=4,cpu_probe_batch=probe_batch,stage3_starts=1,
        stage3_iteration_limit=int(bake_inverse.ITERATIONS),
        stage3_stopping_tolerance=float(bake_inverse.SEARCH_TOLERANCE),
        stage3_chroma_scale=dict(minimum=float(bake_inverse.CHROMA_TOE_MIN),maximum=float(bake_inverse.CHROMA_TOE_MAX)),
        cases={},limitations=[
            'No per-lattice or completed-LUT caches; every timed trial computes all vertices. No discarded warmup trials.',
            f'CPU uses four workers and {chunk}-row chunks. GPU uses real GLSL with 4096-pixel dispatch/readback batches.',
            'Immutable lookup and shader creation are reported separately. Each trial constructs a fresh grade; total includes grade setup, calculation/assembly and GPU transfers.',
            'No Blender UI, timer delay, RGBE packing, image installation, active scopes or compositor frame timing.',
            'Inverse residuals describe the selected direct/solved candidate, not global inverse existence or completeness.',
            'Every inverse considers at most prior, black and one reconstructed candidate; no additional simple-family RGB search.',
            f'RGB acceptance: max channel error <= max({float(bake_inverse.RGB_RELATIVE_TOLERANCE):.9g} * target peak, {float(bake_inverse.RGB_ABSOLUTE_TOLERANCE):.9g}) in canonical linear Rec.709.',
            f'Raw appearance acceptance: normalized residual <= {float(bake_inverse.TOLERANCE):.9g}; solver stopping is {float(bake_inverse.SEARCH_TOLERANCE):.9g} with at most {bake_inverse.ITERATIONS} Stage 3 rounds.',
            'Each run compiles a fresh GPU program with its policy; grade uploads cannot update compiled solver constants.',
            'Stage 3 searches log-J_A and a target-scaled C2 chroma coordinate, including exact zero chroma; each row retains its own transformed bounds.',
            'Approximate means the applicable acceptance limit was exceeded; it does not prove that no preimage exists.',
            'Saved baseline arrays are reclassified with the current acceptance rule when counting roots gained/lost.',
            'Baseline selection gate: native RGB difference <= max(0.001 * baseline peak, 0.0003), with no newly lost accepted inverses.',
            'CPU/GPU parity is separate: native RGB difference <= max(0.001 * CPU peak, 1e-7).'])
    from importlib.resources import files
    report['resource_sha256']=hashlib.sha256((files('color_tools.perceptual_grade_reference')/'d65_boundary.npz').read_bytes()).hexdigest()
    program=None
    if not cpu_only:
        import bpy,gpu
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL';gpu.init()
        report.update(blender=bpy.app.version_string,renderer=gpu.platform.renderer_get())
    for name in selected:
        settings,directions=cases()[name]
        def fresh_stack():
            stack=LegacyCapacityBakeStack(settings,directions,table, program_factory=ReferenceGPUProgram)
            for solver in stack.solvers:solver.probe_batch=probe_batch
            return stack
        start=time.perf_counter();stack=fresh_stack()
        item=dict(model_setup_s=time.perf_counter()-start,cpu_seconds=[],gpu_seconds=[],
            cpu_tone_preparation_seconds=[],gpu_tone_preparation_seconds=[],
            gpu_parameter_upload_seconds=[],
            tone_tables=[dict(cells=t.cells,bytes=t.bytes,requested_relative_tolerance=t.tolerance,
                preparation_probe_relative_error=t.max_error,
                rounds=t.rounds,root_evaluations=t.root_evaluations,maximum_root_iterations=t.maximum_root_iterations,
                scale=float(t.scale),tail_h=float(t.tail_h),tail_relative_bound=t.tail_relative_bound) for t in stack.tone_tables],
            cpu_grade_setup_seconds=[],gpu_grade_setup_seconds=[],cpu_total_seconds=[],gpu_total_seconds=[])
        appearance=len(directions)>1 and directions[-2]=='FORWARD'
        limit=stack.solvers[-1].acceptance_limit(rgb,appearance)
        item['acceptance_mode']='raw appearance' if appearance else 'RGB'
        solver=stack.solvers[-1]
        compared=rgb if solver.kernel.identity else solver.kernel.native(rgb,solver.canonical)
        canonical_peak=None if appearance else np.max(abs(compared),axis=-1)
        if not cpu_only:
            if program is None:
                program=stack.prepare_gpu();report['shader_creation_s']=program.compile_seconds;report['gpu_lookup_bytes']=program.lookup_bytes
            else:stack.program=program
        outputs={};baselines={}
        for backend in (('CPU',) if cpu_only else ('CPU','GPU')):
            path=baseline_dir/f'{name}-{backend.lower()}.npy' if baseline_dir else None
            if path is not None and path.exists():baselines[backend]=np.load(path)
        for repeat in range(repeats):
            for backend in (('CPU',) if cpu_only else (('CPU','GPU') if repeat%2==0 else ('GPU','CPU'))):
                start=time.perf_counter();stack=fresh_stack()
                if backend=='GPU':stack.program=program
                uploads_before=program.parameter_upload_total_seconds if backend=='GPU' else 0.
                prepared=time.perf_counter()
                result=cpu_bake(stack,rgb,chunk) if backend=='CPU' else stack.bake_native(rgb,'GPU')
                finished=time.perf_counter();duration=finished-prepared;prefix=backend.lower()
                item[prefix+'_seconds'].append(duration)
                item[prefix+'_grade_setup_seconds'].append(prepared-start)
                item[prefix+'_tone_preparation_seconds'].append(stack.tone_table_seconds)
                if backend=='GPU':
                    item['gpu_parameter_bytes']=program.parameter_bytes
                    item['gpu_combined_lookup_bytes']=program.lookup_bytes+program.parameter_bytes
                    item['gpu_parameter_upload_seconds'].append(program.parameter_upload_total_seconds-uploads_before)
                item[prefix+'_total_seconds'].append(finished-start)
                item[backend.lower()+'_quality']=quality(result,rgb,limit,canonical_peak);outputs[backend]=result
                if backend in baselines:
                    gate=compare(result,baselines[backend],rgb,limit)
                    item.setdefault('baseline_trial_gates',{}).setdefault(backend,[]).append(gate['passed'])
                    item.setdefault('baseline_trial_bit_identity',{}).setdefault(backend,[]).append(gate['bit_identical'])
                print(f'{name} {backend} {repeat+1}/{repeats}: {duration:.6f}s calculation, {finished-start:.6f}s with grade setup; '+
                    f'approximate {item[backend.lower()+"_quality"]["approximate_pixels"]}/{len(rgb)}',flush=True)
                report['cases'][name]=item
                (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if not cpu_only:
            expected=outputs['CPU'][:,:3].astype(float);actual=outputs['GPU'][:,:3]
            error=np.max(abs(actual-expected),axis=-1);device_limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
            index=int(np.argmax(error/device_limit))
            item['gpu_vs_cpu']=dict(maximum_tolerance_fraction=float((error/device_limit)[index]),
                outside_tolerance=int(np.count_nonzero(error>device_limit)),worst_input=rgb[index].tolist(),
                expected=expected[index].tolist(),actual=actual[index].tolist(),absolute_error=float(error[index]))
        item['direct_diagnostics']=direct_diagnostics(stack,rgb)
        item['cpu_candidate_routes']=candidate_routes(stack,rgb,item['direct_diagnostics'])
        if breakdown:
            item['cpu_breakdown']=PhaseProfile().run(fresh_stack,rgb,chunk,outputs['CPU'])
            item['cpu_breakdown']['wall_ratio_to_uninstrumented_median']=item['cpu_breakdown']['wall_seconds']/median(item['cpu_seconds'])
            item['cpu_breakdown']['total_ratio_to_uninstrumented_median']=item['cpu_breakdown']['total_seconds']/median(item['cpu_total_seconds'])
            print(f'{name} CPU phase profile: {item["cpu_breakdown"]["total_seconds"]:.6f}s with grade setup; '+
                f'approximate pixels {item["cpu_breakdown"]["routes"]["approximate_pixels"]}/{len(rgb)}',flush=True)
        if baseline_dir:
            item['previous_comparison']={backend:compare(result,baselines[backend],rgb,limit)
                for backend,result in outputs.items() if backend in baselines}
            item['baseline_backends_checked']=list(baselines)
            item['baseline_backends_missing']=[backend for backend in outputs if backend not in baselines]
            item['baseline_gate_passed']=bool(baselines) and all(
                all(gates) for gates in item.get('baseline_trial_gates',{}).values())
        report['cases'][name]=item
        for backend,result in outputs.items():np.save(output/f'{name}-{backend.lower()}.npy',result)
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Reference inverse LUT baking','',f'{size}³ = {len(rgb):,} vertices; {repeats} trials per case/backend.',
        f'Immutable D65 lookup preparation: {1000*setup:.2f} ms; reused across fresh grade construction in every trial.',
        'Study policy: '+json.dumps(report['policy'])+'.',
        '', '| Case | CPU setup + bake median / min / max ms | CPU calculation median / min / max ms | GPU setup + bake median / min / max ms | GPU calculation median / min / max ms | CPU approximate pixels | GPU/CPU tolerance failures |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,item in report['cases'].items():
        timing=lambda key:' / '.join(f'{1000*f(item[key]):.2f}' for f in (median,min,max)) if item[key] else '—'
        lines.append(f'| {name} | {timing("cpu_total_seconds")} | {timing("cpu_seconds")} | {timing("gpu_total_seconds")} | {timing("gpu_seconds")} | '+
            f'{item["cpu_quality"]["approximate_pixels"]} | {item.get("gpu_vs_cpu",{}).get("outside_tolerance","—")} |')
    for name,item in report['cases'].items():
        lines+=['',f'## {name}']
        if item['cpu_candidate_routes']:
            lines+=['','Untimed CPU candidate routes: '+json.dumps(item['cpu_candidate_routes'])+'.']
        for backend in ('cpu','gpu'):
            errors=item.get(backend+'_quality',{}).get('rgb_max_channel_error')
            if errors:
                lines+=['',f'{backend.upper()} maximum-channel reproduction error: '+json.dumps(errors)+'.']
        profile=item.get('cpu_breakdown')
        if profile:
            lines+=['',f'## {name}: actual CPU inverse phases','',
                '| Phase | Finishing worker timeline ms | Sum across workers ms |',
                '| --- | ---: | ---: |',
                f'| Grade preparation before workers | {1000*profile["grade_setup_seconds"]:.2f} | — |']
            for key,label in PHASES.items():
                lines.append(f'| {label} | {1000*profile["critical_worker_seconds"][key]:.2f} | {1000*profile["all_workers_seconds"][key]:.2f} |')
            lines += [f'| Host coordination and gaps on finishing worker | {1000*profile["critical_worker_seconds"]["host_and_idle"]:.2f} | — |',
                f'| Instrumented setup + bake total | {1000*profile["total_seconds"]:.2f} | — |','',
                f'Stage 3 subtotal: {1000*profile["stage3_total_seconds"]:.2f} ms on the finishing worker.',
                f'Stage 2 subtotal: {1000*profile["stage2_total_seconds"]:.2f} ms on the finishing worker.',
                f'Validation subtotal: {1000*profile["validation_total_seconds"]:.2f} ms on the finishing worker.',
                f'Instrumented / uninstrumented median wall ratio: {profile["wall_ratio_to_uninstrumented_median"]:.3f}. Output is bit-identical.','',
                'Route counts: '+json.dumps(profile['routes'])+'.','',*(f'- {v}' for v in profile['limitations'])]
        if item['tone_tables']:
            lines+=['',f'## {name}: prepared inverse tone',
                f'- CPU table construction median: {1000*median(item["cpu_tone_preparation_seconds"]):.2f} ms, included in grade setup.',
                '- Table metadata: '+json.dumps(item['tone_tables'])+'.']
            if item['gpu_tone_preparation_seconds']:
                lines += [f'- GPU table construction median: {1000*median(item["gpu_tone_preparation_seconds"]):.2f} ms, included in grade setup.',
                    f'- GPU parameter packing/upload median: {1000*median(item["gpu_parameter_upload_seconds"]):.2f} ms, included in calculation.',
                    f'- GPU parameter texture: {item["gpu_parameter_bytes"]:,} bytes; boundary plus parameters: {item["gpu_combined_lookup_bytes"]:,} bytes.']
        direct=item.get('direct_diagnostics')
        if direct:
            lines+=['',f'## {name}: direct inverse and validation',
                f'- Identity prior sufficient: {direct["prior_sufficient"]:,}.',
                f'- Additional direct candidates sufficient: {direct["direct_sufficient"]:,}.',
                f'- Remaining approximate pixels: {direct["approximate_pixels"]:,}.',
                f'- Feasible direct states: {direct["feasible_direct_states"]:,}; these still fail reproduction on {direct["feasible_but_reproduction_fails"]:,} pixels.',
                f'- Candidate budget: {direct["candidate_evaluation_limit"]} total; no additional RGB search.',
                '- Feasibility is an untimed diagnostic; acceptance always checks complete forward reproduction.']
        for backend,comparison in item.get('previous_comparison',{}).items():
            selection=comparison['selected_rgb']
            lines+=['',f'### {backend} versus saved baseline',
                f'- All RGB and residual bits unchanged in every trial: {all(item["baseline_trial_bit_identity"][backend])}.',
                f'- Every timed trial passes the baseline gate: {all(item["baseline_trial_gates"][backend])}.',
                f'- Selected RGB outside max(0.1% of baseline peak, 0.0003): {selection["outside_tolerance"]:,} pixels; worst tolerance fraction {selection["maximum_tolerance_fraction"]:.9g}.',
                f'- Worst selection input: {selection["worst_input"]}; expected {selection["expected"]}; actual {selection["actual"]}.',
                f'- Roots gained/lost: {comparison["roots_gained"]:,} / {comparison["roots_lost"]:,}.',
                f'- Reproduction residual worsens by more than 0.001: {comparison["reproduction_worse_by_more_than_0_001"]:,} pixels.',
                f'- Largest residual increase: {comparison["maximum_residual_increase"]:.9g}.',
                f'- Worst input: {comparison["worst_input"]}.',
                f'- Previous RGB + residual: {comparison["previous_result"]}.',
                f'- Current RGB + residual: {comparison["current_result"]}.']
    lines+=['',*(f'- {v}' for v in report['limitations']),'']
    (output/'summary.md').write_text('\n'.join(lines))
    print(f'Reports: {output}/summary.md and report.json',flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--size',type=int,default=65)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--case',action='append',choices=tuple(cases()),dest='selected')
    parser.add_argument('--cpu-only',action='store_true')
    parser.add_argument('--cpu-chunk',type=int,default=65536)
    parser.add_argument('--separate-probes',dest='probe_batch',action='store_false',
        help='Evaluate the four central-difference probes separately for the batching experiment.')
    parser.add_argument('--baseline-dir',type=Path)
    parser.add_argument('--breakdown',action='store_true',help='Add exclusive CPU phase timing for single inverses.')
    parser.add_argument('--rgb-relative-tolerance',type=float,default=float(bake_inverse.RGB_RELATIVE_TOLERANCE),
        help='Study-only RGB relative acceptance; production defaults are unchanged.')
    parser.add_argument('--rgb-absolute-tolerance',type=float,default=float(bake_inverse.RGB_ABSOLUTE_TOLERANCE),
        help='Study-only RGB absolute acceptance; production defaults are unchanged.')
    parser.add_argument('--stage3-iterations',type=int,default=bake_inverse.ITERATIONS,
        help='Study-only Stage 3 iteration ceiling; production defaults are unchanged.')
    parser.add_argument('--raw-tolerance',type=float,default=float(bake_inverse.TOLERANCE),
        help='Study-only normalized raw appearance acceptance.')
    parser.add_argument('--stage3-stopping-tolerance',type=float,default=float(bake_inverse.SEARCH_TOLERANCE),
        help='Study-only inner Stage 3 residual stopping threshold.')
    parser.add_argument('--tone-table-tolerance',type=float,default=current_policy()['tone_table_tolerance'],
        help='Study-only relative inverse-tone table preparation tolerance.')
    args=parser.parse_args()
    if args.size<2 or args.repeats<1 or args.cpu_chunk<1:parser.error('size >= 2, repeats >= 1 and cpu-chunk >= 1 required')
    if args.breakdown and (not args.selected or any(cases()[name][1]!=['INVERSE'] for name in args.selected)):
        parser.error('--breakdown requires explicit single-inverse cases')
    with ExitStack() as scope:
        try:
            scope.enter_context(study_policy(rgb_relative=args.rgb_relative_tolerance,
                rgb_absolute=args.rgb_absolute_tolerance,stage3_iterations=args.stage3_iterations,
                raw_tolerance=args.raw_tolerance,stage3_stopping=args.stage3_stopping_tolerance,
                tone_table_tolerance=args.tone_table_tolerance))
        except ValueError as error:parser.error(str(error))
        run(args.output_dir,args.size,args.repeats,args.selected or tuple(cases()),args.cpu_only,args.cpu_chunk,args.baseline_dir,args.breakdown,args.probe_batch)
