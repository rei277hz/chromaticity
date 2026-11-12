"""Build bilingual PDF and EPUB editions from the existing mdBook output."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ET

# Importing the renderer loads its declared native runtime before WeasyPrint.
from pg_book_print.pdf import render_pdf

import pikepdf
from lxml import etree, html
import weasyprint

from pg_book_print.document import build_document
from pg_book_print.epub import write_epub


XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
LANGUAGES = ("en", "zh-Hans")
FIXED_DATE = "1980-01-01T00:00:00Z"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    root = Path(root)
    return {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _copy_tree(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_dir():
        raise ValueError(f"Missing declared print resource directory: {source}")
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Print resources may not contain symlinks: {path}")
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def _prepare_pdf_fonts(work_dir, source_dir):
    """Keep each PDF face in one file; web shards can collide in PDF font IDs."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    source_dir = Path(source_dir)
    font_root = Path(work_dir) / "pdf-fonts"
    tinos_root = font_root / "tinos"
    noto_root = font_root / "noto-serif-sc"
    tinos_root.mkdir(parents=True)
    noto_root.mkdir()
    tinos_rules = []
    for suffix, weight, style in (
        ("Regular", 400, "normal"), ("Bold", 700, "normal"),
        ("Italic", 400, "italic"), ("BoldItalic", 700, "italic"),
    ):
        name = f"Tinos-{suffix}.ttf"
        shutil.copyfile(source_dir / name, tinos_root / name)
        tinos_rules.append(
            f'@font-face {{ font-family: "Tinos"; font-style: {style}; '
            f'font-weight: {weight}; src: url("{name}") format("truetype"); }}'
        )
    (tinos_root / "index.css").write_text("\n".join(tinos_rules) + "\n", encoding="utf-8")

    # Resolve the full variable source to two complete faces before PDF layout.
    # WeasyPrint 70 accepts single CSS weights, not variable weight ranges.
    noto_rules = []
    for weight in (400, 700):
        with TTFont(source_dir / "NotoSerifSC-variable.ttf", recalcTimestamp=False) as font:
            instantiateVariableFont(font, {"wght": weight}, inplace=True, updateFontNames=True)
            name = f"NotoSerifSC-{weight}.ttf"
            font.save(noto_root / name)
        noto_rules.append(
            f'@font-face {{ font-family: "Noto Serif SC"; font-style: normal; '
            f'font-weight: {weight}; src: url("{name}") format("truetype"); }}'
        )
    (noto_root / "index.css").write_text("\n".join(noto_rules) + "\n", encoding="utf-8")

    stylesheets = {}
    for language in LANGUAGES:
        imports = ['@import url("tinos/index.css");']
        font_stack = '"Tinos", serif'
        mono_stack = '"Roboto Mono", "Tinos", monospace'
        if language == "zh-Hans":
            imports.append('@import url("noto-serif-sc/index.css");')
            font_stack = '"Tinos", "Noto Serif SC", serif'
            mono_stack = '"Roboto Mono", "Noto Serif SC", monospace'
        stylesheet = font_root / (language + ".css")
        # write_pdf stylesheets are user stylesheets: important overrides the
        # authored tokens without changing the shared HTML or EPUB styles.
        stylesheet.write_text(
            "\n".join(imports) + "\n:root { --book-font-sans: " + font_stack
            + " !important; --book-font-mono: " + mono_stack + " !important; }\n",
            encoding="utf-8",
        )
        stylesheets[language] = stylesheet
    return stylesheets, {
        name: source_dir / name for name in ("Tinos-OFL.txt", "Noto-Serif-SC-OFL.txt")
    }


def _write_xhtml(path, title, language, body_children):
    html_node = etree.Element(f"{{{XHTML_NS}}}html", nsmap={None: XHTML_NS, "epub": EPUB_NS})
    html_node.set("lang", language)
    html_node.set("{http://www.w3.org/XML/1998/namespace}lang", language)
    head = etree.SubElement(html_node, f"{{{XHTML_NS}}}head")
    etree.SubElement(head, f"{{{XHTML_NS}}}meta", attrib={"charset": "utf-8"})
    title_node = etree.SubElement(head, f"{{{XHTML_NS}}}title")
    title_node.text = title
    for href in ("../styles/epub.css", "../styles/fonts.css", "../fonts/noto/index.css", "../katex/katex.min.css"):
        etree.SubElement(head, f"{{{XHTML_NS}}}link", attrib={"rel": "stylesheet", "type": "text/css", "href": href})
    body = etree.SubElement(html_node, f"{{{XHTML_NS}}}body", attrib={"class": "book"})
    for child in body_children:
        body.append(copy.deepcopy(child))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(etree.tostring(
        html_node,
        encoding="UTF-8",
        xml_declaration=True,
        doctype="<!DOCTYPE html>",
        method="xml",
    ))


