"""Market-data validation and normalization for CIRA."""

from datetime import date
from typing import Any, Dict, List


def normalize_daily_prices(
    symbol: str,
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate and normalize daily OHLCV records."""

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("A non-empty stock symbol is required")

    if not isinstance(records, list):
        raise TypeError("Records must be a list")

    normalized = []
    seen_dates = set()

    for record in records:
        if not isinstance(record, dict):
            raise TypeError("Each record must be a dictionary")

        trading_date = date.fromisoformat(record["date"])

        if trading_date in seen_dates:
            raise ValueError("Duplicate trading date")

        seen_dates.add(trading_date)

        prices = {}

        for field in ("open", "high", "low", "close"):
            value = record[field]

            if isinstance(value, bool) or not isinstance(
                value, (int, float)
            ):
                raise ValueError(f"Invalid {field}")

            import math

            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid {field}")

            prices[field] = float(value)

        if (
            prices["high"] < prices["low"]
            or prices["high"] < prices["open"]
            or prices["high"] < prices["close"]
            or prices["low"] > prices["open"]
            or prices["low"] > prices["close"]
        ):
            raise ValueError("Inconsistent OHLC prices")

        volume = record["volume"]

        if (
            isinstance(volume, bool)
            or not isinstance(volume, int)
            or volume < 0
        ):
            raise ValueError("Invalid trading volume")

        normalized.append({
            "symbol": symbol.strip().upper(),
            "date": trading_date.isoformat(),
            **prices,
            "volume": volume,
        })

    return sorted(normalized, key=lambda row: row["date"])