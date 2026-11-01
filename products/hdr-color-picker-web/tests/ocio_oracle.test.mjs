import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  initSync,
  picker_colorchecker_mode,
  reference_forward_xyz,
  reference_inverse_acescg,
} from "../src/wasm/pkg/modcam16_color_core.js";
import { fileURLToPath } from "node:url";

const PYTHON = process.env.PYTHON ?? "python3";

test("WASM ACES path matches the independent PyOpenColorIO ACES 2.0 oracle", async () => {
  let output;
  try {
    output = execFileSync(PYTHON, ["tests/ocio_oracle.py"], {
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
    });
  } catch (error) {
    assert.fail(
      `PyOpenColorIO oracle failed. Install PyOpenColorIO or set PYTHON: ${error}`,
    );
  }
  const oracle = JSON.parse(output);
  initSync({
    module: new WebAssembly.Module(
      readFileSync(
        fileURLToPath(
          new URL(
            "../src/wasm/pkg/modcam16_color_core_bg.wasm",
            import.meta.url,
          ),
        ),
      ),
    ),
  });
  const vectors = oracle.vectors;
  for (const profile of ["0", "1", "2", "4"]) {
    const expected = oracle.profiles[profile];
    for (let index = 0; index < vectors.length; index += 1) {
      const vector = vectors[index];
      const actualForward = reference_forward_xyz(profile, ...vector);
      const actualInverse = reference_inverse_acescg(profile, ...vector);
      for (let channel = 0; channel < 3; channel += 1) {
        assert.ok(
          Math.abs(
            actualForward[channel] - expected.forward_xyz[index][channel],
          ) < 3e-5,
          `forward profile=${profile}, vector=${index}, channel=${channel}`,
        );
        assert.ok(
          Math.abs(
            actualInverse[channel] - expected.inverse_acescg[index][channel],
          ) < 3e-5,
          `inverse profile=${profile}, vector=${index}, channel=${channel}`,
        );
      }
    }
  }

  assert.equal(oracle.colorchecker.names.length, 18);
  for (const profile of ["0", "1", "2", "4"]) {
    const actual = picker_colorchecker_mode(Number(profile));
    const expected = oracle.colorchecker.views[profile];
    assert.equal(actual.length, 18 * 7);
    for (let patch = 0; patch < 18; patch += 1) {
      assert.equal(actual[patch * 7 + 6], 1);
      for (let channel = 0; channel < 3; channel += 1) {
        assert.ok(
          Math.abs(actual[patch * 7 + 3 + channel] - expected[patch][channel]) < 5e-5,
          `ColorChecker profile=${profile}, patch=${oracle.colorchecker.names[patch]}, channel=${channel}`,
        );
      }
    }
  }
});
