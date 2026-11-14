"""Resolve Python comment references to stable, rendered book locations."""

import argparse
from collections import Counter
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import tokenize

from pg_book_build.assemble import BOOKS, _summary_chapters


EDITION_ROUTES = {
    ("user-manual", "en"): "manual/en",
    ("user-manual", "zh-Hans"): "manual/zh-Hans",
    ("technical-report", "en"): "technical/en",
}
BOOK_SOURCE_PREFIX = "products/perceptual-grade-book/docs/book"
CODE_SOURCE_PREFIX = "products/perceptual-grade-next-blender"
PUBLISHED_BASE = "https://rei277hz.github.io/perceptual-grade/"
IDENTIFIER = r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*"
REFERENCE = re.compile(rf"#\s*pg-book:\s+([a-z-]+)/([A-Za-z-]+)#({IDENTIFIER})\s*")
ANCHOR = re.compile(rf'<a id="({IDENTIFIER})"></a>')
HEADING = re.compile(r" {0,3}#{1,6}\s+(.*?)\s*#*\s*$")


def _visible_markdown_lines(text):
    """Yield source lines outside fences, indented code, and HTML comments.

    Declarations use a standalone HTML anchor directly after an ATX heading.
    This deliberately small syntax avoids interpreting examples as declarations.
    """
    fence = None
    in_comment = False
    for number, line in enumerate(text.splitlines(), 1):
        if fence is not None:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", line):
                fence = None
            yield number, None
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        if not in_comment and opening and (opening[1][0] != "`" or "`" not in opening[2]):
            fence = (opening[1][0], len(opening[1]))
            yield number, None
            continue
        pieces = []
        remainder = line
        commented = in_comment
        while remainder:
            if in_comment:
                end = remainder.find("-->")
                if end < 0:
                    remainder = ""
                else:
                    remainder = remainder[end + 3:]
                    in_comment = False
            else:
                start = remainder.find("<!--")
                if start < 0:
                    pieces.append(remainder)
                    remainder = ""
                else:
                    pieces.append(remainder[:start])
                    remainder = remainder[start + 4:]
                    in_comment = True
                    commented = True
        visible = "".join(pieces)
        if commented or line.startswith(("    ", "\t")):
            yield number, None
        else:
            yield number, visible


def source_anchors(text, source):
    """Return explicit declarations and their original heading locations."""
    preceding_heading = None
    declarations = []
    for number, line in _visible_markdown_lines(text):
        if line is None:
            preceding_heading = None
            continue
        if not line.strip():
            continue
        heading = HEADING.fullmatch(line)
        if heading:
            preceding_heading = (number, heading[1])
            continue
        declaration = ANCHOR.fullmatch(line)
        if declaration:
            if preceding_heading is None:
                raise ValueError(f"{source}:{number}: book anchor must immediately follow a heading")
            declarations.append({
                "anchor": declaration[1],
                "source": source,
                "heading_line": preceding_heading[0],
                "anchor_line": number,
                "heading": preceding_heading[1],
            })
        elif re.match(r"\s*<a\s+id=", line):
            raise ValueError(f"{source}:{number}: use a standalone <a id=\"stable.identifier\"></a> anchor")
        preceding_heading = None
    return declarations


class _PageIDs(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids = Counter()
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        for name, value in attributes:
            if name == "id":
                self.ids[value] += 1


def anchor_index(docs, site):
    """Index authored anchors, then confirm their exact generated destinations."""
    book = Path(docs) / "book"
    site = Path(site)
    index = {}
    for (publication, language), route in EDITION_ROUTES.items():
        summary = BOOKS[publication]["summary_sources"][language]
        for chapter in _summary_chapters(book / summary):
            if publication == "technical-report" and chapter == "README.md":
                original = "src/report/README.md"
            else:
                root = "src" if language == "en" else language
                original = root + "/" + chapter
            source = BOOK_SOURCE_PREFIX + "/" + original
            declarations = source_anchors((book / original).read_text(encoding="utf-8"), source)
            page = "index.html" if chapter == "README.md" else chapter.removesuffix(".md") + ".html"
            site_page = route + "/" + page
            rendered = None
            for declaration in declarations:
                identifier = f"{publication}/{language}#{declaration['anchor']}"
                if identifier in index:
                    previous = index[identifier]
                    raise ValueError(
                        f"{source}:{declaration['anchor_line']}: duplicate book anchor {identifier}; "
                        f"first declared at {previous['source']}:{previous['anchor_line']}"
                    )
                if rendered is None:
                    if not (site / site_page).is_file():
                        raise ValueError(f"{source}: missing generated book page {site_page}")
                    rendered = _PageIDs((site / site_page).read_text(encoding="utf-8"))
                count = rendered.ids[declaration["anchor"]]
                if count != 1:
                    raise ValueError(
                        f"{source}:{declaration['anchor_line']}: generated {site_page} must contain "
                        f"exactly one #{declaration['anchor']} anchor; found {count}"
                    )
                location = site_page + "#" + declaration["anchor"]
                index[identifier] = dict(declaration, reference=identifier, book=publication,
                                         language=language, site_path=location,
                                         published_url=PUBLISHED_BASE + location)
    return index


def comment_references(text, source):
    """Read only Python comments, retaining source locations for diagnostics."""
    result = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.COMMENT or "pg-book:" not in token.string:
                continue
            match = REFERENCE.fullmatch(token.string)
            if match is None:
                raise ValueError(
                    f"{source}:{token.start[0]}: malformed book reference; "
                    "expected # pg-book: book/language#stable.identifier"
                )
            publication, language, anchor = match.groups()
            if (publication, language) not in EDITION_ROUTES:
                raise ValueError(f"{source}:{token.start[0]}: unsupported book edition {publication}/{language}")
            result.append({
                "code": source, "code_line": token.start[0],
                "reference": f"{publication}/{language}#{anchor}",
            })
    except (tokenize.TokenError, IndentationError) as error:
        raise ValueError(f"{source}: cannot parse Python comments: {error}") from error
    return result


def resolve(docs, site, sources):
    index = anchor_index(docs, site)
    references = []
    source_root = Path(sources)
    paths = sorted(source_root.rglob("*.py"))
    if not paths:
        raise ValueError("Book references need a nonempty declared Python source tree")
    for path in paths:
        source = CODE_SOURCE_PREFIX + "/" + path.relative_to(source_root).as_posix()
        for reference in comment_references(path.read_text(encoding="utf-8"), source):
            target = index.get(reference["reference"])
            if target is None:
                raise ValueError(
                    f"{source}:{reference['code_line']}: unresolved book reference {reference['reference']}"
                )
            references.append(dict(target, **reference))
    return {"schema": 1, "source_files_checked": len(paths),
            "anchors": [index[key] for key in sorted(index)], "references": references}


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "book-refs.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"Resolved {len(report['references'])} code references against {len(report['anchors'])} stable book anchors.", ""]
    for item in report["references"]:
        lines.extend((
            f"{item['code']}:{item['code_line']}: {item['reference']}",
            f"  {item['source']}:{item['heading_line']} — {item['heading']}",
            f"  {item['published_url']}",
            f"  http://127.0.0.1:8080/{item['site_path']}",
            "",
        ))
    (output / "book-refs.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("docs", "site", "sources", "output-dir"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    try:
        report = resolve(args.docs, args.site, args.sources)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    write_report(report, args.output_dir)


if __name__ == "__main__":
    main()
