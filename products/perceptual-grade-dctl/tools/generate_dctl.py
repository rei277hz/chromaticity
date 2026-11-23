"""Generate the Resolve DCTL product or its audition variants."""
import argparse
import json
from pathlib import Path
import tomllib

from color_tools.perceptual_grade_core.model import linear, tone
from color_tools.perceptual_grade_reference.appearance import response_constants
from color_tools.perceptual_grade_reference.responses import GAMMA
from .warp_geometry import geometry_source


STAGES = {
    "linear": "1-Linear",
    "input": "1B-XYZ-Input",
    "tone": "2-Cone-Tone",
    "jc": "3A-Cone-Color-JC",
    "warp": "3B-Cone-Warp",
    "output": "4-XYZ-Output",
}
CONE_DOMAINS = {
    "input": "Linear XYZ D65 to modCAM16 cone responses",
    "tone": "modCAM16 cone responses",
    "jc": "modCAM16 cone responses",
    "jc_gain": "modCAM16 cone responses",
    "jc_global_shape": "modCAM16 cone responses",
    "jc_tone_fit": "modCAM16 cone responses",
    "warp": "modCAM16 cone responses",
    "output": "modCAM16 cone responses to linear XYZ D65",
}
CONE_OUTPUTS = {"input", "tone", "jc", "jc_gain", "jc_global_shape", "jc_tone_fit", "warp"}
JC_PROTOTYPES = {
    "lgg": "3A-Color-JC-LGG-Prototype",
    "lgg_nonlog": "3A-Color-JC-LGG-NonLog-Prototype",
    "lgg_pivot": "3A-Color-JC-LGG-Pivot-Prototype",
}
JC_SURFACE_PROTOTYPE = {"surface": "3A-Color-JC-Surface-Prototype"}
JC_OVERLAP_PROTOTYPES = {
    "jc_adjacent_overlap": "3A-Cone-Color-JC-Adjacent-Overlap-Prototype",
    "jc_broad_overlap": "3A-Cone-Color-JC-Broad-Overlap-Prototype",
}
JC_ANCHOR_CENTERS_PROTOTYPE = {
    "jc_anchor_centers": "3A-Cone-Color-JC-Broad-Overlap-Anchor-Centers-Prototype",
}
JC_GAIN_PROTOTYPES = {
    "jc_linear_gain": "3A-Cone-Color-JC-Linear-Gain-Prototype",
    "jc_log_gain": "3A-Cone-Color-JC-Log-Gain-Prototype",
}
JC_GLOBAL_SHAPE_PROTOTYPE = {"jc_global_shape": "3A-Cone-Color-JC-Global-Shape-Prototype"}
JC_TONE_FIT_PROTOTYPE = {"jc_tone_fit": "2-3A-Cone-Tone-JC-Prototype"}
JC_TONE_FIT_LINEAR_GAIN_PROTOTYPE = {
    "jc_tone_fit_linear_gain": "2-3A-Cone-Tone-JC-Linear-Gain-Prototype",
}
JC_TONE_FIT_UNIFIED_CHROMA_PROTOTYPE = {
    "jc_tone_fit_unified_chroma": "2-3A-Cone-Tone-JC-Unified-Chroma-Prototype",
}
WARP_QUADRATIC_SCALE_PROTOTYPE = {
    "warp_quadratic_scale": "3B-Cone-Warp-Quadratic-Scale-Prototype",
}
VARIANT_STAGES = {
    "jc_tone_fit_linear_gain": "jc_tone_fit",
    "jc_tone_fit_unified_chroma": "jc_tone_fit",
    "warp_quadratic_scale": "warp",
}
# Weights for anchor distances 0 through 3 under each audition kernel.
JC_OVERLAP_WEIGHTS = {
    "jc_adjacent_overlap": (1, 1/4, 0, 0),
    "jc_broad_overlap": (1, 1/2, 1/16, 1/512),
}
TONES = {"S": "shadows", "M": "midtones", "W": "white", "H": "highlights"}
LGG_ADJUSTMENTS = ("Lift", "Gamma", "Gain")
SATURATION_PIVOT = 35 / 75
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


