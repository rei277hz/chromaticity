"""Short native premises; no extension, numerical jobs, GPU or GUI automation."""
import json
import sys
import bpy

mode = sys.argv[sys.argv.index('--') + 1]
bpy.context.preferences.edit.use_global_undo = True
for value in (0, 1, 2):
    bpy.context.scene['pg_contract_value'] = value
    bpy.ops.ed.undo_push(message='Ownership contract ' + str(value))
events = []


def record(name):
    events.append([name, int(bpy.context.scene['pg_contract_value'])])


if mode == 'failure':
    def pre(*_args):
        record('pre_failed')
        raise RuntimeError('EXPECTED_PRE_ERROR')

    def pre_next(*_args):
        record('pre_next')

    def post(*_args):
        record('post_failed')
        raise RuntimeError('EXPECTED_POST_ERROR')

    def post_next(*_args):
        record('post_next')

    bpy.app.handlers.undo_pre.extend((pre, pre_next))
    bpy.app.handlers.undo_post.extend((post, post_next))
elif mode == 'reentrant_pre':
    nested = False

    def pre(*_args):
        global nested
        record('pre_enter')
        if not nested:
            nested = True
            events.append(['nested_result', sorted(bpy.ops.ed.undo())])
        record('pre_leave')

    def post(*_args):
        record('post')

    bpy.app.handlers.undo_pre.append(pre)
    bpy.app.handlers.undo_post.append(post)
else:
    nested = False

    def pre(*_args):
        record('pre')

    def post(*_args):
        global nested
        record('post_enter')
        if not nested:
            nested = True
            events.append(['nested_result', sorted(bpy.ops.ed.undo())])
        record('post_leave')

    bpy.app.handlers.undo_pre.append(pre)
    bpy.app.handlers.undo_post.append(post)
record('before')
result = bpy.ops.ed.undo()
record('after')
print('PG_UNDO_CONTRACT ' + json.dumps(dict(
    version=list(bpy.app.version), build=bpy.app.build_hash.decode(), mode=mode,
    result=sorted(result), events=events, last_exception=hasattr(sys, 'last_exc'))), flush=True)
bpy.app.handlers.undo_pre.clear()
bpy.app.handlers.undo_post.clear()
