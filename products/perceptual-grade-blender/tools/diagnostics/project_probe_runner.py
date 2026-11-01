"""Read a project in native Blender without saving or decoding image pixels.

Invoked by the isolated Buck launcher with arguments after ``--``:
repository report_path blend_path. The repository contains the installed
``perceptual_grade`` package. A flushed JSONL phase log accompanies the report,
so the last native operation remains identifiable even after a process crash.
"""
from collections import Counter
from datetime import datetime
import faulthandler
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

import addon_utils
import bpy


def text(value):
    if isinstance(value,bytes):return value.decode('utf8',errors='replace')
    return ''.join((str(value),''))


def identity(value):
    if value is None:return None
    library=getattr(value,'library',None)
    return dict(name=text(getattr(value,'name','')),type=text(value.bl_rna.identifier),
                library=None if library is None else text(library.filepath))


def scalar(value,depth=0):
    """Copy saved metadata into JSON values; never keep RNA in the report."""
    if value is None or type(value) in (str,bool,int):return value
    if type(value) is float:return value if math.isfinite(value) else text(value)
    if isinstance(value,bpy.types.ID):return {'id':identity(value)}
    if depth>=8:return {'omitted_type':type(value).__name__}
    if type(value) in (tuple,list):
        return [scalar(item,depth+1) for item in value[:256]]
    if type(value) is dict:
        return {text(key):scalar(item,depth+1) for key,item in value.items()}
    if type(value).__name__=='IDPropertyGroup':
        return {text(key):scalar(value[key],depth+1) for key in value.keys()}
    if type(value).__name__=='IDPropertyArray':
        return [scalar(item,depth+1) for item in value[:256]]
    return {'omitted_type':type(value).__name__}


def read(function):
    try:return scalar(function())
    except Exception as error:return {'error':type(error).__name__+': '+text(error)}


def flags(value):
    result={}
    for key in value.keys():
        if key.startswith(('_pg_','_perceptual_grade')) or key in (
                'pg_grade','pg_stack_entries','pg_tone','pg_chromatic','pg_linear'):
            result[text(key)]=read(lambda:value[key])
    return result


def image_info(image):
    if image is None:return None
    return dict(identity=identity(image),source=text(image.source),filepath=text(image.filepath),
                size=[int(value) for value in image.size],channels=int(image.channels),
                has_data=bool(image.has_data),is_dirty=bool(image.is_dirty),
                is_float=bool(image.is_float),packed=bool(image.packed_file),
                packed_files=read(lambda:len(image.packed_files)),
                colorspace=text(image.colorspace_settings.name),alpha_mode=text(image.alpha_mode),
                flags=flags(image))


def kernel_info(tree):
    if tree is None:return None
    types=Counter();images=[];addresses=[]
    for node in tree.nodes:
        types[text(node.bl_idname)]+=1
        if node.get('_pg_cube_image'):
            images.append(dict(node=text(node.name),image=image_info(getattr(node,'image',None))))
        if node.get('_pg_cube_address'):
            addresses.append(dict(node=text(node.name),tree=identity(getattr(node,'node_tree',None))))
    return dict(identity=identity(tree),flags=flags(tree),node_count=len(tree.nodes),
                node_types=dict(types),images=images,address_helpers=addresses)


def relevant(node):
    return (text(node.bl_idname).startswith('PG')
            or any(key.startswith(('_pg_','_perceptual_grade')) for key in node.keys()))


def node_info(node):
    result=dict(name=text(node.name),label=text(node.label),bl_idname=text(node.bl_idname),
                type=text(node.type),selected=bool(node.select),flags=flags(node),
                grade=identity(getattr(node,'pg_grade',None)),
                kernel=kernel_info(getattr(node,'node_tree',None)),stack_entries=[])
    result['lut_endpoints']={name:read(lambda:tuple(node.inputs[name].default_value))
                            for name in ('Scene to LUT R','Scene to LUT G','Scene to LUT B',
                                         'LUT to Scene R','LUT to Scene G','LUT to Scene B')
                            if name in node.inputs}
    for entry in getattr(node,'pg_stack_entries',()):
        result['stack_entries'].append(dict(grade=identity(entry.grade),enabled=bool(entry.enabled),
            direction=text(entry.direction),key=text(entry.key)))
    return result


