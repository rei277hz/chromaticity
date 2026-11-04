"""Verify declared CDN inputs and generate references without bundling their bytes."""

import argparse
import ast
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pins(path):
    assignments = {}
    for item in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = ast.literal_eval(item.value)
    return assignments


def build(pins_path, sources, output):
    pins_path, sources, output = Path(pins_path), Path(sources), Path(output)
    pins = read_pins(pins_path)
    fonts, tools = pins["DOC_FONTS"], pins["DOC_TOOLS"]
    katex = tools["katex"]
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"CDN output must be absent or empty: {output}")
    inputs = {}

    def verify(spec):
        source = sources / spec["out"]
        actual = digest(source)
        if actual != spec["sha256"]:
            raise ValueError(f"CDN input hash mismatch: {source.name}")
        inputs[source.name] = actual
        return source

    resources = [tools["mdbook"]["license"], *pins["TUTORIAL_ASSETS"].values()]
    resources += [katex[key] for key in ("stylesheet", "script", "license")]
    resources += [spec[key] for spec in fonts.values() for key in ("normal", "license")]
    for spec in resources:
        verify(spec)
    for spec in fonts.values():
        if (sources / spec["normal"]["out"]).read_bytes()[:4] != b"wOF2":
            raise ValueError(f"Expected a WOFF2 font: {spec['normal']['out']}")

    theme = output / "theme"
    downloads = output / "src/downloads"
    licenses = downloads / "licenses"
    provenance = downloads / "provenance"
    for directory in (theme, licenses, provenance):
        directory.mkdir(parents=True, exist_ok=True)
    css = ["/* Versioned CDN fonts, verified by the Buck2 CDN assets action. */"]
    for spec in fonts.values():
        css.append(
            '@font-face {\n'
            f'  font-family: "{spec["family"]}"; font-style: normal; font-weight: {spec["weights"]};\n'
            f'  src: url("{spec["normal"]["url"]}") format("woff2");\n'
            '  font-display: swap;\n}'
        )
    stylesheet = theme / "fonts.css"
    stylesheet.write_text("\n".join(css) + "\n", encoding="utf-8")
    integrity = {
        key: "sha384-" + base64.b64encode(hashlib.sha384(
            (sources / katex[key]["out"]).read_bytes()
        ).digest()).decode("ascii")
        for key in ("stylesheet", "script")
    }
    head = theme / "head.hbs"
    head.write_text(
        '<link rel="stylesheet" href="' + html.escape(katex["stylesheet"]["url"], quote=True)
        + '" integrity="' + integrity["stylesheet"] + '" crossorigin="anonymous">\n'
        '<script defer src="' + html.escape(katex["script"]["url"], quote=True)
        + '" integrity="' + integrity["script"] + '" crossorigin="anonymous"></script>\n',
        encoding="utf-8",
    )
    for spec in [tools["mdbook"]["license"], katex["license"],
                 pins["TUTORIAL_ASSETS"]["colour_nuke_license"],
                 *(font["license"] for font in fonts.values())]:
        shutil.copyfile(sources / spec["out"], licenses / spec["out"])
    tutorial = pins["TUTORIAL_ASSETS"]["colorchecker2014"]
    shutil.copyfile(sources / tutorial["out"], downloads / tutorial["out"])
    common = {
        "schema": 1,
        "invocation": "buck2" if os.environ.get("PG_BUCK_ACTION") == "1" else "authoring-preview",
        "pins_sha256": digest(pins_path),
        "generator_sha256": digest(Path(__file__)),
    }
    font_inputs = {spec[key]["out"]: inputs[spec[key]["out"]]
                   for spec in fonts.values() for key in ("normal", "license")}
    manifests = {
        "fonts": dict(common, producer="Pinned CDN typography", fonts=fonts,
                      inputs=font_inputs, outputs={"fonts.css": digest(stylesheet)}),
        "katex": dict(common, producer="Pinned CDN equations", katex=katex,
                      integrity=integrity,
                      inputs={katex[key]["out"]: inputs[katex[key]["out"]]
                              for key in ("stylesheet", "script", "license")},
                      outputs={"head.hbs": digest(head)}),
    }
    for name, manifest in manifests.items():
        (provenance / (name + ".json")).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pins", "sources", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.pins, args.sources, args.output_dir)


if __name__ == "__main__":
    main()
