from __future__ import annotations

import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


class SiteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web" / "index.html").read_text()
        cls.soup = BeautifulSoup(cls.html, "html.parser")
        cls.payload = json.loads((ROOT / "web" / "data" / "events.json").read_text())

    def test_geometry_module_loads_before_application(self):
        scripts = [
            tag.get("src")
            for tag in self.soup.find_all("script")
            if tag.get("src")
        ]
        self.assertLess(scripts.index("geometry.js"), scripts.index("app.js"))

    def test_status_updates_are_announced(self):
        status = self.soup.select_one("#status")
        self.assertEqual(status.get("role"), "status")
        self.assertEqual(status.get("aria-live"), "polite")

    def test_map_has_an_accessible_name(self):
        world_map = self.soup.select_one("#map")
        self.assertEqual(world_map.get("role"), "region")
        self.assertEqual(world_map.get("aria-label"), "Neutrino alert world map")

    def test_km3_metrics_and_localization_match_published_contract(self):
        event = next(
            event for event in self.payload["events"]
            if event["id"] == "KM3-230213A"
        )
        self.assertEqual(event["err50_arcmin"], 72.0)
        self.assertEqual(event["err90_arcmin"], 132.0)
        self.assertIsNone(event["signalness"])
        self.assertIsNone(event["far_per_yr"])

    def test_copy_does_not_repeat_disproved_rate_or_flux_claims(self):
        text = self.soup.get_text(" ", strip=True)
        self.assertNotIn("≈ 50 events / year", text)
        self.assertNotIn("10 14", text)
        self.assertNotIn("Source candidates within 90% error region", text)


if __name__ == "__main__":
    unittest.main()
