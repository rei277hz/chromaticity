"""Build and validate the fixed native AP1 boundary asset; no Blender required."""
import argparse
from dataclasses import replace
import hashlib
import importlib
import io
import json
from pathlib import Path
import time
import zipfile
import numpy as np

from color_tools.perceptual_grade_nodes.boundary import (
    PreparedBoundary, SEED_SPLIT, SEED_LOW_CELLS, SEED_HIGH_CELLS, SEED_HUE_CELLS,
    CORRECTION_STEPS, RESOURCE_NAME, RESOURCE_SCHEMA, RESOURCE_FLOATS, _context_geometry,
)
from color_tools.perceptual_grade_nodes.prepare import prepare_tone
from color_tools.perceptual_grade_nodes.tables import readonly


def generate_boundary(fl,aw,gamma,*,low_cells=None,high_cells=None,hue_cells=None,
                      enforce_accuracy=True):
    """Generate and audit a boundary seed, canonical unless explicitly sized.

    Diagnostic callers may disable accuracy admission to render a smaller
    failing seed. Geometry, probe coverage, the split and correction algorithm
    are unchanged; ``max_error`` always contains the complete finite audit.
    The packaged resource writer accepts only the canonical representation.
    """
    low_cells=SEED_LOW_CELLS if low_cells is None else low_cells
    high_cells=SEED_HIGH_CELLS if high_cells is None else high_cells
    hue_cells=SEED_HUE_CELLS if hue_cells is None else hue_cells
    for name,value in (('low_cells',low_cells),('high_cells',high_cells),('hue_cells',hue_cells)):
        if (not isinstance(value,(int,np.integer)) or isinstance(value,(bool,np.bool_))
                or value<1):
            raise ValueError(f'Boundary {name} must be a positive integer')
    low_cells,high_cells,hue_cells=map(int,(low_cells,high_cells,hue_cells))
    matrix,inverse,rw,maximum=_context_geometry(fl,aw,gamma)
    empty=PreparedBoundary(readonly(matrix),readonly(inverse),fl,aw,gamma,rw,maximum,np.empty((0,0,4)),0.,
                           seed_split=SEED_SPLIT,seed_low_cells=low_cells,seed_high_cells=high_cells,
                           seed_hue_cells=hue_cells,correction_steps=CORRECTION_STEPS)
    heights=np.r_[np.linspace(0,SEED_SPLIT,low_cells,endpoint=False),np.linspace(SEED_SPLIT,1,high_cells+1)]
    hues=np.linspace(0,2*np.pi,hue_cells+1)
    t,h=np.meshgrid(heights,hues,indexing='ij')
    roots=empty.exact(t,h)
    clipped=np.clip(t,1e-9,1-1e-9);beta=empty.direction(h)
    values,derivatives,upper=empty.normalized(clipped,roots,beta)
    targets=np.where(derivatives>0,upper[...,None],0.)
    correction=np.divide(targets-values,derivatives,out=np.full_like(values,np.inf),where=derivatives!=0)
    faces=np.minimum(np.maximum(roots[...,None],roots[...,None]+correction),empty.outer(clipped,beta)[...,None])
    pixels=np.zeros((*roots.shape,4),np.float32);pixels[...,:3]=faces;pixels[...,3]=1
    result=replace(empty,pixels=readonly(pixels,np.float32),
                   seed_max_error=float(np.max(abs(np.min(pixels[...,:3],axis=-1)-roots)/(1+roots))))
    # Every cell center catches sharp active-face changes that random samples
    # can miss. Fixed random points, float32 selector boundaries and both tips
    # complement the structured probe; this is a finite gate, not a proof.
    tt,hh=np.meshgrid((heights[1:]+heights[:-1])/2,(np.arange(hue_cells)+.5)*(2*np.pi/hue_cells),indexing='ij')
    rng=np.random.default_rng(20261029)
    probe_t=[tt.ravel(),rng.uniform(0,1,16384)]
    probe_h=[hh.ravel(),rng.uniform(-np.pi,np.pi,16384)]
    limits=np.r_[np.geomspace(1e-8,.001,24),1-np.geomspace(1e-7,.001,24),
                 *([np.nextafter(np.float32(v),np.float32(0)),v,np.nextafter(np.float32(v),np.float32(1))] for v in (.5,SEED_SPLIT))]
    tt,hh=np.meshgrid(limits,np.arange(64)*(2*np.pi/64),indexing='ij')
    t=np.concatenate((*probe_t,tt.ravel()));h=np.concatenate((*probe_h,hh.ravel()))
    exact=result.exact(t,h);native=result.corrected(t,h)
    scale=rw*t*(1-t)
    error=float(np.max(abs(scale*(native-exact))/(1+scale*exact)))
    if not np.isfinite(pixels).all() or not np.isfinite(error):
        raise ValueError('Output-boundary generation produced nonfinite values')
    if enforce_accuracy and error>2e-5:
        raise ValueError(f'Output-boundary root internal gate failed: {error:.8g} > 2e-5')
    return replace(result,max_error=error,probe_count=len(t))


