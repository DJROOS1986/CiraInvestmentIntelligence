import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "portfolio-engine" / "company_intelligence.py"

spec = importlib.util.spec_from_file_location(
    "company_intelligence", PATH
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestCompanyIntelligence(unittest.TestCase):

    def setUp(self):
        self.financial = {
            "ticker": "MSFT",
            "company": "Microsoft",
            "period_end": "2026-06-30",
            "currency": "USD",
            "metrics_usd": {
                "revenue": 100,
                "net_income": 20,
                "free_cash_flow": 15,
            },
            "provenance": {},
        }
        self.prices = {
            "symbol": "MSFT",
            "currency": "USD",
            "price_type": "unadjusted",
            "records": [
                {"date": "2026-11-05", "close": 100},
                {"date": "2026-11-06", "close": 101},
            ],
        }
        self.market = {
            "symbol": "MSFT",
            "provider": "Yahoo Finance chart endpoint",
            "currency": "USD",
            "price_type": "unadjusted",
            "observations": 2,
            "last_date": "2026-11-06",
            "latest_close": 101,
        }
        self.bcg = {
            "ticker": "MSFT",
            "research_available": True,
            "status": "Research only - verification required",
            "research_score": 74,
            "verified_bcg_class": None,
        }

    def build(self):
        return module.build_company_intelligence(
            "MSFT",
            self.financial,
            self.prices,
            self.market,
            self.bcg,
        )

    def test_success(self):
        self.assertEqual(self.build()["ticker"], "MSFT")

    def test_financial_metrics(self):
        self.assertEqual(
            self.build()["financial"]["metrics_usd"]["revenue"], 100
        )

    def test_market_indicators(self):
        self.assertEqual(
            self.build()["market"]["indicators"]["latest_close"], 101
        )

    def test_bcg_uncertainty(self):
        self.assertFalse(
            self.build()["data_quality"]["independently_verified_bcg"]
        )

    def test_no_recommendation(self):
        self.assertIsNone(
            self.build()["data_quality"]["investment_recommendation"]
        )

    def test_ticker_mismatch(self):
        self.prices["symbol"] = "AAPL"
        with self.assertRaises(ValueError):
            self.build()

    def test_observation_mismatch(self):
        self.market["observations"] = 10
        with self.assertRaises(ValueError):
            self.build()


if __name__ == "__main__":
    unittest.main()