# Astrophysical Neutrino Alert Atlas — project guide

Static site visualizing public astrophysical neutrino alerts on a Leaflet world
map. The user enters an observer location; each event's reconstructed sky
direction is back-projected through Earth to an atmospheric entry point, and the
closest-approach distance from the line-of-sight to the observer is computed.
Independent editorial/scientific project — **not affiliated with any
experimental collaboration** (keep that framing).

## Run it

```bash
# Dev server (static files in web/). Open http://localhost:8765 in Chrome
# (Safari blocks HTTP). Cache-busting on app.js + style.css means edits show
# up on reload without a hard refresh.
python3 -m http.server -d web 8765
```

Python pipeline uses the venv at `.venv/` (astropy, astroquery, beautifulsoup4,
certifi, numpy, pillow, scipy). Use `.venv/bin/python` directly.

## Layout

```
scripts/
  fetch_events.py        # GCN scraper + geometry (ECEF/ITRS) + SIMBAD lookup -> web/data/events.json
  build_agm_layers.py    # builds the AGM2015 flux overlays (see below)
  requirements.txt
  agm_src/               # gitignored cache: source figures, coastline geojson, --debug QA renders
web/
  index.html  app.js  style.css
  data/  events.json + agm2015_{all,reactor,geological}.png
.github/workflows/update-events.yml   # cron, every 3h, re-runs fetch_events.py
```

## Stack

Vanilla HTML/CSS/JS (no framework, no build step). Leaflet 1.9.4 + CartoDB
Voyager raster tiles. Aladin Lite v3 (lazy-loaded sky view in the details
panel). Fonts: Geist (sans), Instrument Serif (H1), JetBrains Mono (IDs).

Catalog: 182 events — 181 IceCube Gold/Bronze scraped from GCN, plus 1
hand-curated KM3-230213A (KM3NeT/ARCA, 220 PeV, Aiello et al. 2025 Nature
638:376) in `HAND_CURATED_EVENTS` in `fetch_events.py`.

## AGM2015 overlay

`scripts/build_agm_layers.py` builds the three antineutrino-flux overlays
(Usman et al. 2015; source figures from github.com/ultralytics/agm2015, AGPL-3.0).

```bash
.venv/bin/python scripts/build_agm_layers.py            # build overlays
.venv/bin/python scripts/build_agm_layers.py --debug    # + coastline QA images in scripts/agm_src/_debug_*.png
```

It downloads + caches the source `pcarree` figures, crops each to its true map
rectangle (full-globe equirectangular, verified 2:1), reprojects
equirectangular -> Web Mercator, and writes 2048² adaptive-palette PNGs to
`web/data/`. Idempotent (byte-identical re-runs). The overlay is placed at the
clean Web Mercator bounds `[[-85.0511,-180],[85.0511,180]]` in `ensureAgmLayer()`
in `app.js`. The colorbar + `10^x` labels are composited over the eastern
Pacific and kept visible by design.

## Verified working — don't refactor without reason

- Geometry math (verified vs NYC observer, distances 8000–11500 km, sensible)
- GCN scraping + highest-revision dedup
- SIMBAD lookup with caching + Aladin Lite embed
- AGM overlay alignment (coastline QA + in-browser checks confirm registration)
- Map constraints, timeline play, filters, reset, mobile responsive to 320px

## Session notes (2026-05-29) — UNCOMMITTED

The repo has a single "Initial commit" on `main`; **everything below plus the
prior session's work is uncommitted in the working tree.** Nothing is pushed.
Commit/push only when the user asks; if you do, branch off `main` first.

This session fixed three things (all verified in-browser via the Chrome MCP):

1. **Down-going selection clutter** (`web/style.css`). A selected down-going
   used to stack a dot+halo reticle inside the large ~600 km highlight ring
   (`drawTrajectory()`). Now: selected up-going = small dot + halo; selected
   down-going **hides its marker glyph** so the 600 km ring is the only
   indicator (one clean ring, no central dot). Deselect restores the 13px
   hollow ring. Also removed a dead, unstyled `.sub-pin` divIcon from
   `drawTrajectory()` in `app.js`.

2. **AGM2015 overlay was skewed right.** Root cause: a bad heuristic crop + a
   `+217.6°` east-bound fudge. Replaced with the proper `build_agm_layers.py`
   and clean `±180` bounds (see AGM section above). `requirements.txt` gained
   `pillow`; `.gitignore` gained `scripts/agm_src/`; the AGM explainer in
   `index.html` was updated.

3. **No auto-scroll on event click.** Removed `els.details.scrollIntoView(...)`
   in `showDetails()` (`app.js`). Clicking an event (marker OR list item)
   reveals the details panel but keeps the viewport on the map. **Don't
   reintroduce the scroll.**

## Accumulated user preferences

- Real, published data over homemade extrapolation (they rejected a synthesized
  reactor heatmap; AGM2015 is the real dataset).
- Scientific/editorial aesthetic, not "AI slop": avoid Inter/Roboto/Arial,
  avoid uniform rounded corners, avoid purple, vary type/color intentionally.
- Markers are uniform-sized; signalness is encoded by color intensity, not size.
- Figma plugin work is paused — the `figma:*` skills load but their MCP tools
  aren't reachable from Claude Code (they live in the Desktop app's MCP context).
