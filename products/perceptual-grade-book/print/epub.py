"""Create deterministic EPUB archives from a prepared EPUB package tree."""

from pathlib import Path, PurePosixPath
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


_MIMETYPE = b"application/epub+zip"
_CONTAINER = "META-INF/container.xml"
_REQUIRED = {_CONTAINER, "mimetype"}
_EPUB_NS = "http://www.idpf.org/2007/opf"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_CONTENT_FEATURES = {
    "mathml": "{http://www.w3.org/1998/Math/MathML}math",
    "svg": "{http://www.w3.org/2000/svg}svg",
}


def _safe_member(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or "\x00" in name or path.is_absolute()
            or path.as_posix() != name
            or any(part in ("", ".", "..") for part in name.split("/"))
            or any(ord(character) < 32 for character in name)):
        raise ValueError(f"Unsafe EPUB path: {name!r}")
    return path


def _tree_files(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"EPUB package root must be a directory: {root}")

    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed in EPUB packages: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Non-file EPUB package entry: {path}")
        name = path.relative_to(root).as_posix()
        _safe_member(name)
        if name in files:
            raise ValueError(f"Duplicate EPUB package path: {name}")
        files[name] = path

    if not _REQUIRED.issubset(files):
        raise ValueError(f"Missing required EPUB entries: {sorted(_REQUIRED - files.keys())}")
    if not any(name.startswith("EPUB/") for name in files):
        raise ValueError("EPUB package is missing its EPUB content directory")
    if files["mimetype"].read_bytes() != _MIMETYPE:
        raise ValueError("EPUB mimetype must contain application/epub+zip exactly")
    return files


def _parse_xml(path, description):
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError) as error:
        raise ValueError(f"Invalid {description}: {path}") from error


def _validate_package(root, files):
    container = _parse_xml(root / _CONTAINER, "EPUB container.xml")
    if container.tag != f"{{{_CONTAINER_NS}}}container":
        raise ValueError("EPUB container.xml has an invalid root element")

    rootfiles = container.findall(f".//{{{_CONTAINER_NS}}}rootfile")
    if not rootfiles:
        raise ValueError("EPUB container.xml has no rootfile")

    package_names = []
    for rootfile in rootfiles:
        package_path = rootfile.get("full-path", "")
        _safe_member(package_path)
        if rootfile.get("media-type") != "application/oebps-package+xml":
            raise ValueError("EPUB rootfile has an invalid media type")
        if package_path not in files:
            raise ValueError(f"EPUB rootfile does not exist: {package_path}")
        package_names.append(package_path)

    for package_name in package_names:
        package = _parse_xml(root / package_name, "EPUB package document")
        if package.tag != f"{{{_EPUB_NS}}}package":
            raise ValueError(f"Invalid EPUB package root element: {package_name}")
        manifest = package.find(f"{{{_EPUB_NS}}}manifest")
        spine = package.find(f"{{{_EPUB_NS}}}spine")
        if manifest is None or spine is None:
            raise ValueError(f"EPUB package requires a manifest and spine: {package_name}")

        opf_dir = PurePosixPath(package_name).parent
        identifiers = set()
        items = manifest.findall(f"{{{_EPUB_NS}}}item")
        nav_items = []
        for item in items:
            identifier = item.get("id")
            href = item.get("href")
            if not identifier or identifier in identifiers:
                raise ValueError(f"Missing or duplicate EPUB manifest id: {identifier!r}")
            identifiers.add(identifier)
            if not href:
                raise ValueError("EPUB manifest item is missing href")
            url = urlsplit(href)
            if url.scheme or url.netloc or url.path.startswith("/"):
                raise ValueError(f"EPUB manifest href must be package-relative: {href}")
            member = (opf_dir / unquote(url.path)).as_posix()
            _safe_member(member)
            if member not in files:
                raise ValueError(f"EPUB manifest item does not exist: {member}")
            if item.get("media-type") == "application/xhtml+xml":
                document = _parse_xml(files[member], "EPUB XHTML document")
                declared = set(item.get("properties", "").split())
                for feature, tag in _CONTENT_FEATURES.items():
                    if next(document.iter(tag), None) is not None and feature not in declared:
                        raise ValueError(
                            f"EPUB XHTML requires the {feature} manifest property: {member}"
                        )
            if "nav" in item.get("properties", "").split():
                nav_items.append(identifier)

        if len(nav_items) != 1:
            raise ValueError(f"EPUB package requires exactly one navigation document: {package_name}")

        manifest_ids = identifiers
        spine_ids = [item.get("idref") for item in spine.findall(f"{{{_EPUB_NS}}}itemref")]
        if not spine_ids or any(identifier not in manifest_ids for identifier in spine_ids):
            raise ValueError(f"EPUB spine is empty or references an unknown id: {package_name}")


def _zip_info(name, compression):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def write_epub(package_root, destination):
    """Validate and package an EPUB 3 tree with stable ZIP metadata."""
    root = Path(package_root)
    if root.is_symlink():
        raise ValueError(f"EPUB package root must not be a symlink: {root}")
    root = root.resolve()
    destination = Path(destination)
    if destination.exists() and destination.is_dir():
        raise ValueError(f"EPUB destination must be a file: {destination}")
    destination_parent = destination.parent.resolve()
    final_path = destination_parent / destination.name
    if final_path == root or final_path.is_relative_to(root):
        raise ValueError("EPUB destination must be outside its package tree")

    files = _tree_files(root)
    _validate_package(root, files)
    destination_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="epub-stage-", dir=destination_parent) as temporary:
        staged = Path(temporary) / destination.name
        with zipfile.ZipFile(staged, "w") as archive:
            archive.writestr(
                _zip_info("mimetype", zipfile.ZIP_STORED),
                _MIMETYPE,
                compress_type=zipfile.ZIP_STORED,
            )
            for name in sorted(files):
                if name == "mimetype":
                    continue
                archive.writestr(
                    _zip_info(name, zipfile.ZIP_DEFLATED),
                    files[name].read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )

        with zipfile.ZipFile(staged) as archive:
            expected = ["mimetype", *sorted(name for name in files if name != "mimetype")]
            if archive.namelist() != expected or archive.testzip() is not None:
                raise ValueError("Generated EPUB is incomplete or corrupt")
            first = archive.infolist()[0]
            if first.filename != "mimetype" or first.compress_type != zipfile.ZIP_STORED:
                raise ValueError("Generated EPUB must start with an uncompressed mimetype entry")

        staged.replace(final_path)
    return final_path
