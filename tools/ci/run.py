#!/usr/bin/env python3
"""Run the selected Linux builds/tests and retain evidence even when they fail."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from check_targets import check as check_targets


ROOT = Path(__file__).resolve().parents[2]
TARGETS = Path(__file__).with_name("targets.json")
REPORT_FILES = (
    "build-report.json", "test-build-report.json", "test-trace-id.txt",
    "test-events.pb.zst", "test-events.jsonl", "build.log", "test.log",
    "events-errors.log", "exits.json",
)


class Interrupted(Exception):
    def __init__(self, signum: int):
        self.signum = signum


def interrupt(signum: int, _frame: object) -> None:
    raise Interrupted(signum)


def write_exits(directory: Path, values: dict[str, int | None]) -> None:
    temporary = directory / "exits.json.tmp"
    temporary.write_text(json.dumps(values, indent=2) + "\n")
    temporary.replace(directory / "exits.json")


def load_targets(path: Path = TARGETS) -> dict[str, list[str]]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("target selection must be a JSON object")
    for group in ("builds", "tests"):
        targets = value.get(group)
        if not isinstance(targets, list) or not targets or any(
            not isinstance(target, str) or not target.startswith("//")
            or "\x00" in target or "\n" in target for target in targets
        ) or len(set(targets)) != len(targets):
            raise ValueError(f"{group} must contain unique root-cell target labels")
    return value


def stop(process: subprocess.Popen, signum: int) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signum)
        process.wait(timeout=10)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def execute(command: list[str], log: Path, output: Path | None = None) -> int:
    """Tee ordinary command output; keep event JSON separate from stderr."""
    print("+ " + " ".join(command), flush=True)
    with log.open("w") as log_stream:
        output_stream = output.open("w") if output else None
        process = None
        try:
            process = subprocess.Popen(
                command, cwd=ROOT, text=True, errors="replace", start_new_session=True,
                stdout=output_stream if output_stream else subprocess.PIPE,
                stderr=log_stream if output_stream else subprocess.STDOUT,
            )
            if output_stream is None:
                assert process.stdout is not None
                for line in process.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    log_stream.write(line)
                    log_stream.flush()
                process.stdout.close()
            return process.wait()
        except Interrupted as error:
            if process is not None:
                stop(process, error.signum)
            raise
        except OSError as error:
            print(str(error), file=log_stream, flush=True)
            print(str(error), file=sys.stderr, flush=True)
            return 127
        finally:
            if process is not None and process.poll() is None:
                stop(process, signal.SIGTERM)
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if output_stream is not None:
                output_stream.close()


def run(directory: Path, targets: dict[str, list[str]]) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    for name in REPORT_FILES:
        (directory / name).unlink(missing_ok=True)
    exits: dict[str, int | None] = dict(selection=None, build=None, test=None, events=None)
    write_exits(directory, exits)
    stage = "selection"
    try:
        exits[stage] = check_targets(targets)
        write_exits(directory, exits)
        if exits[stage] != 0:
            return exits[stage]
        stage = "build"
        exits[stage] = execute([
            "buck2", "build", *targets["builds"], "--keep-going",
            "--build-report", str(directory / "build-report.json"),
        ], directory / "build.log")
        write_exits(directory, exits)
        stage = "test"
        exits[stage] = execute([
            "buck2", "test", *targets["tests"], "--keep-going",
            "--build-report", str(directory / "test-build-report.json"),
            "--write-build-id", str(directory / "test-trace-id.txt"),
            "--event-log", str(directory / "test-events.pb.zst"),
            "--", "--timeout", "1830",
        ], directory / "test.log")
        write_exits(directory, exits)
        stage = "events"
        exits[stage] = execute([
            "buck2", "log", "show", str(directory / "test-events.pb.zst"), "--no-remote",
        ], directory / "events-errors.log", directory / "test-events.jsonl")
        write_exits(directory, exits)
    except Interrupted as error:
        exits[stage] = -error.signum
        write_exits(directory, exits)
        return 128 + error.signum
    # Keep the original build/test error code when later evidence collection succeeds.
    for code in exits.values():
        if code is not None and code != 0:
            return code if code > 0 else 128 - code
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupt)
    try:
        return run(args.report_dir.resolve(), load_targets())
    except (OSError, ValueError) as error:
        print(f"CI runner: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
