#!/usr/bin/env python3
"""Build the AGM2015 antineutrino-flux map overlays for the web app.

Source data: AGM2015 (Usman, Jocher, Dye, McDonough, Learned 2015),
figures published at https://github.com/ultralytics/agm2015 (AGPL-3.0).
We use the equirectangular ("pcarree") renders of three channels:
    all        - total antineutrino flux
    reactor    - reactor (man-made) component
    geological - geological (U/Th decay) component

What this script does, per channel:
  1. Fetch the source PNG into scripts/agm_src/ (cached; only downloads once).
  2. Detect the true map-data rectangle inside the figure. The source figures
     are full-bleed equirectangular world maps with a few px of black padding
     and a colorbar; crucially the map data spans a clean -180..+180 lon by
     +90..-90 lat, i.e. exactly 2:1. We detect the top/bottom of the map from
     the black padding and DERIVE the right edge as left + 2*height. This is
     robust: it never has to find the colorbar, and it self-checks to 2:1.
  3. Reproject the equirectangular crop to Web Mercator (EPSG:3857), because
     Leaflet's L.imageOverlay stretches an image LINEARLY in projected space.
     The output covers the full Web Mercator world: lon -180..+180,
     lat -85.0511..+85.0511, as a square PNG.
  4. Write web/data/agm2015_<channel>.webp.

The colorbar + its 10^x.y labels are composited onto the eastern Pacific
(roughly +173..+180 lon) WITHIN the map for the 'all' / 'geological' figures,
so they survive the crop and stay visible (a deliberate choice). For 'reactor'
the colorbar is appended east of +180 and is cropped away.

  --debug   also writes scripts/agm_src/_debug_<channel>.png: the reprojected
            overlay with Natural Earth 110m coastlines and a 30deg graticule
            drawn on top. If the coastlines sit on the flux land/ocean
            boundaries, registration is correct and the Leaflet bounds
            [[-85.0511,-180],[85.0511,180]] will line up with the basemap.

Idempotent: re-running reproduces identical outputs; downloads are cached.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import urllib.request

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - certifi should be installed
    _SSL_CTX = ssl.create_default_context()

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "agm_src")
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "web", "data"))

# Raw source figures (URL-encoded spaces) on the ultralytics/agm2015 master branch.
_RAW = "https://raw.githubusercontent.com/ultralytics/agm2015/master/AGM2015%20Figures"
CHANNELS = {
    "all":        f"{_RAW}/AGM2015%20all%20pcarree.png",
    "reactor":    f"{_RAW}/AGM2015%20reactor%20pcarree.png",
    "geological": f"{_RAW}/AGM2015%20geological%20pcarree.png",
}
COASTLINE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_coastline.geojson"
)

# Web Mercator latitude limit (where the projected world becomes square).
MERC_MAX_LAT = 85.05112877980659
OUT_SIZE = 2048  # square Web Mercator output edge, in px


def _download(url: str, dest: str) -> None:
    if os.path.exists(dest):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"  downloading {os.path.basename(dest)} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "agm-build/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as r, open(dest, "wb") as f:
        f.write(r.read())


def detect_map_rect(arr: np.ndarray) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the equirectangular map data.

    The figure has black (0,0,0) padding/frame around the map. We sample a
    left column (col 50, always inside the map, never the eastern colorbar) to
    find the first/last non-black row, then derive width = 2 * height so the
    crop is exactly a -180..180 / 90..-90 globe.
    """
    black = (arr < 45).all(axis=2)
    col = 50
    rows = np.where(~black[:, col])[0]
    if len(rows) == 0:
        raise RuntimeError("no map content found in sample column")
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    height = bottom - top
    left = 0
    right = left + 2 * height
    # self-check: the source should be at least as wide as a 2:1 globe
    if right > arr.shape[1]:
        raise RuntimeError(
            f"derived right edge {right} exceeds image width {arr.shape[1]}"
        )
    return left, top, right, bottom


def reproject_to_mercator(eq: np.ndarray, size: int = OUT_SIZE) -> np.ndarray:
    """Inverse-warp an equirectangular RGBA crop into a square Web Mercator image.

    eq covers lon -180..+180 (cols) and lat +90..-90 (rows). Output covers the
    full Web Mercator square: lon -180..180, lat -MERC_MAX_LAT..+MERC_MAX_LAT.
    """
    if eq.shape[2] == 3:
        eq = np.dstack([eq, np.full(eq.shape[:2], 255, np.uint8)])
    in_h, in_w = eq.shape[:2]

    # Output pixel centers -> Web Mercator coords in [-pi, pi].
    j = np.arange(size)
    i = np.arange(size)
    y_merc = math.pi - (j + 0.5) / size * 2 * math.pi   # +pi at top (north)
    x_merc = -math.pi + (i + 0.5) / size * 2 * math.pi   # -pi at left (west)

    lon = np.degrees(x_merc)                              # (size,)
    lat = np.degrees(2 * np.arctan(np.exp(y_merc)) - math.pi / 2)  # (size,)

    # (lon, lat) -> source pixel indices.
    src_x = (lon + 180.0) / 360.0 * in_w                  # (size,)
    src_y = (90.0 - lat) / 180.0 * in_h                   # (size,)

    # Bilinear sample. Build full index grids.
    sx = np.clip(src_x, 0, in_w - 1.0001)
    sy = np.clip(src_y, 0, in_h - 1.0001)
    x0 = np.floor(sx).astype(int)
    y0 = np.floor(sy).astype(int)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = (sx - x0)[None, :, None]      # (1,size,1)
    fy = (sy - y0)[:, None, None]      # (size,1,1)

    eqf = eq.astype(np.float32)
    # Gather rows (y) and cols (x) via broadcasting.
    X0, Y0 = np.meshgrid(x0, y0)       # (size,size)
    X1, Y1 = np.meshgrid(x1, y1)
    Ia = eqf[Y0, X0]
    Ib = eqf[Y0, X1]
    Ic = eqf[Y1, X0]
    Id = eqf[Y1, X1]
    top = Ia * (1 - fx) + Ib * fx
    bot = Ic * (1 - fx) + Id * fx
    out = top * (1 - fy) + bot * fy
    return np.clip(out, 0, 255).astype(np.uint8)


