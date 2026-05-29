# Astrophysical Neutrino Alert Atlas — project guide

Static site visualizing public astrophysical neutrino alerts on a Leaflet world
map. You enter an observer location; each event's reconstructed sky direction is
back-projected through Earth to an atmospheric entry point, and the
closest-approach distance from the line-of-sight to the observer is computed.
Independent project — not affiliated with any experimental collaboration.

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
.github/workflows/pages.yml           # deploys web/ to GitHub Pages on push to main
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

## Notes

- Geometry verified against an NYC observer (distances 8000–11500 km, sensible).
- GCN scraping keeps the highest-revision row per event.
- SIMBAD lookups are cached; the details panel embeds Aladin Lite.
- AGM overlay registration confirmed via the `--debug` coastline QA pass.
- Markers are uniform-sized; signalness is encoded by color intensity, not size.
- Map constraints, timeline playback, filters, and reset are wired in `app.js`;
  layout is responsive down to 320px.
