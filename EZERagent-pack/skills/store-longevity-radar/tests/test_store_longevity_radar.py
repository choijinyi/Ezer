import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import store_longevity_radar as radar


class HistoricalCodesTest(unittest.TestCase):
    def test_default_codes_expand_to_matching_legacy_codes(self):
        self.assertEqual(
            radar.historical_codes({"G21302", "G21306"}),
            {"G21302", "G21306", "D08A01", "D04A01", "D04A02"},
        )

    def test_custom_code_does_not_include_default_legacy_codes(self):
        self.assertEqual(radar.historical_codes({"G99999"}), {"G99999"})


class DownloadFailureTest(unittest.TestCase):
    def test_timeout_reports_unavailable_json(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            with (
                patch.object(radar, "CACHE_DIR", cache_dir),
                patch.object(radar, "http_get", side_effect=TimeoutError("timed out")),
                self.assertRaises(SystemExit) as raised,
            ):
                radar.download_latest_zip()

        payload = json.loads(str(raised.exception))
        self.assertEqual(payload["status"], "unavailable")
        self.assertIn("timed out", payload["note"])


if __name__ == "__main__":
    unittest.main()
