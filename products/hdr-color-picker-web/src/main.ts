import "./style.css";
import { VIEW_IDS, VIEW_NAMES, type ViewId } from "./preview_png";
import type { ImageSourceMode } from "./slice_webgpu";
import {
  BACKGROUND_J_SNAP_DISTANCE,
  J_REFERENCE_WHITE,
  J_SNAP_DISTANCE,
  PATCH_ENTRY_RADIUS,
  TRACK_SENSITIVITY,
  canvasPoint,
  clamp01,
  nearestJSnapTarget,
  nearestBackgroundJSnapTarget,
  nearestSnapTarget,
  trackMotionAcceleration,
  trackpadDelta,
  trackMotionVelocity,
  trackwheelDelta,
  projectSnapCode,
  slicePoint,
  covarianceEllipse,
  ellipsePoint,
} from "./picker_math";

const FULL = 512;
const PREVIEW = 64;
const INITIAL_J = 0.3;
const PATCH_NAMES = [
  "Dark Skin",
  "Light Skin",
  "Blue Sky",
  "Foliage",
  "Blue Flower",
  "Bluish Green",
  "Orange",
  "Purplish Blue",
  "Moderate Red",
  "Purple",
  "Yellow Green",
  "Orange Yellow",
  "Blue",
  "Green",
  "Red",
  "Yellow",
  "Magenta",
  "Cyan",
] as const;

type Code = { j: number; x: number; y: number };
type Patch = {
  name: string;
  j: number;
  x: number;
  y: number;
  color: [number, number, number];
  available: boolean;
};
type SnapTarget =
  | { kind: "neutral"; x: number; y: number }
  | { kind: "patch"; index: number; x: number; y: number; j: number }
  | { kind: "average"; x: number; y: number };
type RenderResponse = {
  kind: "slice";
  id: number;
  profile: number;
  width: number;
  height: number;
  j: number;
  renderer: "webgpu" | "wasm";
  fullRec2020: boolean;
  png: Uint8Array<ArrayBuffer>;
};
type EvaluateResponse = {
  kind: "evaluate";
  id: number;
  profile: number;
  j: number;
  fittedRadiusX: number;
  fittedRadiusY: number;
  backgroundJ: number;
  fullRec2020: boolean;
  values: Float64Array;
};
type PreviewResponse = Omit<EvaluateResponse, "kind" | "values"> & {
  kind: "preview"; valid: boolean; png: Uint8Array<ArrayBuffer>;
};
type ColorCheckerResponse = {
  kind: "colorchecker";
  id: number;
  profile: number;
  points: Float64Array;
  png: Uint8Array<ArrayBuffer>;
};
type SetResponse = {
  kind: "set";
  id: number;
  profile: number;
  values: Float64Array;
};
type WorkerError = {
  kind: "worker-error";
  id: number;
  operation: string;
  profile?: number;
};

const $ = <T extends Element>(selector: string) =>
  document.querySelector<T>(selector)!;
const checkerboard = $("#gamut-checkerboard") as HTMLCanvasElement;
const appShell = $(".app-shell") as HTMLElement;
const gamutSliceImage = $("#gamut-slice") as HTMLImageElement;
const gamutColorcheckerImage = $("#gamut-colorchecker") as HTMLImageElement;
const indicators = $("#gamut-indicators") as HTMLCanvasElement;
const colorTrackpad = $(".color-trackpad") as HTMLElement;
const sliceOptions = $(".slice-options") as HTMLElement;
const plotStatus = $("#plot-status") as HTMLElement;
const viewMenu = $("#view-menu") as HTMLElement;
const viewButtons = Array.from(viewMenu.querySelectorAll<HTMLButtonElement>("[data-view]"));
const previewStatus = $("#preview-status") as HTMLElement;
const jTrackwheel = $("#j-trackwheel") as HTMLElement;
const jTrackwheelBody = $(".j-trackwheel-body") as HTMLElement;
const jTrackwheelTexture = $(".j-trackwheel-texture") as HTMLElement;
const jReferenceTick = $("#j-reference-tick") as HTMLElement;
const jCurrentIndicator = $("#j-current-indicator") as HTMLElement;
const jNumber = $("#j-number") as HTMLInputElement;
const xNumber = $("#x-number") as HTMLInputElement;
const yNumber = $("#y-number") as HTMLInputElement;
const sliceCoordinateInputs = $(".slice-coordinate-inputs") as HTMLElement;
const backgroundStick = $("#background-stick") as HTMLElement;
const preview = $("#preview") as HTMLButtonElement;
let previewImage = $("#preview-image") as HTMLImageElement;
const linearValue = $("#linear-value") as HTMLElement;
const encodedLabel = $("#encoded-label") as HTMLElement;
const encodedValue = $("#encoded-value") as HTMLInputElement;
const copyValue = $("#copy-value") as HTMLButtonElement;
const setValue = $("#set-value") as HTMLButtonElement;
const colorName = $("#color-name") as HTMLElement;
const jStick = $("#j-stick") as HTMLElement;
const jImageStick = $("#j-image-stick") as HTMLElement;
const imageFileInput = $("#image-file-input") as HTMLInputElement;
const imagePanel = $("#image-panel") as HTMLElement;
const imagePreview = $("#image-preview") as HTMLImageElement;
const imageViewport = $("#image-viewport") as HTMLElement;
const imageOverlay = $("#image-overlay") as HTMLCanvasElement;
const imageLoupe = $("#image-loupe") as HTMLImageElement;
const imageStatus = $("#image-status") as HTMLElement;
const imageTransformBanner = $("#image-transform-banner") as HTMLElement;
const imageGamutSelect = $("#image-gamut") as HTMLSelectElement;
const imageTransferSelect = $("#image-transfer") as HTMLSelectElement;
const imageReferenceWhite203Control = $("#image-reference-white-encoded-as-linear-203") as HTMLInputElement;
const imageReferenceWhiteHelp = $("#image-units-help") as HTMLElement;
const imageUnitsField = $(".image-units-field") as HTMLElement;
const imageGamutField = $("#image-gamut-field") as HTMLElement;
const imageTransferField = $("#image-transfer-field") as HTMLElement;
const imageStats = $("#image-stats") as HTMLElement;
const imageLoadButton = $("#image-load") as HTMLButtonElement;
const imageOptionsButton = $("#image-options") as HTMLButtonElement;
const imageOptionsDialog = $("#image-options-dialog") as HTMLDialogElement;
const imageOptionsClose = $("#image-options-close") as HTMLButtonElement;
const imageInterpretationWarning = $("#image-interpretation-warning") as HTMLElement;
const imageZoomButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-image-zoom]"));
const fullRec2020Toggle = $("#full-rec2020-toggle") as HTMLButtonElement;

// Keep toggle gestures from reaching the gamut viewport's placement/drag
// handlers while preserving normal button click and keyboard behavior.
sliceOptions.addEventListener("pointerdown", event => event.stopPropagation());
sliceOptions.addEventListener("pointermove", event => event.stopPropagation());
sliceCoordinateInputs.addEventListener("pointerdown", event => event.stopPropagation());
sliceCoordinateInputs.addEventListener("pointermove", event => event.stopPropagation());

function canvasContext(target: HTMLCanvasElement): CanvasRenderingContext2D {
  try {
    const p3 = target.getContext("2d", { colorSpace: "display-p3" });
    if (p3) return p3;
  } catch {
    // Fall through for browsers without canvas color-space selection.
  }
  const context = target.getContext("2d");
  if (!context) throw new Error("A 2D canvas context is required.");
  return context;
}

const checkerboardContext = canvasContext(checkerboard);
const indicatorContext = canvasContext(indicators);
// Keep this transparent overlay in the same wide-gamut canvas space as the
// gamut indicators. Safari can otherwise flatten an HDR image stack when an
// sRGB canvas is composited over its valid PQ image.
const imageOverlayContext = canvasContext(imageOverlay);
let sliceSize = FULL;

let imageKey = "";
let renderId = 0;
let evaluationId = 0;
let checkerId = 0;
let setId = 0;
let currentRender:
  | {
      id: number;
      key: string;
      profile: ViewId;
      j: number;
      width: number;
      height: number;
      fullRec2020: boolean;
    }
  | undefined;
let currentPatches: Patch[] = [];
let activePatch: number | null = null;
let activeTarget: SnapTarget | null = null;
let imageAverage: Code | null = null;
type ImageAnalysis = {
  x: number;
  y: number;
  sampleCount: number;
  rejectedCount: number;
  mean: Code;
  meanAcescg: [number, number, number];
  ellipse: ReturnType<typeof covarianceEllipse>;
  loupe?: { x: number; y: number; width: number; height: number };
};
let imageAnalysis: ImageAnalysis | null = null;
let activeAxis: "j" | "xy" | null = null;
let code: Code = { j: INITIAL_J, x: 0.38, y: 0.65 };
let realCode: Code = { ...code };
let trackpadTouchPointerId: number | null = null;
let trackpadTouchLastX = 0;
let trackpadTouchLastY = 0;
let trackpadTouchLastTime = 0;
let trackpadTouchVelocityX = 0;
let trackpadTouchVelocityY = 0;
let jTrackwheelPointerId: number | null = null;
let jTrackwheelSurface: "trackwheel" | "page" | null = null;
let jTrackwheelLastX = 0;
let jTrackwheelLastY = 0;
let jTrackwheelLastTime = 0;
let jTrackwheelVelocityX = 0;
let jTrackwheelVelocityY = 0;
let jTrackwheelTextureOffset = 0;
let jTrackwheelVisualHeight = 0;
let jTrackwheelSnapHeld = false;
let jTrackwheelDeferredDeltaY = 0;
let jTrackwheelDeferredJ = 0;
let jTrackwheelDeferredAcceleration = 1;
let jTrackwheelSnapTargetValue: number | null = null;
let trackpadTrackingActive = false;
let selectedView: ViewId = 0;
let fullRec2020 = false;
let encodedReadoutMode: "ap1" | "jxy" = "ap1";
let lastValidEncodedAp1 = "000000";
let lastValidEncodedJxy = "000000";
let lastEvaluationValid = false;
let confirmedSliceRenderer: "unknown" | "webgpu" | "wasm" = "unknown";
let previewUrl: string | undefined;
let sliceUrl: string | undefined;
let colorcheckerUrl: string | undefined;
let pageClosed = false;
let backgroundJ = 0.15;
let realBackgroundJ = 0.15;
let backgroundSnap: ReturnType<typeof backgroundSnapTarget> = null;
let backgroundTracking = false;
let latestValueResponseId = 0;
let latestPreviewResponseId = 0;
let previewDecodeActive = false;
let queuedPreview: PreviewResponse | undefined;

const sliceWorker = new Worker(new URL("./render_worker.ts", import.meta.url), { type: "module" });
const evaluatorWorker = new Worker(new URL("./render_worker.ts", import.meta.url), { type: "module" });
const checkerWorker = new Worker(new URL("./render_worker.ts", import.meta.url), { type: "module" });
type ImageWorkerRequest = {
  kind: "inspect" | "prepare" | "sample" | "preview";
  id: number;
  generation: number;
  token?: number;
  appearanceToken?: number;
  format: string;
  bytes?: ArrayBuffer;
  gamut?: string | null;
  transfer?: string | null;
  view?: ViewId;
  referenceWhiteEncodedAsLinear203?: boolean;
  x?: number;
  y?: number;
  radius?: number;
};
type ImageWorkerMessage =
  | { kind: "inspect"; id: number; generation: number; summary: any }
  | { kind: "ready"; id: number; generation: number; width: number; height: number; previewWidth: number; previewHeight: number; summary: any; png: ArrayBuffer; view: ViewId; sourceMode: ImageSourceMode; referenceWhiteEncodedAsLinear203: boolean; renderer: "webgpu" | "wasm" }
  | { kind: "preview"; id: number; generation: number; appearanceToken: number; width: number; height: number; previewWidth: number; previewHeight: number; png: ArrayBuffer; view: ViewId; sourceMode: ImageSourceMode; referenceWhiteEncodedAsLinear203: boolean; renderer: "webgpu" | "wasm" }
  | { kind: "sample"; id: number; generation: number; token: number; x: number; y: number; minX: number; minY: number; width: number; height: number; loupe: ArrayBuffer; points: Array<{ j: number; x: number; y: number }>; mean: Code; meanAcescg: [number, number, number]; meanCode: Float64Array; rejected: number; total: number; view: ViewId; sourceMode: ImageSourceMode; referenceWhiteEncodedAsLinear203: boolean }
  | { kind: "error"; id: number; generation?: number; message: string };
const imageWorker = new Worker(new URL("./image_locator_worker.ts", import.meta.url), { type: "module" });
let imageRequestId = 0;
let imageGeneration = 0;
let imageFile: File | undefined;
let imageFormat = "";
let imageSummary: any;
let imagePrepared = false;
let imageSourceMode: ImageSourceMode = "display-linear-xyz-d65";
let referenceWhiteEncodedAsLinear203 = false;
let imageUnitsUserChanged = false;
let imageWidth = 0;
let imageHeight = 0;
let imagePreviewUrl: string | undefined;
let imageLoupeUrl: string | undefined;
let imagePointerX = 0;
let imagePointerY = 0;
let imagePointerSet = false;
let imageTrackingActive = false;
let imageTouchPointerId: number | null = null;
let imageTouchLastX = 0;
let imageTouchLastY = 0;
let imageTouchLastTime = 0;
let imageTouchVelocityX = 0;
let imageTouchVelocityY = 0;
let imageSampleToken = 0;
let latestImageSampleToken = 0;
let imageZoom = 2;
let imagePointerLockActive = false;
let imagePointerLockFallback = false;
let imageOptionsFocusPending = false;
let imageAppearanceToken = 0;
let pendingImageAppearance:
  | { token: number; view: ViewId; sourceMode: ImageSourceMode; referenceWhiteEncodedAsLinear203: boolean; previewReady: boolean; sampleToken?: number; loupeReady: boolean }
  | undefined;

