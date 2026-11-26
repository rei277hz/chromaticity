"""Build-only evidence that the Perceptual Grade book ships current, static content."""

from io import BytesIO
import base64
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import re
import tomllib
from xml.etree import ElementTree
import zipfile

from PIL import Image
from pypdf import PdfReader


ARCHIVED_ZIP = "archived-blender-extension.zip"
EDITIONS = {
    "user-manual": ("en", "zh-Hans"),
    "technical-report": ("en",),
}
RASTER_SUFFIXES = {
    ".png", ".apng", ".gif", ".webp", ".avif", ".jpg", ".jpeg",
    ".bmp", ".ico", ".tif", ".tiff",
}
IMAGE_SUFFIXES = RASTER_SUFFIXES | {".svg"}


def audit_sources(docs: Path, generators: Path) -> dict:
    """Check the active bilingual manual and detached video producers."""
    chapters = []
    for language, directory in (("en", "src"), ("zh-Hans", "zh-Hans")):
        root = docs / directory
        intro = (root / "README.md").read_text(encoding="utf-8")
        if ARCHIVED_ZIP not in intro or "Perceptual Grade" not in intro:
            raise ValueError("Manual must identify Perceptual Grade and retain its archive")
        paths = [root / "README.md", *sorted((root / "guide").glob("*.md"))]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for match in re.finditer(r'''(?:href=["']?|\]\()([^\s"')>]+\.zip)''', text):
            target = match.group(1).split("#", 1)[0].split("?", 1)[0]
            if PurePosixPath(target).name != ARCHIVED_ZIP:
                raise ValueError("The active manual must not offer another install ZIP")
        for obsolete in ("data-still", "assets/demos/", "assets/intro/",
                         "DaVinci Resolve", "DCTL", "Preserved release", "保留版本"):
            if obsolete in text:
                raise ValueError("Obsolete active-manual content: " + obsolete)
        if re.search(r"<(?:video|audio|iframe)\b", text, re.IGNORECASE):
            raise ValueError("The active manual must not embed time-based media")
        for control in ("Linear", "Tone", "Color", "Adaptance", "Warp", "Scale",
                        "Bake", "Use Bake", "Node-Owned Grade", "65³"):
            if control not in text:
                raise ValueError("Missing Blender manual control: " + control)
        chapters.extend(language + "/" + path.relative_to(root).as_posix() for path in paths)
    source = generators.read_text(encoding="utf-8")
    if 'name = "demos"' not in source or 'name = "intro"' not in source:
        raise ValueError("The video producer targets must remain available")
    publication = source.split("ASSETS =", 1)[1].split("source_tree(", 1)[0]
    if re.search(r":(?:intro|demos)\[", publication):
        raise ValueError("Video outputs and provenance must not enter published assets")
    return {"manual_chapters": chapters, "archived_zip": ARCHIVED_ZIP,
            "video_producers_retained": True}


def _check_image(name: str, payload: bytes) -> bool:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".svg":
        root = ElementTree.fromstring(payload)
        if any(element.tag.rsplit("}", 1)[-1] in
               {"animate", "animateMotion", "animateTransform", "set"}
               for element in root.iter()):
            raise ValueError("Animated SVG in handbook: " + name)
        if re.search(rb"@keyframes|\banimation\s*:", payload):
            raise ValueError("Animated SVG stylesheet in handbook: " + name)
        return True
    if suffix not in RASTER_SUFFIXES:
        return False
    with Image.open(BytesIO(payload)) as image:
        if getattr(image, "n_frames", 1) != 1 or getattr(image, "is_animated", False):
            raise ValueError("Animated raster in handbook: " + name)
    return True


def _image_inventory(directory: Path) -> list[str]:
    images = []
    for path in sorted(directory.rglob("*")):
        if (path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()
                and _check_image(path.name, path.read_bytes())):
            images.append(path.relative_to(directory).as_posix())
    return images


def _check_pdf(path: Path) -> dict:
    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError("Empty handbook PDF: " + path.name)
    for page in reader.pages:
        for reference in page.get("/Annots", ()):
            annotation = reference.get_object()
            if annotation.get("/Subtype") in {"/Movie", "/RichMedia", "/Screen", "/Sound", "/3D"}:
                raise ValueError("Time-based content in handbook PDF: " + path.name)
    return {"file": path.name, "pages": len(reader.pages)}