def node_trees():
    # This synchronous iterator is always exhausted before another open/enable.
    seen=set()
    for tree in bpy.data.node_groups:
        seen.add(int(tree.as_pointer()));yield tree
    for collection in (bpy.data.materials,bpy.data.worlds,bpy.data.lights,bpy.data.scenes):
        for owner in collection:
            for attribute in ('node_tree','compositing_node_group'):
                tree=getattr(owner,attribute,None)
                if tree is not None and int(tree.as_pointer()) not in seen:
                    seen.add(int(tree.as_pointer()));yield tree


def tree_owners():
    """Resolve same-named embedded trees to scalar datablock descriptions."""
    owners={}
    for kind in ('materials','worlds','lights','scenes'):
        for owner in getattr(bpy.data,kind):
            for attribute in ('node_tree','compositing_node_group'):
                tree=getattr(owner,attribute,None)
                if tree is not None:
                    owners.setdefault(int(tree.as_pointer()),[]).append(
                        dict(collection=kind,owner=identity(owner),attribute=attribute))
    return owners


def strip_info(strip,depth=0):
    result=dict(name=text(strip.name),type=text(strip.type),action=identity(getattr(strip,'action',None)),
                mute=bool(strip.mute),frame_start=float(strip.frame_start),frame_end=float(strip.frame_end))
    if depth<32:result['strips']=[strip_info(child,depth+1) for child in getattr(strip,'strips',())]
    else:result['nested_strips_omitted']=True
    return result


def animation_info(owner):
    animation=getattr(owner,'animation_data',None)
    if animation is None:return None
    return dict(owner=identity(owner),action=identity(animation.action),
                drivers=[dict(path=text(curve.data_path),index=int(curve.array_index),mute=bool(curve.mute))
                         for curve in animation.drivers],
                nla_tracks=[dict(name=text(track.name),mute=bool(track.mute),
                                 strips=[strip_info(strip) for strip in track.strips])
                            for track in animation.nla_tracks])


def animation_summary():
    actions=[]
    for action in bpy.data.actions:
        curves=[]
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip,'channelbags',()):
                    for curve in bag.fcurves:
                        curves.append(dict(path=text(curve.data_path),index=int(curve.array_index),
                                           keyframes=len(curve.keyframe_points),mute=bool(curve.mute)))
        actions.append(dict(identity=identity(action),users=int(action.users),
                            slots=len(action.slots),curve_count=len(curves),curves=curves))
    owners=[];seen=set()
    for prop in bpy.data.bl_rna.properties:
        if prop.type!='COLLECTION':continue
        for owner in getattr(bpy.data,prop.identifier):
            if not isinstance(owner,bpy.types.ID):continue
            key=int(owner.as_pointer())
            if key in seen:continue
            seen.add(key)
            item=animation_info(owner)
            if item is not None:owners.append(item)
    return dict(action_count=len(actions),actions=actions,owners=owners)


def editor_summary():
    editors=[]
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type!='NODE_EDITOR':continue
            space=area.spaces.active
            tree=getattr(space,'edit_tree',None) or getattr(space,'node_tree',None)
            editors.append(dict(screen=text(screen.name),tree_type=text(space.tree_type),
                shader_type=text(getattr(space,'shader_type','')),pin=bool(space.pin),tree=identity(tree),
                active_node=None if tree is None or tree.nodes.active is None else text(tree.nodes.active.name),
                selected_nodes=[] if tree is None else [text(node.name) for node in tree.nodes if node.select]))
    return editors


