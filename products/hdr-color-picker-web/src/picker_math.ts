export const PATCH_ENTRY_RADIUS = 0.02;
export const PATCH_SNAP_DISTANCE = 0.005;
export const J_SNAP_DISTANCE = 0.005;
export const BACKGROUND_J_SNAP_DISTANCE = 0.01;
// Background is a normalized J' neutral coordinate.
export const BACKGROUND_MAX = 1.0;
export const J_HK_PEAK = 217.2768649129496;
export const J_REFERENCE_WHITE = 100 / J_HK_PEAK;
export const TRACK_SENSITIVITY = 0.25;
export const TRACK_MAX_ACCELERATION = 4;
export const TRACK_ACCELERATION_SPEED = 2.5;
export const TRACK_VELOCITY_SMOOTHING_MS = 45;

export type Point = { x: number; y: number };
export type CovarianceEllipse = {
  mean: Point;
  covariance: [number, number, number, number];
  major: number;
  minor: number;
  angle: number;
  confidence: number;
  sampleCount: number;
  subsetSize: number;
};
export type SnapCandidate =
  | { kind: "neutral"; x: number; y: number }
  | { kind: "patch"; index: number; x: number; y: number }
  | { kind: "average"; x: number; y: number };
export type JSnapTarget =
  | { kind: "reference"; value: number }
  | { kind: "patch"; value: number }
  | { kind: "average"; value: number };
export type BackgroundJSnapTarget =
  | { kind: "foreground"; value: number }
  | { kind: "reference"; value: number };
export type SnapAxis = "j" | "xy" | null;

export function clamp(value: number, minimum: number, maximum: number): number {
  return Number.isFinite(value)
    ? Math.max(minimum, Math.min(maximum, value))
    : minimum;
}

export function clamp01(value: number): number {
  return clamp(value, 0, 1);
}

export function slicePoint(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): Point {
  const width = Number.isFinite(rect.width) && rect.width > 0 ? rect.width : 1;
  const height = Number.isFinite(rect.height) && rect.height > 0 ? rect.height : 1;
  return {
    x: clamp01((clientX - rect.left) / width),
    y: clamp01(1 - (clientY - rect.top) / height),
  };
}

export function trackwheelDelta(
  j: number,
  deltaY: number,
  height: number,
  sensitivity = TRACK_SENSITIVITY,
  acceleration = 1,
): number {
  const scale = Number.isFinite(height) && height > 0 ? height : 1;
  const factor = Number.isFinite(sensitivity)
    ? sensitivity
    : TRACK_SENSITIVITY;
  const speedFactor = Number.isFinite(acceleration)
    ? Math.max(0, Math.min(TRACK_MAX_ACCELERATION, acceleration))
    : 1;
  return clamp01(j - (deltaY / scale) * factor * speedFactor);
}

export function trackpadDelta(
  x: number,
  y: number,
  deltaX: number,
  deltaY: number,
  width: number,
  height: number,
  sensitivity = TRACK_SENSITIVITY,
  acceleration = 1,
): Point {
  const scaleX = Number.isFinite(width) && width > 0 ? width : 1;
  const scaleY = Number.isFinite(height) && height > 0 ? height : 1;
  const factor = Number.isFinite(sensitivity) ? sensitivity : TRACK_SENSITIVITY;
  const speedFactor = Number.isFinite(acceleration)
    ? Math.max(0, Math.min(TRACK_MAX_ACCELERATION, acceleration))
    : 1;
  return {
    x: clamp01(x + (deltaX / scaleX) * factor * speedFactor),
    y: clamp01(y - (deltaY / scaleY) * factor * speedFactor),
  };
}

export function trackMotionAcceleration(normalizedSpeed: number): number {
  const speed = Math.max(0, Number.isFinite(normalizedSpeed) ? normalizedSpeed : 0);
  return Math.min(
    TRACK_MAX_ACCELERATION,
    1 + (TRACK_MAX_ACCELERATION - 1) *
      (1 - Math.exp(-speed / TRACK_ACCELERATION_SPEED)),
  );
}

