"""CIRA historical market analytics."""

import math
import statistics
from datetime import date


def analyze_prices(document):
    records = document["records"]

    if not isinstance(records, list) or len(records) < 2:
        raise ValueError("At least two daily records are required")

    records = sorted(records, key=lambda row: row["date"])

    dates = [date.fromisoformat(row["date"]) for row in records]

    if len(set(dates)) != len(dates):
        raise ValueError("Duplicate trading dates")

    closes = [float(row["close"]) for row in records]

    if any(not math.isfinite(x) or x <= 0 for x in closes):
        raise ValueError("Closing prices must be finite and positive")

    returns = [
        (closes[i] / closes[i - 1]) - 1
        for i in range(1, len(closes))
    ]

    def sma(window):
        if len(closes) < window:
            return None
        return round(statistics.mean(closes[-window:]), 4)

    volatility = None

    if len(returns) >= 2:
        volatility = (
            statistics.stdev(returns) * math.sqrt(252) * 100
        )

    return {
        "symbol": document["symbol"],
        "provider": document.get("provider"),
        "currency": document.get("currency"),
        "price_type": document.get("price_type"),
        "first_date": records[0]["date"],
        "last_date": records[-1]["date"],
        "observations": len(closes),
        "latest_close": closes[-1],
        "daily_return_pct": round(returns[-1] * 100, 4),
        "period_price_change_pct": round(
            ((closes[-1] / closes[0]) - 1) * 100, 4
        ),
        "sma_5": sma(5),
        "sma_20": sma(20),
        "annualized_volatility_pct": (
            round(volatility, 4)
            if volatility is not None
            else None
        ),
        "annualization_trading_days": 252,
        "return_basis": "unadjusted_close",
        "note": (
            "Historical descriptive analytics only. "
            "Unadjusted prices exclude dividend adjustments "
            "and may be affected by corporate actions."
        ),
    }