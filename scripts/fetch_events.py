#!/usr/bin/env python3
"""Fetch IceCube Gold/Bronze alerts from GCN, precompute ECEF geometry, write events.json.

For each event we store the neutrino's source direction as a unit vector in the
Earth-fixed (ITRS / ECEF) frame at the event's UTC time. The frontend can then do
trivial vector math against an observer position to get a closest-approach distance.
"""

from __future__ import annotations

import json
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

# Mean Earth radius for non-polar detectors; polar radius is fine for IceCube
# (and a sub-percent difference at km scale anyway).
EARTH_RADIUS_KM = 6371.0
EARTH_POLAR_RADIUS_KM = 6356.752


def latlon_to_ecef_km(lat_deg: float, lon_deg: float, depth_m: float = 0.0) -> np.ndarray:
    """Spherical lat/lon (+ depth below surface in meters) to ECEF km."""
    r_km = EARTH_RADIUS_KM - depth_m / 1000.0
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    return np.array([
        r_km * np.cos(lat) * np.cos(lon),
        r_km * np.cos(lat) * np.sin(lon),
        r_km * np.sin(lat),
    ])


# Operating high-energy neutrino telescopes. Detector ECEF positions are used
# as the trajectory anchor point for each event's geometry.
DETECTORS = {
    "icecube": {
        "name": "IceCube",
        "ecef_km": np.array([0.0, 0.0, -EARTH_POLAR_RADIUS_KM]),
    },
    "km3net-arca": {
        "name": "KM3NeT/ARCA",
        "ecef_km": latlon_to_ecef_km(36.2667, 16.1, depth_m=3500),
    },
    "km3net-orca": {
        "name": "KM3NeT/ORCA",
        "ecef_km": latlon_to_ecef_km(42.8, 6.0333, depth_m=2450),
    },
    "baikal-gvd": {
        "name": "Baikal-GVD",
        "ecef_km": latlon_to_ecef_km(51.7667, 104.4, depth_m=1100),
    },
}
ICECUBE_ECEF_KM = DETECTORS["icecube"]["ecef_km"]


@dataclass
class RawRow:
    run_event: str
    rev: int
    date_str: str
    time_str: str
    notice_type: str
    ra_deg: float
    dec_deg: float
    err90_arcmin: float
    err50_arcmin: float
    energy: float
    signalness: float
    far_per_yr: float
    comments: str


