import init, {
  inspect,
  new_bounded_display_preview,
  image_picker_analyze_xyz_d65_with_reference_white_encoded_as_linear_203,
  image_picker_analyze_scene_ap0,
  image_picker_code_from_acescg,
  image_picker_display_rgb_xyz_d65_batch,
  image_picker_display_rgb_scene_ap0_batch,
  picker_gpu_parameters,
  prepare,
  prepare_heic_pixels,
} from "./wasm/decomposition_pkg/modcam16_decomposition_wasm.js";
import { encodeLinearRgbPng, type ViewId } from "./preview_png";
import { SliceWebGpuRenderer, type ImageSourceMode } from "./slice_webgpu";
import libheif from "libheif-js/wasm-bundle";

type ImageRequest = {
  kind: "inspect" | "prepare" | "sample" | "preview";
  id: number;
  format: string;
  bytes?: ArrayBuffer;
  gamut?: string | null;
  transfer?: string | null;
  x?: number;
  y?: number;
  radius?: number;
  generation?: number;
  token?: number;
  appearanceToken?: number;
  view?: ViewId;
  referenceWhiteEncodedAsLinear203?: boolean;
};
type TransformRenderer = "webgpu" | "wasm";

type Prepared = {
  image: any;
  width: number;
  height: number;
  summary: any;
  sourceMode: ImageSourceMode;
  boundedPreview?: { width: number; height: number; pixels: Float32Array };
};

