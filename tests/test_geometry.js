"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const geometry = require("../web/geometry.js");

function assertVectorClose(actual, expected, tolerance = 1e-6) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => {
    assert.ok(
      Math.abs(value - expected[index]) <= tolerance,
      `component ${index}: expected ${expected[index]}, got ${value}`,
    );
  });
}

test("geodeticToEcef uses WGS84 at the equator", () => {
  assertVectorClose(
    geometry.geodeticToEcef(0, 0),
    [6378.137, 0, 0],
  );
});

test("geodeticToEcef uses the WGS84 polar radius", () => {
  assertVectorClose(
    geometry.geodeticToEcef(90, 0),
    [0, 0, 6356.752314245],
    1e-6,
  );
});

test("distancePointToSegment clamps a closest point beyond the detector", () => {
  const detector = [0, 0, 0];
  const atmosphericEntry = [2, 0, 0];
  const observerOnPostDetectorContinuation = [-3314.7, 0, 0];

  assert.equal(
    geometry.distancePointToSegment(
      observerOnPostDetectorContinuation,
      detector,
      atmosphericEntry,
    ),
    3314.7,
  );
});

test("distancePointToSegment uses an interior perpendicular projection", () => {
  assert.equal(
    geometry.distancePointToSegment([1, 3, 0], [0, 0, 0], [2, 0, 0]),
    3,
  );
});
