"""Small real actions for execution, isolation, concurrency and cache validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    start = time.time()
    home = Path.home()
    with tempfile.TemporaryDirectory(prefix='re-probe-') as directory:
        path = Path(directory) / 'data'
        path.write_bytes(b'NativeLink probe\n')
        assert path.read_bytes() == b'NativeLink probe\n'
        temporary_root = str(Path(directory).parent)
    # Enough CPU work to expose overlapping execution in a multi-action build.
    digest = hashlib.sha256()
    block = bytes(1024 * 1024)
    until = time.process_time() + 0.25
    while time.process_time() < until:
        digest.update(block)
    tools = {}
    for command in ('gcc', 'g++', 'nm', 'tar'):
        tools[command] = subprocess.check_output([command, '--version'], text=True).splitlines()[0]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = dict(probe=args.probe, nonce=args.nonce, hostname=socket.gethostname(),
                  start=start, end=time.time(), cwd=str(Path.cwd()), home=str(home),
                  tmpdir=temporary_root, python=platform.python_version(), tools=tools,
                  digest=digest.hexdigest(), home_writable=os.access(home, os.W_OK))
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