class Report:
    def __init__(self,path,project):
        self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
        self.phase_path=self.path.with_suffix('.phases.jsonl')
        self.data=dict(passed=False,project=str(project),blender=list(bpy.app.version),
            blender_version=bpy.app.version_string,build_hash=text(bpy.app.build_hash),
            build_date=text(bpy.app.build_commit_date),build_time=text(bpy.app.build_commit_time),
            binary=bpy.app.binary_path,pid=os.getpid(),background=bool(bpy.app.background),
            snapshots=[],events=[])

    def save(self):
        temporary=self.path.with_suffix('.writing')
        with temporary.open('w',encoding='utf8') as stream:
            json.dump(self.data,stream,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,self.path)

    def phase(self,event_name,**values):
        event=dict(phase=event_name,at=datetime.now().astimezone().isoformat(),perf_counter=time.perf_counter(),**values)
        self.data['events'].append(event)
        with self.phase_path.open('a',encoding='utf8') as stream:
            stream.write(json.dumps(event,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
        self.save();print('PG project probe:',json.dumps(event),flush=True)

    def snapshot(self,label):
        self.phase('snapshot.begin',label=label)
        owners=tree_owners()
        snapshot=dict(label=label,filepath=text(bpy.data.filepath),is_dirty=bool(bpy.data.is_dirty),
                      scene_space=read(lambda:bpy.data.colorspace.working_space),
                      working_space_interop_id=read(lambda:bpy.data.colorspace.working_space_interop_id),
                      scenes=[],trees=[],editors=editor_summary())
        self.data['snapshots'].append(snapshot)
        for scene in bpy.data.scenes:
            snapshot['scenes'].append(dict(identity=identity(scene),render_engine=text(scene.render.engine),
                frame=int(scene.frame_current),view_transform=text(scene.view_settings.view_transform),
                look=text(scene.view_settings.look),display_device=text(scene.display_settings.display_device),
                exposure=float(scene.view_settings.exposure),gamma=float(scene.view_settings.gamma)))
        for tree in node_trees():
            info=dict(identity=identity(tree),owners=owners.get(int(tree.as_pointer()),[]),
                      flags=flags(tree),node_count=len(tree.nodes),
                      active_node=None if tree.nodes.active is None else text(tree.nodes.active.name),nodes=[])
            for node in tree.nodes:
                if relevant(node):
                    self.phase('snapshot.node',label=label,tree=text(tree.name),node=text(node.name),kind=text(node.bl_idname))
                    info['nodes'].append(node_info(node))
            if info['nodes'] or info['flags']:snapshot['trees'].append(info)
        self.phase('snapshot.animation.begin',label=label)
        snapshot['animation']=animation_summary()
        self.phase('snapshot.complete',label=label,trees=len(snapshot['trees']))


def main(repository,report_path,blend_path):
    faulthandler.enable(all_threads=True)
    repository=Path(repository).resolve();project=Path(blend_path).resolve()
    package=repository/'perceptual_grade';report=Report(report_path,project)
    name='bl_ext.pg_probe.perceptual_grade';enabled=False
    original=project.stat();report.data['original_stat']=dict(size=original.st_size,mtime_ns=original.st_mtime_ns)
    try:
        if tuple(bpy.app.version)!=(5,2,2):raise RuntimeError('The probe requires native Blender 5.2.2')
        if not bpy.app.binary_path or not bpy.app.background:raise RuntimeError('The probe requires native background Blender')
        bpy.context.preferences.filepaths.use_scripts_auto_execute=False
        report.phase('raw.open.begin')
        bpy.ops.wm.open_mainfile(filepath=str(project),use_scripts=False,load_ui=True)
        report.phase('raw.open.complete')
        report.snapshot('before_extension_enable')
        report.phase('extension.enable.begin',package=str(package))
        bpy.context.preferences.extensions.repos.new(name='PG project probe',module='pg_probe',custom_directory=str(repository))
        errors=[]
        def enable_error(error):errors.append(type(error).__name__+': '+text(error))
        addon=addon_utils.enable(name,default_set=False,handle_error=enable_error)
        if addon is None or errors:raise RuntimeError('Extension enable failed: '+json.dumps(errors))
        enabled=True
        if Path(addon.__file__).resolve()!=package/'__init__.py':raise RuntimeError('Extension was not loaded from the isolated repository')
        report.phase('extension.enable.complete')
        report.snapshot('after_extension_enable')
        report.phase('registered.open.begin')
        bpy.ops.wm.open_mainfile(filepath=str(project),use_scripts=False,load_ui=True)
        report.phase('registered.open.complete')
        report.snapshot('after_registered_project_load')
        report.phase('extension.disable.begin')
        addon_utils.disable(name,default_set=False)
        enabled=False
        report.phase('extension.disable.complete')
        after=project.stat()
        report.data['original_unchanged']=(original.st_size,original.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
        if not report.data['original_unchanged']:raise RuntimeError('Original project metadata changed during probe')
        report.data['passed']=True
        report.phase('complete')
    except BaseException as error:
        report.data['error']=dict(type=type(error).__name__,message=text(error),traceback=traceback.format_exc())
        report.phase('failed')
        raise
    finally:
        if enabled:
            report.phase('failure_cleanup.begin')
            addon_utils.disable(name,default_set=False)
            report.phase('failure_cleanup.complete')


if __name__=='__main__':
    main(*sys.argv[sys.argv.index('--')+1:])
