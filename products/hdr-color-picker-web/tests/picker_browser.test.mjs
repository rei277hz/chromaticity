import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright-core";
import { createServer } from "vite";
import { readPng } from "./png_reader.mjs";

const CHROMIUM = process.env.CHROMIUM;
if (!CHROMIUM) {
  throw new Error("CHROMIUM must point to the declared Buck browser executable.");
}

test(
  "desktop color trackpad supports live mouse tracking and second-click commit",
  { timeout: 60_000 },
  async (context) => {
    const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
    await server.listen();
    const address = server.httpServer?.address();
    assert.ok(address && typeof address !== "string");
    const browser = await chromium.launch({
      executablePath: CHROMIUM,
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    context.after(async () => {
      await browser.close();
      await server.close();
    });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: "networkidle" });
    await page.waitForFunction(
      () => document.querySelector("#color-trackpad")?.dataset.colorcheckerRingCount === "18",
    );
    assert.equal(await page.locator('[data-image-zoom="2"]').getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator('[data-image-zoom="1"]').getAttribute("aria-pressed"), "false");
    assert.equal(await page.locator("#image-options").textContent(), "Options");
    assert.equal(await page.locator("#image-options-heading").textContent(), "Options");
    assert.equal(await page.locator("#image-options").isDisabled(), true);
    assert.ok((await page.locator("#image-file-input").getAttribute("accept") ?? "").split(",").includes("image/x-exr"));
    assert.equal(await page.locator("body").evaluate(element => getComputedStyle(element).userSelect), "none");
    assert.equal(await page.locator("#j-number").evaluate(element => getComputedStyle(element).userSelect), "text");
    assert.equal(await page.locator("#color-trackpad").getAttribute("data-indicator-patch-count"), "18");
    assert.ok(await page.locator("#gamut-indicators").evaluate(canvas => {
      const context = canvas.getContext("2d");
      if (!context) return false;
      const alpha = context.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 3; i < alpha.length; i += 4) if (alpha[i] !== 0) return true;
      return false;
    }), "ColorChecker indicators are painted before any picker movement");
    const desktopLayout = await page.evaluate(() => {
      const trackwheel = document.querySelector("#j-trackwheel").getBoundingClientRect();
      const slice = document.querySelector("#color-trackpad").getBoundingClientRect();
      return {
        scroll: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
        viewport: [innerWidth, innerHeight],
        trackwheelRight: trackwheel.right,
        sliceLeft: slice.left,
      };
    });
    assert.equal(desktopLayout.scroll[0], desktopLayout.viewport[0]);
    assert.ok(desktopLayout.scroll[1] >= desktopLayout.viewport[1]);
    assert.ok(desktopLayout.trackwheelRight <= desktopLayout.sliceLeft, JSON.stringify(desktopLayout));
    const slice = page.locator("#gamut-slice");
    const box = await slice.boundingBox();
    assert.ok(box);
    await slice.dispatchEvent("pointerdown", {
      pointerId: 90,
      pointerType: "mouse",
      button: 0,
      clientX: box.x + box.width * 0.2,
      clientY: box.y + box.height * 0.2,
    });
    await page.waitForFunction(
      () => document.querySelector(".color-trackpad")?.dataset.trackpadTracking === "active",
    );
    await page.evaluate(() => {
      document.dispatchEvent(
        new PointerEvent("pointermove", {
          pointerId: 90,
          pointerType: "mouse",
          clientX: 9999,
          clientY: 9999,
        }),
      );
    });
    await page.waitForFunction(
      () => Number(document.querySelector("#color-trackpad")?.dataset.displayX) > 0.99 &&
        Number(document.querySelector("#color-trackpad")?.dataset.displayY) < 0.01,
    );
    const live = await page.evaluate(() => ({
      state: document.querySelector(".color-trackpad")?.dataset.trackpadTracking,
      x: Number(document.querySelector("#color-trackpad")?.dataset.displayX),
      y: Number(document.querySelector("#color-trackpad")?.dataset.displayY),
    }));
    assert.equal(live.state, "active");
    assert.ok(live.x > 0.99 && live.y < 0.01);
    await page.evaluate(() => {
      document.dispatchEvent(
        new PointerEvent("pointerdown", {
          pointerId: 91,
          pointerType: "mouse",
          button: 0,
          clientX: 500,
          clientY: 500,
        }),
      );
    });
    await page.waitForFunction(
      () => document.querySelector(".color-trackpad")?.dataset.trackpadTracking === "idle",
    );
    const committed = await page.evaluate(() => ({
      state: document.querySelector(".color-trackpad")?.dataset.trackpadTracking,
      x: Number(document.querySelector("#color-trackpad")?.dataset.displayX),
      y: Number(document.querySelector("#color-trackpad")?.dataset.displayY),
    }));
    await page.evaluate(() => {
      document.dispatchEvent(
        new PointerEvent("pointermove", {
          pointerId: 90,
          pointerType: "mouse",
          clientX: 100,
          clientY: 100,
        }),
      );
    });
    await page.waitForTimeout(100);
    assert.deepEqual(
      await page.evaluate(() => ({
        state: document.querySelector(".color-trackpad")?.dataset.trackpadTracking,
        x: Number(document.querySelector("#color-trackpad")?.dataset.displayX),
        y: Number(document.querySelector("#color-trackpad")?.dataset.displayY),
      })),
      committed,
    );
  },
);

test(
  "narrow DPR-3 layout fits the 360x645 viewport without scrolling",
  { timeout: 60_000 },
  async (context) => {
    const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
    await server.listen();
    const address = server.httpServer?.address();
    assert.ok(address && typeof address !== "string");
    const browser = await chromium.launch({
      executablePath: CHROMIUM,
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    context.after(async () => {
      await browser.close();
      await server.close();
    });
    const page = await browser.newPage({ viewport: { width: 360, height: 645 }, deviceScaleFactor: 3 });
    await page.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: "networkidle" });
    await page.waitForFunction(
      () => document.querySelector("#color-trackpad")?.dataset.colorcheckerRingCount === "18",
    );
    const metrics = await page.evaluate(() => ({
      dpr: devicePixelRatio,
      documentWidth: document.documentElement.scrollWidth,
      documentHeight: document.documentElement.scrollHeight,
      viewportWidth: innerWidth,
      viewportHeight: innerHeight,
      shellBottom: document.querySelector(".app-shell").getBoundingClientRect().bottom,
      layerBounds: ["#gamut-checkerboard", "#gamut-slice", "#gamut-indicators"].map(selector => {
        const rect = document.querySelector(selector).getBoundingClientRect();
        return [rect.left, rect.top, rect.width, rect.height];
      }),
      canvasBacking: ["#gamut-checkerboard", "#gamut-indicators"].map(selector => {
        const canvas = document.querySelector(selector);
        return [canvas.width, canvas.height];
      }),
      trackwheel: (() => { const r = document.querySelector("#j-trackwheel").getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; })(),
      slice: (() => { const r = document.querySelector("#color-trackpad").getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; })(),
      required: ["#gamut-slice", "#preview", "#linear-value", "#view-menu", "#j-trackwheel", "#background-stick", ".app-footer"].every((selector) => !!document.querySelector(selector)),
      controlsNamed: ["#color-trackpad", "#j-trackwheel"].every((selector) => !!document.querySelector(selector)),
    }));
    assert.equal(metrics.dpr, 3);
    assert.equal(metrics.documentWidth, metrics.viewportWidth);
    assert.equal(metrics.documentHeight, metrics.viewportHeight);
    assert.ok(metrics.shellBottom <= metrics.viewportHeight + 1, JSON.stringify(metrics));
    assert.deepEqual(metrics.layerBounds[1], metrics.layerBounds[0]);
    assert.deepEqual(metrics.layerBounds[2], metrics.layerBounds[0]);
    assert.deepEqual(metrics.canvasBacking, [[512, 512], [512, 512]]);
    assert.equal(metrics.required, true);
    assert.equal(metrics.controlsNamed, true);
    assert.ok(metrics.trackwheel[1] <= metrics.slice[0], JSON.stringify(metrics));

    const slice = page.locator("#gamut-slice");
    const sliceBox = await slice.boundingBox();
    const point = { pointerId: 81, pointerType: "mouse", button: 0, clientX: sliceBox.x + sliceBox.width / 2, clientY: sliceBox.y + sliceBox.height / 2 };
    await slice.dispatchEvent("pointerdown", point);
    assert.equal(await page.locator("#color-trackpad").getAttribute("data-trackpad-tracking"), "active");
    await slice.dispatchEvent("pointerdown", point);
    assert.equal(await page.locator("#color-trackpad").getAttribute("data-trackpad-tracking"), "idle");
  },
);


