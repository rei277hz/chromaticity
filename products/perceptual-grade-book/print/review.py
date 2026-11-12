"""Render PDF review pages with PDFium, without OCR."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader
import pypdfium2 as pdfium
from lxml import html


REGRESSION_PHRASE = "参数纹理使用稳定容量"
CHARTS = {
    "linear-basis", "tone-curves", "tone-saturation", "color-tone-weights",
    "color-drivers", "color-hue-concentration", "guard-boundary", "guard-energy",
    "lut-input-grid", "lut-interpolation", "render-benchmark",
    "lut-shaper-errors", "lut-shaper-placement", "lut-domain128-errors", "lut-domain128-placement",
}


def chapter_pages(reader, title):
    entries = []

    def visit(outline, depth=0):
        for item in outline:
            if isinstance(item, list):
                visit(item, depth + 1)
            else:
                entries.append((depth, item.title, reader.get_destination_page_number(item)))

    visit(reader.outline)
    # The print heading contains a separate chapter-number span. Depending on
    # its DOM position the PDF outline places that number before or after the
    # title, without necessarily inserting whitespace.
    numbered_title = r"(?:[\d.]+\s*)?" + re.escape(title) + r"(?:\s*[\d.]+)?"
    for index, (depth, name, start) in enumerate(entries):
        if re.fullmatch(numbered_title, " ".join(name.split())):
            end = next((page for level, _, page in entries[index + 1:] if level <= depth), len(reader.pages))
            return set(range(start, end))
    raise ValueError(f"PDF outline is missing chapter: {title}")


def chart_pages(reader, document_path, language):
    """Locate charts through the same figure anchors used by the figure list."""
    document = html.document_fromstring(Path(document_path).read_bytes())
    destinations = reader.named_destinations
    pages = {}
    found = set()
    for image in document.xpath("//figure//img[@src]"):
        name = Path(image.get("src")).stem
        if name not in CHARTS:
            continue
        figure = image.xpath("ancestor::figure[1]")[0]
        identifier = figure.get("id")
        if not identifier or identifier not in destinations:
            raise ValueError(f"PDF is missing the chart destination: {name}")
        page = reader.get_destination_page_number(destinations[identifier])
        if page is None or not 0 <= page < len(reader.pages):
            raise ValueError(f"PDF chart destination has no page: {name}")
        pages.setdefault(page, []).append({"chart": name, "figure_id": identifier})
        found.add(name)
    expected = CHARTS - ({"render-benchmark"} if language == "zh-Hans" else set())
    if found != expected:
        raise ValueError(f"Chart review inventory differs: missing={sorted(expected - found)}, extra={sorted(found - expected)}")
    return pages


def render_review(pdf_path, output_dir, language="zh-Hans", chapter=None, document_path=None):
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    chart_locations = None
    if document_path is not None:
        chart_locations = chart_pages(reader, document_path, language)
        matching_pages = set(chart_locations)
        selected = set(matching_pages)
        # Historical candidate keys follow the paired plots and can flow onto
        # the next page. Include that page in the visual review as well.
        for index, figures in chart_locations.items():
            if any(figure["chart"] in {"lut-shaper-placement", "lut-domain128-placement"} for figure in figures):
                if index + 1 < len(reader.pages):
                    selected.add(index + 1)
    elif chapter is not None:
        matching_pages = chapter_pages(reader, chapter)
        selected = matching_pages
    else:
        texts = [page.extract_text() or "" for page in reader.pages]
        matching_pages = [
            index for index, text in enumerate(texts)
            if REGRESSION_PHRASE in re.sub(r"\s+", "", text)
        ]
        if not matching_pages:
            raise ValueError(f"Chinese PDF text mapping is missing {REGRESSION_PHRASE}")
        selected = {0}
        for index in matching_pages:
            selected.update(range(max(0, index - 1), min(len(texts), index + 2)))
    pages = []
    dpi = 144 if chart_locations is not None else 110
    with pdfium.PdfDocument(str(pdf_path)) as document:
        for index in sorted(selected):
            filename = f"{language}-page-{index + 1:03d}.png"
            page = document[index]
            bitmap = page.render(scale=dpi / 72)
            image = bitmap.to_pil()
            image.save(output_dir / filename)
            image.close()
            bitmap.close()
            page.close()
            record = {
                "physical_page": index + 1,
                "image": filename,
            }
            if chart_locations is not None:
                record["figures"] = chart_locations.get(index, [])
            else:
                record["contains_requested_chapter" if chapter is not None else "contains_regression_phrase"] = index in matching_pages
            pages.append(record)

    manifest = {
        "pdf": pdf_path.name,
        "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "dpi": dpi,
        "pages": pages,
    }
    if chart_locations is not None:
        manifest["selection"] = "charts"
        manifest["document_sha256"] = hashlib.sha256(Path(document_path).read_bytes()).hexdigest()
    else:
        manifest["phrase"] = chapter if chapter is not None else REGRESSION_PHRASE
    (output_dir / "review.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "zh-Hans"), default="zh-Hans")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--chapter")
    selection.add_argument("--charts", action="store_true", help="Review every chart in both language editions")
    parser.add_argument("--documents", type=Path, help="Prepared print documents used to locate chart figure anchors")
    args = parser.parse_args()
    if args.charts:
        if args.documents is None:
            parser.error("--charts requires --documents")
        reviews = {}
        for language in ("en", "zh-Hans"):
            review = render_review(
                args.pdf_dir / f"perceptual-grade-{language}.pdf", args.output_dir / language,
                language, document_path=args.documents / language / "book.html",
            )
            reviews[language] = {
                "manifest": language + "/review.json",
                "pdf_sha256": review["pdf_sha256"],
                "charts": sum(len(page["figures"]) for page in review["pages"]),
                "pages": len(review["pages"]),
            }
        (args.output_dir / "review.json").write_text(
            json.dumps({"selection": "charts", "languages": reviews}, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        render_review(args.pdf_dir / f"perceptual-grade-{args.language}.pdf", args.output_dir,
                      args.language, args.chapter)


if __name__ == "__main__":
    main()
