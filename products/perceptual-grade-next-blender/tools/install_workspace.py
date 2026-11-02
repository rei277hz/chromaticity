"""Install the completed product ZIP into a Git worktree, preserving only .git."""

import argparse
from importlib.resources import as_file, files
from pathlib import Path, PurePosixPath
import shutil
import stat
import tomllib
import zipfile


def _destination(archive, destination):
    destination = Path(destination).expanduser()
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("Destination must be an existing directory, not a symlink")
    destination = destination.resolve()
    git = destination / ".git"
    if not (git.is_dir() or git.is_file()):
        raise ValueError("Destination must contain a .git directory or worktree file")
    if destination in {Path(destination.anchor), Path.home().resolve()}:
        raise ValueError("Refusing to replace the filesystem root or home directory")
    protected = (archive, Path.cwd().resolve(), Path(__file__).resolve())
    if any(path == destination or path.is_relative_to(destination) for path in protected):
        raise ValueError("Destination must not contain the archive, tool, or current directory")
    return destination


def _archive_contents(archive):
    """Read and CRC-check the complete archive before touching the destination."""
    contents = {}
    directories = set()
    paths = set()
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            name = entry.filename
            directory = entry.is_dir()
            normalized = name[:-1] if directory else name
            path = PurePosixPath(normalized)
            if (not normalized or not path.parts or path.is_absolute()
                    or normalized != path.as_posix() or ".." in path.parts
                    or "\\" in name or ":" in name
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)):
                raise ValueError("Unsafe ZIP path: " + repr(name))
            if path.parts[0].casefold() == ".git":
                raise ValueError("ZIP must not contain .git")
            if path in paths:
                raise ValueError("Duplicate ZIP path: " + normalized)
            paths.add(path)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
                raise ValueError("ZIP members must be regular files or directories: " + name)
            data = bundle.read(entry)
            if directory:
                if data:
                    raise ValueError("ZIP directory has file contents: " + name)
                directories.add(path)
            else:
                contents[path] = data

    for path in paths:
        if any(parent in contents for parent in path.parents):
            raise ValueError("ZIP file/directory conflict: " + str(path))
    if PurePosixPath("__init__.py") not in contents:
        raise ValueError("Product ZIP must contain a root __init__.py")
    manifest = contents.get(PurePosixPath("blender_manifest.toml"))
    if manifest is None or tomllib.loads(manifest.decode("utf-8")).get("id") != "perceptual_grade":
        raise ValueError("Product ZIP must identify the perceptual_grade extension")
    return contents, directories


def install_archive(archive_path, destination):
    """Replace worktree contents with exact ZIP bytes; never replace .git."""
    archive = Path(archive_path).expanduser().resolve(strict=True)
    destination = _destination(archive, destination)
    contents, directories = _archive_contents(archive)

    # The product ZIP is fully available and validated before any removal.
    # Unlink stale symlinks instead of following them outside the destination.
    for path in destination.iterdir():
        if path.name == ".git":
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    for path in sorted(directories, key=lambda item: len(item.parts)):
        destination.joinpath(*path.parts).mkdir(parents=True, exist_ok=True)
    for path, data in contents.items():
        output = destination.joinpath(*path.parts)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    return len(contents)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination", type=Path,
        default=Path.home() / "workspace" / "perceptual-grade",
        help="Git worktree to replace, keeping only .git (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        resource = files("product_install") / "perceptual_grade.zip"
        with as_file(resource) as archive:
            print(f"Using completed product ZIP: {archive}", flush=True)
            count = install_archive(archive, args.destination)
        print(f"Installed {count} files in {args.destination.expanduser().resolve()}; preserved .git")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        parser.exit(1, f"Workspace installation failed: {error}\n")


if __name__ == "__main__":
    main()
