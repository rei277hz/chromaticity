"""WeasyPrint PDF generation and reproducibility post-processing."""

import ctypes
import mimetypes
import os
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, urlunsplit


def _load_native_runtime():
    runtime = os.environ.get("PG_BOOK_NATIVE_RUNTIME")
    if runtime is None:
        if os.environ.get("PG_BUCK_ACTION") == "1":
            raise RuntimeError("PG_BOOK_NATIVE_RUNTIME must identify the pinned print runtime")
        return ()
    library_dir = Path(runtime).resolve(strict=True) / "usr/lib/x86_64-linux-gnu"
    handles = []
    for name in ("libpangoft2-1.0.so.0", "libharfbuzz-subset.so.0"):
        library = (library_dir / name).resolve(strict=True)
        # Buck's launcher must receive PAR_APPEND_LD_LIBRARY_PATH: changing
        # LD_LIBRARY_PATH after process startup cannot fix transitive dlopen.
        handles.append(ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL))
    return tuple(handles)


_NATIVE_LIBRARIES = _load_native_runtime()

from lxml import etree, html
import pikepdf
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher, URLFetcherResponse


EPOCH_PDF_DATE = "D:19800101000000Z"
EPOCH_XMP_DATE = "1980-01-01T00:00:00Z"
VIRTUAL_BOOK_ROOT = PurePosixPath("/__pg_print__/book")
VIRTUAL_FONT_ROOT = PurePosixPath("/__pg_print__/pdf-fonts")


class _StableResourceFetcher(URLFetcher):
    """Resolve stable virtual file URLs to declared local print resources."""

    def __init__(self, roots):
        super().__init__(allowed_protocols={"data", "file"})
        self.roots = roots

    def fetch(self, url, headers=None):
        parsed = urlsplit(url)
        if parsed.scheme == "file" and not parsed.netloc:
            virtual_path = PurePosixPath(unquote(parsed.path))
            for virtual_root, real_root in self.roots.items():
                try:
                    relative = virtual_path.relative_to(virtual_root)
                except ValueError:
                    continue
                root = Path(real_root).resolve(strict=True)
                target = (root / Path(*relative.parts)).resolve(strict=True)
                if not target.is_relative_to(root) or not target.is_file():
                    raise ValueError(f"Invalid print resource URL: {url}")
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                return URLFetcherResponse(url, target.read_bytes(), {"Content-Type": content_type})
            raise ValueError(f"Unmapped print resource URL: {url}")
        return super().fetch(url, headers)


def _first_destination_page(pdf, chapter_title):
    try:
        with pdf.open_outline() as outline:
            pending = list(outline.root)
            while pending:
                item = pending.pop(0)
                pending[0:0] = list(item.children)
                if item.title != chapter_title:
                    continue
                destination = item.destination
                if not isinstance(destination, pikepdf.Array) or not destination:
                    continue
                page_ref = destination[0]
                for index, page in enumerate(pdf.pages):
                    if page_ref.objgen == page.obj.objgen:
                        return index
    except (IndexError, TypeError, ValueError):
        return None
    return None


def _page_labels(pdf, chapter_title):
    if "/PageLabels" in pdf.Root:
        return
    body_start = _first_destination_page(pdf, chapter_title)
    if body_start is None or body_start < 1:
        raise ValueError("Could not locate the first body page for Roman/Arabic PDF page labels")
    pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
        0,
        pikepdf.Dictionary(S=pikepdf.Name("/r"), St=1),
        body_start,
        pikepdf.Dictionary(S=pikepdf.Name("/D"), St=1),
    ]))


def render_pdf(html_path, destination, title, author, description, language, first_chapter_title=None, pdf_stylesheet=None):
    """Render one edition using the pinned WeasyPrint package and worker fonts."""
    html_path = Path(html_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + ".weasy.pdf")
    normalized = destination.with_name(destination.name + ".normalized.pdf")
    font_config = FontConfiguration()
    if pdf_stylesheet is None:
        pdf_stylesheet = html_path.parent.parent / "pdf-fonts" / (html_path.parent.name + ".css")
    pdf_stylesheet = Path(pdf_stylesheet)
    if not pdf_stylesheet.is_file():
        raise ValueError(f"Missing PDF font stylesheet: {pdf_stylesheet}")
    document = html.document_fromstring(html_path.read_bytes())
    # EPUB packages these linked images. PDF annotations need deployed URLs;
    # resolving them against the worker directory creates unusable file: links.
    for anchor in document.xpath("//a[@href]"):
        reference = urlsplit(anchor.get("href"))
        if not reference.scheme and not reference.netloc and reference.path.startswith("media/"):
            anchor.set("href", urlunsplit((
                "https", "rei277hz.github.io",
                "/perceptual-grade/" + reference.path.removeprefix("media/"),
                reference.query, reference.fragment,
            )))
    # EPUB uses browser-compatible CJK shards. WeasyPrint 70 identifies fonts
    # by face description, so shards can collide in PDF font dictionaries.
    # Strip this stylesheet only from the in-memory PDF document.
    for stylesheet in document.xpath('//link[@href="fonts/noto/index.css"]'):
        stylesheet.getparent().remove(stylesheet)
    if first_chapter_title is None:
        headings = document.xpath("//section[contains(concat(' ', normalize-space(@class), ' '), ' chapter ')]/h1[1]")
        if not headings:
            raise ValueError("Could not find the first chapter title for PDF page labels")
        first_chapter_title = " ".join("".join(headings[0].itertext()).split())

    fetcher = _StableResourceFetcher({
        VIRTUAL_BOOK_ROOT: html_path.parent,
        VIRTUAL_FONT_ROOT: pdf_stylesheet.parent,
    })
    HTML(
        string=etree.tostring(document, encoding="unicode", method="html"),
        base_url=VIRTUAL_BOOK_ROOT.as_uri() + "/",
        url_fetcher=fetcher,
        media_type="print",
    ).write_pdf(
        target=str(staged),
        stylesheets=[CSS(
            string=pdf_stylesheet.read_text(encoding="utf-8"),
            base_url=(VIRTUAL_FONT_ROOT / pdf_stylesheet.name).as_uri(),
            url_fetcher=fetcher,
            font_config=font_config,
        )],
        font_config=font_config,
        presentational_hints=True,
        optimize_images=True,
        dpi=200,
        pdf_variant="pdf/ua-1",
    )

    with pikepdf.open(staged) as pdf:
        info = pdf.docinfo
        info["/Title"] = title
        info["/Author"] = author
        info["/Subject"] = description
        info["/Keywords"] = "Perceptual Grade, handbook, " + language
        info["/CreationDate"] = EPOCH_PDF_DATE
        info["/ModDate"] = EPOCH_PDF_DATE
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            metadata["xmp:CreateDate"] = EPOCH_XMP_DATE
            metadata["xmp:ModifyDate"] = EPOCH_XMP_DATE
            metadata["xmp:MetadataDate"] = EPOCH_XMP_DATE
        _page_labels(pdf, first_chapter_title)
        pdf.save(normalized, deterministic_id=True, compress_streams=True)

    staged.unlink()
    normalized.replace(destination)
    return destination
