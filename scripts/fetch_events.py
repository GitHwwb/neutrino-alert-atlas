#!/usr/bin/env python3
"""Fetch IceCube Gold/Bronze alerts from GCN, precompute ECEF geometry, write events.json.

For each event we store the neutrino's source direction as a unit vector in the
Earth-fixed (ITRS / ECEF) frame at the event's UTC time. The frontend can then do
trivial vector math against an observer position to get a closest-approach distance.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import certifi
import numpy as np
from astropy.coordinates import ITRS, SkyCoord
from astropy.time import Time
import astropy.units as u
from bs4 import BeautifulSoup

GCN_URL = "https://gcn.gsfc.nasa.gov/amon_icecube_gold_bronze_events.html"
OUTPUT = Path(__file__).resolve().parent.parent / "web" / "data" / "events.json"

# WGS84 ellipsoid. Observer inputs are ordinary geodetic latitude/longitude,
# so using the same reference here avoids the ~20 km errors produced by a
# spherical conversion at mid-latitudes.
WGS84_A_KM = 6378.137
WGS84_F = 1.0 / 298.257223563
WGS84_B_KM = WGS84_A_KM * (1.0 - WGS84_F)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
MINIMUM_ACTIVE_EVENTS = 150
MAX_EVENT_DROP_FRACTION = 0.10


def geodetic_to_ecef_km(
    lat_deg: float,
    lon_deg: float,
    depth_m: float = 0.0,
) -> np.ndarray:
    """Convert WGS84 geodetic coordinates and depth below surface to ECEF km."""
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    altitude_km = -depth_m / 1000.0
    prime_vertical_radius = WGS84_A_KM / np.sqrt(1.0 - WGS84_E2 * sin_lat**2)
    return np.array([
        (prime_vertical_radius + altitude_km) * cos_lat * np.cos(lon),
        (prime_vertical_radius + altitude_km) * cos_lat * np.sin(lon),
        (prime_vertical_radius * (1.0 - WGS84_E2) + altitude_km) * sin_lat,
    ])


# Operating high-energy neutrino telescopes. Detector ECEF positions are used
# as the trajectory anchor point for each event's geometry.
DETECTORS = {
    "icecube": {
        "name": "IceCube",
        "lat_deg": -90.0,
        "lon_deg": 0.0,
        "depth_m": 1950.0,
    },
    "km3net-arca": {
        "name": "KM3NeT/ARCA",
        "lat_deg": 36.2667,
        "lon_deg": 16.1,
        "depth_m": 3500.0,
    },
    "km3net-orca": {
        "name": "KM3NeT/ORCA",
        "lat_deg": 42.8,
        "lon_deg": 6.0333,
        "depth_m": 2450.0,
    },
    "baikal-gvd": {
        "name": "Baikal-GVD",
        "lat_deg": 51.7667,
        "lon_deg": 104.4,
        "depth_m": 1100.0,
    },
}
for detector in DETECTORS.values():
    detector["ecef_km"] = geodetic_to_ecef_km(
        detector["lat_deg"],
        detector["lon_deg"],
        detector["depth_m"],
    )
ICECUBE_ECEF_KM = DETECTORS["icecube"]["ecef_km"]


@dataclass
class RawRow:
    run_event: str
    rev: int
    date_str: str
    time_str: str
    notice_type: str
    ra_deg: float | None
    dec_deg: float | None
    err90_arcmin: float | None
    err50_arcmin: float | None
    energy: float | None
    signalness: float | None
    far_per_yr: float | None
    comments: str


FETCH_ATTEMPTS = 4
FETCH_BACKOFF_S = 20.0  # doubled after each failed attempt


def fetch_html() -> str:
    """Fetch the GCN table, retrying on transient network failures.

    GitHub-hosted runners intermittently lose the route to gcn.gsfc.nasa.gov
    ("[Errno 101] Network is unreachable"), so a single attempt fails runs
    that would succeed a minute later.
    """
    req = Request(GCN_URL, headers={"User-Agent": "icecube-tracker/0.1 (+github)"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    delay = FETCH_BACKOFF_S
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except OSError as exc:  # URLError subclasses OSError
            if attempt == FETCH_ATTEMPTS:
                raise
            print(
                f"Fetch attempt {attempt}/{FETCH_ATTEMPTS} failed ({exc}); "
                f"retrying in {delay:.0f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def parse_rows(html: str) -> list[RawRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[RawRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 13:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        # Sanity: first cell looks like "142545_58544625"; notice type is GOLD/BRONZE.
        if "_" not in texts[0] or texts[4] not in ("GOLD", "BRONZE"):
            continue
        try:
            revision = int(texts[1])
        except ValueError as exc:
            raise ValueError(
                f"recognized GCN row {texts[0]} has invalid revision {texts[1]!r}"
            ) from exc

        def optional_float(value: str) -> float | None:
            try:
                return float(value)
            except ValueError:
                return None

        # Preserve recognized rows with malformed metrics through revision
        # selection. Otherwise a malformed latest row can silently revive an
        # obsolete earlier revision.
        rows.append(
            RawRow(
                run_event=texts[0],
                rev=revision,
                date_str=texts[2],
                time_str=texts[3],
                notice_type=texts[4],
                ra_deg=optional_float(texts[5]),
                dec_deg=optional_float(texts[6]),
                err90_arcmin=optional_float(texts[7]),
                err50_arcmin=optional_float(texts[8]),
                energy=optional_float(texts[9]),
                signalness=optional_float(texts[10]),
                far_per_yr=optional_float(texts[11]),
                comments=texts[12],
            )
        )
    return rows


def latest_revisions(rows: list[RawRow]) -> list[RawRow]:
    """Each event has multiple Rev entries; keep the highest Rev per event."""
    by_event: dict[str, RawRow] = {}
    for row in rows:
        prior = by_event.get(row.run_event)
        if prior is None or row.rev > prior.rev:
            by_event[row.run_event] = row
    return list(by_event.values())


def partition_active_rows(
    rows: list[RawRow],
) -> tuple[list[RawRow], list[dict[str, object]]]:
    """Separate active alerts from latest revisions with unavailable metrics."""
    active: list[RawRow] = []
    excluded: list[dict[str, object]] = []
    for row in rows:
        numeric_values = (
            row.ra_deg,
            row.dec_deg,
            row.err90_arcmin,
            row.err50_arcmin,
            row.energy,
            row.signalness,
            row.far_per_yr,
        )
        invalid = any(
            value is None or not math.isfinite(value)
            for value in numeric_values
        )
        invalid = invalid or any(
            value is not None and value <= 0
            for value in (
                row.err90_arcmin,
                row.err50_arcmin,
                row.energy,
                row.signalness,
                row.far_per_yr,
            )
        )
        invalid = invalid or (
            row.ra_deg is not None
            and row.dec_deg is not None
            and not (0 <= row.ra_deg < 360 and -90 <= row.dec_deg <= 90)
        )
        try:
            parse_datetime(row.date_str, row.time_str)
        except (TypeError, ValueError):
            invalid = True
        if invalid:
            excluded.append({
                "id": row.run_event,
                "rev": row.rev,
                "reason": "latest revision has unavailable alert metrics",
            })
        else:
            active.append(row)
    return active, excluded


def parse_datetime(date_str: str, time_str: str) -> datetime:
    # Date format on the page is YY/MM/DD. The IceCube alerts archive starts in 2019,
    # so 2-digit years are 20xx unambiguously.
    yy, mm, dd = date_str.split("/")
    year = 2000 + int(yy)
    iso = f"{year:04d}-{int(mm):02d}-{int(dd):02d}T{time_str}"
    # fromisoformat handles fractional seconds.
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def source_ecef_unit(ra_deg: float, dec_deg: float, when: datetime) -> np.ndarray:
    """Convert celestial (RA, Dec) at UTC time `when` to a unit vector in ECEF (ITRS)."""
    t = Time(when)
    sky = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    itrs = sky.transform_to(ITRS(obstime=t))
    # SkyCoord with no distance becomes a unit vector after frame transform.
    xyz = itrs.cartesian.xyz.value
    return xyz / np.linalg.norm(xyz)


def ecef_to_geodetic(p_km: np.ndarray) -> tuple[float, float]:
    """Convert an ECEF point to WGS84 geodetic latitude/longitude."""
    x, y, z = p_km
    horizontal = float(np.hypot(x, y))
    lon = float(np.degrees(np.arctan2(y, x)))
    if horizontal < 1e-12:
        return (90.0 if z >= 0 else -90.0), lon

    lat = math.atan2(z, horizontal * (1.0 - WGS84_E2))
    for _ in range(10):
        sin_lat = math.sin(lat)
        prime_vertical_radius = WGS84_A_KM / math.sqrt(
            1.0 - WGS84_E2 * sin_lat**2
        )
        next_lat = math.atan2(
            z + WGS84_E2 * prime_vertical_radius * sin_lat,
            horizontal,
        )
        if abs(next_lat - lat) < 1e-14:
            lat = next_lat
            break
        lat = next_lat
    return math.degrees(lat), lon


def atmospheric_entry_ecef_km(
    detector_ecef_km: np.ndarray,
    source_unit: np.ndarray,
) -> np.ndarray:
    """Intersect the incoming ray from detector toward source with WGS84."""
    dx, dy, dz = detector_ecef_km
    sx, sy, sz = source_unit
    a2 = WGS84_A_KM**2
    b2 = WGS84_B_KM**2
    qa = (sx**2 + sy**2) / a2 + sz**2 / b2
    qb = 2.0 * ((dx * sx + dy * sy) / a2 + dz * sz / b2)
    qc = (dx**2 + dy**2) / a2 + dz**2 / b2 - 1.0
    discriminant = qb**2 - 4.0 * qa * qc
    if discriminant < 0:
        raise ValueError("detector-source ray does not intersect WGS84")
    roots = (
        (-qb - math.sqrt(discriminant)) / (2.0 * qa),
        (-qb + math.sqrt(discriminant)) / (2.0 * qa),
    )
    positive_roots = [root for root in roots if root >= 0]
    if not positive_roots:
        raise ValueError("detector-source ray has no forward WGS84 intersection")
    return detector_ecef_km + max(positive_roots) * source_unit


def trajectory_geometry(source_unit: np.ndarray, detector_ecef_km: np.ndarray) -> dict:
    """Geographically meaningful points on Earth for an event at a given detector.

    - subsource_lat/lon: where on Earth the source was directly overhead at event
      time. Detector-independent.
    - entry_lat/lon and entry_ecef_km: where the incoming ray from the detector
      toward the source intersects the WGS84 surface. This is the finite
      trajectory endpoint used for observer-distance calculations.
    """
    # A source is directly overhead where the local ellipsoid normal points in
    # the source direction. Geodetic latitude is defined by that normal.
    sub_lat = math.degrees(math.asin(float(source_unit[2])))
    sub_lon = math.degrees(math.atan2(float(source_unit[1]), float(source_unit[0])))
    detector_lat, detector_lon = ecef_to_geodetic(detector_ecef_km)
    detector_lat_rad = math.radians(detector_lat)
    detector_lon_rad = math.radians(detector_lon)
    local_up = np.array([
        math.cos(detector_lat_rad) * math.cos(detector_lon_rad),
        math.cos(detector_lat_rad) * math.sin(detector_lon_rad),
        math.sin(detector_lat_rad),
    ])
    is_up_going = bool(np.dot(source_unit, local_up) < 0)
    entry = atmospheric_entry_ecef_km(detector_ecef_km, source_unit)
    entry_lat, entry_lon = ecef_to_geodetic(entry)
    return {
        "is_up_going": is_up_going,
        "entry_lat": entry_lat,
        "entry_lon": entry_lon,
        "entry_ecef_km": [float(value) for value in entry],
        "subsource_lat": sub_lat,
        "subsource_lon": sub_lon,
    }


def to_event_dict(row: RawRow, simbad_cache: dict[str, list]) -> dict:
    when = parse_datetime(row.date_str, row.time_str)
    src = source_ecef_unit(row.ra_deg, row.dec_deg, when)
    geom = trajectory_geometry(src, ICECUBE_ECEF_KM)
    # SIMBAD lookup is rate-limited so we cache results from previous runs.
    if row.run_event in simbad_cache:
        candidates = simbad_cache[row.run_event]
        simbad_lookup = {"status": "ok", "candidates": candidates}
    else:
        simbad_lookup = query_simbad(row.ra_deg, row.dec_deg, row.err90_arcmin)
        if simbad_lookup["status"] == "ok":
            time.sleep(0.4)
            simbad_cache[row.run_event] = simbad_lookup["candidates"]
    simbad_lookup = remove_neutrino_alert_records(simbad_lookup)
    return {
        "id": row.run_event,
        "rev": row.rev,
        "datetime_utc": when.isoformat().replace("+00:00", "Z"),
        "notice_type": row.notice_type,
        "ra_deg": row.ra_deg,
        "dec_deg": row.dec_deg,
        "err90_arcmin": row.err90_arcmin,
        "err50_arcmin": row.err50_arcmin,
        "energy": row.energy,
        "signalness": row.signalness,
        "far_per_yr": row.far_per_yr,
        "comments": row.comments,
        "detector": "IceCube",
        "detector_lat": DETECTORS["icecube"]["lat_deg"],
        "detector_lon": DETECTORS["icecube"]["lon_deg"],
        "detector_ecef_km": ICECUBE_ECEF_KM.tolist(),
        "energy_basis": (
            "Most-probable neutrino energy under the IceCube alert "
            "pipeline's E^-2.19 astrophysical-flux model"
        ),
        "metrics_source": "NASA GCN AMON IceCube Gold/Bronze notice",
        "source_ecef_unit": [float(src[0]), float(src[1]), float(src[2])],
        "simbad_lookup": simbad_lookup,
        **geom,
    }


# Hand-curated events from other detectors. Each entry has the published
# parameters from the announcement (paper or circular); the geometry is then
# computed through the same pipeline as IceCube events.
HAND_CURATED_EVENTS = [
    {
        "id": "KM3-230213A",
        "datetime_utc_str": "2023-02-13T01:16:47.0",
        "notice_type": "KM3NET",
        "detector_key": "km3net-arca",
        "ra_deg": 94.3,
        "dec_deg": -7.8,
        "err90_arcmin": 132.0,       # 2.2° published 90% C.L. radius
        "err50_arcmin": 72.0,        # 1.2° published 50% C.L. radius
        "energy": 2.2e5,             # ~220 PeV in TeV — the GCN table's unit, so
                                     # formatting can remain consistent
        "energy_basis": (
            "Median incoming-neutrino energy under the KM3NeT paper's "
            "E^-2 spectrum assumption"
        ),
        # The Nature paper does not publish IceCube-alert signalness or FAR.
        "signalness": None,
        "far_per_yr": None,
        "comments": (
            "KM3NeT/ARCA single ultra-high-energy detection. Reconstructed "
            "neutrino energy ~220 PeV (90% C.L. range ~72 PeV – 2.6 EeV). "
            "Reported in KM3NeT Collaboration, Nature 638, 376–382 (2025)."
        ),
        "reference_url": "https://www.nature.com/articles/s41586-024-08543-1",
    },
]


def round_floats(obj, ndigits: int = 6):
    """Round every float in a JSON-ready structure. 6 decimals is ~0.1 m in
    degrees and ~6 m for unit vectors scaled to Earth radius — far below the
    physics' angular uncertainty, and roughly halves the payload size."""
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, list):
        return [round_floats(x, ndigits) for x in obj]
    if isinstance(obj, dict):
        return {k: round_floats(v, ndigits) for k, v in obj.items()}
    return obj


