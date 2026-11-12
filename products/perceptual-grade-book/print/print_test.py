"""Integration checks for the derived PDF and EPUB editions."""

from copy import deepcopy
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

from lxml import html
from fontTools.ttLib import TTFont
import pikepdf
from pypdf import PdfReader

from pg_book_print.document import _copy_media, _summary_items
from pg_book_print.pdf import render_pdf


ROOT = Path(__file__).parent
LANGUAGES = ("en", "zh-Hans")
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


class PrintBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = ROOT / "book"
        cls.site = ROOT / "site"
        cls.site_manifest = ROOT / "site-manifest.json"
        cls.archive = ROOT / "site.zip"
        cls.documents = ROOT / "documents"
        cls.pdf_dir = ROOT / "pdf"
        cls.epub_dir = ROOT / "epub"
        cls.print_manifest = json.loads((ROOT / "print-manifest.json").read_text(encoding="utf-8"))
        cls.site_data = json.loads(cls.site_manifest.read_text(encoding="utf-8"))
        cls.baseline = json.loads((ROOT / "site-baseline.json").read_text(encoding="utf-8"))
        cls.theme = ROOT / "theme"
        with (cls.book / "book.toml").open("rb") as stream:
            cls.book_config = tomllib.load(stream)["book"]

    def test_site_and_archive_match_reviewed_baseline(self):
        self.assertEqual(sha(self.site_manifest), self.baseline["site_manifest_sha256"])
        self.assertEqual(sha(self.archive), self.baseline["site_archive_sha256"])
        self.assertEqual(
            {
                path.relative_to(self.site).as_posix(): sha(path)
                for path in sorted(self.site.rglob("*"))
                if path.is_file() and path.relative_to(self.site).as_posix() != "site-manifest.json"
            },
            self.site_data["site_files"],
        )

    def test_print_documents_match_summary_and_render_math_statically(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                _, chapters, parts = _summary_items(self.book, language)
                edition = self.print_manifest["languages"][language]
                self.assertEqual([item["path"] for item in edition["chapters"]], [item["path"] for item in chapters])
                self.assertEqual(
                    any(item["path"] == "development/next-policies.md" for item in edition["chapters"]),
                    language == "en",
                )
                self.assertEqual([item["title"] for item in edition["parts"]], [item["title"] for item in parts])
                self.assertGreater(edition["math_expressions_rendered"], 0)
                self.assertEqual(edition["remaining_data_tex"], 0)

                book_html = self.documents / language / "book.html"
                parsed = html.document_fromstring(book_html.read_bytes())
                self.assertEqual("Next Blender policy machines" in parsed.text_content(), language == "en")
                policy_figures = parsed.xpath("//img[contains(@src, '/next-policy/')]")
                self.assertEqual(len(policy_figures), 13 if language == "en" else 0)
                if language == "en":
                    policy_heading = parsed.xpath("//h1[@id='next-blender-policy-machines']")[0]
                    self.assertEqual(
                        " ".join(" ".join(policy_heading.itertext()).split()),
                        "2 Next Blender policy machines",
                    )
                    policy_captions = parsed.xpath(
                        "//section[@id='chapter-section-next-blender-policy-machines']//figcaption"
                    )
                    self.assertEqual(len(policy_captions), 13)
                    for index, caption in enumerate(policy_captions, start=1):
                        self.assertTrue(
                            " ".join(caption.itertext()).startswith(f"Figure 2.{index} "),
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
            edition = root / "en"
            downloads = root / "downloads"
            edition.mkdir(parents=True)
            downloads.mkdir()
            origin = edition / "print.html"
            origin.write_text("<html><body></body></html>", encoding="utf-8")
            (downloads / "release.zip").write_bytes(b"historical download")
            main = html.document_fromstring(
                '<div><a href="print.html#chapter-tone">Tone</a>'
                '<a href="../downloads/release.zip">Download</a></div>'
            )

            _copy_media(main, root, origin, Path(temporary) / "derived", {"chapter-tone"})

            self.assertEqual(main.xpath("string(//a[1]/@href)"), "#chapter-tone")
            self.assertEqual(
                main.xpath("string(//a[2]/@href)"),
                "https://rei277hz.github.io/perceptual-grade/downloads/release.zip",
            )

    def test_vector_charts_keep_their_bytes_links_and_pdf_destinations(self):
        for language in LANGUAGES:
            book_html = self.documents / language / "book.html"
            parsed = html.document_fromstring(book_html.read_bytes())
            reader = PdfReader(str(self.pdf_dir / f"perceptual-grade-{language}.pdf"))
            expected = set(CHART_PATHS)
            if language == "zh-Hans":
                expected.remove("render-benchmark")
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

            with zipfile.ZipFile(self.epub_dir / f"perceptual-grade-{language}.epub") as archive:
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

    def test_pdf_metadata_outline_labels_fonts_and_determinism(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                pdf_path = self.pdf_dir / f"perceptual-grade-{language}.pdf"
                with pikepdf.open(pdf_path) as pdf:
                    self.assertGreater(len(pdf.pages), 0)
                    self.assertEqual(str(pdf.docinfo["/Title"]), self.book_config["title"])
                    self.assertEqual(str(pdf.docinfo["/Author"]), ", ".join(self.book_config["authors"]))
                    self.assertIn("/PageLabels", pdf.Root)
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
                    for expected in ("白平衡", "自定义影调曲线", "选择性色彩调整", "参数纹理使用稳定容量", "架构与运行时"):
                        self.assertTrue(expected in compact_text, f"Chinese PDF text extraction is missing {expected}")

                if language == "en":
                    self.assertLess(pdf_path.stat().st_size, 40 * 1024 * 1024)
                    with tempfile.TemporaryDirectory() as temporary:
                        repeated = Path(temporary) / "first.pdf"
                        render_pdf(
                            self.documents / language / "book.html",
                            repeated,
                            self.book_config["title"],
                            ", ".join(self.book_config["authors"]),
                            self.book_config["description"],
                            language,
                        )
                        repeated_again = Path(temporary) / "second.pdf"
                        render_pdf(
                            self.documents / language / "book.html",
                            repeated_again,
                            self.book_config["title"],
                            ", ".join(self.book_config["authors"]),
                            self.book_config["description"],
                            language,
                        )
                        self.assertEqual(sha(repeated), sha(repeated_again))

    def test_chinese_pdf_unicode_maps_match_embedded_glyphs(self):
        # Fontsource CJK shards reuse glyph IDs for different characters. When
        # a PDF renderer confuses those fonts, text extraction and the visible
        # glyph can disagree even though the font is embedded successfully.
        expected_characters = set("参数纹理使用稳定容量架构与运行时")
        checked_characters = set()
        checked_weights = set()
        visited = set()
        with pikepdf.open(self.pdf_dir / "perceptual-grade-zh-Hans.pdf") as pdf:
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
        for language in LANGUAGES:
            with self.subTest(language=language):
                path = self.epub_dir / f"perceptual-grade-{language}.epub"
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    self.assertEqual(names[0], "mimetype")
                    self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
                    package = ET.fromstring(archive.read("EPUB/content.opf"))
                    manifest = package.find(f"{{{OPF_NS}}}manifest")
                    spine = package.find(f"{{{OPF_NS}}}spine")
                    by_id = {item.get("id"): item for item in manifest.findall(f"{{{OPF_NS}}}item")}
                    spine_paths = [by_id[item.get("idref")].get("href") for item in spine.findall(f"{{{OPF_NS}}}itemref")]
                    chapter_bodies = "".join(
                        archive.read("EPUB/" + name).decode("utf-8")
                        for name in spine_paths if name.startswith("text/chapter-")
                    )
                    self.assertEqual("Next Blender policy machines" in chapter_bodies, language == "en")
                    self.assertEqual("next-policy/" in chapter_bodies, language == "en")
                    self.assertEqual(len(spine_paths), len(set(spine_paths)))
                    self.assertTrue(spine_paths[0].endswith("text/cover.xhtml"))
                    self.assertTrue(any("text/front.xhtml" == value for value in spine_paths))
                    for item in manifest.findall(f"{{{OPF_NS}}}item"):
                        member = "EPUB/" + item.get("href")
                        self.assertIn(member, names)
                        if item.get("media-type") == "application/xhtml+xml":
                            root = ET.fromstring(archive.read(member))
                            self.assertFalse(root.findall(".//*[@data-tex]"))
                edition = self.print_manifest["languages"][language]
                self.assertEqual(len([name for name in spine_paths if name.startswith("text/chapter-")]), len(edition["chapters"]))


if __name__ == "__main__":
    unittest.main()
