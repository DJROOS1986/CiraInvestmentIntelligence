"""Fetch historical daily market prices for CIRA local development."""

import json
import pathlib
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))

from market_data import normalize_daily_prices


SYMBOLS = list(tuple(c["ticker"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]))
OUTPUT = ROOT / "reports" / "market-data"


def fetch_prices(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote(symbol, safe="")
    )

    response = requests.get(
        url,
        params={
            "range": "1mo",
            "interval": "1d",
        },
        headers={
            "User-Agent": "Mozilla/5.0 CIRA-Development/1.0",
            "Accept": "application/json",
        },
        timeout=20,
    )

    response.raise_for_status()
    payload = response.json()

    chart = payload.get("chart", {})

    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))

    results = chart.get("result") or []

    if not results:
        raise RuntimeError(f"No market data for {symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = result.get("indicators", {}).get("quote") or []

    if not quotes:
        raise RuntimeError(f"No OHLCV data for {symbol}")

    quote_data = quotes[0]
    records = []

    for index, timestamp in enumerate(timestamps):
        try:
            row = {
                "date": datetime.fromtimestamp(
                    timestamp, timezone.utc
                ).date().isoformat(),
                "open": quote_data["open"][index],
                "high": quote_data["high"][index],
                "low": quote_data["low"][index],
                "close": quote_data["close"][index],
                "volume": quote_data["volume"][index],
            }
        except (IndexError, KeyError, TypeError):
            continue

        if any(value is None for value in row.values()):
            continue

        if isinstance(row["volume"], bool):
            continue

        try:
            row["volume"] = int(row["volume"])
            validated = normalize_daily_prices(symbol, [row])
            records.extend(validated)
        except (ValueError, TypeError):
            continue

    return normalize_daily_prices(symbol, records)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failures = []

    for symbol in SYMBOLS:
        print(f"\nFetching {symbol}...")

        try:
            prices = fetch_prices(symbol)

            if not prices:
                raise RuntimeError("No valid price records")

            document = {
                "symbol": symbol,
                "provider": "Yahoo Finance chart endpoint (prototype)",
                "retrieved_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "currency": "USD",
                "price_type": "unadjusted",
                "records": prices,
            }

            path = OUTPUT / f"{symbol}-daily-prices.json"
            path.write_text(
                json.dumps(document, indent=2),
                encoding="utf-8",
            )

            print(f"Records: {len(prices)}")
            print(f"Latest date: {prices[-1]['date']}")
            print(f"Latest close: {prices[-1]['close']:.2f}")
            print(f"Saved: {path}")

        except (requests.RequestException, RuntimeError,
                ValueError, TypeError, KeyError) as exc:
            failures.append(symbol)
            print(f"FAILED: {symbol}: {exc}")

    if failures:
        print("\nFailed symbols:", ", ".join(failures))
        return 1

    print("\nCIRA MARKET INGESTION SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())