def to_hand_curated_event_dict(entry: dict, simbad_cache: dict[str, list]) -> dict:
    detector = DETECTORS[entry["detector_key"]]
    when = datetime.fromisoformat(entry["datetime_utc_str"]).replace(tzinfo=timezone.utc)
    src = source_ecef_unit(entry["ra_deg"], entry["dec_deg"], when)
    geom = trajectory_geometry(src, detector["ecef_km"])
    if entry["id"] in simbad_cache:
        candidates = simbad_cache[entry["id"]]
        simbad_lookup = {"status": "ok", "candidates": candidates}
    else:
        simbad_lookup = query_simbad(
            entry["ra_deg"],
            entry["dec_deg"],
            entry["err90_arcmin"],
        )
        if simbad_lookup["status"] == "ok":
            time.sleep(0.4)
            simbad_cache[entry["id"]] = simbad_lookup["candidates"]
    simbad_lookup = remove_neutrino_alert_records(simbad_lookup)
    return {
        "id": entry["id"],
        "rev": 0,
        "datetime_utc": when.isoformat().replace("+00:00", "Z"),
        "notice_type": entry["notice_type"],
        "ra_deg": entry["ra_deg"],
        "dec_deg": entry["dec_deg"],
        "err90_arcmin": entry["err90_arcmin"],
        "err50_arcmin": entry["err50_arcmin"],
        "energy": entry["energy"],
        "signalness": entry["signalness"],
        "far_per_yr": entry["far_per_yr"],
        "comments": entry["comments"],
        "detector": detector["name"],
        "detector_lat": detector["lat_deg"],
        "detector_lon": detector["lon_deg"],
        "detector_ecef_km": detector["ecef_km"].tolist(),
        "energy_basis": entry["energy_basis"],
        "metrics_source": "KM3NeT Collaboration, Nature 638, 376-382 (2025)",
        "reference_url": entry.get("reference_url"),
        "source_ecef_unit": [float(src[0]), float(src[1]), float(src[2])],
        "simbad_lookup": simbad_lookup,
        **geom,
    }


