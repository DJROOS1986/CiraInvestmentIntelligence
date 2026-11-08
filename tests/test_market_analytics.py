"""Unit tests for CIRA market analytics."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "market_analytics",
    ROOT / "portfolio-engine" / "market_analytics.py",
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample_document(closes):
    return {
        "symbol": "TEST",
        "currency": "USD",
        "records": [
            {
                "date": f"2026-10-{i + 1:02d}",
                "close": price,
            }
            for i, price in enumerate(closes)
        ],
    }


class MarketAnalyticsTests(unittest.TestCase):

    def test_daily_return(self):
        result = module.analyze_prices(
            sample_document([100, 110])
        )
        self.assertAlmostEqual(
            result["daily_return_pct"], 10.0
        )

    def test_five_day_average(self):
        result = module.analyze_prices(
            sample_document([10, 20, 30, 40, 50])
        )
        self.assertEqual(result["sma_5"], 30.0)

    def test_twenty_day_average(self):
        result = module.analyze_prices(
            sample_document(list(range(1, 21)))
        )
        self.assertEqual(result["sma_20"], 10.5)

    def test_insufficient_data_for_sma(self):
        result = module.analyze_prices(
            sample_document([100, 110])
        )
        self.assertIsNone(result["sma_5"])
        self.assertIsNone(result["sma_20"])

    def test_constant_prices_zero_volatility(self):
        result = module.analyze_prices(
            sample_document([100, 100, 100])
        )
        self.assertEqual(
            result["annualized_volatility_pct"], 0.0
        )

    def test_reject_invalid_prices(self):
        with self.assertRaises(ValueError):
            module.analyze_prices(
                sample_document([100, -10])
            )


if __name__ == "__main__":
    unittest.main()