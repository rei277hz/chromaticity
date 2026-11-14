"""The declared Next Blender references resolve against the real built book."""

import json
from pathlib import Path, PurePosixPath
import unittest


class BuiltBookReferencesTests(unittest.TestCase):
    def test_policy_and_consumer_references_have_real_destinations(self):
        report = json.loads((Path(__file__).parent / "book-refs.json").read_text())
        self.assertEqual(report["schema"], 1)
        references = report["references"]
        self.assertTrue(references)
        self.assertGreater(report["source_files_checked"], 20)
        expected_hotspots = {
            "src/policy/node.py": "technical/en/development/next-policies.html#next-policy.node-output",
            "src/runtime/bank_publication.py": "technical/en/development/next-policies.html#next-policy.bank-publication",
            "examples/publication_compare/policy/parameter_publication.py":
                "technical/en/development/next-policies.html#next-policy.parameter-publication",
        }
        for suffix, site_path in expected_hotspots.items():
            self.assertTrue(any(item["code"].endswith(suffix)
                                and item["site_path"] == site_path
                                for item in references), suffix)
        node_references = [item for item in references if item["code"].endswith("src/nodes.py")]
        self.assertTrue(node_references)
        self.assertTrue({item["site_path"] for item in node_references} >= {
            "technical/en/development/next-policies.html#next-policy.node-output",
            "technical/en/development/next-policies.html#next-policy.gesture",
            "technical/en/development/next-policies.html#next-policy.render-preflight",
        })
        routes = {
            ("user-manual", "en"): "manual/en",
            ("user-manual", "zh-Hans"): "manual/zh-Hans",
            ("technical-report", "en"): "technical/en",
        }
        for item in references:
            edition = item["book"], item["language"]
            self.assertIn(edition, routes)
            source_root = "zh-Hans" if item["language"] == "zh-Hans" else "src"
            self.assertTrue(item["source"].startswith(
                "products/perceptual-grade-book/docs/book/" + source_root + "/"))
            self.assertGreater(item["heading_line"], 0)
            self.assertGreater(item["code_line"], 0)
            route = "/".join(item["site_path"].split("/")[:2])
            self.assertEqual(route, routes[edition])
            self.assertEqual(item["site_path"].count("#"), 1)
            page, fragment = item["site_path"].split("#")
            self.assertEqual(PurePosixPath(page).suffix, ".html")
            self.assertFalse(PurePosixPath(page).is_absolute())
            self.assertNotIn("..", PurePosixPath(page).parts)
            self.assertRegex(fragment, r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
            self.assertEqual(item["anchor"], fragment)
            self.assertEqual(item["reference"],
                             f"{item['book']}/{item['language']}#{fragment}")
            self.assertEqual(item["published_url"],
                             "https://rei277hz.github.io/perceptual-grade/" + item["site_path"])


if __name__ == "__main__":
    unittest.main()
