/** Check final SVG label geometry using the declared Chromium and embedded fonts. */
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const TOLERANCE = 0.5;

export async function launchBrowser(chromiumPath, modules) {
  const { chromium } = await import(pathToFileURL(resolve(modules, "playwright-core/index.mjs")).href);
  return chromium.launch({
    executablePath: resolve(chromiumPath),
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-webgpu", "--disable-gpu"],
  });
}

export async function measureSvg(page, source) {
  await page.setContent(source, { waitUntil: "load" });
  return page.evaluate(async () => {
    const root = document.querySelector("svg");
    if (!root || document.querySelector("parsererror")) throw new Error("Missing or invalid SVG root");
    // Explicitly load all declared faces, including a face first used by an
    // offscreen label. Measuring a fallback font would make this check unsound.
    const fonts = [...document.fonts];
    await Promise.all(fonts.map(async font => {
      try {
        await font.load();
      } catch (error) {
        throw new Error(`Could not load embedded SVG font ${font.family}: ${error.message}`);
      }
    }));
    await document.fonts.ready;
    if (fonts.some(font => font.status !== "loaded")) {
      throw new Error(`SVG fonts did not load: ${fonts.map(font => `${font.family}:${font.status}`).join(", ")}`);
    }
    const rootMatrix = root.getScreenCTM();
    if (!rootMatrix) throw new Error("SVG has no coordinate transform");
    const inverse = rootMatrix.inverse();
    const labels = [];
    for (const element of root.querySelectorAll("text")) {
      // A text element owns all its tspans. Descendants are never compared
      // against their parent; reusable definitions are not visible instances.
      if (element.closest("defs, mask, marker, clipPath, symbol")) continue;
      const text = [...element.childNodes].map(node => node.textContent).join(" ").replace(/\s+/g, " ").trim();
      if (!text) continue;
      const style = getComputedStyle(element);
      if (style.visibility !== "visible") continue;
      let hidden = false;
      for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
        const ancestorStyle = getComputedStyle(ancestor);
        if (ancestorStyle.display === "none" || Number(ancestorStyle.opacity) === 0) hidden = true;
      }
      if (hidden || (style.fill === "none" && style.stroke === "none")) continue;
      const family = style.fontFamily.split(",")[0].trim().replace(/^["']|["']$/g, "");
      if (!fonts.some(font => font.family.replace(/^["']|["']$/g, "") === family)) {
        throw new Error(`Visible label uses an undeclared font ${family}: ${text}`);
      }
      const box = element.getBBox();
      const screenMatrix = element.getScreenCTM();
      if (!screenMatrix || box.width <= 0 || box.height <= 0) {
        throw new Error(`Unmeasurable visible label: ${text}; width=${box.width}, height=${box.height}`);
      }
      const matrix = inverse.multiply(screenMatrix);
      const points = [
        [box.x, box.y], [box.x + box.width, box.y],
        [box.x, box.y + box.height], [box.x + box.width, box.y + box.height],
      ].map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix));
      const bounds = {
        left: Math.min(...points.map(point => point.x)),
        top: Math.min(...points.map(point => point.y)),
        right: Math.max(...points.map(point => point.x)),
        bottom: Math.max(...points.map(point => point.y)),
      };
      if (!Object.values(bounds).every(Number.isFinite)) throw new Error(`Invalid label bounds: ${text}`);
      const owner = element.closest("g[id], g[class]");
      labels.push({ text, owner: owner?.id || owner?.getAttribute("class") || "", bounds });
    }
    if (!labels.length) throw new Error("SVG has no visible text labels");
    return { labels, embedded_font_count: fonts.length };
  });
}

export function findCollisions(labels, tolerance = TOLERANCE) {
  const collisions = [];
  for (let first = 0; first < labels.length; first += 1) {
    for (let second = first + 1; second < labels.length; second += 1) {
      const a = labels[first].bounds;
      const b = labels[second].bounds;
      const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (width > tolerance && height > tolerance) {
        collisions.push({ first: labels[first], second: labels[second], overlap: { width, height } });
      }
    }
  }
  return collisions;
}

export async function checkFigures({ chromiumPath, modules, svgDirectory, manifest }) {
  const browser = await launchBrowser(chromiumPath, modules);
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
    page.setDefaultTimeout(30_000);
    // All production SVG resources must be embedded. Block accidental fetches
    // even if a future renderer lets an external resource through its validator.
    await page.route(/^https?:/, route => route.abort());
    const packageInfo = JSON.parse(await readFile(resolve(modules, "playwright-core/package.json"), "utf8"));
    const report = {
      schema: 1,
      engine: "Chromium",
      browser_version: browser.version(),
      node_version: process.versions.node,
      playwright_version: packageInfo.version,
      tolerance_svg_units: TOLERANCE,
      figures: {},
    };
    const failures = [];
    for (const figure of manifest.figures) {
      try {
        const source = await readFile(resolve(svgDirectory, `${figure.id}.svg`), "utf8");
        const measured = await measureSvg(page, source);
        if (!measured.embedded_font_count) throw new Error("SVG has no embedded font declarations");
        const collisions = findCollisions(measured.labels);
        report.figures[figure.id] = {
          label_count: measured.labels.length,
          embedded_font_count: measured.embedded_font_count,
          collision_count: collisions.length,
        };
        for (const collision of collisions) failures.push({ figure: figure.id, ...collision });
      } catch (error) {
        failures.push({ figure: figure.id, error: error.message });
      }
    }
    if (failures.length) throw new Error(`Diagram label check failed:\n${JSON.stringify(failures, null, 2)}`);
    return report;
  } finally {
    await browser.close();
  }
}

async function main() {
  function required(name) {
    const index = process.argv.indexOf(name);
    if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}`);
    return process.argv[index + 1];
  }
  const report = await checkFigures({
    chromiumPath: required("--chromium"),
    modules: required("--node-modules"),
    svgDirectory: required("--svg-dir"),
    manifest: JSON.parse(await readFile(required("--manifest"), "utf8")),
  });
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