const scope = self as unknown as {
  onmessage: ((event: MessageEvent<ImageRequest>) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
};

const ready = init();
const bytesById = new Map<number, Uint8Array>();
const preparedById = new Map<number, Prepared>();
const latestGenerationById = new Map<number, number>();
const latestSampleTokenById = new Map<number, number>();
const latestAppearanceTokenById = new Map<number, number>();
let pendingPreview: ImageRequest | undefined;
let previewRunning = false;
let pendingSample: ImageRequest | undefined;
let sampleRunning = false;
// The same official OCIO table payload used by the slice renderer is shared
// with image/loupe appearance conversion.  A failed adapter or shader
// validation permanently selects the deterministic WASM path for this worker.
const imageGpu = new SliceWebGpuRenderer();
let imageGpuParameters: Float32Array | undefined;
let imageGpuDisabled = false;
const CPU_BATCH_PIXELS = 32_768;
type FallbackWorker = { worker: Worker; pending: Map<number, (value: Float32Array) => void>; failed: boolean };
let fallbackWorkers: FallbackWorker[] | null = null;
let fallbackWorkerCursor = 0;
let fallbackJobId = 0;

function ensureFallbackWorkers(): FallbackWorker[] {
  if (fallbackWorkers) return fallbackWorkers;
  if (typeof Worker === "undefined") throw new Error("Dedicated transform workers are unavailable.");
  const workers: FallbackWorker[] = [];
  for (let index = 0; index < 2; index += 1) {
    const worker = new Worker(new URL("./image_transform_worker.ts", import.meta.url), { type: "module" });
    const entry: FallbackWorker = { worker, pending: new Map(), failed: false };
    worker.onmessage = event => {
      const message = event.data as { id: number; pixels?: ArrayBuffer; error?: string };
      const resolve = entry.pending.get(message.id);
      if (!resolve) return;
      entry.pending.delete(message.id);
      if (message.pixels) resolve(new Float32Array(message.pixels));
      else resolve(new Float32Array());
    };
    worker.onerror = () => {
      entry.failed = true;
      for (const resolve of entry.pending.values()) resolve(new Float32Array());
      entry.pending.clear();
    };
    workers.push(entry);
  }
  fallbackWorkers = workers;
  return workers;
}

function wasmDisplayRgbBatch(pixels: Float32Array, view: ViewId, sourceMode: ImageSourceMode, referenceWhiteEncodedAsLinear203: boolean): Float32Array {
  return sourceMode === "scene-reference-aces"
    ? image_picker_display_rgb_scene_ap0_batch(pixels, view)
    : image_picker_display_rgb_xyz_d65_batch(pixels, view, referenceWhiteEncodedAsLinear203);
}

async function cpuDisplayRgbBatch(pixels: Float32Array, view: ViewId, sourceMode: ImageSourceMode, referenceWhiteEncodedAsLinear203: boolean): Promise<Float32Array> {
  const workers = ensureFallbackWorkers().filter(entry => !entry.failed);
  if (!workers.length) return wasmDisplayRgbBatch(pixels, view, sourceMode, referenceWhiteEncodedAsLinear203);
  const output = new Float32Array(pixels.length);
  const jobs: Promise<void>[] = [];
  for (let offset = 0, chunk = 0; offset < pixels.length; offset += CPU_BATCH_PIXELS * 3, chunk += 1) {
    const end = Math.min(pixels.length, offset + CPU_BATCH_PIXELS * 3);
    const input = pixels.slice(offset, end);
    const backup = input.slice();
    const candidates = workers.filter(entry => !entry.failed);
    if (!candidates.length) {
      output.set(wasmDisplayRgbBatch(input, view, sourceMode, referenceWhiteEncodedAsLinear203), offset);
      continue;
    }
    const slot = candidates[fallbackWorkerCursor++ % candidates.length];
    const id = ++fallbackJobId;
    jobs.push(new Promise<void>(resolve => {
      slot.pending.set(id, result => {
        // A worker error is represented by an empty result; run that chunk
        // locally so a transient worker failure cannot corrupt row ordering.
        const converted = result.length === input.length
          ? result
          : wasmDisplayRgbBatch(backup, view, sourceMode, referenceWhiteEncodedAsLinear203);
        output.set(converted, offset);
        resolve();
      });
      try {
        slot.worker.postMessage({ id, pixels: input.buffer, view, sourceMode, referenceWhiteEncodedAsLinear203 }, [input.buffer]);
      } catch {
        slot.failed = true;
        const converted = wasmDisplayRgbBatch(backup, view, sourceMode, referenceWhiteEncodedAsLinear203);
        slot.pending.delete(id);
        output.set(converted, offset);
        resolve();
      }
    }));
  }
  await Promise.all(jobs);
  return output;
}

async function displayRgbBatch(pixels: Float32Array, view: ViewId, sourceMode: ImageSourceMode, referenceWhiteEncodedAsLinear203: boolean): Promise<Float32Array> {
  if (!pixels.length) return new Float32Array();
  if (!imageGpuDisabled && imageGpu.available) {
    try {
      imageGpuParameters ??= picker_gpu_parameters();
      return await imageGpu.renderImage(imageGpuParameters, viewIndex(view), sourceMode, referenceWhiteEncodedAsLinear203, pixels);
    } catch {
      imageGpuDisabled = true;
    }
  }
  // Keep the fallback bounded and parallel. The WASM implementation is the
  // numerical reference when WebGPU is absent or fails validation.
  try {
    return await cpuDisplayRgbBatch(pixels, view, sourceMode, referenceWhiteEncodedAsLinear203);
  } catch {
    return wasmDisplayRgbBatch(pixels, view, sourceMode, referenceWhiteEncodedAsLinear203);
  }
}

function viewIndex(view: ViewId): number {
  return view === 0 ? 0 : view === 1 ? 1 : view === 2 ? 2 : 3;
}

function textHasGainMap(bytes: Uint8Array): boolean {
  const text = new TextDecoder().decode(bytes);
  return text.includes("urn:com:apple:photo:2020:aux:hdrgainmap") || text.includes("HDRGainMap");
}

function parseNclx(bytes: Uint8Array): { gamut: string; transfer: string } | undefined {
  for (let i = 0; i + 11 < bytes.length; i += 1) {
    if (bytes[i] !== 0x6e || bytes[i + 1] !== 0x63 || bytes[i + 2] !== 0x6c || bytes[i + 3] !== 0x78) continue;
    const primaries = (bytes[i + 4] << 8) | bytes[i + 5];
    const transfer = (bytes[i + 6] << 8) | bytes[i + 7];
    const gamut = primaries === 1 ? "Rec.709 / sRGB" : primaries === 9 ? "Rec.2020" : primaries === 12 ? "Display P3 / P3-D65" : undefined;
    const tr = transfer === 13 ? "sRGB" : transfer === 16 ? "PQ / ST 2084" : transfer === 18 ? "HLG / BT.2100" : transfer === 1 || transfer === 14 || transfer === 15 ? "BT.709 / BT.2020" : transfer === 8 ? "Linear" : undefined;
    if (gamut && tr) return { gamut, transfer: tr };
  }
  return undefined;
}

function nativeRgb16(image: any): { width: number; height: number; pixels: Float32Array; bitDepth: number } {
  const module = libheif as any;
  const decoded = module.heif_js_decode_image2(image, module.heif_colorspace_RGB, module.heif_chroma_interleaved_RRGGBB_LE);
  if (!decoded || decoded.code || !decoded.channels?.length) throw new Error("libheif-js could not decode native RGB samples.");
  const channel = decoded.channels.find((entry: any) => Number(entry.id) === Number(module.heif_channel_interleaved)) ?? decoded.channels[0];
  const width = Number(decoded.width), height = Number(decoded.height), bits = Number(channel.bits_per_pixel || 16);
  const bytes = channel.data instanceof Uint8Array ? channel.data : new Uint8Array(channel.data);
  const pixels = new Float32Array(width * height * 3), stride = Number(channel.stride || width * 6), max = (2 ** bits) - 1;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let y = 0, out = 0; y < height; y += 1) {
    const row = y * stride;
    for (let x = 0; x < width; x += 1, out += 3) {
      const offset = row + x * 6;
      pixels[out] = view.getUint16(offset, true) / max;
      pixels[out + 1] = view.getUint16(offset + 2, true) / max;
      pixels[out + 2] = view.getUint16(offset + 4, true) / max;
    }
  }
  module.heif_image_release(decoded.image);
  return { width, height, pixels, bitDepth: bits };
}

