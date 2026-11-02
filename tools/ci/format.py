#!/usr/bin/env python3
"""Check maintained Buck/Starlark and TOML formatting; --fix applies that scope only."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from install_tools import check_version


ROOT = Path(__file__).resolve().parents[2]
GENERATED = {
    "third_party/rust/BUCK",
    "third_party/web/dependencies.bzl",
}
EXCLUDED_DIRECTORIES = {
    ".git", ".cargo", ".state", ".venv", "__pycache__", "buck-out",
    "dist", "node_modules", "prelude", "target", "vendor",
}
HISTORICAL = "products/perceptual-grade-book/docs/"


def inventory():
    files = repository_files()
    groups = {"build": [], "starlark": [], "toml": []}
    for name in sorted(files):
        path = Path(name)
        if (name in GENERATED or name.startswith(HISTORICAL)
                or EXCLUDED_DIRECTORIES.intersection(path.parts)
                or not (ROOT / path).is_file() or (ROOT / path).is_symlink()):
            continue
        if path.name == "BUCK":
            groups["build"].append(name)
        elif path.suffix in {".bzl", ".bxl"} or path.name in {"PACKAGE", "BUCK_TREE"}:
            groups["starlark"].append(name)
        elif path.suffix == ".toml":
            groups["toml"].append(name)
    for kind, names in groups.items():
        if not names:
            raise ValueError(f"No maintained {kind} files found; refusing an empty formatting check")
    return groups


def repository_files():
    if shutil.which("git"):
        git_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if git_root.returncode == 0:
            result = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
            )
            return set(result.stdout.decode().split("\0")) - {""}

    sapling = os.environ.get("CHROMATICITY_SAPLING_BIN") or shutil.which("sl")
    if sapling:
        sapling_root = subprocess.run(
            [sapling, "root"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if sapling_root.returncode == 0:
            tracked = subprocess.run(
                [sapling, "files", "--print0"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
            )
            unknown = subprocess.run(
                [sapling, "status", "--unknown", "--no-status", "--print0"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
            )
            names = tracked.stdout + unknown.stdout
            return set(names.decode().split("\0")) - {""}

    raise ValueError(f"{ROOT} is neither a Git nor a Sapling working copy")


def tool(name):
    executable = shutil.which(name)
    if executable is None:
        raise ValueError(f"Missing {name}; install the pinned CI tools and add their bin directory to PATH")
    check_version(executable, name)
    return executable


def run(command):
    # Taplo's default INFO tracing dumps every filename. Keep diagnostics concise.
    env = dict(os.environ)
    env.setdefault("RUST_LOG", "warn")
    return subprocess.run(command, cwd=ROOT, env=env).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fix", action="store_true", help="format the maintained Buck/Starlark and TOML files")
    mode.add_argument("--starlark-lint", action="store_true", help="run Buck's linter on maintained .bzl/.bxl files")
    args = parser.parse_args()
    groups = inventory()
    if args.starlark_lint:
        paths = [name for name in groups["starlark"] if Path(name).suffix in {".bzl", ".bxl"}]
        if not paths:
            raise ValueError("No maintained .bzl/.bxl files found")
        return run([tool("buck2"), "starlark", "lint", *paths])

    buildifier = tool("buildifier")
    taplo = tool("taplo")
    mode = "fix" if args.fix else "check"
    results = []
    for kind, file_type in [("build", "build"), ("starlark", "bzl")]:
        results.append(run([
            buildifier, f"-mode={mode}", "-lint=off", f"-type={file_type}", *groups[kind],
        ]))
    results.append(run([taplo, "fmt", *([] if args.fix else ["--check"]), *groups["toml"]]))
    print(
        f"Formatting {'fix' if args.fix else 'check'}: "
        f"{len(groups['build'])} Buck files, {len(groups['starlark'])} Starlark/package files, "
        f"{len(groups['toml'])} TOML files."
    )
    return 1 if any(results) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
