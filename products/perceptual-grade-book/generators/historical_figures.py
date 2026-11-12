"""Read recorded LUT studies for publication without rerunning the experiments.

The domain-128 scatter coordinates retain the report's eight decimal places.
Only two placement axes are reconstructed, from the original sampling formulas;
neither reconstruction evaluates the grading model or repeats a measured study.
"""

import csv
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile


SHAPER_BASELINE = "Rec2020_neg4_n16_asinh0.001"
SHAPER_SELECTED = "Rec2020_neg2_n20_log1p0.003"
DOMAIN_BASELINE = "Rec2020_D65_neg2_pos64_n20_log1p0.003"
DOMAIN_SELECTED = "AP1_ACES_neg0_pos128_n0_logpower0.003_p0.9"
RECONSTRUCTED_GRIDS = {
    "AP1_D65_neg2_pos128_n2_asinh0.01": {
        "basis": "AP1_D65", "negative": 2.0, "negative_cells": 2,
        "positive": 128.0, "family": "asinh", "k": 0.01,
    },
    "Rec2020_D65_neg4_pos128_n8_logtoe0.003": {
        "basis": "Rec2020_D65", "negative": 4.0, "negative_cells": 8,
        "positive": 128.0, "family": "logtoe", "k": 0.003,
    },
}
DOMAIN_FIELDS = ("scene_p99", "scene_rms", "display_p99", "display_rms")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _positive(value, context):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Non-numeric {context}")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Expected a finite positive {context}")
    return value


def _validate_axis(values, name):
    if len(values) != 65 or any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) for value in values
    ):
        raise ValueError(f"Expected 65 finite vertices for {name}")
    if values.count(0) != 1 or any(a >= b for a, b in zip(values, values[1:])):
        raise ValueError(f"Expected a strictly increasing, zero-containing axis for {name}")
    return list(values)


def reconstruct_axis(parameters):
    """Reconstruct the two missing signed axes using the published base curves.

    With p=64-n positive cells, a branch is k*h^-1(j*h(extent/k)/cells).
    The negative scale matches k*h(positive/k)/p at zero, using the original
    100-step bisection in log(k) over [-40, log(negative*1e6)]. These formulas
    follow the 1.23.2 study's tests/blender/domain128_grid.py, Grid.axis.
    """
    family = parameters["family"]
    if family == "asinh":
        transform, inverse = math.asinh, math.sinh
    elif family == "logtoe":
        transform = lambda value: value if value <= 1 else 1 + math.log(value)
        inverse = lambda value: value if value <= 1 else math.exp(value - 1)
    else:
        raise ValueError(f"Unsupported reconstruction family: {family}")
    negative = _positive(parameters["negative"], "negative extent")
    positive = _positive(parameters["positive"], "positive extent")
    scale = _positive(parameters["k"], "positive scale")
    n = parameters["negative_cells"]
    if isinstance(n, bool) or not isinstance(n, int) or not 0 < n < 64 or n % 2:
        raise ValueError("Reconstructed signed axes require an even negative allocation")
    p = 64 - n
    slope = scale * transform(positive / scale) / p
    if slope >= negative / n:
        raise ValueError("No matching negative scale exists")
    lo, hi = -40.0, math.log(negative * 1e6)
    for _ in range(100):
        mid = (lo + hi) / 2
        candidate = math.exp(mid)
        if candidate * transform(negative / candidate) / n < slope:
            lo = mid
        else:
            hi = mid
    negative_scale = math.exp((lo + hi) / 2)

    def branch(extent, count, k):
        return [k * inverse(j / count * transform(extent / k)) for j in range(count + 1)]

    below = branch(negative, n, negative_scale)
    above = branch(positive, p, scale)
    axis = [-value for value in reversed(below)] + above[1:]
    axis[0], axis[n], axis[-1] = -negative, 0.0, positive
    return _validate_axis(axis, parameters["basis"]), negative_scale


def _candidate_rows(rows, prefix, selected, baseline):
    names = [row["name"] for row in rows]
    if len(rows) != 12 or len(set(names)) != 12 or not {selected, baseline} <= set(names):
        raise ValueError("Historical figures require twelve unique finalists, including selection and baseline")
    return [dict(row, id=f"{prefix}{index:02d}", selected=row["name"] == selected,
                 baseline=row["name"] == baseline)
            for index, row in enumerate(sorted(rows, key=lambda row: row["name"]), 1)]