function extractHeifIcc(module: any, image: any): Uint8Array {
  const size = Number(module._heif_image_handle_get_raw_color_profile_size(image.$$?.ptr));
  if (!(size > 0)) return new Uint8Array();
  const destination = module._malloc(size), error = module._malloc(32);
  try {
    module._heif_image_handle_get_raw_color_profile(error, image.$$?.ptr, destination);
    return new Uint8Array(module.HEAPU8.slice(destination, destination + size));
  } finally {
    module._free(destination);
    module._free(error);
  }
}

function nativeAuxiliary(module: any, context: any, primary: any): { pixels: Float32Array; width: number; height: number } | undefined {
  const pointer = primary.$$?.ptr;
  const count = Number(module._heif_image_handle_get_number_of_auxiliary_images(pointer, 0));
  if (!count) return undefined;
  const idsPointer = module._malloc(count * 4);
  const actual = Number(module._heif_image_handle_get_list_of_auxiliary_image_IDs(pointer, 0, idsPointer, count));
  try {
    for (let index = 0; index < actual; index += 1) {
      const auxiliaryId = module.HEAPU32[(idsPointer >> 2) + index];
      const handle = module.heif_js_context_get_image_handle(context, auxiliaryId);
      if (!handle || handle.code) continue;
      const typeOutput = module._malloc(4);
      const error = module._malloc(32);
      let auxiliaryType = "";
      try {
        module._heif_image_handle_get_auxiliary_type(error, handle.$$?.ptr, typeOutput);
        const typePointer = module.HEAPU32[typeOutput >> 2];
        if (typePointer) auxiliaryType = new TextDecoder()
          .decode(module.HEAPU8.subarray(typePointer, typePointer + 160))
          .split("\0")[0];
      } finally {
        module._free(typeOutput);
        module._free(error);
      }
      if (auxiliaryType !== "urn:com:apple:photo:2020:aux:hdrgainmap") continue;
      const decoded = nativeRgb16(handle);
      const pixels = new Float32Array(decoded.width * decoded.height);
      for (let pixel = 0; pixel < pixels.length; pixel += 1) pixels[pixel] = decoded.pixels[pixel * 3];
      return { pixels, width: decoded.width, height: decoded.height };
    }
  } finally {
    module._free(idsPointer);
  }
  return undefined;
}

function extractExif(module: any, primary: any): Uint8Array {
  const pointer = primary.$$?.ptr;
  const count = Number(module._heif_image_handle_get_number_of_metadata_blocks(pointer, 0));
  if (!count) return new Uint8Array();
  const idsPointer = module._malloc(count * 4);
  const actual = Number(module._heif_image_handle_get_list_of_metadata_block_IDs(pointer, 0, idsPointer, count));
  try {
    for (let index = 0; index < actual; index += 1) {
      const metadataId = module.HEAPU32[(idsPointer >> 2) + index];
      const typePointer = module._heif_image_handle_get_metadata_type(pointer, metadataId);
      const type = new TextDecoder().decode(module.HEAPU8.subarray(typePointer, typePointer + 8)).split("\0")[0];
      if (type !== "Exif") continue;
      const size = Number(module._heif_image_handle_get_metadata_size(pointer, metadataId));
      const destination = module._malloc(size);
      const error = module._malloc(32);
      try {
        module._heif_image_handle_get_metadata(error, pointer, metadataId, destination);
        return new Uint8Array(module.HEAPU8.slice(destination, destination + size));
      } finally {
        module._free(destination);
        module._free(error);
      }
    }
  } finally {
    module._free(idsPointer);
  }
  return new Uint8Array();
}

