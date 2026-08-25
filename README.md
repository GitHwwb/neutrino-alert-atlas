# Astrophysical Neutrino Alert Atlas

A static visualization of public high-energy neutrino candidate alerts.
Currently ingests IceCube Gold/Bronze alerts from NASA GCN plus a hand-curated
entry for KM3-230213A (KM3NeT/ARCA); the geometry pipeline is
detector-agnostic.

https://githwwb.github.io/neutrino-alert-atlas/

## How it works

IceCube publishes Gold/Bronze candidate alerts for TeV–PeV neutrinos
on the [GCN AMON page](https://gcn.gsfc.nasa.gov/amon_icecube_gold_bronze_events.html).
Each alert has a sky direction (RA, Dec) and an arrival time.

For each event, a GitHub Actions cron job runs `scripts/fetch_events.py`,
which:

1. Scrapes the GCN table, keeps the latest revision of each event, and excludes
   revisions whose alert metrics were zeroed by the source.
2. Uses astropy to convert (RA, Dec, UTC time) into a unit vector in the
   Earth-fixed (ITRS/ECEF) frame at the event time. That vector is the
   direction the neutrino arrived from, in Earth coordinates.
3. Intersects the incoming ray with the WGS84 ellipsoid and validates the
   complete payload before atomically replacing `web/data/events.json`.

The frontend loads that JSON and, given your latitude/longitude, computes the
shortest distance from your WGS84 position to the finite atmospheric-entry to
detector segment. Pure vector arithmetic runs in the browser; Astropy remains
in the data pipeline.

## What this is, and isn't

- **Is**: a geometric reconstruction of candidate-alert directions, with a
  closest-approach distance to your location.
- **Isn't**: confirmation that every alert is astrophysical, a measurement at
  your location, or a real-time count of the much larger low-energy neutrino
  flux passing through Earth. Direction uncertainty makes each trajectory a
  corridor rather than an exact line.

## Project layout

```
scripts/
  fetch_events.py        # scraper + astropy precompute
  requirements.txt
web/
  index.html             # static page
  geometry.js            # tested WGS84 + finite-segment browser math
  app.js                 # ranking + map
  style.css
  data/events.json       # generated; committed by the workflow
.github/workflows/
  update-events.yml      # cron: test, update, deploy, verify
  pages.yml              # deploy tested site changes on pushes to main
tests/
  test_geometry.js       # browser-math regressions
  test_*.py              # pipeline and page-contract regressions
```

## Running locally

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt
.venv/bin/python scripts/fetch_events.py
# then serve web/ with any static server:
python3 -m http.server -d web 8000
# open http://localhost:8000
```

Run the complete automated suite:

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v
node --test tests/test_geometry.js
node --check web/geometry.js
node --check web/app.js
.venv/bin/python scripts/fetch_events.py --validate-only
```

## Deploy

GitHub Pages serves `web/`. Human pushes to `main` run `pages.yml`. The
three-hour `update-events.yml` schedule tests and validates the catalog, commits
only substantive data changes, deploys the validated working-tree artifact
directly, and verifies the served generation timestamp. It does not depend on a
bot-authored push starting a second workflow.

## Data attribution

- Events: NASA GCN/AMON IceCube Gold and Bronze candidate alerts;
  KM3-230213A from Aiello et al. 2025, Nature 638:376. KM3NeT signalness and
  false-alarm rate are left unavailable because the paper does not publish
  IceCube-comparable values.
- Map tiles: © OpenStreetMap contributors, © CARTO.
- AGM2015 antineutrino-flux overlays: derived (cropped + reprojected) from the
  figures in [ultralytics/agm2015](https://github.com/ultralytics/agm2015)
  (AGPL-3.0), based on Usman et al. 2015.

## License

Copyright © 2026 Jonathan Lopes.

This project is licensed under the **GNU Affero General Public License v3.0**
(AGPL-3.0) — see [`LICENSE`](LICENSE). AGPL-3.0 is used because the AGM2015
flux overlays are derived from AGPL-3.0 source material (see Data attribution),
and that copyleft obligation extends to the work as a whole. If you run a
modified version of this site as a network service, the AGPL requires you to
offer your users the corresponding source.

Bundled/loaded third-party components keep their own licenses: Leaflet (BSD-2),
Aladin Lite, and the Google-hosted fonts (SIL Open Font License) are loaded at
runtime from their respective CDNs and are not redistributed here.
