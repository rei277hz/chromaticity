"""Native Blender window worker for the synthetic displayed-preview experiment.

Invoked by gui_drag.py, never by runtime code. Evaluation is a synchronous native
render followed by an in-memory Viewer readback and a POST_PIXEL preview draw.
This deliberately does not claim automatic Shader viewport or Next UI latency.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


SCENARIOS = ('reset', 'exposure', 'tone_fit', 'lightness', 'chroma', 'global_gain',
             'web_chroma', 'web_hue', 'web_scale', 'adaptance',
             'all_active_exposure', 'all_active_color', 'web_stress', 'reset_active',
             'aba_exposure', 'burst_exposure')


def settings_for(name, index, count):
    from color_tools.kernel.settings import Settings, WebSettings
    from tools.perceptual_grade.reports import cases, full_cases
    fraction = (index+1)/count
    settings = Settings()
    if name == 'reset':
        return settings
    if name == 'reset_active':
        return settings if index % 2 == 0 else replace(settings, color=full_cases.all_active())
    if name == 'aba_exposure':
        return replace(settings, linear=replace(settings.linear, exposure=(.2, .6, .2)[index%3]))
    if name == 'burst_exposure':
        return replace(settings, linear=replace(settings.linear, exposure=.8*fraction))
    if name == 'exposure':
        return replace(settings, linear=replace(settings.linear, exposure=.5*fraction))
    if name == 'tone_fit':
        tone = next(row[2] for row in cases.grades() if row[0] == 'combined')
        return replace(settings, tone=replace(tone, fit=-1+2*fraction))
    if name in ('lightness', 'chroma'):
        rows = ((0.,)*4, (.2*fraction, 0., 0., 0.), (0.,)*4, (0.,)*4)
        return replace(settings, color=replace(settings.color, **{name: rows}))
    if name == 'global_gain':
        return replace(settings, color=replace(settings.color, global_gain=.2*fraction))
    if name.startswith('web_') and name != 'web_stress':
        field = {'web_chroma': 'log_chroma', 'web_hue': 'hue_degrees',
                 'web_scale': 'log_scale'}[name]
        value = (8. if name == 'web_hue' else .2)*fraction
        web = replace(WebSettings(), **{field: ((value,)*6,)*4})
        return replace(settings, color=replace(settings.color, web=web))
    if name == 'adaptance':
        rows = ((0., 0.), (.2*fraction, -.1*fraction), (0., 0.), (0., 0.))
        return replace(settings, color=replace(settings.color, adaptance=rows))
    if name in ('all_active_exposure', 'all_active_color'):
        _, linear, tone = next(row for row in cases.grades() if row[0] == 'combined')
        color = full_cases.all_active()
        if name == 'all_active_exposure':
            linear = replace(linear, exposure=linear.exposure+.2*fraction)
        else:
            color = replace(color, global_gain=color.global_gain+.2*fraction)
        return Settings(linear=linear, tone=tone, color=color)
    if name == 'web_stress':
        row = next(row for row in full_cases.ui_boundaries() if row[0] == 'web_alternating_extremes')
        # Regenerate both large 1D Web fields on each UI-valid alternating edit.
        delta = .25*fraction
        chroma = tuple(tuple(value-delta if value > 0 else value+delta
                             for value in values) for values in row[3].web.log_chroma)
        scale_delta = .125*fraction
        scale = tuple(tuple(value-scale_delta if value > 0 else value+scale_delta
                            for value in values) for values in row[3].web.log_scale)
        web = replace(row[3].web, log_chroma=chroma, log_scale=scale)
        return Settings(linear=row[1], tone=row[2],
                        color=replace(row[3], web=web))
    raise ValueError(name)


def main(argv=None):
    imports_started = time.perf_counter()
    # Load native bundled modules before adding the Buck Python import tree.
    import bpy
    import gpu
    import numpy as np
    from gpu_extras.batch import batch_for_shader

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', type=Path, required=True)
    args = parser.parse_args(argv)
    config = json.loads(args.configuration.read_text())
    sys.path[:0] = config['import_paths']
    from color_tools.kernel import prepare
    from color_tools.kernel.boundary import prepare_boundary
    from color_tools.kernel.prepare import prepare_update
    from color_tools.kernel.persistent import build_persistent
    from color_tools.kernel.graph import count_nodes
    from color_tools.kernel import color_prepare, tables
    from tools.perceptual_grade.reports import cases, oracle
    from tools.perceptual_grade.reports.native import NativeFixture
    from tools.perceptual_grade.reports.gui_drag_report import summarize_samples

    output = Path(config['output'])
    started = time.perf_counter()
    software_gpu = config.get('backend', 'cpu') == 'software-gpu'
    threads = int(config.get('threads', 1))
    if threads < 1:
        raise ValueError('Native thread count must be positive')
    engine = 'BLENDER_EEVEE' if software_gpu and config['context'] == 'shader' else 'CYCLES'
    compositor_device = 'GPU' if software_gpu else 'CPU'
    report = dict(schema=1, context=config['context'], size=[config['size']]*2,
                  sample_count_per_scenario=config['samples'], scenarios=config['scenarios'],
                  session=config['session'], blender=bpy.app.version_string,
                  blender_build=bpy.app.build_hash.decode(),
                  backend=config.get('backend', 'cpu'), threads=threads,
                  cpu_affinity=config.get('cpu_affinity'), engine=engine,
                  compositor_device=compositor_device,
                  contract='Synthetic displayed preview: accepted setting → native render → '
                           'in-memory Viewer readback → preview texture upload → matched POST_PIXEL framebuffer readback.',
                  limitations=['Not automatic Shader viewport evaluation, Next UI, or physical frame presentation.',
                               'Readback synchronizes GPU work and tracer overhead is included.',
                               'Independent reference probes are computed before acceptance; native comparison and image hashes are inside readback time.',
                               'Ordinary samples wait for a matching draw; the explicit burst records accepted/superseded occurrences.',
                               'Quantiles describe recorded samples; no performance threshold or population confidence is claimed.'],
                  initialization={'python_import_seconds': time.perf_counter()-imports_started},
                  samples=[], completed=False)
    report['native_evaluation_backend'] = (
        ('Eevee / software OpenGL' if software_gpu else 'Cycles CPU, one sample')
        if config['context'] == 'shader' else
        ('GPU Compositor / full precision' if software_gpu else 'CPU Compositor, full precision'))

    def unexpected_audit(*args, **kwargs):
        raise AssertionError('Production GUI preparation called a dense audit or table-resolution search')
    forbidden = {tables: ('audit_table', 'audit_tone', 'select_table', 'build_table', '_probes'),
                 color_prepare: ('audit_color', '_audit_field', '_table_probes', '_build_field')}
    for module, names in forbidden.items():
        for name in names:
            if hasattr(module, name):
                setattr(module, name, unexpected_audit)
    report['runtime_audit_tripwires'] = [module.__name__+'.'+name for module, names in forbidden.items()
                                       for name in names if hasattr(module, name)]

    def stamp():
        return time.perf_counter()-started

    def save():
        report['summary'] = summarize_samples(report['samples'])
        output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')

    @contextmanager
    def phase(destination, name):
        begin = time.perf_counter()
        try:
            yield
        finally:
            destination[name] = time.perf_counter()-begin

    with phase(report['initialization'], 'context_preparation_seconds'):
        context = prepare()
    with phase(report['initialization'], 'boundary_loading_seconds'):
        boundary = prepare_boundary(context.fl, context.aw, context.gamma)
    with phase(report['initialization'], 'preparation_seconds'):
        prepared = prepare(full_fields=True, boundary=boundary)
    values = cases.rgba(config['size']**2)
    with phase(report['initialization'], 'native_fixture_seconds'):
        fixture = NativeFixture(prepared, values, config['context'], engine=engine,
                                device=compositor_device, threads=threads,
                                builder=build_persistent)
        if config['context'] == 'shader' and software_gpu and not fixture.split_aov:
            raise RuntimeError('Software-GPU Shader evaluation requires the Eevee float32 split-AOV path')
        if config['context'] == 'shader' and software_gpu:
            high = next(node for node in fixture.comp.nodes
                        if node.bl_idname == 'NodeGroupOutput').inputs['Image'].links[0].from_socket
            low = fixture.color_low
            exponent = fixture.color_exponent
            nodes = fixture.comp.nodes
            links = fixture.comp.links
            split_high = nodes.new('ShaderNodeSeparateXYZ')
            split_low = nodes.new('ShaderNodeSeparateXYZ')
            split_exponent = nodes.new('ShaderNodeSeparateXYZ')
            links.new(high, split_high.inputs[0])
            links.new(low, split_low.inputs[0])
            links.new(exponent, split_exponent.inputs[0])
            reconstructed = []
            for index in range(3):
                low_scaled = nodes.new('ShaderNodeMath')
                low_scaled.operation = 'DIVIDE'
                links.new(split_low.outputs[index], low_scaled.inputs[0])
                low_scaled.inputs[1].default_value = 1024.
                mantissa = nodes.new('ShaderNodeMath')
                mantissa.operation = 'ADD'
                links.new(split_high.outputs[index], mantissa.inputs[0])
                links.new(low_scaled.outputs[0], mantissa.inputs[1])
                exponent_scaled = nodes.new('ShaderNodeMath')
                exponent_scaled.operation = 'SUBTRACT'
                links.new(split_exponent.outputs[index], exponent_scaled.inputs[0])
                exponent_scaled.inputs[1].default_value = 10.
                scale = nodes.new('ShaderNodeMath')
                scale.operation = 'POWER'
                scale.inputs[0].default_value = 2.
                links.new(exponent_scaled.outputs[0], scale.inputs[1])
                channel = nodes.new('ShaderNodeMath')
                channel.operation = 'MULTIPLY'
                links.new(mantissa.outputs[0], channel.inputs[0])
                links.new(scale.outputs[0], channel.inputs[1])
                reconstructed.append(channel.outputs[0])
            combine = nodes.new('ShaderNodeCombineXYZ')
            for socket, channel_socket in zip(combine.inputs, reconstructed):
                links.new(channel_socket, socket)
            sink = next(node for node in nodes if node.bl_idname == 'NodeGroupOutput')
            for link in tuple(sink.inputs['Image'].links):
                links.remove(link)
            links.new(combine.outputs[0], sink.inputs['Image'])
        for node in tuple(fixture.comp.nodes):
            if node.bl_idname == 'CompositorNodeOutputFile':
                fixture.comp.nodes.remove(node)
        sink = next(node for node in fixture.comp.nodes if node.bl_idname == 'NodeGroupOutput')
        viewer = fixture.comp.nodes.new('CompositorNodeViewer')
        fixture.comp.links.new(sink.inputs['Image'].links[0].from_socket, viewer.inputs['Image'])
        bpy.context.preferences.view.render_display_type = 'NONE'
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
    region = next(region for region in area.regions if region.type == 'WINDOW')
    report['display_renderer'] = gpu.platform.renderer_get()
    report['display_backend'] = gpu.platform.backend_type_get()
    report['display_vendor'] = gpu.platform.vendor_get()
    report['display_version'] = gpu.platform.version_get()
    report['compute_shader_support'] = gpu.capabilities.compute_shader_support_get()
    report['native_render_threads'] = fixture.scene.render.threads
    report['native_render_thread_mode'] = fixture.scene.render.threads_mode
    report['compositor_device'] = fixture.scene.render.compositor_device
    report['cpu_affinity'] = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    report['aov_transport'] = ('Split high/residual/exponent reconstructed in full-precision Compositor before Viewer; included in render timing'
                               if fixture.split_aov else 'Direct float32 Viewer')
    if software_gpu and 'llvmpipe' not in report['display_renderer'].lower():
        raise RuntimeError('Software-GPU run did not initialize Mesa llvmpipe')
    if software_gpu and not report['compute_shader_support']:
        raise RuntimeError('Software-GPU run requires compute shader support')
    report['graph'] = asdict(fixture.built.stats)
    report['initialization'].update({f'fixture_{name}': value
                                     for name, value in fixture.initialization_timings.items()})
    report['tree_pointer'] = int(fixture.built.tree.as_pointer())
    report['input_sha256'] = hashlib.sha256(values.tobytes()).hexdigest()
    texture = pending = None
    shader = gpu.shader.from_builtin('IMAGE')
    draw_size = min(config['size'], max(32, min(region.width-64, region.height-64)))
    origin = (24, 24)
    report['preview_surface'] = dict(origin=list(origin), size=[draw_size, draw_size],
                                    region_size=[region.width, region.height])
    batch = batch_for_shader(shader, 'TRI_FAN', {
        'pos': ((origin[0], origin[1]), (origin[0]+draw_size, origin[1]),
                (origin[0]+draw_size, origin[1]+draw_size), (origin[0], origin[1]+draw_size)),
        'texCoord': ((0, 0), (1, 0), (1, 1), (0, 1))})
    # Probe binary cells from the actual texture, plus an ordinary graded pixel.
    witness_cells = 16
    marker_height = max(2, config['size']//16)
    cell_width = config['size']//witness_cells
    # Pick a framebuffer pixel mapping near a source-texel center. The exact
    # center of an odd-size preview maps to UV=.5, which lies on a nearest-texel
    # boundary for an even source size and is sensitive to GPU coordinate roundoff.
    candidates = range(draw_size//3, max(draw_size//3+1, 2*draw_size//3))
    preview_probe = min(candidates, key=lambda coordinate:
                        abs(((coordinate+.5)*config['size']/draw_size)%1-.5))
    preview_probe_source = int((preview_probe+.5)*config['size']/draw_size)
    report['preview_surface']['probe_framebuffer_xy'] = [preview_probe]*2
    report['preview_surface']['probe_source_xy'] = [preview_probe_source]*2
    preview_expected = None
    failure = None
    prior_outputs = {}
    # Small independent witnesses are computed before sample acceptance; the
    # native result must match those settings before it can be drawn as current.
    reference_indices = np.unique(np.linspace(0, len(values)-1, 32, dtype=int))
    reference_expected = None
    reference_seconds = 0.

    def inventory():
        trees = []
        seen = set()
        def visit(tree):
            pointer = int(tree.as_pointer())
            if pointer in seen:
                return
            seen.add(pointer)
            trees.append(dict(pointer=pointer, nodes=sorted(int(node.as_pointer()) for node in tree.nodes)))
            for node in tree.nodes:
                child = getattr(node, 'node_tree', None)
                if child is not None:
                    visit(child)
        visit(fixture.built.tree)
        return dict(trees=trees, images=[dict(pointer=int(image.as_pointer()), size=list(image.size),
                    channels=image.channels, float_buffer=image.is_float, alpha=image.alpha_mode,
                    color_space=image.colorspace_settings.name, half=image.use_half_precision,
                    packed=bool(image.packed_file)) for image in fixture.built.images],
                    stats=asdict(count_nodes(fixture.built.tree, fixture.built.images)))
    initial_inventory = inventory()
    report['resource_inventory'] = initial_inventory

    def draw():
        nonlocal failure
        if bpy.context.area != area or texture is None or pending is None:
            return
        try:
            begin = time.perf_counter()
            previous_blend = gpu.state.blend_get()
            try:
                gpu.state.blend_set('NONE')
                shader.bind()
                shader.uniform_sampler('image', texture)
                batch.draw(shader)
                if 'draw' in pending:
                    return
                pixels = np.asarray(gpu.state.active_framebuffer_get().read_color(
                    origin[0], origin[1], draw_size, draw_size, 4, 0, 'FLOAT'))
            finally:
                gpu.state.blend_set(previous_blend)
            y = max(0, int(marker_height*.5/config['size']*draw_size))
            xs = [min(draw_size-1, int((index+.5)*cell_width/config['size']*draw_size))
                  for index in range(witness_cells)]
            observed = sum(int(pixels[y, x, 0]>.5)<<index for index, x in enumerate(xs))
            target = pending['sample_id']
            # Nearest filtered texture sample at a known interior source position.
            actual_color = pixels[preview_probe, preview_probe, :3]
            expected_color = preview_expected[preview_probe_source, preview_probe_source, :3]
            preview_matches = bool(np.allclose(actual_color, expected_color, atol=3/255., rtol=0))
            token_matches = observed == target
            if not token_matches or not preview_matches:
                raise AssertionError(dict(observed=observed, target=target,
                                          actual=actual_color.tolist(), expected=expected_color.tolist()))
            pending['phases']['draw_and_framebuffer_readback_seconds'] = time.perf_counter()-begin
            pending['draw'] = dict(sample_id=observed, revision=pending['revision'],
                                   at_seconds=stamp(), token_matches=token_matches,
                                   preview_matches=preview_matches,
                                   preview_max_error=float(np.max(abs(actual_color-expected_color))))
            pending['outcome'] = 'drawn'
        except BaseException:
            failure = traceback.format_exc()

    handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')

    def evaluate(row):
        nonlocal texture, preview_expected
        with phase(row['phases'], 'native_evaluation_seconds'):
            fixture.input_image.update()
            bpy.ops.render.render()
        with phase(row['phases'], 'native_readback_seconds'):
            image = bpy.data.images.get('Viewer Node')
            if image is None or tuple(image.size) != (config['size'], config['size']):
                raise RuntimeError('Native Viewer did not publish the expected image domain')
            pixels = np.empty(config['size']**2*4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            rgba = pixels.reshape(config['size'], config['size'], 4)
            if not np.isfinite(rgba).all():
                raise RuntimeError('Nonfinite native GUI preview')
            row['native_rgba_sha256'] = hashlib.sha256(pixels.tobytes()).hexdigest()
            if reference_expected is not None:
                observed = rgba.reshape(-1, 4)[reference_indices, :3].astype(float)
                normalized = np.max(abs(observed-reference_expected), axis=-1)/(1+np.max(abs(reference_expected), axis=-1))
                row['reference_probe_max_normalized_error'] = float(np.max(normalized))
                row['reference_probe_passed'] = row['reference_probe_max_normalized_error'] <= 1e-4
                # Preserve the acceptance failure, but finish the timing corpus
                # so a numerical mismatch cannot hide later scenarios.
            if 'settings' in row:
                key = json.dumps(row['settings'], sort_keys=True)
                previous = prior_outputs.setdefault(key, row['native_rgba_sha256'])
                row['same_settings_deterministic'] = previous == row['native_rgba_sha256']
                if not row['same_settings_deterministic']:
                    raise AssertionError('A/B/A or reset returned a different native output for identical settings')
        with phase(row['phases'], 'preview_texture_seconds'):
            # This simple display map is part of the fixture only; grading output
            # remains the native float result recorded above.
            preview_expected = np.ones_like(rgba)
            positive = np.maximum(rgba[..., :3], 0)
            preview_expected[..., :3] = positive/(1+positive)
            for index in range(witness_cells):
                preview_expected[:marker_height, index*cell_width:(index+1)*cell_width, :3] = (row['sample_id']>>index)&1
            texture = gpu.types.GPUTexture((config['size'], config['size']), format='RGBA32F',
                       data=gpu.types.Buffer('FLOAT', preview_expected.shape, preview_expected))
            texture.filter_mode(False)
        row['published_seconds'] = stamp()
        area.tag_redraw()

    sequence = iter((name, index) for name in config['scenarios'] for index in range(config['samples']))
    next_id = 1
    warmed = False
    active_families = set()
    previously_activated = set()

    def accept(name, index):
        nonlocal next_id
        settings = settings_for(name, index, config['samples'])
        row = dict(sample_id=next_id, session=config['session'], scenario=name, index=index,
                   scenario_entry=index == 0, accepted_seconds=stamp(),
                   settings=asdict(settings), phases={}, outcome='pending')
        next_id += 1
        report['samples'].append(row)
        return row, settings

    def advance():
        nonlocal pending, prepared, next_id, texture, warmed, reference_expected, reference_seconds, active_families
        try:
            if failure:
                raise RuntimeError(failure)
            if stamp() > config['timeout']:
                raise TimeoutError('GUI drag session exceeded configured timeout')
            if not warmed and pending is None:
                pending = dict(sample_id=65535, revision=fixture.built.revision,
                               phases={}, accepted_seconds=stamp())
                evaluate(pending)
                return .01
            if pending is not None and 'draw' not in pending:
                if stamp()-pending['published_seconds'] > 30:
                    raise TimeoutError('No matching actual GUI draw within 30 seconds')
                area.tag_redraw()
                return .01
            if pending is not None:
                if not warmed:
                    if software_gpu and Path('/proc/self/task').is_dir():
                        names = []
                        for path in Path('/proc/self/task').glob('*/comm'):
                            try:
                                names.append(path.read_text().strip())
                            except FileNotFoundError:
                                pass
                        raster = sorted(name for name in names if name.startswith('llvmpipe-'))
                        report['software_gpu_threads'] = dict(
                            requested=os.environ.get('LP_NUM_THREADS'),
                            mesa_25_0_7_max_threads_per_pool=32,
                            observed_raster_thread_names=raster,
                            observed_raster_thread_count=len(raster),
                            observed_process_thread_count=len(names),
                            note='Mesa caps each raster/compute worker pool at 32; process threads are not compute concurrency.')
                    report['initialization'].update({f'cold_{name}': value for name, value in pending['phases'].items()})
                    report['initialization']['cold_evaluation_to_draw_seconds'] = pending['draw']['at_seconds']-pending['accepted_seconds']
                    report['initialization']['total_seconds'] = stamp()
                    report['initialization_draw'] = pending['draw']
                    warmed = True
                save()
            try:
                name, index = next(sequence)
            except StopIteration:
                report['completed'] = True
                report['duration_seconds'] = stamp()
                report['graph_after'] = asdict(count_nodes(fixture.built.tree, fixture.built.images))
                report['resource_inventory_preserved'] = inventory() == initial_inventory
                report['reference_probe_limit'] = 1e-4
                report['reference_probe_failures'] = [row['sample_id'] for row in report['samples']
                    if row.get('reference_probe_passed') is False]
                report['numerical_passed'] = not report['reference_probe_failures']
                report['correctness_passed'] = (report['resource_inventory_preserved'] and report['numerical_passed'])
                save()
                bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
                texture = None
                bpy.ops.wm.quit_blender()
                return None
            settings = settings_for(name, index, config['samples'])
            if name == 'burst_exposure':
                settings = replace(settings, linear=replace(settings.linear, exposure=settings.linear.exposure+.02))
            reference_start = time.perf_counter()
            reference_expected = oracle.evaluate_full(values[reference_indices, :3], settings.linear,
                                                       settings.tone, settings.color, settings.space)['rgb']
            reference_seconds = time.perf_counter()-reference_start
            pending, settings = accept(name, index)
            if name == 'burst_exposure':
                # Three accepted occurrences arrive before native installation.
                # Only the most recent occurrence may complete a current draw.
                for offset in (1, 2):
                    pending['outcome'] = 'superseded'
                    pending['superseded_seconds'] = stamp()
                    pending, settings = accept(name, index)
                    settings = replace(settings, linear=replace(settings.linear,
                                       exposure=settings.linear.exposure+.01*offset))
                    pending['settings'] = asdict(settings)
            pending['untimed_reference_probe_seconds'] = reference_seconds
            pending['reference_probe_indices'] = reference_indices.tolist()
            with phase(pending['phases'], 'preparation_seconds'):
                prepared = prepare_update(settings, prepared)
            from color_tools.kernel.settings import LinearSettings
            families = set()
            if settings.linear != LinearSettings():
                families.add('linear')
            if prepared.tone.active:
                families.add('tone')
            for field in ('lightness', 'chroma', 'adaptance'):
                if any(value != 0 for row in getattr(settings.color, field) for value in row):
                    families.add(field)
            if settings.color.global_gain != 0:
                families.add('global_gain')
            for field in ('log_chroma', 'hue_degrees', 'log_scale'):
                if any(value != 0 for row in getattr(settings.color.web, field) for value in row):
                    families.add('web_'+field)
            pending['active_families'] = sorted(families)
            pending['newly_active_families'] = sorted(families-active_families)
            pending['first_activation_families'] = sorted(families-previously_activated)
            with phase(pending['phases'], 'native_install_seconds'):
                pending['apply_receipt'] = fixture.built.apply(prepared, expected_revision=fixture.built.revision)
            active_families = families
            previously_activated.update(families)
            pending['phases'].update({f'install_{name}_seconds': value
                                      for name, value in pending['apply_receipt'].get('phase_seconds', {}).items()})
            pending['resource_inventory_preserved'] = inventory() == initial_inventory
            if not pending['resource_inventory_preserved']:
                raise AssertionError('Native grade resource identity/layout changed during an update')
            pending['revision'] = fixture.built.revision
            pending['installed_seconds'] = stamp()
            evaluate(pending)
            return .01
        except BaseException:
            report['error'] = traceback.format_exc()
            if pending is not None:
                pending['outcome'] = 'failed'
            save()
            print(report['error'], file=sys.stderr, flush=True)
            bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
            bpy.ops.wm.quit_blender()
            return None

    save()
    bpy.app.timers.register(advance, first_interval=.5)


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--')+1:])
