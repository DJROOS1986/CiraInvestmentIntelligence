"""Fallback labels and derived liabilities, using real SEC values observed on 11 Nov 2026."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "cira_financial_processor", Path(__file__).resolve().parents[1] / "portfolio-engine" / "financial_processor.py")
fp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fp)

END, START = "2025-12-31", "2025-01-01"


def duration(val):
    return {"USD": [{"val": val, "start": START, "end": END, "form": "10-K", "fp": "FY", "filed": "2026-02-01", "accn": "a"}]}


def instant(val):
    return {"USD": [{"val": val, "end": END, "form": "10-K", "fp": "FY", "filed": "2026-02-01", "accn": "a"}]}


def run(facts):
    doc = {"cik": 1, "entityName": "Test", "facts": {"us-gaap": {k: {"units": v} for k, v in facts.items()}}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "facts.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return fp.extract_annual_metrics(path)


BASE = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": duration(5_296_759_000),
    "NetIncomeLoss": duration(1_108_888_000),
    "Assets": instant(10_153_148_000),
    "NetCashProvidedByUsedInOperatingActivities": duration(1_728_781_000),
    "PaymentsToAcquirePropertyPlantAndEquipment": duration(141_871_000),
}
CDNS_BALANCE = {  # Cadence 10-K FY2025: no total "Liabilities" line
    "LiabilitiesCurrent": instant(1_635_291_000),
    "LiabilitiesNoncurrent": instant(3_043_676_000),
    "LiabilitiesAndStockholdersEquity": instant(10_153_148_000),
    "StockholdersEquity": instant(5_474_181_000),
}


class FallbackTests(unittest.TestCase):
    def test_derived_liabilities_when_both_routes_agree(self):
        result = run({**BASE, **CDNS_BALANCE})
        self.assertEqual(result["metrics_usd"]["total_liabilities"], 4_678_967_000)
        self.assertTrue(result["provenance"]["total_liabilities"]["tag"].startswith("derived:"))

    def test_no_derivation_when_routes_disagree(self):
        result = run({**BASE, **CDNS_BALANCE, "StockholdersEquity": instant(5_000_000_000)})
        self.assertIsNone(result["metrics_usd"]["total_liabilities"])

    def test_reported_total_liabilities_wins_over_derivation(self):
        result = run({**BASE, **CDNS_BALANCE, "Liabilities": instant(4_000_000_000)})
        self.assertEqual(result["metrics_usd"]["total_liabilities"], 4_000_000_000)
        self.assertEqual(result["provenance"]["total_liabilities"]["tag"], "Liabilities")

    def test_capex_fallback_productive_assets(self):  # e.g. NVDA FY2026: 6,042,000,000
        facts = {k: v for k, v in BASE.items() if k != "PaymentsToAcquirePropertyPlantAndEquipment"}
        facts["PaymentsToAcquireProductiveAssets"] = duration(6_042_000_000)
        result = run(facts)
        self.assertEqual(result["metrics_usd"]["capital_expenditure"], 6_042_000_000)
        self.assertEqual(result["provenance"]["capital_expenditure"]["tag"], "PaymentsToAcquireProductiveAssets")
        self.assertEqual(result["metrics_usd"]["free_cash_flow"], 1_728_781_000 - 6_042_000_000)

    def test_net_income_fallback_profit_loss(self):  # e.g. AVGO FY2025: 23,126,000,000
        facts = {k: v for k, v in BASE.items() if k != "NetIncomeLoss"}
        facts["ProfitLoss"] = duration(23_126_000_000)
        result = run(facts)
        self.assertEqual(result["metrics_usd"]["net_income"], 23_126_000_000)
        self.assertEqual(result["provenance"]["net_income"]["tag"], "ProfitLoss")

    def test_primary_label_preferred_over_fallback(self):
        facts = {**BASE, "ProfitLoss": duration(999)}
        self.assertEqual(run(facts)["provenance"]["net_income"]["tag"], "NetIncomeLoss")

    def test_missing_capex_gives_null_fcf(self):
        facts = {k: v for k, v in BASE.items() if k != "PaymentsToAcquirePropertyPlantAndEquipment"}
        result = run(facts)
        self.assertIsNone(result["metrics_usd"]["capital_expenditure"])
        self.assertIsNone(result["metrics_usd"]["free_cash_flow"])


if __name__ == "__main__":
    unittest.main()
