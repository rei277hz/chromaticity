#!/usr/bin/env python3
"""Check next-blender Buck/Starlark, TOML and .inv formatting; --fix uses the same scope."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from install_tools import check_version


ROOT = Path(__file__).resolve().parents[2]
PRODUCT = Path("products/perceptual-grade-next-blender")
EXCLUDED_DIRECTORIES = {
    ".git", ".cargo", ".state", ".venv", "__pycache__", "buck-out",
    "dist", "node_modules", "prelude", "target", "vendor",
}


def inventory():
    files = repository_files()
    groups = {"build": [], "starlark": [], "toml": [], "json": []}
    for name in sorted(files):
        path = Path(name)
        if (not path.is_relative_to(PRODUCT)
                or EXCLUDED_DIRECTORIES.intersection(path.parts)
                or not (ROOT / path).is_file() or (ROOT / path).is_symlink()):
            continue
        if path.name == "BUCK":
            groups["build"].append(name)
        elif path.suffix in {".bzl", ".bxl"} or path.name in {"PACKAGE", "BUCK_TREE"}:
            groups["starlark"].append(name)
        elif path.suffix == ".toml":
            groups["toml"].append(name)
        elif path.suffix == ".inv":
            groups["json"].append(name)
    if not any(groups.values()):
        raise ValueError(f"No formatting files found in {PRODUCT}; refusing an empty formatting check")
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


def canonical_json(contents):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"nonfinite number {value}")

    value = json.loads(contents, object_pairs_hook=unique_object, parse_constant=reject_constant)
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def format_json(paths, *, fix=False):
    failed = False
    for name in paths:
        path = ROOT / name
        try:
            contents = path.read_bytes()
            formatted = canonical_json(contents.decode("utf-8")).encode("utf-8")
            if formatted != contents:
                if fix:
                    path.write_bytes(formatted)
                else:
                    print(f"{name}: JSON formatting differs; run tools/ci/format.py --fix", file=sys.stderr)
                    failed = True
        except (OSError, ValueError, UnicodeError) as error:
            print(f"{name}: cannot format JSON: {error}", file=sys.stderr)
            failed = True
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fix", action="store_true", help="format next-blender Buck/Starlark, TOML and .inv files")
    mode.add_argument("--starlark-lint", action="store_true", help="run Buck's linter on next-blender .bzl/.bxl files")
    args = parser.parse_args()
    groups = inventory()
    if args.starlark_lint:
        paths = [name for name in groups["starlark"] if Path(name).suffix in {".bzl", ".bxl"}]
        if not paths:
            print(f"No .bzl/.bxl files to lint in {PRODUCT}.")
            return 0
        return run([tool("buck2"), "starlark", "lint", *paths])

    mode = "fix" if args.fix else "check"
    results = []
    for kind, file_type in [("build", "build"), ("starlark", "bzl")]:
        if groups[kind]:
            results.append(run([
                tool("buildifier"), f"-mode={mode}", "-lint=off", f"-type={file_type}", *groups[kind],
            ]))
    if groups["toml"]:
        results.append(run([tool("taplo"), "fmt", *([] if args.fix else ["--check"]), *groups["toml"]]))
    results.append(format_json(groups["json"], fix=args.fix))
    print(
        f"Formatting {'fix' if args.fix else 'check'} for {PRODUCT}: "
        f"{len(groups['build'])} Buck files, {len(groups['starlark'])} Starlark/package files, "
        f"{len(groups['toml'])} TOML files, {len(groups['json'])} .inv files as JSON."
    )
    return 1 if any(results) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
