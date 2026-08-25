from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_og_card


class OgCardTests(unittest.TestCase):
    def test_fetch_creates_its_ignored_cache_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "nested" / "asset.bin"
            with patch.object(
                build_og_card.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b"asset"),
            ):
                result = build_og_card._fetch(
                    "https://example.com/asset.bin",
                    str(destination),
                )

            self.assertEqual(result, str(destination))
            self.assertEqual(destination.read_bytes(), b"asset")

    def test_km3_event_color_does_not_require_icecube_signalness(self):
        color = build_og_card.event_color({
            "notice_type": "KM3NET",
            "signalness": None,
        })

        self.assertEqual(color, build_og_card.TIER_BASE["KM3NET"])


if __name__ == "__main__":
    unittest.main()