function finite(value: number, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}
function currentCode(): Code {
  return { ...code };
}
function currentRealCode(): Code {
  return { ...realCode };
}
function currentProfile(): ViewId { return selectedView; }
function requestedSliceSize() {
  return activeAxis === "j" && confirmedSliceRenderer === "wasm"
    ? PREVIEW
    : FULL;
}
function stateKey(code = currentCode(), size = requestedSliceSize()) {
  return `${selectedView}:${Number(fullRec2020)}:${size}:${code.j.toFixed(12)}`;
}
function formatRgb(values: ArrayLike<number>) {
  return `(${Array.from(values, (value) => (Number.isFinite(value) ? value.toFixed(4) : "nan")).join(", ")})`;
}
function encodeHex(values: ArrayLike<number>) {
  return Array.from(values, (value) =>
    Math.round(clamp01(Number(value)) * 255)
      .toString(16)
      .padStart(2, "0"),
  )
    .join("")
    .toUpperCase();
}
function encodeSrgbChannel(value: number) {
  if (!Number.isFinite(value)) return 0;
  const clamped = clamp01(value);
  return clamped <= 0.0031308
    ? 12.92 * clamped
    : 1.055 * clamped ** (1 / 2.4) - 0.055;
}
function decodeSrgbChannel(value: number) {
  if (!Number.isFinite(value)) return 0;
  const clamped = clamp01(value);
  return clamped <= 0.04045
    ? clamped / 12.92
    : ((clamped + 0.055) / 1.055) ** 2.4;
}
function encodeJxyHex(values: ArrayLike<number>) {
  return encodeHex(Array.from(values, encodeSrgbChannel));
}
function decodeHex(value: string): [number, number, number] | undefined {
  const match = /^([0-9a-f]{6})$/i.exec(value.trim());
  if (!match) return undefined;
  return [
    parseInt(match[1].slice(0, 2), 16) / 255,
    parseInt(match[1].slice(2, 4), 16) / 255,
    parseInt(match[1].slice(4, 6), 16) / 255,
  ];
}
function decodeJxyHex(value: string) {
  const encoded = decodeHex(value);
  return encoded?.map(decodeSrgbChannel) as [number, number, number] | undefined;
}
function renderEncodedLabel() {
  const source = encodedReadoutMode === "ap1" ? "AP1" : "J′x′y′";
  const target = encodedReadoutMode === "ap1" ? "J′x′y′" : "AP1";
  const targetMode = encodedReadoutMode === "ap1" ? "jxy" : "ap1";
  const targetId = encodedReadoutMode === "ap1" ? "encoded-label-jxy" : "encoded-label-ap1";
  const switchButton = document.createElement("button");
  switchButton.type = "button";
  switchButton.id = targetId;
  switchButton.className = "encoded-label-link";
  switchButton.dataset.encodedMode = targetMode;
  switchButton.textContent = target;
  switchButton.setAttribute("aria-label", `Show sRGB Encoded ${target}`);
  encodedLabel.replaceChildren(
    document.createTextNode("sRGB Encoded "),
    document.createTextNode(source),
    document.createTextNode(" (→ "),
    switchButton,
    document.createTextNode(")"),
  );
}
function currentEncodedHex() {
  return encodedReadoutMode === "ap1" ? lastValidEncodedAp1 : lastValidEncodedJxy;
}
function updateEncodedReadout(values?: ArrayLike<number>, valid = false) {
  if (valid && values) {
    lastValidEncodedAp1 = encodeHex(Array.from(values).slice(10, 13));
    lastValidEncodedJxy = encodeJxyHex(Array.from(values).slice(20, 23));
  }
  if (document.activeElement !== encodedValue) encodedValue.value = currentEncodedHex();
  const modeName = encodedReadoutMode === "ap1" ? "AP1" : "normalized J′x′y′";
  encodedValue.title = valid
    ? `sRGB-transfer encoded scene-linear ${modeName}`
    : `Last valid encoded ${modeName}; the current pick is unavailable`;
  encodedValue.setAttribute("aria-label", `Six sRGB Encoded ${encodedReadoutMode === "ap1" ? "ACEScg AP1" : "J′x′y′"} hexadecimal digits`);
}
function currentBackgroundJ() {
  return backgroundJ;
}
function backgroundSnapTarget() {
  return nearestBackgroundJSnapTarget(
    realBackgroundJ,
    code.j,
    J_REFERENCE_WHITE,
    BACKGROUND_J_SNAP_DISTANCE,
  );
}
function updateBackground(projectSnap = false, clearSnap = false) {
  if (clearSnap) backgroundSnap = null;
  if (projectSnap) {
    backgroundSnap = backgroundSnapTarget();
    backgroundJ = backgroundSnap ? backgroundSnap.value : realBackgroundJ;
  }
  backgroundStick.hidden = false;
  backgroundStick.style.bottom = `${clamp01(backgroundJ) * 100}%`;
  backgroundStick.title = `Background J′ ${backgroundJ.toFixed(3)}`;
  backgroundStick.dataset.realValue = realBackgroundJ.toFixed(6);
  backgroundStick.dataset.displayValue = backgroundJ.toFixed(6);
  backgroundStick.dataset.snapTarget = backgroundSnap?.kind ?? "none";
  backgroundStick.dataset.snapValue = backgroundSnap ? backgroundSnap.value.toFixed(6) : "";
}
function updateJTrackwheelVisual() {
  const height = jTrackwheel.getBoundingClientRect().height || 1;
  if (jTrackwheelVisualHeight > 0 && Math.abs(height - jTrackwheelVisualHeight) > 0.01)
    jTrackwheelTextureOffset *= height / jTrackwheelVisualHeight;
  jTrackwheelVisualHeight = height;
  // The trackwheel is a free physical surface. Its texture phase records raw
  // pointer travel and is deliberately independent of accelerated/snapped J'
  // except while a captured snap temporarily freezes the visible phase.
  // Overscan the trackwheel texture by half a tick period so the repeating pattern is
  // continuous through both clipped trackwheel edges instead of exposing a
  // partial end mark.  The phase remains the raw one-pixel pointer travel.
  jTrackwheelTexture.style.backgroundPositionY = `${jTrackwheelTextureOffset + 4}px`;
  jTrackwheel.dataset.realValue = realCode.j.toFixed(6);
  // Keep enough precision for resize reconstruction and diagnostics; the
  // texture itself remains sub-pixel precise in CSS.
  jTrackwheel.dataset.visualOffset = jTrackwheelTextureOffset.toFixed(9);
}
function updatePlotLabel() {
  const interaction = trackpadTrackingActive
    ? " mouse tracking active;"
    : trackpadTouchPointerId !== null
      ? " touch or pen gesture active;"
      : ";";
  colorTrackpad.setAttribute(
    "aria-label",
    `Color trackpad${interaction} x’ ${code.x.toFixed(6)}, y’ ${code.y.toFixed(6)}`,
  );
}
function setDisplayedCode(next: Code) {
  code = {
    j: clamp01(next.j),
    x: clamp01(next.x),
    y: clamp01(next.y),
  };
  updatePlotLabel();
  jTrackwheel.setAttribute("aria-valuenow", code.j.toString());
  jTrackwheel.setAttribute("aria-valuetext", code.j.toFixed(3));
  jTrackwheel.dataset.value = code.j.toFixed(6);
  if (document.activeElement !== jNumber) jNumber.value = code.j.toFixed(3);
  if (document.activeElement !== xNumber) xNumber.value = code.x.toFixed(3);
  if (document.activeElement !== yNumber) yNumber.value = code.y.toFixed(3);
  jCurrentIndicator.style.bottom = `${code.j * 100}%`;
  colorTrackpad.dataset.realJ = realCode.j.toFixed(6);
  colorTrackpad.dataset.realX = realCode.x.toFixed(6);
  colorTrackpad.dataset.realY = realCode.y.toFixed(6);
  colorTrackpad.dataset.displayJ = code.j.toFixed(6);
  colorTrackpad.dataset.displayX = code.x.toFixed(6);
  colorTrackpad.dataset.displayY = code.y.toFixed(6);
  // Foreground changes must never re-project a retained Background snap.
  updateBackground(false, true);
  updateJTrackwheelVisual();
  drawIndicators();
}
function setRealCode(axis: keyof Code, value: number) {
  const target = clamp01(value);
  realCode[axis] = target;
}
function setAllCode(next: Code) {
  realCode = {
    j: clamp01(next.j),
    x: clamp01(next.x),
    y: clamp01(next.y),
  };
  setDisplayedCode(realCode);
}
function paintCheckerboard() {
  checkerboardContext.clearRect(0, 0, checkerboard.width, checkerboard.height);
  checkerboardContext.fillStyle = "#171a20";
  checkerboardContext.fillRect(0, 0, checkerboard.width, checkerboard.height);
  const tile = 16;
  for (let y = 0; y < checkerboard.height; y += tile) {
    for (let x = 0; x < checkerboard.width; x += tile) {
      checkerboardContext.fillStyle = ((x / tile + y / tile) & 1) === 0 ? "#1b1f26" : "#11151b";
      checkerboardContext.fillRect(x, y, tile, tile);
    }
  }
}
function drawCircle(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  stroke: string,
  lineWidth: number,
) {
  context.strokeStyle = stroke;
  context.lineWidth = lineWidth;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.stroke();
}
function drawIndicators() {
  const scale = indicators.width;
  const point = (x: number, y: number) => canvasPoint(x, y, scale);
  indicatorContext.clearRect(0, 0, indicators.width, indicators.height);
  indicatorContext.save();
  const [cx, cy] = point(code.x, code.y);
  drawCircle(indicatorContext, cx, cy, 7, "rgb(255 255 255 / 65%)", 2);
  const [nx, ny] = point(0.5, 0.5);
  indicatorContext.strokeStyle = "rgb(255 255 255 / 25%)";
  indicatorContext.lineWidth = 2;
  indicatorContext.beginPath();
  indicatorContext.moveTo(nx - 8, ny);
  indicatorContext.lineTo(nx + 8, ny);
  indicatorContext.moveTo(nx, ny - 8);
  indicatorContext.lineTo(nx, ny + 8);
  indicatorContext.stroke();
  drawCircle(indicatorContext, nx, ny, PATCH_ENTRY_RADIUS * scale, "rgb(245 193 93 / 30%)", 1.5);
  currentPatches.forEach((patch, patchIndex) => {
    const [px, py] = point(patch.x, patch.y);
    const active = activeTarget?.kind === "patch" && activeTarget.index === patchIndex;
    drawCircle(indicatorContext, px, py, PATCH_ENTRY_RADIUS * scale,
      active ? "rgb(190 220 255 / 78%)" : "rgb(190 220 255 / 26%)", active ? 2 : 1.5);
  });
  if (imageAnalysis?.ellipse) {
    indicatorContext.strokeStyle = "rgb(255 203 93 / 78%)";
    indicatorContext.lineWidth = 2;
    indicatorContext.beginPath();
    for (let step = 0; step <= 96; step += 1) {
      const ellipsePointValue = ellipsePoint(imageAnalysis.ellipse, step / 96 * Math.PI * 2);
      const [ex, ey] = point(ellipsePointValue.x, ellipsePointValue.y);
      if (step === 0) indicatorContext.moveTo(ex, ey);
      else indicatorContext.lineTo(ex, ey);
    }
    indicatorContext.closePath();
    indicatorContext.stroke();
  }
  if (imageAverage) {
    const [ax, ay] = point(imageAverage.x, imageAverage.y);
    drawCircle(indicatorContext, ax, ay, 5, "rgb(255 203 93 / 92%)", 2);
    indicatorContext.fillStyle = "rgb(255 203 93 / 92%)";
    indicatorContext.beginPath();
    indicatorContext.arc(ax, ay, 2, 0, Math.PI * 2);
    indicatorContext.fill();
  }
  if (activeTarget?.kind === "neutral")
    drawCircle(indicatorContext, nx, ny, PATCH_ENTRY_RADIUS * scale, "rgb(245 193 93 / 78%)", 2);
  if (activeTarget?.kind === "average" && imageAverage) {
    const [ax, ay] = point(imageAverage.x, imageAverage.y);
    drawCircle(indicatorContext, ax, ay, PATCH_ENTRY_RADIUS * scale, "rgb(255 203 93 / 96%)", 2);
  }
  colorTrackpad.dataset.indicatorPatchCount = String(currentPatches.length);
  indicatorContext.restore();
}
function invalidatePendingSet() {
  // A hex import must not overwrite newer pointer or Background input.
  // Advancing the request token marks an eventual worker response as stale.
  setId += 1;
}
function updatePatchLocators() {
  const patch = activePatch === null ? undefined : currentPatches[activePatch];
  jStick.hidden = patch === undefined;
  if (patch) {
    jStick.style.bottom = `${patch.j * 100}%`;
  }
  jImageStick.hidden = imageAverage === null;
  if (imageAverage) jImageStick.style.bottom = `${imageAverage.j * 100}%`;
  jCurrentIndicator.style.bottom = `${code.j * 100}%`;
  const pickedColor = !patch && activeTarget?.kind === "average";
  colorName.classList.toggle("is-hidden", !patch && !pickedColor);
  colorName.classList.toggle("picked-color", pickedColor);
  colorName.setAttribute("aria-hidden", String(!patch && !pickedColor));
  colorName.textContent = patch?.name ?? (pickedColor ? "Avg. Sampled Color" : "");
}
function updatePatchCandidate(applySnap = true, allowJSnap = false) {
  const real = currentRealCode();
  const patchPoints = currentPatches.map((patch) => ({ x: patch.x, y: patch.y }));
  const candidate = nearestSnapTarget(real.x, real.y, patchPoints, { x: 0.5, y: 0.5 }, imageAverage ? { x: imageAverage.x, y: imageAverage.y } : undefined);
  if (candidate?.kind === "neutral") {
    activeTarget = candidate;
    activePatch = null;
  } else if (candidate?.kind === "average") {
    activePatch = null;
    activeTarget = { kind: "average", x: candidate.x, y: candidate.y };
  } else if (candidate?.kind === "patch") {
    const patch = currentPatches[candidate.index];
    activePatch = candidate.index;
    activeTarget = {
      kind: "patch",
      index: candidate.index,
      x: patch.x,
      y: patch.y,
      j: patch.j,
    };
  } else {
    activePatch = null;
    activeTarget = null;
  }
  colorTrackpad.dataset.snapTarget =
    activeTarget?.kind === "patch"
      ? `patch:${activeTarget.index}`
      : activeTarget?.kind ?? "none";
  const jTarget = nearestJSnapTarget(
    real.j,
    activeTarget?.kind === "patch" ? activeTarget.j : undefined,
    J_REFERENCE_WHITE,
    J_SNAP_DISTANCE,
    imageAverage?.j,
  );
  colorTrackpad.dataset.jSnapTarget = jTarget?.kind ?? "none";
  colorTrackpad.dataset.colorcheckerRingCount = String(currentPatches.length);
  updatePatchLocators();
  let jSnapValue: number | null = null;
  if (applySnap) {
    const projected = projectSnapCode(
      real,
      activeTarget,
      activeTarget?.kind === "patch" ? activeTarget.j : undefined,
      activeAxis,
      code,
      imageAverage?.j,
      allowJSnap,
    );
    if (allowJSnap && jTarget && Math.abs(projected.j - real.j) > 1e-12)
      jSnapValue = jTarget.value;
    setDisplayedCode(projected);
  }
  return jSnapValue;
}
function displayValues(values: Float64Array) {
  const valid = values[0] > 0.5;
  lastEvaluationValid = valid;
  linearValue.textContent = valid ? formatRgb(values.slice(1, 4)) : "Unavailable";
  updateEncodedReadout(values, valid);
  preview.classList.toggle("preview-unavailable", !valid);
  // Keep the last decoded PNG visible while the replacement is encoded and
  // decoded. The invalid-state diagnostic cross is embedded in that PNG.
  preview.dataset.previewReady = "pending";
  preview.dataset.valid = String(valid);
  preview.setAttribute("aria-label", `${valid ? "Picked color" : "Out-of-gamut color"}; ${VIEW_NAMES[selectedView]}. Choose view transform`);
  updateBackground();
}
function evaluationIsCurrent(response: EvaluateResponse | PreviewResponse) {
  return !pageClosed && response.id === evaluationId && response.profile === selectedView &&
    response.fullRec2020 === fullRec2020 &&
    response.j === code.j && response.fittedRadiusX === code.x && response.fittedRadiusY === code.y &&
    Math.abs(response.backgroundJ - currentBackgroundJ()) < 1e-12;
}
function responseBelongsToCurrentView(response: EvaluateResponse | PreviewResponse) {
  return !pageClosed && response.profile === selectedView &&
    response.fullRec2020 === fullRec2020;
}
function responseMayAdvanceDuringGesture(response: EvaluateResponse | PreviewResponse) {
  if (jTrackwheelSnapHeld) return false;
  return responseBelongsToCurrentView(response) &&
    (activeAxis !== null || backgroundTracking || evaluationIsCurrent(response));
}
async function displayPreview(response: PreviewResponse) {
  if (!responseMayAdvanceDuringGesture(response)) return;
  previewDecodeActive = true;
  const url = URL.createObjectURL(new Blob([response.png], { type: "image/png" }));
  const nextImage = new Image(256, 256);
  nextImage.id = "preview-image";
  nextImage.alt = `Picked color and background — ${VIEW_NAMES[response.profile as ViewId]}`;
  nextImage.src = url;
  try {
    await nextImage.decode();
    if (!responseMayAdvanceDuringGesture(response) || response.id !== latestPreviewResponseId) {
      URL.revokeObjectURL(url);
      return;
    }
    const previousUrl = previewUrl;
    previewImage.replaceWith(nextImage);
    previewImage = nextImage;
    previewUrl = url;
    preview.dataset.view = String(response.profile);
    preview.dataset.imageGeneration = String(response.id);
    preview.dataset.imageCode = JSON.stringify([response.j, response.fittedRadiusX, response.fittedRadiusY, response.backgroundJ]);
    preview.classList.toggle("preview-unavailable", !response.valid);
    preview.dataset.valid = String(response.valid);
    preview.dataset.previewReady = response.valid ? "valid" : "invalid";
    previewStatus.hidden = true;
    if (previousUrl) URL.revokeObjectURL(previousUrl);
  } catch {
    URL.revokeObjectURL(url);
    if (responseMayAdvanceDuringGesture(response)) {
      previewStatus.textContent = "Preview could not be decoded; previous image retained.";
      previewStatus.hidden = false;
    }
  } finally {
    previewDecodeActive = false;
    const next = queuedPreview;
    queuedPreview = undefined;
    if (next) queuePreview(next);
  }
}
function queuePreview(response: PreviewResponse) {
  if (!responseMayAdvanceDuringGesture(response)) return;
  if (response.id < latestPreviewResponseId) return;
  latestPreviewResponseId = response.id;
  if (previewDecodeActive) {
    if (!queuedPreview || response.id > queuedPreview.id) queuedPreview = response;
    return;
  }
  void displayPreview(response);
}
async function displaySlice(response: RenderResponse, key: string) {
  if (!currentRender || currentRender.id !== response.id) return;
  if (jTrackwheelSnapHeld) {
    // A render may finish while the J' snap hold deliberately freezes the
    // visible slice. Release ownership so the first post-hold schedule can
    // request the current J' again.
    currentRender = undefined;
    colorTrackpad.setAttribute("aria-busy", "true");
    return;
  }
  const url = URL.createObjectURL(new Blob([response.png], { type: "image/png" }));
  const nextImage = new Image(response.width, response.height);
  nextImage.alt = "J’, x’, and y’ gamut slice";
  nextImage.src = url;
  try {
    await nextImage.decode();
    if (!currentRender || currentRender.id !== response.id) {
      URL.revokeObjectURL(url);
      return;
    }
    if (jTrackwheelSnapHeld) {
      // The hold may have started while the replacement image was decoding.
      // Keep the displayed PNG visible and release ownership for the next schedule.
      currentRender = undefined;
      colorTrackpad.setAttribute("aria-busy", "true");
      URL.revokeObjectURL(url);
      return;
    }
    const mayAdvanceGesture = activeAxis === "j";
    const exactState = stateKey(currentCode(), response.width) === key;
    const settledSize = requestedSliceSize();
    if (pageClosed || response.profile !== selectedView || response.fullRec2020 !== fullRec2020 ||
      (!mayAdvanceGesture && (!exactState || response.width !== settledSize))) {
      URL.revokeObjectURL(url);
      currentRender = undefined;
      if (!pageClosed) requestRender();
      return;
    }
    const previousUrl = sliceUrl;
    gamutSliceImage.src = url;
    gamutSliceImage.dataset.renderer = response.renderer;
    gamutSliceImage.dataset.view = String(response.profile);
    gamutSliceImage.dataset.fullRec2020 = String(response.fullRec2020);
    gamutSliceImage.dataset.imageGeneration = String(response.id);
    gamutSliceImage.dataset.imageCode = JSON.stringify([response.j]);
    if (response.renderer === "webgpu") confirmedSliceRenderer = "webgpu";
    else if (confirmedSliceRenderer === "unknown") confirmedSliceRenderer = "wasm";
    colorTrackpad.dataset.sliceRenderer = confirmedSliceRenderer;
    sliceUrl = url;
    sliceSize = response.width;
    imageKey = key;
    currentRender = undefined;
    colorTrackpad.setAttribute("aria-busy", "false");
    plotStatus.hidden = true;
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    requestRender();
  } catch {
    URL.revokeObjectURL(url);
    if (currentRender?.id === response.id) {
      currentRender = undefined;
      imageKey = "";
      colorTrackpad.setAttribute("aria-busy", "false");
      plotStatus.textContent = "Slice image could not be decoded; previous image retained.";
      plotStatus.hidden = false;
      if (!pageClosed) requestRender();
    }
  }
}
function requestEvaluate() {
  const code = currentCode();
  const id = ++evaluationId;
  evaluatorWorker.postMessage({
    kind: "evaluate",
    id,
    profile: currentProfile(),
    j: code.j,
    fittedRadiusX: code.x,
    fittedRadiusY: code.y,
    backgroundJ: currentBackgroundJ(),
    fullRec2020,
  });
}
function requestRender() {
  const size = requestedSliceSize();
  const code = currentCode();
  const key = stateKey(code, size);
  if (imageKey === key && sliceSize === size) {
    return;
  }
  colorTrackpad.setAttribute("aria-busy", "true");
  // Keep one current-key slice frame in flight. If the desired key changed,
  // release stale ownership before posting the replacement; otherwise a
  // stale response discarded during a gesture could block the latest request.
  if (currentRender) {
    if (currentRender.key === key && currentRender.profile === selectedView &&
        currentRender.width === size && currentRender.fullRec2020 === fullRec2020)
      return;
    // During a live J' gesture, let the worker finish one frame and let
    // displaySlice() enqueue the newest key afterward. Cancelling every
    // pointer sample starves the worker under rapid movement.
    if (activeAxis === "j") return;
    sliceWorker.postMessage({ kind: "cancel-render", id: currentRender.id });
    currentRender = undefined;
  }
  const id = ++renderId;
  currentRender = { id, key, profile: selectedView, j: code.j, width: size, height: size, fullRec2020 };
  sliceWorker.postMessage({
    kind: "render",
    id,
    profile: currentProfile(),
    j: code.j,
    width: size,
    height: size,
    fullRec2020,
  });
}
function schedule() {
  // Pointer events can arrive faster than animation frames. The workers
  // already coalesce and cancel stale requests, so submit the newest state
  // immediately rather than waiting for rAF; this keeps J'/XY gestures live
  // even during fast drags while retaining bounded worker work.
  requestEvaluate();
  requestRender();
}
function parsePatches(values: Float64Array) {
  if (values.length !== PATCH_NAMES.length * 7) return;
  const hadPatches = currentPatches.length > 0;
  const patches: Patch[] = [];
  for (let i = 0; i < PATCH_NAMES.length; i++) {
    const o = i * 7;
    patches.push({
      name: PATCH_NAMES[i],
      j: clamp01(values[o]),
      x: clamp01(values[o + 1]),
      y: clamp01(values[o + 2]),
      color: [values[o + 3], values[o + 4], values[o + 5]],
      available: values[o + 6] > 0.5,
    });
  }
  currentPatches = patches;
  activePatch = null;
  activeTarget = null;
  if (hadPatches) {
    updatePatchCandidate(false);
  } else {
    colorTrackpad.dataset.snapTarget = "none";
    colorTrackpad.dataset.jSnapTarget = "none";
  }
  colorTrackpad.dataset.colorcheckerRingCount = String(currentPatches.length);
  updatePatchLocators();
  // The initial canvas was painted before the asynchronous ColorChecker
  // response arrived.  Repaint now so dots and their dim rings are visible
  // without requiring a picker gesture.
  drawIndicators();
}
function requestPatches(reset = false) {
  if (reset) {
    currentPatches = [];
    activePatch = null;
    activeTarget = null;
    colorTrackpad.dataset.snapTarget = "none";
    colorTrackpad.dataset.jSnapTarget = "none";
    colorTrackpad.dataset.colorcheckerRingCount = "0";
    updatePatchLocators();
  }
  const id = ++checkerId;
  checkerWorker.postMessage({
    kind: "colorchecker",
    id,
    profile: selectedView,
  });
}

