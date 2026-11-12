"""Author current-reference figures and explicitly historical PGFPlots studies."""

import argparse
import html
import math
from pathlib import Path
import shutil
import statistics

import numpy as np

from pg_book_legacy.model import linear as lm, tone as tm, color as cm, lut
from color_tools.perceptual_grade_reference import appearance as ra, grading as rg, model as rm, responses as rr
from color_tools.perceptual_grade_core.model import hk_guard as hg
from color_tools.color_core import scaled
from pg_book_generators import historical_figures
from pg_book_generators.figure_common import benchmark_data, manifest, write_json


COLORS = ("bookblue", "bookorange", "bookgreen", "bookpurple")
SERIES = tuple(color + "," + style for color, style in
               zip(COLORS, ("solid", "dashed", "dashdotted", "densely dotted")))
FIT_VALUES = (-1, 0, 2, 4)
CURRENT_FIGURES = frozenset({
    "linear-basis", "tone-curves", "tone-saturation", "color-tone-weights",
    "color-drivers", "guard-boundary", "guard-energy",
})
TONES = ("Shadows", "Midtones", "White", "Highlights")
GROUP_BEGIN = (r"\begin{groupplot}[book axis,width=70mm,height=55mm,"
               r"group style={group size=2 by 1,horizontal sep=12mm}]")
SCATTER_BEGIN = (r"\begin{groupplot}[book axis,width=70mm,height=55mm,"
                 r"group style={group size=2 by 1,horizontal sep=22mm}]")
GROUP_END = r"\end{groupplot}"
LEGEND_BELOW = r"legend style={at={(0.5,-0.28)},anchor=north,legend columns=1}"


def tex_text(value):
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
                    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
                    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(character, character) for character in str(value))


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
        scope = "current-reference" if name in CURRENT_FIGURES else "historical"
        self.figures.append({"id": name, "title": title, "description": description, "scope": scope})


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


