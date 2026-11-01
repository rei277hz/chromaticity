"""Assemble a small relocatable Linux shared-library closure from pinned Debian packages."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


SONAMES = (
    "libX11.so.6", "libXrender.so.1", "libXfixes.so.3", "libXi.so.6",
    "libxkbcommon.so.0", "libSM.so.6", "libICE.so.6", "libXext.so.6",
    "libGL.so.1", "libGLX.so.0", "libGLdispatch.so.0", "libxcb.so.1",
    "libXau.so.6", "libXdmcp.so.6", "libbsd.so.0", "libmd.so.0", "libuuid.so.1",
)
LIBDIR = Path("usr/lib/x86_64-linux-gnu")


def _extract(archive: Path, destination: Path) -> None:
    with archive.open("rb") as source:
        if source.read(8) != b"!<arch>\n":
            raise ValueError(f"Not a Debian ar archive: {archive}")
        found_payload = False
        while header := source.read(60):
            if len(header) != 60 or header[58:] != b"`\n":
                raise ValueError(f"Invalid Debian archive header: {archive}")
            size = int(header[48:58])
            data = source.read(size)
            if len(data) != size:
                raise ValueError(f"Truncated Debian archive member: {archive}")
            if size % 2:
                source.read(1)
            member = header[:16].decode("ascii").strip().rstrip("/")
            if member.startswith("data.tar."):
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as payload:
                    payload.extractall(destination, filter="data")
                found_payload = True
        if not found_payload:
            raise ValueError(f"Debian archive has no data payload: {archive}")


def unpack(archives, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    for archive in archives:
        _extract(Path(archive), destination)
    library_dir = destination / LIBDIR
    missing = [name for name in SONAMES if not (library_dir / name).exists()]
    if missing:
        raise ValueError(f"Pinned Debian ABI closure is missing shared-library links: {missing}")
    libraries = {}
    for name in SONAMES:
        path = library_dir / name
        resolved = path.resolve(strict=True)
        if library_dir.resolve() not in resolved.parents:
            raise ValueError(f"Shared-library link escapes the pinned package directory: {path}")
        libraries[name] = dict(path=str(LIBDIR / name), target=resolved.name,
                               sha256=hashlib.sha256(resolved.read_bytes()).hexdigest())
    return dict(schema=1, platform="Debian 13 amd64", libraries=libraries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = unpack(args.archive, args.output_dir)
    (args.output_dir / "native_abi_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
