"""Replace a website checkout's color-picker directory with the completed ZIP."""

import argparse
import hashlib
from importlib.resources import as_file, files
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


def _digest(source):
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _destination(archive, manifest, destination):
    destination = Path(destination).expanduser().absolute()
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError("Destination must not pass through a symlink")
    destination = destination.resolve()
    if destination in {Path(destination.anchor), Path.home().resolve()}:
        raise ValueError("Refusing to replace the filesystem root or home directory")
    if destination.name.casefold() == ".git":
        raise ValueError("Destination must not be Git metadata")
    if destination.exists() and not destination.is_dir():
        raise ValueError("Destination must be a directory")
    git = destination.parent / ".git"
    if git.is_symlink() or not (git.is_dir() or git.is_file()):
        raise ValueError("Destination must be a direct child of an existing Git worktree")
    if (destination / ".git").exists() or (destination / ".git").is_symlink():
        raise ValueError("Destination must not itself be a Git worktree")
    protected = (archive, manifest, Path.cwd().resolve(), Path(__file__).resolve())
    if any(path == destination or path.is_relative_to(destination) for path in protected):
        raise ValueError("Destination must not contain the archive, manifest, tool, or current directory")
    return destination


def _archive_contents(bundle, expected):
    """Validate paths, CRCs, and the complete file inventory before any removal."""
    contents = {}
    directories = set()
    paths = set()
    for entry in bundle.infolist():
        name = entry.filename
        directory = entry.is_dir()
        normalized = name[:-1] if directory else name
        path = PurePosixPath(normalized)
        if (not normalized or not path.parts or path.is_absolute()
                or normalized != path.as_posix() or ".." in path.parts
                or "\\" in name or ":" in name or entry.orig_filename != name
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise ValueError("Unsafe ZIP path: " + repr(name))
        if any(part.casefold() == ".git" for part in path.parts):
            raise ValueError("ZIP must not contain Git metadata")
        if path in paths:
            raise ValueError("Duplicate ZIP path: " + normalized)
        paths.add(path)
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
            raise ValueError("ZIP members must be regular files or directories: " + name)
        if directory:
            if bundle.read(entry):
                raise ValueError("ZIP directory has file contents: " + name)
            directories.add(path)
        else:
            contents[path] = entry

    for path in paths:
        if any(parent in contents for parent in path.parents):
            raise ValueError("ZIP file/directory conflict: " + str(path))
    required = {PurePosixPath("index.html"), PurePosixPath("THIRD_PARTY_NOTICES.txt")}
    if not required <= contents.keys() or any(
            not any(path.parts[0] == "assets" and path.suffix == suffix for path in contents)
            for suffix in (".js", ".css", ".wasm")):
        raise ValueError("Site ZIP is missing required HDR Color Picker publication files")
    if set(expected) != {str(path) for path in contents}:
        raise ValueError("Site ZIP contents do not match its inventory")
    for path, entry in contents.items():
        with bundle.open(entry) as source:
            if _digest(source) != expected[str(path)]:
                raise ValueError("Site ZIP checksum mismatch: " + str(path))
    return contents, directories


def publish_archive(archive_path, manifest_path, destination):
    """Clear the target directory and extract exact bytes from a validated ZIP."""
    archive = Path(archive_path).expanduser().resolve(strict=True)
    manifest_path = Path(manifest_path).expanduser().resolve(strict=True)
    destination = _destination(archive, manifest_path, destination)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError("Site manifest must contain a file inventory")
    with archive.open("rb") as source:
        if _digest(source) != manifest.get("sha256"):
            raise ValueError("Site ZIP checksum does not match its manifest")
        source.seek(0)
        with zipfile.ZipFile(source) as bundle:
            contents, directories = _archive_contents(bundle, manifest["files"])
            destination.mkdir(exist_ok=True)
            # Only this child directory is replaced. Unlink stale symlinks
            # instead of following them elsewhere in the website checkout.
            for path in destination.iterdir():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            for path in sorted(directories, key=lambda item: len(item.parts)):
                destination.joinpath(*path.parts).mkdir(parents=True, exist_ok=True)
            for path, entry in contents.items():
                output = destination.joinpath(*path.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as member, output.open("wb") as target:
                    shutil.copyfileobj(member, target, length=1024 * 1024)
    return len(contents)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination", type=Path,
        default=Path.home() / "workspace" / "rei277hz.github.io" / "color-picker",
        help="Site directory to replace inside a Git worktree (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        resources = files("hdr_color_picker_publish")
        with as_file(resources / "hdr-color-picker-web.zip") as archive, \
                as_file(resources / "manifest.json") as manifest:
            print(f"Using completed static-site ZIP: {archive}", flush=True)
            count = publish_archive(archive, manifest, args.destination)
        print(f"Published {count} files in {args.destination.expanduser().resolve()}")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        parser.exit(1, f"HDR Color Picker publication failed: {error}\n")


if __name__ == "__main__":
    main()