def _ids(node):
    return [element.get("id") for element in node.iter() if element.get("id")]


def _rewrite_epub_links(node, current_name, id_to_file):
    for element in node.iter():
        for attr in ("href", "src", "poster"):
            value = element.get(attr)
            if not value:
                continue
            if value.startswith("#"):
                fragment = value[1:]
                target = id_to_file.get(fragment)
                if target and target != current_name:
                    element.set(attr, target + "#" + fragment)
            elif value.startswith("media/"):
                element.set(attr, "../" + value)


def _media_type(path):
    suffix = Path(path).suffix.lower()
    return {
        ".css": "text/css",
        ".html": "application/xhtml+xml",
        ".xhtml": "application/xhtml+xml",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".avif": "image/avif",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".txt": "text/plain",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def _build_epub(document, book_root, work_dir, destination, metadata):
    package = work_dir / "epub-package"
    if package.exists():
        shutil.rmtree(package)
    epub = package / "EPUB"
    text_dir = epub / "text"
    styles_dir = epub / "styles"
    text_dir.mkdir(parents=True)
    styles_dir.mkdir(parents=True)

    (package / "mimetype").write_bytes(b"application/epub+zip")
    container_dir = package / "META-INF"
    container_dir.mkdir()
    (container_dir / "container.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container xmlns="' + CONTAINER_NS + '" version="1.0">'
        '<rootfiles><rootfile full-path="EPUB/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>\n',
        encoding="utf-8",
    )

    _copy_tree(document.media_dir, epub / "media")
    _copy_tree(work_dir / "fonts", epub / "fonts")
    _copy_tree(work_dir / "katex", epub / "katex")
    _copy_tree(work_dir / "licenses", epub / "licenses")
    for name in ("epub.css", "tokens.css"):
        shutil.copyfile(work_dir / name, styles_dir / name)
    (styles_dir / "fonts.css").write_text(
        '@import url("../fonts/noto/index.css");\n'
        '@font-face{font-family:"Pontano Sans";font-style:normal;font-weight:300 700;'
        'src:url("../fonts/pontano-sans.woff2") format("woff2");}\n'
        '@font-face{font-family:"Roboto Mono";font-style:normal;font-weight:100 700;'
        'src:url("../fonts/roboto-mono.woff2") format("woff2");}\n',
        encoding="utf-8",
    )

    # The same mark used by the site becomes the EPUB's accessible cover image.
    cover_source = Path(book_root) / "src/assets/icons/perceptual-grade-512-opaque.png"
    if not cover_source.is_file():
        raise ValueError("Missing handbook cover icon")
    shutil.copyfile(cover_source, epub / "media/cover.png")
    cover = etree.Element("section", attrib={"class": "cover"})
    logo = etree.SubElement(cover, "img", attrib={"src": "../media/cover.png", "alt": "Perceptual Grade"})
    logo.tail = ""
    heading = etree.SubElement(cover, "h1")
    heading.text = document.title
    edition = etree.SubElement(cover, "p", attrib={"class": "edition"})
    edition.text = "简体中文版" if document.language == "zh-Hans" else "English edition"
    cover_path = text_dir / "cover.xhtml"
    _write_xhtml(cover_path, document.title, document.language, [cover])

    source_root = html.document_fromstring(document.book_html.read_bytes())
    front_node = source_root.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' front-matter ')]")[0]
    toc_node = source_root.xpath("//nav[contains(concat(' ', normalize-space(@class), ' '), ' toc ')]")[0]
    figure_nodes = source_root.xpath("//nav[contains(concat(' ', normalize-space(@class), ' '), ' figure-list ')]")
    front_children = [front_node, toc_node, *figure_nodes]
    front_path = text_dir / "front.xhtml"

    part_files = {}
    chapter_files = {}
    for index, part in enumerate(document.parts, start=1):
        filename = f"part-{index:02d}.xhtml"
        part_files[part["index"]] = filename
        _write_xhtml(text_dir / filename, part["title"], document.language, [part["section"]])
    for index, chapter in enumerate(document.chapters, start=1):
        filename = f"chapter-{index:02d}.xhtml"
        chapter_files[chapter["id"]] = filename
        _write_xhtml(text_dir / filename, chapter["title"], document.language, [chapter["section"]])

    id_to_file = {}
    for part in document.parts:
        filename = part_files[part["index"]]
        for identifier in _ids(part["section"]):
            id_to_file[identifier] = filename
    for chapter in document.chapters:
        filename = chapter_files[chapter["id"]]
        for identifier in _ids(chapter["section"]):
            id_to_file[identifier] = filename
    for node in front_children:
        for identifier in _ids(node):
            id_to_file[identifier] = "front.xhtml"

    front_clone = [copy.deepcopy(node) for node in front_children]
    front_wrapper = etree.Element("div")
    for node in front_clone:
        front_wrapper.append(node)
    _rewrite_epub_links(front_wrapper, "front.xhtml", id_to_file)
    _write_xhtml(front_path, document.title, document.language, list(front_wrapper))

    # Re-emit section pages with cross-chapter links resolved to their XHTML files.
    for part in document.parts:
        filename = part_files[part["index"]]
        section = copy.deepcopy(part["section"])
        _rewrite_epub_links(section, filename, id_to_file)
        _write_xhtml(text_dir / filename, part["title"], document.language, [section])
    for chapter in document.chapters:
        filename = chapter_files[chapter["id"]]
        section = copy.deepcopy(chapter["section"])
        _rewrite_epub_links(section, filename, id_to_file)
        _write_xhtml(text_dir / filename, chapter["title"], document.language, [section])

    nav = etree.Element(f"{{{XHTML_NS}}}html", nsmap={None: XHTML_NS, "epub": EPUB_NS})
    nav.set("lang", document.language)
    nav.set("{http://www.w3.org/XML/1998/namespace}lang", document.language)
    nav_head = etree.SubElement(nav, f"{{{XHTML_NS}}}head")
    etree.SubElement(nav_head, f"{{{XHTML_NS}}}title").text = "目录" if document.language == "zh-Hans" else "Contents"
    nav_body = etree.SubElement(nav, f"{{{XHTML_NS}}}body")
    nav_node = etree.SubElement(nav_body, f"{{{XHTML_NS}}}nav", attrib={f"{{{EPUB_NS}}}type": "toc", "id": "toc"})
    etree.SubElement(nav_node, f"{{{XHTML_NS}}}h1").text = "目录" if document.language == "zh-Hans" else "Contents"
    nav_list = etree.SubElement(nav_node, f"{{{XHTML_NS}}}ol")

    def add_nav_link(parent, href, label):
        item = etree.SubElement(parent, f"{{{XHTML_NS}}}li")
        etree.SubElement(item, f"{{{XHTML_NS}}}a", attrib={"href": href}).text = label
        return item

    for chapter in document.chapters:
        if chapter["part_index"] is None:
            number = ".".join(map(str, chapter["number"])) if chapter["number"] else ""
            add_nav_link(nav_list, chapter_files[chapter["id"]] + "#" + chapter["id"], (number + ". " if number else "") + chapter["title"])
    for part in document.parts:
        part_file = part_files[part["index"]]
        part_id = part["id"]
        part_item = add_nav_link(nav_list, part_file + "#" + part_id, part["title"])
        child_list = etree.SubElement(part_item, f"{{{XHTML_NS}}}ol")
        for chapter in document.chapters:
            if chapter["part_index"] != part["index"]:
                continue
            number = ".".join(map(str, chapter["number"])) if chapter["number"] else ""
            label = (number + ". " if number else "") + chapter["title"]
            add_nav_link(child_list, chapter_files[chapter["id"]] + "#" + chapter["id"], label)
    nav_path = epub / "nav.xhtml"
    nav_path.write_bytes(etree.tostring(nav, encoding="UTF-8", xml_declaration=True, doctype="<!DOCTYPE html>", method="xml"))

    # The EPUB spine is derived from SUMMARY order: front matter, unnumbered pages,
    # then each part title followed by its chapters.
    spine_filenames = ["text/cover.xhtml", "text/front.xhtml"]
    for chapter in document.chapters:
        if chapter["part_index"] is None:
            spine_filenames.append("text/" + chapter_files[chapter["id"]])
    for part in document.parts:
        spine_filenames.append("text/" + part_files[part["index"]])
        spine_filenames.extend(
            "text/" + chapter_files[chapter["id"]]
            for chapter in document.chapters
            if chapter["part_index"] == part["index"]
        )

    package_tag = f"{{{OPF_NS}}}package"
    opf = etree.Element(package_tag, attrib={
        "version": "3.0",
        "unique-identifier": "book-id",
        "prefix": "dcterms: http://purl.org/dc/terms/",
    })
    metadata_node = etree.SubElement(opf, f"{{{OPF_NS}}}metadata")
    etree.SubElement(metadata_node, f"{{{DC_NS}}}identifier", attrib={"id": "book-id"}).text = metadata["identifier"]
    etree.SubElement(metadata_node, f"{{{DC_NS}}}title").text = document.title
    etree.SubElement(metadata_node, f"{{{DC_NS}}}language").text = document.language
    etree.SubElement(metadata_node, f"{{{DC_NS}}}creator").text = metadata["author"]
    etree.SubElement(metadata_node, f"{{{DC_NS}}}description").text = metadata["description"]
    etree.SubElement(metadata_node, f"{{{OPF_NS}}}meta", attrib={"property": "dcterms:modified"}).text = FIXED_DATE
    manifest_node = etree.SubElement(opf, f"{{{OPF_NS}}}manifest")
    item_ids = {}
    package_files = [path for path in sorted(epub.rglob("*")) if path.is_file()]
    package_files.extend(path for path in sorted(text_dir.rglob("*")) if path.is_file())
    package_files = sorted({path.resolve() for path in package_files})
    for path in package_files:
        relative = path.relative_to(epub).as_posix()
        item_id = "item-" + hashlib.sha256(relative.encode()).hexdigest()[:16]
        item_ids[relative] = item_id
        properties = "nav" if relative == "nav.xhtml" else "cover-image" if relative == "media/cover.png" else None
        attributes = {"id": item_id, "href": relative, "media-type": _media_type(path)}
        if properties:
            attributes["properties"] = properties
        etree.SubElement(manifest_node, f"{{{OPF_NS}}}item", attrib=attributes)
    spine = etree.SubElement(opf, f"{{{OPF_NS}}}spine")
    for name in spine_filenames:
        etree.SubElement(spine, f"{{{OPF_NS}}}itemref", attrib={"idref": item_ids[name]})
    (epub / "content.opf").write_bytes(etree.tostring(opf, encoding="UTF-8", xml_declaration=True, pretty_print=True))
    return write_epub(package, destination)