def lgg_controls(adjustable_pivot):
    for row, tone_name in TONES.items():
        for family in "JC":
            for adjustment in LGG_ADJUSTMENTS:
                choice = f"{family}{adjustment}"
                limit, step = (20, 0.1) if choice == "JLift" else (2, 0.01)
                yield dict(name=f"tone{row}{choice}", type="DCTLUI_SLIDER_FLOAT", default=0,
                           min=-limit, max=limit, step=step,
                           label_id=f"lgg.{tone_name}.{choice}", tooltip_id=f"lgg.tooltip.{choice}")
    if adjustable_pivot:
        yield dict(name="saturationPivot", type="DCTLUI_SLIDER_FLOAT", default=SATURATION_PIVOT,
                   min=0.05, max=2, step=0.01,
                   label_id="lgg.saturationPivot", tooltip_id="lgg.tooltip.saturationPivot")


def lgg_messages(messages, lgg_locale):
    labels = {f"lgg.{tone_name}.{choice}": f"{messages[f'tone.{tone_name}']} {label}"
              for tone_name in TONES.values()
              for choice, label in lgg_locale["labels"].items() if choice != "saturationPivot"}
    return (messages | labels | {"lgg.saturationPivot": lgg_locale["labels"]["saturationPivot"]}
            | {f"lgg.tooltip.{key}": value for key, value in lgg_locale["tooltips"].items()})


def surface_controls(reversible, per_anchor_centers=False):
    for row, tone_name in TONES.items():
        for family in "JC":
            limit, step = (20, 0.1) if family == "J" and not reversible else (2, 0.01)
            yield dict(name=f"tone{row}{family}Contrast", type="DCTLUI_SLIDER_FLOAT", default=0,
                       min=-limit, max=limit, step=step,
                       label_id=f"surface.{tone_name}.{family}Contrast",
                       tooltip_id=f"surface.tooltip.{family}Contrast")
            if per_anchor_centers:
                yield dict(name=f"tone{row}{family}Center", type="DCTLUI_SLIDER_FLOAT", default=0.5,
                           min=0.05, max=0.95, step=0.01,
                           label_id=f"surface.{tone_name}.{family}Center",
                           tooltip_id=f"cone.tooltip.anchor_{family.lower()}_center")
    for family in "jc":
        for shape, maximum in (("Center", 0.95), ("Width", 1.0)):
            if per_anchor_centers and shape == "Center":
                continue
            name = f"{family}Saturation{shape}"
            yield dict(name=name, type="DCTLUI_SLIDER_FLOAT", default=0.5,
                       min=0.05, max=maximum, step=0.01,
                       label_id=f"surface.{name}", tooltip_id=f"surface.tooltip.{name}")


def jc_gain_controls(spec):
    for row, tone_name in TONES.items():
        for control, label, tooltip in (("JContrast", f"surface.{tone_name}.JContrast", "gain_j_contrast"),
                                        ("CGain", f"gain.{tone_name}.CGain", "gain_c_gain")):
            yield dict(name=f"tone{row}{control}",
                       type="DCTLUI_SLIDER_FLOAT", default=0.0, min=-2.0, max=2.0, step=0.01,
                       label_id=label, tooltip_id=f"cone.tooltip.{tooltip}")
    yield from (control for control in spec if control["name"] in {"peakNits", "direction"})


def global_shape_sliders(sliders):
    for name, default, minimum, maximum, step in sliders:
        yield dict(name=name, type="DCTLUI_SLIDER_FLOAT", default=default, min=minimum, max=maximum, step=step,
                   label_id=f"global_shape.{name}", tooltip_id=f"global_shape.tooltip.{name}")


def global_chroma_controls(unified=False):
    if unified:
        yield from global_shape_sliders((
            ("cMutedGain", 0, -2, 2, 0.01),
            ("cVividGain", 0, -2, 2, 0.01),
            ("cSaturationCrossover", 0.5, 0.05, 0.95, 0.01),
        ))
    else:
        yield from global_shape_sliders((
            ("cContrast", 0, -2, 2, 0.01),
            ("cPivot", 0.5, 0.05, 0.95, 0.01),
            ("cMuted", 0, -1, 1, 0.01),
            ("cVivid", 0, -1, 1, 0.01),
        ))
    yield from global_shape_sliders((
        ("shadowChroma", 0, -2, 2, 0.01),
        ("highlightChroma", 0, -2, 2, 0.01),
        ("cToneCrossover", 45, 10, 160, 0.1),
    ))