def numeric_figures(author, benchmark, fragments):
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

    angles = np.linspace(0, 2 * np.pi, 500)
    ab = 20 * np.stack([np.cos(angles), np.sin(angles)], axis=-1)
    columns = {"x": np.rad2deg(angles)}
    for index, value in enumerate((0, 0.25, 0.75)):
        result = cm.hue_concentration(ab, np.broadcast_to([value, 0], ab.shape))
        angle = np.unwrap(np.arctan2(result[:, 1], result[:, 0]))
        columns[f"angle{index}"] = np.rad2deg(angle)
        columns[f"spacing{index}"] = np.gradient(angle, angles)
    concentration = author.table("color-hue-concentration", **columns)
    body = [GROUP_BEGIN, panel(r"xlabel={Input hue (degrees)},ylabel={Output hue (degrees)},title={Concentration around $+a$}," + LEGEND_BELOW)]
    body.extend(line(concentration, f"angle{index}", f"Concentration {value}", SERIES[index]) for index, value in enumerate((0, 0.25, 0.75)))
    body.append(panel(r"xlabel={Input hue (degrees)},ylabel={Local spacing ratio},title={Continuous hue ordering}"))
    body.extend(line(concentration, f"spacing{index}", options=SERIES[index]) for index in range(3))
    body.append(GROUP_END)
    author.plot("color-hue-concentration", "Hue concentration and angular spacing",
                "Unwrapped output hue and its numerical angular derivative show how concentrations 0, 0.25 and 0.75 gather hues while preserving ordering.", body)

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
    # Include the first vertex above the zoom window so clipping preserves the
    # boundary-crossing segment without transforming distant points in TeX.
    zoom_count = min(lut.SIZE, int(np.searchsorted(grid_values, 0.25, side="right")) + 1)
    grid_zoom = author.table("lut-input-grid-zoom", x=np.arange(zoom_count), y=grid_values[:zoom_count])
    body = [GROUP_BEGIN, panel(r"xlabel={Grid index},ylabel={Linear ACEScg component},title={65 samples / $0\ldots128$}"),
            line(grid, options="bookblue,mark=*,mark size=0.8pt"),
            panel(r"xlabel={Grid index},ylabel={Linear RGB component},title={Density near black},xmin=0,xmax=64,ymin=-0.025,ymax=0.25"),
            line(grid_zoom, options="bookblue,mark=*,mark size=0.8pt"),
            coordinates(((0, 0), (64, 0)), "bookgray,no marks,forget plot"), GROUP_END]
    author.plot("lut-input-grid", "Native AP1 input samples",
                "The same 65-point input axis is shown at full 0 to 128 range and with a near-black vertical zoom from -0.025 to 0.25.", body)
    x = np.linspace(0.01, 0.99, 500)
    decoder = author.table("lut-decode", x=x, y=lut.decode(x))
    lo, hi = 0.03, 0.12
    points = np.linspace(lo, hi, 200)
    fraction = (points - lo) / (hi - lo)
    interpolation = author.table("lut-interpolation", x=points, affine=2.4 * points - 0.1,
                                 physical=(1 - fraction) * (2.4 * lo - 0.1) + fraction * (2.4 * hi - 0.1))
    body = [GROUP_BEGIN, panel(r"xlabel={Shaped coordinate},ylabel={Linear ACEScg component},title={Nonuniform cell address}"),
            line(decoder, options="bookblue"),
            panel(r"xlabel={Linear component},ylabel={Output component},title={Affine reproduction},"
                  r"xticklabel style={/pgf/number format/fixed,/pgf/number format/precision=2}," + LEGEND_BELOW),
            line(interpolation, "affine", "Affine reference", "bookblue"),
            line(interpolation, "physical", "Physical-cell interpolation", "bookorange,dashed"), GROUP_END]
    author.plot("lut-interpolation", "Shaping and physical-cell interpolation",
                "The input shaper locates a nonuniform cell. Physical linear-RGB fractions reproduce the affine reference, so the two curves coincide.", body)

    labels = ("Shader / small", "Shader / full", "Compositor")
    lines = ["| Workload | Method | Preparation (s) | Median render (s) |", "| --- | --- | ---: | ---: |"]
    benchmark_tables = []
    for index, method in enumerate(("LUT", "DIRECT")):
        selected = [next(row for row in benchmark["cases"] if row["workload"] == workload and row["method"] == method)
                    for workload in ("shader-small", "shader-full", "compositor-full")]
        benchmark_tables.append(author.table("render-benchmark-" + method.lower(),
            x=np.arange(3) + (index - 0.5) * 0.34,
            render=[statistics.median(row["render_seconds"]) for row in selected],
            preparation=[row["prepare_seconds"] for row in selected]))
        for label, row in zip(labels, selected):
            lines.append(f"| {label} | {method} | {row['prepare_seconds']:.3f} | {statistics.median(row['render_seconds']):.3f} |")
    body = [GROUP_BEGIN]
    for metric, title in (("render", "Steady render"), ("preparation", "Graph and grade preparation")):
        body.append(panel(r"ylabel={Seconds},ymin=0,xmin=-0.6,xmax=2.6,"
                          r"xtick={0,1,2},xticklabels={Small shader,Full shader,Compositor},"
                          r"x tick label style={rotate=25,anchor=east},title={" + title + "}," + LEGEND_BELOW))
        for index, (table, label) in enumerate(zip(benchmark_tables, ("Baked LUT", "Direct"))):
            body.append(line(table, metric, label, COLORS[index] + ",ybar,solid,area legend,bar width=6pt,fill=" + COLORS[index]))
    body.append(GROUP_END)
    status = "ILLUSTRATIVE DATA: replace with workstation measurements" if benchmark["status"] == "illustrative" else "Measured on " + benchmark["environment"]["device"]
    body.append(r"\node[anchor=south,font=\small] at ([yshift=7mm]current bounding box.north) {" + tex_text(status) + "};")
    author.plot("render-benchmark", "Workload and preparation comparison", status + ". Median render time and preparation time compare Baked LUT and Direct for three workloads.", body)
    label = "Illustrative data. These values demonstrate the reporting layout." if benchmark["status"] == "illustrative" else "Workstation measurements. See the linked JSON for settings and every trial."
    (fragments / "benchmark.md").write_text(label + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    sample, sample_energy = rg.guard(np.array([50., 80., 0.]), rr.hk_energy(50., 80.), reference_energy)
    return {"model": "perceptual-grade-reference", "reference_nits": tone.reference,
            "peak_nits": tone.peak, "shadow_ratio": rg.LOW_Y, "tone_targets": tone.target.tolist(),
            "chroma_drivers": {"p": 2, "s0": 75 * rg.CHROMA_CROSSOVER, "Cn": 2.},
            "guard_sample_50_80": sample.tolist(), "guard_sample_energy": float(sample_energy)}


def historical_plots(author, data, fragments):
    historical_figures.write_tables(data, author.root)
    for study, key, title in (("shaper", "shaper_errors", "Shaper finalists"),
                              ("domain128", "domain_errors", "Domain-128 finalists")):
        body = [SCATTER_BEGIN]
        for metric, x_label, y_metric, y_label in (
            ("scene_p99", "Scene RGB p99", "display_p99", r"Rendered $\Delta E_{\mathrm{ITP}}$ p99" if study == "shaper" else "Encoded RGB p99"),
            ("scene_rms", "Scene RGB RMS", "display_p99" if study == "shaper" else "display_rms", r"Rendered $\Delta E_{\mathrm{ITP}}$ p99" if study == "shaper" else "Encoded RGB RMS"),
        ):
            body.append(panel("xlabel={" + x_label + "},ylabel={" + y_label + "},title={"
                              + ("p99 tradeoff" if metric == "scene_p99" else "RMS tradeoff")
                              + r"},enlargelimits=0.17,legend style={at={(0.5,-0.28)},anchor=north,legend columns=3}"))
            for index, row in enumerate(data[key]):
                color = {"Rec2020": "bookblue", "AP1_ACES": "bookgreen", "AP1_D65": "bookorange", "Rec2020_D65": "bookblue"}[row["basis"]]
                if study == "shaper":
                    color = COLORS[index % len(COLORS)]
                marker = "star" if row["selected"] else "x" if row["baseline"] else ("*", "square*", "triangle*", "diamond*", "pentagon*")[index % 5]
                size = "3.2pt" if row["selected"] else "2.5pt" if row["baseline"] else "1.6pt"
                # Metric-specific names keep the two scatter panels independent.
                metric_table = author.table(f"lut-{study}-{row['id']}-{metric}", x=[row[metric]], y=[row[y_metric]])
                body.append(line(metric_table, label=row["id"], options=f"{color},only marks,mark={marker},mark size={size}"))
        body.append(GROUP_END)
        author.plot("lut-" + study + "-errors", title + " error tradeoffs",
                    ("Recorded full-finalist shaper scores. " if study == "shaper" else "Recorded full-finalist scores rounded to eight decimal places in the domain-128 report. ")
                    + "Candidate IDs identify the key below. Stars mark the selected candidate and crosses mark the historical baseline.", body)

        rows = ["| ID | Candidate | Role |", "| --- | --- | --- |"]
        for row in data[key]:
            name = html.escape(row["name"]).replace("_", "_<wbr>")
            role = "Selected" if row["selected"] else "Baseline" if row["baseline"] else "Finalist"
            rows.append(f"| {row['id']} | <code>{name}</code> | {role} |")
        (fragments / ("lut-" + study + "-key.md")).write_text("\n".join(rows) + "\n", encoding="utf-8")

    for study, key, title in (("shaper", "shaper_axes", "Shaper sample placement"),
                              ("domain128", "domain_axes", "Domain-128 sample placement")):
        body = [GROUP_BEGIN]
        for branch, panel_title in (("negative", "Negative branch"), ("positive", "Positive branch")):
            body.append(panel(r"xlabel={Vertex index away from zero},ylabel={Channel magnitude},ymode=log,title={"
                              + panel_title + "}," + LEGEND_BELOW))
            for index, record in enumerate(data[key]):
                if branch == "negative" and not record["negative_branch"]:
                    continue
                table = f"tables/lut-{study}-{record['id']}-{branch}.dat"
                role = " selected" if record["selected"] else " baseline" if record["baseline"] else ""
                body.append(line(table, "magnitude", record["id"] + role,
                                 SERIES[index] + ",mark=*,mark size=0.8pt", x="index"))
        body.append(GROUP_END)
        author.plot("lut-" + study + "-placement", title,
                    "Negative and positive vertex magnitudes are indexed away from zero on logarithmic axes. Zero is omitted; native AP1 has no negative branch. Candidate IDs match the error-chart key."
                    if study == "domain128" else
                    "Original and selected shaper grids show negative and positive vertex magnitudes on logarithmic axes. Zero is omitted and each branch is indexed away from zero.", body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("data", "historical", "style", "output-dir"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args(argv)
    author = Author(args.output_dir)
    fragments = args.output_dir / "fragments"
    fragments.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.style, args.output_dir / "plot-style.tex")
    benchmark = benchmark_data(args.data / "benchmark.json")
    numerical = numeric_figures(author, benchmark, fragments)
    inputs = [args.historical / name for name in
              ("shaper.zip", "shaper-selection.json", "domain-report.md", "domain-selection.json")]
    historical = historical_figures.load_historical_figures(*inputs)
    historical_plots(author, historical, fragments)
    write_json(args.output_dir / "numerical-data.json", numerical)
    write_json(args.output_dir / "figures.json", {"figures": author.figures})
    manifest(args.output_dir,
             [args.data / "benchmark.json", args.style, Path(__file__), Path(historical_figures.__file__),
              *inputs, *(Path(module.__file__) for module in (lm, tm, cm, lut, ra, rg, rm, rr, hg, scaled))],
             "Perceptual Grade current-reference and historical numerical tables and PGFPlots sources",
             {"docs/data": args.data, "historical": args.historical,
              "plot-style": args.style.parent, "generators": Path(__file__).parent,
              "legacy": Path(lm.__file__).parent.parent,
              "reference": Path(rg.__file__).parent,
              "shared-model": Path(hg.__file__).parent,
              "color-core": Path(scaled.__file__).parent})


if __name__ == "__main__":
    main()
