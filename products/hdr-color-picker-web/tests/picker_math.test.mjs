import assert from "node:assert/strict";
import test from "node:test";
import {
  BACKGROUND_MAX,
  BACKGROUND_J_SNAP_DISTANCE,
  J_REFERENCE_WHITE,
  J_SNAP_DISTANCE,
  TRACK_MAX_ACCELERATION,
  PATCH_ENTRY_RADIUS,
  PATCH_SNAP_DISTANCE,
  canvasPoint,
  patchCandidate,
  nearestSnapTarget,
  nearestJSnapTarget,
  nearestBackgroundJSnapTarget,
  trackpadDelta,
  trackMotionAcceleration,
  trackMotionVelocity,
  trackwheelDelta,
  neighborhoodPixels,
  covarianceEllipse,
  ellipsePoint,
  projectSnapCode,
  slicePoint,
  snapCartesianPoint,
  snapCoordinate,
} from "../src/picker_math.ts";

test("Cartesian canvas mapping keeps Y upward", () => {
  assert.deepEqual(canvasPoint(0, 0, 512), [0, 511]);
  assert.deepEqual(canvasPoint(1, 1, 512), [511, 0]);
  assert.deepEqual(canvasPoint(0.5, 0.5, 513), [256, 256]);
});

test("slice pointer mapping clamps to the Cartesian viewport", () => {
  assert.deepEqual(slicePoint(150, 200, { left: 100, top: 100, width: 100, height: 100 }), {
    x: 0.5,
    y: 0,
  });
  assert.deepEqual(slicePoint(80, 40, { left: 100, top: 100, width: 100, height: 100 }), {
    x: 0,
    y: 1,
  });
  assert.deepEqual(slicePoint(240, 260, { left: 100, top: 100, width: 100, height: 100 }), {
    x: 1,
    y: 0,
  });
});

test("candidate selection uses the reduced nearest-dot radius", () => {
  const boundaryPatch = [{ x: 0.5, y: 0.5 }];
  assert.equal(
    patchCandidate(
      0.5 + PATCH_ENTRY_RADIUS - 1e-12,
      0.5,
      boundaryPatch,
    ),
    0,
  );
  assert.equal(
    patchCandidate(0.5 + PATCH_ENTRY_RADIUS + 1e-6, 0.5, boundaryPatch),
    null,
  );

  const patches = [
    { x: 0.5, y: 0.5 },
    { x: 0.53, y: 0.5 },
  ];
  assert.equal(patchCandidate(0.52, 0.5, patches), 1);
  assert.equal(patchCandidate(0.51, 0.5, patches), 0);
});

test("candidate selection chooses the nearest patch", () => {
  const patches = [
    { x: 0.5, y: 0.5 },
    { x: 0.53, y: 0.5 },
  ];
  assert.equal(patchCandidate(0.525, 0.5, patches), 1);
});

test("neutral and ColorChecker targets compete by nearest distance", () => {
  const patches = [{ x: 0.52, y: 0.5 }];
  assert.deepEqual(nearestSnapTarget(0.501, 0.5, patches), {
    kind: "neutral",
    x: 0.5,
    y: 0.5,
  });
  assert.deepEqual(nearestSnapTarget(0.515, 0.5, patches), {
    kind: "patch",
    index: 0,
    x: 0.52,
    y: 0.5,
  });
  assert.equal(nearestSnapTarget(0.55, 0.5, patches), null);
});

test("snap band changes only the supplied coordinate", () => {
  assert.equal(snapCoordinate(0.5 + PATCH_SNAP_DISTANCE - 1e-12, 0.5), 0.5);
  assert.equal(snapCoordinate(0.5 + PATCH_SNAP_DISTANCE + 1e-6, 0.5), 0.505001);
});

test("J snap targets choose the nearest active patch or reference white", () => {
  assert.deepEqual(nearestJSnapTarget(J_REFERENCE_WHITE + 0.004), {
    kind: "reference",
    value: J_REFERENCE_WHITE,
  });
  assert.equal(
    nearestJSnapTarget(J_REFERENCE_WHITE + J_SNAP_DISTANCE + 1e-6),
    null,
  );
  const patchJ = J_REFERENCE_WHITE + 0.004;
  assert.deepEqual(nearestJSnapTarget(J_REFERENCE_WHITE + 0.005, patchJ), {
    kind: "patch",
    value: patchJ,
  });
  assert.deepEqual(
    nearestJSnapTarget(J_REFERENCE_WHITE + 0.004, J_REFERENCE_WHITE + 0.008),
    { kind: "patch", value: J_REFERENCE_WHITE + 0.008 },
  );
  const averageJ = J_REFERENCE_WHITE + 0.002;
  assert.deepEqual(nearestJSnapTarget(averageJ + 0.001, undefined, J_REFERENCE_WHITE, J_SNAP_DISTANCE, averageJ), {
    kind: "average",
    value: averageJ,
  });
});

