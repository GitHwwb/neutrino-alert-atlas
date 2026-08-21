from __future__ import annotations

import json
import math
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts import fetch_events as fe


FIXTURE = Path(__file__).parent / "fixtures" / "gcn_sample.html"


class Wgs84GeometryTests(unittest.TestCase):
    def test_geodetic_to_ecef_uses_wgs84_axes(self):
        equator = fe.geodetic_to_ecef_km(0.0, 0.0)
        pole = fe.geodetic_to_ecef_km(90.0, 0.0)

        np.testing.assert_allclose(equator, [6378.137, 0.0, 0.0], atol=1e-6)
        np.testing.assert_allclose(
            pole,
            [0.0, 0.0, 6356.752314245],
            atol=1e-6,
        )

    def test_surface_intersection_is_on_wgs84_ellipsoid(self):
        detector = fe.geodetic_to_ecef_km(-90.0, 0.0, depth_m=1950.0)
        source = np.array([0.6, 0.0, 0.8])
        source /= np.linalg.norm(source)

        entry = fe.atmospheric_entry_ecef_km(detector, source)
        ellipsoid_value = (
            (entry[0] ** 2 + entry[1] ** 2) / fe.WGS84_A_KM**2
            + entry[2] ** 2 / fe.WGS84_B_KM**2
        )

        self.assertAlmostEqual(ellipsoid_value, 1.0, places=10)
        self.assertGreater(np.dot(entry - detector, source), 0.0)

    def test_subsource_uses_local_wgs84_zenith_not_geocentric_radius(self):
        detector = fe.geodetic_to_ecef_km(-90.0, 0.0, depth_m=1950.0)
        source = np.array([math.sqrt(0.5), 0.0, math.sqrt(0.5)])

        geometry = fe.trajectory_geometry(source, detector)

        self.assertAlmostEqual(geometry["subsource_lat"], 45.0, places=9)
        self.assertAlmostEqual(geometry["subsource_lon"], 0.0, places=9)

    def test_upgoing_classification_uses_local_zenith_off_the_pole(self):
        detector = fe.DETECTORS["km3net-arca"]
        lat = math.radians(detector["lat_deg"])
        lon = math.radians(detector["lon_deg"])
        local_up = np.array([
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        ])

        down_going = fe.trajectory_geometry(local_up, detector["ecef_km"])
        up_going = fe.trajectory_geometry(-local_up, detector["ecef_km"])

        self.assertFalse(down_going["is_up_going"])
        self.assertTrue(up_going["is_up_going"])