export function trackMotionVelocity(
  previous: Point,
  deltaX: number,
  deltaY: number,
  width: number,
  height: number,
  elapsedMs: number,
  smoothingMs = TRACK_VELOCITY_SMOOTHING_MS,
): Point {
  const scaleX = Number.isFinite(width) && width > 0 ? width : 1;
  const scaleY = Number.isFinite(height) && height > 0 ? height : 1;
  const elapsed = Math.max(1, Number.isFinite(elapsedMs) ? elapsedMs : 1);
  const smoothing = Math.max(
    1,
    Number.isFinite(smoothingMs)
      ? smoothingMs
      : TRACK_VELOCITY_SMOOTHING_MS,
  );
  const alpha = 1 - Math.exp(-elapsed / smoothing);
  const rawX = (deltaX / scaleX) * (1000 / elapsed);
  const rawY = (deltaY / scaleY) * (1000 / elapsed);
  return {
    x: previous.x + (rawX - previous.x) * alpha,
    y: previous.y + (rawY - previous.y) * alpha,
  };
}

export function canvasPoint(
  x: number,
  y: number,
  size: number,
): [number, number] {
  const extent = Math.max(0, size - 1);
  return [clamp01(x) * extent, (1 - clamp01(y)) * extent];
}

export function patchCandidate(
  x: number,
  y: number,
  patches: readonly Point[],
): number | null {
  let nearest: number | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  patches.forEach((patch, index) => {
    const distance = Math.hypot(x - patch.x, y - patch.y);
    if (distance < nearestDistance) {
      nearest = index;
      nearestDistance = distance;
    }
  });
  return nearestDistance <= PATCH_ENTRY_RADIUS ? nearest : null;
}

export function nearestPoint(
  x: number,
  y: number,
  points: readonly Point[],
): { index: number; distance: number } | null {
  let nearest: { index: number; distance: number } | null = null;
  points.forEach((point, index) => {
    const distance = Math.hypot(x - point.x, y - point.y);
    if (nearest === null || distance < nearest.distance)
      nearest = { index, distance };
  });
  return nearest;
}

/** Select the nearest ColorChecker/neutral target only while inside the entry halo. */
export function nearestSnapTarget(
  x: number,
  y: number,
  patches: readonly Point[],
  neutral: Point = { x: 0.5, y: 0.5 },
  average?: Point,
): SnapCandidate | null {
  const nearestPatch = nearestPoint(x, y, patches);
  const neutralDistance = Math.hypot(x - neutral.x, y - neutral.y);
  const averageDistance = average ? Math.hypot(x - average.x, y - average.y) : Number.POSITIVE_INFINITY;
  const nearestDistance = nearestPatch?.distance ?? Number.POSITIVE_INFINITY;
  if (average && averageDistance <= PATCH_ENTRY_RADIUS && averageDistance < nearestDistance && averageDistance < neutralDistance)
    return { kind: "average", x: average.x, y: average.y };
  if (
    neutralDistance <= PATCH_ENTRY_RADIUS &&
    neutralDistance <= nearestDistance
  ) {
    return { kind: "neutral", x: neutral.x, y: neutral.y };
  }
  if (nearestPatch && nearestPatch.distance <= PATCH_ENTRY_RADIUS) {
    const patch = patches[nearestPatch.index];
    return {
      kind: "patch",
      index: nearestPatch.index,
      x: patch.x,
      y: patch.y,
    };
  }
  return null;
}

/** Select the nearest J target: the active patch, when present, and reference white. */
export function nearestJSnapTarget(
  j: number,
  patchJ?: number,
  referenceJ = J_REFERENCE_WHITE,
  threshold = J_SNAP_DISTANCE,
  averageJ?: number,
): JSnapTarget | null {
  const candidates: JSnapTarget[] = [];
  if (Number.isFinite(patchJ)) candidates.push({ kind: "patch", value: patchJ as number });
  if (Number.isFinite(averageJ)) candidates.push({ kind: "average", value: averageJ as number });
  if (Number.isFinite(referenceJ)) candidates.push({ kind: "reference", value: referenceJ });
  let nearest: JSnapTarget | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const candidate of candidates) {
    const distance = Math.abs(j - candidate.value);
    // Keep patch-first ordering on an exact tie.
    if (distance < nearestDistance) {
      nearest = candidate;
      nearestDistance = distance;
    }
  }
  return nearest && nearestDistance <= threshold ? nearest : null;
}

export function nearestBackgroundJSnapTarget(
  backgroundJ: number,
  foregroundJ: number,
  referenceJ = J_REFERENCE_WHITE,
  threshold = BACKGROUND_J_SNAP_DISTANCE,
): BackgroundJSnapTarget | null {
  const target = nearestJSnapTarget(
    backgroundJ,
    foregroundJ,
    referenceJ,
    threshold,
  );
  if (target?.kind === "patch")
    return { kind: "foreground", value: target.value };
  if (target?.kind === "reference") return target;
  return null;
}