async function displayColorchecker(response: ColorCheckerResponse) {
  if (response.id !== checkerId || response.profile !== selectedView) return;
  const url = URL.createObjectURL(new Blob([response.png], { type: "image/png" }));
  const decoded = new Image(1024, 1024);
  decoded.src = url;
  try {
    await decoded.decode();
    if (response.id !== checkerId || response.profile !== selectedView) {
      URL.revokeObjectURL(url);
      return;
    }
    const previous = colorcheckerUrl;
    gamutColorcheckerImage.src = url;
    gamutColorcheckerImage.dataset.view = String(response.profile);
    colorcheckerUrl = url;
    if (previous) URL.revokeObjectURL(previous);
  } catch {
    URL.revokeObjectURL(url);
  }
}
function chooseView(view: ViewId) {
  cancelTrackpadTracking();
  finishJTrackwheelInteraction(false);
  finishPreviewDrag(false);
  if (imageTrackingActive) finishImageTracking();
  selectedView = view;
  preview.title = `${VIEW_NAMES[view]} — click to change view`;
  viewButtons.forEach(button => button.setAttribute("aria-checked", String(Number(button.dataset.view) === view)));
  closeViewMenu(true);
  // No coordinate conversion, marker reload, snap projection, or background edit.
  schedule();
  requestPatches();
  if (imagePrepared) {
    requestImagePreview();
    requestImageSample();
  }
}

