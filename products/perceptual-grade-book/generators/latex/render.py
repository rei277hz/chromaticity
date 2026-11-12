"""Render declared PGFPlots documents to portable SVG with pinned TeX tools."""

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile


SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
XETEX_FLAGS = [
    "-no-pdf", "-no-shell-escape", "-interaction=nonstopmode",
    "-halt-on-error", "-file-line-error", "-recorder",
]
DVISVGM_FLAGS = ["--no-fonts", "--exact-bbox", "--bbox=2pt", "--cache=none", "--page=1"]
FONT_FILES = ["Tinos-Regular.ttf", "Tinos-Bold.ttf", "Tinos-Italic.ttf", "Tinos-BoldItalic.ttf"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): digest(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, check=False,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}):\n{result.stdout[-24000:]}")
    return result.stdout


def runtime_command(runtime, binary):
    # Use the matching loader as well as matching libraries; the worker's glibc
    # and host TeX installation are not part of the tool contract.
    loader = runtime / "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
    return [str(loader), "--inhibit-cache", "--library-path",
            str(runtime / "usr/lib/x86_64-linux-gnu"), str(runtime / "usr/bin" / binary)]


def prepare_environment(runtime, work, source):
    texmf = runtime / "usr/share/texlive/texmf-dist"
    extra = runtime / "usr/share/texmf"
    config, formats, cache = work / "config", work / "formats", work / "cache"
    for path in (config, formats, cache):
        path.mkdir()
    # Debian normally builds language.dat and format files in postinst. The
    # chart action needs only English hyphenation and generates its own format.
    (config / "language.dat").write_text("english hyphen.tex\n", encoding="utf-8")
    (config / "language.def").write_text("\\addlanguage{english}{hyphen}{}{2}{3}\n", encoding="utf-8")
    (config / "texmf.cnf").write_text(
        "TEXMFROOT = " + str(runtime / "usr/share/texlive") + "\n"
        "TEXMFDIST = " + str(texmf) + "\n"
        "TEXMF = {" + str(config) + "," + str(texmf) + "," + str(extra) + "}\n"
        "TEXMFDBS = $TEXMF\n"
        "TEXINPUTS = .;" + str(source) + "//;" + str(config) + "//;" + str(texmf) + "/tex//;" + str(extra) + "/tex//\n"
        "TEXFORMATS = " + str(formats) + "\n"
        "TFMFONTS = " + str(texmf) + "/fonts/tfm//;" + str(extra) + "/fonts/tfm//\n"
        "VFFONTS = " + str(texmf) + "/fonts/vf//;" + str(extra) + "/fonts/vf//\n"
        "T1FONTS = " + str(texmf) + "/fonts/type1//;" + str(extra) + "/fonts/type1//\n"
        "OPENTYPEFONTS = .;" + str(source / "fonts") + "//;" + str(texmf) + "/fonts/opentype//;" + str(extra) + "/fonts/opentype//\n"
        "TTFONTS = .;" + str(source / "fonts") + "//;" + str(texmf) + "/fonts/truetype//;" + str(extra) + "/fonts/truetype//\n"
        "ENCFONTS = " + str(texmf) + "/fonts/enc//;" + str(extra) + "/fonts/enc//\n"
        "TEXFONTMAPS = " + str(texmf) + "/fonts/map//;" + str(extra) + "/fonts/map//\n"
        "shell_escape = f\nopenin_any = a\nopenout_any = p\n"
        "parse_first_line = f\nmain_memory = 5000000\nextra_mem_top = 2000000\n"
        "extra_mem_bot = 2000000\nfont_mem_size = 8000000\nfont_max = 9000\n"
        "hash_extra = 600000\npool_size = 6250000\nmax_strings = 500000\n"
        "string_vacancies = 90000\npool_free = 47500\nstrings_free = 100\n"
        "buf_size = 200000\ntrie_size = 1100000\nhyph_size = 8191\n"
        "nest_size = 1000\nmax_in_open = 15\nparam_size = 20000\n"
        "save_size = 200000\nstack_size = 10000\n", encoding="utf-8",
    )
    (config / "fonts.conf").write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
        '<fontconfig><dir>' + html.escape(str(source / "fonts")) + '</dir><cachedir>'
        + html.escape(str(cache)) + '</cachedir></fontconfig>\n', encoding="utf-8",
    )
    env = {
        "PATH": str(runtime / "usr/bin"),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
        "SOURCE_DATE_EPOCH": "315532800", "FORCE_SOURCE_DATE": "1",
        "TEXMFCNF": str(config), "TEXMFVAR": str(cache), "TEXMFCONFIG": str(config),
        "TEXMFHOME": str(config), "TEXMFOUTPUT": str(work),
        "FONTCONFIG_FILE": str(config / "fonts.conf"), "FONTCONFIG_PATH": str(config),
        "XDG_CACHE_HOME": str(cache),
        "MKTEXFMT": "0", "MKTEXPK": "0", "MKTEXTFM": "0",
    }
    return env, formats