test("Background J snap targets choose foreground first on ties or reference white", () => {
  const foregroundJ = J_REFERENCE_WHITE + 0.008;
  assert.deepEqual(
    nearestBackgroundJSnapTarget(J_REFERENCE_WHITE + 0.004, foregroundJ),
    { kind: "foreground", value: foregroundJ },
  );
  assert.deepEqual(
    nearestBackgroundJSnapTarget(J_REFERENCE_WHITE - 0.006, 0.2),
    { kind: "reference", value: J_REFERENCE_WHITE },
  );
  assert.deepEqual(
    nearestBackgroundJSnapTarget(0.2 + BACKGROUND_J_SNAP_DISTANCE - 1e-12, 0.2),
    { kind: "foreground", value: 0.2 },
  );
  assert.equal(
    nearestBackgroundJSnapTarget(0.2 + BACKGROUND_J_SNAP_DISTANCE + 1e-6, 0.2, 0.5),
    null,
  );
});

test("Cartesian snap preserves the real pointer and releases without hysteresis", () => {
  assert.deepEqual(snapCartesianPoint(0.502, 0.503, 0.5, 0.5), {
    x: 0.5,
    y: 0.5,
  });
  assert.deepEqual(snapCartesianPoint(0.506, 0.5, 0.5, 0.5), {
    x: 0.506,
    y: 0.5,
  });
  assert.deepEqual(nearestSnapTarget(0.506, 0.5, [{ x: 0.5, y: 0.5 }]), {
    kind: "neutral",
    x: 0.5,
    y: 0.5,
  });
});

test("neutral targets omit patch J while reference-white J remains available", () => {
  const target = nearestSnapTarget(0.5, 0.5, []);
  assert.equal(target?.kind, "neutral");
  assert.deepEqual(
    projectSnapCode({ j: 0.503, x: 0.502, y: 0.503 }, target),
    { j: 0.503, x: 0.5, y: 0.5 },
  );
  assert.equal(
    projectSnapCode({ j: J_REFERENCE_WHITE + 0.004, x: 0.502, y: 0.503 }, target).j,
    J_REFERENCE_WHITE,
  );
  assert.equal(
    projectSnapCode(
      { j: J_REFERENCE_WHITE + 0.004, x: 0.502, y: 0.503 },
      target,
      undefined,
      "j",
      { j: 0.2, x: 0.5, y: 0.5 },
      undefined,
      false,
    ).j,
    J_REFERENCE_WHITE + 0.004,
  );
});

test("ColorChecker J snapping remains independent from vector snapping", () => {
  const target = nearestSnapTarget(0.522, 0.503, [{ x: 0.52, y: 0.5 }]);
  assert.equal(target?.kind, "patch");
  assert.deepEqual(
    projectSnapCode(
      { j: 0.404, x: 0.522, y: 0.503 },
      target,
      0.4,
      "xy",
      { j: 0.42, x: 0.6, y: 0.4 },
    ),
    { j: 0.42, x: 0.52, y: 0.5 },
  );
  assert.deepEqual(
    projectSnapCode(
      { j: 0.404, x: 0.522, y: 0.503 },
      target,
      0.4,
      "j",
      { j: 0.42, x: 0.6, y: 0.4 },
    ),
    { j: 0.4, x: 0.6, y: 0.4 },
  );
  assert.deepEqual(
    projectSnapCode({ j: 0.404, x: 0.522, y: 0.503 }, target, 0.4),
    { j: 0.4, x: 0.52, y: 0.5 },
  );
  assert.equal(
    projectSnapCode(
      { j: 0.404, x: 0.522, y: 0.503 },
      target,
      0.4,
      "j",
    ).j,
    0.4,
  );
});

test("a color-trackpad projection preserves the displayed J channel", () => {
  const target = nearestSnapTarget(0.522, 0.503, [{ x: 0.52, y: 0.5 }]);
  assert.equal(target?.kind, "patch");
  assert.deepEqual(
    projectSnapCode(
      { j: 0.404, x: 0.526, y: 0.5 },
      target,
      0.4,
      "xy",
      { j: 0.4, x: 0.52, y: 0.5 },
    ),
    { j: 0.4, x: 0.526, y: 0.5 },
  );
});

