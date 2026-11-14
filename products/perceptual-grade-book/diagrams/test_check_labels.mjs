import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { launchBrowser, measureSvg, findCollisions, TOLERANCE } from "./check_labels.mjs";

function required(name) {
  const index = process.argv.indexOf(name);
  assert.ok(index >= 0 && process.argv[index + 1], `Missing ${name}`);
  return process.argv[index + 1];
}

const font = (await readFile(required("--font"))).toString("base64");

function svg(content) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 400 300">
    <style>@font-face { font-family: Fixture; src: url("data:font/ttf;base64,${font}"); }
      text { font-family: Fixture; font-size: 20px; }</style>${content}</svg>`;
}

const browser = await launchBrowser(required("--chromium"), required("--node-modules"));
try {
  const page = await browser.newPage();
  let measured = await measureSvg(page, svg('<text x="10" y="30">first</text><text x="200" y="30">second</text>'));
  assert.equal(measured.labels.length, 2);
  assert.deepEqual(findCollisions(measured.labels), []);

  measured = await measureSvg(page, svg('<g id="edge-a"><text x="10" y="30">first</text></g><g id="edge-b"><text x="20" y="30">second</text></g>'));
  assert.equal(findCollisions(measured.labels).length, 1);
  assert.equal(measured.labels[0].owner, "edge-a");

  measured = await measureSvg(page, svg('<text x="10" y="30"><tspan x="10">first</tspan><tspan x="10" dy="24">second</tspan></text><text x="200" y="30">other</text>'));
  assert.equal(measured.labels.length, 2, "Tspans belong to one label");
  assert.equal(measured.labels[0].text, "first second");
  assert.deepEqual(findCollisions(measured.labels), []);

  measured = await measureSvg(page, svg('<svg x="100" y="50" width="200" height="100" viewBox="0 0 100 50"><g transform="translate(5 2)"><text x="0" y="20">same</text></g></svg><text transform="translate(110 54) scale(2)" x="0" y="20">same</text>'));
  assert.equal(findCollisions(measured.labels).length, 1, "Nested SVG and group transforms share one coordinate system");
  for (const coordinate of ["left", "top", "right", "bottom"]) {
    assert.ok(Math.abs(measured.labels[0].bounds[coordinate] - measured.labels[1].bounds[coordinate]) < 0.01);
  }

  measured = await measureSvg(page, svg('<defs><text x="10" y="30">definition</text></defs><text x="10" y="30">visible</text><g style="display:none"><text x="10" y="30">display</text></g><text visibility="hidden" x="10" y="30">hidden</text><g opacity="0"><text x="10" y="30">transparent</text></g>'));
  assert.equal(measured.labels.length, 1);
  assert.equal(measured.labels[0].text, "visible");

  const box = (left, right) => ({ text: "fixture", bounds: { left, right, top: 0, bottom: 10 } });
  assert.deepEqual(findCollisions([box(0, 10), box(10, 20)]), [], "Touching is not overlap");
  assert.deepEqual(findCollisions([box(0, 10), box(10 - TOLERANCE, 20)]), []);
  assert.equal(findCollisions([box(0, 10), box(10 - TOLERANCE - 0.01, 20)]).length, 1);

  await assert.rejects(measureSvg(page, svg('<style>@font-face { font-family: Broken; src: url(data:font/woff2;base64,AAAA); } text { font-family: Broken; }</style><text x="10" y="30">broken</text>')), /font|network/i);
  await assert.rejects(measureSvg(page, svg('<text x="10" y="30" style="font-family: sans-serif">fallback</text>')), /undeclared font/);
  await assert.rejects(measureSvg(page, svg('<rect width="20" height="20"/>')), /no visible text/);
  process.stdout.write("SVG label collision fixtures passed\n");
} finally {
  await browser.close();
}