def normalized_svg(source, destination, figure):
    text = Path(source).read_text(encoding="utf-8")
    root = ET.fromstring(text)
    if root.tag != f"{{{SVG}}}svg":
        raise ValueError(f"Not an SVG: {figure['id']}")
    viewbox = [float(value) for value in root.get("viewBox", "").split()]
    if len(viewbox) != 4 or not all(math.isfinite(value) for value in viewbox) or min(viewbox[2:]) <= 0:
        raise ValueError(f"Missing positive SVG viewBox: {figure['id']}")
    scale = {"": 1.0, "px": 1.0, "pt": 96 / 72, "bp": 96 / 72,
             "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}
    dimensions = []
    for attribute in ("width", "height"):
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]*)?)(px|pt|bp|mm|cm|in)?", root.get(attribute, ""))
        if match is None:
            raise ValueError(f"Unsupported SVG {attribute}: {root.get(attribute)}")
        dimensions.append(max(1, round(float(match[1]) * scale[match[2] or ""])))
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        if name in ("script", "foreignObject", "image", "text", "font", "style"):
            raise ValueError(f"Chart SVG must be static outlined vectors: {figure['id']} ({name})")
        for key, value in element.attrib.items():
            attribute = key.rsplit("}", 1)[-1]
            if attribute.startswith("on") or (attribute == "href" and not value.startswith("#")):
                raise ValueError(f"External or active SVG resource: {figure['id']}")
            for reference in re.findall(r"url\(([^)]*)\)", value):
                if not reference.strip(" \t\r\n'\"").startswith("#"):
                    raise ValueError(f"External SVG style resource: {figure['id']}")
    # Preserve dvisvgm's serialization and namespace choices. Only modify the
    # root and insert accessibility metadata, keeping referenced glyph IDs intact.
    match = re.search(r"<svg\b[^>]*>", text)
    if match is None:
        raise ValueError(f"Missing SVG root: {figure['id']}")
    header = match[0]
    for attribute, value in zip(("width", "height"), dimensions):
        header = re.sub(rf"\b{attribute}=(['\"]).*?\1", f'{attribute}="{value}"', header)
    title_id, description_id = figure["id"] + "-title", figure["id"] + "-description"
    header = header[:-1] + f' role="img" aria-labelledby="{title_id} {description_id}">'
    accessible = (f'<title id="{title_id}">{html.escape(figure["title"])}</title>'
                  f'<desc id="{description_id}">{html.escape(figure["description"])}</desc>')
    background = (f'<rect x="{viewbox[0]}" y="{viewbox[1]}" width="{viewbox[2]}" '
                  f'height="{viewbox[3]}" fill="#fff"/>')
    text = text[:match.start()] + header + accessible + background + text[match.end():]
    # dvisvgm writes a generator comment, not a wall-clock timestamp. Retain it
    # so standalone assets identify their renderer without path metadata.
    Path(destination).write_text(text, encoding="utf-8")


