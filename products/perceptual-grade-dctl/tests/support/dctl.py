"""Public DCTL files and section boundaries used by the host and tests."""
from dctl_testing.parser import controls as parse_controls, section

STAGES = {
    "linear": "1-Linear",
    "input": "1B-XYZ-Input",
    "tone": "2-Cone-Tone",
    "jc": "3A-Cone-Color-JC",
    "warp": "3B-Cone-Warp",
    "output": "4-XYZ-Output",
}
PROTOTYPES = {
    "lgg": "3A-Color-JC-LGG-Prototype",
    "lgg_nonlog": "3A-Color-JC-LGG-NonLog-Prototype",
    "lgg_pivot": "3A-Color-JC-LGG-Pivot-Prototype",
}
SURFACE_PROTOTYPES = {"surface": "3A-Color-JC-Surface-Prototype"}
ALL_STAGES = STAGES | PROTOTYPES | SURFACE_PROTOTYPES
LOCALES = ("en", "zh_HANS")
BEGIN = "/* PG_NUMERICAL_BEGIN */"
END = "/* PG_NUMERICAL_END */"


def filename(stage, locale="en"):
    suffix = "" if locale == "en" else "-" + locale.replace("_", "-")
    return f"Perceptual-Grade-{ALL_STAGES[stage]}{suffix}.dctl"


def controls(source):
    if any(line.startswith("DEFINE_UI_PARAMS(") for line in source.splitlines()):
        return parse_controls(source)
    return []


def body(source):
    return section(source, BEGIN, END)


def entry(source):
    return source.split(END, 1)[1]
