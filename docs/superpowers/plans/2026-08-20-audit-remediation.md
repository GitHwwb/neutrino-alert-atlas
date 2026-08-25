# Neutrino Alert Atlas Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the scientific, deployment, data-integrity, accessibility, and
copy issues found in the August 2026 audit.

**Architecture:** Keep the vanilla static application. Move reusable browser
geometry into a small UMD module that Node can test, strengthen the existing
Python generator at its input/output boundaries, and make the scheduled workflow
deploy its validated artifact directly.

**Tech Stack:** Python 3.12, standard `unittest`, Astropy, NumPy, vanilla
JavaScript, Node's built-in test runner, Leaflet, GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-08-20-audit-remediation.md`

## Global Constraints

- Do not add a frontend framework or build step.
- Preserve the existing visual identity and responsive layout.
- Use tests before production changes and observe each regression fail first.
- Keep all Git author settings repository-local to the personal GitHub identity.
- Do not push until personal `GitHwwb` authentication is verified.

---

### Task 1: Finite WGS84 Trajectory Geometry

**Files:**
- Create: `web/geometry.js`
- Create: `tests/test_geometry.js`
- Modify: `web/index.html`
- Modify: `web/app.js`

**Interfaces:**
- Produces: `NeutrinoGeometry.geodeticToEcef(latDeg, lonDeg, altitudeKm)`
- Produces: `NeutrinoGeometry.distancePointToSegment(point, start, end)`
- Consumes: event `detector_ecef_km` and `entry_ecef_km` arrays.

- [x] Write Node tests with hand-derived WGS84 pole/equator coordinates and a
  segment case where the infinite-line answer is zero but the finite-segment
  answer is 3,314.7 km.
- [x] Run `node --test tests/test_geometry.js`; verify failure because
  `web/geometry.js` does not exist.
- [x] Implement the UMD geometry module and load it before `app.js`.
- [x] Replace the browser's spherical observer conversion and point-to-line
  function with the tested module.
- [x] Run `node --test tests/test_geometry.js`; verify all geometry tests pass.

### Task 2: Source-Safe Generator And Data Model

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/fixtures/gcn_sample.html`
- Create: `tests/test_fetch_events.py`
- Modify: `scripts/fetch_events.py`
- Modify: `web/data/events.json`

**Interfaces:**
- Produces: WGS84 `detector_ecef_km`, `entry_ecef_km`, `entry_lat`, and
  `entry_lon` for every active event.
- Produces: nullable `signalness` and `far_per_yr`.
- Produces: `simbad_lookup = {"status": "ok"|"error", "candidates": [...]}`.
- Produces: payload `excluded_events` with source ID and reason.
- Produces: `validate_payload(payload, previous_payload=None)`.

- [x] Add Python tests covering published KM3 localization and null metrics,
  WGS84 surface intersections, exclusion of zero-valued latest revisions,
  SIMBAD error/empty distinction, payload count/schema validation, count
  regression rejection, and unchanged-content detection.
- [x] Run `.venv/bin/python -m unittest discover -s tests -v`; verify the new
  tests fail against the current generator for the audited reasons.
- [x] Implement WGS84 conversion and ellipsoid intersection in the generator.
- [x] Correct KM3-230213A fields and add source-specific energy metadata.
- [x] Change SIMBAD lookup/cache representation and remove the event itself from
  nearby-object results.
- [x] Add active-row validation, payload validation, bounded regression checks,
  atomic output, and content-change detection.
- [x] Run the Python tests and verify they pass.
- [x] Regenerate `web/data/events.json` from the current GCN source and verify it
  passes `validate_payload`.

### Task 3: Nullable Metrics, Accessibility, And Scientific Copy

**Files:**
- Create: `tests/test_site_contract.py`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/style.css`

**Interfaces:**
- Consumes: nullable metrics, `energy_basis`, and `simbad_lookup`.
- Produces: sortable rows with unavailable values ordered last.
- Produces: accessible map/status/details behavior.

- [x] Add contract tests that parse the real HTML and generated JSON to assert:
  the status region is live, the map is named, KM3 metrics are null, the
  published localization is present, and all required scripts load in order.
- [x] Run the contract test and verify it fails against the current page/data.
- [x] Update list/detail formatting and sorting to display unavailable metrics
  honestly and avoid cross-detector comparisons.
- [x] Use fixed KM3NeT marker color while retaining IceCube signalness encoding.
- [x] Rename SIMBAD content to nearby catalog objects and add lookup-failure UI.
- [x] Disable marker keyboard tab stops, name the map, make status updates live,
  and add focus-visible styles for event rows and pagination.
- [x] Correct candidate-alert, annual-rate, flux, uncertainty, and energy copy.
- [x] Run Node, Python, and contract tests; verify they pass.

### Task 4: Reliable Scheduled Deployment

**Files:**
- Modify: `.github/workflows/update-events.yml`
- Modify: `.github/workflows/pages.yml`
- Modify: `scripts/requirements.txt`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Scheduled workflow consumes the validated working-tree artifact.
- Scheduled workflow deploys through the GitHub Pages Actions API.
- Post-deploy verification compares the served and generated dataset metadata.

- [x] Add updater concurrency, fixed runner/Python versions, test and validation
  steps, conditional commit behavior, direct Pages upload/deploy, and
  post-deployment retry verification.
- [x] Keep `pages.yml` for human code pushes and add the same test gate.
- [x] Pin direct Python dependencies to versions installed and verified locally;
  pin official Actions to immutable commit SHAs with release comments.
- [x] Correct README and project-guide deployment, geometry, catalog, and
  freshness descriptions.
- [x] Validate both workflow YAML files with a YAML parser and run all tests.

### Task 5: Rendered QA And Release Gate

**Files:**
- No committed browser artifacts.

**Interfaces:**
- Local URL: `http://127.0.0.1:8765/`

- [x] Start the static server and run the CDP browser audit at `1440x1000` and
  `390x844`.
- [x] Exercise filter, search, details, observer distance, distance sort,
  timeline, AGM overlay, and reset interactions.
- [x] Verify page identity, meaningful DOM, no framework overlay, console
  health, network health, no document overflow, and named/non-focusable map
  markers.
- [x] Capture desktop/mobile screenshots outside the repository.
- [x] Run the complete Python, Node, syntax, JSON, and workflow verification
  suite from a clean command.
- [x] Review `git diff` against every acceptance criterion.
- [ ] Verify the authenticated GitHub account is `GitHwwb` before any push; if it
  is not verifiable, stop and request personal authentication.