def remove_neutrino_alert_records(lookup: dict) -> dict:
    """Remove catalog records for the neutrino alert itself, not real sources."""
    filtered = []
    for candidate in lookup.get("candidates", []):
        normalized_name = candidate.get("name", "").strip().upper()
        if normalized_name.startswith("NAME "):
            normalized_name = normalized_name[5:].strip()
        separation = candidate.get("sep_arcmin")
        is_neutrino_alert = normalized_name.startswith(("ICECUBE-", "KM3-"))
        is_same_position = (
            isinstance(separation, (int, float))
            and math.isfinite(separation)
            and separation <= 0.05
        )
        if not (is_neutrino_alert and is_same_position):
            filtered.append(candidate)
    return {**lookup, "candidates": filtered}


def query_simbad(ra_deg: float, dec_deg: float, err90_arcmin: float) -> dict:
    """Return up to 5 nearest SIMBAD objects within the 90% error radius.

    Successful empty results and failed lookups are distinct so a transient
    outage is never presented or cached as "no nearby objects."
    """
    try:
        from astroquery.simbad import Simbad
        s = Simbad()
        # Ensure object type is in the response (varies by astroquery version).
        try:
            s.add_votable_fields("otype")
        except Exception:
            pass
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
        results = s.query_region(coord, radius=err90_arcmin * u.arcmin)
        if results is None or len(results) == 0:
            return {"status": "ok", "candidates": []}
        candidates: list[dict] = []
        for row in results:
            name = None
            otype = None
            # Astroquery column names vary by version: try a few.
            for k in ("MAIN_ID", "main_id"):
                if k in results.colnames:
                    name = str(row[k])
                    break
            for k in ("OTYPE", "otype", "OTYPE_S"):
                if k in results.colnames:
                    otype = str(row[k])
                    break
            ra_k = next((k for k in ("RA", "ra", "RA_d", "ra_d") if k in results.colnames), None)
            dec_k = next((k for k in ("DEC", "dec", "DEC_d", "dec_d") if k in results.colnames), None)
            sep_arcmin = None
            if ra_k and dec_k:
                try:
                    obj_ra = float(row[ra_k])
                    obj_dec = float(row[dec_k])
                    obj = SkyCoord(ra=obj_ra * u.deg, dec=obj_dec * u.deg, frame="icrs")
                    sep_arcmin = float(coord.separation(obj).to(u.arcmin).value)
                except Exception:
                    sep_arcmin = None
            obj_ra_val = None
            obj_dec_val = None
            if ra_k and dec_k:
                try:
                    obj_ra_val = float(row[ra_k])
                    obj_dec_val = float(row[dec_k])
                except Exception:
                    pass
            if name:
                candidates.append({
                    "name": name.strip(),
                    "otype": otype,
                    "sep_arcmin": sep_arcmin,
                    "ra_deg": obj_ra_val,
                    "dec_deg": obj_dec_val,
                })
        # Sort by separation and keep nearest 5.
        candidates.sort(key=lambda c: c["sep_arcmin"] if c["sep_arcmin"] is not None else 1e9)
        return {"status": "ok", "candidates": candidates[:5]}
    except Exception as exc:
        print(f"  SIMBAD lookup failed for RA={ra_deg}, Dec={dec_deg}: {exc}", file=sys.stderr)
        return {
            "status": "error",
            "candidates": [],
            "message": str(exc),
        }


