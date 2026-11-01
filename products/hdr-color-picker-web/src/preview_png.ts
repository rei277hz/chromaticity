import { zlibSync } from "fflate";

export const VIEW_IDS = [1, 4, 2, 0] as const;
export type ViewId = (typeof VIEW_IDS)[number];
export const VIEW_NAMES: Record<ViewId, string> = {
  1: "ACES 2.0 - SDR 100 nits (Rec.709)",
  4: "ACES 2.0 - SDR 100 nits (P3 D65)",
  2: "ACES 2.0 - HDR 1000 nits (P3 D65)",
  0: "ACES 2.0 - HDR 1000 nits (Rec.2020)",
};
export const PREVIEW_SIZE = 256;
export const SWATCH_INSET = 35;

const ascii = (value: string) => new TextEncoder().encode(value);
function join(parts: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const result = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
}
function u32(value: number) {
  const bytes = new Uint8Array(4);
  new DataView(bytes.buffer).setUint32(0, value);
  return bytes;
}
const crcTable = Uint32Array.from({ length: 256 }, (_, i) => {
  for (let bit = 0; bit < 8; bit++) i = (i >>> 1) ^ ((i & 1) ? 0xedb88320 : 0);
  return i >>> 0;
});
function chunk(type: string, data: Uint8Array) {
  const body = join([ascii(type), data]);
  let crc = 0xffffffff;
  for (const value of body) crc = crcTable[(crc ^ value) & 255] ^ (crc >>> 8);
  return join([u32(data.length), body, u32((crc ^ 0xffffffff) >>> 0)]);
}

// ICC v2 matrix/shaper profiles, built once per worker. Colorants are Bradford
// adapted from their standard D65 primaries to the ICC D50 PCS. A shared 4096
// sample decode-sRGB TRC avoids browser-specific canvas export behavior.
type Matrix = number[][];
const multiply = (a: Matrix, b: Matrix): Matrix => a.map(row =>
  b[0].map((_, col) => row.reduce((sum, v, i) => sum + v * b[i][col], 0)));
const D50 = [0.9642, 1, 0.8249];
const D65 = [0.3127 / 0.329, 1, (1 - 0.3127 - 0.329) / 0.329];
const BRADFORD = [[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]];
const BRADFORD_INVERSE = [[0.9869929055, -0.1470542564, 0.1599626517], [0.4323052697, 0.5183602715, 0.0492912282], [-0.0085286646, 0.0400428217, 0.9684866958]];
const cones = (v: number[]) => BRADFORD.map(row => row.reduce((sum, c, i) => sum + c * v[i], 0));
const whiteScale = cones(D50).map((v, i) => v / cones(D65)[i]);
const adaptation = multiply(BRADFORD_INVERSE, BRADFORD.map((row, i) => row.map(v => v * whiteScale[i])));
const RGB_TO_XYZ: Record<"srgb" | "p3", Matrix> = {
  srgb: [[0.4123907993, 0.3575843394, 0.1804807884], [0.2126390059, 0.7151686788, 0.0721923154], [0.0193308187, 0.1191947798, 0.9505321522]],
  p3: [[0.4865709486, 0.2656676932, 0.1982172852], [0.2289745641, 0.6917385218, 0.0792869141], [0, 0.0451133819, 1.0439443689]],
};
function fixed(value: number) { return u32(Math.round(value * 65536) >>> 0); }
function xyzTag(value: number[]) { return join([ascii("XYZ "), u32(0), ...value.map(fixed)]); }
const profiles = new Map<string, Uint8Array>();
export function displayIcc(space: "srgb" | "p3"): Uint8Array {
  const cached = profiles.get(space);
  if (cached) return cached;
  const name = ascii((space === "p3" ? "Display P3" : "sRGB") + "\0");
  const description = join([ascii("desc"), u32(0), u32(name.length), name, new Uint8Array(78)]);
  const curve = new Uint8Array(12 + 4096 * 2);
  curve.set(ascii("curv"));
  const curveView = new DataView(curve.buffer);
  curveView.setUint32(8, 4096);
  for (let i = 0; i < 4096; i++) {
    const v = i / 4095;
    const linear = v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    curveView.setUint16(12 + i * 2, Math.round(linear * 65535));
  }
  const colors = multiply(adaptation, RGB_TO_XYZ[space]);
  const tags: [string, Uint8Array][] = [
    ["desc", description],
    ["cprt", join([ascii("text"), u32(0), ascii("Public domain standard colorimetry\0")])],
    ["wtpt", xyzTag(D50)],
    ["chad", join([ascii("sf32"), u32(0), ...adaptation.flat().map(fixed)])],
    ...["r", "g", "b"].map((channel, col): [string, Uint8Array] => [channel + "XYZ", xyzTag(colors.map(row => row[col]))]),
    ["rTRC", curve], ["gTRC", curve], ["bTRC", curve],
  ];
  const header = new Uint8Array(128);
  const view = new DataView(header.buffer);
  view.setUint32(8, 0x02100000);
  header.set(ascii("mntrRGB XYZ "), 12);
  [2026, 9, 13, 0, 0, 0].forEach((v, i) => view.setUint16(24 + 2 * i, v));
  header.set(ascii("acsp"), 36);
  view.setUint32(64, 1); // Relative colorimetric intent.
  D50.forEach((v, i) => view.setInt32(68 + 4 * i, Math.round(v * 65536)));
  header.set(ascii("mcHK"), 80);
  const directory: Uint8Array[] = [u32(tags.length)];
  const data: Uint8Array[] = [];
  const offsets = new Map<Uint8Array, number>();
  let offset = 128 + 4 + tags.length * 12;
  for (const [signature, bytes] of tags) {
    if (!offsets.has(bytes)) {
      offsets.set(bytes, offset);
      const padding = new Uint8Array((4 - bytes.length % 4) % 4);
      data.push(bytes, padding);
      offset += bytes.length + padding.length;
    }
    directory.push(ascii(signature), u32(offsets.get(bytes)!), u32(bytes.length));
  }
  view.setUint32(0, offset);
  const result = join([header, ...directory, ...data]);
  profiles.set(space, result);
  return result;
}

