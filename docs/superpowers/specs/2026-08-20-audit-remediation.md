# Neutrino Alert Atlas Audit Remediation

## Objective

Correct every material issue found in the August 2026 audit without changing
the site's visual identity or adding a framework.

## Scientific Contract

- Treat catalog entries as candidate alerts, not confirmed astrophysical events.
- Compute observer distance to the finite incoming trajectory segment from the
  atmospheric entry point to the detector.
- Convert ordinary latitude/longitude with the WGS84 ellipsoid.
- Preserve source-specific energy semantics.
- Store unavailable metrics as `null`; never synthesize IceCube signalness or
  false-alarm-rate fields for KM3NeT.
- Use the published KM3-230213A containment radii: 1.2 degrees at 50% and
  2.2 degrees at 90%.
- Label SIMBAD results as nearby catalog objects, not source candidates.
- Distinguish a successful empty SIMBAD result from a failed lookup.
- Exclude highest-revision GCN rows with invalid zero-valued alert metrics from
  the active map while recording their IDs and exclusion reason in the payload.

## Pipeline Contract

- Reject malformed or unexpectedly small upstream catalogs before replacing the
  last known-good artifact.
- Validate required fields, unique IDs, coordinate ranges, unit-vector norms,
  event counts, and bounded count regression.
- Write `events.json` atomically.
- Do not create a repository commit when only the fetch timestamp changed.
- A successful scheduled update must deploy GitHub Pages directly; it must not
  rely on a bot-authored push to trigger another workflow.
- Verify the served dataset after deployment.
- Serialize scheduled updater runs and preserve the last known-good deployment
  on failure.

## Frontend Contract

- Support nullable signalness and false-alarm-rate fields in filtering, sorting,
  color encoding, list rows, and details.
- Give the map an accessible name.
- Avoid hundreds of unnamed marker tab stops; the accessible event list remains
  the keyboard path to event details.
- Announce asynchronous status changes and provide visible focus on interactive
  event rows.
- Keep the existing responsive layout, map controls, timeline, AGM overlay, and
  visual styling.
- Remove or correct unsupported rate, flux, certainty, and cross-detector
  comparability claims.

## Repository And Identity Constraints

- Work only in `/Users/flopjona/Projects/neutrino-alert-atlas-personal`.
- Use repository-local author identity
  `GitHwwb <132339858+GitHwwb@users.noreply.github.com>`.
- Do not use the global Twitch/work identity for commits.
- Do not authenticate, push, or deploy until the active GitHub identity is
  explicitly verified as the personal `GitHwwb` account.

## Acceptance Criteria

- Python and Node regression tests pass.
- The generated payload validates and contains no fabricated KM3NeT metrics.
- A known down-going antipodal continuation no longer reports zero distance.
- The local site passes desktop and mobile smoke tests with no relevant console
  or network errors.
- The mobile accessibility tree has no unnamed event-marker buttons.
- Workflow syntax is valid and the deployment path no longer depends on a
  `GITHUB_TOKEN` push triggering `pages.yml`.
- README and project guide describe the deployed system accurately.