def _version_checks(node, versions):
    node_version = subprocess.run([str(node), "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if node_version != versions["node"]:
        raise ValueError(f"Expected Node {versions['node']}, received {node_version}")
    if weasyprint.__version__ != versions["weasyprint"]:
        raise ValueError(f"Expected WeasyPrint {versions['weasyprint']}, received {weasyprint.__version__}")
    if pikepdf.__version__ != versions["pikepdf"]:
        raise ValueError(f"Expected pikepdf {versions['pikepdf']}, received {pikepdf.__version__}")


def build(args):
    site_root = args.site.resolve()
    book_root = args.book.resolve()
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Book output must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    versions = json.loads(args.versions.read_text(encoding="utf-8"))
    _version_checks(args.node, versions)
    native_runtime = json.loads((args.native_runtime / "native_runtime_manifest.json").read_text(encoding="utf-8"))

    with (book_root / "book.toml").open("rb") as stream:
        book_config = tomllib.load(stream)["book"]
    authors = book_config.get("authors", [])
    author = ", ".join(authors) if authors else ""
    description = book_config.get("description", "")
    site_manifest = site_root / "site-manifest.json"
    if not site_manifest.is_file():
        raise ValueError("The existing mdBook site manifest is required for derived outputs")

    work = output / "working"
    pdf_dir = output / "pdf"
    epub_dir = output / "epub"
    license_dir = output / "licenses"
    pdf_dir.mkdir()
    epub_dir.mkdir()
    license_dir.mkdir()

    docs = {}
    for language in LANGUAGES:
        edition_work = work / language
        front = args.front_matter / (language + "/front-matter.html")
        doc = build_document(
            site_root=site_root,
            book_root=book_root,
            language=language,
            front_matter=front,
            output_dir=edition_work,
            node=args.node,
            math_renderer=args.math_renderer,
            katex_js=args.katex_js,
            katex_css=args.katex_css,
            katex_package=args.katex_package,
            noto_package=args.noto_package,
            font_sans=args.font_sans,
            font_mono=args.font_mono,
            theme_dir=args.theme,
        )
        docs[language] = doc

    pdf_font_stylesheets, pdf_font_licenses = _prepare_pdf_fonts(
        work,
        args.pdf_fonts,
    )

    license_sources = {
        "pontano-sans-OFL.txt": args.font_sans_license,
        "roboto-mono-OFL.txt": args.font_mono_license,
        "Noto-Sans-SC-OFL.txt": work / "en/fonts/noto/LICENSE",
        "KaTeX-MIT.txt": work / "en/katex/LICENSE",
    }
    for name, source in license_sources.items():
        if not Path(source).is_file():
            raise ValueError(f"Missing print license notice: {source}")
        shutil.copyfile(source, license_dir / name)
    shutil.copytree(license_dir, pdf_dir / "licenses")
    for name, source in pdf_font_licenses.items():
        if not source.is_file():
            raise ValueError(f"Missing PDF font license notice: {source}")
        shutil.copyfile(source, pdf_dir / "licenses" / name)
    for language in LANGUAGES:
        (work / language / "licenses").mkdir(parents=True, exist_ok=True)
        for path in license_dir.iterdir():
            shutil.copyfile(path, work / language / "licenses" / path.name)

    edition_manifests = {}
    site_document = json.loads(site_manifest.read_text(encoding="utf-8"))
    for language, doc in docs.items():
        pdf_path = pdf_dir / f"perceptual-grade-{language}.pdf"
        epub_path = epub_dir / f"perceptual-grade-{language}.epub"
        render_pdf(
            doc.book_html,
            pdf_path,
            doc.title,
            author,
            description,
            language,
            first_chapter_title=doc.chapters[0]["title"],
            pdf_stylesheet=pdf_font_stylesheets[language],
        )
        identifier = "urn:sha256:" + hashlib.sha256(
            (language + "\n" + "\n".join(chapter["path"] for chapter in doc.chapters)).encode()
        ).hexdigest()
        _build_epub(
            doc,
            book_root,
            work / language,
            epub_path,
            {"author": author, "description": description, "identifier": identifier},
        )
        edition_manifests[language] = {
            "chapters": [
                {"path": chapter["path"], "id": chapter["id"], "number": chapter["number"], "title": chapter["title"]}
                for chapter in doc.chapters
            ],
            "parts": [{"title": part["title"], "id": part["id"]} for part in doc.parts],
            "figures": doc.figures,
            "math_expressions_rendered": doc.math_expressions,
            "remaining_data_tex": 0,
            "outputs": {
                pdf_path.relative_to(output).as_posix(): {"sha256": digest(pdf_path), "bytes": pdf_path.stat().st_size},
                epub_path.relative_to(output).as_posix(): {"sha256": digest(epub_path), "bytes": epub_path.stat().st_size},
            },
        }

    document_output = output / "documents"
    work.replace(document_output)
    manifest = {
        "schema": 1,
        "build_target": "root//products/perceptual-grade-book:book",
        "invocation": "buck2" if os.environ.get("PG_BUCK_ACTION") == "1" else "authoring-preview",
        "site_manifest_sha256": digest(site_manifest),
        "site_files": site_document["site_files"],
        "tools": versions,
        "python_tools": {"weasyprint": weasyprint.__version__, "pikepdf": pikepdf.__version__},
        "native_runtime": native_runtime,
        "languages": edition_manifests,
        "license_files": inventory(license_dir),
        "pdf_license_files": inventory(pdf_dir / "licenses"),
        "pdf_font_inputs": inventory(args.pdf_fonts),
        "outputs": inventory(output / "pdf") | inventory(output / "epub"),
        "documents": inventory(document_output),
    }
    (output / "print-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"WeasyPrint {weasyprint.__version__}: built PDF and EPUB editions for {', '.join(LANGUAGES)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "site", "book", "front-matter", "theme", "katex-js", "katex-css", "katex-package",
        "font-sans", "font-mono", "font-sans-license", "font-mono-license", "noto-package",
        "pdf-fonts", "node", "math-renderer", "versions", "native-runtime", "output-dir",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