function setRec2020AuthoringOptions(nextFull: boolean) {
  fullRec2020 = nextFull;
  fullRec2020Toggle.textContent = fullRec2020 ? "Rec.2020" : "Rec.2020 (P3-D65 Limited)";
  fullRec2020Toggle.title = fullRec2020
    ? "Using full Rec.2020 authoring; click for P3-D65-limited Rec.2020"
    : "Using P3-D65-limited Rec.2020 authoring; click for full Rec.2020";
  fullRec2020Toggle.setAttribute("aria-label", fullRec2020
    ? "Rec.2020; click to switch to P3-D65-limited Rec.2020"
    : "Rec.2020 (P3-D65 Limited); click to switch to full Rec.2020");
  imageKey = "";
  currentRender = undefined;
  schedule();
}
fullRec2020Toggle.addEventListener("click", () => setRec2020AuthoringOptions(!fullRec2020));
function closeViewMenu(restoreFocus = false) {
  viewMenu.hidden = true;
  preview.setAttribute("aria-expanded", "false");
  if (restoreFocus) preview.focus({ preventScroll: true });
}
function openViewMenu() {
  viewMenu.hidden = false;
  preview.setAttribute("aria-expanded", "true");
  const rect = preview.getBoundingClientRect();
  const width = Math.min(370, innerWidth - 20);
  viewMenu.style.width = `${width}px`;
  viewMenu.style.left = `${Math.max(10, Math.min(rect.left, innerWidth - width - 10))}px`;
  viewMenu.style.top = `${Math.max(10, Math.min(rect.bottom + 4, innerHeight - viewMenu.offsetHeight - 10))}px`;
  viewButtons.find(button => Number(button.dataset.view) === selectedView)?.focus({ preventScroll: true });
}
function setFromHex() {
  cancelTrackpadTracking();
  finishJTrackwheelInteraction(false);
  finishPreviewDrag(false);
  const decoded = decodeHex(encodedValue.value);
  if (!decoded) {
    encodedValue.setCustomValidity("Enter exactly six hexadecimal digits.");
    encodedValue.reportValidity();
    return;
  }
  encodedValue.setCustomValidity("");
  if (encodedReadoutMode === "jxy") {
    // J′x′y′ mode edits the normalized Rec.2020-authored coordinates directly. The
    // inverse sRGB transfer recovers each channel before clamping to the
    // picker domain; this path intentionally does not create a snap target.
    const coordinates = decodeJxyHex(encodedValue.value);
    if (!coordinates) return;
    invalidatePendingSet();
    realCode = { j: coordinates[0], x: coordinates[1], y: coordinates[2] };
    setAllCode(realCode);
    activePatch = null;
    activeTarget = null;
    colorTrackpad.dataset.snapTarget = "none";
    colorTrackpad.dataset.jSnapTarget = "none";
    updatePatchLocators();
    drawIndicators();
    schedule();
    return;
  }
  const id = ++setId;
  evaluatorWorker.postMessage({
    kind: "set",
    id,
    profile: selectedView,
    red: decoded[0],
    green: decoded[1],
    blue: decoded[2],
    fullRec2020,
  });
}

function imageSetStatus(message: string, error = false) {
  imageStatus.textContent = message;
  imageStatus.classList.toggle("callout-error", error);
}

function clearImageLoupe() {
  imageLoupe.removeAttribute("src");
  imageLoupe.alt = "";
  if (imageLoupeUrl) URL.revokeObjectURL(imageLoupeUrl);
  imageLoupeUrl = undefined;
}

function setImageTransformBusy(busy: boolean) {
  imagePanel.classList.toggle("image-transforming", busy);
  imageTransformBanner.hidden = !busy;
  imageViewport.setAttribute("aria-busy", String(busy));
  imagePanel.dataset.transforming = String(busy);
  if (!busy) pendingImageAppearance = undefined;
}

function finishImageAppearanceIfReady() {
  const pending = pendingImageAppearance;
  if (pending?.view === selectedView && pending.sourceMode === imageSourceMode && pending.referenceWhiteEncodedAsLinear203 === referenceWhiteEncodedAsLinear203 &&
    pending.previewReady && pending.loupeReady) setImageTransformBusy(false);
}

function detectImageFormat(file: File): string | undefined {
  const lower = file.name.toLowerCase();
  if (lower.endsWith(".dng") || file.type === "image/x-adobe-dng" || file.type === "image/dng") return "dng";
  if (lower.endsWith(".png") || file.type === "image/png") return "png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg") || file.type === "image/jpeg") return "jpeg";
  if (lower.endsWith(".exr") || file.type === "image/x-exr") return "exr";
  if (lower.endsWith(".heic") || file.type === "image/heic") return "heic";
  if (lower.endsWith(".heif") || file.type === "image/heif") return "heif";
  return undefined;
}

function defaultReferenceWhiteEncodedAsLinear203(format: string, summary?: any): boolean {
  const normalizedFormat = String(summary?.format ?? format).toLowerCase();
  // Checked means the prepared display-linear source stores 203-nit reference
  // white as 2.03, so it must be divided back to the application's 1.0-white
  // boundary before inverse ACES. Scene-reference ACES EXR bypasses this flag.
  if (normalizedFormat === "exr") return false;
  if (normalizedFormat === "dng") return false;
  if (summary?.gainmap_confirmed) return true;
  const transfer = String(summary?.transfer ?? "").toLowerCase();
  if (transfer.includes("pq") || transfer.includes("hlg")) return true;
  return false;
}

function requestedImageSourceMode(): ImageSourceMode {
  const format = String(imageSummary?.format ?? imageFormat).toLowerCase();
  if (format === "dng") return "display-linear-xyz-d65";
  if (format !== "exr") return "display-linear-xyz-d65";
  const gamut = imageGamutSelect.value === "embedded"
    ? String(imageSummary?.gamut ?? "")
    : imageGamutSelect.value;
  return gamut === "ACEScg" || gamut === "ACES2065-1"
    ? "scene-reference-aces"
    : "display-linear-xyz-d65";
}

function updateImageUnitsHelp() {
  const dng = String(imageSummary?.format ?? imageFormat).toLowerCase() === "dng";
  const sceneReference = requestedImageSourceMode() === "scene-reference-aces";
  imageReferenceWhite203Control.disabled = sceneReference || dng;
  imageUnitsField.setAttribute("aria-disabled", String(sceneReference || dng));
  if (dng) {
    referenceWhiteEncodedAsLinear203 = false;
    imageReferenceWhite203Control.checked = false;
    imageReferenceWhiteHelp.textContent = "RAW/DNG uses linear 1.0 as reference white.";
    return;
  }
  if (sceneReference) {
    imageReferenceWhiteHelp.textContent = "Scene-reference ACES data goes directly through the selected view transform; no reference-white scaling or inverse view transform is applied.";
    return;
  }
  imageReferenceWhiteHelp.textContent = imageReferenceWhite203Control.checked
    ? "Divide by 2.03 before the inverse view transform."
    : "Use linear 1.0 as reference white.";
}

function syncImageUnitsDefault() {
  if (String(imageSummary?.format ?? imageFormat).toLowerCase() === "dng") {
    referenceWhiteEncodedAsLinear203 = false;
    imageReferenceWhite203Control.checked = false;
    updateImageUnitsHelp();
    return;
  }
  if (requestedImageSourceMode() === "scene-reference-aces") {
    updateImageUnitsHelp();
    return;
  }
  if (imageUnitsUserChanged) {
    updateImageUnitsHelp();
    return;
  }
  const selectedTransfer = imageGamutSelect.value === "embedded"
    ? imageSummary?.transfer
    : imageTransferSelect.value;
  referenceWhiteEncodedAsLinear203 = defaultReferenceWhiteEncodedAsLinear203(
    imageFormat,
    { ...imageSummary, transfer: selectedTransfer },
  );
  imageReferenceWhite203Control.checked = referenceWhiteEncodedAsLinear203;
  updateImageUnitsHelp();
}

function imageSetControlVisibility(summary: any) {
  const isDng = String(summary?.format ?? imageFormat).toLowerCase() === "dng";
  const isExr = String(summary?.format ?? imageFormat).toLowerCase() === "exr";
  const manualSceneAces = isExr && imageGamutSelect.value !== "embedded" &&
    (imageGamutSelect.value === "ACEScg" || imageGamutSelect.value === "ACES2065-1");
  if (manualSceneAces) imageTransferSelect.value = "Linear";
  imageGamutField.hidden = isDng;
  imageTransferField.hidden = isDng || imageGamutSelect.value === "embedded";
  imageTransferSelect.disabled = isDng || imageGamutSelect.value === "embedded" || manualSceneAces;
  const embedded = Boolean(summary?.embedded_available ?? summary?.automatic_icc);
  const option = imageGamutSelect.querySelector<HTMLOptionElement>('option[value="embedded"]');
  if (option) {
    option.disabled = !embedded;
    option.textContent = summary?.metadata_source
      ? `Use embedded ${String(summary.metadata_source).replace(/^(PNG|JPEG|HEIF|EXR)\s+/i, "")}`
      : "Use embedded interpretation";
  }
  // ACEScg/AP0 are scene-reference encodings, not display RGB primaries.
  // Keep those choices available only for EXR sources where the scene path is
  // well-defined; ordinary raster/HEIF sources must use an RGB→XYZ-D65 adapter.
  for (const value of ["ACEScg", "ACES2065-1"]) {
    const acesOption = imageGamutSelect.querySelector<HTMLOptionElement>(`option[value="${value}"]`);
    if (acesOption) acesOption.disabled = !isExr;
  }
  // Apply the no-profile sRGB fallback only on initial inspection.  A later
  // Primaries change must never overwrite the user's manual selection.
  if (!embedded && !isDng && (imageGamutSelect.value === "embedded" || !imageGamutSelect.value)) {
    imageGamutSelect.value = "Rec.709 / sRGB";
    imageTransferSelect.value = "sRGB";
    imageInterpretationWarning.hidden = false;
    imageInterpretationWarning.textContent = "No embedded color profile was found. The image is being interpreted as sRGB (Rec.709) with sRGB transfer; you can override this below.";
  }
}

function imageInterpretationReady() {
  if (String(imageSummary?.format ?? imageFormat).toLowerCase() === "dng") return true;
  if (imageGamutSelect.value === "embedded") return Boolean(imageSummary?.embedded_available ?? imageSummary?.automatic_icc);
  return Boolean(imageGamutSelect.value && imageTransferSelect.value);
}

function updateImageOptionsWarning() {
  const format = String(imageSummary?.format ?? imageFormat).toLowerCase();
  const assumed = format !== "dng" && !Boolean(imageSummary?.embedded_available ?? imageSummary?.automatic_icc) && imageGamutSelect.value === "Rec.709 / sRGB" && imageTransferSelect.value === "sRGB";
  imageInterpretationWarning.hidden = !assumed;
  if (assumed) imageInterpretationWarning.textContent = "No embedded color profile was found. The image is being interpreted as sRGB (Rec.709) with sRGB transfer; you can override this below.";
}

function imageRequestPrepare() {
  if (!imageFile || !imageFormat || !imageInterpretationReady()) {
    if (imageFile) imageSetStatus("Select both Primaries and Transfer to interpret this image.");
    return;
  }
  imagePrepared = false;
  setImageTransformBusy(true);
  if (imageTrackingActive) finishImageTracking();
  // A new interpretation changes every sampled XYZ-D65 value. Clear the
  // statistics and average snap target immediately; the pointer location is
  // retained and sampled again when the replacement raster is ready.
  imageAnalysis = null;
  imageAverage = null;
  clearImageLoupe();
  if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
  imagePreviewUrl = undefined;
  imagePreview.removeAttribute("src");
  imagePreview.alt = "";
  imageOverlayContext.clearRect(0, 0, imageOverlay.width, imageOverlay.height);
  imagePanel.dataset.imageState = "loading";
  imagePanel.dataset.ready = "false";
  imageViewport.dataset.ready = "false";
  updatePatchCandidate(false);
  drawIndicators();
  imageGeneration += 1;
  imageSetStatus("Preparing the native image raster…");
  const id = imageRequestId;
  const embedded = imageGamutSelect.value === "embedded";
  imageWorker.postMessage({
    kind: "prepare", id, generation: imageGeneration, format: imageFormat,
    gamut: embedded || String(imageSummary?.format ?? "").toLowerCase() === "dng" ? null : imageGamutSelect.value,
    transfer: embedded || String(imageSummary?.format ?? "").toLowerCase() === "dng" ? null : imageTransferSelect.value,
    view: selectedView,
    referenceWhiteEncodedAsLinear203,
  } satisfies ImageWorkerRequest);
}

