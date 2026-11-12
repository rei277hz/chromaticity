"""Historical chart data keeps recorded precision and signed-grid semantics."""

import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from pg_book_generators.historical_figures import (
    DOMAIN_BASELINE,
    DOMAIN_SELECTED,
    RECONSTRUCTED_GRIDS,
    SHAPER_BASELINE,
    SHAPER_SELECTED,
    _domain_rows,
    load_historical_figures,
    reconstruct_axis,
    write_tables,
)


RESOURCES = Path(__file__).with_name("historical_inputs")


class HistoricalFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_historical_figures(
            RESOURCES / "shaper.zip", RESOURCES / "shaper-selection.json",
            RESOURCES / "domain-report.md", RESOURCES / "domain-selection.json",
        )

    def test_shaper_uses_original_measurements_and_stable_ids(self):
        rows = self.data["shaper_errors"]
        self.assertEqual([row["id"] for row in rows], [f"S{index:02d}" for index in range(1, 13)])
        selected = next(row for row in rows if row["selected"])
        baseline = next(row for row in rows if row["baseline"])
        self.assertEqual(selected["name"], SHAPER_SELECTED)
        self.assertEqual(baseline["name"], SHAPER_BASELINE)
        self.assertEqual(selected["scene_p99"], 0.02558291713619288)
        self.assertEqual(selected["scene_rms"], 0.012655700821490323)
        self.assertEqual(selected["display_p99"], 2.5140193009494345)
        self.assertEqual([axis["axis"][0] for axis in self.data["shaper_axes"]], [-4, -2])
        self.assertTrue(all(not axis["formula_reconstructed"] for axis in self.data["shaper_axes"]))

    def test_domain_coordinates_keep_report_precision(self):
        rows = self.data["domain_errors"]
        self.assertEqual([row["id"] for row in rows], [f"D{index:02d}" for index in range(1, 13)])
        selected = next(row for row in rows if row["selected"])
        self.assertEqual(selected["name"], DOMAIN_SELECTED)
        self.assertEqual(selected["recorded_values"]["scene_p99"], "0.04168850")
        self.assertEqual(selected["scene_p99"], 0.04168850)
        self.assertEqual(selected["display_p99"], 0.00538943)
        self.assertTrue(all(row["source_decimal_places"] == 8 for row in rows))
        report = (RESOURCES / "domain-report.md").read_text(encoding="utf-8")
        selection = json.loads((RESOURCES / "domain-selection.json").read_text())
        with self.assertRaisesRegex(ValueError, "eight report decimal places"):
            _domain_rows(report.replace("0.04168850", "0.0416885", 1), selection)
        with self.assertRaisesRegex(ValueError, "disagrees with exact"):
            _domain_rows(report.replace("0.04168850", "0.04168851", 1), selection)

    def test_axes_preserve_zero_negative_allocation_and_reconstruction_origin(self):
        axes = {axis["name"]: axis for axis in self.data["domain_axes"]}
        self.assertEqual(axes[DOMAIN_BASELINE]["axis"], self.data["shaper_axes"][1]["axis"])
        self.assertFalse(axes[DOMAIN_SELECTED]["negative_branch"])
        self.assertEqual(axes[DOMAIN_SELECTED]["axis"][0], 0)
        self.assertEqual(axes[DOMAIN_SELECTED]["axis"][-1], 128)
        self.assertEqual({name for name, axis in axes.items() if axis["formula_reconstructed"]}, set(RECONSTRUCTED_GRIDS))
        for name, parameters in RECONSTRUCTED_GRIDS.items():
            with self.subTest(name=name):
                record = axes[name]
                axis = record["axis"]
                n = parameters["negative_cells"]
                self.assertEqual(len(axis), 65)
                self.assertEqual(axis[0], -parameters["negative"])
                self.assertEqual(axis[n], 0)
                self.assertEqual(axis[-1], parameters["positive"])
                self.assertEqual(sum(value < 0 for value in axis), n)
                self.assertTrue(all(a < b for a, b in zip(axis, axis[1:])))
                transform = math.asinh if parameters["family"] == "asinh" else lambda value: value if value <= 1 else 1 + math.log(value)
                scale, negative_scale = parameters["k"], record["reconstructed_negative_scale"]
                positive_slope = scale * transform(parameters["positive"] / scale) / (64 - n)
                negative_slope = negative_scale * transform(parameters["negative"] / negative_scale) / n
                self.assertAlmostEqual(positive_slope, negative_slope, delta=positive_slope * 1e-12)
        with self.assertRaisesRegex(ValueError, "even negative allocation"):
            reconstruct_axis(dict(next(iter(RECONSTRUCTED_GRIDS.values())), negative_cells=3))

    def test_tables_keep_candidate_keys_and_omit_logarithmic_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = write_tables(self.data, root)
            with (root / paths["lut-domain128-errors.csv"]).open(newline="") as stream:
                metrics = list(csv.DictReader(stream))
            selected = next(row for row in metrics if row["selected"] == "1")
            self.assertEqual(selected["scene_p99"], "0.04168850")
            self.assertEqual(selected["display_rms"], "0.00137624")
            with (root / paths["lut-domain128-candidates.csv"]).open(newline="") as stream:
                candidates = {row["id"]: row for row in csv.DictReader(stream)}
            self.assertEqual(candidates[selected["id"]]["name"], DOMAIN_SELECTED)
            self.assertEqual(candidates[selected["id"]]["source_decimal_places"], "8")
            self.assertNotIn(f"lut-domain128-{selected['id']}-negative.dat", paths)
            with (root / paths["lut-domain128-placement.csv"]).open(newline="") as stream:
                placement = list(csv.DictReader(stream))
            self.assertTrue(all(float(row["magnitude"]) > 0 for row in placement))
            baseline = next(row for row in self.data["domain_errors"] if row["baseline"])
            negative = [row for row in placement if row["id"] == baseline["id"] and row["branch"] == "negative"]
            self.assertEqual([int(row["index"]) for row in negative], list(range(1, 21)))
            self.assertEqual(float(negative[-1]["magnitude"]), 2)
            first = {name: (root / path).read_bytes() for name, path in paths.items()}
            write_tables(self.data, root)
            self.assertEqual(first, {name: (root / path).read_bytes() for name, path in paths.items()})


if __name__ == "__main__":
    unittest.main()