async function openPicker(context, options = {}) {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
  await server.listen();
  const browser = await chromium.launch({
    executablePath: CHROMIUM, headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  context.after(async () => { await browser.close(); await server.close(); });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, ...options });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.querySelector("#preview-image")?.getAttribute("src")?.startsWith("blob:") && document.querySelector("#gamut-slice")?.getAttribute("src")?.startsWith("blob:") && document.querySelector("#gamut-slice")?.dataset.renderer && document.querySelector("#color-trackpad")?.dataset.colorcheckerRingCount === "18");
  return { page, errors };
}
async function makeAces2065Exr(page) {
  const bytes = await page.evaluate(async () => {
    const { ScanlineExrWriter } = await import("/src/exr_zip.ts");
    const storage = [];
    const sink = {
      name: "scene.exr",
      size: 0,
      async write(data, offset = this.size) {
        for (let index = 0; index < data.length; index += 1) storage[offset + index] = data[index];
        this.size = Math.max(this.size, offset + data.length);
      },
      async close() {},
    };
    const writer = await ScanlineExrWriter.create(sink, 1, 1, ["B", "G", "R"], "browser-test");
    await writer.writeRow(0, {
      B: new Uint16Array([0x3000]),
      G: new Uint16Array([0x3400]),
      R: new Uint16Array([0x3800]),
    });
    await writer.close();
    const bytes = new Uint8Array(storage);
    const marker = new TextEncoder().encode("chromaticities\0chromaticities\0");
    let markerOffset = -1;
    outer: for (let offset = 0; offset <= bytes.length - marker.length; offset += 1) {
      for (let index = 0; index < marker.length; index += 1) if (bytes[offset + index] !== marker[index]) continue outer;
      markerOffset = offset;
      break;
    }
    if (markerOffset < 0) throw new Error("EXR chromaticities attribute is missing");
    const payload = markerOffset + marker.length + 4;
    const view = new DataView(bytes.buffer);
    [[.7347, .2653], [0, 1], [.0001, -.077], [.32168, .33767]].forEach((pair, index) => {
      view.setFloat32(payload + index * 8, pair[0], true);
      view.setFloat32(payload + index * 8 + 4, pair[1], true);
    });
    return [...bytes];
  });
  return Buffer.from(bytes);
}
async function pickXY(page, x, y) {
  const slice = page.locator("#gamut-slice");
  const box = await slice.boundingBox();
  const event = { pointerId: 90, pointerType: "mouse", button: 0, clientX: box.x + box.width * x, clientY: box.y + box.height * (1 - y) };
  await slice.dispatchEvent("pointerdown", event);
  await slice.dispatchEvent("pointerdown", event);
}
async function setJ(page, j) {
  const trackwheel = page.locator("#j-trackwheel");
  await trackwheel.press("Home");
  for (let i = 0; i < Math.round(j / .01); i++) await trackwheel.press("ArrowUp");
}
async function setJNumber(page, j) {
  await page.locator("#j-number").evaluate((input, value) => {
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, j);
}
async function setCoordinateNumber(page, axis, value) {
  await page.locator(`#${axis}-number`).evaluate((input, next) => {
    input.value = String(next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}
let backgroundPointerSequence = 800;
async function steerBackgroundReal(page, target) {
  const preview = page.locator("#preview");
  const box = await preview.boundingBox();
  assert.ok(box);
  const pointerId = ++backgroundPointerSequence;
  const x = box.x + box.width / 2;
  let y = box.y + box.height / 2;
  await preview.dispatchEvent("pointerdown", { pointerId, pointerType: "touch", button: 0, clientX: x, clientY: y });
  for (let attempt = 0; attempt < 80; attempt++) {
    const real = Number(await page.locator("#background-stick").getAttribute("data-real-value"));
    const difference = target - real;
    if (Math.abs(difference) <= .0015) break;
    const step = Math.abs(difference) > .05 ? 6 : Math.abs(difference) > .015 ? 2 : 1;
    y += Math.sign(difference) * -step;
    await page.waitForTimeout(30);
    await preview.dispatchEvent("pointermove", { pointerId, pointerType: "touch", button: 0, clientX: x, clientY: y });
  }
  await preview.dispatchEvent("pointerup", { pointerId, pointerType: "touch", button: 0, clientX: x, clientY: y });
  return Number(await page.locator("#background-stick").getAttribute("data-real-value"));
}
async function chooseView(page, view) {
  await page.locator("#preview").click();
  await page.locator(`#view-menu [data-view="${view}"]`).click();
  await page.waitForFunction(view => document.querySelector("#preview").dataset.view === String(view), view);
}
async function settledImage(page) {
  await page.waitForFunction(() => {
    const frame = document.querySelector("#color-trackpad");
    const imageCode = JSON.parse(document.querySelector("#preview").dataset.imageCode ?? "[]");
    const background = Number.parseFloat(document.querySelector("#background-stick").style.bottom) / 100;
    return imageCode.length === 4 && Math.abs(imageCode[0] - Number(frame.dataset.displayJ)) < 1e-6 && Math.abs(imageCode[1] - Number(frame.dataset.displayX)) < 1e-6 && Math.abs(imageCode[2] - Number(frame.dataset.displayY)) < 1e-6 && Math.abs(imageCode[3] - background) < 1e-3;
  });
}
async function currentPng(page) {
  return readPng(await page.evaluate(async () => [...new Uint8Array(await (await fetch(document.querySelector("#preview-image").src)).arrayBuffer())]));
}
async function currentSlicePng(page) {
  return readPng(await page.evaluate(async () => [...new Uint8Array(await (await fetch(document.querySelector("#gamut-slice").src)).arrayBuffer())]));
}
async function elementPng(page, selector) {
  return readPng(await page.evaluate(async selector => [...new Uint8Array(await (await fetch(document.querySelector(selector).src)).arrayBuffer())], selector));
}

test("gamut viewport keeps fixed canvas layers around an RGBA slice PNG", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  const layers = await page.evaluate(() => {
    const selectors = ["#gamut-checkerboard", "#gamut-slice", "#gamut-colorchecker", "#gamut-indicators"];
    const boxes = selectors.map(selector => {
      const element = document.querySelector(selector);
      const rect = element.getBoundingClientRect();
      return { selector, tag: element.tagName, width: rect.width, height: rect.height, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
    });
    const checker = document.querySelector("#gamut-checkerboard");
      const overlay = document.querySelector("#gamut-indicators");
      const dots = document.querySelector("#gamut-colorchecker");
    const checkerPixels = checker.getContext("2d").getImageData(0, 0, checker.width, checker.height).data;
    const overlayPixels = overlay.getContext("2d").getImageData(0, 0, overlay.width, overlay.height).data;
    return {
      boxes,
      backing: selectors.map(selector => {
        const element = document.querySelector(selector);
        return [selector, element instanceof HTMLImageElement ? element.naturalWidth : element.width, element instanceof HTMLImageElement ? element.naturalHeight : element.height];
      }),
      checkerInk: Array.from(checkerPixels).some((value, index) => index % 4 !== 3 && value !== 0),
      overlayInk: Array.from(overlayPixels).some((value, index) => index % 4 === 3 && value !== 0),
      dotSource: dots.getAttribute("src"),
      order: Array.from(document.querySelector(".color-trackpad").children).map(element => element.id),
    };
  });
  assert.deepEqual(layers.order.slice(0, 4), ["gamut-checkerboard", "gamut-slice", "gamut-colorchecker", "gamut-indicators"]);
  assert.deepEqual(layers.backing, [["#gamut-checkerboard", 512, 512], ["#gamut-slice", 512, 512], ["#gamut-colorchecker", 1024, 1024], ["#gamut-indicators", 512, 512]]);
  for (const box of layers.boxes) {
    assert.ok(Math.abs(box.width - layers.boxes[0].width) < 0.01, `${box.selector} width`);
    assert.ok(Math.abs(box.height - layers.boxes[0].height) < 0.01, `${box.selector} height`);
    assert.ok(Math.abs(box.left - layers.boxes[0].left) < 0.01, `${box.selector} left`);
    assert.ok(Math.abs(box.top - layers.boxes[0].top) < 0.01, `${box.selector} top`);
  }
  assert.equal(layers.checkerInk, true);
  assert.equal(layers.overlayInk, true);
  assert.ok(layers.dotSource?.startsWith("blob:"));
  const dots = await elementPng(page, "#gamut-colorchecker");
  assert.deepEqual([dots.width, dots.height, dots.colorType], [1024, 1024, 6]);
  const firstPatch = await page.evaluate(async () => {
    const wasm = await import("/src/wasm/pkg/modcam16_color_core.js");
    await wasm.default();
    return [...wasm.picker_colorchecker().slice(0, 3)];
  });
  assert.ok(dots.alpha(Math.round(firstPatch[1] * 1023), Math.round((1 - firstPatch[2]) * 1023)) > 0, "dot layer should contain visible coverage");

  const slice = await currentSlicePng(page);
  assert.equal(slice.colorType, 6);
  assert.equal(slice.width, 512);
  assert.equal(slice.height, 512);
  const alphaSamples = [];
  for (let y = 0; y < slice.height; y += 32) {
    for (let x = 0; x < slice.width; x += 32) alphaSamples.push(slice.alpha(x, y));
  }
  assert.ok(alphaSamples.some(alpha => alpha === 0), "invalid slice samples are transparent");
  assert.ok(alphaSamples.some(alpha => alpha > 0), "valid slice samples are opaque");

  const before = await page.locator("#gamut-slice").getAttribute("src");
  await pickXY(page, .23, .71);
  await page.waitForFunction(() => Number(document.querySelector("#color-trackpad").dataset.displayX) !== .38);
  assert.equal(await page.locator("#gamut-slice").getAttribute("src"), before, "X/Y only repaints the overlay");

  const renderer = await page.locator("#gamut-slice").getAttribute("data-renderer");
  const trackwheel = page.locator("#j-trackwheel"), trackwheelBox = await trackwheel.boundingBox();
  const centerX = trackwheelBox.x + trackwheelBox.width / 2, centerY = trackwheelBox.y + trackwheelBox.height / 2;
  await page.evaluate(({ centerX, centerY }) => {
    const trackwheel = document.querySelector("#j-trackwheel");
    trackwheel.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 71, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY }));
    window.__rapidJRunning = true;
    let tick = 0;
    const timer = setInterval(() => {
      tick++;
      trackwheel.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 71, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY + Math.sin(tick * .55) * 9 }));
      if (tick >= 180) {
        clearInterval(timer);
        window.__rapidJRunning = false;
      }
    }, 10);
  }, { centerX, centerY });
  await page.waitForFunction(() => !window.__rapidJRunning);
  await trackwheel.dispatchEvent("pointerup", { pointerId: 71, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 20 });
  await page.waitForFunction(src => document.querySelector("#gamut-slice").getAttribute("src") !== src, before);
  const transientSource = await page.locator("#gamut-slice").getAttribute("src");
  const transient = await currentSlicePng(page);
  assert.equal(transient.width, renderer === "webgpu" ? 512 : 64);
  assert.equal(transient.height, renderer === "webgpu" ? 512 : 64);
  assert.deepEqual(await page.evaluate(() => [
    document.querySelector("#gamut-checkerboard").width,
    document.querySelector("#gamut-checkerboard").height,
    document.querySelector("#gamut-indicators").width,
    document.querySelector("#gamut-indicators").height,
  ]), [512, 512, 512, 512]);
  if (renderer === "wasm") {
    await page.waitForFunction(() => {
      const image = document.querySelector("#gamut-slice");
      const code = JSON.parse(image.dataset.imageCode ?? "[]");
      return image.naturalWidth === 512 && Math.abs(code[0] - Number(document.querySelector("#color-trackpad").dataset.displayJ)) < 1e-6;
    });
    assert.equal((await currentSlicePng(page)).width, 512);
  }
  assert.deepEqual(errors, []);
});

