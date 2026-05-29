# Astrophysical Neutrino Alert Atlas

A static visualization of public astrophysical neutrino alerts from operating
high-energy neutrino telescopes. Currently ingests IceCube Gold/Bronze alerts
from NASA GCN plus a hand-curated entry for KM3-230213A (KM3NeT/ARCA); the
geometry pipeline is detector-agnostic.

## How it works

IceCube publishes Gold/Bronze alerts for likely-astrophysical TeV–PeV neutrinos
on the [GCN AMON page](https://gcn.gsfc.nasa.gov/amon_icecube_gold_bronze_events.html).
Each alert has a sky direction (RA, Dec) and an arrival time.

For each event, a GitHub Actions cron job runs `scripts/fetch_events.py`,
which:

1. Scrapes the GCN table and keeps the latest revision of each event.
2. Uses astropy to convert (RA, Dec, UTC time) into a unit vector in the
   Earth-fixed (ITRS/ECEF) frame at the event time. That vector is the
   direction the neutrino arrived from, in Earth coordinates.
3. Writes everything to `web/data/events.json`.

The frontend loads that JSON and, given your latitude/longitude, computes the
perpendicular distance from your ECEF position to the line between the source
direction and the detector. Pure 3D vector arithmetic — no astropy in the
browser.

## What this is, and isn't

- **Is**: a geometric reconstruction of where each of ~50 events/year passed,
  with a closest-approach distance to your location.
- **Isn't**: a real-time "neutrino just passed through you" counter (~10¹⁴
  solar/atmospheric neutrinos per cm² per second pass through everything; that
  framing isn't a meaningful event). And it's not a measurement at your
  location — the detector is at the South Pole, and direction errors mean the
  line is a corridor, not a hair.

## Project layout

```
scripts/
  fetch_events.py        # scraper + astropy precompute
  requirements.txt
web/
  index.html             # static page
  app.js                 # ranking + map
  style.css
  data/events.json       # generated; committed by the workflow
.github/workflows/
  update-events.yml      # cron, runs every 3 hours
```

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/fetch_events.py
# then serve web/ with any static server:
python3 -m http.server -d web 8000
# open http://localhost:8000
```

## Deploy

Cloudflare Pages: point at this repo, build output directory `web`, no build
command. The cron in `.github/workflows/update-events.yml` keeps
`web/data/events.json` fresh by committing back to the repo, which triggers
a new Pages deploy automatically.

## Data attribution

Events: NASA GCN/AMON IceCube Gold and Bronze alerts.
Map tiles: OpenStreetMap.
