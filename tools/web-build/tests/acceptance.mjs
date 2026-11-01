/** Exercise an extracted production archive with no development server. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

function argument(name) {
  const index = process.argv.indexOf(name);
  return index < 0 ? undefined : process.argv[index + 1];
}

const site = argument("--site");
assert.ok(site, "--site must name an extracted static site");
const root = resolve(site);
const samplePng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
const chromiumPath = argument("--chromium") ?? process.env.CHROMIUM;
assert.ok(chromiumPath, "--chromium or CHROMIUM must name the declared browser");
const modules = argument("--node-modules");
const { chromium } = await import(modules
  ? pathToFileURL(resolve(modules, "playwright-core/index.mjs")).href
  : "playwright-core");

const types = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".wasm": "application/wasm", ".json": "application/json", ".png": "image/png", ".txt": "text/plain", ".svg": "image/svg+xml" };
const requests = [];
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://127.0.0.1");
    requests.push(url.pathname);
    let pathname = decodeURIComponent(url.pathname);
    if (pathname.startsWith("/nested/")) pathname = pathname.slice("/nested".length);
    if (pathname.endsWith("/")) pathname += "index.html";
    const file = resolve(root, "." + pathname);
    if (!file.startsWith(root + sep)) throw new Error("Unsafe static request");
    if (!(await stat(file)).isFile()) throw new Error("Not a file");
    response.writeHead(200, { "Content-Type": types[extname(file)] ?? "application/octet-stream", "Cache-Control": "no-store" });
    response.end(await readFile(file));
  } catch {
    response.writeHead(404);
    response.end("Not found");
  }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({
    executablePath: chromiumPath,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-webgpu"],
  });
  for (const prefix of ["/", "/nested/"]) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    // Disable WebGPU in both window and worker contexts through Chromium's flag;
    // the renderer assertions below prove that the fallback actually executed.
    const errors = [];
    const failed = [];
    const external = [];
    context.on("request", request => {
      const url = request.url();
      if (/^https?:/.test(url) && !url.startsWith(origin + "/")) external.push(url);
    });
    context.on("requestfailed", request => failed.push(`${request.url()}: ${request.failure()?.errorText}`));
    context.on("response", response => {
      if (response.status() >= 400) failed.push(`${response.url()}: HTTP ${response.status()}`);
    });
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    page.setDefaultTimeout(90_000);
    await page.goto(origin + prefix, { waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#color-trackpad")?.dataset.colorcheckerRingCount === "18"
      && document.querySelector("#gamut-slice")?.dataset.renderer
      && document.querySelector("#preview-image")?.getAttribute("src")?.startsWith("blob:"));
    assert.equal(await page.locator("#gamut-slice").getAttribute("data-renderer"), "wasm");
    assert.equal(await page.locator('#image-gamut option[value="Adobe RGB"]').count(), 0);

    // View selection must update the real bundled worker's PNG output.
    const scene = await page.locator("#linear-value").textContent();
    for (const view of [1, 4, 2, 0]) {
      await page.locator("#preview").click();
      await page.locator(`#view-menu [data-view="${view}"]`).click();
      await page.waitForFunction(view => document.querySelector("#preview")?.dataset.view === String(view)
        && document.querySelector("#gamut-slice")?.dataset.view === String(view), view);
      assert.equal(await page.locator("#linear-value").textContent(), scene);
    }

    // A gesture reaches the exported numeric engine and produces a new preview.
    const pad = page.locator("#color-trackpad");
    const point = await pad.boundingBox();
    assert.ok(point);
    await page.mouse.click(point.x + point.width * 0.5, point.y + point.height * 0.5);
    await page.waitForFunction(() => document.querySelector("#color-trackpad")?.dataset.trackpadTracking === "active");
    await page.mouse.move(point.x + point.width * 0.52, point.y + point.height * 0.48);
    await page.mouse.click(point.x + point.width * 0.52, point.y + point.height * 0.48);
    await page.waitForFunction(() => document.querySelector("#color-trackpad")?.dataset.trackpadTracking === "idle");

    // Image decode initializes decomposition Wasm, then the nested transform pool.
    await page.locator("#image-file-input").setInputFiles({ name: "acceptance.png", mimeType: "image/png", buffer: samplePng });
    await page.waitForFunction(() => ["inspected", "true"].includes(document.querySelector("#image-panel")?.dataset.ready ?? ""));
    await page.locator("#image-options").click();
    await page.locator("#image-gamut").selectOption("Rec.709 / sRGB");
    await page.locator("#image-transfer").selectOption("sRGB");
    await page.locator("#image-options-close").click();
    await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true"
      && document.querySelector("#image-preview")?.getAttribute("src")?.startsWith("blob:"));
    assert.equal(await page.locator("#image-preview").getAttribute("data-renderer"), "wasm");
    const viewport = await page.locator("#image-viewport").boundingBox();
    assert.ok(viewport);
    await page.locator("#image-viewport").dispatchEvent("pointerdown", {
      pointerId: 501, pointerType: "mouse", button: 0,
      clientX: viewport.x + viewport.width / 2, clientY: viewport.y + viewport.height / 2,
    });
    await page.waitForFunction(() => Number(document.querySelector("#image-viewport")?.dataset.sampleCount ?? 0) > 0);
    assert.ok((await page.locator("#image-loupe").getAttribute("src"))?.startsWith("blob:"));

    assert.deepEqual(errors, [], `Runtime errors at ${prefix}`);
    assert.deepEqual(failed, [], `Failed requests at ${prefix}`);
    assert.deepEqual(external, [], `External requests at ${prefix}`);
    const loaded = requests.filter(path => path.startsWith(prefix + "assets/"));
    assert.ok(loaded.some(path => /render_worker.*\.js$/.test(path)), `Render worker was requested at ${prefix}`);
    assert.ok(loaded.some(path => /image_locator_worker.*\.js$/.test(path)), `Image worker was requested at ${prefix}`);
    assert.ok(loaded.some(path => /image_transform_worker.*\.js$/.test(path)), `Nested transform worker was requested at ${prefix}`);
    assert.ok(new Set(loaded.filter(path => path.endsWith(".wasm"))).size >= 2, `Both Wasm libraries were requested at ${prefix}`);
    await context.close();
    console.log(`Production archive passed at ${prefix}`);
  }

  const mobile = await browser.newContext({ viewport: { width: 360, height: 645 }, deviceScaleFactor: 3 });
  const page = await mobile.newPage();
  const mobileErrors = [];
  page.on("pageerror", error => mobileErrors.push(error.message));
  page.setDefaultTimeout(90_000);
  await page.goto(origin + "/nested/", { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.querySelector("#color-trackpad")?.dataset.colorcheckerRingCount === "18");
  async function checkMobileLayout() {
    const layout = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      scroll: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
      viewport: [innerWidth, innerHeight],
      bottom: document.querySelector(".app-shell").getBoundingClientRect().bottom,
    }));
    assert.equal(layout.dpr, 3);
    assert.deepEqual(layout.scroll, layout.viewport);
    assert.ok(layout.bottom <= 646, JSON.stringify(layout));
  }
  await checkMobileLayout();
  await page.locator("#image-file-input").setInputFiles({ name: "mobile.png", mimeType: "image/png", buffer: samplePng });
  await page.waitForFunction(() => ["inspected", "true"].includes(document.querySelector("#image-panel")?.dataset.ready ?? ""));
  await page.locator("#image-options").click();
  await page.locator("#image-gamut").selectOption("Rec.709 / sRGB");
  await page.locator("#image-options-close").click();
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true");
  await checkMobileLayout();
  assert.deepEqual(mobileErrors, []);
  await mobile.close();
  console.log("Mobile 360x645 DPR-3 layout passed");
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
