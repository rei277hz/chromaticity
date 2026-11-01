#!/usr/bin/env python3
"""Regenerate Rust dependency rules with the pinned Reindeer and Rust toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


REINDEER_REVISION = "ede87128a86b36aa04e625071f87f52f05c7a827"
REINDEER_REPOSITORY = "https://github.com/facebookincubator/reindeer"
RUST_VERSION = "1.99.1"
THIRD_PARTY = Path(__file__).resolve().parent
ROOT = THIRD_PARTY.parent.parent


def run(command: list[str | Path], *, env: dict[str, str], capture: bool = False) -> str:
    result = subprocess.run(
        [str(arg) for arg in command],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else ""


def toolchain(args: argparse.Namespace, env: dict[str, str]) -> tuple[Path, Path]:
    if args.cargo or args.rustc:
        if not args.cargo or not args.rustc:
            raise ValueError("--cargo and --rustc must be provided together")
        # Keep rustup proxy filenames: resolving their symlinks changes argv[0].
        cargo, rustc = args.cargo.absolute(), args.rustc.absolute()
    else:
        output = run(
            ["buck2", "build", "//tools/rust-build:distribution", "--show-full-simple-output"],
            env=env,
            capture=True,
        ).strip().splitlines()
        if len(output) != 1:
            raise ValueError("expected one Rust distribution output from Buck2")
        distribution = Path(output[0])
        cargo, rustc = distribution / "bin/cargo", distribution / "bin/rustc"
    for executable, name in [(cargo, "cargo"), (rustc, "rustc")]:
        version = run([executable, "--version"], env=env, capture=True)
        if not version.startswith(f"{name} {RUST_VERSION} "):
            raise ValueError(f"expected {name} {RUST_VERSION}, got {version.strip()}")
    return cargo, rustc


def reindeer(cargo: Path, env: dict[str, str]) -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    installation = cache / "perceptual-grade/reindeer" / REINDEER_REVISION
    binary = installation / "bin/reindeer"
    receipt = installation / ".crates2.json"

    def pinned() -> bool:
        if not binary.is_file() or not receipt.is_file():
            return False
        installs = json.loads(receipt.read_text())["installs"]
        source = f"git+{REINDEER_REPOSITORY}?rev={REINDEER_REVISION}#{REINDEER_REVISION}"
        return any(
            key.startswith("reindeer ") and f"({source})" in key
            for key in installs
        )

    if not pinned():
        run(
            [cargo, "install", "--locked", "--git", REINDEER_REPOSITORY,
             "--rev", REINDEER_REVISION, "--root", installation, "reindeer"],
            env=env,
        )
    if not pinned():
        raise ValueError("Cargo installation receipt does not match the pinned Reindeer revision")
    return binary


def tool_versions() -> str:
    lock_bytes = (THIRD_PARTY / "Cargo.lock").read_bytes()
    packages = tomllib.loads(lock_bytes.decode())["package"]
    crates = {}
    for name in ["mdbook", "wasm-bindgen-cli"]:
        matches = [package for package in packages if package["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one locked {name} package")
        package = matches[0]
        crates[name] = {"version": package["version"], "sha256": package["checksum"]}
    bindgen = [package["version"] for package in packages if package["name"] == "wasm-bindgen"]
    if bindgen != [crates["wasm-bindgen-cli"]["version"]]:
        raise ValueError("wasm-bindgen and wasm-bindgen-cli must have exactly matching versions")
    return json.dumps(
        {
            "schema": 1,
            "reindeer_revision": REINDEER_REVISION,
            "cargo_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
            "crates": crates,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def write_atomic(path: Path, contents: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(contents)
    temporary.chmod(0o644)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="fail if checked-in generated files differ")
    modes.add_argument("--update", action="store_true", help="allow Cargo.lock to resolve changed manifest requirements")
    parser.add_argument("--cargo", type=Path, help="explicit pinned Cargo, paired with --rustc (bootstrap only)")
    parser.add_argument("--rustc", type=Path, help="explicit pinned rustc, paired with --cargo (bootstrap only)")
    args = parser.parse_args()

    if any((THIRD_PARTY / path).exists() for path in ["vendor", ".cargo/config", ".cargo/config.toml"]):
        raise ValueError("remove local Reindeer vendor state before generating nonvendored rules")
    env = dict(os.environ)
    cargo, rustc = toolchain(args, env)
    env["RUSTC"] = str(rustc)
    binary = reindeer(cargo, env)
    # Reindeer uses this location when looking up checksum-verified archive
    # sizes. Make Cargo metadata use it too, including on a fresh checkout.
    # Keep the generator bootstrap above on the user's normal Cargo cache.
    env["CARGO_HOME"] = str(THIRD_PARTY / ".cargo")

    if args.update:
        # Artifact dependencies are enabled only during dependency maintenance.
        update_env = dict(env, RUSTC_BOOTSTRAP="1")
        run(
            [cargo, "-Zbindeps", "metadata", "--manifest-path", THIRD_PARTY / "Cargo.toml",
             "--format-version", "1", "--all-features"],
            env=update_env,
            capture=True,
        )
    generated = run(
        [binary, "--third-party-dir", THIRD_PARTY, "--cargo-path", cargo,
         "--rustc-path", rustc, "--cargo-options=--locked", "buckify", "--stdout"],
        env=env,
        capture=True,
    )
    outputs = {
        THIRD_PARTY / "BUCK": generated,
        THIRD_PARTY / "tools/versions.json": tool_versions(),
    }
    changed = [path for path, content in outputs.items() if not path.is_file() or path.read_text() != content]
    if args.check:
        if changed:
            print("Generated Rust dependency files are stale:", file=sys.stderr)
            for path in changed:
                print(f"  {path.relative_to(ROOT)}", file=sys.stderr)
            return 1
        print("Rust dependency rules and tool metadata match the pinned generator.")
        return 0
    for path in changed:
        write_atomic(path, outputs[path])
    print(f"Generated Rust dependency rules and tool metadata ({len(changed)} files updated).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
