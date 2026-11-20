"""Compile the four emitted transform entry points with injectable UI values."""
import argparse
from pathlib import Path

from tests.support.dctl import STAGES, body, controls, entry, filename


def stage_source(stage, source):
    ui = controls(source)
    declarations = []
    formats = []
    addresses = []
    for item in ui:
        name = item["name"]
        is_float = item["type"] == "DCTLUI_SLIDER_FLOAT"
        declarations.append(f'{"float" if is_float else "int"} {name};')
        formats.append("%f" if is_float else "%d")
        addresses.append("&" + name)
    variables = "\n".join(declarations)
    return f"""
namespace {stage} {{
{body(source)}
{variables}
{entry(source)}
int run() {{
    if (scanf("{''.join(formats)}", {', '.join(addresses)}) != {len(ui)}) return 2;
    float red, green, blue;
    int width, height, x, y;
    int fields;
    while ((fields = scanf("%f%f%f%d%d%d%d", &red, &green, &blue, &width, &height, &x, &y)) == 7) {{
        float3 pixel = transform(width, height, x, y, red, green, blue);
        printf("%.9g %.9g %.9g\\n", pixel.x, pixel.y, pixel.z);
    }}
    return fields == EOF ? 0 : 2;
}}
}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dctl-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sections = ['#include "float3.h"', '#include <stdio.h>', '#include <string.h>']
    for stage in STAGES:
        source = (args.dctl_dir / filename(stage)).read_text(encoding="utf-8")
        sections.append(stage_source(stage, source))
        # Each standalone DCTL may define its own constants with the same name.
        for line in body(source).splitlines():
            if line.startswith("#define "):
                sections.append("#undef " + line.split()[1].split("(")[0])
    sections += ["int main(int argc, char** argv) {", "    if (argc != 2) return 2;"]
    for stage in STAGES:
        sections.append(f'    if (!strcmp(argv[1], "{stage}")) return {stage}::run();')
    sections += ["    return 2;", "}"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "host.cpp").write_text("\n".join(sections) + "\n")


if __name__ == "__main__":
    main()
