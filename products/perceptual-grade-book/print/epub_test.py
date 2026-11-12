"""Focused tests for deterministic EPUB archive packaging."""

from pathlib import Path
import tempfile
import unittest
import zipfile

from pg_book_print.epub import write_epub


_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
_PACKAGE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:example:test</dc:identifier></metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="style" href="style.css" media-type="text/css"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>"""


class EpubArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        (self.package / "META-INF").mkdir(parents=True)
        (self.package / "EPUB" / "images").mkdir(parents=True)
        self.write("mimetype", b"application/epub+zip")
        self.write("META-INF/container.xml", _CONTAINER.encode())
        self.write("EPUB/content.opf", _PACKAGE.encode())
        self.write("EPUB/nav.xhtml", b"<html xmlns='http://www.w3.org/1999/xhtml'><body/></html>")
        self.write("EPUB/chapter.xhtml", b"<html xmlns='http://www.w3.org/1999/xhtml'><body>Chapter</body></html>")
        self.write("EPUB/style.css", b"body { color: black; }")
        self.write("EPUB/images/figure.png", b"image")
        self.output = self.root / "book.epub"

    def write(self, relative, content):
        path = self.package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_mimetype_is_first_and_uncompressed_and_other_entries_are_stable(self):
        write_epub(self.package, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), [
                "mimetype", "EPUB/chapter.xhtml", "EPUB/content.opf",
                "EPUB/images/figure.png", "EPUB/nav.xhtml", "EPUB/style.css",
                "META-INF/container.xml",
            ])
            self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
            for item in archive.infolist():
                self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(item.external_attr >> 16, 0o100644)

        first = self.output.read_bytes()
        write_epub(self.package, self.output)
        self.assertEqual(self.output.read_bytes(), first)

    def test_rejects_missing_or_malformed_package_structure(self):
        (self.package / "EPUB/content.opf").unlink()
        with self.assertRaisesRegex(ValueError, "manifest item|rootfile"):
            write_epub(self.package, self.output)

        self.write("EPUB/content.opf", b"<package")
        with self.assertRaisesRegex(ValueError, "Invalid EPUB package document"):
            write_epub(self.package, self.output)

    def test_rejects_package_without_navigation_document(self):
        self.write("EPUB/content.opf", _PACKAGE.replace(' properties="nav"', "").encode())
        with self.assertRaisesRegex(ValueError, "navigation document"):
            write_epub(self.package, self.output)

    def test_rejects_unsafe_paths_and_symlinks(self):
        (self.package / "EPUB/unsafe").symlink_to(self.package / "EPUB/chapter.xhtml")
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            write_epub(self.package, self.output)
        (self.package / "EPUB/unsafe").unlink()

        self.write("EPUB/bad\\name", b"bad")
        with self.assertRaisesRegex(ValueError, "Unsafe EPUB path"):
            write_epub(self.package, self.output)

    def test_rejects_destination_inside_package_tree(self):
        destination = self.package / "nested.epub"
        with self.assertRaisesRegex(ValueError, "outside its package tree"):
            write_epub(self.package, destination)


if __name__ == "__main__":
    unittest.main()
