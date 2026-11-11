import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("cira_dashboard_data", Path(__file__).resolve().parents[1] / "dashboard" / "data.py")
data = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(data)


class FakeBlob:
    def __init__(self, payload):
        self.payload = payload

    def readall(self):
        return self.payload


class FakeContainer:
    def __init__(self, blobs):
        self.blobs = blobs

    def download_blob(self, path):
        return FakeBlob(self.blobs[path])


def build(present, excluded=None, run_id="run1"):
    batch = "20261112T000000Z-abc"
    prefix = f"financial-intelligence/batches/{batch}/"
    blobs, reports, artifacts = {}, [], []
    for t in present:
        report = json.dumps({"ticker": t, "schema_version": "1.0", "run_id": run_id,
                             "data_quality": {"independently_verified_bcg": False, "investment_recommendation": None}}).encode()
        prices = json.dumps({"symbol": t, "records": []}).encode()
        for path, payload, bucket in ((prefix + f"company-intelligence/{t}-company-intelligence.json", report, reports),
                                      (prefix + f"market-data/{t}-daily-prices.json", prices, artifacts)):
            blobs[path] = payload
            bucket.append({"ticker": t, "blob_path": path, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)})
    manifest = {"status": "complete", "batch_id": batch, "run_id": run_id, "report_count": len(reports),
                "reports": reports, "artifacts": artifacts, "excluded": excluded or {}}
    manifest_bytes = json.dumps(manifest).encode()
    blobs[prefix + "manifest.json"] = manifest_bytes
    blobs["financial-intelligence/latest.json"] = json.dumps({"batch_id": batch, "manifest_path": prefix + "manifest.json",
                                                               "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}).encode()
    return FakeContainer(blobs)


class PartialBatchTests(unittest.TestCase):
    def test_partial_batch_loads_present_companies_and_reports_exclusions(self):
        present = list(data.TICKERS[:-1])
        missing = data.TICKERS[-1]
        result = data.load_azure(build(present, {missing: {"stage": "market-prices", "reason": "HTTP 404"}}))
        self.assertEqual(sorted(result["companies"]), sorted(present))
        self.assertIn(missing, result["excluded"])

    def test_full_batch_still_loads(self):
        result = data.load_azure(build(list(data.TICKERS)))
        self.assertEqual(sorted(result["companies"]), sorted(data.TICKERS))
        self.assertEqual(result["excluded"], {})

    def test_unknown_ticker_rejected(self):
        with self.assertRaises(ValueError):
            data.load_azure(build(list(data.TICKERS[:2]) + ["ZZZZ"]))

    def test_tampered_manifest_rejected(self):
        container = build(list(data.TICKERS))
        latest = json.loads(container.blobs["financial-intelligence/latest.json"])
        latest["manifest_sha256"] = "0" * 64
        container.blobs["financial-intelligence/latest.json"] = json.dumps(latest).encode()
        with self.assertRaises(ValueError):
            data.load_azure(container)


if __name__ == "__main__":
    unittest.main()
