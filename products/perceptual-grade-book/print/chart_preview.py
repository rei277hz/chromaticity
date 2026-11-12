"""Render standalone chart proofs at their natural print size on A4 pages."""

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import xml.etree.ElementTree as ET

# Importing the PDF helper loads the declared native runtime before WeasyPrint.
from pg_book_print import pdf as pdf_render
import pikepdf
import pypdfium2 as pdfium


DPI = 144


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preview(figures_dir, output_dir, policy_manifest=None, fonts_dir=None):
    figures_dir, output_dir = Path(figures_dir).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir()
    metadata_path = policy_manifest or figures_dir / "sources/figures.json"
    figures = json.loads(metadata_path.read_text(encoding="utf-8"))["figures"]
    sections, records = [], {}
    for index, figure in enumerate(figures, start=1):
        name = figure["id"]
        image_directory = "src/assets/illustrations/next-policy" if policy_manifest else "images"
        svg_path = figures_dir / image_directory / (name + ".svg")
        svg = ET.parse(svg_path).getroot()
        width, height = float(svg.get("width")), float(svg.get("height"))
        if width <= 0 or height <= 0 or (not policy_manifest and width > 160 * 96 / 25.4):
            raise ValueError(f"Chart exceeds the 160 mm print column: {name} ({width} px)")
        records[name] = {
            "title": figure["title"], "physical_page": index,
            "pdf": "chart-preview.pdf", "image": f"pages/{name}.png",
            "svg_sha256": digest(svg_path),
            "natural_size_mm": {"width": width * 25.4 / 96, "height": height * 25.4 / 96},
        }
        sections.append(
            '<section><h1>' + escape(figure["title"]) + '</h1><p class="identifier">'
            + escape(name) + f' · {width * 25.4 / 96:.1f} × {height * 25.4 / 96:.1f} mm</p>'
            + '<figure><img src="' + escape(svg_path.as_uri(), quote=True)
            + '" alt="' + escape(figure["description"], quote=True) + '">'
            + '<figcaption>' + escape(figure["description"]) + '</figcaption></figure></section>'
        )
    fonts = fonts_dir or figures_dir / "sources/fonts"
    stylesheet = """
        @font-face { font-family: BookProof; src: url('%s'); font-weight: 400; }
        @font-face { font-family: BookProof; src: url('%s'); font-weight: 700; }
        @page { size: A4; margin: 25mm;
          @bottom-center { content: 'Chart proof · ' counter(page); font-size: 9pt; }
        }
        html { font-family: BookProof; font-size: 11pt; color: #111; }
        body { margin: 0; }
        section { break-after: page; }
        section:last-child { break-after: auto; }
        h1 { font-size: 17pt; line-height: 1.2; margin: 0 0 3mm; }
        .identifier { font-size: 10pt; color: #555; margin: 0 0 8mm; }
        figure { margin: 0; }
        img { display: block; width: auto; height: auto; max-width: none; }
        figcaption { margin-top: 5mm; line-height: 1.4; }
    """ % ((fonts / "Tinos-Regular.ttf").as_uri(), (fonts / "Tinos-Bold.ttf").as_uri())
    if policy_manifest:
        stylesheet += "img { max-width: 160mm; max-height: 175mm; margin: 0 auto; }"
    font_config = pdf_render.FontConfiguration()
    staged = output_dir / "chart-preview.weasy.pdf"
    pdf_path = output_dir / "chart-preview.pdf"
    pdf_render.HTML(
        string='<!doctype html><html lang="en"><head><meta charset="utf-8">'
               '<title>Perceptual Grade chart proofs</title></head><body>'
               + "".join(sections) + '</body></html>',
        base_url=str(figures_dir), media_type="print",
    ).write_pdf(
        str(staged), stylesheets=[pdf_render.CSS(string=stylesheet, font_config=font_config)],
        font_config=font_config,
    )
    with pikepdf.open(staged) as document:
        document.docinfo["/Title"] = "Perceptual Grade chart proofs"
        document.docinfo["/CreationDate"] = pdf_render.EPOCH_PDF_DATE
        document.docinfo["/ModDate"] = pdf_render.EPOCH_PDF_DATE
        document.save(pdf_path, deterministic_id=True, compress_streams=True)
    staged.unlink()
    with pdfium.PdfDocument(str(pdf_path)) as document:
        if len(document) != len(figures):
            raise ValueError(f"Expected one proof page per chart: {len(figures)} charts, {len(document)} pages")
        for index, figure in enumerate(figures):
            page = document[index]
            bitmap = page.render(scale=DPI / 72)
            image = bitmap.to_pil()
            image.save(output_dir / records[figure["id"]]["image"])
            image.close()
            bitmap.close()
            page.close()
    manifest = {
        "schema": 1, "purpose": "Standalone chart proof at natural print size",
        "page_size": "A4", "margin_mm": 25, "dpi": DPI,
        "pdf": pdf_path.name, "pdf_sha256": digest(pdf_path),
        "figure_manifest_sha256": digest(policy_manifest or figures_dir / "manifest.json"),
        "charts": records,
    }
    (output_dir / "preview.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--policy-manifest", type=Path)
    parser.add_argument("--fonts", type=Path)
    args = parser.parse_args()
    preview(args.figures, args.output_dir, args.policy_manifest, args.fonts.resolve() if args.fonts else None)


if __name__ == "__main__":
    main()