test("trackwheel, color trackpad gestures, and canonical snap display/calculation stay synchronized", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  assert.equal(await page.locator(".j-trackwheel-ticks span").count(), 11);
  assert.deepEqual(await page.locator("#view-menu [data-view]").evaluateAll(buttons => buttons.map(b => [b.dataset.view, b.disabled])), [["1", false], ["4", false], ["2", false], ["0", false]]);
  assert.equal(await page.locator("#background-stick").getAttribute("aria-hidden"), "true");
  assert.equal(await page.locator("#j-label").textContent(), "J’=");
  assert.equal(await page.locator("#full-rec2020-toggle").textContent(), "Rec.2020 (P3-D65 Limited)");
  assert.equal(await page.locator("#full-rec2020-toggle").evaluate(element => element.parentElement?.parentElement?.id), "color-trackpad");
  assert.equal(await page.locator("#x-number").evaluate(element => element.parentElement?.parentElement?.id), "color-trackpad");
  assert.equal(await page.locator("#y-number").evaluate(element => element.parentElement?.parentElement?.id), "color-trackpad");
  const sliceOptions = await page.locator(".slice-options").boundingBox();
  const plotBox = await page.locator("#color-trackpad").boundingBox();
  assert.ok(sliceOptions && plotBox);
  assert.ok(sliceOptions.x >= plotBox.x && sliceOptions.y >= plotBox.y);
  assert.ok(sliceOptions.x + sliceOptions.width <= plotBox.x + plotBox.width * .6, "controls stay away from the slice's right/R=1 region");
  const initialGeometry = await page.evaluate(() => {
    const rect = selector => {
      const value = document.querySelector(selector).getBoundingClientRect();
      return { left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height };
    };
    return {
      visuals: rect(".visuals"), stage: rect(".gamut-stage"),
      control: rect(".j-trackwheel-control"), trackwheel: rect("#j-trackwheel"),
      ruler: rect(".j-ruler"), label: rect("#j-label"), number: rect("#j-number"), slice: rect("#color-trackpad"),
      coordinates: rect(".slice-coordinate-inputs"), xInput: rect("#x-number"),
      previewPanel: rect(".preview-panel"), preview: rect(".preview"), details: rect(".preview-details"),
      name: rect("#color-name"),
      nameVisibility: getComputedStyle(document.querySelector("#color-name")).visibility,
    };
  });
  assert.ok(Math.abs(initialGeometry.stage.left - initialGeometry.visuals.left) < .01);
  assert.ok(Math.abs(initialGeometry.stage.right - initialGeometry.visuals.right) < .01);
  assert.ok(Math.abs(initialGeometry.slice.right - initialGeometry.stage.right) < .01);
  assert.ok(initialGeometry.previewPanel.top >= initialGeometry.stage.bottom - .01);
  assert.ok(Math.abs(initialGeometry.control.top - initialGeometry.slice.top) < .01);
  assert.ok(Math.abs(initialGeometry.control.bottom - initialGeometry.slice.bottom) < .01);
  assert.ok(initialGeometry.trackwheel.right <= initialGeometry.ruler.left);
  assert.ok(initialGeometry.ruler.right <= initialGeometry.slice.left);
  assert.ok(initialGeometry.label.right <= initialGeometry.number.left);
  assert.ok(Math.abs((initialGeometry.label.top + initialGeometry.label.bottom) / 2 -
    (initialGeometry.number.top + initialGeometry.number.bottom) / 2) < .01);
  assert.ok(initialGeometry.number.bottom <= initialGeometry.control.bottom + .01);
  assert.ok(initialGeometry.coordinates.left >= initialGeometry.slice.left);
  assert.ok(initialGeometry.coordinates.bottom <= initialGeometry.slice.bottom);
  assert.ok(initialGeometry.coordinates.left - initialGeometry.slice.left < 12);
  assert.ok(initialGeometry.slice.bottom - initialGeometry.coordinates.bottom < 12);
  assert.deepEqual(await page.locator(".slice-coordinate-inputs").evaluate(element => {
    const style = getComputedStyle(element);
    return [style.backgroundColor, style.borderTopWidth, style.paddingTop];
  }), ["rgba(0, 0, 0, 0)", "0px", "0px"]);
  assert.ok(Math.abs(initialGeometry.preview.width - initialGeometry.preview.height) < .01);
  assert.ok(Math.abs(initialGeometry.preview.height - initialGeometry.details.height) < .01);
  assert.ok(initialGeometry.name.height >= 14);
  assert.equal(initialGeometry.nameVisibility, "hidden");
  assert.ok(Math.abs(initialGeometry.name.left - initialGeometry.coordinates.left) < .01);
  assert.ok(initialGeometry.name.bottom <= initialGeometry.xInput.top + .01);

  const patch = await page.evaluate(async () => {
    const wasm = await import("/src/wasm/pkg/modcam16_color_core.js");
    await wasm.default();
    return [...wasm.picker_colorchecker().slice(70, 73)];
  });
  await page.locator("#x-number").dispatchEvent("pointerdown", { pointerId: 310, pointerType: "mouse", button: 0 });
  assert.equal(await page.locator("#color-trackpad").getAttribute("data-trackpad-tracking"), "idle");
  await setCoordinateNumber(page, "x", patch[1] + .002);
  await setCoordinateNumber(page, "y", patch[2] + .002);
  await settledImage(page);
  const numericCoordinates = await page.locator("#color-trackpad").evaluate(frame => ({ ...frame.dataset }));
  assert.equal(numericCoordinates.snapTarget, "patch:7", "numeric edits may select the nearby target ring");
  assert.ok(Math.abs(Number(numericCoordinates.displayX) - (patch[1] + .002)) < 1e-6);
  assert.ok(Math.abs(Number(numericCoordinates.displayY) - (patch[2] + .002)) < 1e-6);
  assert.equal(numericCoordinates.realX, numericCoordinates.displayX);
  assert.equal(numericCoordinates.realY, numericCoordinates.displayY);
  await pickXY(page, patch[1] + .002, patch[2] + .002);
  await setJ(page, patch[0]);
  await settledImage(page);
  const snapped = await page.locator("#color-trackpad").evaluate(frame => ({ ...frame.dataset }));
  assert.equal(snapped.snapTarget, "patch:7");
  assert.equal(snapped.jSnapTarget, "patch");
  assert.notEqual(Number(snapped.displayJ), patch[0], "keyboard J' edits do not project a snap");
  assert.ok(Math.abs(Number(snapped.displayX) - patch[1]) < 1e-6);
  assert.ok(Math.abs(Number(snapped.displayY) - patch[2]) < 1e-6);
  assert.notEqual(snapped.realX, snapped.displayX);
  assert.equal(await page.textContent("#color-name"), "Purplish Blue");
  assert.equal(await page.locator("#color-name").evaluate(element => getComputedStyle(element).visibility), "visible");
  assert.equal(await page.locator("#j-stick").isVisible(), true);
  assert.notEqual(await page.locator("#j-trackwheel").getAttribute("aria-valuenow"), String(patch[0]));
  const trackwheelBox = await page.locator("#j-trackwheel").boundingBox();
  assert.ok(trackwheelBox);
  await page.locator("#j-trackwheel").dispatchEvent("pointerdown", {
    pointerId: 71, pointerType: "touch", clientX: trackwheelBox.x + trackwheelBox.width / 2,
    clientY: trackwheelBox.y + trackwheelBox.height / 2,
  });
  await page.locator("#j-trackwheel").dispatchEvent("pointermove", {
    pointerId: 71, pointerType: "touch", clientX: trackwheelBox.x + trackwheelBox.width / 2,
    clientY: trackwheelBox.y + trackwheelBox.height / 2 - 1,
  });
  await page.locator("#j-trackwheel").dispatchEvent("pointerup", {
    pointerId: 71, pointerType: "touch", clientX: trackwheelBox.x + trackwheelBox.width / 2,
    clientY: trackwheelBox.y + trackwheelBox.height / 2 - 1,
  });
  await settledImage(page);
  const trackwheelSnapped = await page.locator("#color-trackpad").evaluate(frame => ({ ...frame.dataset }));
  assert.equal(trackwheelSnapped.jSnapTarget, "patch");
  assert.ok(Math.abs(Number(trackwheelSnapped.displayJ) - patch[0]) < 1e-6);
  const scene = await page.textContent("#linear-value");
  assert.equal(await page.locator("#gamut-slice").evaluate(element => element.tagName), "IMG");
  let sliceSource = await page.locator("#gamut-slice").getAttribute("src");
  for (const view of [4, 2, 0, 1]) {
    await chooseView(page, view);
    assert.deepEqual(await page.locator("#color-trackpad").evaluate(frame => ({ ...frame.dataset })), trackwheelSnapped);
    assert.equal(await page.textContent("#linear-value"), scene);
    await page.waitForFunction(expected => document.querySelector("#gamut-slice").dataset.view === String(expected), view);
    const nextSource = await page.locator("#gamut-slice").getAttribute("src");
    assert.notEqual(nextSource, sliceSource);
    sliceSource = nextSource;
    assert.equal((await currentSlicePng(page)).depth, view === 0 || view === 2 ? 16 : 8);
    assert.equal((await currentPng(page)).depth, view === 0 || view === 2 ? 16 : 8);
    assert.equal(await page.locator(".visuals").evaluate(element => element.scrollLeft), 0);
  }

  // Snapping is a projection: leaving its band updates both numbers and ACEScg.
  const frame = page.locator("#color-trackpad");
  const frameBox = await frame.boundingBox();
  const centerX = frameBox.x + frameBox.width / 2;
  const centerY = frameBox.y + frameBox.height / 2;
  await frame.dispatchEvent("pointerdown", { pointerId: 7, pointerType: "touch", clientX: centerX, clientY: centerY });
  await frame.dispatchEvent("pointermove", { pointerId: 7, pointerType: "touch", clientX: centerX + frameBox.width * .08, clientY: centerY });
  await frame.dispatchEvent("pointerup", { pointerId: 7, pointerType: "touch", clientX: centerX + frameBox.width * .08, clientY: centerY });
  await settledImage(page);
  assert.notEqual(await page.textContent("#linear-value"), scene);
  const escaped = await frame.evaluate(element => ({ ...element.dataset }));
  assert.equal(escaped.realX, escaped.displayX);
  assert.ok(Number(escaped.displayX) > patch[1] + .005);

  await pickXY(page, .5, .5);
  await settledImage(page);
  assert.match(await frame.getAttribute("aria-label"), /x’ 0\.500000, y’ 0\.500000/);
  assert.equal(await page.locator("#j-stick").isVisible(), false);
  const referenceJ = await page.locator("#j-reference-tick").evaluate(tick => Number.parseFloat(tick.style.bottom) / 100);
  await setJNumber(page, referenceJ + .003);
  await settledImage(page);
  const numericJ = Number(await page.locator("#j-trackwheel").getAttribute("aria-valuenow"));
  assert.ok(Math.abs(numericJ - referenceJ) > 1e-4, "numeric J' remains unsnapped near the reference marker");
  await page.locator("#j-trackwheel").press("ArrowUp");
  await settledImage(page);
  const releasedJ = await frame.evaluate(element => ({ real: element.dataset.realJ, display: element.dataset.displayJ }));
  assert.equal(releasedJ.real, releasedJ.display);

  // Neutral foreground and its snapped surround must be the same PNG samples.
  // The preview drag controls Background J'. Keep the foreground at the
  // default surround here so the view-switch comparison remains neutral.
  await setJ(page, .15);
  await settledImage(page);
  for (const view of [1, 4, 2, 0]) {
    await chooseView(page, view);
    // Vertical preview dragging controls Background J'. The default surround
    // is intentionally independent of foreground J'.
    await settledImage(page);
    const png = await currentPng(page);
    assert.deepEqual(png.pixel(0, 0), png.pixel(128, 128));
  }

  const beforeTouch = Number(await frame.getAttribute("data-real-x"));
  await frame.dispatchEvent("pointerdown", { pointerId: 8, pointerType: "touch", clientX: centerX, clientY: centerY });
  assert.equal(Number(await frame.getAttribute("data-real-x")), beforeTouch, "touch contact does not jump");
  await frame.dispatchEvent("pointermove", { pointerId: 8, pointerType: "touch", clientX: centerX + frameBox.width / 4, clientY: centerY });
  assert.ok(Number(await frame.getAttribute("data-real-x")) > beforeTouch + .07, "fast slice movement accelerates beyond quarter speed");
  await frame.dispatchEvent("pointerup", { pointerId: 8, pointerType: "touch", clientX: centerX + frameBox.width / 4, clientY: centerY });
  assert.equal(await frame.getAttribute("data-trackpad-tracking"), "idle");
  assert.deepEqual(errors, []);
});