async function decodeHeif(bytes: Uint8Array): Promise<{ width: number; height: number; pixels: Float32Array; icc: Uint8Array; gamut?: string; transfer?: string; gain?: { pixels: Float32Array; width: number; height: number }; gainmap_metadata_detected: boolean; gainmap_confirmed: boolean; exif: Uint8Array; warnings: string[] }> {
  const module = libheif as any;
  const decoder = new module.HeifDecoder();
  const images = decoder.decode(bytes);
  if (!images?.length) throw new Error("The HEIF file contains no decodable image.");
  const image = module.heif_js_context_get_primary_image_handle(decoder.decoder);
  if (!image || image.code) throw new Error("The HEIF file contains no decodable primary image.");
  const native = nativeRgb16(image);
  const nclx = parseNclx(bytes);
  const gainMapPresent = textHasGainMap(bytes);
  const gain = gainMapPresent ? nativeAuxiliary(module, decoder.decoder, image) : undefined;
  const warnings = gainMapPresent && !gain
    ? ["Apple HDR gain-map metadata was detected, but its auxiliary image could not be decoded."]
    : [];
  return {
    ...native,
    icc: extractHeifIcc(module, image),
    gamut: nclx?.gamut,
    transfer: nclx?.transfer,
    gain,
    gainmap_metadata_detected: gainMapPresent,
    gainmap_confirmed: Boolean(gain),
    exif: extractExif(module, image),
    warnings,
  };
}

function summaryForHeif(decoded: Awaited<ReturnType<typeof decodeHeif>>, format: string) {
  const embedded = Boolean(decoded.icc.length || (decoded.gamut && decoded.transfer));
  return {
    format,
    width: decoded.width,
    height: decoded.height,
    gamut: decoded.gamut ?? null,
    transfer: decoded.transfer ?? null,
    metadata_source: decoded.icc.length ? "HEIF ICC profile" : decoded.gamut ? "HEIF nclx metadata" : null,
    automatic_icc: decoded.icc.length > 0,
    embedded_available: embedded,
    gainmap_metadata_detected: decoded.gainmap_metadata_detected,
    gainmap_confirmed: decoded.gainmap_confirmed,
    warnings: decoded.warnings,
  };
}

