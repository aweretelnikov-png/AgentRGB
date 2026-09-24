"""Offline validation of the loopback WebHID metadata collector."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "phase-04b" / "webhid-diagnostic"))
from serve import validate_snapshot  # noqa: E402


class WebHidServeTests(unittest.TestCase):
    def setUp(self):
        self.good = {
            "vendorId": 0x258A, "productId": 0x010C, "productName": "AULA F75",
            "collections": [{
                "usagePage": 0xFF00, "usage": 1, "inputReports": [],
                "outputReports": [], "featureReports": [5],
                "children": [{"usagePage": 0xFF00, "usage": 2, "inputReports": [],
                              "outputReports": [], "featureReports": [6], "children": []}],
            }],
        }

    def test_accepts_recursive_sanitized_metadata(self):
        self.assertIs(validate_snapshot(self.good), self.good)

    def test_rejects_serial_and_extra_fields_even_in_children(self):
        self.good["serialNumber"] = "private"
        with self.assertRaises(ValueError):
            validate_snapshot(self.good)
        del self.good["serialNumber"]
        self.good["collections"][0]["children"][0]["path"] = "private"
        with self.assertRaises(ValueError):
            validate_snapshot(self.good)


if __name__ == "__main__":
    unittest.main()
