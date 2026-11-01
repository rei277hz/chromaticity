"""Small hermetic packaging actions; Rust compilation is owned by Buck rules."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib


def distribution(args):
    args.output.mkdir(parents=True, exist_ok=True)
    for component, archive in args.component:
        with tempfile.TemporaryDirectory(prefix="rust-distribution-") as temporary:
            root = Path(temporary)
            with tarfile.open(archive) as source:
                source.extractall(root, filter="data")
            directories = list(root.iterdir())
            if len(directories) != 1:
                raise ValueError(f"Expected one root in {archive}")
            payload = directories[0] / component
            if not payload.is_dir():
                raise ValueError(f"Missing component {component} in {archive}")
            shutil.copytree(payload, args.output, dirs_exist_ok=True, symlinks=True)


def bindgen(args):
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        args.bindgen, str(args.wasm), "--target", "web",
        "--out-name", args.name, "--out-dir", str(args.output),
    ], check=True)
    (args.output / "package.json").write_text('{"type":"module"}\n')


def notices(args):
    entries = {}
    for sources in args.sources:
        # Reindeer srcs contains the whole downloaded .crate directory. The
        # RustSources closure also contains first-party trees without manifests.
        manifests = list(sources.glob("*/Cargo.toml"))
        if (sources / "Cargo.toml").is_file():
            manifests.append(sources / "Cargo.toml")
        for manifest in manifests:
            package = tomllib.loads(manifest.read_text())["package"]
            identity = package["name"] + " " + package["version"]
            root = manifest.parent
            files = []
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.name.lower().startswith(("license", "copying", "notice", "copyright")):
                    files.append((path.relative_to(root).as_posix(), path.read_text(errors="replace")))
            text = "\n".join(
                [identity, "License: " + package.get("license", package.get("license-file", "See included license files"))]
                + [f"\n--- {path} ---\n{content}" for path, content in files]
            )
            previous = entries.setdefault(identity, text)
            if previous != text:
                raise ValueError("Conflicting notices for " + identity)
    if not entries:
        raise ValueError("No dependency manifests found in the Rust source closure")
    args.output.write_text("Rust dependencies\n\n" + "\n\n".join(entries[key] for key in sorted(entries)) + "\n")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    unpack = subparsers.add_parser("distribution")
    unpack.add_argument("--component", action="append", nargs=2, required=True)
    unpack.add_argument("--output", type=Path, required=True)
    package = subparsers.add_parser("bindgen")
    package.add_argument("--bindgen", required=True)
    package.add_argument("--wasm", type=Path, required=True)
    package.add_argument("--name", required=True)
    package.add_argument("--output", type=Path, required=True)
    licenses = subparsers.add_parser("notices")
    licenses.add_argument("--output", type=Path, required=True)
    licenses.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    {"distribution": distribution, "bindgen": bindgen, "notices": notices}[args.operation](args)


if __name__ == "__main__":
    main()