export function encodePq(nits: number): number {
  const l = Math.max(0, Math.min(10000, nits)) / 10000;
  const p = l ** (2610 / 16384);
  return ((3424 / 4096 + (2413 / 128) * p) / (1 + (2392 / 128) * p)) ** (2523 / 32);
}
function sample(value: number, hdr: boolean): number {
  if (!Number.isFinite(value)) value = 0;
  // Internal HDR view values use 1.0 for 203-nit reference white. PQ PNGs use
  // the common 100-nit-unit convention, so only this encoder boundary upscales.
  if (hdr) return Math.round(encodePq(Math.max(0, Math.min(10, value * 2.03)) * 100) * 65535);
  const l = Math.max(0, Math.min(1, value));
  return Math.round((l <= 0.0031308 ? 12.92 * l : 1.055 * l ** (1 / 2.4) - 0.055) * 255);
}

/** Encode row-major display-linear RGB using the selected view's transfer and metadata. */
export function encodeLinearRgbPng(
  view: ViewId,
  width: number,
  height: number,
  linear: ArrayLike<number>,
): Uint8Array<ArrayBuffer> {
  if (!Number.isInteger(width) || width < 1 || !Number.isInteger(height) || height < 1)
    throw new RangeError("PNG dimensions must be positive integers.");
  if (linear.length !== width * height * 3)
    throw new RangeError("Linear RGB payload has the wrong length.");
  const hdr = view === 0 || view === 2;
  const bytesPerSample = hdr ? 2 : 1;
  const stride = 1 + width * 3 * bytesPerSample;
  const pixels = new Uint8Array(height * stride);
  const data = new DataView(pixels.buffer);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      for (let channel = 0; channel < 3; channel++) {
        const value = sample(Number(linear[(y * width + x) * 3 + channel]), hdr);
        const offset = y * stride + 1 + (x * 3 + channel) * bytesPerSample;
        if (hdr) data.setUint16(offset, value);
        else pixels[offset] = value;
      }
    }
  }
  const ihdr = join([u32(width), u32(height), new Uint8Array([hdr ? 16 : 8, 2, 0, 0, 0])]);
  const chunks = [chunk("IHDR", ihdr)];
  const primaries = view === 0 ? 9 : view === 1 ? 1 : 12;
  chunks.push(chunk("cICP", new Uint8Array([primaries, hdr ? 16 : 13, 0, 1])));
  if (!hdr) {
    const space = view === 1 ? "srgb" : "p3";
    chunks.push(chunk("iCCP", join([ascii(space === "srgb" ? "sRGB\0" : "Display P3\0"), new Uint8Array([0]), zlibSync(displayIcc(space), { level: 1 })])));
  }
  chunks.push(chunk("IDAT", zlibSync(pixels, { level: 1 })), chunk("IEND", new Uint8Array()));
  return join([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), ...chunks]);
}