test("J trackwheel is direct, persistent, clamped, and escapes a snap during the gesture", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  assert.equal(await page.locator(".j-ruler").evaluate(element => getComputedStyle(element).cursor), "ns-resize");
  assert.deepEqual(await page.locator("#background-stick polygon").evaluate(element => ({
    points: element.getAttribute("points"), fill: element.getAttribute("fill"),
    stroke: element.getAttribute("stroke"), strokeWidth: element.getAttribute("stroke-width"),
  })), { points: "1.5,1.5 10.5,7 1.5,12.5", fill: "#171a20", stroke: "#fff", strokeWidth: "1" });
  assert.equal(await page.locator("#j-current-indicator polygon").getAttribute("points"), "0,0 8,5 0,10");
  await setJNumber(page, .15);
  const alignedMarkers = await page.evaluate(() => {
    const background = document.querySelector("#background-stick").getBoundingClientRect();
    const foreground = document.querySelector("#j-current-indicator").getBoundingClientRect();
    return {
      background: { right: background.right, centerY: (background.top + background.bottom) / 2 },
      foreground: { right: foreground.right, centerY: (foreground.top + foreground.bottom) / 2 },
    };
  });
  assert.ok(alignedMarkers.background.right - alignedMarkers.foreground.right > .9, "hollow triangle contains the solid apex with a visible gap");
  assert.ok(Math.abs(alignedMarkers.background.centerY - alignedMarkers.foreground.centerY) < .01, "triangle centers align");
  await pickXY(page, .5, .5);
  const trackwheel = page.locator("#j-trackwheel");
  const frame = page.locator("#color-trackpad");
  const box = await trackwheel.boundingBox();
  assert.ok(box);
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  const realJ = () => frame.evaluate(element => Number(element.dataset.realJ));
  const displayJ = () => frame.evaluate(element => Number(element.dataset.displayJ));
  const visualOffset = () => trackwheel.evaluate(element => Number(element.dataset.visualOffset));

  const ruler = page.locator(".j-ruler");
  const rulerBox = await ruler.boundingBox();
  assert.ok(rulerBox);
  await setJNumber(page, .5);
  await ruler.dispatchEvent("pointerdown", { pointerId: 206, pointerType: "touch", button: 0, clientX: rulerBox.x + rulerBox.width / 2, clientY: rulerBox.y + rulerBox.height / 2 });
  await ruler.dispatchEvent("pointermove", { pointerId: 206, pointerType: "touch", button: 0, clientX: rulerBox.x + rulerBox.width / 2, clientY: rulerBox.y + rulerBox.height / 2 - rulerBox.height * .1 });
  assert.ok(await realJ() > .5, "the adjacent J' ruler accepts trackwheel movement");
  await ruler.dispatchEvent("pointerup", { pointerId: 206, pointerType: "touch", button: 0, clientX: rulerBox.x + rulerBox.width / 2, clientY: rulerBox.y + rulerBox.height / 2 - rulerBox.height * .1 });

  await setJNumber(page, .5);
  const startingOffset = await visualOffset();
  await trackwheel.dispatchEvent("pointerdown", { pointerId: 201, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY });
  await trackwheel.dispatchEvent("pointermove", { pointerId: 201, pointerType: "touch", button: 0, clientX: centerX + 100, clientY: centerY - box.height * .2 });
  assert.ok(await realJ() > .55, "fast movement applies acceleration beyond the base quarter-speed delta");
  const fastOffset = await visualOffset();
  assert.ok(Math.abs((fastOffset - startingOffset) + box.height * .2) < .01);
  await trackwheel.dispatchEvent("pointerup", { pointerId: 201, pointerType: "touch", button: 0, clientX: centerX + 100, clientY: centerY - box.height * .2 });
  assert.equal(await visualOffset(), fastOffset, "trackwheel texture stays where it was released");

  await setJNumber(page, .5);
  await trackwheel.dispatchEvent("pointerdown", { pointerId: 202, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY });
  for (let step = 1; step <= 4; step++) {
    await trackwheel.dispatchEvent("pointermove", { pointerId: 202, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - box.height * .05 * step });
  }
  assert.ok(await realJ() > .55, "rapid event samples retain accelerated value movement");
  await trackwheel.dispatchEvent("pointerup", { pointerId: 202, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - box.height * .2 });

  await setJNumber(page, .5);
  const horizontalOffset = await visualOffset();
  await trackwheel.dispatchEvent("pointerdown", { pointerId: 203, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY });
  await trackwheel.dispatchEvent("pointermove", { pointerId: 203, pointerType: "touch", button: 0, clientX: centerX + 500, clientY: centerY });
  assert.equal(await realJ(), .5, "horizontal travel has no J' effect");
  assert.equal(await visualOffset(), horizontalOffset);
  await trackwheel.dispatchEvent("pointerup", { pointerId: 203, pointerType: "touch", button: 0, clientX: centerX + 500, clientY: centerY });

  await setJNumber(page, .99);
  await trackwheel.dispatchEvent("pointerdown", { pointerId: 204, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY });
  await trackwheel.dispatchEvent("pointermove", { pointerId: 204, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - box.height });
  assert.equal(await realJ(), 1);
  const endpointOffset = await visualOffset();
  await trackwheel.dispatchEvent("pointermove", { pointerId: 204, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - box.height * 2 });
  assert.ok(Math.abs(Math.abs((await visualOffset()) - endpointOffset) - box.height) < .01, "texture keeps following the pointer at the endpoint");
  await trackwheel.dispatchEvent("pointermove", { pointerId: 204, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - box.height * 2 + 10 });
  assert.ok(await realJ() < 1, "reversing at an endpoint changes J' immediately");
  await trackwheel.dispatchEvent("pointerup", { pointerId: 204, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - box.height * 2 + 10 });

  const referenceJ = await page.locator("#j-reference-tick").evaluate(tick => Number.parseFloat(tick.style.bottom) / 100);
  await setJNumber(page, referenceJ + .003);
  assert.ok(Math.abs(await realJ() - (referenceJ + .003)) < 1e-6);
  assert.ok(Math.abs(await displayJ() - (referenceJ + .003)) < 1e-6, "numeric J' edits do not snap");
  const snappedOffset = await visualOffset();
  await trackwheel.dispatchEvent("pointerdown", { pointerId: 205, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY });
  await trackwheel.dispatchEvent("pointermove", { pointerId: 205, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 1 });
  assert.ok(Math.abs(await displayJ() - referenceJ) < 1e-6, "trackwheel movement projects the reference snap");
  assert.ok(await realJ() > referenceJ + .003, "the hidden real value continues moving");
  assert.equal(await trackwheel.getAttribute("data-snap-held"), "true", "snap capture freezes the trackwheel gesture");
  const capturedOffset = await visualOffset();
  assert.ok(Math.abs(capturedOffset - snappedOffset + 1) < .01, "trackwheel texture advances through the capture movement");
  const heldDisplay = await displayJ();
  const heldReal = await realJ();
  await trackwheel.dispatchEvent("pointermove", { pointerId: 205, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 1.5 });
  assert.equal(await displayJ(), heldDisplay, "displayed J' remains frozen while snap is held");
  assert.equal(await realJ(), heldReal, "real J' remains frozen until deferred travel is released");
  assert.equal(await trackwheel.getAttribute("data-snap-held"), "true", "small movement remains inside the snap band");
  assert.ok(Math.abs(Number(await trackwheel.getAttribute("data-deferred-delta-y")) + .5) < 1e-6,
    "subsequent pointer travel is accumulated while snapped");
  await trackwheel.dispatchEvent("pointermove", { pointerId: 205, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 8 });
  assert.equal(await trackwheel.getAttribute("data-snap-held"), "false", "continued movement escapes the snap before release");
  assert.ok(Math.abs(Number(await trackwheel.getAttribute("data-deferred-delta-y"))) < 1e-6,
    "deferred travel is cleared when the snap escapes");
  assert.ok(Math.abs((await visualOffset()) - capturedOffset + 7) < .01,
    "escape applies the complete deferred raw trackwheel distance");
  assert.ok(await realJ() > heldReal, "escape applies deferred J' movement immediately");
  const escapedJ = await displayJ();
  assert.ok(Math.abs(escapedJ - referenceJ) > 1e-4, "displayed J' leaves the snapped target during the gesture");
  await trackwheel.dispatchEvent("pointermove", { pointerId: 205, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 9 });
  assert.ok(await displayJ() > escapedJ, "trackwheel movement resumes after snap escape");
  await page.waitForFunction(() => {
    const frame = document.querySelector("#color-trackpad");
    const image = document.querySelector("#gamut-slice");
    if (!frame || !image?.dataset.imageCode) return false;
    const imageJ = Number(JSON.parse(image.dataset.imageCode)[0]);
    return Math.abs(imageJ - Number(frame.dataset.displayJ)) < 1e-6;
  }, undefined, { timeout: 20_000 });
  await trackwheel.dispatchEvent("pointerup", { pointerId: 205, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 9 });
  assert.equal(await trackwheel.getAttribute("data-snap-held"), "false");
  assert.match(await page.locator("#j-number").inputValue(), /^\d\.\d{3}$/);

  await setJNumber(page, referenceJ + .003);
  const fallbackOffset = await visualOffset();
  await trackwheel.dispatchEvent("pointerdown", { pointerId: 206, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY });
  await trackwheel.dispatchEvent("pointermove", { pointerId: 206, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 1 });
  assert.equal(await trackwheel.getAttribute("data-snap-held"), "true");
  const heldReleaseOffset = await visualOffset();
  await trackwheel.dispatchEvent("pointermove", { pointerId: 206, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 1.25 });
  await trackwheel.dispatchEvent("pointerup", { pointerId: 206, pointerType: "touch", button: 0, clientX: centerX, clientY: centerY - 1.25 });
  assert.equal(await trackwheel.getAttribute("data-snap-held"), "false", "release clears a still-held snap");
  assert.equal(await visualOffset(), heldReleaseOffset,
    "release leaves a snap-held trackwheel exactly where it stopped");
  assert.ok(Math.abs(heldReleaseOffset - fallbackOffset + 1) < .01,
    "only pointer travel before snap capture advances the trackwheel texture");
  assert.ok(Math.abs(await realJ() - referenceJ) < 1e-6,
    "release commits hidden real J' to the visible snapped target");
  assert.ok(Math.abs(await displayJ() - referenceJ) < 1e-6,
    "release retains the visible snapped J'");
  assert.match(await page.locator("#j-number").inputValue(), /^\d\.\d{3}$/);

  const beforeResize = { height: box.height, offset: await visualOffset() };
  await page.setViewportSize({ width: 1280, height: 700 });
  const resizedBox = await trackwheel.boundingBox();
  assert.ok(resizedBox);
  await page.waitForFunction(({ height, offset }) => {
    const trackwheel = document.querySelector("#j-trackwheel");
    const actualHeight = trackwheel.getBoundingClientRect().height;
    return actualHeight > 0 && Math.abs(offset / height - Number(trackwheel.dataset.visualOffset) / actualHeight) < 1e-5;
  }, beforeResize);
  assert.ok(Math.abs(beforeResize.offset / beforeResize.height - (await visualOffset()) / resizedBox.height) < 1e-5,
    "trackwheel position is reconstructed for the new trackwheel height");
  assert.deepEqual(errors, []);
});

test("desktop J trackwheel commits a captured drag instead of click-follow tracking", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  const trackwheel = page.locator("#j-trackwheel");
  const box = await trackwheel.boundingBox();
  assert.ok(box);
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  const realJ = () => page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ));
  const visualOffset = () => trackwheel.evaluate(element => Number(element.dataset.visualOffset));
  const before = await realJ();

  await page.mouse.move(centerX, centerY);
  await page.mouse.down();
  assert.equal(await trackwheel.getAttribute("data-tracking"), "drag-active");
  await page.mouse.up();
  assert.equal(await realJ(), before, "pressing and releasing without movement leaves J' unchanged");

  const startingOffset = await visualOffset();
  const outsideX = box.x + box.width + 80;
  const outsideY = centerY - box.height * .2;
  await page.mouse.move(centerX, centerY);
  await page.mouse.down();
  await page.mouse.move(outsideX, outsideY);
  assert.notEqual(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.id, { x: outsideX, y: outsideY }), "j-trackwheel");
  assert.ok(await realJ() > before, "captured movement outside the trackwheel changes J'");
  assert.ok(Math.abs((await visualOffset()) - startingOffset - (outsideY - centerY)) < .01,
    "the trackwheel texture follows raw mouse movement one-to-one");
  const dragged = await realJ();
  await page.mouse.up();
  assert.equal(await trackwheel.getAttribute("data-tracking"), "idle");

  await page.mouse.move(centerX, centerY + box.height * .2);
  assert.equal(await realJ(), dragged, "movement after release cannot change J'");
  assert.deepEqual(errors, []);
});

test("Background J snaps to reference and foreground targets while retaining real motion", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  const referenceJ = await page.locator("#j-reference-tick").evaluate(tick => Number.parseFloat(tick.style.bottom) / 100);
  const preview = page.locator("#preview");
  const previewBox = await preview.boundingBox();
  assert.ok(previewBox);
  const pointerX = previewBox.x + previewBox.width / 2;
  const pointerY = previewBox.y + previewBox.height / 2;
  await preview.dispatchEvent("pointerdown", { pointerId: 910, pointerType: "touch", button: 0, clientX: pointerX, clientY: pointerY });
  await preview.dispatchEvent("pointermove", {
    pointerId: 910, pointerType: "touch", button: 0,
    clientX: pointerX + previewBox.height * .2,
    clientY: pointerY - previewBox.height * .1,
  });
  const acceleratedReal = Number(await page.locator("#background-stick").getAttribute("data-real-value"));
  assert.ok(acceleratedReal - .15 > .025, "Background J uses more than the unaccelerated quarter-height delta");
  await preview.dispatchEvent("pointerup", { pointerId: 910, pointerType: "touch", button: 0, clientX: pointerX, clientY: pointerY - previewBox.height * .1 });

  const realBefore = await steerBackgroundReal(page, referenceJ);
  const background = page.locator("#background-stick");
  assert.ok(Math.abs(realBefore - referenceJ) < .01);
  assert.equal(await background.getAttribute("data-snap-target"), "reference");
  assert.ok(Math.abs(Number.parseFloat(await background.evaluate(element => element.style.bottom)) / 100 - referenceJ) < 1e-6);
  await settledImage(page);
  assert.ok(Math.abs(JSON.parse(await preview.getAttribute("data-image-code"))[3] - referenceJ) < 1e-6,
    "preview calculation uses the snapped Background J value");

  await setJNumber(page, referenceJ);
  assert.equal(await background.getAttribute("data-snap-target"), "none", "foreground changes clear gesture-scoped Background snap metadata");
  assert.ok(Math.abs(Number(await background.getAttribute("data-display-value")) - referenceJ) < 1e-6,
    "foreground changes preserve the displayed Background value");

  const escapedReal = await steerBackgroundReal(page, referenceJ + .025);
  assert.ok(escapedReal > referenceJ + .01);
  assert.equal(await background.getAttribute("data-snap-target"), "none");
  assert.ok(Math.abs(Number.parseFloat(await background.evaluate(element => element.style.bottom)) / 100 - escapedReal) < 1e-6);
  assert.equal(await background.getAttribute("data-real-value"), escapedReal.toFixed(6));

  const foregroundTarget = escapedReal + .006;
  await setJNumber(page, foregroundTarget);
  assert.equal(await background.getAttribute("data-snap-target"), "none");
  assert.ok(Math.abs(Number(await background.getAttribute("data-display-value")) - escapedReal) < 1e-6);
  await steerBackgroundReal(page, foregroundTarget);
  assert.equal(await background.getAttribute("data-snap-target"), "foreground");
  assert.ok(Math.abs(Number(await background.getAttribute("data-display-value")) - foregroundTarget) < 1e-6);
  await setJNumber(page, .2);
  assert.equal(await background.getAttribute("data-snap-target"), "none");
  assert.ok(Math.abs(Number(await background.getAttribute("data-display-value")) - foregroundTarget) < 1e-6,
    "foreground changes preserve the retained Background value");
  assert.deepEqual(errors, []);
});

