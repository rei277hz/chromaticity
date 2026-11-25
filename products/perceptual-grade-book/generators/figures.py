"""Author Perceptual Grade reference and current LUT figures."""

import argparse
import math
from pathlib import Path
import shutil

import numpy as np

from color_tools.perceptual_grade_reference import grading as rg, model as rm, responses as rr
from color_tools.perceptual_grade_core.model import hk_guard as hg
from color_tools.color_core import scaled
from color_tools.kernel import lut
from pg_book_generators.figure_common import manifest, write_json


COLORS = ("bookblue", "bookorange", "bookgreen", "bookpurple")
SERIES = tuple(color + "," + style for color, style in
               zip(COLORS, ("solid", "dashed", "dashdotted", "densely dotted")))
FIT_VALUES = (-1, 0, 2, 4)
TONES = ("Shadows", "Midtones", "White", "Highlights")
GROUP_BEGIN = (r"\begin{groupplot}[book axis,width=70mm,height=55mm,"
               r"group style={group size=2 by 1,horizontal sep=12mm}]")
GROUP_END = r"\end{groupplot}"
LEGEND_BELOW = r"legend style={at={(0.5,-0.28)},anchor=north,legend columns=1}"


class Author:
    def __init__(self, root):
        self.root = Path(root)
        self.tables = self.root / "tables"
        self.plots = self.root / "plots"
        self.tables.mkdir(parents=True, exist_ok=True)
        self.plots.mkdir(parents=True, exist_ok=True)
        self.figures = []

    def table(self, name, **columns):
        arrays = {key: np.asarray(value) for key, value in columns.items()}
        if not arrays or len({len(value) for value in arrays.values()}) != 1:
            raise ValueError(f"Invalid numeric table columns: {name}")
        if any(value.ndim != 1 or not np.isfinite(value).all() for value in arrays.values()):
            raise ValueError(f"Nonfinite or nonvector numeric table: {name}")
        path = self.tables / (name + ".dat")
        with path.open("w", encoding="utf-8") as stream:
            stream.write(" ".join(arrays) + "\n")
            for row in zip(*arrays.values()):
                stream.write(" ".join(format(float(value), ".17g") for value in row) + "\n")
        return "tables/" + path.name

    def plot(self, name, title, description, body):
        (self.plots / (name + ".tex")).write_text(
            "\\input{plot-style.tex}\n\\begin{document}\n\\begin{tikzpicture}\n"
            + "\n".join(body)
            + "\n\\end{tikzpicture}\n\\end{document}\n", encoding="utf-8")
        self.figures.append({"id": name, "title": title, "description": description,
                             "scope": "current-reference"})


def line(table, y="y", label=None, options="", x="x"):
    if label is None:
        options += ",forget plot"
    command = rf"\addplot[{options}] table[x={x},y={y}] {{{table}}};"
    return command + ("\n" + rf"\addlegendentry{{{label}}}" if label else "")


def coordinates(points, options="", label=None):
    if label is None:
        options += ",forget plot"
    values = " ".join(f"({float(x):.17g},{float(y):.17g})" for x, y in points)
    command = rf"\addplot[{options}] coordinates {{{values}}};"
    return command + ("\n" + rf"\addlegendentry{{{label}}}" if label else "")


def panel(options):
    return r"\nextgroupplot[" + options + "]"