async function makePreview(
  prepared: Prepared,
  view: ViewId,
  referenceWhiteEncodedAsLinear203: boolean,
): Promise<{ png: Uint8Array; width: number; height: number; renderer: TransformRenderer }> {
  if (!prepared.boundedPreview) {
    const display = new_bounded_display_preview(prepared.width, prepared.height, 1600);
    try {
      const chunks: Float32Array[] = [];
      const rowsPerBatch = Math.max(1, Math.min(prepared.height, Math.floor(256 * 1024 / Math.max(1, prepared.width))));
      for (let y = 0; y < prepared.height; y += rowsPerBatch) {
        const rows = Math.min(rowsPerBatch, prepared.height - y);
        const reduced = display.append_rgb(prepared.image.read_pixels(y * prepared.width, rows * prepared.width));
        if (reduced.length) chunks.push(new Float32Array(reduced));
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      }
      display.finish();
      const pixels = new Float32Array(chunks.reduce((sum, chunk) => sum + chunk.length, 0));
      let offset = 0;
      for (const chunk of chunks) { pixels.set(chunk, offset); offset += chunk.length; }
      prepared.boundedPreview = { width: display.width, height: display.height, pixels };
    } finally {
      display.free();
    }
  }
  const source = prepared.boundedPreview;
  const rgb = new Float32Array(source.pixels.length);
  // Keep GPU/WASM submissions bounded for mobile adapters and let the event
  // loop observe generation changes between batches.
  const batchLength = 131_072 * 3;
  for (let offset = 0; offset < source.pixels.length; offset += batchLength) {
    const end = Math.min(source.pixels.length, offset + batchLength);
    const converted = await displayRgbBatch(source.pixels.subarray(offset, end), view, prepared.sourceMode, referenceWhiteEncodedAsLinear203);
    rgb.set(converted, offset);
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
  return {
    png: encodeLinearRgbPng(view, source.width, source.height, rgb),
    width: source.width,
    height: source.height,
    renderer: !imageGpuDisabled && imageGpu.available ? "webgpu" : "wasm",
  };
}

async function inspectImage(message: ImageRequest, bytes: Uint8Array): Promise<void> {
  if (message.format === "heic" || message.format === "heif") {
    const decoded = await decodeHeif(bytes);
    scope.postMessage({ kind: "inspect", id: message.id, generation: message.generation ?? 0, summary: summaryForHeif(decoded, message.format) });
    return;
  }
  if (message.format === "dng") {
    // Match the reference decomposition loader: DNG inspection develops the
    // embedded camera calibration once, both to validate the file and to
    // expose the developed dimensions/diagnostics before the user starts
    // locating pixels.  Keep that prepared object for the following ready
    // request so a second full raw development is not required.
    const request = { format: "dng", gamut: null, transfer: null, profile: 4, refl: 0.5, blur_sigma: 0 };
    const image = prepare(bytes, request);
    const summary = image.summary ?? inspect(bytes, message.format);
    const width = Number(image.width), height = Number(image.height);
    preparedById.set(message.id, { image, width, height, summary, sourceMode: "display-linear-xyz-d65" });
    scope.postMessage({ kind: "inspect", id: message.id, generation: message.generation ?? 0, summary });
    return;
  }
  scope.postMessage({ kind: "inspect", id: message.id, generation: message.generation ?? 0, summary: inspect(bytes, message.format) });
}

async function prepareImage(message: ImageRequest, bytes: Uint8Array): Promise<void> {
  if ((latestGenerationById.get(message.id) ?? message.generation ?? 0) !== (message.generation ?? 0)) return;
  const request = { format: message.format, gamut: message.gamut ?? null, transfer: message.transfer ?? null, profile: 4, refl: 0.5, blur_sigma: 0 };
  let image: any;
  let summary: any;
  if (message.format === "heic" || message.format === "heif") {
    const decoded = await decodeHeif(bytes);
    const effective = { ...request };
    // An embedded ICC profile has precedence over container nclx tags, just
    // as in the reference decompose worker.  Only fall back to nclx when no
    // usable ICC profile is present.
    if (effective.gamut === null && effective.transfer === null && !decoded.icc.length && decoded.gamut && decoded.transfer) {
      effective.gamut = decoded.gamut;
      effective.transfer = decoded.transfer;
    }
    image = prepare_heic_pixels(
      decoded.pixels,
      decoded.width,
      decoded.height,
      effective,
      decoded.icc,
      decoded.gain?.pixels ?? new Float32Array(),
      decoded.gain?.width ?? 0,
      decoded.gain?.height ?? 0,
      decoded.exif,
    );
    summary = summaryForHeif(decoded, message.format);
  } else if (message.format === "dng") {
    const cached = preparedById.get(message.id);
    if (cached) {
      image = cached.image;
      summary = cached.summary;
      preparedById.delete(message.id);
    } else {
      image = prepare(bytes, request);
      summary = image.summary ?? inspect(bytes, message.format);
    }
  } else {
    image = prepare(bytes, request);
    summary = image.summary ?? inspect(bytes, message.format);
  }
  const width = Number(image.width), height = Number(image.height);
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) throw new Error("The image has invalid dimensions.");
  const previous = preparedById.get(message.id);
  if ((latestGenerationById.get(message.id) ?? message.generation ?? 0) !== (message.generation ?? 0)) {
    try { image.free(); } catch { /* stale preparation */ }
    return;
  }
  if (previous && previous.image !== image) {
    try { previous.image.free(); } catch { /* best effort */ }
  }
  const effectiveGamut = message.gamut ?? summary?.gamut ?? null;
  const sourceMode: ImageSourceMode = message.format.toLowerCase() === "dng"
    ? "display-linear-xyz-d65"
    : message.format.toLowerCase() === "exr" &&
    (effectiveGamut === "ACEScg" || effectiveGamut === "ACES2065-1")
    ? "scene-reference-aces"
    : "display-linear-xyz-d65";
  preparedById.set(message.id, { image, width, height, summary, sourceMode });
  const referenceWhiteEncodedAsLinear203 = message.referenceWhiteEncodedAsLinear203 ?? false;
  const preview = await makePreview(preparedById.get(message.id)!, message.view ?? 0, referenceWhiteEncodedAsLinear203);
  scope.postMessage({ kind: "ready", id: message.id, generation: message.generation ?? 0, width, height, previewWidth: preview.width, previewHeight: preview.height, summary, view: message.view ?? 0, sourceMode, referenceWhiteEncodedAsLinear203, renderer: preview.renderer, png: preview.png.buffer }, [preview.png.buffer]);
}