def fetch_html() -> str:
    req = Request(GCN_URL, headers={"User-Agent": "icecube-tracker/0.1 (+github)"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urlopen(req, timeout=30, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


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
            rows.append(
                RawRow(
                    run_event=texts[0],
                    rev=int(texts[1]),
                    date_str=texts[2],
                    time_str=texts[3],
                    notice_type=texts[4],
                    ra_deg=float(texts[5]),
                    dec_deg=float(texts[6]),
                    err90_arcmin=float(texts[7]),
                    err50_arcmin=float(texts[8]),
                    energy=float(texts[9]),
                    signalness=float(texts[10]),
                    far_per_yr=float(texts[11]),
                    comments=texts[12],
                )
            )
        except ValueError:
            # Skip rows with non-numeric placeholders (e.g. "Network problem" entries)
            continue
    return rows


def latest_revisions(rows: list[RawRow]) -> list[RawRow]:
    """Each event has multiple Rev entries; keep the highest Rev per event."""
    by_event: dict[str, RawRow] = {}
    for row in rows:
        prior = by_event.get(row.run_event)
        if prior is None or row.rev > prior.rev:
            by_event[row.run_event] = row
    return list(by_event.values())


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
    """Spherical lat/lon for a surface point. Good enough for visualization."""
    x, y, z = p_km
    r = float(np.linalg.norm(p_km))
    lat = float(np.degrees(np.arcsin(z / r)))
    lon = float(np.degrees(np.arctan2(y, x)))
    return lat, lon


def trajectory_geometry(source_unit: np.ndarray, detector_ecef_km: np.ndarray) -> dict:
    """Geographically meaningful points on Earth for an event at a given detector.

    - subsource_lat/lon: where on Earth the source was directly overhead at event
      time. Detector-independent.
    - entry_lat/lon: where the neutrino's path entered Earth's atmosphere on its
      way through to the detector. Only physically meaningful for up-going
      events (neutrino travel direction has positive component along the
      detector's outward radial). For down-going events the neutrino enters
      Earth at the detector itself.

    Line: r(t) = detector + t * source_unit. The trajectory crosses Earth's
    surface at t = 0 (the detector, approximately) and t = -2 * (detector·src).
    "Up-going" ↔ velocity (-source_unit) has positive component along the
    detector's local zenith ↔ source_unit · detector_unit < 0.
    """
    sub_lat, sub_lon = ecef_to_geodetic(source_unit * EARTH_POLAR_RADIUS_KM)
    detector_unit = detector_ecef_km / np.linalg.norm(detector_ecef_km)
    is_up_going = bool(np.dot(source_unit, detector_unit) < 0)
    if is_up_going:
        t = -2.0 * float(np.dot(detector_ecef_km, source_unit))
        entry = detector_ecef_km + t * source_unit
        entry_lat, entry_lon = ecef_to_geodetic(entry)
    else:
        entry_lat, entry_lon = None, None
    return {
        "is_up_going": is_up_going,
        "entry_lat": entry_lat,
        "entry_lon": entry_lon,
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
    else:
        candidates = query_simbad(row.ra_deg, row.dec_deg, row.err90_arcmin)
        time.sleep(0.4)
        simbad_cache[row.run_event] = candidates
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
        "detector_ecef_km": ICECUBE_ECEF_KM.tolist(),
        "source_ecef_unit": [float(src[0]), float(src[1]), float(src[2])],
        "simbad_candidates": candidates,
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
        "err90_arcmin": 84.0,        # ~1.4° published 90% C.L. radius
        "err50_arcmin": 42.0,        # estimate (~0.7° 50% radius)
        "energy": 2.2e8,             # ~220 PeV in GeV (best-fit muon proxy)
        "signalness": 0.99,          # treated as essentially astrophysical
        "far_per_yr": 0.0001,        # extremely low FAR (single event, unique morphology)
        "comments": (
            "KM3NeT/ARCA single ultra-high-energy detection. Reconstructed "
            "neutrino energy ~220 PeV (90% C.L. range ~72 PeV – 2.6 EeV). "
            "Reported in KM3NeT Collaboration, Nature 638, 376–382 (2025)."
        ),
        "reference_url": "https://www.nature.com/articles/s41586-024-08543-1",
    },
]


def to_hand_curated_event_dict(entry: dict, simbad_cache: dict[str, list]) -> dict:
    detector = DETECTORS[entry["detector_key"]]
    when = datetime.fromisoformat(entry["datetime_utc_str"]).replace(tzinfo=timezone.utc)
    src = source_ecef_unit(entry["ra_deg"], entry["dec_deg"], when)
    geom = trajectory_geometry(src, detector["ecef_km"])
    if entry["id"] in simbad_cache:
        candidates = simbad_cache[entry["id"]]
    else:
        candidates = query_simbad(entry["ra_deg"], entry["dec_deg"], entry["err90_arcmin"])
        time.sleep(0.4)
        simbad_cache[entry["id"]] = candidates
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
        "detector_ecef_km": detector["ecef_km"].tolist(),
        "reference_url": entry.get("reference_url"),
        "source_ecef_unit": [float(src[0]), float(src[1]), float(src[2])],
        "simbad_candidates": candidates,
        **geom,
    }


def query_simbad(ra_deg: float, dec_deg: float, err90_arcmin: float) -> list[dict]:
    """Return up to 5 nearest SIMBAD objects within the 90% error radius.

    On any failure (network, server, query error), returns []. We cache results
    across runs so transient failures don't repeatedly cost the user time.
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
            return []
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
        return candidates[:5]
    except Exception as exc:
        print(f"  SIMBAD lookup failed for RA={ra_deg}, Dec={dec_deg}: {exc}", file=sys.stderr)
        return []


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
        cands = ev.get("simbad_candidates")
        if cands is None:
            continue
        if not cands:
            cache[ev["id"]] = cands     # empty list = no candidates found, valid
        elif all(("ra_deg" in c and "dec_deg" in c) for c in cands):
            cache[ev["id"]] = cands
        # else: skip → re-query
    return cache


def main() -> int:
    print(f"Fetching {GCN_URL}", file=sys.stderr)
    html = fetch_html()
    raw = parse_rows(html)
    print(f"Parsed {len(raw)} table rows", file=sys.stderr)
    rows = latest_revisions(raw)
    print(f"Reduced to {len(rows)} unique events (latest revision per event)", file=sys.stderr)

    simbad_cache = load_simbad_cache()
    print(f"SIMBAD cache: {len(simbad_cache)} events already looked up", file=sys.stderr)

    events = []
    for i, r in enumerate(rows, 1):
        cached = r.run_event in simbad_cache
        if not cached:
            print(f"  [{i}/{len(rows)}] querying SIMBAD for {r.run_event}", file=sys.stderr)
        events.append(to_event_dict(r, simbad_cache))

    print(f"Adding {len(HAND_CURATED_EVENTS)} hand-curated event(s)", file=sys.stderr)
    for entry in HAND_CURATED_EVENTS:
        events.append(to_hand_curated_event_dict(entry, simbad_cache))

    events.sort(key=lambda e: e["datetime_utc"], reverse=True)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_url": GCN_URL,
        "icecube_ecef_km": ICECUBE_ECEF_KM.tolist(),
        "earth_radius_km": EARTH_POLAR_RADIUS_KM,
        "event_count": len(events),
        "events": events,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUTPUT} ({len(events)} events)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
