"""Compile emitted transform entry points with injectable UI values."""
import argparse
from pathlib import Path

from tests.support.dctl import (
    ALL_STAGES, ANCHOR_CENTER_PROTOTYPES, GAIN_PROTOTYPES, GLOBAL_SHAPE_PROTOTYPES,
    OVERLAP_PROTOTYPES, PROTOTYPES, STAGES, SURFACE_PROTOTYPES, TONE_FIT_LINEAR_GAIN_PROTOTYPES,
    TONE_FIT_PROTOTYPES, TONE_FIT_UNIFIED_CHROMA_PROTOTYPES,
    WARP_QUADRATIC_SCALE_PROTOTYPES,
    body, controls, entry, filename,
)


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
    read_controls = (f'if (scanf("{"".join(formats)}", {", ".join(addresses)}) != {len(ui)}) return 2;'
                     if ui else "")
    helpers = chroma_source(stage == "lgg_nonlog") if stage in PROTOTYPES else ""
    if stage in SURFACE_PROTOTYPES:
        helpers = surface_source()
    return f"""
namespace {stage} {{
{body(source)}
{variables}
{entry(source)}
{helpers}
int run() {{
    {read_controls}
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


def chroma_source(nonlog):
    return f"""
int read_four(PGFour& values) {{
    return scanf("%f%f%f%f", &values.s, &values.m, &values.w, &values.h);
}}

int run_chroma() {{
    PGFour lift, gamma, gain, weights;
    float ja, pivot;
    if (read_four(lift) != 4 || read_four(gamma) != 4 ||
        read_four(gain) != 4 || read_four(weights) != 4 ||
        scanf("%f%f", &ja, &pivot) != 2) return 2;
    float chroma;
    int fields;
    while ((fields = scanf("%f", &chroma)) == 1) {{
        float axis = pg_jc_lgg_axis(chroma, ja, pivot, {int(nonlog)});
        float scale = pg_jc_lgg_chroma_gain(axis, lift, gamma, gain, weights);
        printf("%.9g %.9g\\n", axis, chroma * scale);
    }}
    return fields == EOF ? 0 : 2;
}}
"""


def surface_source():
    return """
int run_surface() {
    PGFour amounts;
    float center, width;
    int peak;
    if (scanf("%f%f%f%f%f%f%d", &amounts.s, &amounts.m, &amounts.w, &amounts.h,
              &center, &width, &peak) != 7) return 2;
    PGFour anchors = pg_tone_anchors(peak);
    anchors = pg_four(100.0f * anchors.s, 100.0f * anchors.m, 100.0f * anchors.w, 100.0f * anchors.h);
    float height, chroma, ja;
    int fields;
    while ((fields = scanf("%f%f%f", &height, &chroma, &ja)) == 3) {
        float amount = pg_jc_surface_anchor(height, anchors, amounts);
        float lightness = pg_jc_surface_j_response(chroma, ja, center, width);
        float chromaStops = pg_jc_surface_c_response(chroma, ja, center, width, amount);
        printf("%.9g %.9g %.9g\\n", amount, lightness, chromaStops);
    }
    return fields == EOF ? 0 : 2;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dctl-dir", type=Path, required=True)
    parser.add_argument("--prototype-dir", type=Path, required=True)
    parser.add_argument("--surface-dir", type=Path, required=True)
    parser.add_argument("--overlap-dir", type=Path, required=True)
    parser.add_argument("--anchor-centers-dir", type=Path, required=True)
    parser.add_argument("--gain-dir", type=Path, required=True)
    parser.add_argument("--global-shape-dir", type=Path, required=True)
    parser.add_argument("--tone-fit-dir", type=Path, required=True)
    parser.add_argument("--tone-fit-linear-gain-dir", type=Path, required=True)
    parser.add_argument("--tone-fit-unified-chroma-dir", type=Path, required=True)
    parser.add_argument("--warp-quadratic-scale-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sections = ['#include "float3.h"', '#include <stdio.h>', '#include <string.h>']
    for stages, root in ((STAGES, args.dctl_dir), (PROTOTYPES, args.prototype_dir),
                         (SURFACE_PROTOTYPES, args.surface_dir), (OVERLAP_PROTOTYPES, args.overlap_dir),
                         (ANCHOR_CENTER_PROTOTYPES, args.anchor_centers_dir), (GAIN_PROTOTYPES, args.gain_dir),
                         (GLOBAL_SHAPE_PROTOTYPES, args.global_shape_dir), (TONE_FIT_PROTOTYPES, args.tone_fit_dir),
                         (TONE_FIT_LINEAR_GAIN_PROTOTYPES, args.tone_fit_linear_gain_dir),
                         (TONE_FIT_UNIFIED_CHROMA_PROTOTYPES, args.tone_fit_unified_chroma_dir),
                         (WARP_QUADRATIC_SCALE_PROTOTYPES, args.warp_quadratic_scale_dir)):
        for stage in stages:
            source = (root / filename(stage)).read_text(encoding="utf-8")
            sections.append(stage_source(stage, source))
            # Each standalone DCTL may define its own constants with the same name.
            for line in body(source).splitlines():
                if line.startswith("#define "):
                    sections.append("#undef " + line.split()[1].split("(")[0])
    sections += ["int main(int argc, char** argv) {", "    if (argc != 2) return 2;"]
    for stage in ALL_STAGES:
        sections.append(f'    if (!strcmp(argv[1], "{stage}")) return {stage}::run();')
    for stage in PROTOTYPES:
        sections.append(f'    if (!strcmp(argv[1], "{stage}_chroma")) return {stage}::run_chroma();')
    for stage in SURFACE_PROTOTYPES:
        sections.append(f'    if (!strcmp(argv[1], "{stage}_response")) return {stage}::run_surface();')
    sections += ["    return 2;", "}"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "host.cpp").write_text("\n".join(sections) + "\n")


if __name__ == "__main__":
    main()