def source_archive(source, destination):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(source).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def render(sources, runtime, fonts, output):
    sources, runtime, fonts, output = [Path(path).resolve() for path in (sources, runtime, fonts, output)]
    figures_path = sources / "figures.json"
    document = json.loads(figures_path.read_text(encoding="utf-8"))
    figures = document["figures"] if isinstance(document, dict) else document
    ids = [figure["id"] for figure in figures]
    if (not ids or len(ids) != len(set(ids))
            or any(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None for name in ids)):
        raise ValueError("Figure IDs must be unique lowercase hyphenated names")
    if {path.stem for path in (sources / "plots").glob("*.tex")} != set(ids):
        raise ValueError("PGFPlots documents and figure metadata do not match")
    for figure in figures:
        if not all(isinstance(figure.get(key), str) and figure[key] for key in ("title", "description")):
            raise ValueError(f"Chart accessibility metadata is missing: {figure['id']}")
    runtime_manifest = json.loads((runtime / "runtime-manifest.json").read_text(encoding="utf-8"))
    math_font = runtime / runtime_manifest["math_font"]
    output.mkdir(parents=True, exist_ok=True)
    images = output / "images"
    images.mkdir()
    source_copy = output / "sources"
    shutil.copytree(sources, source_copy)
    font_copy = source_copy / "fonts"
    font_copy.mkdir()
    for name in FONT_FILES + ["Tinos-OFL.txt"]:
        shutil.copyfile(fonts / name, font_copy / name)
    shutil.copyfile(math_font, font_copy / "texgyretermes-math.otf")
    math_license = runtime / "usr/share/doc/fonts-texgyre-math/copyright"
    shutil.copyfile(math_license, font_copy / "TeX-Gyre-Math-LICENSE.txt")
    (source_copy / "font-paths.tex").write_text(
        "\\def\\BookFontPath{fonts/}\n\\def\\BookMathFontPath{fonts/}\n", encoding="utf-8",
    )
    with tempfile.TemporaryDirectory(prefix="pg-book-latex-") as temporary:
        work = Path(temporary).resolve()
        compile_root = work / "source"
        shutil.copytree(source_copy, compile_root)
        env, formats = prepare_environment(runtime, work, compile_root)
        xetex = runtime_command(runtime, "xetex")
        dvisvgm = runtime_command(runtime, "dvisvgm")
        xetex_version = run([*xetex, "--version"], work, env).splitlines()[0]
        dvisvgm_version = run([*dvisvgm, "--version"], work, env).splitlines()[0]
        run([*xetex, "-ini", "-etex", "-jobname=xelatex", "-progname=xelatex",
             "-no-pdf", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
             "-output-directory=" + str(formats), "xelatex.ini"], compile_root, env)
        for figure in figures:
            name = figure["id"]
            chart_work = work / name
            chart_work.mkdir()
            run([*xetex, "-fmt=xelatex", "-progname=xelatex", *XETEX_FLAGS,
                 "-output-directory=" + str(chart_work), "plots/" + name + ".tex"], compile_root, env)
            xdv = chart_work / (name + ".xdv")
            svg = chart_work / (name + ".svg")
            run([*dvisvgm, *DVISVGM_FLAGS, "--output=" + str(svg), str(xdv)], compile_root, env)
            normalized_svg(svg, images / (name + ".svg"), figure)
    for path in (sources / "fragments").glob("*"):
        if path.is_file():
            (output / "fragments").mkdir(exist_ok=True)
            shutil.copyfile(path, output / "fragments" / path.name)
    if (sources / "numerical-data.json").is_file():
        shutil.copyfile(sources / "numerical-data.json", output / "numerical-data.json")
    source_archive(source_copy, output / "chart-sources.zip")
    data_provenance = json.loads((sources / "manifest.json").read_text(encoding="utf-8"))
    write_json(output / "manifest.json", {
        "schema": 1, "producer": "PGFPlots book figures", "invocation": "buck2",
        "renderer": {"name": "PGFPlots", "compat": "1.18", "xetex": xetex_version,
                     "dvisvgm": dvisvgm_version, "xetex_flags": XETEX_FLAGS,
                     "dvisvgm_flags": DVISVGM_FLAGS, "pgf_driver": "pgfsys-dvisvgm.def"},
        "runtime": runtime_manifest,
        "data_provenance": data_provenance,
        "inputs": {"sources/" + name: value for name, value in inventory(sources).items()}
                  | {"renderer/render.py": digest(__file__),
                     "runtime/runtime-manifest.json": digest(runtime / "runtime-manifest.json")},
        "fonts": {name: digest(font_copy / name) for name in FONT_FILES + ["texgyretermes-math.otf"]},
        "figures": figures,
        "outputs": inventory(output),
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "runtime", "fonts", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    render(args.sources, args.runtime, args.fonts, args.output_dir)


if __name__ == "__main__":
    main()