def jc_global_shape_controls(spec):
    yield from global_shape_sliders((
        ("jContrast", 0, -2, 2, 0.01),
        ("jPivot", 45, 10, 160, 0.1),
        ("jToe", 0, -1, 1, 0.01),
        ("jShoulder", 0, -1, 1, 0.01),
        ("jSaturationBias", 0, -1, 1, 0.01),
    ))
    yield from global_chroma_controls()
    direction = next(control for control in spec if control["name"] == "direction")
    yield dict(direction, tooltip_id="global_shape.tooltip.direction")


def jc_tone_fit_controls(spec, variant):
    unified = variant in JC_TONE_FIT_UNIFIED_CHROMA_PROTOTYPE
    direction = next(control for control in spec if control["name"] == "direction")
    shared = (control for control in spec
              if "jc_tone_fit" in control["stages"] and control["name"] != "direction"
              and not (unified and control["name"] == "hkInfluence"))
    for control in shared:
        if unified and control["name"] == "remapFit":
            control = dict(control, max=2)
        yield control
    yield from global_chroma_controls(unified)
    yield dict(direction, tooltip_id="tone_fit.tooltip.direction")
    if unified:
        yield dict(name="showToneCurve", type="DCTLUI_CHECK_BOX", default=0,
                   label_id="tone_fit.showToneCurve", tooltip_id="tone_fit.tooltip.showToneCurve")


def surface_messages(messages, surface_locale):
    labels = {f"surface.{tone_name}.{family}Contrast":
              f"{messages[f'tone.{tone_name}']} {surface_locale['labels'][family + 'Contrast']}"
              for tone_name in TONES.values() for family in "JC"}
    labels.update({f"surface.{tone_name}.{family}Center":
                   f"{messages[f'tone.{tone_name}']} {surface_locale['labels'][family.lower() + 'SaturationCenter']}"
                   for tone_name in TONES.values() for family in "JC"})
    labels.update({f"surface.{key}": value for key, value in surface_locale["labels"].items()
                   if key not in ("JContrast", "CContrast", "globalChromaGain")})
    labels["control.global_gain.label"] = surface_locale["labels"]["globalChromaGain"]
    tooltips = {f"surface.tooltip.{key}": value
                for key, value in surface_locale["tooltips"].items()}
    return messages | labels | tooltips


def ui_header(stage, slug, version, controls, messages):
    domain = CONE_DOMAINS.get(stage, "Linear XYZ D65")
    lines = [f"// Perceptual Grade {version} | {slug} | {domain}, reference white 203 nits."]
    names = set()
    labels = set()
    tooltips = []
    for control in controls:
        name = control["name"]
        label = messages[control["label_id"]]
        if "(" in label or ")" in label:
            raise ValueError(f"ASCII parentheses in Resolve control label for {stage}: {name} / {label}")
        if name in names or label in labels:
            raise ValueError(f"Duplicate Resolve control in {stage}: {name} / {label}")
        names.add(name)
        labels.add(label)
        kind = control["type"]
        if kind == "DCTLUI_COMBO_BOX":
            enums, options = control["options"]
            arguments = [str(control["default"]), "{" + ", ".join(enums) + "}",
                         "{" + ", ".join(messages[key] for key in options) + "}"]
        elif kind == "DCTLUI_CHECK_BOX":
            arguments = [str(control["default"])]
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