async function previewImage(message: ImageRequest): Promise<void> {
  const prepared = preparedById.get(message.id);
  if (!prepared) throw new Error("The image is not prepared; load it again.");
  const referenceWhiteEncodedAsLinear203 = message.referenceWhiteEncodedAsLinear203 ?? false;
  const preview = await makePreview(prepared, message.view ?? 0, referenceWhiteEncodedAsLinear203);
  if ((latestGenerationById.get(message.id) ?? message.generation ?? 0) !== (message.generation ?? 0)) return;
  if ((latestAppearanceTokenById.get(message.id) ?? message.appearanceToken ?? 0) !== (message.appearanceToken ?? 0)) return;
  scope.postMessage({ kind: "preview", id: message.id, generation: message.generation ?? 0, appearanceToken: message.appearanceToken ?? 0, width: prepared.width, height: prepared.height, previewWidth: preview.width, previewHeight: preview.height, view: message.view ?? 0, sourceMode: prepared.sourceMode, referenceWhiteEncodedAsLinear203, renderer: preview.renderer, png: preview.png.buffer }, [preview.png.buffer]);
}

async function previewLatest(): Promise<void> {
  previewRunning = true;
  while (pendingPreview) {
    const message = pendingPreview;
    pendingPreview = undefined;
    try { await previewImage(message); }
    catch (error) {
      scope.postMessage({ kind: "error", id: message.id, generation: message.generation ?? 0, message: error instanceof Error ? error.message : String(error) });
    }
  }
  previewRunning = false;
}

async function sampleImage(message: ImageRequest): Promise<void> {
  const prepared = preparedById.get(message.id);
  if (!prepared) throw new Error("The image is not prepared; load it again.");
  const cx = Math.max(0, Math.min(prepared.width - 1, Math.round(message.x ?? 0)));
  const cy = Math.max(0, Math.min(prepared.height - 1, Math.round(message.y ?? 0)));
  const radius = Math.max(0, Number.isFinite(message.radius) ? Number(message.radius) : 3);
  const minX = Math.max(0, Math.floor(cx - radius)), maxX = Math.min(prepared.width - 1, Math.ceil(cx + radius));
  const minY = Math.max(0, Math.floor(cy - radius)), maxY = Math.min(prepared.height - 1, Math.ceil(cy + radius));
  // PreparedImage.read_pixels() addresses a contiguous row-major span.  Read
  // complete rows so the native x coordinate remains stable even when the
  // circular neighborhood is clipped at an image edge.
  const rowCount = maxY - minY + 1;
  const start = minY * prepared.width;
  const count = rowCount * prepared.width;
  const pixels = prepared.image.read_pixels(start, count) as Float32Array;
  const points: Array<{ j: number; x: number; y: number }> = [];
  const acescg: number[][] = [];
  const loupe: number[] = [];
  let rejected = 0;
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      const local = ((y - minY) * prepared.width + x) * 3;
      const source = [pixels[local], pixels[local + 1], pixels[local + 2]];
      // The loupe is a rectangular nearest-neighbor raster. Keep every pixel
      // in the clipped square, including pixels just outside the sampling
      // circle, so the UI can render a stable grid without holes.
      loupe.push(...Array.from(source));
      const converted = prepared.sourceMode === "scene-reference-aces"
        ? image_picker_analyze_scene_ap0(source[0], source[1], source[2])
        : image_picker_analyze_xyz_d65_with_reference_white_encoded_as_linear_203(source[0], source[1], source[2], message.referenceWhiteEncodedAsLinear203 ?? false);
      const inCircle = Math.hypot(x - cx, y - cy) <= radius + 1e-12;
      if (!inCircle) continue;
      if (converted[0] > 0.5) {
        points.push({ j: converted[4], x: converted[5], y: converted[6] });
        acescg.push([converted[1], converted[2], converted[3]]);
      } else rejected += 1;
    }
  }
  const mean = { j: 0, x: 0, y: 0 };
  const meanAcescg = [0, 0, 0];
  for (const point of points) { mean.j += point.j; mean.x += point.x; mean.y += point.y; }
  for (const value of acescg) for (let c = 0; c < 3; c += 1) meanAcescg[c] += value[c];
  if (points.length) {
    mean.j /= points.length; mean.x /= points.length; mean.y /= points.length;
    for (let c = 0; c < 3; c += 1) meanAcescg[c] /= points.length;
  }
  const meanCode = points.length
    ? image_picker_code_from_acescg(meanAcescg[0], meanAcescg[1], meanAcescg[2])
    : new Float64Array([0, 0, 0, 0]);
  // Render the interpreted XYZ-D65 or scene-AP0 samples into display RGB for a direct loupe
  // image. CSS pixelated scaling preserves one sharp square per source pixel
  // without decoding this HDR PNG through a 2D canvas.
  const loupeWidth = maxX - minX + 1;
  const loupeHeight = maxY - minY + 1;
  const loupeRgb = loupe.length
    ? await displayRgbBatch(new Float32Array(loupe), message.view ?? 0, prepared.sourceMode, message.referenceWhiteEncodedAsLinear203 ?? false)
    : new Float32Array();
  const loupePng = loupeRgb.length
    ? encodeLinearRgbPng(message.view ?? 0, loupeWidth, loupeHeight, loupeRgb)
    : new Uint8Array();
  if ((latestSampleTokenById.get(message.id) ?? message.token ?? 0) !== (message.token ?? 0)) return;
  scope.postMessage({ kind: "sample", id: message.id, generation: message.generation ?? 0, token: message.token ?? 0, x: cx, y: cy, minX, minY, width: loupeWidth, height: loupeHeight, loupe: loupePng.buffer, points, mean, meanAcescg, meanCode, rejected, total: points.length + rejected, view: message.view ?? 0, sourceMode: prepared.sourceMode, referenceWhiteEncodedAsLinear203: message.referenceWhiteEncodedAsLinear203 ?? false }, [loupePng.buffer]);
}

