"""Public DCTL files and section boundaries used by the host and tests."""
from dctl_testing.parser import controls, section

STAGES = {"linear": "1-Linear", "tone": "2-Tone", "jc": "3A-Color-JC", "warp": "3B-Warp"}
LOCALES = ("en", "zh_HANS")
BEGIN = "/* PG_NUMERICAL_BEGIN */"
END = "/* PG_NUMERICAL_END */"


def filename(stage, locale="en"):
    suffix = "" if locale == "en" else "-" + locale.replace("_", "-")
    return f"Perceptual-Grade-{STAGES[stage]}{suffix}.dctl"


def body(source):
    return section(source, BEGIN, END)


def entry(source):
    return source.split(END, 1)[1]
