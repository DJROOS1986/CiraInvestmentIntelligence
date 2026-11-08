"""Tests for CIRA market-data normalization."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location(
    "market_data",
    ROOT / "ingestion" / "market_data.py",
)

market_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(market_data)


class MarketDataTests(unittest.TestCase):

    def test_valid_daily_prices(self):
        records = [{
            "date": "2026-11-06",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1000000,
        }]

        result = market_data.normalize_daily_prices(
            "aapl", records
        )

        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertEqual(result[0]["close"], 105.0)

    def test_invalid_price_range(self):
        records = [{
            "date": "2026-11-06",
            "open": 100,
            "high": 90,
            "low": 95,
            "close": 105,
            "volume": 1000,
        }]

        with self.assertRaises(ValueError):
            market_data.normalize_daily_prices(
                "AAPL", records
            )

    def test_duplicate_dates(self):
        record = {
            "date": "2026-11-06",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1000,
        }

        with self.assertRaises(ValueError):
            market_data.normalize_daily_prices(
                "AAPL", [record, record]
            )

    def test_invalid_volume(self):
        record = {
            "date": "2026-11-06",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": -1,
        }

        with self.assertRaises(ValueError):
            market_data.normalize_daily_prices(
                "AAPL", [record]
            )


if __name__ == "__main__":
    unittest.main()