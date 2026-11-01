"""Disposable factory-startup Blender fixture; never runs in the user's project.

Fresh-object RNA scalars here are an oracle for the external native adapter.
The production recorder never performs these probes. Nothing saves a project.
"""
import json
import os
from pathlib import Path
import signal
import bpy

root = Path(os.environ['PG_UNDO_TRACE_CANARY_DIR'])
root.mkdir(parents=True, exist_ok=True)
oracle = root / 'oracle.jsonl'


def emit(event, **fields):
    with oracle.open('a') as stream:
        stream.write(json.dumps(dict(event=event, **fields)) + '\n')
        stream.flush()


def identity(value):
    if value is None:
        return dict(pointer=0, name=None, uid=None)
    return dict(pointer=value.as_pointer(), name=value.name, uid=value.session_uid)


def assignments():
    for kind, tree_kind, node_kind in (
            ('shader', 'ShaderNodeTree', 'ShaderNodeTexImage'),
            ('compositor', 'CompositorNodeTree', 'CompositorNodeImage')):
        tree = bpy.data.node_groups.new('PG native canary ' + kind, tree_kind)
        nodes = [tree.nodes.new(node_kind), tree.nodes.new(node_kind)]
        images = [bpy.data.images.new('PG native canary ' + kind + suffix, 2, 2)
                  for suffix in (' A', ' B')]
        for node in nodes:
            old = None
            for new in (images[0], images[1], None):
                emit('setter_expected', kind=kind, node=node.as_pointer(), node_name=node.name,
                     tree=identity(tree), old=identity(old), new=identity(new))
                node.image = new
                emit('setter_completed', node=node.as_pointer(), new=identity(new))
                old = new
        for image in images:
            emit('delete_expected', image=identity(image))
            bpy.data.images.remove(image)
        # Keep the ordinary trees in undo snapshots; no local wrapper crosses undo.
    emit('assignments_completed')


emit('build', build=bpy.app.build_hash.decode(), version=list(bpy.app.version))
assignments()
bpy.ops.ed.undo_push(message='PG canary initial')
bpy.context.scene.frame_start = 2
bpy.ops.ed.undo_push(message='PG canary changed')
bpy.ops.ed.undo()
bpy.ops.ed.redo()
emit('undo_completed')
# Intentionally stop alive, so the host can query the deleted Image histories.
os.kill(os.getpid(), signal.SIGSTOP)