class CatalogSemanticsTests(unittest.TestCase):
    def test_zero_valued_highest_revision_is_excluded_without_reviving_old_data(self):
        rows = fe.latest_revisions(fe.parse_rows(FIXTURE.read_text()))

        active, excluded = fe.partition_active_rows(rows)

        self.assertEqual([row.run_event for row in active], ["100002_200002"])
        self.assertEqual(
            excluded,
            [
                {
                    "id": "100001_200001",
                    "rev": 1,
                    "reason": "latest revision has unavailable alert metrics",
                },
                {
                    "id": "100003_200003",
                    "rev": 1,
                    "reason": "latest revision has unavailable alert metrics",
                },
            ],
        )

    def test_km3_uses_published_localization_and_no_invented_icecube_metrics(self):
        event = fe.HAND_CURATED_EVENTS[0]

        self.assertEqual(event["err50_arcmin"], 72.0)
        self.assertEqual(event["err90_arcmin"], 132.0)
        self.assertIsNone(event["signalness"])
        self.assertIsNone(event["far_per_yr"])
        self.assertIn("E^-2", event["energy_basis"])

    def test_simbad_cache_keeps_only_confirmed_successful_lookups(self):
        payload = {
            "events": [
                {
                    "id": "ok-empty",
                    "simbad_lookup": {"status": "ok", "candidates": []},
                },
                {
                    "id": "failed",
                    "simbad_lookup": {
                        "status": "error",
                        "candidates": [],
                        "message": "timeout",
                    },
                },
                {"id": "legacy-ambiguous", "simbad_candidates": []},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "events.json"
            output.write_text(json.dumps(payload))
            with patch.object(fe, "OUTPUT", output):
                cache = fe.load_simbad_cache()

        self.assertEqual(cache, {"ok-empty": []})

    def test_neutrino_alert_records_are_removed_from_nearby_objects(self):
        lookup = {
            "status": "ok",
            "candidates": [
                {
                    "name": "IceCube-250309A",
                    "otype": "ev",
                    "sep_arcmin": 0.005,
                    "ra_deg": 10.0,
                    "dec_deg": 20.0,
                },
                {
                    "name": "NAME KM3-230213A",
                    "otype": "ev",
                    "sep_arcmin": 0.0,
                    "ra_deg": 10.0,
                    "dec_deg": 20.0,
                },
                {
                    "name": "Nearby galaxy",
                    "otype": "G",
                    "sep_arcmin": 0.001,
                    "ra_deg": 10.0,
                    "dec_deg": 20.0,
                },
            ],
        }

        filtered = fe.remove_neutrino_alert_records(lookup)

        self.assertEqual(
            [candidate["name"] for candidate in filtered["candidates"]],
            ["Nearby galaxy"],
        )


class PayloadValidationTests(unittest.TestCase):
    @staticmethod
    def event(event_id: str) -> dict:
        return {
            "id": event_id,
            "datetime_utc": "2026-08-20T00:00:00Z",
            "notice_type": "GOLD",
            "ra_deg": 10.0,
            "dec_deg": 20.0,
            "err90_arcmin": 30.0,
            "err50_arcmin": 12.0,
            "energy": 100.0,
            "signalness": 0.7,
            "far_per_yr": 0.2,
            "comments": "Test event",
            "detector": "Test detector",
            "detector_lat": 0.0,
            "detector_lon": 0.0,
            "detector_ecef_km": [6376.187, 0.0, 0.0],
            "entry_ecef_km": [6378.137, 0.0, 0.0],
            "source_ecef_unit": [1.0, 0.0, 0.0],
            "is_up_going": False,
            "entry_lat": 0.0,
            "entry_lon": 0.0,
            "subsource_lat": 0.0,
            "subsource_lon": 0.0,
            "energy_basis": "Test energy basis",
            "metrics_source": "Test source",
            "simbad_lookup": {"status": "ok", "candidates": []},
        }

    def test_validate_payload_rejects_duplicate_ids(self):
        payload = {
            "event_count": 2,
            "events": [self.event("same"), self.event("same")],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "duplicate event IDs"):
            fe.validate_payload(payload, minimum_events=1)

    def test_validate_payload_rejects_large_count_regression(self):
        previous = {
            "event_count": 10,
            "events": [self.event(f"old-{i}") for i in range(10)],
        }
        current = {
            "event_count": 5,
            "events": [self.event(f"new-{i}") for i in range(5)],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "dropped"):
            fe.validate_payload(
                current,
                previous_payload=previous,
                minimum_events=1,
                max_drop_fraction=0.10,
            )

    def test_content_comparison_ignores_generation_timestamp_only(self):
        event = self.event("event")
        older = {
            "generated_at_utc": "2026-08-20T00:00:00Z",
            "event_count": 1,
            "events": [event],
            "excluded_events": [],
        }
        newer = deepcopy(older)
        newer["generated_at_utc"] = "2026-08-20T03:00:00Z"

        self.assertFalse(fe.payload_content_changed(newer, older))
        newer["events"][0] = {**event, "energy": 101.0}
        self.assertTrue(fe.payload_content_changed(newer, older))

    def test_validate_payload_rejects_entry_off_forward_source_ray(self):
        event = self.event("bad-entry")
        event["entry_ecef_km"] = [6376.187, 2.0, 0.0]
        payload = {
            "event_count": 1,
            "events": [event],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "entry point"):
            fe.validate_payload(payload, minimum_events=1)

    def test_validate_payload_rejects_invalid_map_coordinates(self):
        event = self.event("bad-map-coordinate")
        event["subsource_lat"] = 91.0
        payload = {
            "event_count": 1,
            "events": [event],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "geographic coordinates"):
            fe.validate_payload(payload, minimum_events=1)

    def test_validate_payload_rejects_nonfinite_optional_metric(self):
        event = self.event("bad-far")
        event["far_per_yr"] = float("nan")
        payload = {
            "event_count": 1,
            "events": [event],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "false-alarm rate"):
            fe.validate_payload(payload, minimum_events=1)

    def test_validate_payload_rejects_boolean_numeric_values(self):
        event = self.event("boolean-energy")
        event["energy"] = True
        payload = {
            "event_count": 1,
            "events": [event],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "positive-valued metrics"):
            fe.validate_payload(payload, minimum_events=1)

    def test_validate_payload_requires_nonempty_text_fields(self):
        event = self.event("empty-detector")
        event["detector"] = ""
        payload = {
            "event_count": 1,
            "events": [event],
            "excluded_events": [],
        }

        with self.assertRaisesRegex(ValueError, "text field"):
            fe.validate_payload(payload, minimum_events=1)


if __name__ == "__main__":
    unittest.main()