def _merc_xy(lon: float, lat: float, size: int) -> tuple[float, float]:
    lat = max(-MERC_MAX_LAT, min(MERC_MAX_LAT, lat))
    x_merc = math.radians(lon)
    y_merc = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    col = (x_merc + math.pi) / (2 * math.pi) * size
    row = (math.pi - y_merc) / (2 * math.pi) * size
    return col, row


def draw_debug(out_rgba: np.ndarray, size: int) -> Image.Image:
    """Overlay Natural Earth coastlines + a 30deg graticule for visual QA."""
    img = Image.fromarray(out_rgba, "RGBA").convert("RGB")
    d = ImageDraw.Draw(img)

    # Graticule every 30 deg.
    for lon in range(-150, 181, 30):
        c, _ = _merc_xy(lon, 0, size)
        d.line([(c, 0), (c, size)], fill=(0, 0, 0), width=1)
    for lat in (-60, -30, 0, 30, 60):
        _, r = _merc_xy(0, lat, size)
        d.line([(0, r), (size, r)], fill=(0, 0, 0), width=1)

    # Coastlines (bright magenta so they read over any flux color).
    coast = os.path.join(SRC_DIR, "ne_110m_coastline.geojson")
    _download(COASTLINE_URL, coast)
    gj = json.load(open(coast))

    def draw_line(coords):
        pts = [_merc_xy(lon, lat, size) for lon, lat in coords]
        # split where the segment wraps the dateline to avoid horizontal streaks
        seg = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - seg[-1][0]) > size * 0.5:
                if len(seg) > 1:
                    d.line(seg, fill=(255, 0, 200), width=2)
                seg = [p]
            else:
                seg.append(p)
        if len(seg) > 1:
            d.line(seg, fill=(255, 0, 200), width=2)

    for feat in gj["features"]:
        g = feat["geometry"]
        if g["type"] == "LineString":
            draw_line(g["coordinates"])
        elif g["type"] == "MultiLineString":
            for part in g["coordinates"]:
                draw_line(part)
    return img


def build(debug: bool = False, size: int = OUT_SIZE) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for ch, url in CHANNELS.items():
        print(f"[{ch}]")
        src = os.path.join(SRC_DIR, f"AGM2015_{ch}_pcarree.png")
        _download(url, src)
        arr = np.asarray(Image.open(src).convert("RGBA"))
        left, top, right, bottom = detect_map_rect(arr[:, :, :3])
        crop = arr[top:bottom, left:right]
        h, w = crop.shape[:2]
        print(f"  map rect: left={left} top={top} right={right} bottom={bottom}"
              f"  ({w}x{h}, ratio {w/h:.3f})")
        merc = reproject_to_mercator(crop, size)
        out_path = os.path.join(OUT_DIR, f"agm2015_{ch}.webp")
        # The overlay needs no in-image transparency (the layer's CSS opacity
        # handles blending) and renders at 0.85 opacity with screen blending,
        # so lossy WebP q90 is visually identical — and ~3x smaller than the
        # adaptive-palette PNG this used to write (~230 KB vs ~690 KB).
        Image.fromarray(merc[:, :, :3], "RGB").save(
            out_path, "WEBP", quality=90, method=6
        )
        kb = os.path.getsize(out_path) // 1024
        print(f"  wrote {os.path.relpath(out_path)}  ({size}x{size}, {kb} KB)")
        if debug:
            dbg = draw_debug(merc, size)
            dbg_path = os.path.join(SRC_DIR, f"_debug_{ch}.png")
            dbg.save(dbg_path)
            print(f"  wrote {os.path.relpath(dbg_path)} (coastline QA)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--debug", action="store_true",
                    help="also write coastline-overlay QA images to scripts/agm_src/")
    ap.add_argument("--size", type=int, default=OUT_SIZE,
                    help=f"output square edge in px (default {OUT_SIZE})")
    args = ap.parse_args()
    build(debug=args.debug, size=args.size)
    print("done.")
