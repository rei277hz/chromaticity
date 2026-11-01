// Independent PNG inspection: node's zlib (not the encoder's fflate), a
// bitwise CRC implementation, unfiltered RGB samples, and metadata parsing.
import assert from "node:assert/strict";
import { inflateSync } from "node:zlib";

export function readPng(bytes) {
  const png = Buffer.from(bytes);
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const chunks = new Map();
  for (let offset = 8; offset < png.length;) {
    const length = png.readUInt32BE(offset);
    const name = png.toString("ascii", offset + 4, offset + 8);
    const payload = png.subarray(offset + 8, offset + 8 + length);
    let crc = 0xffffffff;
    for (const byte of png.subarray(offset + 4, offset + 8 + length)) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    assert.equal((crc ^ 0xffffffff) >>> 0, png.readUInt32BE(offset + 8 + length), `${name} CRC`);
    chunks.set(name, Buffer.concat([chunks.get(name) ?? Buffer.alloc(0), payload]));
    offset += length + 12;
    assert.ok(offset <= png.length, "chunk stays in file");
  }
  assert.ok(chunks.has("IEND"));
  const ihdr = chunks.get("IHDR");
  const width = ihdr.readUInt32BE(0), height = ihdr.readUInt32BE(4), depth = ihdr[8], colorType = ihdr[9];
  assert.ok(colorType === 2 || colorType === 6, "RGB or RGBA, without palette");
  assert.deepEqual([...ihdr.subarray(10)], [0, 0, 0]);
  const sampleBytes = depth === 16 ? 2 : 1;
  const channelCount = colorType === 6 ? 4 : 3;
  const pixelBytes = sampleBytes * channelCount;
  const stride = 1 + width * pixelBytes;
  const raw = inflateSync(chunks.get("IDAT"));
  assert.equal(raw.length, stride * height);
  for (let y = 0; y < height; y++) assert.equal(raw[y * stride], 0);
  let icc;
  if (chunks.has("iCCP")) {
    const payload = chunks.get("iCCP"), nameEnd = payload.indexOf(0);
    assert.equal(payload[nameEnd + 1], 0);
    icc = inflateSync(payload.subarray(nameEnd + 2));
    assert.equal(icc.readUInt32BE(0), icc.length);
    assert.equal(icc.toString("ascii", 36, 40), "acsp");
  }
  return {
    width, height, depth, colorType, chunks, icc,
    pixel(x, y) {
      const offset = y * stride + 1 + x * pixelBytes;
      return Array.from({ length: 3 }, (_, c) => depth === 16 ? raw.readUInt16BE(offset + c * 2) : raw[offset + c]);
    },
    alpha(x, y) {
      if (colorType !== 6) return depth === 16 ? 65535 : 255;
      const offset = y * stride + 1 + x * pixelBytes + 3 * sampleBytes;
      return depth === 16 ? raw.readUInt16BE(offset) : raw[offset];
    },
  };
}