def resource_payload(boundary):
    expected=(SEED_SPLIT,SEED_LOW_CELLS,SEED_HIGH_CELLS,SEED_HUE_CELLS,CORRECTION_STEPS)
    actual=(boundary.seed_split,boundary.seed_low_cells,boundary.seed_high_cells,
            boundary.seed_hue_cells,boundary.correction_steps)
    if actual!=expected or boundary.pixels.shape!=(SEED_LOW_CELLS+SEED_HIGH_CELLS+1,SEED_HUE_CELLS+1,4):
        raise ValueError('Diagnostic boundary layouts cannot be packaged as the runtime resource')
    if not np.isfinite(boundary.max_error) or not 0<=boundary.max_error<=2e-5:
        raise ValueError('Boundary resource must pass the canonical accuracy gate')
    payload = {name: np.asarray(getattr(boundary, name), dtype=np.float64) for name in RESOURCE_FLOATS}
    payload.update(matrix=boundary.matrix, inverse=boundary.inverse, pixels=boundary.pixels,
                   seed_split=np.asarray(SEED_SPLIT, dtype=np.float64))
    payload.update({name: np.asarray(value, dtype=np.int64) for name, value in dict(
        schema=RESOURCE_SCHEMA, seed_low_cells=SEED_LOW_CELLS, seed_high_cells=SEED_HIGH_CELLS,
        seed_hue_cells=SEED_HUE_CELLS, correction_steps=CORRECTION_STEPS,
        probe_count=boundary.probe_count).items()})
    return payload


def write_resource(path, payload):
    """Fixed ZIP metadata and member order make the NPZ byte-reproducible."""
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(payload):
            encoded = io.BytesIO()
            np.lib.format.write_array(encoded, np.asarray(payload[name]), allow_pickle=False)
            member = zipfile.ZipInfo(name+'.npy', date_time=(1980, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.create_system = 3
            member.external_attr = 0o600 << 16
            archive.writestr(member, encoded.getvalue(), compresslevel=9)


def source_hashes():
    names = (
        'color_tools.perceptual_grade_nodes.boundary', 'color_tools.perceptual_grade_nodes.prepare',
        'color_tools.perceptual_grade_nodes.tables', 'color_tools.perceptual_grade_nodes.settings',
        'color_tools.color_core.linear', 'color_tools.color_core.modcam16')
    paths = {'generator': Path(__file__), **{name: Path(importlib.import_module(name).__file__) for name in names}}
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    before = source_hashes()
    context = prepare_tone()
    started = time.perf_counter()
    boundary = generate_boundary(context.fl, context.aw, context.gamma)
    generation_seconds = time.perf_counter()-started
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir/RESOURCE_NAME
    write_resource(path, resource_payload(boundary))
    after = source_hashes()
    if before != after:
        raise RuntimeError('Boundary generation sources changed during generation')
    report = dict(schema=RESOURCE_SCHEMA, asset=RESOURCE_NAME,
                  asset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  source_sha256=before, sources_stable_during_run=True,
                  generation_seconds=generation_seconds,
                  context=dict(fl=boundary.fl, aw=boundary.aw, gamma=boundary.gamma,
                               gamut='Bradford-adapted AP1', viewing_reference_nits=203.,
                               rgb_minimum=0., rgb_maximum=1024.),
                  sampling=dict(width=boundary.pixels.shape[1], height=boundary.pixels.shape[0],
                                seed_split=SEED_SPLIT, low_cells=SEED_LOW_CELLS,
                                high_cells=SEED_HIGH_CELLS, hue_cells=SEED_HUE_CELLS,
                                correction_steps=CORRECTION_STEPS),
                  pixel_bytes=boundary.pixels.nbytes, archive_bytes=path.stat().st_size,
                  probe_count=boundary.probe_count, seed_max_error=boundary.seed_max_error,
                  corrected_radius_max_error=boundary.max_error, corrected_radius_limit=2e-5,
                  passed=True)
    (args.output_dir/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
