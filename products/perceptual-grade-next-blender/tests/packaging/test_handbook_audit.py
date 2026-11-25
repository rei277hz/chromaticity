"""Audit the published handbook as documentation of Perceptual Grade."""

from io import BytesIO
from importlib.resources import files
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from product_build.handbook_audit import (
    EDITIONS, _check_image, audit_artifacts, audit_sources,
)


class HandbookAuditTests(unittest.TestCase):
    def test_active_manual_and_all_published_formats(self):
        root = Path(files("tests.perceptual_grade_blender"))
        source = audit_sources(root / "book_sources", root / "generators.BUCK")
        self.assertEqual(len(source["manual_chapters"]), 20)
        evidence = audit_artifacts(
            root / "site", root / "site.zip",
            {name: root / "print-exports" / name for name in EDITIONS},
        )
        self.assertEqual(evidence["animated_images"], 0)
        self.assertEqual(set(evidence["editions"]), {
            "user-manual-en", "user-manual-zh-Hans", "technical-report-en",
        })

    def test_animation_detection_uses_frames_and_svg_operations(self):
        still = BytesIO()
        Image.new("RGB", (1, 1), "red").save(still, format="PNG")
        self.assertTrue(_check_image("still.png", still.getvalue()))
        animation = BytesIO()
        Image.new("RGB", (1, 1), "red").save(
            animation, format="GIF", save_all=True,
            append_images=[Image.new("RGB", (1, 1), "blue")],
            duration=100, loop=0,
        )
        with self.assertRaisesRegex(ValueError, "Animated raster"):
            _check_image("two-frames.gif", animation.getvalue())
        with self.assertRaisesRegex(ValueError, "Animated SVG"):
            _check_image(
                "motion.svg",
                b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x"/></svg>',
            )

    def test_source_audit_rejects_a_new_install_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("src", "zh-Hans"):
                (root / name / "guide").mkdir(parents=True)
                (root / name / "README.md").write_text(
                    'Perceptual Grade archived Blender package 归档的 Blender 扩展 '
                    'archived-blender-extension.zip '
                    '[Next download](downloads/next.zip)', encoding="utf-8",
                )
            with self.assertRaisesRegex(ValueError, "another install ZIP"):
                audit_sources(root, root / "unused.BUCK")