function imageGeometry() {
  const viewport = imageViewport.getBoundingClientRect();
  const sourceW = Math.max(1, imageWidth), sourceH = Math.max(1, imageHeight);
  const baseScale = Math.max(viewport.width / sourceW, viewport.height / sourceH);
  const scale = baseScale * imageZoom;
  const width = sourceW * scale, height = sourceH * scale;
  const xFraction = imagePointerX / Math.max(1, imageWidth - 1);
  const yFraction = imagePointerY / Math.max(1, imageHeight - 1);
  const desiredLeft = viewport.width / 2 - xFraction * width;
  const desiredTop = viewport.height / 2 - yFraction * height;
  const left = Math.max(viewport.width - width, Math.min(0, desiredLeft));
  const top = Math.max(viewport.height - height, Math.min(0, desiredTop));
  return {
    viewport,
    scale,
    width,
    height,
    left,
    top,
    crosshairX: left + xFraction * width,
    crosshairY: top + yFraction * height,
  };
}

function updateImageGeometry() {
  if (!imageWidth || !imageHeight) return imageGeometry();
  const geometry = imageGeometry();
  imagePreview.style.left = `${geometry.left}px`;
  imagePreview.style.top = `${geometry.top}px`;
  imagePreview.style.width = `${geometry.width}px`;
  imagePreview.style.height = `${geometry.height}px`;
  imageViewport.dataset.zoom = String(imageZoom);
  imageViewport.dataset.panX = geometry.left.toFixed(3);
  imageViewport.dataset.panY = geometry.top.toFixed(3);
  imageViewport.dataset.crosshairX = geometry.crosshairX.toFixed(3);
  imageViewport.dataset.crosshairY = geometry.crosshairY.toFixed(3);
  return geometry;
}

function imageViewportRect() {
  const geometry = updateImageGeometry();
  return {
    left: geometry.viewport.left + geometry.left,
    top: geometry.viewport.top + geometry.top,
    width: geometry.width,
    height: geometry.height,
  };
}

function imageClientToNative(clientX: number, clientY: number) {
  const rect = imageViewportRect();
  return {
    x: clamp01((clientX - rect.left) / Math.max(1, rect.width)) * Math.max(0, imageWidth - 1),
    y: clamp01((clientY - rect.top) / Math.max(1, rect.height)) * Math.max(0, imageHeight - 1),
  };
}

function imageNativeToCanvas(x: number, y: number): [number, number] {
  const geometry = updateImageGeometry();
  const px = geometry.left + (x / Math.max(1, imageWidth - 1)) * geometry.width;
  const py = geometry.top + (y / Math.max(1, imageHeight - 1)) * geometry.height;
  return [
    px / Math.max(1, geometry.viewport.width) * imageOverlay.width,
    py / Math.max(1, geometry.viewport.height) * imageOverlay.height,
  ];
}

function drawImageOverlay() {
  imageOverlayContext.clearRect(0, 0, imageOverlay.width, imageOverlay.height);
  if (!imagePointerSet) return;
  const geometry = updateImageGeometry();
  const [px, py] = [
    geometry.crosshairX / Math.max(1, geometry.viewport.width) * imageOverlay.width,
    geometry.crosshairY / Math.max(1, geometry.viewport.height) * imageOverlay.height,
  ];
  // The fixed 512x512 overlay is stretched to the viewport's 1.5:1 CSS
  // rectangle. Express each dimension in its own backing-store units so the
  // crosshair remains square and its strokes retain the same CSS width.
  const scaleX = imageOverlay.width / Math.max(1, geometry.viewport.width);
  const scaleY = imageOverlay.height / Math.max(1, geometry.viewport.height);
  const armX = 18 * scaleX;
  const gapX = 5 * scaleX;
  const halfX = 4 * scaleX;
  const armY = 18 * scaleY;
  const gapY = 5 * scaleY;
  const halfY = 4 * scaleY;
  const horizontalStroke = 2 * scaleY;
  const verticalStroke = 2 * scaleX;
  imageOverlayContext.save();
  imageOverlayContext.strokeStyle = "rgb(255 255 255 / 92%)";
  imageOverlayContext.lineWidth = horizontalStroke;
  imageOverlayContext.beginPath();
  imageOverlayContext.moveTo(px - armX, py); imageOverlayContext.lineTo(px - gapX, py);
  imageOverlayContext.moveTo(px + gapX, py); imageOverlayContext.lineTo(px + armX, py);
  imageOverlayContext.stroke();
  imageOverlayContext.lineWidth = verticalStroke;
  imageOverlayContext.beginPath();
  imageOverlayContext.moveTo(px, py - armY); imageOverlayContext.lineTo(px, py - gapY);
  imageOverlayContext.moveTo(px, py + gapY); imageOverlayContext.lineTo(px, py + armY);
  imageOverlayContext.stroke();
  imageOverlayContext.fillStyle = "rgb(0 0 0 / 85%)";
  imageOverlayContext.fillRect(px - halfX, py - halfY, 2 * halfX, scaleY);
  imageOverlayContext.fillRect(px - halfX, py + halfY - scaleY, 2 * halfX, scaleY);
  imageOverlayContext.fillRect(px - halfX, py - halfY, scaleX, 2 * halfY);
  imageOverlayContext.fillRect(px + halfX - scaleX, py - halfY, scaleX, 2 * halfY);
  imageOverlayContext.restore();
}

function requestImageSample() {
  if (!imagePrepared || !imageFile) return;
  const token = ++imageSampleToken;
  latestImageSampleToken = token;
  if (pendingImageAppearance?.view === selectedView && pendingImageAppearance.sourceMode === imageSourceMode && pendingImageAppearance.referenceWhiteEncodedAsLinear203 === referenceWhiteEncodedAsLinear203) {
    pendingImageAppearance.sampleToken = token;
    pendingImageAppearance.loupeReady = false;
  }
  imageWorker.postMessage({ kind: "sample", id: imageRequestId, generation: imageGeneration, token, format: imageFormat, x: imagePointerX, y: imagePointerY, radius: 3, view: selectedView, referenceWhiteEncodedAsLinear203 } satisfies ImageWorkerRequest);
}

function requestImagePreview() {
  if (!imagePrepared || !imageFile) return;
  const appearanceToken = ++imageAppearanceToken;
  pendingImageAppearance = { token: appearanceToken, view: selectedView, sourceMode: imageSourceMode, referenceWhiteEncodedAsLinear203, previewReady: false, loupeReady: false };
  setImageTransformBusy(true);
  imageWorker.postMessage({ kind: "preview", id: imageRequestId, generation: imageGeneration, appearanceToken, format: imageFormat, view: selectedView, referenceWhiteEncodedAsLinear203 } satisfies ImageWorkerRequest);
}

function setImagePointer(x: number, y: number, sample = true) {
  imagePointerX = Math.max(0, Math.min(Math.max(0, imageWidth - 1), x));
  imagePointerY = Math.max(0, Math.min(Math.max(0, imageHeight - 1), y));
  imagePointerSet = true;
  updateImageGeometry();
  imageViewport.dataset.pointerX = imagePointerX.toFixed(4);
  imageViewport.dataset.pointerY = imagePointerY.toFixed(4);
  drawImageOverlay();
  if (sample) requestImageSample();
}

function applyImageRelativeDelta(deltaX: number, deltaY: number, sample = true) {
  const geometry = updateImageGeometry();
  // The native selection is the sole gesture state. Centering it and clamping
  // the rendered image gives the unique image/crosshair solution; at a bound,
  // further deltas move the crosshair toward the image edge, and reversal
  // naturally re-centers it before the image begins moving again.
  setImagePointer(imagePointerX + deltaX / Math.max(1e-6, geometry.scale), imagePointerY + deltaY / Math.max(1e-6, geometry.scale), sample);
}

function setImageZoom(value: number) {
  const nextZoom = [1, 2, 5].includes(value) ? value : 2;
  const selectedX = imagePointerX, selectedY = imagePointerY;
  imageZoom = nextZoom;
  imagePointerX = selectedX;
  imagePointerY = selectedY;
  imageZoomButtons.forEach(button => button.setAttribute("aria-pressed", String(Number(button.dataset.imageZoom) === imageZoom)));
  updateImageGeometry();
  drawImageOverlay();
}

function finishImageTracking() {
  if (document.pointerLockElement === imageViewport) {
    try { document.exitPointerLock(); } catch { /* best effort */ }
  }
  imagePointerLockActive = false;
  imageTrackingActive = false;
  imageTouchPointerId = null;
  imageViewport.classList.remove("image-tracking");
  imageViewport.dataset.tracking = "idle";
  drawImageOverlay();
}

function applyImageDesktopPointer(event: PointerEvent) {
  const point = imageClientToNative(event.clientX, event.clientY);
  setImagePointer(point.x, point.y);
  event.preventDefault();
}

function applyImageLockedMotion(event: MouseEvent) {
  const now = performance.now();
  const elapsed = Math.max(1, now - imageTouchLastTime);
  const dx = event.movementX || 0, dy = event.movementY || 0;
  const velocity = trackMotionVelocity({ x: imageTouchVelocityX, y: imageTouchVelocityY }, dx, dy, imageViewport.clientWidth, imageViewport.clientHeight, elapsed);
  imageTouchVelocityX = velocity.x; imageTouchVelocityY = velocity.y; imageTouchLastTime = now;
  const acceleration = trackMotionAcceleration(Math.hypot(velocity.x, velocity.y));
  applyImageRelativeDelta(dx * acceleration, dy * acceleration);
}

imageWorker.onmessage = async (event: MessageEvent<ImageWorkerMessage>) => {
  const response = event.data;
  if (response.generation !== undefined && response.generation !== imageGeneration) return;
  if (response.id !== imageRequestId) return;
  if (response.kind === "error") {
    imagePrepared = false;
    setImageTransformBusy(false);
    imageSetStatus(response.message, true);
    return;
  }
  if (response.kind === "inspect") {
    imageSummary = response.summary;
    // Inspection establishes the source interpretation controls.  The image
    // viewport remains hidden until the native raster is prepared, but the
    // controls must be available immediately for files without metadata.
    imagePanel.dataset.ready = "inspected";
    imageSetControlVisibility(imageSummary);
    syncImageUnitsDefault();
    updateImageOptionsWarning();
    imageTransferField.hidden = String(imageSummary?.format ?? imageFormat).toLowerCase() === "dng" || imageGamutSelect.value === "embedded";
    imageSetStatus(imageInterpretationReady() ? "Preparing the native image raster…" : "Choose a source interpretation to continue.");
    if (imageInterpretationReady()) imageRequestPrepare();
    return;
  }
  if (response.kind === "ready") {
    imageWidth = response.width; imageHeight = response.height;
    imageSourceMode = response.sourceMode;
    imagePanel.dataset.sourceMode = imageSourceMode;
    // Decode the replacement off-DOM. Keep the image row hidden and expose
    // this generation after the native pointer, geometry, and overlay
    // have all been initialized, preventing an image-without-crosshair gap.
    const generation = imageGeneration;
    const requestId = imageRequestId;
    const url = URL.createObjectURL(new Blob([response.png], { type: "image/png" }));
    const decoded = new Image();
    decoded.src = url;
    try {
      await decoded.decode();
    } catch {
      URL.revokeObjectURL(url);
      imagePrepared = false;
      setImageTransformBusy(false);
      imageSetStatus("Prepared image could not be decoded.", true);
      return;
    }
    if (generation !== imageGeneration || requestId !== imageRequestId) {
      URL.revokeObjectURL(url);
      return;
    }
    const presentationMismatch = response.view !== selectedView || response.sourceMode !== requestedImageSourceMode() || response.referenceWhiteEncodedAsLinear203 !== referenceWhiteEncodedAsLinear203;
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    imagePreviewUrl = url;
    imagePreview.src = imagePreviewUrl;
    imagePreview.dataset.renderer = response.renderer;
    imagePreview.alt = `Loaded ${imageFormat.toUpperCase()} image (${imageWidth} × ${imageHeight})`;
    // Make the replacement layout measurable before deriving geometry.  This
    // handler runs to completion before the browser paints, so the ready row,
    // image, and initialized crosshair become visible as one update.
    imagePrepared = true;
    imagePanel.dataset.imageState = "ready";
    imagePanel.dataset.ready = "true";
    imageViewport.dataset.ready = "true";
    imagePanel.hidden = false;
    imagePointerSet = false;
    setImagePointer(imageWidth / 2, imageHeight / 2, false);
    updateImageGeometry();
    drawImageOverlay();
    imageSetStatus(`${imageWidth} × ${imageHeight} native pixels ready.`);
    setImageTransformBusy(false);
    imageStats.textContent = "Move the crosshair to inspect a 3 px neighborhood.";
    if (presentationMismatch) requestImagePreview();
    requestImageSample();
    return;
  }
  if (response.kind === "preview") {
    if (!imagePrepared || response.appearanceToken !== imageAppearanceToken || response.view !== selectedView || response.sourceMode !== imageSourceMode || response.referenceWhiteEncodedAsLinear203 !== referenceWhiteEncodedAsLinear203) return;
    const generation = imageGeneration;
    const requestId = imageRequestId;
    const url = URL.createObjectURL(new Blob([response.png], { type: "image/png" }));
    const decoded = new Image();
    decoded.src = url;
    try {
      await decoded.decode();
    } catch {
      URL.revokeObjectURL(url);
      setImageTransformBusy(false);
      imageSetStatus("Display transform could not be decoded; previous image retained.", true);
      return;
    }
    if (generation !== imageGeneration || requestId !== imageRequestId || response.appearanceToken !== imageAppearanceToken || response.view !== selectedView || response.sourceMode !== imageSourceMode || response.referenceWhiteEncodedAsLinear203 !== referenceWhiteEncodedAsLinear203) {
      URL.revokeObjectURL(url);
      return;
    }
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    imagePreviewUrl = url;
    imagePreview.src = imagePreviewUrl;
    imagePreview.dataset.renderer = response.renderer;
    imagePreview.alt = `Loaded ${imageFormat.toUpperCase()} image (${imageWidth} × ${imageHeight})`;
    if (pendingImageAppearance?.token === response.appearanceToken && pendingImageAppearance.view === response.view && pendingImageAppearance.sourceMode === response.sourceMode && pendingImageAppearance.referenceWhiteEncodedAsLinear203 === response.referenceWhiteEncodedAsLinear203) {
      pendingImageAppearance.previewReady = true;
      finishImageAppearanceIfReady();
    }
    return;
  }
  if (response.kind === "sample") {
    if (response.token !== latestImageSampleToken) return;
    if (response.view !== selectedView || response.sourceMode !== imageSourceMode || response.referenceWhiteEncodedAsLinear203 !== referenceWhiteEncodedAsLinear203) return;
    imageViewport.dataset.sampleX = String(response.x);
    imageViewport.dataset.sampleY = String(response.y);
    imageViewport.dataset.sampleCount = String(response.points.length);
    imageViewport.dataset.sampleRejected = String(response.rejected);
    const points = response.points.map(point => ({ x: point.x, y: point.y }));
    const ellipse = covarianceEllipse(points);
    const meanCode = response.meanCode;
    void (async () => {
      const url = URL.createObjectURL(new Blob([response.loupe], { type: "image/png" }));
      const image = new Image();
      image.src = url;
      try {
        await image.decode();
      } catch {
        URL.revokeObjectURL(url);
        if (pendingImageAppearance?.sampleToken === response.token &&
          pendingImageAppearance.view === response.view && pendingImageAppearance.sourceMode === response.sourceMode && pendingImageAppearance.referenceWhiteEncodedAsLinear203 === response.referenceWhiteEncodedAsLinear203) {
          pendingImageAppearance.loupeReady = true;
          finishImageAppearanceIfReady();
        }
        return;
      }
      // Decode off-DOM, then atomically publish the direct image.  Keep the
      // active blob URL alive until the next replacement; revoking it
      // immediately after decode can make Safari discard the HDR resource
      // while it is still being presented.
      if (response.id !== imageRequestId || response.generation !== imageGeneration || response.token !== latestImageSampleToken || response.view !== selectedView || response.sourceMode !== imageSourceMode || response.referenceWhiteEncodedAsLinear203 !== referenceWhiteEncodedAsLinear203 || !imagePrepared) {
        URL.revokeObjectURL(url);
        return;
      }
      const previousUrl = imageLoupeUrl;
      imageLoupe.src = url;
      const displayY = Math.max(0, imageHeight - 1 - response.y);
      imageLoupe.alt = `Pixel loupe centered at ${response.x}, ${displayY}`;
      imageLoupeUrl = url;
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      imageAnalysis = {
        x: response.x, y: response.y, sampleCount: response.points.length,
        rejectedCount: response.rejected, mean: response.mean,
        meanAcescg: response.meanAcescg, ellipse,
        loupe: { x: response.minX, y: response.minY, width: response.width, height: response.height },
      };
      imageAverage = meanCode[0] > 0.5 ? { j: meanCode[1], x: meanCode[2], y: meanCode[3] } : null;
      const available = response.total - response.rejected;
      imageStats.textContent = `Center ${response.x}, ${displayY} · ${available}/${response.total} samples available`;
      updatePatchCandidate(false);
      drawIndicators();
      drawImageOverlay();
      if (pendingImageAppearance?.sampleToken === response.token &&
        pendingImageAppearance.view === response.view && pendingImageAppearance.sourceMode === response.sourceMode && pendingImageAppearance.referenceWhiteEncodedAsLinear203 === response.referenceWhiteEncodedAsLinear203) {
        pendingImageAppearance.loupeReady = true;
        finishImageAppearanceIfReady();
      }
    })();
  }
};