def _domain_rows(report, selection):
    sections = report.split("## Full photographic finalists\n")
    if len(sections) != 2:
        raise ValueError("Missing or repeated domain-128 finalist section")
    section = sections[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("| ") or not cells[0].startswith(("AP1_", "Rec2020_")):
            continue
        if len(cells) != 7 or any(not re.fullmatch(r"[0-9]+\.[0-9]{8}", value) for value in cells[1:5]):
            raise ValueError("Domain-128 coordinates must retain eight report decimal places")
        name = cells[0]
        values = {field: _positive(float(value), field) for field, value in zip(DOMAIN_FIELDS, cells[1:5])}
        rows.append({"name": name, "basis": name.split("_neg", 1)[0], **values,
                     "recorded_values": dict(zip(DOMAIN_FIELDS, cells[1:5])),
                     "source_decimal_places": 8})
    if {row["name"] for row in rows} != set(selection["tested_full_finalists"]):
        raise ValueError("Domain-128 report and selection disagree about finalists")
    rows = _candidate_rows(rows, "D", selection["selected"], DOMAIN_BASELINE)
    by_name = {row["name"]: row for row in rows}
    # The two exact records confirm the table's printed precision. Do not mix
    # their extra digits into a scatter plot whose other points are rounded.
    for name, score in ((selection["selected"], selection["score"]),
                        (DOMAIN_BASELINE, selection["baseline_score"])):
        for field in DOMAIN_FIELDS:
            expected = f"{score['worst_' + field]:.8f}"
            if by_name[name]["recorded_values"][field] != expected:
                raise ValueError(f"Domain-128 table disagrees with exact {name} {field}")
    return rows


def _axis_record(candidate, values, source, parameters, reconstructed=False, negative_scale=None):
    axis = _validate_axis(values, candidate["name"])
    return {key: candidate[key] for key in ("id", "name", "basis", "selected", "baseline")} | {
        "axis": axis, "negative_branch": axis[0] < 0, "source": source,
        "formula_reconstructed": reconstructed, "parameters": dict(parameters),
        "reconstructed_negative_scale": negative_scale,
    }


def load_historical_figures(shaper_archive, shaper_selection, domain_report, domain_selection):
    """Return the four figures' data and provenance from declared input paths."""
    shaper = _read_json(shaper_selection)
    domain = _read_json(domain_selection)
    if shaper["selected"] != SHAPER_SELECTED or domain["selected"] != DOMAIN_SELECTED:
        raise ValueError("Unexpected historical study selection")
    with zipfile.ZipFile(shaper_archive) as archive:
        ranking = json.loads(archive.read("results/full-ranking.json"))
        rows = []
        for record in ranking:
            score = record["score"]
            rows.append({
                "name": record["name"], "basis": "Rec2020",
                "scene_p99": _positive(score["worst_absolute_rgb_p99"], "scene p99"),
                "scene_rms": _positive(max(score["absolute_rgb_rms"].values()), "scene RMS"),
                "display_p99": _positive(score["worst_display_p99"], "display p99"),
                "source_decimal_places": None,
            })
        if {row["name"] for row in rows} != set(shaper["tested_full_finalists"]):
            raise ValueError("Shaper archive and selection disagree about finalists")
        shaper_rows = _candidate_rows(rows, "S", shaper["selected"], SHAPER_BASELINE)
        shaper_by_name = {row["name"]: row for row in shaper_rows}
        shaper_axes = []
        for name in (SHAPER_BASELINE, shaper["selected"]):
            member = f"results/full/{name}.json"
            record = json.loads(archive.read(member))
            shaper_axes.append(_axis_record(shaper_by_name[name], record["axis"],
                                          "lut-shaper-report.zip/" + member, record["grid"]))
        if shaper_axes[1]["axis"] != shaper["axis"]:
            raise ValueError("Shaper archive and selection disagree about the selected axis")
    domain_rows = _domain_rows(Path(domain_report).read_text(encoding="utf-8"), domain)
    domain_by_name = {row["name"]: row for row in domain_rows}
    baseline_grid = dict(shaper["grid"], basis="Rec2020_D65")
    domain_axes = [
        _axis_record(domain_by_name[DOMAIN_BASELINE], shaper["axis"],
                     "lut-shaper-selection.json/axis", baseline_grid),
        _axis_record(domain_by_name[domain["selected"]], domain["axis"],
                     "lut-domain128-selection.json/axis", domain["grid"]),
    ]
    for name, parameters in RECONSTRUCTED_GRIDS.items():
        axis, negative_scale = reconstruct_axis(parameters)
        domain_axes.append(_axis_record(domain_by_name[name], axis,
                           "documented domain-128 sampling formula", parameters,
                           reconstructed=True, negative_scale=negative_scale))
    return {
        "shaper_errors": shaper_rows, "shaper_axes": shaper_axes,
        "domain_errors": domain_rows, "domain_axes": domain_axes,
        "provenance": {
            "inputs": {name: _digest(path) for name, path in (
                ("lut-shaper-report.zip", shaper_archive),
                ("lut-shaper-selection.json", shaper_selection),
                ("lut-domain128-report.md", domain_report),
                ("lut-domain128-selection.json", domain_selection),
            )},
            "shaper_errors": "Recorded full-ranking scores; scene RMS is the maximum across RGB spaces.",
            "domain_errors": {"source": "Full photographic finalists table", "decimal_places": 8,
                              "maximum_rounding_error": 5e-9,
                              "exact_selection_scores_used_only_to_verify_rounding": True},
            "domain_axes": {"recorded": [DOMAIN_BASELINE, DOMAIN_SELECTED],
                            "formula_reconstructed": RECONSTRUCTED_GRIDS,
                            "formula_source": "Perceptual Grade 1.23.2 tests/blender/domain128_grid.py: Grid.axis",
                            "negative_scale_solver": {"log_lower": -40.0,
                                "log_upper": "log(negative_extent * 1e6)", "iterations": 100}},
        },
    }


def _write_rows(path, columns, rows, delimiter=","):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([format(value, ".17g") if isinstance(value, float)
                             else int(value) if isinstance(value, bool)
                             else "" if value is None else value for value in row])


def write_tables(data, source_root):
    """Write CSV downloads and whitespace .dat tables below source_root/tables.

    Return paths relative to source_root, suitable for PGFPlots table inputs.
    Axis .dat files contain index/magnitude columns; zeros are deliberately
    absent from the logarithmic branch plots. The JSON metadata records axes
    with no negative branch instead of emitting an empty negative table.
    """
    root = Path(source_root)
    tables = root / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for study, rows_key, axes_key in (("shaper", "shaper_errors", "shaper_axes"),
                                     ("domain128", "domain_errors", "domain_axes")):
        rows, axes = data[rows_key], data[axes_key]
        metrics = ("scene_p99", "scene_rms", "display_p99") if study == "shaper" else DOMAIN_FIELDS
        metric_columns = ("id", *metrics, "selected", "baseline")
        metric_rows = [[row["id"], *(row.get("recorded_values", row)[field] for field in metrics),
                        row["selected"], row["baseline"]] for row in rows]
        for suffix, delimiter in (("csv", ","), ("dat", " ")):
            filename = f"lut-{study}-errors.{suffix}"
            _write_rows(tables / filename, metric_columns, metric_rows, delimiter)
            outputs[filename] = "tables/" + filename
        filename = f"lut-{study}-candidates.csv"
        candidate_columns = ("id", "name", "basis", "selected", "baseline", "source_decimal_places")
        _write_rows(tables / filename, candidate_columns,
                    [[row[field] for field in candidate_columns] for row in rows])
        outputs[filename] = "tables/" + filename
        placement_rows = []
        for record in axes:
            branches = {
                "negative": [-value for value in reversed(record["axis"]) if value < 0],
                "positive": [value for value in record["axis"] if value > 0],
            }
            for branch, values in branches.items():
                points = list(enumerate(values, 1))
                placement_rows.extend([[record["id"], branch, index, magnitude,
                                       record["formula_reconstructed"]] for index, magnitude in points])
                if points:
                    filename = f"lut-{study}-{record['id']}-{branch}.dat"
                    _write_rows(tables / filename, ("index", "magnitude"), points, " ")
                    outputs[filename] = "tables/" + filename
        filename = f"lut-{study}-placement.csv"
        _write_rows(tables / filename, ("id", "branch", "index", "magnitude", "formula_reconstructed"), placement_rows)
        outputs[filename] = "tables/" + filename
    filename = "historical-figures.json"
    (tables / filename).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    outputs[filename] = "tables/" + filename
    return outputs