def _check_epub(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as package:
        images = []
        for name in package.namelist():
            if PurePosixPath(name).suffix.lower() in {".mp4", ".mov", ".webm", ".m4v"}:
                raise ValueError("Video entered handbook EPUB: " + name)
            if PurePosixPath(name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            payload = package.read(name)
            if _check_image(name, payload):
                images.append(name)
        for name in package.namelist():
            if not name.lower().endswith(('.xhtml', '.html')):
                continue
            root = ElementTree.fromstring(package.read(name))
            if any(element.tag.rsplit("}", 1)[-1] in {"video", "audio"}
                   for element in root.iter()):
                raise ValueError("Time-based content in handbook EPUB: " + path.name)
        return sorted(images)


class _DocumentMedia(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []

    def handle_starttag(self, tag, attributes):
        if tag in {"video", "audio"}:
            raise ValueError("Time-based content in prepared handbook document")
        if tag == "img":
            source = dict(attributes).get("src")
            if source is not None:
                self.images.append(source)


def _check_document_images(directory: Path) -> list[str]:
    parser = _DocumentMedia()
    parser.feed((directory / "book.html").read_text(encoding="utf-8"))
    images = []
    for source in parser.images:
        if source.startswith("data:"):
            header, separator, encoded = source.partition(",")
            if not separator or ";base64" not in header:
                raise ValueError("Unsupported embedded handbook image: " + source[:48])
            payload = base64.b64decode(encoded, validate=True)
            media_type = header[5:].split(";", 1)[0]
            extension = {
                "image/png": ".png", "image/apng": ".apng", "image/gif": ".gif",
                "image/webp": ".webp", "image/avif": ".avif", "image/jpeg": ".jpg",
                "image/svg+xml": ".svg",
            }.get(media_type)
            if extension is None:
                raise ValueError("Unsupported embedded handbook image type: " + media_type)
            _check_image("embedded" + extension, payload)
            continue
        if source.startswith(("http:", "https:")):
            raise ValueError("External images cannot be checked for animation: " + source)
        candidate = directory / source
        if not candidate.is_file():
            raise ValueError("Missing handbook image: " + source)
        if _check_image(source, candidate.read_bytes()):
            images.append(source)
    return sorted(set(images))


def audit_artifacts(site: Path, archive: Path, exports: dict[str, Path]) -> dict:
    """Inspect the actual site/ZIP and each PDF/EPUB export's static media."""
    archived_zip = site / "downloads" / ARCHIVED_ZIP
    if not archived_zip.is_file():
        raise ValueError("Site lost the archived Blender package")
    with zipfile.ZipFile(archived_zip) as extension:
        metadata = tomllib.loads(extension.read("blender_manifest.toml").decode("utf-8"))
        if not isinstance(metadata.get("version"), str) or not metadata["version"]:
            raise ValueError("Archived Blender package has no version metadata")
    images = _image_inventory(site)
    if not images:
        raise ValueError("Site has no image inventory")
    if (site / "assets/demos").exists() or (site / "assets/intro").exists():
        raise ValueError("Legacy animation assets entered the site")
    if (site / "downloads/provenance/intro-video.json").exists():
        raise ValueError("Animation provenance entered the site")
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        if "downloads/" + ARCHIVED_ZIP not in names:
            raise ValueError("Deployment ZIP lost the archived Blender package")
        if package.read("downloads/" + ARCHIVED_ZIP) != archived_zip.read_bytes():
            raise ValueError("Site and deployment ZIP extension bytes differ")
        if ("downloads/provenance/intro-video.json" in names
                or any(name.startswith(("assets/demos/", "assets/intro/")) for name in names)):
            raise ValueError("Animation outputs or provenance entered the deployment ZIP")
        archived_images = sorted(name for name in names
                                 if PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES
                                 and _check_image(name, package.read(name)))
        if archived_images != images:
            raise ValueError("Site and deployment ZIP image inventories differ")
        for name in images:
            if package.read(name) != (site / name).read_bytes():
                raise ValueError("Site and deployment ZIP image bytes differ: " + name)
    editions = {}
    for publication, languages in EDITIONS.items():
        root = exports[publication]
        for language in languages:
            stem = publication + "-" + language
            documents = root / "documents" / language
            if not (documents / "book.html").is_file():
                raise ValueError("Missing prepared handbook document: " + stem)
            document_images = _check_document_images(documents)
            pdf = _check_pdf(root / "pdf" / (stem + ".pdf"))
            epub_images = _check_epub(root / "epub" / (stem + ".epub"))
            editions[stem] = {"document_images": document_images,
                              "pdf": pdf, "epub_images": epub_images}
    return {"site_images": images, "archive_images": archived_images,
            "editions": editions, "animated_images": 0}