def numeric_figures(author):
    tone = rg.Tone(rg.ToneSettings())
    H = np.linspace(0, 100 * float(tone.nits_to_j(4000)), 600)

    x = np.linspace(-1, 1, 301)
    columns = {"x": x}
    white_xy = np.asarray(rm.WHITES["D65"])
    white = rm.xyz_from_xy(white_xy)
    anchors = white_xy + .3 * (np.array([[.64, .33], [.15, .06]]) - white_xy)
    for index, reference in enumerate(anchors):
        vector = rm.xyz_from_xy(reference) - white
        columns[f"default{index}"] = 1 + x * vector[1]
        parameters = rm.LinearSettings(balance=(.4, 0.) if index == 0 else (0., .4))
        matrix = rm.linear_matrix(parameters, white)
        samples = white[None, :] + x[:, None] * vector
        columns[f"balanced{index}"] = (samples @ matrix.T)[:, 1]
    basis = author.table("linear-basis", **columns)
    adaptation = rm.adaptation(rm.xyz_from_xy((0.38, 0.35)), white)
    cone = rm.CAT16 @ adaptation @ np.linalg.inv(rm.CAT16)
    gains = author.table("linear-cone-gains", x=np.arange(1, 4), y=np.diag(cone))
    body = [GROUP_BEGIN, panel(r"xlabel={Position around white},ylabel={Relative $Y$},"
                             r"title={Balance response}," + LEGEND_BELOW)]
    for index, label in enumerate(("Cyan--Red", "Yellow--Blue")):
        body.extend((line(basis, f"default{index}", label + " / default", COLORS[index]),
                     line(basis, f"balanced{index}", label + " / UI $+0.4$", COLORS[index] + ",dashed")))
    body.extend((panel(r"ylabel={CAT16 gain},title={$(0.38,0.35)\to D65$},"
                       r"xtick={1,2,3},xticklabels={Cone 1,Cone 2,Cone 3},ymin=0,ybar,bar width=9pt"),
                 line(gains, options="bookblue,fill=bookblue"),
                 coordinates(((0.5, 1), (3.5, 1)), "bookgray,dashed,sharp plot,no marks,forget plot"), GROUP_END))
    author.plot("linear-basis", "White-fixed directional basis and CAT16 gains",
                "Balance changes colored-pixel luminance around an unchanged white. CAT16 independently adapts the source white to D65.", body)

    columns = {"x": H / 100, "identity": H / 100}
    for index, fit in enumerate(FIT_VALUES):
        model = rg.Tone(rg.ToneSettings(input_nits=(0., rg.LOW_Y * 203, 55., 280., 1400.), fit=fit))
        columns[f"fit{index}"] = model.remap(H) / 100
    curves = author.table("tone-curves", **columns)
    landmarks = author.table("tone-landmarks", x=model.source, y=model.target)
    body = [r"\begin{axis}[book axis,width=140mm,height=65mm,xlabel={Input $H/100$},"
            r"ylabel={Output $H/100$},title={Monotone tone curve and adjustable Fit},"
            r"legend style={at={(0.5,-0.22)},anchor=north,legend columns=3}]"]
    body.extend(line(curves, f"fit{index}", f"Fit {fit}", SERIES[index]) for index, fit in enumerate(FIT_VALUES))
    body.extend((line(curves, "identity", "Identity", "bookgray,dashed"),
                 line(landmarks, label="Soft targets", options="black,only marks,mark=x,mark size=3pt"),
                 coordinates(((1, 0), (1, float(max(columns["fit3"])))), "bookgray,dotted,no marks"),
                 coordinates(((0, 1), (float(max(H / 100)), 1)), "bookgray,dotted,no marks,forget plot"), r"\end{axis}"))
    author.plot("tone-curves", "Monotone tone curves and adjustable Fit",
                "Four Fit settings share the same soft landmark targets. Dashed identity and unit reference lines show the tone remapping.", body)

    targets = np.linspace(20, 180, 400)
    h, chroma = 100.0, 20.0
    ja = math.sqrt(h * h - 66 * chroma)
    # Rationalized saturation-preserving gain from the current Tone equations.
    gain = 2 * targets**2 / (np.hypot(66 * chroma, 2 * ja * targets) + 66 * chroma)
    saturation = author.table("tone-saturation", x=targets, preserve_chroma=chroma * gain,
        square_chroma=chroma * (targets / h) ** 2,
        preserve_saturation=75 * chroma / ja * np.ones_like(targets),
        square_saturation=75 * chroma / ja * targets / h)
    body = [GROUP_BEGIN, panel(r"xlabel={Mapped $H$},ylabel={Resulting $C$},title={Input $H=100$, $C=20$}," + LEGEND_BELOW),
            line(saturation, "preserve_chroma", "Preserve saturation", "bookblue"),
            line(saturation, "square_chroma", "Squared-$H$ coupling", "bookorange,dashed"),
            panel(r"xlabel={Mapped $H$},ylabel={Saturation $s$},title={Saturation response}"),
            line(saturation, "preserve_saturation", options="bookblue"),
            line(saturation, "square_saturation", options="bookorange,dashed"), GROUP_END]
    author.plot("tone-saturation", "Saturation-preserving and squared-H policies",
                "At input H 100 and C 20, preserving modCAM16 saturation changes chroma while holding saturation constant; squared-H coupling does not.", body)

    weights = rg.coefficient_weights(H, tone.coefficient_knots, tone.high, 0)
    columns = {"x": H, **{f"weight{index}": weights[:, index] for index in range(len(TONES))}}
    for index, fit in enumerate(FIT_VALUES):
        columns[f"fit{index}"] = 6 * rg.coefficient_weights(H, tone.coefficient_knots, tone.high, fit)[:, 1]
    weights_table = author.table("color-tone-weights", **columns)
    body = [GROUP_BEGIN, panel(r"xlabel={$M$},ylabel={Coefficient weight},title={Smooth tone weights}," + LEGEND_BELOW)]
    body.extend(line(weights_table, f"weight{index}", name, SERIES[index]) for index, name in enumerate(TONES))
    body.append(panel(r"xlabel={$M$},ylabel={$C_{\ell}\to J$ coefficient},title={Midtones adjustment}," + LEGEND_BELOW))
    body.extend(line(weights_table, f"fit{index}", f"Fit {fit}", SERIES[index]) for index, fit in enumerate(FIT_VALUES))
    body.append(GROUP_END)
    author.plot("color-tone-weights", "Tone weights and Midtones coefficient",
                "Four overlapping tone weights and one Midtones C-low to J adjustment at four Fit settings show the adjustment's tonal reach.", body)

    chroma = np.linspace(0, 50 ** 2 / 66, 600)
    driver_q = np.stack((np.full_like(chroma, 50), chroma, np.zeros_like(chroma)), axis=-1)
    drivers = rg.drivers(driver_q, np.sqrt(np.maximum(0, 50 ** 2 - 66 * chroma)))
    driver_table = author.table("color-chroma-drivers", x=chroma, low=drivers[:, 0], high=drivers[:, 1])
    hue = np.linspace(-180, 180, 400)
    radius = 20
    opponent_q = np.stack((np.full_like(hue, 50), radius * np.cos(np.deg2rad(hue)),
                           radius * np.sin(np.deg2rad(hue))), axis=-1)
    opponent_values = rg.drivers(opponent_q, math.sqrt(50**2 - 66 * radius))
    opponents = author.table("color-opponent-drivers", x=hue,
                            a=opponent_values[:, 2], b=opponent_values[:, 3])
    body = [GROUP_BEGIN,
            panel(r"xlabel={Chroma $C$},ylabel={Driver weight},title={$H=50$, $p=2$, $s_0=35$}," + LEGEND_BELOW),
            line(driver_table, "low", r"Low chroma $C_{\ell}$", "bookblue"),
            line(driver_table, "high", r"High chroma $C_h$", "bookorange,dashed"),
            panel(r"xlabel={Hue $h$ (degrees)},ylabel={Signed weight},title={Opponent drivers}," + LEGEND_BELOW),
            line(opponents, "a", "$a$ driver", "bookblue"), line(opponents, "b", "$b$ driver", "bookorange,dashed"),
            coordinates(((-180, 0), (180, 0)), "bookgray,no marks,forget plot"), GROUP_END]
    author.plot("color-drivers", "Chroma and opponent driver responses",
                "Low and high chroma drivers at fixed H weight distinct color ranges. Signed opponent drivers choose opposite sides of the hue wheel.", body)

    C = np.linspace(0, 180, 650)
    requested = np.stack([np.full_like(C, 50), C, np.zeros_like(C)], axis=-1)
    reference_energy = rr.hk_energy(50., 20.)
    safe, energy = rg.guard(requested, rr.hk_energy(50., C), reference_energy)
    guard = author.table("guard-boundary", x=C, requested_h=np.full_like(C, 50), repaired_h=safe[:, 0], repaired_c=safe[:, 1])
    body = [r"\begin{axis}[book axis,name=guard,width=140mm,height=65mm,xmin=0,xmax=180,"
            r"ymin=48,ymax=62,axis y line*=left,xlabel={Requested $C$},ylabel={$H$},"
            r"title={Bounded lift and chroma reduction},legend pos=north west]",
            line(guard, "requested_h", "Requested $H$", "bookgray,dashed"),
            line(guard, "repaired_h", "Repaired $H$", "bookblue,solid"),
            coordinates(((0, 60), (180, 60)), "bookorange,dotted,no marks", r"20\% lift bound"), r"\end{axis}",
            r"\begin{axis}[book axis,at={(guard.south west)},anchor=south west,width=140mm,height=65mm,"
            r"xmin=0,xmax=180,axis y line*=right,axis x line=none,ylabel={Repaired $C$},"
            r"axis background/.style={fill=none},grid=none,legend pos=south east]",
            line(guard, "repaired_c", "Repaired $C$", "bookgreen"), r"\end{axis}"]
    author.plot("guard-boundary", "Sharing repair between H and C",
                "Left scale: requested H, repaired H, and the 60-unit lift bound. Right scale: repaired C. Stronger chroma requests share repair between bounded lift and chroma reduction.", body)
    D = 2500 - 66 * C
    delta = (2500 - 66 * 20) * 2500 / (2500 + (2500 - 66 * 20))
    energy_table = author.table("guard-energy", x=D, y=energy)
    repaired = author.table("guard-repaired-points", x=safe[:, 1], y=safe[:, 0])
    cc = np.linspace(0, max(safe[:, 1]) + 5, 400)
    boundary = author.table("guard-real-boundary", x=cc, y=np.sqrt(66 * cc))
    body = [GROUP_BEGIN, panel(r"xlabel={Requested $D=H^2-66C$},ylabel={Repaired $E$},title={Positive energy floor}," + LEGEND_BELOW),
            line(energy_table, options="bookblue"),
            coordinates(((delta, 0), (delta, max(energy))), "bookgray,dashed,no marks", r"Knee $\delta$"),
            panel(r"xlabel={$C$},ylabel={$H$},title={Positive $J_A$ after repair}," + LEGEND_BELOW),
            line(repaired, label="Guarded points", options="bookblue"),
            line(boundary, label=r"$H^2=66C$ boundary", options="bookorange,dashed"), GROUP_END]
    author.plot("guard-energy", "Guard energy and positive-branch boundary",
                "With positive requested H and reference energy, the knee yields positive achromatic energy. Repaired points stay above H squared equals 66 C before common Scale.", body)

    grid_values = lut.axis()
    grid = author.table("lut-input-grid", x=np.arange(lut.SIZE), y=grid_values)
    zoom_count = min(lut.SIZE, int(np.searchsorted(grid_values, 0.25, side="right")) + 1)
    grid_zoom = author.table("lut-input-grid-zoom", x=np.arange(zoom_count), y=grid_values[:zoom_count])
    body = [GROUP_BEGIN, panel(r"xlabel={Grid index},ylabel={Linear ACEScg component},title={65 samples / $0\ldots1024$}"),
            line(grid, options="bookblue,mark=*,mark size=0.8pt"),
            panel(r"xlabel={Grid index},ylabel={Linear ACEScg component},title={Density near black},xmin=0,xmax=64,ymin=-0.025,ymax=0.25"),
            line(grid_zoom, options="bookblue,mark=*,mark size=0.8pt"),
            coordinates(((0, 0), (64, 0)), "bookgray,no marks,forget plot"), GROUP_END]
    author.plot("lut-input-grid", "Native AP1 input samples",
                "The current 65-point AP1 axis spans 0 to 1024. The second panel enlarges its near-black interval.", body)

    cell = 20
    cell_points = np.linspace(grid_values[cell], grid_values[cell + 1], 200)
    shaped_position = lut.CELLS * np.log1p(cell_points / lut.KAPPA) / lut.LOG_RANGE
    shaped_fraction = shaped_position - cell
    physical_fraction = ((cell_points - grid_values[cell]) /
                         (grid_values[cell + 1] - grid_values[cell]))
    interpolation = author.table("lut-interpolation", x=cell_points,
                                 shaped=shaped_fraction, physical=physical_fraction)
    address_points = np.linspace(lut.MINIMUM, lut.MAXIMUM, 500)
    address = author.table("lut-address", x=address_points,
                           y=lut.CELLS * np.log1p(address_points / lut.KAPPA) / lut.LOG_RANGE)
    body = [GROUP_BEGIN, panel(r"xlabel={Linear ACEScg component},ylabel={Fraction across cell},title={Address versus interpolation coordinate}," + LEGEND_BELOW),
            line(interpolation, "shaped", "Shaped index fraction", "bookblue"),
            line(interpolation, "physical", "Physical RGB fraction", "bookorange,dashed"),
            panel(r"xlabel={Linear ACEScg component},ylabel={Shaped cell index},title={Address across the LUT domain}," + LEGEND_BELOW),
            line(address, options="bookgreen"), GROUP_END]
    author.plot("lut-interpolation", "Shaping and physical-cell interpolation",
                "The logarithmic address selects a nonuniform cell. Interpolation uses the input's physical fraction within that cell.", body)
    return {"model": "perceptual-grade-reference", "reference_nits": tone.reference,
            "peak_nits": tone.peak, "shadow_ratio": rg.LOW_Y, "tone_targets": tone.target.tolist(),
            "chroma_drivers": {"p": 2, "s0": 75 * rg.CHROMA_CROSSOVER, "Cn": 2.},
            "lut_size": lut.SIZE, "lut_minimum": lut.MINIMUM, "lut_maximum": lut.MAXIMUM,
            "lut_kappa": lut.KAPPA}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("style", "output-dir"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args(argv)
    author = Author(args.output_dir)
    shutil.copyfile(args.style, args.output_dir / "plot-style.tex")
    numerical = numeric_figures(author)
    write_json(args.output_dir / "numerical-data.json", numerical)
    write_json(args.output_dir / "figures.json", {"figures": author.figures})
    manifest(args.output_dir,
             [args.style, Path(__file__), *(Path(module.__file__) for module in (rg, rm, rr, hg, scaled, lut))],
             "Perceptual Grade reference and Blender LUT figures and PGFPlots sources",
             {"plot-style": args.style.parent, "generators": Path(__file__).parent,
              "reference": Path(rg.__file__).parent,
              "shared-model": Path(hg.__file__).parent,
              "color-core": Path(scaled.__file__).parent,
              "blender-kernel": Path(lut.__file__).parent})


if __name__ == "__main__":
    main()
