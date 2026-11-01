#!/usr/bin/env python3
"""Install checksum-pinned Linux x86_64 CI binaries without changing the checkout."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


PINS = json.loads(Path(__file__).with_name("tool-pins.json").read_text())


def check_version(executable, name):
    pin = PINS[name]
    result = subprocess.run(
        [str(executable), *pin["version_args"]],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if not re.search(pin["version_pattern"], result.stdout):
        raise ValueError(
            f"Expected {name} {pin['version']}; {executable} reported {result.stdout.strip()!r}"
        )


def download(url, destination):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=180) as response:
                with destination.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            return
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def install(name, directory):
    pin = PINS[name]
    installed = directory / name
    if installed.is_file():
        try:
            check_version(installed, name)
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        else:
            print(f"Using pinned {name} {pin['version']} at {installed}")
            return

    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=directory) as temporary:
        temporary = Path(temporary)
        archive = temporary / "download"
        executable = temporary / name
        download(pin["url"], archive)
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != pin["sha256"]:
            raise ValueError(f"SHA256 mismatch for {name}: expected {pin['sha256']}, got {actual}")
        if pin["compression"] == "gzip":
            with gzip.open(archive, "rb") as source, executable.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        elif pin["compression"] == "zstd":
            if shutil.which("zstd") is None:
                raise ValueError("Installing Buck2 requires zstd on PATH")
            subprocess.run(
                ["zstd", "--decompress", "--quiet", str(archive), "-o", str(executable)],
                check=True,
            )
        else:
            shutil.copyfile(archive, executable)
        executable.chmod(0o755)
        check_version(executable, name)
        executable.replace(directory / name)
    print(f"Installed {name} {pin['version']} at {installed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument("tools", nargs="+", choices=sorted(PINS))
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        parser.error("CI tool binaries are pinned for Linux x86_64")
    directory = args.bin_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for name in dict.fromkeys(args.tools):
        install(name, directory)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
