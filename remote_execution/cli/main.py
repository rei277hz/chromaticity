#!/usr/bin/env python3
"""Manage the private Docker Compose NativeLink deployment and its Buck2 client."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
DOCKER = HERE / 'docker'
TESTS = HERE / 'tests'
STATE = HERE / '.state'
ENV_FILE = STATE / 'compose.env'
NETWORK = 'perceptual-grade-re'
IMAGE = 'perceptual-grade-nativelink:1.8.3'
ENDPOINT = 'perceptual-grade-nativelink:50051'
HEALTH = 'http://perceptual-grade-nativelink:50052'
BEGIN = '# BEGIN NativeLink settings (managed by remote_execution/re)\n'
END = '# END NativeLink settings\n'


def run(command, *, capture=False, cwd=ROOT, check=True, env=None):
    result = subprocess.run([str(arg) for arg in command], cwd=cwd, check=check,
                            text=True, stdout=subprocess.PIPE if capture else None, env=env)
    return result.stdout.strip() if capture else result.returncode


def compose(*args, capture=False, check=True):
    if not ENV_FILE.exists():
        raise RuntimeError('No deployment configuration. Run remote_execution/re up first.')
    # Compose otherwise lets stale shell settings override our persisted image identity.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('NATIVE_') and key != 'RUST_LOG'}
    return run(['docker', 'compose', '--env-file', ENV_FILE, '-f', DOCKER / 'compose.yaml',
                '-p', NETWORK, *args], capture=capture, check=check, env=environment)


def settings():
    return json.loads((STATE / 'deployment.json').read_text())


def configured_buckconfig(original, config=None):
    """Replace only the marked client settings; no config means local execution."""
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise RuntimeError('Incomplete or duplicate managed block in .buckconfig; repair its markers first.')
    pattern = re.compile(re.escape(BEGIN) + r'.*?' + re.escape(END), re.DOTALL)
    if BEGIN in original and not pattern.search(original):
        raise RuntimeError('Reversed managed block markers in .buckconfig.')
    outside = pattern.sub('', original)
    if re.search(r'^\[(?:build|buck2|buck2_re_client|remote_execution)\][ \t]*$', outside, re.MULTILINE):
        raise RuntimeError('Buck execution settings exist outside the managed block; '
                           'consolidate those sections inside its markers first.')
    lines = [
        BEGIN.rstrip(),
        '[build]',
        '  execution_platforms = ' + ('root//remote_execution:platforms' if config else 'prelude//platforms:default'),
        '', '[buck2]', '  digest_algorithms = SHA256',
    ]
    if config:
        endpoint = config.get('endpoint', ENDPOINT)
        lines += ['', '[buck2_re_client]',
                  f'  engine_address = {endpoint}', f'  action_cache_address = {endpoint}',
                  f'  cas_address = {endpoint}', '  tls = false', '  instance_name = main']
    lines += ['', '[remote_execution]', '  enabled = ' + ('true' if config else 'false')]
    if config:
        lines.append(f'  worker_image = {config["image_id"]}')
    lines += [END.rstrip(), '']
    replacement = '\n'.join(lines)
    if BEGIN in original:
        return pattern.sub(lambda _: replacement, original)
    return original + ('\n' if original and not original.endswith('\n\n') else '') + replacement


def configure_buck(root, config=None):
    path = root / '.buckconfig'
    atomic_write(path, configured_buckconfig(path.read_text(), config))


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(content)
    temp.replace(path)


def health(path='/ready'):
    # Private Docker service traffic must not be sent through a shell HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    address = settings().get('health_url', HEALTH)
    with opener.open(address + path, timeout=5) as response:
        return response.read().decode()


def require_ready():
    try:
        health()
        config = settings()
        workers = json.loads(health('/admin/scheduler/scheduler/workers'))
        expected = {'worker-image': config['image_id'], 'OSFamily': 'linux', 'ISA': 'x86-64'}
        usable = [worker for worker in workers
                  if not worker['is_paused'] and not worker['is_draining']
                  and all(worker['platform_properties'].get(key) == value for key, value in expected.items())]
        if not usable:
            raise RuntimeError('No registered worker matches this checkout\'s image and platform. '
                               'Run re up to reconcile deployment and Buck configuration.')
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f'NativeLink is not ready: {error}. '
                           'Run re status / re logs; use re local for local execution.') from error


def up(args):
    run(['docker', 'version', '--format', '{{.Server.Version}}'])
    run(['docker', 'compose', 'version'])
    if sys.platform != 'linux' or os.uname().machine != 'x86_64':
        raise RuntimeError('This deployment targets Linux x86_64.')
    if shutil.disk_usage(ROOT).free < 20 * 1024**3:
        raise RuntimeError('Less than 20 GiB free; free disk space before starting NativeLink.')
    image = args.image or IMAGE
    if not args.no_build and not args.image:
        run(['docker', 'build', '--tag', IMAGE, DOCKER])
    image_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], capture=True)
    config = dict(image_id=image_id, host_cpu_count=len(os.sched_getaffinity(0)),
                  workspace_container=args.workspace_container,
                  generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    values = dict(NATIVE_WORKER_IMAGE=image_id,
                  NATIVE_CAS_MAX_BYTES=os.environ.get('NATIVE_CAS_MAX_BYTES', str(120 * 1024**3)),
                  NATIVE_AC_MAX_BYTES=os.environ.get('NATIVE_AC_MAX_BYTES', str(1024**3)),
                  NATIVE_WORKER_CACHE_MAX_BYTES=os.environ.get('NATIVE_WORKER_CACHE_MAX_BYTES', str(32 * 1024**3)),
                  RUST_LOG=os.environ.get('RUST_LOG', 'info'))
    if any('\n' in value or '\r' in value for value in values.values()):
        raise RuntimeError('Deployment settings must be single-line values.')
    atomic_write(ENV_FILE, ''.join(f'{key}={value}\n' for key, value in values.items()))
    networks = run(['docker', 'network', 'ls', '--format', '{{.Name}}'], capture=True).splitlines()
    if NETWORK not in networks:
        run(['docker', 'network', 'create', NETWORK])
    if args.workspace_container:
        networks = json.loads(run(['docker', 'inspect', '--format', '{{json .NetworkSettings.Networks}}',
                                  args.workspace_container], capture=True))
        if NETWORK not in networks:
            run(['docker', 'network', 'connect', NETWORK, args.workspace_container])
    compose('config', '--quiet')
    worker = compose('ps', '-q', 'worker', capture=True)
    if worker and run(['docker', 'inspect', '--format', '{{.Image}}', worker], capture=True) != image_id:
        # Drain while the old scheduler is still reachable. Recreating control
        # first can leave a shutting-down worker retrying its lost connection.
        compose('stop', 'worker')
    compose('up', '-d', '--wait', '--wait-timeout', '120')
    if args.workspace_container:
        config.update(endpoint=ENDPOINT, health_url=HEALTH)
    else:
        # A native client on the Linux Docker host can reach the private bridge
        # address directly; Docker's service DNS is only available to containers.
        control = compose('ps', '-q', 'control', capture=True)
        networks = json.loads(run(['docker', 'inspect', '--format', '{{json .NetworkSettings.Networks}}',
                                  control], capture=True))
        address = networks[NETWORK]['IPAddress']
        config.update(endpoint=f'{address}:50051', health_url=f'http://{address}:50052')
    atomic_write(STATE / 'deployment.json', json.dumps(config, indent=2) + '\n')
    require_ready()
    configure_buck(ROOT, config)
    print(f'Ready: {config["endpoint"]}; unrestricted worker execution ({config["host_cpu_count"]} visible CPUs).')
    print('Updated root .buckconfig: ordinary Buck builds and tests use NativeLink.')


def logged(command, cwd, destination):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    with destination.open('w') as log:
        process = subprocess.Popen(list(map(str, command)), cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end='', flush=True)
        return process.wait()


def probe_executors(events):
    counts = {}
    for line in events.splitlines():
        if not line:
            continue
        event = json.loads(line)
        if 'root//remote_execution/tests:probe_' in event.get('identity', ''):
            executor = event['reproducer']['executor']
            counts[executor] = counts.get(executor, 0) + 1
    return counts


def validate(args):
    require_ready()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    directory = STATE / 'validation' / stamp
    # Buck discovers the outermost enclosing project. A nested checkout would
    # accidentally share the live workspace daemon and make `clean` unsafe.
    checkout = Path(tempfile.mkdtemp(prefix='perceptual-grade-re-validation-')) / 'checkout'
    directory.mkdir(parents=True)
    # The repository is currently untracked, so a git worktree would omit its contents.
    shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns('.git', 'buck-out', '.state',
                                                                '__pycache__', '.buckconfig.local'))
    configure_buck(checkout)
    actual_root = Path(run(['buck2', 'root', '--kind', 'project'], cwd=checkout, capture=True))
    if actual_root != checkout:
        raise RuntimeError(f'Validation checkout resolved to unexpected Buck root {actual_root}; refusing to run.')
    summary = dict(timestamp=stamp, checkout=str(checkout), deployment=settings(), checks={})
    try:
        validate_checkout(args, directory, checkout, summary)
    except Exception as error:
        summary['error'] = str(error)
        raise
    finally:
        run(['buck2', 'kill'], cwd=checkout, check=False)
        atomic_write(directory / 'summary.json', json.dumps(summary, indent=2) + '\n')
        print(f'Validation evidence: {directory}')


def validate_checkout(args, directory, checkout, summary):
    command = ['buck2', 'build', '//remote_execution:smoke', '--local-only',
               '-c', f'remote_execution.probe_nonce={uuid.uuid4().hex}', '--show-output',
               '--build-report', str(directory / 'local-build.json')]
    start = time.monotonic()
    code = logged(command, checkout, directory / 'local.log')
    summary['checks']['local_build'] = dict(exit_code=code, seconds=time.monotonic() - start)
    if code:
        raise RuntimeError(f'Local smoke probe failed; evidence: {directory}')
    events = run(['buck2', 'log', 'what-ran', '--format', 'json', '--emit-cache-queries'],
                 cwd=checkout, capture=True)
    (directory / 'local-actions.jsonl').write_text(events + '\n')
    counts = probe_executors(events)
    summary['checks']['local_build']['probe_executors'] = counts
    if counts.get('Local', 0) != 16 or counts.get('Re', 0) or counts.get('Cache', 0):
        raise RuntimeError(f'Expected 16 local probe executions, got {counts}.')
    local_records = {json.loads(path.read_text())['probe']: json.loads(path.read_text())
                     for path in (checkout / 'buck-out').rglob('report.json') if '__probe_' in str(path)}
    if len(local_records) != 16 or any(not r['cwd'].startswith(str(checkout) + os.sep)
                                      and r['cwd'] != str(checkout) for r in local_records.values()):
        raise RuntimeError('Local probes did not run in the disposable client checkout.')
    (directory / 'local-probes.json').write_text(json.dumps(list(local_records.values()), indent=2) + '\n')
    # Reset both local state and daemon connections before switching execution mode.
    run(['buck2', 'clean'], cwd=checkout)
    configure_buck(checkout, settings())

    nonce = uuid.uuid4().hex
    command = ['buck2', 'build', '//remote_execution:smoke', '--remote-only',
               '-c', f'remote_execution.probe_nonce={nonce}', '--show-output',
               '--build-report', str(directory / 'cold-build.json')]
    start = time.monotonic()
    code = logged(command, checkout, directory / 'cold.log')
    summary['checks']['cold_build'] = dict(exit_code=code, seconds=time.monotonic() - start)
    if code:
        atomic_write(directory / 'summary.json', json.dumps(summary, indent=2) + '\n')
        raise RuntimeError(f'Cold remote probe failed; evidence: {directory}')
    events = run(['buck2', 'log', 'what-ran', '--format', 'json', '--emit-cache-queries'],
                 cwd=checkout, capture=True)
    (directory / 'cold-actions.jsonl').write_text(events + '\n')
    counts = probe_executors(events)
    summary['checks']['cold_build']['probe_executors'] = counts
    if counts.get('Re', 0) != 16 or counts.get('Local', 0):
        raise RuntimeError(f'Expected 16 remote probe executions, got {counts}.')
    reports = list((checkout / 'buck-out').glob('**/__probe_*/output/report.json'))
    if not reports:
        reports = [p for p in (checkout / 'buck-out').rglob('report.json') if '__probe_' in str(p)]
    records = {json.loads(path.read_text())['probe']: json.loads(path.read_text()) for path in reports}
    if len(records) != 16:
        raise RuntimeError(f'Expected 16 probe reports, found {len(records)}; evidence: {directory}')
    ordered = sorted([(r['start'], 1) for r in records.values()] +
                     [(r['end'], -1) for r in records.values()])
    active = peak = 0
    for _, delta in ordered:
        active += delta
        peak = max(peak, active)
    if peak < 2:
        raise RuntimeError(f'Expected overlapping remote actions, measured {peak}.')
    if len({r['home'] for r in records.values()}) != 16 or not all(r['home_writable'] for r in records.values()):
        raise RuntimeError('Probe HOME directories were not isolated and writable.')
    if any(not r['cwd'].startswith('/data/') for r in records.values()):
        raise RuntimeError('Probe did not execute inside the NativeLink worker action directory.')
    summary['checks']['parallelism'] = dict(actions=16, peak_overlapping=peak,
                                            worker_hostnames=sorted({r['hostname'] for r in records.values()}))
    (directory / 'probes.json').write_text(json.dumps(list(records.values()), indent=2) + '\n')
    # Only this disposable checkout is cleaned; retain the SAME v2 path for matching action keys.
    run(['buck2', 'clean'], cwd=checkout)
    command[-1] = str(directory / 'warm-build.json')
    start = time.monotonic()
    code = logged(command, checkout, directory / 'warm.log')
    summary['checks']['warm_build'] = dict(exit_code=code, seconds=time.monotonic() - start)
    events = run(['buck2', 'log', 'what-ran', '--format', 'json', '--emit-cache-queries'],
                 cwd=checkout, capture=True)
    (directory / 'warm-actions.jsonl').write_text(events + '\n')
    counts = probe_executors(events)
    summary['checks']['warm_build']['probe_executors'] = counts
    warm_records = {json.loads(path.read_text())['probe']: json.loads(path.read_text())
                    for path in (checkout / 'buck-out').rglob('report.json') if '__probe_' in str(path)}
    reused = warm_records == records
    summary['checks']['cache_reuse'] = dict(all_probe_outputs_unchanged=reused)
    if code or not reused or counts.get('Cache', 0) != 16 or counts.get('Re', 0):
        atomic_write(directory / 'summary.json', json.dumps(summary, indent=2) + '\n')
        raise RuntimeError(f'Remote cache reuse failed; evidence: {directory}')
    if args.full:
        targets = json.loads((TESTS / 'validation-targets.json').read_text())
        if any(not isinstance(targets.get(kind), list) or not targets[kind]
               or not all(isinstance(target, str) and target.startswith('//') for target in targets[kind])
               for kind in ('build', 'test')):
            raise RuntimeError('validation-targets.json requires nonempty build/test lists of // target patterns.')
        code = logged(['buck2', 'build', *targets['build'], '--remote-only', '--show-output'],
                      checkout, directory / 'deliveries.log')
        summary['checks']['deliveries'] = dict(exit_code=code)
        # http_file rules also expose local `true` materialization checks. The
        # repository's real test profiles already require remote execution;
        # --remote-only would incorrectly reject those prelude bookkeeping checks.
        code = logged(['buck2', 'test', *targets['test'], '--skip-incompatible-targets',
                       '--', '--timeout', str(args.test_timeout)],
                      checkout, directory / 'tests.log')
        summary['checks']['linux_tests'] = dict(exit_code=code)
    print(json.dumps(summary, indent=2))
    if any(value.get('exit_code', 0) for value in summary['checks'].values()):
        raise RuntimeError('Validation recorded failed builds/tests; see the evidence above.')


def main():
    parser = argparse.ArgumentParser(prog='remote_execution/re', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    deploy = commands.add_parser('up', help='Start the stack and update root .buckconfig; retain caches')
    deploy.add_argument('--no-build', action='store_true')
    deploy.add_argument('--image', help='Use an existing immutable image or tag, e.g. for rollback')
    deploy.add_argument('--workspace-container', help='Optionally attach this existing development container to the private network')
    stop = commands.add_parser('down', help='Stop the stack; retain caches unless explicitly requested')
    stop.add_argument('--purge-caches', action='store_true', help='Delete this stack\'s cache volumes')
    commands.add_parser('local', help='Set local execution in the root .buckconfig')
    commands.add_parser('remote', help='Set remote execution in the root .buckconfig using the deployed worker')
    commands.add_parser('status', help='Inspect service health and registered workers')
    logs = commands.add_parser('logs', help='Show bounded service logs')
    logs.add_argument('service', nargs='?', choices=['control', 'worker'])
    logs.add_argument('--follow', action='store_true')
    check = commands.add_parser('validate', help='Prove local/remote execution, isolation, concurrency and remote cache reuse')
    check.add_argument('--full', action='store_true', help='Also run the project suite in tests/validation-targets.json')
    check.add_argument('--test-timeout', type=int, default=1800,
                       help='Per-test runner timeout in seconds for --full (default: 1800)')
    args = parser.parse_args()
    if args.command == 'up':
        up(args)
    elif args.command == 'down':
        compose('down', *(['--volumes'] if args.purge_caches else []))
    elif args.command == 'local':
        configure_buck(ROOT)
        print('Root .buckconfig now selects local builds and tests.')
        print('Run buck2 kill when this checkout has no active commands to reset its client connections.')
    elif args.command == 'remote':
        require_ready()
        config = settings()
        worker = compose('ps', '-q', 'worker', capture=True)
        actual = run(['docker', 'inspect', '--format', '{{.Image}}', worker], capture=True)
        if actual != config['image_id']:
            raise RuntimeError('Worker image differs from deployment settings; run re up again.')
        configure_buck(ROOT, config)
        print('Root .buckconfig now selects NativeLink for builds and tests.')
        print('Run buck2 kill when this checkout has no active commands to reset its client connections.')
    elif args.command == 'status':
        compose('ps')
        print(json.dumps(settings(), indent=2))
        print('Readiness: ' + health().strip())
        print('Workers: ' + json.dumps(json.loads(health('/admin/scheduler/scheduler/workers')), indent=2))
        require_ready()
    elif args.command == 'logs':
        compose('logs', '--tail', '100', *(['--follow'] if args.follow else []),
                *([args.service] if args.service else []))
    elif args.command == 'validate':
        validate(args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError, urllib.error.URLError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)
