"""Test-owned protocol peer; never registered as a production job handler."""
import json
import os
from pathlib import Path
import socket
import sys
import time


def lease_owner(mode, root, ready):
    from color_tools.blender_runtime.execution.journal import Lease, Session
    value = Session(root) if mode == 'owner' else Lease(Path(root) / 'lease')
    path = value.path if mode == 'owner' else Path(root)
    if mode == 'owner':
        (path / 'abandoned-payload').write_bytes(b'owned temporary data')
    Path(ready).write_text(str(path))
    while True:
        time.sleep(1)


def helper(config_path, mode):
    config = json.loads(Path(config_path).read_text())
    if mode == 'no_hello':
        time.sleep(60)
        return
    from color_tools.blender_runtime.execution.contracts import PROTOCOL
    from color_tools.blender_runtime.execution.journal import Lease
    from color_tools.blender_runtime.execution.payloads import PayloadStore
    from color_tools.blender_runtime.execution.transport import Channel
    lease = Lease(Path(config['directory']) / 'lease')
    store = PayloadStore(config['directory'])
    sock = socket.create_connection(tuple(config['address']), timeout=5)
    channel = Channel(sock)
    def send(kind, **values):
        channel.send(dict(kind=kind, session=config['session'], generation=config['generation'], **values))
    send('hello', protocol=PROTOCOL, token=config['token'],
         fingerprint='incorrect-build' if mode == 'bad_hello' else config['fingerprint'])
    active = None
    stopping = False
    receipts = Path(config['directory']) / ('fixture-' + config['role'] + '.jsonl')
    try:
        while True:
            for message in channel.pump():
                kind = message['kind']
                if kind == 'shutdown':
                    if active is None or not active['inputs'].get('hang'):
                        stopping = True
                elif kind == 'cancel' and active and message['attempt'] == active['attempt']:
                    active['cancelled'] = True
                elif kind == 'run':
                    if active is not None:
                        raise AssertionError('Two jobs dispatched to one physical helper')
                    inputs = store.decode(message['inputs'], copy=True)
                    probe = message['operation'] in ('gpu_probe', 'scope_probe')
                    if probe:
                        inputs['probe'] = True
                        if mode == 'probe_gate':inputs['gate'] = str(Path(config['directory']) / 'probe-release')
                        if mode == 'probe_stale':inputs['stale'] = True
                    active = dict(attempt=message['attempt'], inputs=inputs, cancelled=False)
                    with receipts.open('a') as stream:
                        stream.write(json.dumps(dict(attempt=message['attempt'], generation=config['generation'],
                                                     pid=os.getpid(), operation=message['operation'],
                                                     value=inputs.get('label'))) + '\n')
                    if inputs.get('crash') or inputs.get('crash_first') and config['generation'] == 1:
                        os._exit(31)
                    if inputs.get('stale'):
                        channel.send(dict(kind='complete', session=config['session'],
                            generation=config['generation'] - 1, attempt=message['attempt'], value='wrong generation'))
                        send('complete', attempt=message['attempt'] - 1, value='wrong attempt')
                    send('progress', attempt=message['attempt'], value=.25)
                    for index in range(1, inputs.get('stream', 0) + 1):
                        send('progress', attempt=message['attempt'], value=index / 100)
                        send('preview', attempt=message['attempt'],
                             value=store.encode({'preview': index}, []))
            if stopping and not channel.outgoing:
                return
            if active is not None:
                inputs = active['inputs']
                gate = inputs.get('gate')
                ready = not inputs.get('hang') and (gate is None or Path(gate).exists())
                if ready:
                    attempt = active['attempt']
                    if active['cancelled'] or inputs.get('cancel_receipt'):
                        send('cancelled', attempt=attempt)
                    elif (inputs.get('fail') or inputs.get('fail_gpu') and config['role'] in ('gpu', 'scope_gpu')
                          or inputs.get('probe') and mode == 'probe_fail'):
                        send('failed', attempt=attempt, error='Fixture computation failure',
                             traceback='Fixture traceback\n' + 'full traceback detail\n' * (400 if inputs.get('long_trace') else 1),
                             diagnostic=dict(backend='METAL',device='Fixture device'))
                    elif inputs.get('malformed_first') and config['generation'] == 1:
                        send('complete', attempt=attempt, value={'$invalid': True}, files=[])
                        # The real runtime must terminate this helper before retrying.
                    else:
                        value = dict(value=inputs.get('value'), role=config['role'],
                                     generation=config['generation'], pid=os.getpid())
                        if inputs.get('probe'):
                            value.update(conformance=mode != 'probe_invalid', backend='GPU',device='Fixture device')
                        files = []
                        send('complete', attempt=attempt, value=store.encode(value, files), files=files)
                    active = None
            time.sleep(.001)
    finally:
        channel.close()
        lease.close()


if __name__ == '__main__':
    if sys.argv[1] in ('owner', 'lease'):
        lease_owner(*sys.argv[1:])
    else:
        helper(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'normal')