async function sampleLatest(): Promise<void> {
  sampleRunning = true;
  while (pendingSample) {
    const message = pendingSample;
    pendingSample = undefined;
    try { await sampleImage(message); }
    catch (error) {
      scope.postMessage({ kind: "error", id: message.id, generation: message.generation ?? 0, message: error instanceof Error ? error.message : String(error) });
    }
  }
  sampleRunning = false;
}

scope.onmessage = (event: MessageEvent<ImageRequest>) => {
  const message = event.data;
  if (message.kind === "preview") latestAppearanceTokenById.set(message.id, message.appearanceToken ?? 0);
  const generation = message.generation ?? 0;
  const previousGeneration = latestGenerationById.get(message.id) ?? -1;
  if (generation < previousGeneration) return;
  latestGenerationById.set(message.id, generation);
  void ready.then(async () => {
    try {
      if ((latestGenerationById.get(message.id) ?? generation) !== generation) return;
      if (message.bytes) bytesById.set(message.id, new Uint8Array(message.bytes));
      if (message.kind === "inspect") {
        for (const [id, prepared] of preparedById) {
          if (id === message.id) continue;
          try { prepared.image.free(); } catch { /* best effort */ }
          preparedById.delete(id);
          bytesById.delete(id);
          latestGenerationById.delete(id);
          latestSampleTokenById.delete(id);
          latestAppearanceTokenById.delete(id);
        }
        const bytes = bytesById.get(message.id);
        if (!bytes) throw new Error("Image bytes are unavailable.");
        await inspectImage(message, bytes);
      } else if (message.kind === "prepare") {
        const bytes = bytesById.get(message.id);
        if (!bytes) throw new Error("Image bytes are unavailable.");
        await prepareImage(message, bytes);
      } else if (message.kind === "preview") {
        pendingPreview = message;
        if (!previewRunning) void previewLatest();
      } else {
        latestSampleTokenById.set(message.id, message.token ?? 0);
        pendingSample = message;
        if (!sampleRunning) void sampleLatest();
      }
    } catch (error) {
      scope.postMessage({ kind: "error", id: message.id, generation, message: error instanceof Error ? error.message : String(error) });
    }
  });
};
