// Each worker owns an independent WASM instance. Evaluation has its own worker.
import init, {
  picker_colorchecker_mode, picker_evaluate_mode, picker_from_encoded_mode, picker_render_linear_rows_mode,
  picker_gpu_parameters,
} from "./wasm/pkg/modcam16_color_core.js";
import { encodeLinearRgbaPng, encodePreview, type ViewId } from "./preview_png";
import { SliceWebGpuRenderer } from "./slice_webgpu";

type RenderMessage = {
  kind: "render"; id: number; profile: ViewId; j: number;
  width: number; height: number; fullRec2020: boolean;
};
type EvaluateMessage = {
  kind: "evaluate"; id: number; profile: ViewId; j: number;
  fittedRadiusX: number; fittedRadiusY: number; backgroundJ: number; fullRec2020: boolean;
};
type Message = RenderMessage | EvaluateMessage
  | { kind: "colorchecker"; id: number; profile: ViewId }
  | { kind: "set"; id: number; profile: number; red: number; green: number; blue: number; fullRec2020: boolean }
  | { kind: "cancel-render"; id: number };

const workerScope = self as unknown as {
  onmessage: ((event: MessageEvent<Message>) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
};
const ready = init();
const latest = new Map<string, number>();
let pendingEvaluation: EvaluateMessage | undefined;
let evaluationQueued = false;
const gpuSlice = new SliceWebGpuRenderer();
const FULL_SLICE = 512;
let gpuParameters: Float32Array | undefined;
let cachedSlice: { key: string; pixels: Float32Array; renderer: "webgpu" | "wasm" } | undefined;
let pendingRender: RenderMessage | undefined;
let renderQueued = false;

function viewIndex(view: ViewId) {
  return view === 0 ? 0 : view === 1 ? 1 : view === 2 ? 2 : 3;
}

async function renderSlice(message: RenderMessage) {
  await ready;
  if (latest.get("render") !== message.id) return;
  const baseKey = `${message.profile}:${Number(message.fullRec2020)}:${message.j.toFixed(12)}:${message.width}:${message.height}`;
  let pixels = cachedSlice?.key === baseKey ? cachedSlice.pixels : undefined;
  let renderer: "webgpu" | "wasm" = cachedSlice?.key === baseKey ? cachedSlice.renderer : "wasm";
  if (!pixels) {
    // A low-resolution request is specifically the CPU/WASM interaction path.
    // Never confirm or invoke WebGPU with a 64x64 slice: once WebGPU succeeds,
    // the main thread permanently requests full-resolution interaction frames.
    if (message.width === FULL_SLICE && message.height === FULL_SLICE && gpuSlice.available) {
      try {
        gpuParameters ??= picker_gpu_parameters();
        pixels = await gpuSlice.render(gpuParameters, viewIndex(message.profile), message.j, message.width, message.height, message.fullRec2020);
        renderer = "webgpu";
      } catch {
        pixels = picker_render_linear_rows_mode(message.profile, message.j, message.width, message.height, 0, message.height, message.fullRec2020);
      }
    } else {
      pixels = picker_render_linear_rows_mode(message.profile, message.j, message.width, message.height, 0, message.height, message.fullRec2020);
    }
    cachedSlice = { key: baseKey, pixels, renderer };
  }
  if (latest.get("render") !== message.id) return;
  const png = encodeLinearRgbaPng(message.profile, message.width, message.height, pixels);
  workerScope.postMessage({ ...message, kind: "slice", renderer, png }, [png.buffer]);
}

async function renderLatest() {
  renderQueued = true;
  while (pendingRender) {
    const message = pendingRender;
    pendingRender = undefined;
    try { await renderSlice(message); }
    catch { reportError(message); }
  }
  renderQueued = false;
}

function reportError(message: Message, operation: string = message.kind) {
  workerScope.postMessage({ kind: "worker-error", id: message.id, operation,
    profile: "profile" in message ? message.profile : undefined });
}

async function evaluateLatest() {
  evaluationQueued = false;
  const message = pendingEvaluation;
  if (!message) return;
  pendingEvaluation = undefined;
  try {
    await ready;
    if (latest.get("evaluate") !== message.id) return;
    const values = picker_evaluate_mode(message.profile, message.j, message.fittedRadiusX, message.fittedRadiusY, message.backgroundJ, message.fullRec2020);
    workerScope.postMessage({ ...message, values });
    try {
      const png = encodePreview(message.profile, values.slice(26, 29), values.slice(29, 32), values[0] > 0.5);
      workerScope.postMessage({ ...message, kind: "preview", valid: values[0] > 0.5, png }, [png.buffer]);
    } catch { reportError(message, "preview"); }
  } catch { reportError(message); }
}

workerScope.onmessage = ({ data: message }) => {
  if (message.kind === "cancel-render") {
    latest.set("render", Math.max(latest.get("render") ?? -1, message.id + 1));
    return;
  }
  latest.set(message.kind, message.id);
  if (message.kind === "evaluate") {
    pendingEvaluation = message;
    if (!evaluationQueued) {
      evaluationQueued = true;
      setTimeout(() => void evaluateLatest(), 0);
    }
    return;
  }
  void ready.then(() => {
    if (latest.get(message.kind) !== message.id) return;
    if (message.kind === "render") {
      pendingRender = message;
      if (!renderQueued) void renderLatest();
    } else if (message.kind === "colorchecker") {
      const points = picker_colorchecker_mode(message.profile);
      const width = 1024, height = 1024;
      const rgba = new Float32Array(width * height * 4);
      for (let patch = 0; patch < 18; patch += 1) {
        const offset = patch * 7;
        const px = points[offset + 1] * (width - 1);
        const py = (1 - points[offset + 2]) * (height - 1);
        const radius = 8;
        const minX = Math.max(0, Math.floor(px - radius - 1));
        const maxX = Math.min(width - 1, Math.ceil(px + radius + 1));
        const minY = Math.max(0, Math.floor(py - radius - 1));
        const maxY = Math.min(height - 1, Math.ceil(py + radius + 1));
        for (let y = minY; y <= maxY; y += 1) for (let x = minX; x <= maxX; x += 1) {
          const alpha = Math.max(0, Math.min(1, radius + 0.75 - Math.hypot(x - px, y - py)));
          if (alpha <= 0) continue;
          const index = (y * width + x) * 4;
          rgba[index] = points[offset + 3];
          rgba[index + 1] = points[offset + 4];
          rgba[index + 2] = points[offset + 5];
          rgba[index + 3] = Math.max(rgba[index + 3], alpha);
        }
      }
      const png = encodeLinearRgbaPng(message.profile, width, height, rgba);
      workerScope.postMessage({ ...message, points, png }, [png.buffer]);
    } else if (message.kind === "set") {
      workerScope.postMessage({ ...message, values: picker_from_encoded_mode(message.red, message.green, message.blue, message.fullRec2020) });
    }
  }).catch(() => reportError(message));
};
