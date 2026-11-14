"""Stable code references must resolve to real source and generated locations."""

import json
from pathlib import Path
import tempfile
import unittest

from pg_book_build import book_refs


class CommentReferenceTests(unittest.TestCase):
    def test_only_comments_are_references(self):
        source = '''"""# pg-book: technical-report/en#ignored.docstring"""
text = "# pg-book: technical-report/en#ignored.string"
# pg-book: technical-report/en#next-policy.node-output
value = 1  # pg-book: user-manual/zh-Hans#manual.workflow
'''
        result = book_refs.comment_references(source, "example.py")
        self.assertEqual([(item["code_line"], item["reference"]) for item in result], [
            (3, "technical-report/en#next-policy.node-output"),
            (4, "user-manual/zh-Hans#manual.workflow"),
        ])

    def test_bad_markers_fail_at_the_comment(self):
        for comment in (
                "# pg-book: next-policy.node-output",
                "# pg-book: technical-report/en#next-policy.node-output trailing words",
                "# See pg-book: technical-report/en#next-policy.node-output",
                "# pg-book: technical-report/en#next-policy..node-output"):
            with self.subTest(comment=comment), self.assertRaisesRegex(ValueError, "example.py:2: malformed"):
                book_refs.comment_references("value = 1\n" + comment, "example.py")

    def test_unsupported_language_or_book_fails(self):
        for edition in ("technical-report/zh-Hans", "user-manual/fr", "handbook/en"):
            with self.subTest(edition=edition), self.assertRaisesRegex(ValueError, "unsupported book edition"):
                book_refs.comment_references(f"# pg-book: {edition}#example.anchor", "example.py")


