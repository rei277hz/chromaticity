"""Disposable native undo experiment: no extension and no user project."""
import bpy
import json
import sys

mode = sys.argv[sys.argv.index('--') + 1]


def emit(event, **fields):
    print('PG_PUBLICATION_PROBE ' + json.dumps(dict(event=event, mode=mode, **fields)), flush=True)


def setup():
    tree = bpy.data.node_groups.new('Probe Kernel', 'ShaderNodeTree')
    tree.use_fake_user = True
    image = bpy.data.images.new('Probe Original', 4, 4, float_buffer=True)
    alternate = bpy.data.images.new('Probe Alternate', 4, 4, float_buffer=True)
    for _ in range(4):
        tree.nodes.new('ShaderNodeTexImage').image = image
    emit('setup', kernel=tree.as_pointer(), image=image.as_pointer(),
         alternate=alternate.as_pointer())


def publication():
    tree = bpy.data.node_groups['Probe Kernel']
    if mode == 'pixels':
        image = bpy.data.images['Probe Original']
        image.pixels.foreach_set([.25] * 64)
        image.update()
    else:
        if mode == 'existing':
            image = bpy.data.images['Probe Alternate']
        else:
            image = bpy.data.images.new('Probe Published', 4, 4, float_buffer=True)
            if mode == 'fake_user':
                image.use_fake_user = True
        for node in tree.nodes:
            node.image = image
    emit('published', kernel=tree.as_pointer(), image=image.as_pointer(),
         users=image.users, fake_user=image.use_fake_user)


def observe(stage):
    images = {image.as_pointer(): image.name for image in bpy.data.images}
    tree = bpy.data.node_groups['Probe Kernel']
    emit('before_links', stage=stage, kernel=tree.as_pointer(), images=images)
    pointers = []
    for index, node in enumerate(tree.nodes):
        # This is deliberately isolated in a disposable process: a stale native
        # link can fault at the getter itself, before any Python validity check.
        emit('before_node_getter', stage=stage, index=index)
        image = node.image
        emit('after_node_getter', stage=stage, index=index, is_none=image is None)
        pointer = image.as_pointer() if image is not None else 0
        emit('after_pointer', stage=stage, index=index, pointer=pointer)
        pointers.append(pointer)
    emit('links', stage=stage, pointers=pointers,
         valid=all(pointer in images for pointer in pointers))


emit('build', version=list(bpy.app.version), build=bpy.app.build_hash.decode())
bpy.context.preferences.edit.use_global_undo = True
setup()
for value in (0, 1, 2):
    bpy.context.scene['probe_control'] = value
    bpy.ops.ed.undo_push(message='Probe ' + str(value))
    emit('snapshot', value=value)
publication()
if mode == 'snapshot':
    bpy.ops.ed.undo_push(message='Published Image')
observe('before undo')
for operation in ('undo', 'redo', 'undo', 'undo', 'redo', 'redo'):
    emit('operation', operation=operation)
    result = getattr(bpy.ops.ed, operation)()
    emit('operation_returned', operation=operation, result=sorted(result),
         scene_value=bpy.context.scene.get('probe_control'))
    observe(operation)
emit('complete')
