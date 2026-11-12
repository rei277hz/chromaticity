"""Check SVG interchange and portable source-archive contracts."""

from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from pg_book_latex.render import normalized_svg, source_archive


class SvgContractTest(unittest.TestCase):
    def test_points_become_pixels_without_changing_vector_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, result = root / "raw.svg", root / "chart.svg"
            source.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                'width="120.5pt" height="60.25pt" viewBox="-2 -3 120.5 60.25">'
                '<defs><path id="glyph" d="M0 0L1 1"/></defs><use xlink:href="#glyph"/></svg>',
                encoding="utf-8",
            )
            normalized_svg(source, result, {"id": "a-chart", "title": "A < B", "description": "Clips & glyphs"})
            svg = ET.parse(result).getroot()
            self.assertEqual(svg.get("width"), "161")
            self.assertEqual(svg.get("height"), "80")
            self.assertEqual(svg.get("viewBox"), "-2 -3 120.5 60.25")
            self.assertEqual(svg.get("role"), "img")
            self.assertEqual([element.text for element in list(svg)[:2]], ["A < B", "Clips & glyphs"])
            background = list(svg)[2]
            self.assertEqual(background.get("fill"), "#fff")
            self.assertEqual(background.get("x"), "-2.0")
            self.assertEqual(background.get("width"), "120.5")
            self.assertEqual(svg[-1].get("{http://www.w3.org/1999/xlink}href"), "#glyph")

    def test_external_active_or_unoutlined_output_is_rejected(self):
        for unsafe in ('<script/>', '<text>Label</text>', '<image href="data:image/png;base64,AA=="/>',
                       '<use href="other.svg#glyph"/>', '<path onclick="alert(1)"/>',
                       '<path fill="url(https://example.invalid/pattern)"/>'):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "raw.svg"
                source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10pt" height="10pt" '
                                  'viewBox="0 0 10 10">' + unsafe + '</svg>', encoding="utf-8")
                with self.assertRaises(ValueError):
                    normalized_svg(source, root / "out.svg", {"id": "chart", "title": "Chart", "description": "Chart"})

    def test_source_archive_is_independent_of_filesystem_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archives = []
            for name in ("first", "second"):
                source = root / name
                (source / "tables").mkdir(parents=True)
                (source / "tables/points.dat").write_text("x y\n0 1\n", encoding="utf-8")
                destination = root / (name + ".zip")
                source_archive(source, destination)
                archives.append(destination.read_bytes())
                with zipfile.ZipFile(destination) as archive:
                    self.assertEqual(archive.namelist(), ["tables/points.dat"])
                    self.assertEqual(archive.getinfo("tables/points.dat").date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(*archives)


if __name__ == "__main__":
    unittest.main()
