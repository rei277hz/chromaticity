"""Render the authored Next policy diagrams with the declared D2 distribution."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


SVG = "http://www.w3.org/2000/svg"
D2_VERSION = "0.9.0"
FLAGS = ["--layout", "elk", "--elk-nodeNodeBetweenLayers", "40",
         "--elk-edgeNodeBetweenLayers", "30", "--theme", "0", "--scale", "1", "--pad", "24",
         "--sketch=false", "--animate-interval", "0", "--bundle=false"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def browser_environment(native_runtime, fonts):
    # Chromium still needs an initialized platform font catalog when every SVG
    # label uses an embedded font. An empty host catalog can reject valid font
    # data. This catalog is pinned and separate from the SVG's checked fonts.
    with tempfile.TemporaryDirectory(prefix="pg-diagram-fontconfig-") as temporary:
        config = Path(temporary) / "fonts.conf"
        config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
                          '<fontconfig><dir>' + escape(str(fonts.resolve())) + '</dir>'
                          '<cachedir>' + escape(temporary) + '</cachedir></fontconfig>')
        yield dict(os.environ,
                   LD_LIBRARY_PATH=str(native_runtime.resolve() / "usr/lib/x86_64-linux-gnu"),
                   FONTCONFIG_FILE=str(config))


def accessible_svg(path, figure):
    # Preserve D2's font CSS and SVG serialization while adding accessible text.
    text = path.read_text(encoding="utf-8")
    # D2 places definitions beside visible shapes. Some SVG consumers paint
    # mask children there; defs gives these reusable elements portable scope.
    definitions = re.findall(r"<(?:mask|marker)\b[^>]*>.*?</(?:mask|marker)>", text, re.DOTALL)
    text = re.sub(r"<(?:mask|marker)\b[^>]*>.*?</(?:mask|marker)>", "", text, flags=re.DOTALL)
    inner = list(re.finditer(r"<svg\b[^>]*>", text))[-1]
    text = text[:inner.end()] + "<defs>" + "".join(definitions) + "</defs>" + text[inner.end():]
    root = ET.fromstring(text)
    if root.tag != f"{{{SVG}}}svg" or not root.get("viewBox"):
        raise ValueError(f"Not a complete SVG: {path.name}")
    if any(int(root.get(dimension, "0")) <= 0 for dimension in ("width", "height")):
        raise ValueError(f"SVG needs positive integer dimensions: {path.name}")
    forbidden = {"script", "foreignObject", "animate", "animateTransform", "set"}
    for element in root.iter():
        if element.tag.split("}")[-1] in forbidden:
            raise ValueError(f"Non-static SVG element: {path.name}")
        for key, value in element.attrib.items():
            if key.split("}")[-1] in ("href", "src") and not value.startswith(("#", "data:")):
                raise ValueError(f"External SVG resource: {path.name}")
    for reference in re.findall(r"url\(['\"]?([^)'\"]+)", text):
        if not reference.startswith(("#", "data:")):
            raise ValueError(f"External SVG CSS resource: {path.name}")
    title_id, description_id = figure["id"] + "-title", figure["id"] + "-description"
    title = ET.Element("title", {"id": title_id})
    title.text = figure["title"]
    description = ET.Element("desc", {"id": description_id})
    description.text = figure["description"]
    metadata = ET.tostring(title, encoding="unicode") + ET.tostring(description, encoding="unicode")
    match = re.search(r"<svg\b[^>]*>", text)
    if match is None:
        raise ValueError(f"Missing SVG root element: {path.name}")
    opening = match[0][:-1] + f' role="img" aria-labelledby="{title_id} {description_id}">'
    text = text[:match.start()] + opening + metadata + text[match.end():]
    path.write_text(text, encoding="utf-8")


def render(archive, sources, manifest_path, output, node, chromium, npm, label_checker, native_runtime, fonts):
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Diagram output directory must be empty")
    figures = json.loads(manifest_path.read_text(encoding="utf-8"))["figures"]
    expected = {figure["id"] + ".d2" for figure in figures}
    actual = {path.name for path in sources.glob("*.d2")}
    if actual != expected or len(expected) != len(figures):
        raise ValueError(f"Diagram sources differ from manifest: {actual ^ expected}")
    images = output / "src/assets/illustrations/next-policy"
    images.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="pg-book-d2-") as temporary:
        temporary = Path(temporary)
        with tarfile.open(archive, "r:gz") as distribution:
            member = distribution.getmember(f"d2-v{D2_VERSION}/bin/d2")
            executable = temporary / "d2"
            with distribution.extractfile(member) as source:
                executable.write_bytes(source.read())
            licenses = output / "src/downloads/licenses"
            licenses.mkdir(parents=True)
            for name in ("LICENSE.txt", "THIRD_PARTY_NOTICES.txt"):
                with distribution.extractfile(f"d2-v{D2_VERSION}/{name}") as source:
                    (licenses / ("D2-" + name)).write_bytes(source.read())
        executable.chmod(0o755)
        version = subprocess.run([str(executable), "--version"], check=True,
                                 capture_output=True, text=True).stdout.strip()
        if version != f"v{D2_VERSION}":
            raise ValueError(f"Expected D2 v{D2_VERSION}, got {version}")
        for figure in figures:
            result = images / (figure["id"] + ".svg")
            rendered = subprocess.run([str(executable), *FLAGS, "--salt", figure["id"],
                                       str(sources / (figure["id"] + ".d2")), str(result)],
                                      capture_output=True, text=True)
            if rendered.returncode:
                raise RuntimeError(f'D2 failed for {figure["id"]}: {rendered.stderr}')
            accessible_svg(result, figure)
    with browser_environment(native_runtime, fonts) as browser_env:
        checked = subprocess.run([
            str(node.resolve()), str(label_checker.resolve()),
            "--chromium", str(chromium.resolve() / "chrome"),
            "--node-modules", str(npm.resolve() / "node_modules"),
            "--svg-dir", str(images.resolve()), "--manifest", str(manifest_path.resolve()),
        ], capture_output=True, text=True, env=browser_env)
    if checked.returncode:
        raise RuntimeError(checked.stderr)
    label_check = json.loads(checked.stdout)
    label_check["checker_sha256"] = digest(label_checker)
    label_check["native_runtime_manifest_sha256"] = digest(native_runtime / "native_runtime_manifest.json")
    label_check["platform_fonts"] = {path.name: digest(path) for path in sorted(fonts.glob("*.ttf"))}
    provenance = {
        "schema": 1,
        "invocation": "buck2" if os.environ.get("PG_BUCK_ACTION") == "1" else "authoring-preview",
        "renderer": {"name": "D2", "version": D2_VERSION, "archive_sha256": digest(archive), "flags": FLAGS},
        "inputs": {f"docs/book/diagrams/{name}": digest(sources / name) for name in sorted(expected)},
        "figure_manifest_sha256": digest(manifest_path),
        "renderer_adapter_sha256": digest(Path(__file__)),
        "label_check": label_check,
        "outputs": {f"assets/illustrations/next-policy/{path.name}": digest(path) for path in sorted(images.glob("*.svg"))},
    }
    report = output / "src/downloads/provenance/next-policy-diagrams.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "sources", "manifest", "output-dir", "node", "chromium", "npm", "label-checker", "native-runtime", "fonts"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    render(args.archive, args.sources, args.manifest, args.output_dir,
           args.node, args.chromium, args.npm, args.label_checker, args.native_runtime, args.fonts)


if __name__ == "__main__":
    main()
