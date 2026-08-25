# Astrophysical Neutrino Alert Atlas — project guide

Static site visualizing public high-energy neutrino candidate alerts on a
Leaflet world map. Observer distance is computed from a WGS84 position to the
finite atmospheric-entry-to-detector trajectory segment.
Independent project — not affiliated with any experimental collaboration.

## Run it

```bash
# Dev server (static files in web/). Open http://localhost:8765 in Chrome
# (Safari blocks HTTP). No cache-busting — assets rely on Pages' max-age=600
# + ETag in prod; locally hard-refresh (Cmd+Shift+R) if an edit looks stale.
python3 -m http.server -d web 8765
```

Python pipeline uses the Python 3.12 venv at `.venv/`. Use `.venv/bin/python`
directly.

## Layout

```
scripts/
  fetch_events.py        # GCN scraper + geometry (ECEF/ITRS) + SIMBAD lookup -> web/data/events.json
  build_agm_layers.py    # builds the AGM2015 flux overlays (see below)
  build_og_card.py       # renders web/og-card.png (social preview) from events.json
  requirements.txt
  agm_src/               # gitignored cache: source figures, coastline geojson, --debug QA renders
web/
  index.html  geometry.js  app.js  style.css
  data/  events.json + agm2015_{all,reactor,geological}.webp
.github/workflows/update-events.yml   # cron, every 3h, re-runs fetch_events.py
.github/workflows/pages.yml           # deploys web/ to GitHub Pages on push to main
tests/                                # Python contracts + Node geometry tests
```

## Stack

Vanilla HTML/CSS/JS (no framework, no build step). Leaflet 1.9.4 + CartoDB
Voyager raster tiles. Aladin Lite v3 (lazy-loaded sky view in the details
panel). Fonts: Geist (sans), Instrument Serif (H1), JetBrains Mono (IDs).

Catalog counts are generated data and must not be hardcoded in project
instructions. IceCube records come from GCN; KM3-230213A is hand-curated from
Aiello et al. 2025, Nature 638:376. KM3NeT has no IceCube-comparable
signalness/FAR, so those values remain null.

## AGM2015 overlay

`scripts/build_agm_layers.py` builds the three antineutrino-flux overlays
(Usman et al. 2015; source figures from github.com/ultralytics/agm2015, AGPL-3.0).

```bash
.venv/bin/python scripts/build_agm_layers.py            # build overlays
.venv/bin/python scripts/build_agm_layers.py --debug    # + coastline QA images in scripts/agm_src/_debug_*.png
```

It downloads + caches the source `pcarree` figures, crops each to its true map
rectangle (full-globe equirectangular, verified 2:1), reprojects
equirectangular -> Web Mercator, and writes 2048² WebP (q90) images to
`web/data/`. Idempotent (byte-identical re-runs). The overlay is placed at the
clean Web Mercator bounds `[[-85.0511,-180],[85.0511,180]]` in `ensureAgmLayer()`
in `app.js`. The colorbar + `10^x` labels are composited over the eastern
Pacific and kept visible by design.

## Notes

- Geometry is regression-tested in `tests/test_geometry.js`; never replace the
  finite segment with an infinite line.
- GCN scraping keeps the highest revision and records zero-valued latest
  revisions as excluded rather than reviving stale metrics.
- Only successful SIMBAD lookups are cached; proximity means nearby catalog
  object, not physical source association.
- AGM overlay registration confirmed via the `--debug` coastline QA pass.
- IceCube markers encode signalness by color intensity; KM3NeT uses fixed cyan.
- Map constraints, timeline playback, filters, and reset are wired in `app.js`;
  layout is responsive down to 320px.
- Scheduled updates deploy directly and verify the served artifact because
  `GITHUB_TOKEN` pushes do not trigger the separate Pages workflow.