imageWorker.onerror = () => {
  setImageTransformBusy(false);
  imageSetStatus("Image decoder worker failed.", true);
};
imageLoadButton.addEventListener("click", () => imageFileInput.click());
function openImageOptions() {
  updateImageOptionsWarning();
  imageOptionsButton.setAttribute("aria-expanded", "true");
  if (typeof imageOptionsDialog.showModal === "function") imageOptionsDialog.showModal();
  else imageOptionsDialog.setAttribute("open", "");
  imageOptionsFocusPending = true;
  requestAnimationFrame(() => (imageGamutSelect.offsetParent ? imageGamutSelect : imageOptionsClose).focus());
}
function closeImageOptions() {
  if (imageOptionsDialog.open) imageOptionsDialog.close();
  else imageOptionsDialog.removeAttribute("open");
  imageOptionsButton.setAttribute("aria-expanded", "false");
  if (imageOptionsFocusPending) { imageOptionsFocusPending = false; imageOptionsButton.focus(); }
}
imageOptionsButton.addEventListener("click", openImageOptions);
imageOptionsClose.addEventListener("click", event => { event.preventDefault(); closeImageOptions(); });
imageOptionsDialog.addEventListener("click", event => { if (event.target === imageOptionsDialog) closeImageOptions(); });
imageOptionsDialog.addEventListener("cancel", event => { event.preventDefault(); closeImageOptions(); });
imageOptionsDialog.addEventListener("close", () => {
  imageOptionsButton.setAttribute("aria-expanded", "false");
  if (imageOptionsFocusPending) { imageOptionsFocusPending = false; imageOptionsButton.focus(); }
});
imageZoomButtons.forEach(button => button.addEventListener("click", () => setImageZoom(Number(button.dataset.imageZoom))));
imageFileInput.addEventListener("change", async () => {
  const file = imageFileInput.files?.[0];
  if (!file) return;
  const format = detectImageFormat(file);
  if (!format) { imageSetStatus("Unsupported image format. Choose DNG, EXR, JPEG, PNG, HEIC, or HEIF.", true); return; }
  imageGeneration += 1;
  imageRequestId += 1;
  imageFile = file; imageFormat = format; imageSummary = undefined; imagePrepared = false; imageSourceMode = "display-linear-xyz-d65";
  imagePanel.dataset.sourceMode = imageSourceMode;
  imageOptionsButton.disabled = false;
  imagePointerSet = false; imageAnalysis = null; imageAverage = null;
  imageZoom = 2;
  imageZoomButtons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.imageZoom === "2")));
  clearImageLoupe();
  imagePanel.hidden = false; imageViewport.dataset.ready = "false";
  imagePanel.dataset.imageState = "loading";
  imagePanel.dataset.ready = "false";
  setImageTransformBusy(false);
  imagePreview.removeAttribute("src");
  imagePreview.alt = "";
  imageStats.textContent = "";
  updatePatchCandidate(false);
  drawIndicators();
  imageGamutSelect.value = "embedded"; imageTransferSelect.value = "sRGB";
  imageUnitsUserChanged = false;
  referenceWhiteEncodedAsLinear203 = defaultReferenceWhiteEncodedAsLinear203(format);
  imageReferenceWhite203Control.checked = referenceWhiteEncodedAsLinear203;
  updateImageUnitsHelp();
  imageGamutField.hidden = true;
  imageTransferField.hidden = true;
  imageSetStatus("Inspecting image…");
  try {
    const bytes = await file.arrayBuffer();
    imageWorker.postMessage({ kind: "inspect", id: imageRequestId, generation: imageGeneration, format, bytes } satisfies ImageWorkerRequest, [bytes]);
  } catch (error) { imageSetStatus(error instanceof Error ? error.message : String(error), true); }
});
imageGamutSelect.addEventListener("change", () => { imageSetControlVisibility(imageSummary); updateImageOptionsWarning(); syncImageUnitsDefault(); if (imageInterpretationReady()) imageRequestPrepare(); });
imageTransferSelect.addEventListener("change", () => { updateImageOptionsWarning(); syncImageUnitsDefault(); if (imageInterpretationReady()) imageRequestPrepare(); });
imageReferenceWhite203Control.addEventListener("change", () => {
  imageUnitsUserChanged = true;
  referenceWhiteEncodedAsLinear203 = imageReferenceWhite203Control.checked;
  updateImageUnitsHelp();
  if (imagePrepared) {
    requestImagePreview();
    requestImageSample();
  }
});
imageViewport.addEventListener("pointerdown", event => {
  if (!imagePrepared || event.pointerType === "mouse" && event.button !== 0) return;
  if (event.pointerType === "mouse") {
    if (!imageTrackingActive) {
      imageTrackingActive = true; imagePointerLockFallback = false;
      imageViewport.classList.add("image-tracking"); imageViewport.dataset.tracking = "mouse-active";
      applyImageDesktopPointer(event);
      imageTouchLastTime = performance.now(); imageTouchVelocityX = 0; imageTouchVelocityY = 0;
      try {
        if (typeof imageViewport.requestPointerLock !== "function") {
          imagePointerLockFallback = true;
          imageViewport.dataset.pointerLock = "fallback";
        }
        const result = imageViewport.requestPointerLock?.();
        if (result && typeof (result as Promise<void>).catch === "function") {
          (result as Promise<void>).catch(() => { imagePointerLockFallback = true; imageViewport.dataset.pointerLock = "fallback"; });
        }
      } catch { imagePointerLockFallback = true; imageViewport.dataset.pointerLock = "fallback"; }
    } else {
      finishImageTracking();
    }
    event.stopPropagation(); event.preventDefault(); return;
  }
  if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
  imageTouchPointerId = event.pointerId; imageTrackingActive = true; imageViewport.classList.add("image-tracking"); imageViewport.dataset.tracking = "touch-active";
  imageTouchLastX = event.clientX; imageTouchLastY = event.clientY; imageTouchLastTime = performance.now(); imageTouchVelocityX = 0; imageTouchVelocityY = 0;
  try { imageViewport.setPointerCapture(event.pointerId); } catch { /* best effort */ }
  event.preventDefault();
});
document.addEventListener("pointermove", event => {
  if (!imageTrackingActive || event.pointerType !== "mouse") return;
  if (!imagePointerLockActive || document.pointerLockElement !== imageViewport) applyImageDesktopPointer(event);
});
// Pointer Lock reports relative movement through `mousemove`, not
// `pointermove`; keep this separate from the visible-pointer fallback above.
document.addEventListener("mousemove", event => {
  if (!imageTrackingActive || !imagePointerLockActive || document.pointerLockElement !== imageViewport) return;
  applyImageLockedMotion(event);
});
document.addEventListener("pointerdown", event => {
  if (imageTrackingActive && event.pointerType === "mouse" && event.button === 0 && !imageViewport.contains(event.target as Node)) {
    finishImageTracking(); event.preventDefault(); event.stopImmediatePropagation();
  }
}, true);
document.addEventListener("pointerlockchange", () => {
  imagePointerLockActive = document.pointerLockElement === imageViewport;
  imageViewport.classList.toggle("pointer-lock-active", imagePointerLockActive);
  imageViewport.dataset.pointerLock = imagePointerLockActive ? "active" : (imagePointerLockFallback ? "fallback" : "none");
  if (!imagePointerLockActive && imageTrackingActive && !imagePointerLockFallback) finishImageTracking();
});
document.addEventListener("pointerlockerror", () => {
  if (imageTrackingActive) { imagePointerLockFallback = true; imageViewport.dataset.pointerLock = "fallback"; }
});
imageViewport.addEventListener("pointermove", event => {
  if ((event.pointerType !== "touch" && event.pointerType !== "pen") || event.pointerId !== imageTouchPointerId) return;
  const now = performance.now(); const elapsed = Math.max(1, now - imageTouchLastTime);
  const dx = event.clientX - imageTouchLastX, dy = event.clientY - imageTouchLastY;
  const velocity = trackMotionVelocity({ x: imageTouchVelocityX, y: imageTouchVelocityY }, dx, dy, imageViewport.clientWidth, imageViewport.clientHeight, elapsed);
  imageTouchVelocityX = velocity.x; imageTouchVelocityY = velocity.y; imageTouchLastX = event.clientX; imageTouchLastY = event.clientY; imageTouchLastTime = now;
  const acceleration = trackMotionAcceleration(Math.hypot(velocity.x, velocity.y));
  applyImageRelativeDelta(dx * acceleration, dy * acceleration);
  event.preventDefault();
});
imageViewport.addEventListener("pointerup", event => { if (event.pointerId === imageTouchPointerId) finishImageTracking(); });
imageViewport.addEventListener("pointercancel", event => { if (event.pointerId === imageTouchPointerId) finishImageTracking(); });