class AnchorDeclarationTests(unittest.TestCase):
    def test_examples_are_not_declarations(self):
        source = '''# Chapter

<a id="example.chapter"></a>

```markdown
## A code example
<a id="example.code"></a>
```
~~~
## Another code example
<a id="example.tilde"></a>
~~~
<!--
## A commented heading
<a id="example.comment"></a>
-->
    <a id="example.indented"></a>
`<a id="example.inline"></a>`
## Section

<a id="example.section"></a>
'''
        result = book_refs.source_anchors(source, "chapter.md")
        self.assertEqual([item["anchor"] for item in result], ["example.chapter", "example.section"])
        self.assertEqual(result[0]["heading_line"], 1)
        self.assertEqual(result[0]["anchor_line"], 3)

    def test_declaration_belongs_after_its_heading(self):
        for text in ('<a id="example.chapter"></a>\n# Chapter\n',
                     '# Chapter\nParagraph\n<a id="example.chapter"></a>\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "immediately follow a heading"):
                book_refs.source_anchors(text, "chapter.md")

    def test_malformed_declaration_fails(self):
        with self.assertRaisesRegex(ValueError, "standalone"):
            book_refs.source_anchors('# Chapter\n<a id="Not Stable"></a>\n', "chapter.md")


class BookReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.docs = self.root / "docs"
        self.book = self.docs / "book"
        self.site = self.root / "site"
        self.sources = self.root / "code"
        self.write(self.book / "src/SUMMARY.md", "# Summary\n[Manual](README.md)\n")
        self.write(self.book / "zh-Hans/SUMMARY.md", "# Summary\n[Manual](README.md)\n")
        self.write(self.book / "src/report/SUMMARY.md",
                   "# Summary\n[Report](README.md)\n- [Policies](development/policies.md)\n")
        self.write(self.book / "src/README.md", '# Manual\n\n<a id="manual.introduction"></a>\n')
        self.write(self.book / "zh-Hans/README.md", '# 用户手册\n\n<a id="manual.introduction"></a>\n')
        self.write(self.book / "src/report/README.md", '# Report\n\n<a id="report.introduction"></a>\n')
        self.write(self.book / "src/development/policies.md",
                   '# Policies\n\n## Node output\n\n<a id="next-policy.node-output"></a>\n')
        self.write(self.site / "manual/en/index.html", '<h1>Manual</h1><a id="manual.introduction"></a>')
        self.write(self.site / "manual/zh-Hans/index.html", '<h1>手册</h1><a id="manual.introduction"></a>')
        self.write(self.site / "technical/en/index.html", '<h1>Report</h1><a id="report.introduction"></a>')
        self.write(self.site / "technical/en/development/policies.html",
                   '<h1>Policies</h1><h2>Node output</h2><a id="next-policy.node-output"></a>')
        self.write(self.sources / "src/policy/node.py",
                   '# pg-book: technical-report/en#next-policy.node-output\n')

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def resolve(self):
        return book_refs.resolve(self.docs, self.site, self.sources)

    def test_real_source_and_generated_page_are_both_resolved(self):
        report = self.resolve()
        target = report["references"][0]
        self.assertEqual(target["source"],
                         "products/perceptual-grade-book/docs/book/src/development/policies.md")
        self.assertEqual(target["heading_line"], 3)
        self.assertEqual(target["code"], "products/perceptual-grade-next-blender/src/policy/node.py")
        self.assertEqual(target["site_path"],
                         "technical/en/development/policies.html#next-policy.node-output")
        self.assertEqual(target["published_url"],
                         "https://rei277hz.github.io/perceptual-grade/technical/en/development/policies.html#next-policy.node-output")
        output = self.root / "output"
        book_refs.write_report(report, output)
        self.assertEqual(json.loads((output / "book-refs.json").read_text()), report)
        self.assertIn("http://127.0.0.1:8080/technical/en/", (output / "book-refs.txt").read_text())

    def test_path_move_and_heading_rename_keep_comment_working(self):
        old_marker = (self.sources / "src/policy/node.py").read_text()
        (self.book / "src/development/policies.md").unlink()
        (self.site / "technical/en/development/policies.html").unlink()
        self.write(self.book / "src/report/SUMMARY.md",
                   "# Summary\n[Report](README.md)\n- [Runtime](development/runtime.md)\n")
        self.write(self.book / "src/development/runtime.md",
                   '# Runtime\n\n## Current installation\n\n<a id="next-policy.node-output"></a>\n')
        self.write(self.site / "technical/en/development/runtime.html",
                   '<h1>Runtime</h1><h2>Current installation</h2><a id="next-policy.node-output"></a>')
        target = self.resolve()["references"][0]
        self.assertEqual((self.sources / "src/policy/node.py").read_text(), old_marker)
        self.assertEqual(target["heading"], "Current installation")
        self.assertEqual(target["site_path"], "technical/en/development/runtime.html#next-policy.node-output")

    def test_report_introduction_uses_original_source_path(self):
        self.write(self.sources / "src/policy/node.py", '# pg-book: technical-report/en#report.introduction\n')
        target = self.resolve()["references"][0]
        self.assertEqual(target["source"], "products/perceptual-grade-book/docs/book/src/report/README.md")
        self.assertEqual(target["site_path"], "technical/en/index.html#report.introduction")

    def test_manual_languages_resolve_independently(self):
        self.write(self.sources / "src/policy/node.py", '# pg-book: user-manual/zh-Hans#manual.introduction\n')
        target = self.resolve()["references"][0]
        self.assertEqual(target["source"], "products/perceptual-grade-book/docs/book/zh-Hans/README.md")
        self.assertEqual(target["site_path"], "manual/zh-Hans/index.html#manual.introduction")

    def test_missing_source_anchor_is_not_replaced_by_a_heading_slug(self):
        self.write(self.book / "src/development/policies.md", '# Policies\n\n## Node output\n')
        with self.assertRaisesRegex(ValueError, "node.py:1: unresolved book reference"):
            self.resolve()

    def test_unlisted_chapter_cannot_resolve(self):
        self.write(self.book / "src/report/SUMMARY.md", "# Summary\n[Report](README.md)\n")
        with self.assertRaisesRegex(ValueError, "unresolved book reference"):
            self.resolve()

    def test_duplicate_source_anchor_fails(self):
        self.write(self.book / "src/report/README.md", '# Report\n\n<a id="next-policy.node-output"></a>\n')
        self.write(self.site / "technical/en/index.html", '<a id="next-policy.node-output"></a>')
        with self.assertRaisesRegex(ValueError, "duplicate book anchor"):
            self.resolve()

    def test_missing_or_duplicate_generated_anchor_fails(self):
        for content in ('<h1>Policies</h1>',
                        '<a id="next-policy.node-output"></a><a id="next-policy.node-output"></a>'):
            self.write(self.site / "technical/en/development/policies.html", content)
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "exactly one"):
                self.resolve()

    def test_missing_generated_page_fails(self):
        (self.site / "technical/en/development/policies.html").unlink()
        with self.assertRaisesRegex(ValueError, "missing generated book page"):
            self.resolve()

    def test_empty_code_input_fails(self):
        (self.sources / "src/policy/node.py").unlink()
        with self.assertRaisesRegex(ValueError, "nonempty declared Python source tree"):
            self.resolve()


if __name__ == "__main__":
    unittest.main()