def stage_call(stage, variant):
    if stage == "linear":
        return "", "pg_linear_xyz(pixel, srcWhite, srcX, srcY, globalExposure, la, ls, le, ba, bs, be)"
    if stage == "input":
        return "", "pg_cone_input(pixel)"
    if stage == "output":
        return "", "pg_cone_output(pixel)"
    if stage == "tone":
        return "", ("pg_cone_tone(pixel, inputBlack, pg_four(inputShadows, inputMidtones, inputWhite, "
                    "inputHighlights), remapFit, peakNits)")
    if stage in JC_PROTOTYPES:
        arguments = ["pixel"]
        for family, fit in (("J", "lightnessFit"), ("C", "chromaFit")):
            for adjustment in LGG_ADJUSTMENTS:
                entries = [f"tone{row}{family}{adjustment}" for row in TONES]
                arguments.append("pg_four(" + ", ".join(entries) + ")")
            arguments.append(fit)
        axis = "1" if stage == "lgg_nonlog" else "0"
        pivot = "saturationPivot" if stage == "lgg_pivot" else number(SATURATION_PIVOT)
        return "", "pg_jc_lgg_xyz(" + ",\n            ".join(arguments + ["peakNits", axis, pivot]) + ")"
    if stage == "jc" or stage in JC_SURFACE_PROTOTYPE:
        arguments = ["pixel"]
        for family in "JC":
            amounts = ", ".join(f"tone{row}{family}Contrast" for row in TONES)
            center = f"{family.lower()}SaturationCenter"
            if stage == "jc":
                centers = ([f"tone{row}{family}Center" for row in TONES]
                           if variant in JC_ANCHOR_CENTERS_PROTOTYPE else [center] * 4)
                center = "pg_four(" + ", ".join(centers) + ")"
            arguments.extend([f"pg_four({amounts})", center, f"{family.lower()}SaturationWidth"])
        arguments.extend(["globalChromaGain", "peakNits"])
        function = "pg_jc_surface_xyz"
        if stage == "jc":
            arguments.append("direction")
            function = "pg_cone_jc"
        return "", function + "(" + ",\n            ".join(arguments) + ")"
    if stage == "jc_gain":
        arguments = ["pixel"]
        for control in ("JContrast", "CGain"):
            amounts = ", ".join(f"tone{row}{control}" for row in TONES)
            arguments.append(f"pg_four({amounts})")
        mode = "0" if variant == "jc_linear_gain" else "1"
        arguments.extend(["peakNits", "direction", mode])
        return "", "pg_cone_jc_gain(" + ",\n            ".join(arguments) + ")"
    if stage == "jc_global_shape":
        return "", (
            "pg_cone_global_shape(pixel, pg_four(jContrast, jPivot, jToe, jShoulder), jSaturationBias,\n"
            "            pg_four(cContrast, cPivot, cMuted, cVivid), shadowChroma, highlightChroma,\n"
            "            cToneCrossover, direction)"
        )
    if stage == "jc_tone_fit":
        unified = variant in JC_TONE_FIT_UNIFIED_CHROMA_PROTOTYPE
        if unified:
            mode = "PG_JC_CHROMA_UNIFIED"
            saturation = "pg_four(0.0f, cSaturationCrossover, cMutedGain, cVividGain)"
        else:
            mode = ("PG_JC_CHROMA_LINEAR_GAIN" if variant in JC_TONE_FIT_LINEAR_GAIN_PROTOTYPE
                    else "PG_JC_CHROMA_LOG_GAIN")
            saturation = "pg_four(cContrast, cPivot, cMuted, cVivid)"
        tone = ("pixel, blackCompression, pg_four(inputShadows, inputMidtones, inputWhite, inputHighlights),\n"
                "            remapFit, peakNits")
        tonal_chroma = "shadowChroma, highlightChroma, cToneCrossover, direction"
        influence = "1.0f" if unified else "hkInfluence"
        return "", (
            f"pg_cone_tone_fit({tone}, {influence}, {saturation},\n"
            f"            {tonal_chroma}, {mode})"
        )

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
    quadratic_scale = 1 if variant == "warp_quadratic_scale" else 0
    return setup, f"pg_cone_warp(pixel, settings, peakNits, direction, {quadratic_scale})"