[sliceWorker, evaluatorWorker, checkerWorker].forEach((worker) => {
  worker.onmessage = (
    event: MessageEvent<
      | RenderResponse
      | EvaluateResponse
      | PreviewResponse
      | ColorCheckerResponse
      | SetResponse
      | WorkerError
    >,
  ) => {
    const response = event.data;
    if (response.kind === "worker-error") {
      const current =
        ((response.operation === "render" &&
          response.id === currentRender?.id) ||
          ((response.operation === "evaluate" || response.operation === "preview") && response.id === evaluationId) ||
          (response.operation === "colorchecker" &&
            response.id === checkerId) ||
          (response.operation === "set" && response.id === setId));
      if (!current) return;
      if (response.operation === "preview") {
        previewStatus.textContent = "Preview encoding failed; previous image retained.";
        previewStatus.hidden = false;
        return;
      }
      if (response.operation === "render" || response.operation === "slice") {
        currentRender = undefined;
        imageKey = "";
        colorTrackpad.setAttribute("aria-busy", "false");
      }
      plotStatus.hidden = false;
      plotStatus.textContent = "Color engine error";
      return;
    }
    if (response.kind === "colorchecker") {
      if (response.id === checkerId && response.profile === selectedView) {
        parsePatches(response.points);
        void displayColorchecker(response);
      }
      return;
    }
    if (response.kind === "set") {
      if (
        response.id !== setId ||
        response.values.length < 4
      )
        return;
      setAllCode({
        j: response.values[1],
        x: response.values[2],
        y: response.values[3],
      });
      if (response.values[0] > 0.5) updatePatchCandidate(false);
      else {
        activePatch = null;
        activeTarget = null;
        updatePatchLocators();
      }
      schedule();
      return;
    }
    if (response.kind === "evaluate") {
      if (responseMayAdvanceDuringGesture(response) && response.id > latestValueResponseId) {
        latestValueResponseId = response.id;
        displayValues(response.values);
      }
      return;
    }
    if (response.kind === "preview") {
      queuePreview(response);
      return;
    }
    if (response.kind === "slice") {
      const render = currentRender;
      if (
        !render ||
        response.id !== render.id ||
        response.profile !== render.profile ||
        response.width !== render.width ||
        response.height !== render.height ||
        response.j !== render.j || response.fullRec2020 !== render.fullRec2020
      )
        return;
      void displaySlice(response, render.key);
    }
  };
});

function jTrackwheelEventTime(event: PointerEvent) {
  return Number.isFinite(event.timeStamp) && event.timeStamp > 0
    ? event.timeStamp
    : performance.now();
}
function beginJTrackwheelMotion(event: PointerEvent, surface: "trackwheel" | "page" = "trackwheel") {
  jTrackwheelLastX = event.clientX;
  jTrackwheelLastY = event.clientY;
  jTrackwheelLastTime = jTrackwheelEventTime(event);
  jTrackwheelVelocityX = 0;
  jTrackwheelVelocityY = 0;
  jTrackwheelSnapHeld = false;
  jTrackwheelDeferredDeltaY = 0;
  jTrackwheelDeferredJ = realCode.j;
  jTrackwheelDeferredAcceleration = 1;
  jTrackwheelSnapTargetValue = null;
  activeAxis = "j";
  jTrackwheelSurface = surface;
  jTrackwheel.dataset.tracking = "drag-active";
  jTrackwheel.dataset.trackingSurface = surface;
  jTrackwheelBody.classList.add("is-tracking");
  jTrackwheel.dataset.snapHeld = "false";
  jTrackwheel.dataset.deferredDeltaY = "0";
  jNumber.blur();
}
function applyJTrackwheelMotion(event: PointerEvent) {
  const rect = jTrackwheel.getBoundingClientRect();
  const deltaX = event.clientX - jTrackwheelLastX;
  const deltaY = event.clientY - jTrackwheelLastY;
  const eventTime = jTrackwheelEventTime(event);
  const elapsedMs = Math.max(1, eventTime - jTrackwheelLastTime);
  const velocity = trackMotionVelocity(
    { x: jTrackwheelVelocityX, y: jTrackwheelVelocityY },
    deltaX,
    deltaY,
    rect.height,
    rect.height,
    elapsedMs,
  );
  jTrackwheelVelocityX = velocity.x;
  jTrackwheelVelocityY = velocity.y;
  jTrackwheelLastX = event.clientX;
  jTrackwheelLastY = event.clientY;
  jTrackwheelLastTime = eventTime;
  if (deltaX === 0 && deltaY === 0) return;
  const acceleration = trackMotionAcceleration(Math.hypot(velocity.x, velocity.y));
  jTrackwheelDeferredAcceleration = acceleration;
  if (jTrackwheelSnapHeld) {
    jTrackwheelDeferredDeltaY += deltaY;
    jTrackwheelDeferredJ = trackwheelDelta(
      jTrackwheelDeferredJ,
      deltaY,
      rect.height,
      TRACK_SENSITIVITY,
      acceleration,
    );
    jTrackwheel.dataset.deferredDeltaY = jTrackwheelDeferredDeltaY.toFixed(6);
    if (jTrackwheelSnapTargetValue !== null &&
        Math.abs(jTrackwheelDeferredJ - jTrackwheelSnapTargetValue) > J_SNAP_DISTANCE) {
      // The hidden accelerated position has left the captured snap band. Make
      // the frozen trackwheel catch up by the complete deferred pointer distance,
      // then return to ordinary live tracking for the rest of the gesture.
      const deferredDeltaY = jTrackwheelDeferredDeltaY;
      invalidatePendingSet();
      activeAxis = "j";
      jTrackwheelTextureOffset += deferredDeltaY;
      setRealCode("j", jTrackwheelDeferredJ);
      const nextSnapValue = updatePatchCandidate(true, true);
      if (nextSnapValue !== null) {
        jTrackwheelSnapHeld = true;
        jTrackwheelSnapTargetValue = nextSnapValue;
        jTrackwheelDeferredJ = realCode.j;
        jTrackwheelDeferredDeltaY = 0;
      } else {
        jTrackwheelSnapHeld = false;
        jTrackwheelSnapTargetValue = null;
        jTrackwheelDeferredJ = realCode.j;
        jTrackwheelDeferredDeltaY = 0;
      }
      jTrackwheel.dataset.snapHeld = String(jTrackwheelSnapHeld);
      jTrackwheel.dataset.deferredDeltaY = jTrackwheelDeferredDeltaY.toFixed(6);
      schedule();
    }
    event.preventDefault();
    return;
  }
  jTrackwheelTextureOffset += deltaY;
  invalidatePendingSet();
  activeAxis = "j";
  setRealCode(
    "j",
    trackwheelDelta(
      realCode.j,
      deltaY,
      rect.height,
      TRACK_SENSITIVITY,
      acceleration,
    ),
  );
  // J′ snapping is meaningful only when the trackwheel actually changes J′. A
  // horizontal-only pointer move contributes to acceleration but must not
  // project a nearby ruler target. Numeric, keyboard, and programmatic
  // updates intentionally pass the default false.
  const snapValue = updatePatchCandidate(true, deltaY !== 0);
  if (snapValue !== null) {
    jTrackwheelSnapHeld = true;
    jTrackwheelSnapTargetValue = snapValue;
    jTrackwheelDeferredJ = realCode.j;
    jTrackwheel.dataset.snapHeld = "true";
  }
  schedule();
  event.preventDefault();
}
function finishJTrackwheelInteraction(scheduleFinal = true) {
  const capturedPointer = jTrackwheelPointerId;
  const surface = jTrackwheelSurface;
  const wasActive = capturedPointer !== null;
  if (wasActive && jTrackwheelSnapHeld && jTrackwheelSnapTargetValue !== null) {
    // Releasing inside the captured snap band commits the value the user can
    // see. Deferred travel exists only to detect an in-gesture escape; it must
    // not produce a second trackwheel/value jump after the pointer is released.
    invalidatePendingSet();
    activeAxis = "j";
    setRealCode("j", jTrackwheelSnapTargetValue);
    setDisplayedCode({ ...code, j: jTrackwheelSnapTargetValue });
  }
  jTrackwheelPointerId = null;
  jTrackwheelSurface = null;
  if (capturedPointer !== null) {
    try {
      if (surface === "page" && appShell.hasPointerCapture?.(capturedPointer))
        appShell.releasePointerCapture(capturedPointer);
      else if (surface === "trackwheel" && jTrackwheelBody.hasPointerCapture?.(capturedPointer))
        jTrackwheelBody.releasePointerCapture(capturedPointer);
    } catch {
      // Synthetic events and browsers without active capture may have no capture.
    }
  }
  jTrackwheelVelocityX = 0;
  jTrackwheelVelocityY = 0;
  jTrackwheelLastTime = 0;
  jTrackwheelSnapHeld = false;
  jTrackwheelDeferredDeltaY = 0;
  jTrackwheelDeferredJ = realCode.j;
  jTrackwheelDeferredAcceleration = 1;
  jTrackwheelSnapTargetValue = null;
  jTrackwheel.dataset.tracking = "idle";
  jTrackwheel.dataset.trackingSurface = "none";
  jTrackwheel.dataset.snapHeld = "false";
  jTrackwheel.dataset.deferredDeltaY = "0";
  jTrackwheelBody.classList.remove("is-tracking");
  if (!wasActive) return;
  activeAxis = null;
  jNumber.value = code.j.toFixed(3);
  if (scheduleFinal) schedule();
}
jTrackwheelBody.addEventListener("pointerdown", (event) => {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  if (event.pointerType !== "mouse" && event.pointerType !== "touch" && event.pointerType !== "pen") return;
  if (jTrackwheelPointerId !== null) return;
  cancelTrackpadTracking();
  jTrackwheelPointerId = event.pointerId;
  beginJTrackwheelMotion(event);
  try {
    jTrackwheelBody.setPointerCapture?.(event.pointerId);
  } catch {
    // Synthetic events and browsers without active capture can reject this.
  }
  event.stopPropagation();
  event.preventDefault();
});
jTrackwheelBody.addEventListener("pointermove", (event) => {
  if (event.pointerId !== jTrackwheelPointerId) return;
  applyJTrackwheelMotion(event);
});
jTrackwheelBody.addEventListener("pointerup", (event) => {
  if (event.pointerId !== jTrackwheelPointerId) return;
  finishJTrackwheelInteraction();
  event.preventDefault();
});
jTrackwheelBody.addEventListener("pointercancel", (event) => {
  if (event.pointerId !== jTrackwheelPointerId) return;
  finishJTrackwheelInteraction();
});
jTrackwheelBody.addEventListener("lostpointercapture", (event) => {
  if (event.pointerId !== jTrackwheelPointerId) return;
  finishJTrackwheelInteraction();
});

function isBlankPageTouchTarget(target: EventTarget | null) {
  if (!(target instanceof Element)) return true;
  if (target.closest([
    ".j-trackwheel-body", ".color-trackpad", ".preview", ".preview-column", ".image-panel",
    ".view-menu", "dialog", ".app-footer", "button", "input", "select",
    "textarea", "a", "label", "[role='button']", "[contenteditable='true']",
  ].join(","))) return false;
  return Boolean(target.closest(".app-shell, body"));
}
function beginPageJTrackwheelGesture(event: PointerEvent) {
  if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
  if (event.isPrimary === false || jTrackwheelPointerId !== null || trackpadTouchPointerId !== null ||
      previewPointerId !== null || imageTouchPointerId !== null) return;
  if (!viewMenu.hidden || imageOptionsDialog.open || !isBlankPageTouchTarget(event.target)) return;
  cancelTrackpadTracking();
  jTrackwheelPointerId = event.pointerId;
  beginJTrackwheelMotion(event, "page");
  try { appShell.setPointerCapture?.(event.pointerId); } catch { /* synthetic events */ }
  event.preventDefault();
}
document.addEventListener("pointerdown", beginPageJTrackwheelGesture);
document.addEventListener("pointermove", event => {
  if (jTrackwheelSurface !== "page" || event.pointerId !== jTrackwheelPointerId) return;
  applyJTrackwheelMotion(event);
}, { passive: false });
document.addEventListener("pointerup", event => {
  if (jTrackwheelSurface !== "page" || event.pointerId !== jTrackwheelPointerId) return;
  finishJTrackwheelInteraction();
  event.preventDefault();
}, { passive: false });
document.addEventListener("pointercancel", event => {
  if (jTrackwheelSurface !== "page" || event.pointerId !== jTrackwheelPointerId) return;
  finishJTrackwheelInteraction();
}, { passive: false });
appShell.addEventListener("lostpointercapture", event => {
  if (jTrackwheelSurface !== "page" || event.pointerId !== jTrackwheelPointerId) return;
  finishJTrackwheelInteraction();
});
document.addEventListener("contextmenu", event => {
  if (event.target instanceof HTMLImageElement) event.preventDefault();
});
document.addEventListener("dragstart", event => {
  if (event.target instanceof HTMLImageElement) event.preventDefault();
});
jTrackwheel.addEventListener("keydown", (event) => {
  const step = event.shiftKey ? 0.05 : 0.01;
  let delta = 0;
  if (event.key === "ArrowUp") delta = step;
  else if (event.key === "ArrowDown") delta = -step;
  else if (event.key === "Home") delta = -1;
  else if (event.key === "End") delta = 1;
  else return;
  event.preventDefault();
  finishJTrackwheelInteraction(false);
  invalidatePendingSet();
  activeAxis = "j";
  setRealCode("j", event.key === "Home" ? 0 : event.key === "End" ? 1 : realCode.j + delta);
  updatePatchCandidate();
  activeAxis = null;
  schedule();
});

function applyJNumber(format = false) {
  const value = Number(jNumber.value);
  if (!Number.isFinite(value)) {
    if (format) jNumber.value = code.j.toFixed(3);
    return;
  }
  finishJTrackwheelInteraction(false);
  invalidatePendingSet();
  activeAxis = "j";
  setRealCode("j", value);
  updatePatchCandidate();
  activeAxis = null;
  if (format) jNumber.value = code.j.toFixed(3);
  schedule();
}
jNumber.addEventListener("input", () => applyJNumber());
jNumber.addEventListener("change", () => applyJNumber(true));
jNumber.addEventListener("blur", () => {
  jNumber.value = code.j.toFixed(3);
});