/** Encode row-major display-linear RGBA. Alpha is unassociated coverage. */
export function encodeLinearRgbaPng(
  view: ViewId,
  width: number,
  height: number,
  rgba: ArrayLike<number>,
): Uint8Array<ArrayBuffer> {
  if (!Number.isInteger(width) || width < 1 || !Number.isInteger(height) || height < 1)
    throw new RangeError("PNG dimensions must be positive integers.");
  if (rgba.length !== width * height * 4)
    throw new RangeError("Linear RGBA payload has the wrong length.");
  const hdr = view === 0 || view === 2;
  const bytesPerSample = hdr ? 2 : 1;
  const stride = 1 + width * 4 * bytesPerSample;
  const pixels = new Uint8Array(height * stride);
  const data = new DataView(pixels.buffer);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      for (let channel = 0; channel < 4; channel++) {
        const value = channel === 3
          ? Math.round(Math.max(0, Math.min(1, Number(rgba[(y * width + x) * 4 + channel]))) * (hdr ? 65535 : 255))
          : sample(Number(rgba[(y * width + x) * 4 + channel]), hdr);
        const offset = y * stride + 1 + (x * 4 + channel) * bytesPerSample;
        if (hdr) data.setUint16(offset, value);
        else pixels[offset] = value;
      }
    }
  }
  const ihdr = join([u32(width), u32(height), new Uint8Array([hdr ? 16 : 8, 6, 0, 0, 0])]);
  const chunks = [chunk("IHDR", ihdr)];
  const primaries = view === 0 ? 9 : view === 1 ? 1 : 12;
  chunks.push(chunk("cICP", new Uint8Array([primaries, hdr ? 16 : 13, 0, 1])));
  if (!hdr) {
    const space = view === 1 ? "srgb" : "p3";
    chunks.push(chunk("iCCP", join([ascii(space === "srgb" ? "sRGB\0" : "Display P3\0"), new Uint8Array([0]), zlibSync(displayIcc(space), { level: 1 })])));
  }
  chunks.push(chunk("IDAT", zlibSync(pixels, { level: 1 })), chunk("IEND", new Uint8Array()));
  return join([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), ...chunks]);
}

/** One actual RGB image contains both swatch and surround. DEFLATE level 1. */
export function encodePreview(view: ViewId, foreground: ArrayLike<number>, background: ArrayLike<number>, valid = true): Uint8Array<ArrayBuffer> {
  const pixels = new Float32Array(PREVIEW_SIZE * PREVIEW_SIZE * 3);
  const fg = Array.from(foreground, v => valid ? Number(v) : 0);
  const bg = Array.from(background, Number);
  const cross = [0.86, 0.058, 0.058];
  for (let y = 0; y < PREVIEW_SIZE; y++) {
    for (let x = 0; x < PREVIEW_SIZE; x++) {
      const inside = x >= SWATCH_INSET && x < PREVIEW_SIZE - SWATCH_INSET && y >= SWATCH_INSET && y < PREVIEW_SIZE - SWATCH_INSET;
      const diagnostic = inside && !valid && x >= 50 && x < 206 && y >= 50 && y < 206 && (Math.abs(x - y) <= 4 || Math.abs(x + y - 255) <= 4);
      const rgb = diagnostic ? cross : inside ? fg : bg;
      pixels.set(rgb, (y * PREVIEW_SIZE + x) * 3);
    }
  }
  return encodeLinearRgbPng(view, PREVIEW_SIZE, PREVIEW_SIZE, pixels);
}