test("preview retains decoded images, rejects stale work, and shows invalidity during a gesture", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  await page.evaluate(() => {
    const decode = HTMLImageElement.prototype.decode;
    window.__decodes = 0;
    HTMLImageElement.prototype.decode = async function () {
      await decode.call(this);
      if (this.id !== "preview-image") return;
      const delay = window.__delayNextDecode ?? 0;
      window.__delayNextDecode = 0;
      window.__decodes++;
      if (window.__failNextDecode) { window.__failNextDecode = false; throw new Error("test decode failure"); }
      await new Promise(resolve => setTimeout(resolve, delay));
    };
    window.__delayNextDecode = 300;
  });
  const before = await page.locator("#preview-image").getAttribute("src");
  await page.locator("#j-trackwheel").press("ArrowUp");
  await page.waitForFunction(() => window.__decodes >= 1);
  assert.equal(await page.locator("#preview-image").getAttribute("src"), before);
  await page.locator("#j-trackwheel").press("ArrowUp");
  await page.waitForFunction(src => document.querySelector("#preview-image").src !== src, before);
  const latest = await page.locator("#preview-image").getAttribute("src");
  await page.waitForTimeout(350);
  assert.equal(await page.locator("#preview-image").getAttribute("src"), latest);

  await page.evaluate(() => { window.__failNextDecode = true; });
  await page.locator("#j-trackwheel").press("ArrowUp");
  await page.waitForFunction(() => !document.querySelector("#preview-status").hidden);
  assert.equal(await page.locator("#preview-image").getAttribute("src"), latest);
  await page.locator("#j-trackwheel").press("ArrowUp");
  await page.waitForFunction(() => document.querySelector("#preview-status").hidden);

  // Background J' drags are admitted to the same live, coalesced preview
  // pipeline, so rapid movement advances the PNG before release.
  const preview = page.locator("#preview");
  const previewBox = await preview.boundingBox();
  assert.ok(previewBox);
  const beforeBackground = await preview.getAttribute("data-image-generation");
  await preview.dispatchEvent("pointerdown", {
    pointerId: 701, pointerType: "touch", button: 0,
    clientX: previewBox.x + previewBox.width / 2,
    clientY: previewBox.y + previewBox.height / 2,
  });
  await preview.dispatchEvent("pointermove", {
    pointerId: 701, pointerType: "touch", button: 0,
    clientX: previewBox.x + previewBox.width / 2,
    clientY: previewBox.y + previewBox.height * .35,
  });
  await page.waitForFunction(generation => document.querySelector("#preview").dataset.imageGeneration !== generation, beforeBackground);
  await preview.dispatchEvent("pointerup", {
    pointerId: 701, pointerType: "touch", button: 0,
    clientX: previewBox.x + previewBox.width / 2,
    clientY: previewBox.y + previewBox.height * .35,
  });

  const desktopBackgroundBefore = Number.parseFloat(await page.locator("#background-stick").evaluate(element => element.style.bottom));
  const desktopGenerationBefore = await preview.getAttribute("data-image-generation");
  // The full-width desktop square can place the lower preview below the first
  // viewport. Scroll it into the interaction viewport before using real mouse
  // coordinates; synthetic touch events above intentionally remain unchanged.
  await preview.scrollIntoViewIfNeeded();
  const desktopPreviewBox = await preview.boundingBox();
  assert.ok(desktopPreviewBox);
  const previewCenterX = desktopPreviewBox.x + desktopPreviewBox.width / 2;
  const previewCenterY = desktopPreviewBox.y + desktopPreviewBox.height / 2;
  const outsidePreviewX = desktopPreviewBox.x + desktopPreviewBox.width + 40;
  const outsidePreviewY = desktopPreviewBox.y - 30;
  await page.mouse.move(previewCenterX, previewCenterY);
  await page.mouse.down();
  await page.mouse.move(outsidePreviewX, outsidePreviewY);
  assert.notEqual(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.id, { x: outsidePreviewX, y: outsidePreviewY }), "preview");
  await page.waitForFunction(before => Number.parseFloat(document.querySelector("#background-stick").style.bottom) !== before, desktopBackgroundBefore);
  await page.waitForFunction(generation => document.querySelector("#preview").dataset.imageGeneration !== generation, desktopGenerationBefore);
  await page.mouse.up();
  assert.equal(await page.locator("#view-menu").isVisible(), false, "a background drag does not open the view menu");
  const committedBackground = await page.locator("#background-stick").evaluate(element => element.style.bottom);
  await page.mouse.move(previewCenterX, previewCenterY + previewBox.height * .3);
  assert.equal(await page.locator("#background-stick").evaluate(element => element.style.bottom), committedBackground,
    "mouse movement after release cannot change Background J'");
  await page.waitForTimeout(350);
  await page.mouse.click(previewCenterX, previewCenterY);
  assert.equal(await page.locator("#view-menu").isVisible(), true, "a preview click without dragging still opens the view menu");
  await page.keyboard.press("Escape");

  // A captured touch drag has not released, and PNG decode is deliberately slow.
  await page.evaluate(() => { window.__delayNextDecode = 400; });
  const frame = page.locator("#color-trackpad"), box = await frame.boundingBox();
  await frame.dispatchEvent("pointerdown", { pointerId: 99, pointerType: "touch", clientX: box.x, clientY: box.y });
  await frame.dispatchEvent("pointermove", { pointerId: 99, pointerType: "touch", clientX: box.x + box.width * 4, clientY: box.y + box.height * 4 });
  await page.waitForFunction(() => document.querySelector("#preview").classList.contains("preview-unavailable"));
  assert.equal(await page.textContent("#linear-value"), "Unavailable");
  assert.deepEqual(await page.locator("#preview").evaluate(element => ({
    imageVisibility: getComputedStyle(document.querySelector("#preview-image")).visibility,
    background: getComputedStyle(element).backgroundColor,
    immediateCross: getComputedStyle(element, "::before").content,
  })), { imageVisibility: "visible", background: "rgb(23, 26, 32)", immediateCross: "none" });
  await frame.dispatchEvent("pointerup", { pointerId: 99, pointerType: "touch" });
  await page.waitForFunction(() => document.querySelector("#preview").dataset.previewReady === "invalid");
  const unavailable = await currentPng(page);
  assert.deepEqual(unavailable.pixel(128, 100), [0, 0, 0]);
  assert.ok(unavailable.pixel(128, 128)[0] > unavailable.pixel(128, 128)[1]);
  assert.deepEqual(await page.locator("#preview").evaluate(element => ({
    imageVisibility: getComputedStyle(document.querySelector("#preview-image")).visibility,
    immediateCross: getComputedStyle(element, "::before").content,
  })), { imageVisibility: "visible", immediateCross: "none" });
  assert.deepEqual(errors, []);
});

test("mobile view menu and controls stay visible at 360x645 DPR 3", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context, { viewport: { width: 360, height: 645 }, deviceScaleFactor: 3 });
  const geometry = await page.evaluate(() => {
    const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width }; };
    return { slice: rect(".color-trackpad"), preview: rect(".preview-panel"), background: rect("#background-stick"), footer: rect(".app-footer"), trackwheel: rect("#j-trackwheel") };
  });
  assert.ok(geometry.slice.bottom <= geometry.preview.top);
  for (const [name, r] of Object.entries(geometry)) assert.ok(r.top >= 0 && r.bottom <= 645 && r.left >= 0 && r.right <= 360, `${name} visible: ${JSON.stringify(r)}`);

  const previewGeneration = await page.locator("#preview").getAttribute("data-image-generation");
  assert.ok(geometry.trackwheel.right <= geometry.slice.left, JSON.stringify(geometry));
  const frame = page.locator("#color-trackpad"), frameBox = await frame.boundingBox();
  const pointerX = frameBox.x + frameBox.width / 2, pointerY = frameBox.y + frameBox.height / 2;
  await page.evaluate(({ pointerX, pointerY }) => {
    const frame = document.querySelector("#color-trackpad");
    frame.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 72, pointerType: "touch", button: 0, clientX: pointerX, clientY: pointerY }));
    window.__rapidSwipeRunning = true;
    let tick = 0;
    const timer = setInterval(() => {
      tick++;
      frame.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 72, pointerType: "touch", button: 0, clientX: pointerX + Math.sin(tick * .65) * 5, clientY: pointerY + Math.cos(tick * .51) * 4 }));
      if (tick >= 180) {
        clearInterval(timer);
        window.__rapidSwipeRunning = false;
      }
    }, 5);
  }, { pointerX, pointerY });
  await page.waitForFunction(generation => document.querySelector("#preview").dataset.imageGeneration !== generation && window.__rapidSwipeRunning, previewGeneration);
  await page.waitForFunction(() => !window.__rapidSwipeRunning);
  await frame.dispatchEvent("pointerup", { pointerId: 72, pointerType: "touch", button: 0, clientX: pointerX, clientY: pointerY });
  await settledImage(page);

  await page.locator("#preview").click();
  const menu = await page.locator("#view-menu").boundingBox();
  assert.ok(menu.y >= 0 && menu.y + menu.height <= 645 && menu.x >= 0 && menu.x + menu.width <= 360);
  await page.keyboard.press("End");
  assert.equal(await page.evaluate(() => document.activeElement.dataset.view), "0");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector("#preview").dataset.view === "0");
  assert.equal(await page.locator("#view-menu").isVisible(), false);
  assert.equal(await page.evaluate(() => document.activeElement.id), "preview");
  assert.deepEqual(errors, []);
});

