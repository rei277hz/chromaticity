"""Generate four self-contained Resolve DCTLs for each product locale."""
import argparse
import json
from pathlib import Path
import tomllib

from color_tools.perceptual_grade_core.model import linear, tone
from color_tools.perceptual_grade_reference.appearance import response_constants
from color_tools.perceptual_grade_reference.responses import GAMMA
from .warp_geometry import geometry_source


STAGES = {"linear": "1-Linear", "tone": "2-Tone", "jc": "3A-Color-JC", "warp": "3B-Warp"}
WEB_FIELDS = (
    ("chroma", "DCTLUI_SLIDER_FLOAT", 16, 0.001),
    ("hue", "DCTLUI_SLIDER_INT", 360, 1),
    ("scale", "DCTLUI_SLIDER_FLOAT", 8, 0.01),
)


def number(value):
    literal = format(value, ".12g")
    if "." not in literal and "e" not in literal:
        literal += ".0"
    return literal + "f"


def web_controls():
    for row in range(4):
        for handle in range(6):
            for field, kind, limit, step in WEB_FIELDS:
                yield dict(name=f"web{field}{row}{handle}", type=kind, default=0,
                           min=-limit, max=limit, step=step,
                           label_id=f"control.web_{field}_{row}_{handle}.label",
                           tooltip_id=f"tooltip.warp.{field}")


def ui_header(stage, version, controls, messages):
    lines = [f"// Perceptual Grade {version} | {stage} | Linear XYZ D65, reference white 203 nits."]
    names = set()
    labels = set()
    tooltips = []
    for control in controls:
        name = control["name"]
        label = messages[control["label_id"]]
        if name in names or label in labels:
            raise ValueError(f"Duplicate Resolve control in {stage}: {name} / {label}")
        names.add(name)
        labels.add(label)
        kind = control["type"]
        if kind == "DCTLUI_COMBO_BOX":
            enums, options = control["options"]
            arguments = [str(control["default"]), "{" + ", ".join(enums) + "}",
                         "{" + ", ".join(messages[key] for key in options) + "}"]
        else:
            encode = number if kind == "DCTLUI_SLIDER_FLOAT" else str
            arguments = [encode(control[key]) for key in ("default", "min", "max", "step")]
        lines.append(f"DEFINE_UI_PARAMS({name}, {label}, {kind}, {', '.join(arguments)})")
        tooltip = json.dumps(messages[control["tooltip_id"]], ensure_ascii=True)
        tooltips.append(f"DEFINE_UI_TOOLTIP({label}, {tooltip})")
    for kind in ("DCTLUI_SLIDER_INT", "DCTLUI_SLIDER_FLOAT"):
        if sum(c["type"] == kind for c in controls) > 64:
            raise ValueError(f"{stage} exceeds Resolve's 64-control limit for {kind}")
    return "\n".join(lines + tooltips) + "\n"


def white_guard_source():
    """Project a custom white point onto the shared admissible CAT16 polygon."""
    vertices = linear.WHITE_POLYGON
    lines = ["__DEVICE__ float3 pg_source_vertex(int index) {"]
    for i, (x, y) in enumerate(vertices):
        lines.append(f"    if (index == {i}) return make_float3({number(x)}, {number(y)}, 0.0f);")
    lines.extend(["    return make_float3(0.3127f, 0.329f, 0.0f);", "}"])
    conditions = [f"({number(a)}*x + {number(b)}*y + {number(c)} >= 0.0f)"
                  for a, b, c in linear.WHITE_PLANES]
    return "\n".join(lines) + f"""
__DEVICE__ float3 pg_safe_source_xy(float x, float y) {{
    x = _fminf(0.9f, _fmaxf(0.0f, x));
    y = _fminf(0.9f, _fmaxf(0.0f, y));
    float3 point = make_float3(x, y, 0.0f);
    if ({" && ".join(conditions)}) return point;
    float distance = 1e20f;
    float3 nearest = point;
    for (int i = 0; i < {len(vertices)}; ++i) {{
        float3 start = pg_source_vertex(i);
        float3 edge = pg_source_vertex((i + 1) % {len(vertices)}) - start;
        float t = _fminf(1.0f, _fmaxf(0.0f, color_dot(point - start, edge) / color_dot(edge, edge)));
        float3 candidate = make_float3(_fmaf(edge.x, t, start.x), _fmaf(edge.y, t, start.y), 0.0f);
        float error = color_dot(point - candidate, point - candidate);
        if (error < distance) {{ distance = error; nearest = candidate; }}
    }}
    return nearest;
}}
"""


