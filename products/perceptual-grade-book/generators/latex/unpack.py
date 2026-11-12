"""Extract the pinned XeTeX/PGFPlots runtime without running package scripts."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_filter(member, destination):
    name = PurePosixPath(member.name)
    parts = name.parts
    # Documentation assets dominate several TeX packages. Retain notices, not
    # tutorials, examples or binaries that this renderer will never execute.
    if parts[:3] == ("usr", "share", "doc") and member.isfile():
        if name.name not in ("copyright", "LICENSE", "LICENSE.txt", "Licenses.gz"):
            return None
    if parts[:3] in (("usr", "share", "man"), ("usr", "share", "info")):
        return None
    if parts[:2] == ("usr", "bin") and name.name not in ("xetex", "dvisvgm"):
        return None
    if member.issym() and PurePosixPath(member.linkname).is_absolute():
        target = PurePosixPath(member.linkname.lstrip("/"))
        if ".." in target.parts:
            raise ValueError(f"Package symlink escapes its root: {name}")
        member.linkname = os.path.relpath(target.as_posix(), name.parent.as_posix())
    return tarfile.data_filter(member, destination)


def extract(archive_path, destination):
    with Path(archive_path).open("rb") as archive:
        if archive.read(8) != b"!<arch>\n":
            raise ValueError(f"Not a Debian package: {archive_path}")
        found = False
        while header := archive.read(60):
            if len(header) != 60 or header[58:] != b"`\n":
                raise ValueError(f"Invalid Debian package header: {archive_path}")
            size = int(header[48:58])
            data = archive.read(size)
            if len(data) != size:
                raise ValueError(f"Truncated Debian package: {archive_path}")
            if size % 2:
                archive.read(1)
            name = header[:16].decode("ascii").strip().rstrip("/")
            if name.startswith("data.tar."):
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as contents:
                    contents.extractall(destination, filter=runtime_filter)
                found = True
        if not found:
            raise ValueError(f"Missing Debian package payload: {archive_path}")


def unpack(archives, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for archive in archives:
        extract(archive, destination)
    required = (
        "usr/bin/xetex", "usr/bin/dvisvgm",
        "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
        "usr/share/texlive/texmf-dist/tex/latex/base/latex.ltx",
        "usr/share/texlive/texmf-dist/tex/latex/standalone/standalone.cls",
        "usr/share/texlive/texmf-dist/tex/latex/pgfplots/pgfplots.sty",
        "usr/share/texlive/texmf-dist/tex/generic/pgf/systemlayer/pgfsys-dvisvgm.def",
    )
    for name in required:
        path = destination / name
        if not path.is_file():
            raise ValueError(f"Pinned TeX runtime is missing {name}")
        if destination not in path.resolve().parents:
            raise ValueError(f"Pinned TeX runtime resource escapes its root: {name}")
    math_fonts = list(destination.rglob("texgyretermes-math.otf"))
    if not math_fonts or any(destination not in path.resolve().parents for path in math_fonts):
        raise ValueError("Pinned TeX runtime is missing TeX Gyre Termes Math")
    manifest = {
        "schema": 1,
        "platform": "Debian 13 amd64",
        "packages": {Path(path).name: digest(path) for path in sorted(archives)},
        "binaries": {name: digest(destination / name) for name in required[:3]},
        "math_font": math_fonts[0].relative_to(destination).as_posix(),
    }
    (destination / "runtime-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.output_dir)


if __name__ == "__main__":
    main()
