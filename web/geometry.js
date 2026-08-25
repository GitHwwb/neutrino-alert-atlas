(function initGeometry(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NeutrinoGeometry = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  const WGS84_A_KM = 6378.137;
  const WGS84_F = 1 / 298.257223563;
  const WGS84_E2 = WGS84_F * (2 - WGS84_F);

  function geodeticToEcef(latDeg, lonDeg, altitudeKm = 0) {
    const lat = (latDeg * Math.PI) / 180;
    const lon = (lonDeg * Math.PI) / 180;
    const sinLat = Math.sin(lat);
    const cosLat = Math.cos(lat);
    const primeVerticalRadius = WGS84_A_KM / Math.sqrt(1 - WGS84_E2 * sinLat * sinLat);

    return [
      (primeVerticalRadius + altitudeKm) * cosLat * Math.cos(lon),
      (primeVerticalRadius + altitudeKm) * cosLat * Math.sin(lon),
      (primeVerticalRadius * (1 - WGS84_E2) + altitudeKm) * sinLat,
    ];
  }

  function distancePointToSegment(point, start, end) {
    const segment = end.map((value, index) => value - start[index]);
    const fromStart = point.map((value, index) => value - start[index]);
    const segmentLengthSquared = segment.reduce((sum, value) => sum + value * value, 0);
    if (segmentLengthSquared === 0) {
      return Math.hypot(...fromStart);
    }

    const projection = fromStart.reduce(
      (sum, value, index) => sum + value * segment[index],
      0,
    ) / segmentLengthSquared;
    const clamped = Math.max(0, Math.min(1, projection));
    const closest = start.map((value, index) => value + clamped * segment[index]);
    return Math.hypot(...point.map((value, index) => value - closest[index]));
  }

  return {
    WGS84_A_KM,
    WGS84_E2,
    geodeticToEcef,
    distancePointToSegment,
  };
}));