def stage_call(stage):
    if stage == "linear":
        return "", "pg_linear_xyz(xyz, srcWhite, srcX, srcY, globalExposure, la, ls, le, ba, bs, be)"
    if stage == "tone":
        return "", ("pg_tone_xyz(xyz, inputBlack, pg_four(inputShadows, inputMidtones, inputWhite, "
                    "inputHighlights), remapFit, peakNits)")
    if stage == "jc":
        arguments = ["xyz"]
        for family, fit in (("J", "lightnessFit"), ("C", "chromaFit")):
            for driver in ("Low", "High", "a", "b"):
                rows = [f"tone{tone_id}{driver}To{family}" for tone_id in "SMWH"]
                arguments.append("pg_four(" + ", ".join(rows) + ")")
            arguments.append(fit)
        return "", "pg_jc_xyz(" + ",\n            ".join(arguments + ["globalChromaGain", "peakNits"]) + ")"

    # The controls are uniform for this pixel. Aggregate initialization also
    # gives Metal, CUDA and OpenCL a concrete private storage type.
    arrays = []
    for field, kind, _, _ in WEB_FIELDS:
        cast = "(float)" if kind == "DCTLUI_SLIDER_INT" else ""
        rows = ["{" + ", ".join(f"{cast}web{field}{row}{handle}" for handle in range(6)) + "}"
                for row in range(4)]
        arrays.append("{" + ",\n         ".join(rows) + "}")
    centers = [f"make_float3(tone{row}AdaptanceA, tone{row}AdaptanceB, 0.0f)" for row in "SMWH"]
    arrays.extend(["{" + ", ".join(centers) + "}", "adaptanceHalfSaturation"])
    setup = "    PGWarpSettings settings = {\n        " + ",\n        ".join(arrays) + "\n    };\n"
    return setup, "pg_warp_xyz(xyz, settings, peakNits)"


def entry_point(stage):
    setup, call = stage_call(stage)
    return """__DEVICE__ float3 transform(int p_Width,int p_Height,int p_X,int p_Y,float p_R,float p_G,float p_B) {
    float3 xyz = make_float3(p_R, p_G, p_B);
""" + setup + f"""    PGValue result = pg_value(color_zero3(), 0);
    if (color_finite3(xyz)) result = {call};
    float3 output = result.valid ? result.v : pg_diagnostic(p_Width, p_Height, p_X, p_Y);
    return make_float3(output.x,output.y,output.z);
}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("output-dir", "source-dir", "color-source", "metadata", "catalog-dir"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    version = tomllib.loads(args.metadata.read_text())["version"]
    spec = json.loads((args.source_dir / "ui-spec.json").read_text())
    catalogs = {file.stem: json.loads(file.read_text(encoding="utf-8"))
                for file in sorted(args.catalog_dir.glob("*.json"))}
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def header(name):
        return (args.source_dir / (name + ".dctlh")).read_text(encoding="utf-8")

    common = args.color_source.read_text() + header("common")
    fl, aw = response_constants(203.0)
    viewing = f"#define PG_FL {number(fl)}\n#define PG_AW {number(aw)}\n#define PG_GAMMA {number(GAMMA)}\n"
    appearance = viewing + header("foundation") + header("core")
    for stage, slug in STAGES.items():
        controls = [control for control in spec if stage in control["stages"]]
        helpers = white_guard_source() if stage == "linear" else appearance
        if stage == "warp":
            controls.extend(web_controls())
            helpers += geometry_source(tone.PEAKS, number)
        body = ("/* PG_NUMERICAL_BEGIN */\n" + common + helpers + header(stage)
                + "/* PG_NUMERICAL_END */\n" + entry_point(stage))
        for locale, messages in catalogs.items():
            suffix = "" if locale == "en" else "-" + locale.replace("_", "-")
            output = args.output_dir / f"Perceptual-Grade-{slug}{suffix}.dctl"
            output.write_text(ui_header(slug, version, controls, messages) + body, encoding="utf-8")


if __name__ == "__main__":
    main()