test("Background J' remains normalized", () => {
  assert.equal(BACKGROUND_MAX, 1);
});

test("J trackwheel maps upward movement to increasing J", () => {
  assert.equal(trackwheelDelta(0.5, -100, 400), 0.5625);
  assert.equal(trackwheelDelta(0.5, 100, 400), 0.4375);
  assert.equal(trackwheelDelta(0.02, 1000, 400), 0);
  assert.equal(trackwheelDelta(0.98, -1000, 400), 1);
});

test("J trackwheel acceleration scales movement with the shared 1x..4x profile", () => {
  const acceleration = trackMotionAcceleration(2.5);
  const base = trackwheelDelta(0.3, -100, 400);
  const accelerated = trackwheelDelta(0.3, -100, 400, undefined, acceleration);
  assert.ok(acceleration > 2 && acceleration < 3);
  assert.ok(accelerated > base);
  assert.ok(Math.abs(accelerated - (0.3 + 0.25 * acceleration * 0.25)) < 1e-12);
});

test("reference-white J trackwheel position is the fixed 203-nit ruler", () => {
  assert.ok(Math.abs(J_REFERENCE_WHITE - 100 / 217.2768649129496) < 1e-15);
});

test("color-trackpad deltas use quarter-speed Cartesian movement", () => {
  assert.deepEqual(trackpadDelta(0.38, 0.65, 100, -100, 400, 400), {
    x: 0.4425,
    y: 0.7125,
  });
  assert.deepEqual(trackpadDelta(0.01, 0.99, -1000, 1000, 400, 400), {
    x: 0,
    y: 0.365,
  });
});

test("color-trackpad acceleration preserves slow precision and boosts fast motion", () => {
  assert.equal(trackMotionAcceleration(0), 1);
  assert.ok(trackMotionAcceleration(0.1) < 1.2);
  assert.ok(trackMotionAcceleration(8) > 3.8);
  assert.ok(trackMotionAcceleration(100) <= TRACK_MAX_ACCELERATION);
});

test("image neighborhoods use native pixel centers within the requested radius", () => {
  assert.equal(neighborhoodPixels(3, 3, 9, 9, 0).length, 1);
  assert.equal(neighborhoodPixels(3, 3, 9, 9, 3).length, 29);
  assert.ok(neighborhoodPixels(0, 0, 9, 9, 3).every(([x, y]) => x >= 0 && y >= 0));
});

test("image statistics produce a rotated 95 percent covariance ellipse", () => {
  const ellipse = covarianceEllipse([
    { x: -1, y: -1 }, { x: 1, y: 1 }, { x: -0.5, y: -0.5 }, { x: 0.5, y: 0.5 },
  ]);
  assert.ok(ellipse);
  assert.ok(Math.abs(ellipse.angle - Math.PI / 4) < 1e-12);
  assert.ok(ellipse.major > ellipse.minor);
  const p = ellipsePoint(ellipse, 0);
  assert.ok(p.x > 0 && p.y > 0);
});

test("robust image ellipse resists a distant outlier deterministically", () => {
  const clean = Array.from({ length: 10 }, (_, index) => ({
    x: 0.4 + index * 0.001,
    y: 0.6 + index * 0.001,
  }));
  const withOutlier = [...clean, { x: 0.95, y: 0.05 }];
  const ellipse = covarianceEllipse(withOutlier);
  assert.ok(ellipse);
  assert.equal(ellipse.sampleCount, 11);
  assert.equal(ellipse.subsetSize, 6);
  assert.ok(ellipse.mean.x < 0.42 && ellipse.mean.y > 0.58);
  assert.ok(ellipse.major < 0.02, `major axis unexpectedly expanded: ${ellipse.major}`);
  assert.deepEqual(covarianceEllipse(withOutlier), ellipse);
});

test("image average is an additional nearest snap target", () => {
  assert.equal(nearestSnapTarget(0.51, 0.5, [], { x: 0.5, y: 0.5 }, { x: 0.51, y: 0.5 })?.kind, "average");
});

test("color-trackpad velocity is smoothed from normalized pointer speed", () => {
  const slow = trackMotionVelocity({ x: 0, y: 0 }, 4, 0, 400, 400, 40);
  const fast = trackMotionVelocity({ x: 0, y: 0 }, 80, 0, 400, 400, 40);
  assert.ok(fast.x > slow.x);
  assert.equal(slow.y, 0);
});