def entry_point(stage, variant):
    setup, call = stage_call(stage, variant)
    overlay = ""
    if variant in JC_TONE_FIT_UNIFIED_CHROMA_PROTOTYPE:
        overlay = """    if (showToneCurve && result.valid) {
        output = pg_jc_tone_overlay_pixel(output, p_Width, p_Height, p_X, p_Y,
                    pg_four(inputShadows, inputMidtones, inputWhite, inputHighlights),
                    blackCompression, remapFit, peakNits, direction);
    }
"""
    diagnostic = ("make_float3(400.0f, 0.0f, 400.0f)" if stage in CONE_OUTPUTS else
                  "pg_diagnostic(p_Width, p_Height, p_X, p_Y)")
    return """__DEVICE__ float3 transform(int p_Width,int p_Height,int p_X,int p_Y,float p_R,float p_G,float p_B) {
    float3 pixel = make_float3(p_R, p_G, p_B);
""" + setup + f"""    PGValue result = pg_value(color_zero3(), 0);
    if (color_finite3(pixel)) result = {call};
    float3 output = result.valid ? result.v : {diagnostic};
{overlay}    return make_float3(output.x,output.y,output.z);
}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("output-dir", "source-dir", "color-source", "metadata", "catalog-dir"):
        parser.add_argument("--" + arg, type=Path, required=True)
    prototypes = parser.add_mutually_exclusive_group()
    prototypes.add_argument("--jc-prototype", action="store_true", help="Emit only the Color J/C LGG prototypes")
    prototypes.add_argument("--jc-surface", action="store_true", help="Emit only the Color J/C saturation surface prototype")
    prototypes.add_argument("--jc-overlap", action="store_true", help="Emit the two cone Color J/C tonal overlap prototypes")
    prototypes.add_argument("--jc-anchor-centers", action="store_true",
                            help="Emit the Broad Overlap prototype with independent tonal centers")
    prototypes.add_argument("--jc-gain", action="store_true",
                            help="Emit the saturation-preserving J and C gain prototypes")
    prototypes.add_argument("--jc-global-shape", action="store_true",
                            help="Emit the global J and C shaping prototype")
    prototypes.add_argument("--jc-tone-fit", action="store_true",
                            help="Emit the integrated tone calibration and chroma-shaping prototype")
    prototypes.add_argument("--jc-tone-fit-linear-gain", action="store_true",
                            help="Emit the integrated Tone and J/C prototype with Linear Gain")
    prototypes.add_argument("--jc-tone-fit-unified-chroma", action="store_true",
                            help="Emit the integrated Tone and J/C prototype with a unified chroma curve")
    prototypes.add_argument("--warp-quadratic-scale", action="store_true",
                            help="Emit the Warp prototype with quadratic Scale")
    args = parser.parse_args()
    version = tomllib.loads(args.metadata.read_text())["version"]
    spec = json.loads((args.source_dir / "ui-spec.json").read_text())
    catalogs = {file.stem: json.loads(file.read_text(encoding="utf-8"))
                for file in sorted(args.catalog_dir.glob("*.json"))}
    stages = STAGES
    if args.jc_prototype:
        stages = JC_PROTOTYPES
        lgg_locales = json.loads((args.source_dir / "jc-lgg-locales.json").read_text(encoding="utf-8"))
        catalogs = {locale: lgg_messages(messages, lgg_locales[locale])
                    for locale, messages in catalogs.items()}
    else:
        if args.jc_surface:
            stages = JC_SURFACE_PROTOTYPE
        elif args.jc_overlap:
            stages = JC_OVERLAP_PROTOTYPES
        elif args.jc_anchor_centers:
            stages = JC_ANCHOR_CENTERS_PROTOTYPE
        elif args.jc_gain:
            stages = JC_GAIN_PROTOTYPES
        elif args.jc_global_shape:
            stages = JC_GLOBAL_SHAPE_PROTOTYPE
        elif args.jc_tone_fit:
            stages = JC_TONE_FIT_PROTOTYPE
        elif args.jc_tone_fit_linear_gain:
            stages = JC_TONE_FIT_LINEAR_GAIN_PROTOTYPE
        elif args.jc_tone_fit_unified_chroma:
            stages = JC_TONE_FIT_UNIFIED_CHROMA_PROTOTYPE
        elif args.warp_quadratic_scale:
            stages = WARP_QUADRATIC_SCALE_PROTOTYPE
        surface_locales = json.loads((args.source_dir / "jc-surface-locales.json").read_text(encoding="utf-8"))
        catalogs = {locale: surface_messages(messages, surface_locales[locale])
                    for locale, messages in catalogs.items()}
    if not (args.jc_prototype or args.jc_surface):
        cone_locales = json.loads((args.source_dir / "cone-locales.json").read_text(encoding="utf-8"))
        catalogs = {locale: messages | cone_locales[locale] for locale, messages in catalogs.items()}
    if args.jc_gain:
        for messages in catalogs.values():
            for name in TONES.values():
                messages[f"gain.{name}.CGain"] = f"{messages[f'tone.{name}']} {messages['cone.CGain']}"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def header(name):
        return (args.source_dir / (name + ".dctlh")).read_text(encoding="utf-8")

    common = args.color_source.read_text() + header("common")
    fl, aw = response_constants(203.0)
    viewing = f"#define PG_FL {number(fl)}\n#define PG_AW {number(aw)}\n#define PG_GAMMA {number(GAMMA)}\n"
    appearance = viewing + header("foundation") + header("core")
    for variant, slug in stages.items():
        per_anchor_centers = variant in JC_ANCHOR_CENTERS_PROTOTYPE
        overlap = "jc_broad_overlap" if per_anchor_centers else variant
        stage = "jc" if overlap in JC_OVERLAP_WEIGHTS else VARIANT_STAGES.get(variant, variant)
        if variant in JC_GAIN_PROTOTYPES:
            stage = "jc_gain"
            overlap = "jc_broad_overlap"
        controls = [control for control in spec if stage in control["stages"]]
        helpers = white_guard_source() if stage == "linear" else appearance
        headers = [stage]
        if stage in CONE_DOMAINS:
            headers = ["cone_chart"]
            if stage == "output":
                headers.extend(["hk_repair", "cone_output"])
            elif stage == "jc_tone_fit":
                headers.extend(["jc_gain_common", "jc_global_shape", "jc_tone_compression", "tone_fit", "jc_tone_fit"])
                if variant in JC_TONE_FIT_UNIFIED_CHROMA_PROTOTYPE:
                    headers.append("jc_tone_overlay")
            elif stage != "input":
                if stage in {"jc_gain", "jc_global_shape"}:
                    headers.append("jc_gain_common")
                if stage == "tone":
                    headers.append("tone_fit")
                headers.append(stage)
        if stage in {"jc", "jc_gain", "warp"}:
            helpers += header("stretch")
        if stage == "warp":
            controls.extend(web_controls())
            helpers += geometry_source(tone.PEAKS, number)
            headers.append("cone_warp")
        if stage in {"jc", "jc_gain", "jc_global_shape", "jc_tone_fit"} or stage in JC_SURFACE_PROTOTYPE:
            helpers += header("jc_surface_response")
        if overlap in JC_OVERLAP_WEIGHTS:
            weights = ", ".join(number(value) for value in JC_OVERLAP_WEIGHTS[overlap])
            helpers += f"#define PG_JC_OVERLAP_WEIGHTS pg_four({weights})\n" + header("jc_overlap")
        if stage == "jc":
            controls = [*surface_controls(reversible=True, per_anchor_centers=per_anchor_centers), *controls]
        if stage == "jc_gain":
            controls = list(jc_gain_controls(spec))
        if stage == "jc_global_shape":
            controls = list(jc_global_shape_controls(spec))
        if stage == "jc_tone_fit":
            controls = list(jc_tone_fit_controls(spec, variant))
        if stage in JC_PROTOTYPES:
            helpers += header("jc_weights")
            shared = {"lightnessFit", "chromaFit", "peakNits"}
            controls = [*lgg_controls(stage == "lgg_pivot"),
                        *(control for control in spec if control["name"] in shared)]
            headers = ["hk_repair", "jc_lgg"]
        if stage in JC_SURFACE_PROTOTYPE:
            shared = {"globalChromaGain", "peakNits"}
            controls = [*surface_controls(reversible=False),
                        *(control for control in spec if control["name"] in shared)]
            headers = ["hk_repair", "jc_surface"]
        body = ("/* PG_NUMERICAL_BEGIN */\n" + common + helpers + "".join(header(name) for name in headers)
                + "/* PG_NUMERICAL_END */\n" + entry_point(stage, variant))
        for locale, messages in catalogs.items():
            suffix = "" if locale == "en" else "-" + locale.replace("_", "-")
            output = args.output_dir / f"Perceptual-Grade-{slug}{suffix}.dctl"
            output.write_text(ui_header(stage, slug, version, controls, messages) + body, encoding="utf-8")


if __name__ == "__main__":
    main()