test("mobile blank-area swipes turn the J′ trackwheel with the same acceleration", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context, { viewport: { width: 360, height: 645 }, deviceScaleFactor: 3 });
  const app = page.locator(".app-shell");
  const trackwheel = page.locator("#j-trackwheel");
  assert.equal(await page.locator("html").evaluate(element => getComputedStyle(element).touchAction), "none");
  assert.match(await page.locator('meta[name="viewport"]').getAttribute("content"), /user-scalable=no/);
  assert.equal(await page.locator("#gamut-slice").evaluate(element => {
    const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    return element.dispatchEvent(event);
  }), false, "image context menus are suppressed");
  const trackwheelBox = await trackwheel.boundingBox();
  assert.ok(trackwheelBox);
  const before = await page.locator("#color-trackpad").evaluate(element => ({
    real: Number(element.dataset.realJ), display: Number(element.dataset.displayJ),
  }));
  const offsetBefore = Number(await trackwheel.getAttribute("data-visual-offset"));
  const blankX = 2, blankY = 2;
  await app.dispatchEvent("pointerdown", { pointerId: 501, pointerType: "touch", isPrimary: true, button: 0, clientX: blankX, clientY: blankY });
  assert.equal(await trackwheel.getAttribute("data-tracking"), "drag-active");
  assert.equal(await trackwheel.getAttribute("data-tracking-surface"), "page");
  await page.evaluate(({ blankX, blankY }) => document.dispatchEvent(new PointerEvent("pointermove", {
    bubbles: true, pointerId: 501, pointerType: "touch", isPrimary: true, button: 0,
    clientX: blankX, clientY: blankY - 24,
  })), { blankX, blankY });
  const moved = await page.locator("#color-trackpad").evaluate(element => ({
    real: Number(element.dataset.realJ), display: Number(element.dataset.displayJ),
  }));
  const offsetAfter = Number(await trackwheel.getAttribute("data-visual-offset"));
  assert.ok(moved.real > before.real, `${before.real} -> ${moved.real}`);
  assert.ok(moved.display > before.display, `${before.display} -> ${moved.display}`);
  assert.ok(Math.abs(offsetAfter - offsetBefore + 24) < .01, `${offsetBefore} -> ${offsetAfter}`);
  await page.evaluate(({ blankX, blankY }) => document.dispatchEvent(new PointerEvent("pointerup", {
    bubbles: true, pointerId: 501, pointerType: "touch", isPrimary: true, button: 0,
    clientX: blankX, clientY: blankY - 24,
  })), { blankX, blankY });
  assert.equal(await trackwheel.getAttribute("data-tracking"), "idle");
  const released = await page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ));
  await page.evaluate(({ blankX, blankY }) => document.dispatchEvent(new PointerEvent("pointermove", {
    bubbles: true, pointerId: 501, pointerType: "touch", isPrimary: true, button: 0,
    clientX: blankX, clientY: blankY - 48,
  })), { blankX, blankY });
  assert.equal(await page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ)), released);

  const tapBefore = await page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ));
  await app.dispatchEvent("pointerdown", { pointerId: 502, pointerType: "touch", isPrimary: true, button: 0, clientX: blankX, clientY: blankY });
  await app.dispatchEvent("pointerup", { pointerId: 502, pointerType: "touch", isPrimary: true, button: 0, clientX: blankX, clientY: blankY });
  assert.equal(await page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ)), tapBefore);

  await trackwheel.dispatchEvent("pointerdown", { pointerId: 503, pointerType: "touch", button: 0, clientX: trackwheelBox.x + trackwheelBox.width / 2, clientY: trackwheelBox.y + trackwheelBox.height / 2 });
  assert.equal(await trackwheel.getAttribute("data-tracking-surface"), "trackwheel");
  await trackwheel.dispatchEvent("pointerup", { pointerId: 503, pointerType: "touch", button: 0, clientX: trackwheelBox.x + trackwheelBox.width / 2, clientY: trackwheelBox.y + trackwheelBox.height / 2 });
  assert.equal(await trackwheel.getAttribute("data-tracking"), "idle");

  const slice = page.locator("#color-trackpad");
  const sliceBox = await slice.boundingBox();
  assert.ok(sliceBox);
  await slice.dispatchEvent("pointerdown", { pointerId: 504, pointerType: "touch", isPrimary: true, button: 0, clientX: sliceBox.x + sliceBox.width / 2, clientY: sliceBox.y + sliceBox.height / 2 });
  assert.equal(await trackwheel.getAttribute("data-tracking"), "idle", "color trackpad gestures do not start page trackwheel tracking");
  await slice.dispatchEvent("pointerup", { pointerId: 504, pointerType: "touch", isPrimary: true, button: 0, clientX: sliceBox.x + sliceBox.width / 2, clientY: sliceBox.y + sliceBox.height / 2 });
  assert.deepEqual(errors, []);
});

test("mobile whitespace beside the preview readout also turns the J′ trackwheel", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context, { viewport: { width: 360, height: 645 }, deviceScaleFactor: 3 });
  const details = page.locator(".preview-details");
  const point = await details.evaluate(element => {
    const rect = element.getBoundingClientRect();
    for (let y = rect.top + 4; y < rect.bottom - 4; y += 4) {
      for (let x = rect.right - 4; x >= rect.left + 4; x -= 4) {
        const hit = document.elementFromPoint(x, y);
        if (hit === element) return { x, y };
      }
    }
    return null;
  });
  assert.ok(point, "preview-details should expose a blank touch target");
  const trackwheel = page.locator("#j-trackwheel");
  const before = await page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ));
  await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.dispatchEvent(new PointerEvent("pointerdown", {
    bubbles: true, pointerId: 601, pointerType: "touch", isPrimary: true, button: 0, clientX: x, clientY: y,
  })), point);
  assert.equal(await trackwheel.getAttribute("data-tracking-surface"), "page");
  await page.evaluate(({ x, y }) => document.dispatchEvent(new PointerEvent("pointermove", {
    bubbles: true, pointerId: 601, pointerType: "touch", isPrimary: true, button: 0, clientX: x, clientY: y - 24,
  })), point);
  const moved = await page.locator("#color-trackpad").evaluate(element => Number(element.dataset.realJ));
  assert.ok(moved > before, `${before} -> ${moved}`);
  await page.evaluate(({ x, y }) => document.dispatchEvent(new PointerEvent("pointerup", {
    bubbles: true, pointerId: 601, pointerType: "touch", isPrimary: true, button: 0, clientX: x, clientY: y - 24,
  })), point);
  assert.equal(await trackwheel.getAttribute("data-tracking"), "idle");
  assert.deepEqual(errors, []);
});

test("Rec.2020 authoring toggle keeps canonical readouts stable", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  await page.waitForFunction(() => document.querySelector("#preview")?.dataset.view === "0");
  const toggle = page.locator("#full-rec2020-toggle");
  assert.equal(await toggle.textContent(), "Rec.2020 (P3-D65 Limited)");
  assert.equal(await toggle.getAttribute("aria-pressed"), null);
  const canonical = await page.locator("#linear-value").textContent();
  await toggle.click();
  await page.waitForFunction(() => document.querySelector("#full-rec2020-toggle")?.textContent === "Rec.2020");
  assert.equal(await page.locator("#full-rec2020-toggle").getAttribute("aria-pressed"), null);
  assert.equal(await page.locator("#linear-value").textContent(), canonical);
  await toggle.click();
  await page.waitForFunction(() => document.querySelector("#full-rec2020-toggle")?.textContent === "Rec.2020 (P3-D65 Limited)");
  assert.equal(await page.locator("#linear-value").textContent(), canonical);
  assert.equal(await page.locator(".slice-options button").count(), 1);
  assert.deepEqual(errors, []);
});

test("encoded readout toggles between AP1 and sRGB-encoded J′x′y′", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  const label = page.locator("#encoded-label");
  const value = page.locator("#encoded-value");
  await page.waitForFunction(() => document.querySelector("#encoded-value")?.value !== "000000");
  const ap1 = await value.inputValue();
  assert.equal(await label.textContent(), "sRGB Encoded AP1 (→ J′x′y′)");
  assert.equal(await page.locator("#encoded-label-jxy").getAttribute("aria-label"), "Show sRGB Encoded J′x′y′");

  const expectedJxy = await page.locator("#color-trackpad").evaluate(frame => {
    const encode = value => {
      const clamped = Math.max(0, Math.min(1, value));
      const srgb = clamped <= 0.0031308
        ? 12.92 * clamped
        : 1.055 * clamped ** (1 / 2.4) - 0.055;
      return Math.round(srgb * 255).toString(16).padStart(2, "0");
    };
    return [Number(frame.dataset.displayJ), Number(frame.dataset.displayX), Number(frame.dataset.displayY)].map(encode).join("").toUpperCase();
  });
  await page.locator("#encoded-label-jxy").click();
  assert.equal(await label.textContent(), "sRGB Encoded J′x′y′ (→ AP1)");
  assert.equal(await value.inputValue(), expectedJxy);
  assert.equal(await page.locator("#encoded-label-ap1").getAttribute("aria-label"), "Show sRGB Encoded AP1");
  await page.locator("#encoded-label-ap1").click();
  assert.equal(await label.textContent(), "sRGB Encoded AP1 (→ J′x′y′)");
  assert.equal(await value.inputValue(), ap1);
  assert.deepEqual(errors, []);
});

test("sRGB-encoded J′x′y′ Set imports normalized coordinates without snapping", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  await page.locator("#encoded-label-jxy").click();
  const encode = value => {
    const clamped = Math.max(0, Math.min(1, value));
    const srgb = clamped <= 0.0031308
      ? 12.92 * clamped
      : 1.055 * clamped ** (1 / 2.4) - 0.055;
    return Math.round(srgb * 255).toString(16).padStart(2, "0");
  };
  const expected = [0.001, 0.43, 0.77];
  const hex = expected.map(encode).join("").toUpperCase();
  const decode = value => {
    const linear = Math.max(0, Math.min(1, value));
    const srgb = linear <= 0.0031308
      ? 12.92 * linear
      : 1.055 * linear ** (1 / 2.4) - 0.055;
    const encoded = Math.round(srgb * 255) / 255;
    return encoded <= 0.04045
      ? encoded / 12.92
      : ((encoded + 0.055) / 1.055) ** 2.4;
  };
  const decodedExpected = expected.map(decode);
  await page.locator("#encoded-value").fill(hex);
  await page.locator("#set-value").click();
  await page.waitForFunction(({ j, x, y }) => {
    const frame = document.querySelector("#color-trackpad");
    return Math.abs(Number(frame.dataset.realJ) - j) < 0.0001 &&
      Math.abs(Number(frame.dataset.realX) - x) < 0.0001 &&
      Math.abs(Number(frame.dataset.realY) - y) < 0.0001;
  }, { j: decodedExpected[0], x: decodedExpected[1], y: decodedExpected[2] });
  const coordinates = await page.locator("#color-trackpad").evaluate(frame => ({
    realJ: Number(frame.dataset.realJ), realX: Number(frame.dataset.realX), realY: Number(frame.dataset.realY),
    displayJ: Number(frame.dataset.displayJ), displayX: Number(frame.dataset.displayX), displayY: Number(frame.dataset.displayY),
    snapTarget: frame.dataset.snapTarget,
  }));
  assert.ok(Math.abs(coordinates.realJ - decodedExpected[0]) < 0.0001);
  assert.ok(Math.abs(coordinates.realX - decodedExpected[1]) < 0.0001);
  assert.ok(Math.abs(coordinates.realY - decodedExpected[2]) < 0.0001);
  assert.deepEqual([coordinates.displayJ, coordinates.displayX, coordinates.displayY], [coordinates.realJ, coordinates.realX, coordinates.realY]);
  assert.equal(coordinates.snapTarget, "none");
  assert.deepEqual(errors, []);
});

test("touch and pen swipe the slice relatively without a contact jump", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  await pickXY(page, .4, .4);
  const frame = page.locator("#color-trackpad");
  const box = await frame.boundingBox();
  assert.ok(box);
  for (const [index, pointerType] of ["touch", "pen"].entries()) {
    const pointerId = 130 + index;
    const startX = box.x + box.width * .8;
    const startY = box.y + box.height * .8;
    const before = await frame.evaluate(element => [Number(element.dataset.realX), Number(element.dataset.realY)]);
    await frame.dispatchEvent("pointerdown", { pointerId, pointerType, button: 0, clientX: startX, clientY: startY });
    assert.deepEqual(await frame.evaluate(element => [Number(element.dataset.realX), Number(element.dataset.realY)]), before);
    assert.equal(await frame.getAttribute("data-trackpad-tracking"), "touch-active");
    await frame.dispatchEvent("pointermove", {
      pointerId,
      pointerType,
      button: 0,
      clientX: startX + box.width * .1,
      clientY: startY - box.height * .1,
    });
    const after = await frame.evaluate(element => [Number(element.dataset.realX), Number(element.dataset.realY)]);
    assert.ok(after[0] > before[0], `${pointerType} raises x': ${before[0]} -> ${after[0]}`);
    assert.ok(after[1] > before[1], `${pointerType} upward motion raises y': ${before[1]} -> ${after[1]}`);
    await frame.dispatchEvent("pointerup", { pointerId, pointerType, button: 0, clientX: startX, clientY: startY });
    assert.equal(await frame.getAttribute("data-trackpad-tracking"), "idle");
  }
  assert.equal(await page.locator("#color-trackpad").count(), 1);
  assert.deepEqual(errors, []);
});