export function snapCartesianPoint(
  x: number,
  y: number,
  targetX: number,
  targetY: number,
  threshold = PATCH_SNAP_DISTANCE,
): Point {
  return Math.hypot(x - targetX, y - targetY) <= threshold
    ? { x: targetX, y: targetY }
    : { x, y };
}

export function projectSnapCode(
  real: { j: number; x: number; y: number },
  target: SnapCandidate | null,
  patchJ?: number,
  axis: SnapAxis = null,
  previous = real,
  averageJ?: number,
  allowJSnap = true,
): { j: number; x: number; y: number } {
  const projected = axis === null ? { ...real } : { ...previous };
  if (axis === "j") projected.j = real.j;
  else if (axis === "xy") {
    projected.x = real.x;
    projected.y = real.y;
  }
  if (axis !== "xy" && allowJSnap) {
    const jTarget = nearestJSnapTarget(
      real.j,
      target?.kind === "patch" ? patchJ : undefined,
      J_REFERENCE_WHITE,
      J_SNAP_DISTANCE,
      averageJ,
    );
    if (jTarget) projected.j = jTarget.value;
  }
  if (target && axis !== "j") {
    const snapped = snapCartesianPoint(real.x, real.y, target.x, target.y);
    projected.x = snapped.x;
    projected.y = snapped.y;
  }
  return projected;
}

export function snapCoordinate(
  value: number,
  target: number,
  threshold = PATCH_SNAP_DISTANCE,
): number {
  return Math.abs(value - target) <= threshold ? target : value;
}

/** Return the native integer pixels whose centers lie in a circular radius. */
export function neighborhoodPixels(
  centerX: number,
  centerY: number,
  width: number,
  height: number,
  radius = 3,
): Array<[number, number]> {
  const w = Math.max(0, Math.floor(width));
  const h = Math.max(0, Math.floor(height));
  const cx = Math.max(0, Math.min(w - 1, Math.round(centerX)));
  const cy = Math.max(0, Math.min(h - 1, Math.round(centerY)));
  const r = Math.max(0, Number.isFinite(radius) ? radius : 3);
  const out: Array<[number, number]> = [];
  const minX = Math.max(0, Math.floor(cx - r));
  const maxX = Math.min(w - 1, Math.ceil(cx + r));
  const minY = Math.max(0, Math.floor(cy - r));
  const maxY = Math.min(h - 1, Math.ceil(cy + r));
  for (let y = minY; y <= maxY; y += 1)
    for (let x = minX; x <= maxX; x += 1)
      if (Math.hypot(x - cx, y - cy) <= r + 1e-12) out.push([x, y]);
  return out;
}

const COVARIANCE_FLOOR = 1e-9;

function comparePoint(a: Point, b: Point): number {
  return a.x - b.x || a.y - b.y;
}

