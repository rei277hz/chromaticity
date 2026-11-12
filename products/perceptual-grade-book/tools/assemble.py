"""Assemble authored book editions, generated assets, and historical downloads."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil


BOOKS = {
    "user-manual": {
        "title": "Perceptual Grade User Manual",
        "description": (
            "A bilingual guide to using Perceptual Grade. Some interface and "
            "workflow chapters describe the preserved 1.23.2 release."
        ),
        "summary_sources": {
            "en": "src/SUMMARY.md",
            "zh-Hans": "zh-Hans/SUMMARY.md",
        },
    },
    "technical-report": {
        "title": "Perceptual Grade Technical Report",
        "description": (
            "English technical report on the current Perceptual Grade reference "
            "and project development."
        ),
        "summary_sources": {"en": "src/report/SUMMARY.md"},
    },
}

CHAPTER_DIRECTORIES = {
    "user-manual": ("guide", "reference"),
    "technical-report": ("theory", "development", "reference"),
}
NON_CHAPTER_DIRECTORIES = {"assets", "downloads", "vendor"}
MANIFEST_PATHS = {"SUMMARY.md", "report/SUMMARY.md"}
REPORT_INTRO = "report/README.md"


def _files(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"Missing input directory: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _inventory(root):
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in _files(root).items()
    }


def _summary_chapters(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("# "):
        raise ValueError(f"Missing SUMMARY title: {path}")
    chapters = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(?:[-*]\s+)?\[[^\]]+\]\(([^)#]+\.md)(?:#[^)]*)?\)\s*", line)
        if match:
            name = match.group(1)
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
                raise ValueError(f"Invalid SUMMARY chapter path: {name}")
            chapters.append(name)
    if not chapters or chapters[0] != "README.md":
        raise ValueError(f"SUMMARY must begin with README.md: {path}")
    if len(chapters) != len(set(chapters)):
        raise ValueError(f"Duplicate chapter paths in SUMMARY: {path}")
    return chapters


def _chapter_files(source, report_intro=False):
    """Return Markdown chapters, excluding manifests and downloadable reports."""
    result = set()
    for path in Path(source).rglob("*.md"):
        relative = path.relative_to(source).as_posix()
        parts = PurePosixPath(relative).parts
        manifests = MANIFEST_PATHS if report_intro else {"SUMMARY.md"}
        if (relative in manifests or (report_intro and relative == REPORT_INTRO)
                or parts[0] in NON_CHAPTER_DIRECTORIES):
            continue
        result.add(relative)
    return result


def _expected_chapters(source, directories):
    result = {"README.md"}
    for directory in directories:
        result.update(
            path.relative_to(source).as_posix()
            for path in (Path(source) / directory).rglob("*.md")
        )
    return result


def _validate_chapters(book):
    source = Path(book) / "src"
    manual_order = _summary_chapters(source / "SUMMARY.md")
    manual = set(manual_order)
    report = set(_summary_chapters(source / "report/SUMMARY.md"))
    expected_manual = _expected_chapters(source, CHAPTER_DIRECTORIES["user-manual"])
    expected_report = _expected_chapters(source, CHAPTER_DIRECTORIES["technical-report"])
    actual_english = _chapter_files(source, report_intro=True)
    if manual != expected_manual:
        raise ValueError(
            "User Manual SUMMARY must cover exactly its English chapters: "
            f"missing={sorted(expected_manual - manual)}, "
            f"extra={sorted(manual - expected_manual)}"
        )
    if report != expected_report:
        raise ValueError(
            "Technical Report SUMMARY must cover exactly its English chapters: "
            f"missing={sorted(expected_report - report)}, "
            f"extra={sorted(report - expected_report)}"
        )
    assigned = manual | report
    if assigned != actual_english:
        raise ValueError(
            "Every English chapter must be assigned to a book: "
            f"unassigned={sorted(actual_english - assigned)}, "
            f"unknown={sorted(assigned - actual_english)}"
        )
    for name in ("README.md", "report/README.md"):
        if not (source / name).is_file():
            raise ValueError(f"Missing required English book introduction: {source / name}")

    chinese_source = Path(book) / "zh-Hans"
    chinese_order = _summary_chapters(chinese_source / "SUMMARY.md")
    manual_chinese = set(chinese_order)
    expected_chinese = _expected_chapters(chinese_source, CHAPTER_DIRECTORIES["user-manual"])
    actual_chinese = _chapter_files(chinese_source)
    if manual_chinese != expected_chinese or actual_chinese != expected_chinese:
        raise ValueError(
            "Simplified Chinese SUMMARY must cover exactly the User Manual chapters: "
            f"missing={sorted(expected_chinese - manual_chinese)}, "
            f"unlisted={sorted(actual_chinese - manual_chinese)}, "
            f"extra={sorted(manual_chinese - expected_chinese)}"
        )
    if chinese_order != manual_order:
        raise ValueError("Simplified Chinese chapter paths must match the English User Manual order")
    return {
        "user-manual": manual,
        "technical-report": report,
        "user-manual-zh-Hans": manual_chinese,
    }


def verify_historical(historical, manifest):
    """Only published attachments are frozen; chapters are normal editable inputs."""
    specification = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if specification.get("schema") != 1:
        raise ValueError("Expected schema 1 historical attachment manifest")
    expected = specification["files"]
    for filename in expected:
        relative = PurePosixPath(filename)
        if (relative.is_absolute() or ".." in relative.parts
                or str(relative) != filename or filename in ("", ".")):
            raise ValueError(f"Invalid historical manifest path: {filename}")
    actual = _inventory(historical)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys()
                     if expected[name] != actual[name])
    if missing or extra or changed:
        raise ValueError(
            f"Historical inventory mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
    return specification


def _book_config(source, book_name):
    text = source.read_text(encoding="utf-8")
    book_section = re.search(r"(?ms)^\[book\][ \t]*\n(?P<body>.*?)(?=^\[|\Z)", text)
    if book_section is None:
        raise ValueError(f"Missing [book] configuration in {source}")
    body = book_section["body"]
    for key, value in (
        ("title", BOOKS[book_name]["title"]),
        ("description", BOOKS[book_name]["description"]),
        ("language", "en"),
        ("src", "src"),
    ):
        pattern = rf"(?m)^{key}\s*=.*$"
        assignment = f"{key} = {json.dumps(value)}"
        if re.search(pattern, body):
            body = re.sub(pattern, assignment, body, count=1)
        else:
            body += assignment + "\n"
    return text[:book_section.start("body")] + body + text[book_section.end("body"):]


def _project_book(sources, book_name, chapters):
    """Return an explicit destination map without creating an output tree."""
    is_manual = book_name == "user-manual"
    english_chapters = chapters[book_name]
    all_english_chapters = chapters["user-manual"] | chapters["technical-report"]
    projected = {}

    for name, source in sorted(sources.items()):
        if name.startswith("src/"):
            relative = name.removeprefix("src/")
            if relative in MANIFEST_PATHS:
                continue
            if relative == REPORT_INTRO:
                if not is_manual:
                    projected["src/README.md"] = source
                continue
            if relative in all_english_chapters:
                if relative not in english_chapters or (relative == "README.md" and not is_manual):
                    continue
            # This includes root icons and Markdown downloads as well as assets.
            projected[name] = source
        elif name.startswith("zh-Hans/"):
            if not is_manual or name == "zh-Hans/SUMMARY.md":
                continue
            projected[name] = source
        else:
            projected[name] = source

    for language, relative in BOOKS[book_name]["summary_sources"].items():
        target_root = "src" if language == "en" else language
        projected[f"{target_root}/SUMMARY.md"] = sources[relative]
    return projected


def assemble(docs, assets, historical, manifest, output):
    """Project authored sources into independent Manual and Report mdBooks."""
    docs, output = Path(docs), Path(output)
    verify_historical(historical, manifest)
    source_book = docs / "book"
    if not (source_book / "book.toml").is_file():
        raise ValueError("Missing required docs/book/book.toml")
    chapters = _validate_chapters(source_book)

    sources = {}
    for root in [source_book, *map(Path, assets), Path(historical)]:
        incoming = _files(root)
        if not incoming:
            raise ValueError(f"Empty book input tree: {root}")
        for name, path in incoming.items():
            if name in sources:
                raise ValueError(f"Conflicting book input destination: {name}")
            if root != source_book and name.endswith(".md"):
                relative = PurePosixPath(name)
                if (relative.parts[0] in ("src", "zh-Hans")
                        and len(relative.parts) > 1
                        and relative.parts[1] not in NON_CHAPTER_DIRECTORIES):
                    raise ValueError(f"Generated input cannot introduce a chapter: {name}")
            sources[name] = path
    for name in sources:
        for parent in PurePosixPath(name).parents:
            if parent.as_posix() in sources:
                raise ValueError(f"File/directory conflict in book inputs: {parent}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Assembly output must be absent or empty: {output}")

    projections = {
        name: _project_book(sources, name, chapters) for name in BOOKS
    }
    configurations = {
        name: _book_config(sources["book.toml"], name) for name in BOOKS
    }
    for book_name in BOOKS:
        for name, source in sorted(projections[book_name].items()):
            destination = output / book_name / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name == "book.toml":
                destination.write_text(configurations[book_name], encoding="utf-8")
            else:
                # CAS input permissions do not propagate into private staging.
                shutil.copyfile(source, destination)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("docs", "historical", "manifest", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--assets", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    assemble(args.docs, args.assets, args.historical, args.manifest, args.output_dir)


if __name__ == "__main__":
    main()
