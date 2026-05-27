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

# WGS84 polar radius. IceCube sits ~1.5 km below the surface but at the km scale
# of "closest approach to a person on Earth," that doesn't matter.
EARTH_POLAR_RADIUS_KM = 6356.752
ICECUBE_ECEF_KM = np.array([0.0, 0.0, -EARTH_POLAR_RADIUS_KM])


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


def trajectory_geometry(source_unit: np.ndarray) -> dict:
    """Compute two geographically meaningful points on Earth for each event.

    - subsource_lat/lon: where on Earth the source was directly overhead at event
      time (just source_unit projected to the surface). Defined for every event.
    - entry_lat/lon: where the neutrino's path entered Earth's atmosphere on its
      way through to IceCube. Only physically meaningful for up-going events
      (source_z > 0 in ECEF, i.e. the source is in the opposite hemisphere from
      IceCube). For down-going events the neutrino doesn't traverse Earth.

    Line: r(t) = ICECUBE + t * source_unit. The trajectory crosses Earth's surface
    at t=0 (IceCube) and t = -2*(ICECUBE . source_unit). The second root is
    positive iff source_z > 0.
    """
    sub_lat, sub_lon = ecef_to_geodetic(source_unit * EARTH_POLAR_RADIUS_KM)
    is_up_going = bool(source_unit[2] > 0)
    if is_up_going:
        t = -2.0 * float(np.dot(ICECUBE_ECEF_KM, source_unit))
        entry = ICECUBE_ECEF_KM + t * source_unit
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


def to_event_dict(row: RawRow) -> dict:
    when = parse_datetime(row.date_str, row.time_str)
    src = source_ecef_unit(row.ra_deg, row.dec_deg, when)
    geom = trajectory_geometry(src)
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
        "source_ecef_unit": [float(src[0]), float(src[1]), float(src[2])],
        **geom,
    }


def main() -> int:
    print(f"Fetching {GCN_URL}", file=sys.stderr)
    html = fetch_html()
    raw = parse_rows(html)
    print(f"Parsed {len(raw)} table rows", file=sys.stderr)
    rows = latest_revisions(raw)
    print(f"Reduced to {len(rows)} unique events (latest revision per event)", file=sys.stderr)

    events = [to_event_dict(r) for r in rows]
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