test("ACES EXR uses direct scene-reference appearance and preserves the unit option", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  const exr = await makeAces2065Exr(page);
  await page.locator("#image-file-input").setInputFiles({ name: "scene.exr", mimeType: "image/x-exr", buffer: exr });
  await page.waitForFunction(() => document.querySelector("#image-panel")?.dataset.sourceMode === "scene-reference-aces" && document.querySelector("#image-viewport")?.dataset.ready === "true");
  await page.locator("#image-options").click();
  const units = page.locator("#image-reference-white-encoded-as-linear-203");
  assert.equal(await page.locator("#image-gamut").inputValue(), "embedded");
  assert.equal(await units.isDisabled(), true);
  assert.equal(await units.isChecked(), false);
  assert.equal(
    await page.locator("#image-units-help").textContent(),
    "Scene-reference ACES data goes directly through the selected view transform; no reference-white scaling or inverse view transform is applied.",
  );

  await page.locator("#image-gamut").selectOption("Rec.2020");
  await page.locator("#image-transfer").selectOption("Linear");
  await page.waitForFunction(() => document.querySelector("#image-panel")?.dataset.sourceMode === "display-linear-xyz-d65" && document.querySelector("#image-viewport")?.dataset.ready === "true");
  assert.equal(await units.isDisabled(), false);
  await units.uncheck();

  await page.locator("#image-gamut").selectOption("ACEScg");
  await page.waitForFunction(() => document.querySelector("#image-panel")?.dataset.sourceMode === "scene-reference-aces" && document.querySelector("#image-viewport")?.dataset.ready === "true");
  assert.equal(await units.isDisabled(), true);
  assert.equal(await units.isChecked(), false, "disabled scene mode preserves the user's stored unit choice");

  await page.locator("#image-gamut").selectOption("Rec.2020");
  await page.waitForFunction(() => document.querySelector("#image-panel")?.dataset.sourceMode === "display-linear-xyz-d65" && document.querySelector("#image-viewport")?.dataset.ready === "true");
  assert.equal(await units.isDisabled(), false);
  assert.equal(await units.isChecked(), false);
  assert.deepEqual(errors, []);
});

test("image locator inspects PNG metadata, prepares manual input, and samples a sharp loupe", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  await page.locator("#image-file-input").setInputFiles({ name: "sample.png", mimeType: "image/png", buffer: png });
  assert.equal(await page.locator('[data-image-zoom="2"]').getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator("#image-options").isDisabled(), false);
  assert.equal(await page.locator("#image-status").textContent(), "Inspecting image…");
  assert.equal(await page.locator("#image-panel").getAttribute("data-ready"), "false");
  const placeholderDuringPreparation = await page.locator("#image-panel").evaluate(panel => {
    const row = panel.querySelector(".image-row");
    const viewport = panel.querySelector("#image-viewport");
    const loupe = panel.querySelector("#image-loupe");
    return {
      state: panel.getAttribute("data-image-state"),
      rowVisible: getComputedStyle(row).display !== "none",
      viewportWidth: viewport.getBoundingClientRect().width,
      viewportHeight: viewport.getBoundingClientRect().height,
      loupeVisible: getComputedStyle(loupe).display !== "none",
    };
  });
  assert.equal(placeholderDuringPreparation.state, "loading");
  assert.equal(placeholderDuringPreparation.rowVisible, true);
  assert.ok(placeholderDuringPreparation.viewportWidth > 0 && placeholderDuringPreparation.viewportHeight > 0);
  assert.equal(placeholderDuringPreparation.loupeVisible, true);
  await page.waitForFunction(() => ["inspected", "true"].includes(document.querySelector("#image-panel")?.dataset.ready ?? ""));
  await page.locator("#image-options").click();
  assert.equal(await page.locator("#image-gamut-field").isVisible(), true);
  assert.equal(await page.locator("#image-transfer-field").isVisible(), true);
  assert.match(await page.locator("#image-interpretation-warning").textContent(), /No embedded color profile/);
  assert.equal(await page.locator('#image-gamut option[value="ACEScg"]').evaluate(option => option.disabled), true,
    "scene-reference ACEScg is unavailable for non-EXR images");
  assert.equal(await page.locator('#image-gamut option[value="ACES2065-1"]').evaluate(option => option.disabled), true,
    "scene-reference ACES2065-1 is unavailable for non-EXR images");
  await page.locator("#image-gamut").selectOption("Rec.2020");
  await page.locator("#image-transfer").selectOption("Linear");
  assert.equal(await page.locator("#image-gamut").inputValue(), "Rec.2020",
    "manual primaries must not be overwritten by no-profile fallback synchronization");
  await page.locator("#image-gamut").selectOption("Rec.709 / sRGB");
  await page.locator("#image-transfer").selectOption("sRGB");
  await page.locator("#image-options-close").click();
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true");
  const initialImageGeometry = await page.evaluate(() => {
    const loupeElement = document.querySelector("#image-loupe");
    loupeElement.style.display = "none";
    const rect = selector => document.querySelector(selector).getBoundingClientRect();
    const rowElement = document.querySelector(".image-row");
    const row = rect(".image-row");
    const loupe = rect("#image-loupe");
    const viewport = rect("#image-viewport");
    const zoom = rect(".image-zoom-controls");
    const firstTrack = Number.parseFloat(getComputedStyle(rowElement).gridTemplateColumns);
    loupeElement.style.removeProperty("display");
    return {
      row: [row.left, row.right, row.width, row.height],
      loupe: [loupe.width, loupe.height],
      viewport: [viewport.left, viewport.width, viewport.height],
      zoom: [zoom.left, zoom.right],
      firstTrack,
      ratio: viewport.width / viewport.height,
    };
  });
  assert.ok(initialImageGeometry.viewport[1] > initialImageGeometry.firstTrack + 100,
    `initial viewport collapsed into loupe column: ${JSON.stringify(initialImageGeometry)}`);
  assert.ok(Math.abs(initialImageGeometry.ratio - 1.5) < 0.02,
    `initial viewport ratio changed: ${JSON.stringify(initialImageGeometry)}`);
  assert.ok(initialImageGeometry.viewport[0] >= initialImageGeometry.row[0] + initialImageGeometry.firstTrack + 7,
    `initial viewport is not in the middle grid column: ${JSON.stringify(initialImageGeometry)}`);
  assert.ok(initialImageGeometry.zoom[0] >= initialImageGeometry.viewport[0] + initialImageGeometry.viewport[1],
    `initial zoom controls overlap viewport: ${JSON.stringify(initialImageGeometry)}`);
  assert.equal(await page.locator("#image-status").textContent(), "1 × 1 native pixels ready.");
  assert.equal(await page.locator("#image-status").evaluate(element => element.parentElement?.className), "image-toolbar-copy");
  const toolbarGeometry = await page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect();
    const toolbar = rect(".image-toolbar");
    const title = rect("#image-heading");
    const status = rect("#image-status");
    const actions = rect(".image-toolbar-actions");
    return {
      titleAboveStatus: title.bottom <= status.top,
      actionsInsideRow: actions.top >= toolbar.top && actions.bottom <= toolbar.bottom,
      statusWhiteSpace: getComputedStyle(document.querySelector("#image-status")).whiteSpace,
    };
  });
  assert.deepEqual(toolbarGeometry, { titleAboveStatus: true, actionsInsideRow: true, statusWhiteSpace: "nowrap" });
  assert.equal(await page.locator("#image-preview").evaluate(image => [image.naturalWidth, image.naturalHeight].join("×")), "1×1");
  assert.deepEqual(await page.evaluate(() => ({
    preview: document.querySelector("#image-preview")?.tagName,
    loupe: document.querySelector("#image-loupe")?.tagName,
    overlay: document.querySelector("#image-overlay")?.tagName,
    overlaySpace: document.querySelector("#image-overlay")?.getContext("2d")?.getContextAttributes().colorSpace,
    indicatorSpace: document.querySelector("#gamut-indicators")?.getContext("2d")?.getContextAttributes().colorSpace,
  })), {
    preview: "IMG", loupe: "IMG", overlay: "CANVAS",
    overlaySpace: "display-p3", indicatorSpace: "display-p3",
  });
  const rangePresentation = await page.evaluate(() => ({
    supported: CSS.supports("dynamic-range-limit", "no-limit"),
    preview: getComputedStyle(document.querySelector("#image-preview")).getPropertyValue("dynamic-range-limit"),
    loupe: getComputedStyle(document.querySelector("#image-loupe")).getPropertyValue("dynamic-range-limit"),
  }));
  if (rangePresentation.supported) assert.deepEqual(rangePresentation, { supported: true, preview: "no-limit", loupe: "no-limit" });
  assert.equal(await page.locator("#image-overlay").evaluate(canvas => getComputedStyle(canvas).objectFit), "fill");
  const viewport = await page.locator("#image-viewport").boundingBox();
  assert.ok(viewport);
  await page.locator("#image-viewport").dispatchEvent("pointerdown", {
    pointerId: 401, pointerType: "mouse", button: 0,
    clientX: viewport.x + viewport.width / 2,
    clientY: viewport.y + viewport.height / 2,
  });
  await page.waitForFunction(() => document.querySelector("#image-stats")?.textContent?.includes("samples available"));
  assert.equal(await page.locator("#image-viewport").getAttribute("data-tracking"), "mouse-active");
  assert.equal(await page.locator("#image-viewport").getAttribute("data-pointer-lock"), "active");
  const crosshairGeometry = await page.evaluate(() => {
    const canvas = document.querySelector("#image-overlay");
    const viewport = document.querySelector("#image-viewport").getBoundingClientRect();
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let minX = canvas.width, minY = canvas.height, maxX = -1, maxY = -1;
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        if (pixels[(y * canvas.width + x) * 4 + 3] === 0) continue;
        minX = Math.min(minX, x); minY = Math.min(minY, y);
        maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
      }
    }
    const width = (maxX - minX + 1) * viewport.width / canvas.width;
    const height = (maxY - minY + 1) * viewport.height / canvas.height;
    return { width, height, ratio: width / height };
  });
  assert.ok(Math.abs(crosshairGeometry.ratio - 1) < 0.12,
    `crosshair is not square in viewport pixels: ${JSON.stringify(crosshairGeometry)}`);
  assert.equal(await page.locator("#image-loupe").evaluate(element => getComputedStyle(element).imageRendering), "pixelated");
  assert.match(await page.locator("#image-loupe").getAttribute("src"), /^blob:/);
  assert.equal(await page.locator("#image-stats").textContent(), "Center 0, 0 · 1/1 samples available");
  assert.doesNotMatch(await page.locator("#image-stats").textContent(), /mean J′/);
  assert.doesNotMatch(await page.locator("#image-stats").textContent(), /unavailable/);
  await page.evaluate(() => document.dispatchEvent(new PointerEvent("pointerdown", { pointerId: 402, pointerType: "mouse", button: 0, clientX: 0, clientY: 0 })));
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.tracking === "idle");
  const locatorBeforeHdr = await page.locator("#image-preview").getAttribute("src");
  const loupeBeforeHdr = await page.locator("#image-loupe").getAttribute("src");
  await chooseView(page, 2);
  await page.waitForFunction(({ locator, loupe }) => {
    const panel = document.querySelector("#image-panel");
    return panel?.dataset.transforming === "false" &&
      document.querySelector("#image-preview")?.getAttribute("src") !== locator &&
      document.querySelector("#image-loupe")?.getAttribute("src") !== loupe;
  }, { locator: locatorBeforeHdr, loupe: loupeBeforeHdr });
  const refreshedImageGeometry = await page.evaluate(() => {
    const viewport = document.querySelector("#image-viewport").getBoundingClientRect();
    return { width: viewport.width, height: viewport.height, ratio: viewport.width / viewport.height };
  });
  assert.ok(Math.abs(refreshedImageGeometry.ratio - 1.5) < 0.02,
    `refreshed viewport ratio changed: ${JSON.stringify(refreshedImageGeometry)}`);
  assert.ok(Math.abs(refreshedImageGeometry.width - initialImageGeometry.viewport[1]) < 1,
    `view refresh changed viewport width: ${JSON.stringify({ initial: initialImageGeometry, refreshed: refreshedImageGeometry })}`);
  assert.deepEqual(await page.evaluate(async urls => Promise.all(urls.map(async url => {
    try { return (await fetch(url)).ok; } catch { return false; }
  })), [locatorBeforeHdr, loupeBeforeHdr]), [false, false], "superseded direct-image blob URLs are revoked");
  for (const selector of ["#image-preview", "#image-loupe"]) {
    const encoded = await elementPng(page, selector);
    assert.equal(encoded.depth, 16);
    assert.deepEqual([...encoded.chunks.get("cICP")], [12, 16, 0, 1]);
  }
  const hdr203WhiteControl = "#image-reference-white-encoded-as-linear-203";
  assert.equal(await page.locator(hdr203WhiteControl).isChecked(), false);
  assert.equal(await page.locator(".image-units-copy > span").textContent(), "Image reference white is encoded as linear 2.03");
  assert.equal(await page.locator("#image-units-help").textContent(), "Use linear 1.0 as reference white.");
  assert.ok(await page.locator(".image-units-field").evaluate(element => {
    const input = element.querySelector("input").getBoundingClientRect();
    const text = element.querySelector("span").getBoundingClientRect();
    return text.left >= input.right;
  }));
  const analysisBeforeUnitChange = await page.locator("#image-stats").textContent();
  const previewBeforeUnitChange = await page.locator("#image-preview").getAttribute("src");
  await page.locator("#image-options").click();
  const busyState = await page.locator(hdr203WhiteControl).evaluate(input => {
    input.checked = true;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    const panel = document.querySelector("#image-panel");
    const banner = document.querySelector("#image-transform-banner");
    return {
      busy: panel?.dataset.transforming,
      bannerHidden: banner?.hasAttribute("hidden"),
      bannerInsideViewport: banner?.parentElement?.id === "image-viewport",
      bannerBottom: getComputedStyle(banner).bottom,
      opacity: getComputedStyle(document.querySelector("#image-preview")).opacity,
    };
  });
  assert.deepEqual(busyState, { busy: "true", bannerHidden: false, bannerInsideViewport: true, bannerBottom: "14px", opacity: "0.38" });
  assert.equal(await page.locator("#image-units-help").textContent(), "Divide by 2.03 before the inverse view transform.");
  await page.waitForFunction(src => document.querySelector("#image-preview")?.getAttribute("src") !== src, previewBeforeUnitChange);
  assert.equal(await page.locator("#image-panel").getAttribute("data-transforming"), "false");
  assert.equal(await page.locator("#image-transform-banner").isHidden(), true);
  assert.match(await page.locator("#image-preview").getAttribute("data-renderer"), /^(webgpu|wasm)$/);
  assert.equal(await page.locator("#image-stats").textContent(), analysisBeforeUnitChange);
  await page.locator("#image-options-close").click();
  await page.locator('[data-image-zoom="2"]').click();
  assert.equal(await page.locator('[data-image-zoom="2"]').getAttribute("aria-pressed"), "true");

  // Replacing the image resets to 2x and keeps the row hidden until the new
  // raster/crosshair state is initialized together.
  const twoByTwoPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGP4z8DAAMIM/4EAAB/uBfsL2WiLAAAAAElFTkSuQmCC", "base64");
  await page.locator("#image-file-input").setInputFiles({ name: "sample-2.png", mimeType: "image/png", buffer: twoByTwoPng });
  assert.equal(await page.locator('[data-image-zoom="2"]').getAttribute("aria-pressed"), "true");
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true");
  const zoomWidth = await page.locator(".image-zoom-controls").evaluate(element => element.getBoundingClientRect().width);
  const buttonWidths = await page.locator(".image-zoom-button").evaluateAll(buttons => buttons.reduce((sum, button) => sum + button.getBoundingClientRect().width, 0));
  assert.ok(zoomWidth <= buttonWidths + 8, `zoom controls expanded to ${zoomWidth}px for ${buttonWidths}px of buttons`);
  assert.ok(await page.locator("#image-overlay").evaluate(canvas => {
    const context = canvas.getContext("2d");
    if (!context) return false;
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] !== 0) return true;
    return false;
  }), "replacement image publishes with a crosshair");
  await page.waitForFunction(() => document.querySelector("#image-stats")?.textContent?.startsWith("Center 1, 0"));
  assert.doesNotMatch(await page.locator("#image-stats").textContent(), /mean J′/);
  assert.deepEqual(errors, []);
});