function applyCoordinateNumber(axis: "x" | "y", input: HTMLInputElement, format = false) {
  const value = Number(input.value);
  if (!Number.isFinite(value)) {
    if (format) input.value = code[axis].toFixed(3);
    return;
  }
  cancelTrackpadTracking();
  invalidatePendingSet();
  setRealCode(axis, value);
  // Numeric coordinate edits may update candidate diagnostics, but never
  // project onto a Cartesian snap target. Pointer movement owns snapping.
  updatePatchCandidate(false);
  setDisplayedCode(realCode);
  if (format) input.value = code[axis].toFixed(3);
  schedule();
}
for (const [axis, input] of [["x", xNumber], ["y", yNumber]] as const) {
  input.addEventListener("input", () => applyCoordinateNumber(axis, input));
  input.addEventListener("change", () => applyCoordinateNumber(axis, input, true));
  input.addEventListener("blur", () => { input.value = code[axis].toFixed(3); });
}

function applyTrackpadPointer(event: PointerEvent) {
  const point = slicePoint(event.clientX, event.clientY, gamutSliceImage.getBoundingClientRect());
  invalidatePendingSet();
  activeAxis = "xy";
  setRealCode("x", point.x);
  setRealCode("y", point.y);
  updatePatchCandidate();
  schedule();
}
function cancelTrackpadTracking() {
  trackpadTrackingActive = false;
  colorTrackpad.classList.remove("trackpad-tracking");
  colorTrackpad.dataset.trackpadTracking = "idle";
  if (trackpadTouchPointerId !== null) {
    try {
      if (colorTrackpad.hasPointerCapture?.(trackpadTouchPointerId)) colorTrackpad.releasePointerCapture(trackpadTouchPointerId);
    } catch { /* capture may already be released */ }
  }
  trackpadTouchPointerId = null;
  trackpadTouchVelocityX = 0;
  trackpadTouchVelocityY = 0;
  trackpadTouchLastTime = 0;
  activeAxis = null;
  updatePlotLabel();
}
function commitTrackpadTracking(event?: PointerEvent) {
  if (!trackpadTrackingActive) return;
  if (event && event.target === gamutSliceImage) applyTrackpadPointer(event);
  cancelTrackpadTracking();
  schedule();
}
colorTrackpad.addEventListener("pointerdown", (event) => {
  if (event.pointerType === "mouse") {
    if (event.button !== 0) return;
    if (!trackpadTrackingActive) {
      trackpadTrackingActive = true;
      colorTrackpad.classList.add("trackpad-tracking");
      colorTrackpad.dataset.trackpadTracking = "active";
      applyTrackpadPointer(event);
    } else {
      commitTrackpadTracking(event);
    }
    event.stopPropagation();
    event.preventDefault();
    return;
  }
  if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
  // Color trackpad and trackwheel gestures are mutually exclusive. A touch/pen
  // trackpad start
  // must terminate any document-level mouse trackwheel tracking left by a desktop
  // pointer sequence before capturing this pointer.
  finishJTrackwheelInteraction(false);
  cancelTrackpadTracking();
  trackpadTouchPointerId = event.pointerId;
  trackpadTouchLastX = event.clientX;
  trackpadTouchLastY = event.clientY;
  trackpadTouchLastTime = Number.isFinite(event.timeStamp) && event.timeStamp > 0 ? event.timeStamp : performance.now();
  trackpadTouchVelocityX = 0;
  trackpadTouchVelocityY = 0;
  activeAxis = "xy";
  colorTrackpad.dataset.trackpadTracking = "touch-active";
  colorTrackpad.classList.add("trackpad-tracking");
  updatePlotLabel();
  try { colorTrackpad.setPointerCapture?.(event.pointerId); } catch { /* synthetic events */ }
  event.preventDefault();
});
document.addEventListener("pointermove", (event) => {
  if (!trackpadTrackingActive || event.pointerType !== "mouse") return;
  applyTrackpadPointer(event);
});
document.addEventListener("pointerdown", (event) => {
  if (!trackpadTrackingActive || event.pointerType !== "mouse" || event.button !== 0)
    return;
  if (event.target !== gamutSliceImage) commitTrackpadTracking();
});
colorTrackpad.addEventListener("pointermove", (event) => {
  if ((event.pointerType !== "touch" && event.pointerType !== "pen") || event.pointerId !== trackpadTouchPointerId) return;
  const rect = colorTrackpad.getBoundingClientRect();
  const dx = event.clientX - trackpadTouchLastX;
  const dy = event.clientY - trackpadTouchLastY;
  const eventTime = Number.isFinite(event.timeStamp) && event.timeStamp > 0 ? event.timeStamp : performance.now();
  const elapsedMs = Math.max(1, eventTime - trackpadTouchLastTime);
  const velocity = trackMotionVelocity({ x: trackpadTouchVelocityX, y: trackpadTouchVelocityY }, dx, dy, rect.width, rect.height, elapsedMs);
  trackpadTouchVelocityX = velocity.x;
  trackpadTouchVelocityY = velocity.y;
  trackpadTouchLastX = event.clientX;
  trackpadTouchLastY = event.clientY;
  trackpadTouchLastTime = eventTime;
  const acceleration = trackMotionAcceleration(Math.hypot(velocity.x, velocity.y));
  const next = trackpadDelta(realCode.x, realCode.y, dx, dy, rect.width, rect.height, TRACK_SENSITIVITY, acceleration);
  invalidatePendingSet();
  setRealCode("x", next.x);
  setRealCode("y", next.y);
  updatePatchCandidate();
  schedule();
  event.preventDefault();
});
function finishSliceTouch(event: PointerEvent) {
  if (event.pointerId !== trackpadTouchPointerId) return;
  try { if (colorTrackpad.hasPointerCapture?.(event.pointerId)) colorTrackpad.releasePointerCapture(event.pointerId); } catch { /* synthetic events */ }
  trackpadTouchPointerId = null;
  trackpadTouchVelocityX = 0;
  trackpadTouchVelocityY = 0;
  trackpadTouchLastTime = 0;
  colorTrackpad.dataset.trackpadTracking = "idle";
  colorTrackpad.classList.remove("trackpad-tracking");
  activeAxis = null;
  updatePlotLabel();
  schedule();
}
colorTrackpad.addEventListener("pointerup", finishSliceTouch);
colorTrackpad.addEventListener("pointercancel", finishSliceTouch);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    cancelTrackpadTracking();
    finishJTrackwheelInteraction();
    finishPreviewDrag();
    if (imageTrackingActive) finishImageTracking();
  }
});
let previewPointerId: number | null = null;
let previewStartX = 0;
let previewStartY = 0;
let previewLastY = 0;
let previewLastTime = 0;
let previewVelocityX = 0;
let previewVelocityY = 0;
let previewDragging = false;
let previewSuppressClick = false;
function finishPreviewDrag(scheduleFinal = true) {
  if (previewPointerId === null) return false;
  const capturedPointer = previewPointerId;
  const dragged = previewDragging;
  previewPointerId = null;
  try { if (preview.hasPointerCapture?.(capturedPointer)) preview.releasePointerCapture(capturedPointer); } catch { /* best effort */ }
  previewDragging = false;
  previewVelocityX = previewVelocityY = 0;
  backgroundTracking = false;
  preview.dataset.tracking = "idle";
  if (dragged && scheduleFinal) schedule();
  return dragged;
}
function applyPreviewDrag(event: PointerEvent) {
  if (previewPointerId === null || event.pointerId !== previewPointerId) return;
  const rect = preview.getBoundingClientRect();
  const eventTime = jTrackwheelEventTime(event);
  const elapsed = Math.max(1, eventTime - previewLastTime);
  const dx = event.clientX - previewStartX;
  const dy = event.clientY - previewLastY;
  previewStartX = event.clientX;
  previewLastY = event.clientY;
  const velocity = trackMotionVelocity(
    { x: previewVelocityX, y: previewVelocityY },
    dx,
    dy,
    rect.height,
    rect.height,
    elapsed,
  );
  previewVelocityX = velocity.x; previewVelocityY = velocity.y; previewLastTime = eventTime;
  if (!previewDragging && Math.abs(event.clientY - previewStartY) < 6) return;
  previewDragging = true;
  preview.dataset.tracking = "active";
  const acceleration = trackMotionAcceleration(Math.hypot(velocity.x, velocity.y));
  realBackgroundJ = trackwheelDelta(realBackgroundJ, dy, rect.height, TRACK_SENSITIVITY, acceleration);
  invalidatePendingSet();
  // A real Background gesture is the only operation allowed to create a snap.
  updateBackground(true);
  schedule();
  event.preventDefault();
}
preview.addEventListener("pointerdown", event => {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  if (previewPointerId !== null) return;
  previewPointerId = event.pointerId;
  backgroundTracking = true;
  previewStartX = event.clientX; previewStartY = event.clientY; previewLastY = event.clientY;
  previewLastTime = jTrackwheelEventTime(event); previewVelocityX = previewVelocityY = 0; previewDragging = false;
  try { preview.setPointerCapture(event.pointerId); } catch { /* best effort */ }
  event.preventDefault();
});
preview.addEventListener("pointermove", applyPreviewDrag);
preview.addEventListener("pointerup", event => {
  if (event.pointerId !== previewPointerId) return;
  const dragged = finishPreviewDrag();
  if (dragged) {
    previewSuppressClick = true;
    window.setTimeout(() => { previewSuppressClick = false; }, 300);
    event.preventDefault();
  }
});
preview.addEventListener("pointercancel", event => {
  if (event.pointerId !== previewPointerId) return;
  finishPreviewDrag();
});
preview.addEventListener("lostpointercapture", event => {
  if (event.pointerId !== previewPointerId) return;
  finishPreviewDrag();
});
preview.addEventListener("click", event => {
  if (previewSuppressClick) { previewSuppressClick = false; event.preventDefault(); event.stopPropagation(); return; }
  openViewMenu();
});
viewButtons.forEach(button => button.addEventListener("click", () => {
  const view = Number(button.dataset.view) as ViewId;
  if (VIEW_IDS.includes(view)) chooseView(view);
}));
viewMenu.addEventListener("keydown", event => {
  const index = viewButtons.indexOf(document.activeElement as HTMLButtonElement);
  let next: number | undefined;
  if (event.key === "ArrowDown") next = (index + 1) % viewButtons.length;
  if (event.key === "ArrowUp") next = (index + viewButtons.length - 1) % viewButtons.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = viewButtons.length - 1;
  if (next !== undefined) { event.preventDefault(); viewButtons[next].focus(); }
  if (event.key === "Escape") { event.preventDefault(); closeViewMenu(true); }
  if (event.key === "Tab") closeViewMenu();
});
document.addEventListener("pointerdown", event => {
  if (!viewMenu.hidden && !viewMenu.contains(event.target as Node) && !preview.contains(event.target as Node)) closeViewMenu();
});
window.addEventListener("resize", () => {
  closeViewMenu();
  updateJTrackwheelVisual();
  updateImageGeometry();
  drawImageOverlay();
  // Grid track sizes settle after the resize event.  A queued task catches
  // browsers that deliver ResizeObserver after the next layout read.
  window.setTimeout(() => updateJTrackwheelVisual(), 0);
});
// Resize events can fire before the grid has applied its new track size.  The
// observer runs after layout, ensuring the free trackwheel texture is rescaled to
// the actual companion height rather than the stale pre-resize height.
if (typeof ResizeObserver !== "undefined") {
  new ResizeObserver(() => updateJTrackwheelVisual()).observe(jTrackwheel);
}
window.addEventListener("pagehide", () => {
  pageClosed = true;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  if (sliceUrl) URL.revokeObjectURL(sliceUrl);
  if (colorcheckerUrl) URL.revokeObjectURL(colorcheckerUrl);
  if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
  if (imageLoupeUrl) URL.revokeObjectURL(imageLoupeUrl);
});
window.addEventListener("pageshow", () => {
  if (pageClosed) { pageClosed = false; schedule(); }
});
copyValue.addEventListener("click", async () => {
  try {
    await navigator.clipboard?.writeText(encodedValue.value);
  } catch {
    encodedValue.focus();
    encodedValue.select();
  }
});
setValue.addEventListener("click", setFromHex);
encodedValue.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    setFromHex();
  }
});
encodedLabel.addEventListener("click", (event) => {
  const target = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-encoded-mode]");
  if (!target) return;
  encodedReadoutMode = target.dataset.encodedMode === "jxy" ? "jxy" : "ap1";
  renderEncodedLabel();
  updateEncodedReadout(undefined, lastEvaluationValid);
});

setAllCode(code);
renderEncodedLabel();
updateEncodedReadout();
setRec2020AuthoringOptions(fullRec2020);
paintCheckerboard();
drawIndicators();
colorTrackpad.dataset.trackpadTracking = "idle";
jTrackwheel.dataset.tracking = "idle";
jTrackwheel.dataset.snapHeld = "false";
jTrackwheel.dataset.deferredDeltaY = "0";
imageViewport.dataset.tracking = "idle";
jReferenceTick.style.bottom = `${J_REFERENCE_WHITE * 100}%`;
jReferenceTick.title = `203 nits HDR white — J\u2032 ${J_REFERENCE_WHITE.toFixed(6)}`;
realBackgroundJ = 0.15;
updateBackground();
requestPatches(true);
requestEvaluate();
requestRender();