def load_simbad_cache() -> dict[str, list]:
    """Reuse SIMBAD results from a previous events.json so we don't re-query.

    A cached entry is only honored if every candidate has ra_deg / dec_deg
    populated — older cache entries lacked those, and we now need them for
    the Aladin overlay on the frontend.
    """
    if not OUTPUT.exists():
        return {}
    try:
        prev = json.loads(OUTPUT.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    cache: dict[str, list] = {}
    for ev in prev.get("events", []):
        lookup = ev.get("simbad_lookup")
        if (
            isinstance(lookup, dict)
            and lookup.get("status") == "ok"
            and isinstance(lookup.get("candidates"), list)
        ):
            cache[ev["id"]] = lookup["candidates"]
            continue

        # A non-empty legacy result proves the old lookup succeeded. Legacy
        # empty arrays were ambiguous because failures also returned [].
        legacy = ev.get("simbad_candidates")
        if (
            isinstance(legacy, list)
            and legacy
            and all(("ra_deg" in c and "dec_deg" in c) for c in legacy)
        ):
            cache[ev["id"]] = legacy
    return cache


def load_previous_payload() -> dict | None:
    if not OUTPUT.exists():
        return None
    try:
        return json.loads(OUTPUT.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def validate_payload(
    payload: dict,
    previous_payload: dict | None = None,
    minimum_events: int = MINIMUM_ACTIVE_EVENTS,
    max_drop_fraction: float = MAX_EVENT_DROP_FRACTION,
) -> None:
    """Reject incomplete or internally inconsistent generated catalogs."""
    def is_finite_number(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("payload events must be a list")
    if payload.get("event_count") != len(events):
        raise ValueError("event_count does not match events length")
    if len(events) < minimum_events:
        raise ValueError(
            f"active event count {len(events)} is below minimum {minimum_events}"
        )

    if any(not isinstance(event, dict) for event in events):
        raise ValueError("every payload event must be an object")
    ids = [event.get("id") for event in events]
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in ids):
        raise ValueError("event id must be a nonempty text field")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate event IDs")

    required = {
        "id",
        "datetime_utc",
        "notice_type",
        "ra_deg",
        "dec_deg",
        "err90_arcmin",
        "err50_arcmin",
        "energy",
        "signalness",
        "far_per_yr",
        "detector",
        "detector_lat",
        "detector_lon",
        "detector_ecef_km",
        "entry_ecef_km",
        "source_ecef_unit",
        "is_up_going",
        "entry_lat",
        "entry_lon",
        "subsource_lat",
        "subsource_lon",
        "energy_basis",
        "metrics_source",
        "comments",
        "simbad_lookup",
    }
    for event in events:
        missing = required - set(event)
        if missing:
            raise ValueError(f"{event.get('id', '<unknown>')} missing fields: {sorted(missing)}")
        for field in (
            "id",
            "datetime_utc",
            "notice_type",
            "detector",
            "energy_basis",
            "metrics_source",
        ):
            if not isinstance(event[field], str) or not event[field].strip():
                raise ValueError(f"{event['id']} has invalid text field {field}")
        if not isinstance(event["comments"], str):
            raise ValueError(f"{event['id']} has invalid text field comments")
        numeric_positive = (
            "err90_arcmin",
            "err50_arcmin",
            "energy",
        )
        if any(
            not is_finite_number(event[field])
            or event[field] <= 0
            for field in numeric_positive
        ):
            raise ValueError(f"{event['id']} has invalid positive-valued metrics")
        if (
            not is_finite_number(event["ra_deg"])
            or not is_finite_number(event["dec_deg"])
            or not 0 <= event["ra_deg"] < 360
            or not -90 <= event["dec_deg"] <= 90
        ):
            raise ValueError(f"{event['id']} has invalid sky coordinates")
        geographic_fields = (
            ("detector_lat", -90, 90),
            ("detector_lon", -180, 180),
            ("entry_lat", -90, 90),
            ("entry_lon", -180, 180),
            ("subsource_lat", -90, 90),
            ("subsource_lon", -180, 180),
        )
        if any(
            not is_finite_number(event[field])
            or not lower <= event[field] <= upper
            for field, lower, upper in geographic_fields
        ):
            raise ValueError(f"{event['id']} has invalid geographic coordinates")
        if not isinstance(event["is_up_going"], bool):
            raise ValueError(f"{event['id']} has invalid up-going classification")
        if (
            event["signalness"] is not None
            and (
                not is_finite_number(event["signalness"])
                or not 0 < event["signalness"] <= 1
            )
        ):
            raise ValueError(f"{event['id']} has invalid signalness")
        if (
            event["far_per_yr"] is not None
            and (
                not is_finite_number(event["far_per_yr"])
                or event["far_per_yr"] <= 0
            )
        ):
            raise ValueError(f"{event['id']} has invalid false-alarm rate")
        for field in ("detector_ecef_km", "entry_ecef_km", "source_ecef_unit"):
            vector = event[field]
            if (
                not isinstance(vector, list)
                or len(vector) != 3
                or any(not is_finite_number(value) for value in vector)
            ):
                raise ValueError(f"{event['id']} has invalid {field}")
        if abs(np.linalg.norm(event["source_ecef_unit"]) - 1.0) > 1e-4:
            raise ValueError(f"{event['id']} source vector is not unit length")
        detector = np.asarray(event["detector_ecef_km"], dtype=float)
        entry = np.asarray(event["entry_ecef_km"], dtype=float)
        source = np.asarray(event["source_ecef_unit"], dtype=float)
        delta = entry - detector
        segment_length = float(np.linalg.norm(delta))
        projection = float(np.dot(delta, source))
        collinearity_error = float(np.linalg.norm(delta - projection * source))
        ellipsoid_value = (
            (entry[0] ** 2 + entry[1] ** 2) / WGS84_A_KM**2
            + entry[2] ** 2 / WGS84_B_KM**2
        )
        if (
            segment_length <= 0
            or projection <= 0
            or collinearity_error > max(0.05, segment_length * 2e-6)
            or abs(ellipsoid_value - 1.0) > 1e-5
        ):
            raise ValueError(f"{event['id']} has invalid atmospheric entry point")
        lookup = event["simbad_lookup"]
        if (
            not isinstance(lookup, dict)
            or lookup.get("status") not in {"ok", "error"}
            or not isinstance(lookup.get("candidates"), list)
        ):
            raise ValueError(f"{event['id']} has invalid SIMBAD lookup status")

    if previous_payload:
        previous_count = previous_payload.get("event_count")
        if isinstance(previous_count, int) and previous_count > 0:
            drop_fraction = (previous_count - len(events)) / previous_count
            if drop_fraction > max_drop_fraction:
                raise ValueError(
                    f"active event count dropped {drop_fraction:.1%}, "
                    f"above allowed {max_drop_fraction:.1%}"
                )


def payload_content_changed(payload: dict, previous_payload: dict | None) -> bool:
    if previous_payload is None:
        return True
    current = copy.deepcopy(payload)
    previous = copy.deepcopy(previous_payload)
    current.pop("generated_at_utc", None)
    previous.pop("generated_at_utc", None)
    return current != previous


def write_payload_atomic(payload: dict) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(round_floats(payload), indent=2) + "\n")
    os.replace(temporary, OUTPUT)


def build_payload(html: str, previous_payload: dict | None) -> dict:
    raw = parse_rows(html)
    print(f"Parsed {len(raw)} table rows", file=sys.stderr)
    latest = latest_revisions(raw)
    rows, excluded = partition_active_rows(latest)
    print(
        f"Reduced to {len(rows)} active events and {len(excluded)} excluded "
        "latest revisions",
        file=sys.stderr,
    )

    simbad_cache = load_simbad_cache()
    print(f"SIMBAD cache: {len(simbad_cache)} events already looked up", file=sys.stderr)

    events = []
    for i, row in enumerate(rows, 1):
        if row.run_event not in simbad_cache:
            print(f"  [{i}/{len(rows)}] querying SIMBAD for {row.run_event}", file=sys.stderr)
        events.append(to_event_dict(row, simbad_cache))

    print(f"Adding {len(HAND_CURATED_EVENTS)} hand-curated event(s)", file=sys.stderr)
    for entry in HAND_CURATED_EVENTS:
        events.append(to_hand_curated_event_dict(entry, simbad_cache))
    events.sort(key=lambda event: event["datetime_utc"], reverse=True)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_url": GCN_URL,
        "earth_model": "WGS84",
        "icecube_ecef_km": ICECUBE_ECEF_KM.tolist(),
        "event_count": len(events),
        "excluded_events": excluded,
        "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the existing events.json without fetching upstream data",
    )
    args = parser.parse_args(argv)
    previous_payload = load_previous_payload()
    if args.validate_only:
        if previous_payload is None:
            raise ValueError(f"cannot validate missing or invalid {OUTPUT}")
        validate_payload(previous_payload)
        print(f"Validated {OUTPUT} ({previous_payload['event_count']} events)")
        return 0

    print(f"Fetching {GCN_URL}", file=sys.stderr)
    html = fetch_html()
    payload = round_floats(build_payload(html, previous_payload))
    validate_payload(payload, previous_payload=previous_payload)
    if not payload_content_changed(payload, previous_payload):
        print("No catalog content changes; preserving existing events.json", file=sys.stderr)
        return 0
    write_payload_atomic(payload)
    print(f"Wrote {OUTPUT} ({payload['event_count']} active events)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
