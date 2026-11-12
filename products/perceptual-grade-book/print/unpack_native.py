"""Unpack the pinned Debian libraries used by the print renderer."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import tarfile


LIBRARY_DIR = Path("usr/lib/x86_64-linux-gnu")
REQUIRED_LIBRARIES = (
    "libfontconfig.so.1",
    "libfreetype.so.6",
    "libglib-2.0.so.0",
    "libharfbuzz.so.0",
    "libharfbuzz-subset.so.0",
    "libpango-1.0.so.0",
    "libpangoft2-1.0.so.0",
)


def _debian_filter(member, destination):
    if member.issym() and PurePosixPath(member.linkname).is_absolute():
        target = PurePosixPath(member.linkname.lstrip("/"))
        if ".." in target.parts:
            raise ValueError(f"Debian package symlink escapes its filesystem root: {member.name}")
        member.linkname = os.path.relpath(target.as_posix(), PurePosixPath(member.name).parent.as_posix())
    return tarfile.data_filter(member, destination)


def _extract(archive_path, destination):
    archive_path = Path(archive_path)
    with archive_path.open("rb") as source:
        if source.read(8) != b"!<arch>\n":
            raise ValueError(f"Not a Debian ar archive: {archive_path}")
        found_payload = False
        while header := source.read(60):
            if len(header) != 60 or header[58:] != b"`\n":
                raise ValueError(f"Invalid Debian archive header: {archive_path}")
            size = int(header[48:58])
            data = source.read(size)
            if len(data) != size:
                raise ValueError(f"Truncated Debian archive member: {archive_path}")
            if size % 2:
                source.read(1)
            name = header[:16].decode("ascii").strip().rstrip("/")
            if name.startswith("data.tar."):
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as payload:
                    payload.extractall(destination, filter=_debian_filter)
                found_payload = True
        if not found_payload:
            raise ValueError(f"Debian archive has no data payload: {archive_path}")


def unpack(archives, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    package_hashes = {}
    for archive in archives:
        archive = Path(archive)
        package_hashes[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
        _extract(archive, destination)

    library_dir = destination / LIBRARY_DIR
    missing = [name for name in REQUIRED_LIBRARIES if not (library_dir / name).exists()]
    if missing:
        raise ValueError(f"Pinned WeasyPrint runtime is missing libraries: {missing}")
    for name in REQUIRED_LIBRARIES:
        resolved = (library_dir / name).resolve(strict=True)
        if destination not in resolved.parents:
            raise ValueError(f"Native library symlink escapes the runtime bundle: {name}")
    if not (destination / "etc/fonts/fonts.conf").is_file():
        raise ValueError("Pinned Fontconfig configuration is missing")

    manifest = {
        "platform": "Debian 13 amd64",
        "packages": dict(sorted(package_hashes.items())),
        "libraries": {
            name: hashlib.sha256((library_dir / name).resolve().read_bytes()).hexdigest()
            for name in REQUIRED_LIBRARIES
        },
    }
    (destination / "native_runtime_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.output_dir)


if __name__ == "__main__":
    main()
