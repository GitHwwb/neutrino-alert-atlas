"""Build the 1200x630 Open Graph / social card (web/og-card.png).

Real data, same visual language as the site: every event in
web/data/events.json plotted at its Earth entry / sub-source point
(equirectangular), tier-colored by signalness exactly like app.js
eventColor(), over faint Natural Earth coastlines, with the site's
Instrument Serif / JetBrains Mono type.

Fonts and coastlines are cached in scripts/agm_src/ (gitignored).
Idempotent given unchanged inputs. Re-run after major catalog changes:

    .venv/bin/python scripts/build_og_card.py
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request

import certifi
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "agm_src")
EVENTS = os.path.join(HERE, "..", "web", "data", "events.json")
COAST = os.path.join(CACHE, "ne_110m_coastline.geojson")
OUT = os.path.normpath(os.path.join(HERE, "..", "web", "og-card.png"))

W, H = 1200, 630
SS = 2  # supersample factor for antialiased dots/lines

# Palette (mirrors style.css / app.js)
BG_TOP, BG_BOTTOM = (9, 13, 21), (6, 8, 12)
COAST_COLOR = (32, 40, 58)
INK = (243, 245, 248)
MUTED = (139, 147, 165)
ACCENT = (121, 209, 255)
TIER_BASE = {"GOLD": (245, 207, 78), "BRONZE": (207, 138, 68), "KM3NET": (106, 209, 255)}
MUTED_LOW = (60, 71, 96)

_GF = "https://raw.githubusercontent.com/google/fonts/main/ofl"
FONTS = {
    "InstrumentSerif-Regular.ttf": f"{_GF}/instrumentserif/InstrumentSerif-Regular.ttf",
    "InstrumentSerif-Italic.ttf": f"{_GF}/instrumentserif/InstrumentSerif-Italic.ttf",
    "JetBrainsMono.ttf": f"{_GF}/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
}


def _fetch(url: str, dest: str) -> str:
    if not os.path.exists(dest):
        print(f"  downloading {os.path.basename(dest)}")
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, context=ctx) as r, open(dest, "wb") as f:
            f.write(r.read())
    return dest


def event_color(e: dict) -> tuple[int, int, int]:
    # Port of app.js eventColor(): mix muted slate -> tier color by signalness.
    sig = max(0.0, min(1.0, e["signalness"]))
    t = 0.15 + 0.85 * sig
    base = TIER_BASE.get(e["notice_type"], TIER_BASE["BRONZE"])
    return tuple(round(m + (b - m) * t) for m, b in zip(MUTED_LOW, base))


def project(lat: float, lon: float) -> tuple[float, float]:
    # Equirectangular, map spans the full canvas width at 2:1 (1200x600),
    # vertically centered in the 630px canvas.
    x = (lon + 180.0) / 360.0 * W
    y = (90.0 - lat) / 180.0 * (W / 2) + (H - W / 2) / 2
    return x * SS, y * SS


def vertical_gradient(w: int, h: int) -> Image.Image:
    t = np.linspace(0.0, 1.0, h)[:, None, None]
    top = np.array(BG_TOP, dtype=float)[None, None, :]
    bot = np.array(BG_BOTTOM, dtype=float)[None, None, :]
    arr = (top + (bot - top) * t).astype(np.uint8)
    return Image.fromarray(np.broadcast_to(arr, (h, w, 3)).copy(), "RGB")


def draw_coastlines(draw: ImageDraw.ImageDraw) -> None:
    with open(COAST) as f:
        gj = json.load(f)
    for feat in gj["features"]:
        geom = feat["geometry"]
        lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for line in lines:
            pts = [project(lat, lon) for lon, lat in line]
            draw.line(pts, fill=COAST_COLOR, width=SS)


def draw_events(draw: ImageDraw.ImageDraw, events: list[dict]) -> None:
    # Low-signalness first so confident events render on top in dense areas.
    for e in sorted(events, key=lambda e: e["signalness"]):
        up = e["is_up_going"]
        lat = e["entry_lat"] if up else e["subsource_lat"]
        lon = e["entry_lon"] if up else e["subsource_lon"]
        if lat is None or lon is None:
            continue
        x, y = project(lat, lon)
        c = event_color(e)
        if up:
            r = 4.5 * SS
            draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
        else:
            r = 7 * SS
            draw.ellipse([x - r, y - r, x + r, y + r], outline=c, width=round(2.5 * SS))


def main() -> None:
    for name, url in FONTS.items():
        _fetch(url, os.path.join(CACHE, name))

    with open(EVENTS) as f:
        payload = json.load(f)
    events = payload["events"]
    years = sorted(e["datetime_utc"][:4] for e in events)

    img = vertical_gradient(W * SS, H * SS)
    draw = ImageDraw.Draw(img)
    draw_coastlines(draw)
    draw_events(draw, events)
    img = img.resize((W, H), Image.LANCZOS)

    # Type block (drawn at final size: text needs no supersampling with PIL's
    # own rasterizer, and 1:1 keeps the optical sizes predictable).
    draw = ImageDraw.Draw(img)
    serif = ImageFont.truetype(os.path.join(CACHE, "InstrumentSerif-Regular.ttf"), 88)
    serif_it = ImageFont.truetype(os.path.join(CACHE, "InstrumentSerif-Italic.ttf"), 88)
    mono = ImageFont.truetype(os.path.join(CACHE, "JetBrainsMono.ttf"), 25)
    mono.set_variation_by_axes([500])

    x0, y0 = 64, 56
    draw.text((x0, y0), "INTERACTIVE VISUALIZATION · ICECUBE + KM3NET", font=mono, fill=MUTED)
    draw.text((x0, y0 + 52), "Astrophysical Neutrino", font=serif, fill=INK)
    draw.text((x0, y0 + 144), "Alert Atlas", font=serif_it, fill=ACCENT)

    stats = f"{payload['event_count']} EVENTS · {years[0]}–{years[-1]} · UPDATED EVERY 3 H"
    # Halo stroke in the background color so the line stays legible where
    # event dots crowd the southern hemisphere.
    draw.text((x0, H - 92), stats, font=mono, fill=MUTED,
              stroke_width=5, stroke_fill=BG_BOTTOM)

    img.save(OUT, optimize=True)
    print(f"wrote {os.path.relpath(OUT)} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