test("PQ HDR Rec.2020-authoring slice PNG accepts bright neighborhoods", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context);
  await page.locator("#full-rec2020-toggle").click();
  assert.equal(await page.locator("#full-rec2020-toggle").textContent(), "Rec.2020");
  await chooseView(page, 2);
  await setJNumber(page, 0.8);
  await page.waitForFunction(() => Math.abs(JSON.parse(document.querySelector("#gamut-slice")?.dataset.imageCode ?? "[NaN]")[0] - 0.8) < 1e-6);
  const sliceBytes = await page.evaluate(async () => [...new Uint8Array(await (await fetch(document.querySelector("#gamut-slice").src)).arrayBuffer())]);
  await page.locator("#image-file-input").setInputFiles({ name: "hdr-slice.png", mimeType: "image/png", buffer: Buffer.from(sliceBytes) });
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true");
  assert.equal(await page.locator("#image-reference-white-encoded-as-linear-203").isChecked(), true);
  await page.waitForFunction(() => document.querySelector("#image-stats")?.textContent?.includes("samples available"));
  const stats = await page.locator("#image-stats").textContent();
  assert.match(stats ?? "", /29\/29 samples available/);
  assert.doesNotMatch(stats ?? "", /unavailable/);
  assert.deepEqual(errors, []);
});

test("WebGPU image and slice appearance matches the official-table WASM path", { timeout: 60_000 }, async context => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
  await server.listen();
  const address = server.httpServer?.address();
  assert.ok(address && typeof address !== "string");
  const browser = await chromium.launch({
    executablePath: CHROMIUM,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--enable-unsafe-webgpu", "--use-angle=swiftshader"],
  });
  context.after(async () => { await browser.close(); await server.close(); });
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: "networkidle" });
  const parity = await page.evaluate(async () => {
    const wasm = await import("/src/wasm/decomposition_pkg/modcam16_decomposition_wasm.js");
    await wasm.default();
    const core = await import("/src/wasm/pkg/modcam16_color_core.js");
    await core.default();
    const { SliceWebGpuRenderer } = await import("/src/slice_webgpu.ts");
    const renderer = new SliceWebGpuRenderer();
    if (!renderer.available) return null;
    const parameters = core.picker_gpu_parameters();
    const source = new Float32Array([.18, .18, .18, .5, .1, .05, .02, .3, .7, 1.2, .8, .25]);
    const results = [];
    for (const view of [1, 4, 2, 0]) for (const referenceWhiteEncodedAsLinear203 of [false, true]) {
      const slot = view === 0 ? 0 : view === 1 ? 1 : view === 2 ? 2 : 3;
      const gpu = await renderer.renderImage(parameters, slot, "display-linear-xyz-d65", referenceWhiteEncodedAsLinear203, source);
      const cpu = wasm.image_picker_display_rgb_xyz_d65_batch(source, view, referenceWhiteEncodedAsLinear203);
      let maximum = 0;
      for (let index = 0; index < cpu.length; index += 1)
        maximum = Math.max(maximum, Math.abs(gpu[index] - cpu[index]));
      results.push({ view, referenceWhiteEncodedAsLinear203, maximum, length: gpu.length });
    }
    const sceneSource = new Float32Array([.18, .18, .18, .5, -.1, .05, 1.2, .8, .25]);
    const sceneResults = [];
    for (const view of [1, 4, 2, 0]) {
      const slot = view === 0 ? 0 : view === 1 ? 1 : view === 2 ? 2 : 3;
      const gpu = await renderer.renderImage(parameters, slot, "scene-reference-aces", false, sceneSource);
      const cpu = wasm.image_picker_display_rgb_scene_ap0_batch(sceneSource, view);
      let maximum = 0;
      for (let index = 0; index < cpu.length; index += 1)
        maximum = Math.max(maximum, Math.abs(gpu[index] - cpu[index]));
      sceneResults.push({ view, maximum, length: gpu.length });
    }
    const width = 65, height = 65, j = .9999989018855512;
    const gpuSlice = await renderer.render(parameters, 0, j, width, height, true);
    const cpuSlice = core.picker_render_linear_rows_mode(0, j, width, height, 0, height, true);
    let sliceMaximum = 0, sliceRelativeMaximum = 0, alphaMismatches = 0, visible = 0;
    for (let index = 0; index < cpuSlice.length; index += 4) {
      for (let channel = 0; channel < 3; channel++) {
        const difference = Math.abs(gpuSlice[index + channel] - cpuSlice[index + channel]);
        sliceMaximum = Math.max(sliceMaximum, difference);
        sliceRelativeMaximum = Math.max(sliceRelativeMaximum, difference / Math.max(1, Math.abs(cpuSlice[index + channel])));
      }
      if (gpuSlice[index + 3] !== cpuSlice[index + 3]) alphaMismatches++;
      if (cpuSlice[index + 3] > .5 && cpuSlice.slice(index, index + 3).some(value => Math.abs(value) > 1e-9)) visible++;
    }
    return { images: results, sceneImages: sceneResults, slice: { maximum: sliceMaximum, relativeMaximum: sliceRelativeMaximum, alphaMismatches, visible } };
  });
  if (parity === null) return;
  assert.equal(parity.images.length, 8);
  for (const result of parity.images) {
    assert.equal(result.length, 12);
    assert.ok(result.maximum < .002, JSON.stringify(result));
  }
  assert.equal(parity.sceneImages.length, 4);
  for (const result of parity.sceneImages) {
    assert.equal(result.length, 9);
    assert.ok(result.maximum < .002, JSON.stringify(result));
  }
  assert.equal(parity.slice.alphaMismatches, 0);
  assert.ok(parity.slice.visible > 0);
  // The 1000-nit inverse shoulder amplifies f32 equation-order differences;
  // require exact availability and a bounded sub-0.2% display error.
  assert.ok(parity.slice.maximum < .007, JSON.stringify(parity.slice));
  assert.ok(parity.slice.relativeMaximum < .006, JSON.stringify(parity.slice));
});

test("image appearance falls back to the bounded WASM worker pool without WebGPU", { timeout: 60_000 }, async context => {
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
  await server.listen();
  const address = server.httpServer?.address();
  assert.ok(address && typeof address !== "string");
  const browser = await chromium.launch({
    executablePath: CHROMIUM, headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-webgpu"],
  });
  context.after(async () => { await browser.close(); await server.close(); });
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${address.port}/`, { waitUntil: "networkidle" });
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  await page.locator("#image-file-input").setInputFiles({ name: "cpu.png", mimeType: "image/png", buffer: png });
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true");
  assert.equal(await page.locator("#image-preview").getAttribute("data-renderer"), "wasm");
});

test("loaded image locator still fits the 360x645 DPR-3 viewport", { timeout: 60_000 }, async context => {
  const { page, errors } = await openPicker(context, { viewport: { width: 360, height: 645 }, deviceScaleFactor: 3 });
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  await page.locator("#image-file-input").setInputFiles({ name: "mobile.png", mimeType: "image/png", buffer: png });
  await page.waitForFunction(() => ["inspected", "true"].includes(document.querySelector("#image-panel")?.dataset.ready ?? ""));
  await page.locator("#image-options").click();
  await page.locator("#image-gamut").selectOption("Rec.709 / sRGB");
  await page.locator("#image-options-close").click();
  await page.waitForFunction(() => document.querySelector("#image-viewport")?.dataset.ready === "true");
  const layout = await page.evaluate(() => {
    const selectors = [".app-shell", ".visuals", "#image-panel", "#image-viewport", ".app-footer"];
    return {
      scroll: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
      viewport: [innerWidth, innerHeight],
      bounds: selectors.map(selector => {
        const rect = document.querySelector(selector).getBoundingClientRect();
        return [rect.left, rect.top, rect.right, rect.bottom];
      }),
    };
  });
  assert.deepEqual(layout.scroll, layout.viewport);
  for (const [left, top, right, bottom] of layout.bounds) {
    assert.ok(left >= 0 && top >= 0 && right <= 360 && bottom <= 645, JSON.stringify(layout));
  }
  assert.deepEqual(errors, []);
});
