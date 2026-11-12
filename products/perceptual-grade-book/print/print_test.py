"""Integration checks for the derived PDF and EPUB editions."""

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import tomllib
import unittest
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit

from lxml import html
from fontTools.ttLib import TTFont
import pikepdf
from pypdf import PdfReader

from pg_book_print.document import _copy_media, _summary_items
from pg_book_print.build import _rewrite_epub_links
from pg_book_print.pdf import render_pdf


ROOT = Path(__file__).parent
OPF_NS = "http://www.idpf.org/2007/opf"
XHTML_NS = "http://www.w3.org/1999/xhtml"
CHART_PATHS = {
    name: f"assets/{directory}/{name}.svg"
    for directory, names in (
        ("figures", ("linear-basis", "tone-curves", "tone-saturation", "color-tone-weights",
                     "color-drivers", "color-hue-concentration", "guard-boundary", "guard-energy",
                     "lut-input-grid", "lut-interpolation", "render-benchmark")),
        ("illustrations", ("lut-shaper-errors", "lut-shaper-placement",
                           "lut-domain128-errors", "lut-domain128-placement")),
    )
    for name in names
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def outline_titles(items):
    result = []
    for item in items:
        result.append(item.title)
        result.extend(outline_titles(item.children))
    return result


def embedded_font(font):
    candidates = [font]
    descendants = font.get("/DescendantFonts", [])
    candidates.extend(descendants)
    for candidate in candidates:
        descriptor = candidate.get("/FontDescriptor")
        if descriptor and any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")):
            return True
    return False


class PrintBuildChecks:
    @classmethod
    def setUpClass(cls):
        cls.book = ROOT / "books" / cls.publication
        cls.site = ROOT / "site"
        cls.site_manifest = ROOT / "site-manifest.json"
        cls.archive = ROOT / "site.zip"
        cls.documents = ROOT / cls.publication / "documents"
        cls.pdf_dir = ROOT / cls.publication / "pdf"
        cls.epub_dir = ROOT / cls.publication / "epub"
        cls.print_manifest = json.loads((ROOT / cls.publication / "print-manifest.json").read_text(encoding="utf-8"))
        cls.site_data = json.loads(cls.site_manifest.read_text(encoding="utf-8"))
        cls.theme = ROOT / "theme"
        with (cls.book / "book.toml").open("rb") as stream:
            cls.book_config = tomllib.load(stream)["book"]

    def test_site_and_archive_match_the_print_source_inventory(self):
        self.assertEqual(self.print_manifest["publication"], self.publication)
        self.assertEqual(self.print_manifest["site_prefix"], self.site_prefix)
        self.assertEqual(self.print_manifest["build_target"], "root//products/perceptual-grade-book:" + self.publication)
        self.assertEqual(self.print_manifest["invocation"], "buck2")
        self.assertEqual(self.print_manifest["site_manifest_sha256"], sha(self.site_manifest))
        self.assertEqual(self.print_manifest["site_files"], self.site_data["site_files"])
        self.assertEqual(set(self.print_manifest["languages"]), set(self.languages))
        for suffix, directory in (("pdf", self.pdf_dir), ("epub", self.epub_dir)):
            self.assertEqual(
                {path.name for path in directory.glob("*." + suffix)},
                {f"{self.publication}-{language}.{suffix}" for language in self.languages},
            )
        self.assertEqual(
            {path.relative_to(self.book).as_posix(): sha(path) for path in self.book.rglob("*") if path.is_file()},
            self.print_manifest["book_files"],
        )
        self.assertEqual(
            {
                path.relative_to(self.site).as_posix(): sha(path)
                for path in sorted(self.site.rglob("*"))
                if path.is_file() and path.relative_to(self.site).as_posix() != "site-manifest.json"
            },
            self.site_data["site_files"],
        )
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), set(self.site_data["site_files"]) | {"site-manifest.json"})
            self.assertEqual(archive.read("site-manifest.json"), self.site_manifest.read_bytes())
            for name, expected in self.site_data["site_files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected, name)

    def test_print_documents_match_summary_and_render_math_statically(self):
        for language in self.languages:
            with self.subTest(language=language):
                _, chapters, parts = _summary_items(self.book, language)
                edition = self.print_manifest["languages"][language]
                self.assertEqual([item["path"] for item in edition["chapters"]], [item["path"] for item in chapters])
                self.assertEqual(
                    any(item["path"] == "development/next-policies.md" for item in edition["chapters"]),
                    self.publication == "technical-report",
                )
                paths = {item["path"] for item in edition["chapters"]}
                if self.publication == "user-manual":
                    self.assertTrue(any(path.startswith("guide/") for path in paths))
                    self.assertFalse(any(path.startswith(("theory/", "development/")) for path in paths))
                else:
                    self.assertTrue(any(path.startswith("theory/") for path in paths))
                    self.assertTrue(any(path.startswith("development/") for path in paths))
                    self.assertFalse(any(path.startswith("guide/") for path in paths))
                self.assertEqual([item["title"] for item in edition["parts"]], [item["title"] for item in parts])
                self.assertGreater(edition["math_expressions_rendered"], 0)
                self.assertEqual(edition["remaining_data_tex"], 0)

                book_html = self.documents / language / "book.html"
                parsed = html.document_fromstring(book_html.read_bytes())
                self.assertEqual("Next Blender policy machines" in parsed.text_content(), self.publication == "technical-report")
                policy_figures = parsed.xpath("//img[contains(@src, '/next-policy/')]")
                self.assertEqual(len(policy_figures), 13 if self.publication == "technical-report" else 0)
                if self.publication == "technical-report":
                    policy_heading = parsed.xpath("//h1[@id='next-blender-policy-machines']")[0]
                    policy_chapter = next(item for item in edition["chapters"] if item["path"] == "development/next-policies.md")
                    number = ".".join(map(str, policy_chapter["number"]))
                    self.assertEqual(" ".join(" ".join(policy_heading.itertext()).split()), number + " Next Blender policy machines")
                    policy_captions = parsed.xpath(
                        "//section[@id='chapter-section-next-blender-policy-machines']//figcaption"
                    )
                    self.assertEqual(len(policy_captions), 13)
                    for index, caption in enumerate(policy_captions, start=1):
                        self.assertTrue(
                            " ".join(caption.itertext()).startswith(f"Figure {number}.{index} "),
                            "Print caption number must precede its description",
                        )
                pdf_stylesheet = self.documents / "pdf-fonts" / (language + ".css")
                pdf_font_css = pdf_stylesheet.read_text(encoding="utf-8")
                self.assertIn('@import url("tinos/index.css")', pdf_font_css)
                self.assertEqual('"Tinos", "Noto Serif SC", serif' in pdf_font_css, language == "zh-Hans")
                self.assertFalse(parsed.xpath("//*[@data-tex]"))
                self.assertGreater(len(parsed.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' katex ')]")), 0)
                self.assertFalse(parsed.xpath("//iframe|//video|//audio"))
                for image in parsed.xpath("//img[@src]"):
                    reference = image.get("src")
                    if reference.startswith(("http:", "https:", "data:")):
                        continue
                    target = (book_html.parent / reference).resolve()
                    self.assertTrue(target.is_file(), reference)
                    if "/assets/demos/" in reference:
                        self.assertIn("-still.", reference)

    def test_same_print_document_links_remain_internal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "site"
            edition = root / "manual/en"
            downloads = root / "downloads"
            report = root / "technical/en/theory"
            edition.mkdir(parents=True)
            downloads.mkdir()
            report.mkdir(parents=True)
            origin = edition / "print.html"
            origin.write_text("<html><body></body></html>", encoding="utf-8")
            (downloads / "release.zip").write_bytes(b"historical download")
            (report / "color.html").write_text('<h1 id="warp">Warp</h1>', encoding="utf-8")
            main = html.document_fromstring(
                '<div><a href="print.html#chapter-tone">Tone</a>'
                '<a href="../../downloads/release.zip">Download</a>'
                '<a href="../../technical/en/theory/color.html#warp">Technical Report: Warp</a></div>'
            )

            _copy_media(main, root, origin, Path(temporary) / "derived", {"chapter-tone"})

            self.assertEqual(main.xpath("string(//a[1]/@href)"), "#chapter-tone")
            self.assertEqual(
                main.xpath("string(//a[2]/@href)"),
                "https://rei277hz.github.io/perceptual-grade/downloads/release.zip",
            )
            self.assertEqual(
                main.xpath("string(//a[3]/@href)"),
                "https://rei277hz.github.io/perceptual-grade/technical/en/theory/color.html#warp",
            )

    def test_epub_rewriter_routes_encoded_chinese_fragments(self):
        fragment = "%E5%AE%89%E8%A3%85%E4%B8%8E%E8%BF%9E%E6%8E%A5"
        main = html.document_fromstring(f'<div><a href="#{fragment}">Install</a></div>')

        _rewrite_epub_links(
            main, "chapter-01.xhtml", {"安装与连接": "chapter-02.xhtml"}
        )

        self.assertEqual(
            main.xpath("string(//a/@href)"),
            "chapter-02.xhtml#" + fragment,
        )

    def test_vector_charts_keep_their_bytes_links_and_pdf_destinations(self):
        for language in self.languages:
            book_html = self.documents / language / "book.html"
            parsed = html.document_fromstring(book_html.read_bytes())
            reader = PdfReader(str(self.pdf_dir / f"{self.publication}-{language}.pdf"))
            expected = set(CHART_PATHS) if self.publication == "technical-report" else set()
            found = set()
            for image in parsed.xpath("//figure//img[@src]"):
                name = Path(image.get("src")).stem
                if name not in CHART_PATHS:
                    continue
                with self.subTest(language=language, chart=name):
                    source = "media/" + CHART_PATHS[name]
                    self.assertEqual(image.get("src"), source)
                    self.assertTrue(image.get("alt", "").strip())
                    self.assertEqual((book_html.parent / source).read_bytes(),
                                     (self.site / CHART_PATHS[name]).read_bytes())
                    figure = image.xpath("ancestor::figure[1]")[0]
                    self.assertTrue(figure.xpath("./figcaption"))
                    identifier = figure.get("id")
                    self.assertIn(identifier, reader.named_destinations)
                    page = reader.get_destination_page_number(reader.named_destinations[identifier])
                    self.assertGreaterEqual(page, 0)
                    self.assertLess(page, len(reader.pages))
                    self.assertTrue(figure.xpath(".//a[@href=$source]", source=source))
                    found.add(name)
            self.assertEqual(found, expected)

            with zipfile.ZipFile(self.epub_dir / f"{self.publication}-{language}.epub") as archive:
                package = ET.fromstring(archive.read("EPUB/content.opf"))
                items = {item.get("href"): item for item in
                         package.findall(f"{{{OPF_NS}}}manifest/{{{OPF_NS}}}item")}
                referenced = set()
                for item in items.values():
                    if item.get("media-type") != "application/xhtml+xml":
                        continue
                    chapter = ET.fromstring(archive.read("EPUB/" + item.get("href")))
                    for image in chapter.findall(f".//{{{XHTML_NS}}}img"):
                        name = Path(image.get("src", "")).stem
                        if name in CHART_PATHS:
                            self.assertEqual(image.get("src"), "../media/" + CHART_PATHS[name])
                            referenced.add(name)
                self.assertEqual(referenced, expected)
                for name in expected:
                    with self.subTest(language=language, epub_chart=name):
                        relative = "media/" + CHART_PATHS[name]
                        self.assertIn(relative, items)
                        self.assertEqual(items[relative].get("media-type"), "image/svg+xml")
                        self.assertEqual(archive.read("EPUB/" + relative),
                                         (self.site / CHART_PATHS[name]).read_bytes())
                        self.assertNotIn("EPUB/" + relative.removesuffix(".svg") + ".png",
                                         archive.namelist())

    def test_print_skins_use_shared_color_tokens(self):
        for name in ("print.css", "epub.css"):
            with self.subTest(stylesheet=name):
                stylesheet = (self.theme / name).read_text(encoding="utf-8")
                self.assertIn('@import url("tokens.css")', stylesheet)
                self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", stylesheet))
                if name == "print.css":
                    blank_page = re.search(r"@page\s+body:blank\s*\{(?P<body>.*?)\n\}", stylesheet, re.S)
                    self.assertIsNotNone(blank_page)
                    self.assertEqual(
                        re.findall(r"content:\s*none", blank_page["body"]),
                        ["content: none", "content: none"],
                    )

    def test_pdf_metadata_outline_labels_fonts_and_determinism(self):
        for language in self.languages:
            with self.subTest(language=language):
                pdf_path = self.pdf_dir / f"{self.publication}-{language}.pdf"
                with pikepdf.open(pdf_path) as pdf:
                    self.assertGreater(len(pdf.pages), 0)
                    self.assertEqual(str(pdf.docinfo["/Title"]), self.book_config["title"])
                    self.assertEqual(str(pdf.docinfo["/Author"]), ", ".join(self.book_config["authors"]))
                    self.assertIn("/PageLabels", pdf.Root)
                    linked_assets = 0
                    for page in pdf.pages:
                        for annotation in page.obj.get("/Annots", []):
                            action = annotation.get("/A", {})
                            if action.get("/S") == pikepdf.Name("/URI"):
                                uri = str(action.get("/URI"))
                                self.assertFalse(uri.startswith("file:"))
                                linked_assets += uri.startswith("https://rei277hz.github.io/perceptual-grade/assets/")
                    self.assertGreater(linked_assets, 0, "PDF figure links should use portable site URLs")
                    titles = outline_titles(pdf.open_outline().root)
                    edition = self.print_manifest["languages"][language]
                    font_names = []
                    for part in edition["parts"]:
                        self.assertTrue(any(part["title"] in title for title in titles))
                    for chapter in edition["chapters"]:
                        self.assertTrue(any(chapter["title"] in title for title in titles))

                    found_font = False
                    for page in pdf.pages:
                        fonts = page.obj.get("/Resources", {}).get("/Font", {})
                        for font in fonts.values():
                            self.assertNotEqual(str(font.get("/Subtype")), "/Type3")
                            self.assertTrue(embedded_font(font), "PDF font is not embedded")
                            font_names.append(str(font.get("/BaseFont", "")))
                            for descendant in font.get("/DescendantFonts", []):
                                font_names.append(str(descendant.get("/BaseFont", "")))
                            found_font = True
                    self.assertTrue(found_font)
                    if language == "en":
                        self.assertTrue(
                            any("Tinos" in name for name in font_names),
                            "English PDF does not embed its pinned Tinos font",
                        )
                    else:
                        normalized_names = [re.sub(r"[^a-z]", "", name.lower()) for name in font_names]
                        self.assertTrue(any("tinos" in name for name in normalized_names), "Chinese PDF does not embed Tinos for Latin text")
                        self.assertTrue(
                            any("notoserifsc" in name for name in normalized_names),
                            "Simplified Chinese PDF does not embed its pinned Noto Serif SC font",
                        )

                if language == "zh-Hans":
                    extracted_text = "".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
                    compact_text = re.sub(r"\s+", "", extracted_text)
                    for expected in ("用户手册", "选择工作白点", "共享与复用调色", "安装与连接", "白平衡"):
                        self.assertTrue(expected in compact_text, f"Chinese PDF text extraction is missing {expected}")

                if language == "en" and self.publication == "user-manual":
                    self.assertLess(pdf_path.stat().st_size, 40 * 1024 * 1024)
                    with tempfile.TemporaryDirectory() as temporary:
                        moved_documents = Path(temporary) / "documents"
                        shutil.copytree(
                            self.documents / language, moved_documents / language,
                            ignore=shutil.ignore_patterns("epub-package"),
                        )
                        shutil.copytree(
                            self.documents / "pdf-fonts", moved_documents / "pdf-fonts",
                        )
                        repeated = Path(temporary) / "first.pdf"
                        render_pdf(
                            moved_documents / language / "book.html",
                            repeated,
                            self.book_config["title"],
                            ", ".join(self.book_config["authors"]),
                            self.book_config["description"],
                            language,
                            first_chapter_title=edition["chapters"][0]["title"],
                            pdf_stylesheet=moved_documents / "pdf-fonts/en.css",
                        )
                        repeated_again = Path(temporary) / "second.pdf"
                        render_pdf(
                            moved_documents / language / "book.html",
                            repeated_again,
                            self.book_config["title"],
                            ", ".join(self.book_config["authors"]),
                            self.book_config["description"],
                            language,
                            first_chapter_title=edition["chapters"][0]["title"],
                            pdf_stylesheet=moved_documents / "pdf-fonts/en.css",
                        )
                        self.assertEqual(sha(repeated), sha(repeated_again))
                        self.assertEqual(sha(repeated), sha(pdf_path))

    def test_chinese_pdf_unicode_maps_match_embedded_glyphs(self):
        if "zh-Hans" not in self.languages:
            self.skipTest("The technical report is English-only")
        # Fontsource CJK shards reuse glyph IDs for different characters. When
        # a PDF renderer confuses those fonts, text extraction and the visible
        # glyph can disagree even though the font is embedded successfully.
        expected_characters = set("用户手册选择工作白点安装与连接")
        checked_characters = set()
        checked_weights = set()
        visited = set()
        with pikepdf.open(self.pdf_dir / "user-manual-zh-Hans.pdf") as pdf:
            for page in pdf.pages:
                for font in page.obj.get("/Resources", {}).get("/Font", {}).values():
                    if font.objgen in visited:
                        continue
                    visited.add(font.objgen)
                    name = re.sub(r"[^a-z]", "", str(font.get("/BaseFont", "")).lower())
                    if "notoserifsc" not in name:
                        continue
                    self.assertEqual(str(font["/Encoding"]), "/Identity-H")
                    descendant = font["/DescendantFonts"][0]
                    self.assertEqual(str(descendant["/CIDToGIDMap"]), "/Identity")
                    font_data = descendant["/FontDescriptor"]["/FontFile2"].read_bytes()
                    with TTFont(io.BytesIO(font_data)) as embedded:
                        cmap = embedded.getBestCmap()
                        self.assertIsNotNone(cmap, "Embedded Chinese font has no Unicode cmap")
                        unicode_map = font["/ToUnicode"].read_bytes()
                        for block in re.findall(rb"beginbfchar\s+(.*?)\s+endbfchar", unicode_map, re.S):
                            for cid_hex, text_hex in re.findall(rb"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>", block):
                                text = bytes.fromhex(text_hex.decode("ascii")).decode("utf-16-be")
                                if text not in expected_characters:
                                    continue
                                self.assertIn(ord(text), cmap, f"Chinese glyph missing for {text}")
                                self.assertEqual(
                                    int(cid_hex, 16),
                                    embedded.getGlyphID(cmap[ord(text)]),
                                    f"PDF Unicode map points to the wrong embedded glyph for {text}",
                                )
                                checked_characters.add(text)
                                checked_weights.add(embedded["OS/2"].usWeightClass)
        self.assertEqual(checked_characters, expected_characters)
        self.assertTrue({400, 700}.issubset(checked_weights), "Check both body and bold Chinese faces")

    def test_epub_nav_spine_and_resources_are_well_formed(self):
        for language in self.languages:
            with self.subTest(language=language):
                path = self.epub_dir / f"{self.publication}-{language}.epub"
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    self.assertEqual(names[0], "mimetype")
                    self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
                    package = ET.fromstring(archive.read("EPUB/content.opf"))
                    dc = "http://purl.org/dc/elements/1.1/"
                    self.assertEqual(package.findtext(f"{{{OPF_NS}}}metadata/{{{dc}}}title"), self.book_config["title"])
                    self.assertEqual(package.findtext(f"{{{OPF_NS}}}metadata/{{{dc}}}language"), language)
                    manifest = package.find(f"{{{OPF_NS}}}manifest")
                    spine = package.find(f"{{{OPF_NS}}}spine")
                    by_id = {item.get("id"): item for item in manifest.findall(f"{{{OPF_NS}}}item")}
                    spine_paths = [by_id[item.get("idref")].get("href") for item in spine.findall(f"{{{OPF_NS}}}itemref")]
                    nav_item = next(item for item in manifest.findall(f"{{{OPF_NS}}}item") if "nav" in item.get("properties", "").split())
                    nav_document = ET.fromstring(archive.read("EPUB/" + nav_item.get("href")))
                    nav_links = [node.get("href") for node in nav_document.findall(f".//{{{XHTML_NS}}}nav/{{{XHTML_NS}}}ol//{{{XHTML_NS}}}a")]
                    self.assertTrue(nav_links)
                    self.assertTrue(all(value.startswith("text/") for value in nav_links), nav_links)
                    for value in nav_links:
                        member, fragment = value.split("#", 1)
                        self.assertIn("EPUB/" + member, names, value)
                        target = ET.fromstring(archive.read("EPUB/" + member))
                        self.assertIn(fragment, {node.get("id") for node in target.iter()}, value)
                    chapter_bodies = "".join(
                        archive.read("EPUB/" + name).decode("utf-8")
                        for name in spine_paths if name.startswith("text/chapter-")
                    )
                    self.assertEqual("Next Blender policy machines" in chapter_bodies, self.publication == "technical-report")
                    self.assertEqual("next-policy/" in chapter_bodies, self.publication == "technical-report")
                    self.assertEqual(len(spine_paths), len(set(spine_paths)))
                    self.assertTrue(spine_paths[0].endswith("text/cover.xhtml"))
                    self.assertTrue(any("text/front.xhtml" == value for value in spine_paths))
                    spine_covers = []
                    for name in spine_paths:
                        if not name.endswith((".xhtml", ".html")):
                            continue
                        section_root = ET.fromstring(archive.read("EPUB/" + name))
                        covers = [node for node in section_root.iter()
                                  if node.tag == f"{{{XHTML_NS}}}section"
                                  and "cover" in (node.get("class") or "").split()]
                        spine_covers.extend((name, cover) for cover in covers)
                    self.assertEqual(len(spine_covers), 1)
                    self.assertEqual(spine_covers[0][0], "text/cover.xhtml")
                    for item in manifest.findall(f"{{{OPF_NS}}}item"):
                        member = "EPUB/" + item.get("href")
                        self.assertIn(member, names)
                        if item.get("media-type") == "application/xhtml+xml":
                            root = ET.fromstring(archive.read(member))
                            self.assertFalse(root.findall(".//*[@data-tex]"))
                            properties = set(item.get("properties", "").split())
                            self.assertEqual("mathml" in properties,
                                             bool(root.findall(".//{http://www.w3.org/1998/Math/MathML}math")), member)
                            self.assertEqual("svg" in properties,
                                             bool(root.findall(".//{http://www.w3.org/2000/svg}svg")), member)
                            for element in root.iter():
                                for attr in ("href", "src", "poster"):
                                    value = element.get(attr)
                                    if not value:
                                        continue
                                    url = urlsplit(value)
                                    if url.scheme or url.netloc:
                                        continue
                                    pieces = []
                                    for part in (PurePosixPath(member).parent / unquote(url.path or PurePosixPath(member).name)).parts:
                                        if part == "..":
                                            self.assertTrue(pieces, value)
                                            pieces.pop()
                                        elif part != ".":
                                            pieces.append(part)
                                    target = PurePosixPath(*pieces).as_posix()
                                    self.assertIn(target, names, value)
                                    if url.fragment:
                                        target_document = ET.fromstring(archive.read(target))
                                        self.assertIn(unquote(url.fragment), {node.get("id") for node in target_document.iter()}, value)
                edition = self.print_manifest["languages"][language]
                self.assertEqual(len([name for name in spine_paths if name.startswith("text/chapter-")]), len(edition["chapters"]))


class UserManualPrintTests(PrintBuildChecks, unittest.TestCase):
    publication = "user-manual"
    site_prefix = "manual"
    languages = ("en", "zh-Hans")


class TechnicalReportPrintTests(PrintBuildChecks, unittest.TestCase):
    publication = "technical-report"
    site_prefix = "technical"
    languages = ("en",)


if __name__ == "__main__":
    unittest.main()