function compareIndexSet(a: readonly number[], b: readonly number[]): number {
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function covarianceForIndices(
  points: readonly Point[],
  indices: readonly number[],
): { mean: Point; covariance: [number, number, number, number]; determinant: number } {
  const mean = indices.reduce(
    (sum, index) => ({ x: sum.x + points[index].x, y: sum.y + points[index].y }),
    { x: 0, y: 0 },
  );
  mean.x /= indices.length;
  mean.y /= indices.length;
  let xx = 0, xy = 0, yy = 0;
  for (const index of indices) {
    const dx = points[index].x - mean.x;
    const dy = points[index].y - mean.y;
    xx += dx * dx;
    xy += dx * dy;
    yy += dy * dy;
  }
  const denominator = Math.max(1, indices.length - 1);
  xx = xx / denominator + COVARIANCE_FLOOR;
  xy /= denominator;
  yy = yy / denominator + COVARIANCE_FLOOR;
  const determinant = Math.max(COVARIANCE_FLOOR ** 2, xx * yy - xy * xy);
  return { mean, covariance: [xx, xy, xy, yy], determinant };
}

function deterministicSeedSets(count: number, subsetSize: number): number[][] {
  const seedCount = Math.min(32, count);
  const seeds: number[][] = [];
  for (let seed = 0; seed < seedCount; seed += 1) {
    const phase = Math.floor(seed * count / seedCount);
    const indices = Array.from({ length: subsetSize }, (_, index) =>
      (phase + Math.floor(index * count / subsetSize)) % count,
    ).sort((a, b) => a - b);
    if (!seeds.some(existing => compareIndexSet(existing, indices) === 0)) seeds.push(indices);
  }
  return seeds;
}

function cStep(points: readonly Point[], indices: readonly number[], subsetSize: number): number[] {
  const { mean, covariance, determinant } = covarianceForIndices(points, indices);
  const [xx, xy, , yy] = covariance;
  return points
    .map((point, index) => {
      const dx = point.x - mean.x;
      const dy = point.y - mean.y;
      const distance = (yy * dx * dx - 2 * xy * dx * dy + xx * dy * dy) / determinant;
      return { index, distance: Number.isFinite(distance) ? distance : Number.POSITIVE_INFINITY };
    })
    .sort((a, b) => a.distance - b.distance || a.index - b.index)
    .slice(0, subsetSize)
    .map(entry => entry.index)
    .sort((a, b) => a - b);
}

/**
 * Build a deterministic Fast-MCD 95%-confidence ellipse. The small fixed seed
 * budget keeps continuous image-locator updates bounded while resisting a few
 * very different pixels in the sampled neighborhood.
 */
export function covarianceEllipse(
  points: readonly Point[],
  confidence = 0.95,
): CovarianceEllipse | null {
  const finitePoints = points
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
    .map(point => ({ x: point.x, y: point.y }))
    .sort(comparePoint);
  if (!finitePoints.length) return null;
  const subsetSize = finitePoints.length === 1
    ? 1
    : Math.max(2, Math.ceil(finitePoints.length / 2));
  let selected = Array.from({ length: subsetSize }, (_, index) => index);
  let selectedStats = covarianceForIndices(finitePoints, selected);
  for (const seed of deterministicSeedSets(finitePoints.length, subsetSize)) {
    let candidate = seed;
    for (let step = 0; step < 5; step += 1) {
      const next = cStep(finitePoints, candidate, subsetSize);
      if (compareIndexSet(candidate, next) === 0) break;
      candidate = next;
    }
    const stats = covarianceForIndices(finitePoints, candidate);
    const determinantDifference = stats.determinant - selectedStats.determinant;
    if (
      determinantDifference < -1e-24 ||
      (Math.abs(determinantDifference) <= 1e-24 && compareIndexSet(candidate, selected) < 0)
    ) {
      selected = candidate;
      selectedStats = stats;
    }
  }
  const { mean, covariance } = selectedStats;
  const [xx, xy, , yy] = covariance;
  const trace = xx + yy;
  const discriminant = Math.sqrt(Math.max(0, (xx - yy) * (xx - yy) + 4 * xy * xy));
  const lambdaMajor = Math.max(0, (trace + discriminant) / 2);
  const lambdaMinor = Math.max(0, (trace - discriminant) / 2);
  const angle = 0.5 * Math.atan2(2 * xy, xx - yy);
  // Chi-square(2) quantile is -2 ln(1 - confidence); clamp to a useful
  // finite interval for callers that provide an accidental invalid value.
  const c = Math.min(1 - Number.EPSILON, Math.max(Number.EPSILON, confidence));
  const scale = Math.sqrt(-2 * Math.log(1 - c));
  return {
    mean,
    covariance,
    major: Math.sqrt(Math.max(COVARIANCE_FLOOR, lambdaMajor)) * scale,
    minor: Math.sqrt(Math.max(COVARIANCE_FLOOR, lambdaMinor)) * scale,
    angle,
    confidence: c,
    sampleCount: finitePoints.length,
    subsetSize,
  };
}

export function ellipsePoint(ellipse: CovarianceEllipse, t: number): Point {
  const theta = Number.isFinite(t) ? t : 0;
  const c = Math.cos(theta), s = Math.sin(theta);
  const ca = Math.cos(ellipse.angle), sa = Math.sin(ellipse.angle);
  return {
    x: ellipse.mean.x + ellipse.major * c * ca - ellipse.minor * s * sa,
    y: ellipse.mean.y + ellipse.major * c * sa + ellipse.minor * s * ca,
  };
}

export function encodeSrgb(value: number): number {
  const linear = Math.max(0, value);
  return linear <= 0.0031308
    ? 12.92 * linear
    : 1.055 * linear ** (1 / 2.4) - 0.055;
}

export function decodeSrgb(value: number): number {
  const encoded = Math.max(0, value);
  return encoded <= 0.04045
    ? encoded / 12.92
    : ((encoded + 0.055) / 1.055) ** 2.4;
}

export function backgroundSliderPosition(value: number): number {
  return clamp(value, 0, BACKGROUND_MAX);
}

export function backgroundFromSlider(position: number): number {
  return clamp01(position);
}
