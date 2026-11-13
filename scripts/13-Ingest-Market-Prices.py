"""Fetch historical daily market prices for CIRA local development."""

import json
import pathlib
import sys
from urllib.parse import quote

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))

from market_data import MAX_CHART_RESPONSE_BYTES, normalize_yahoo_chart


SYMBOLS = list(__import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["active_tickers"]())
OUTPUT = ROOT / "reports" / "market-data"
PRICE_REQUEST_PAUSE_SECONDS = 0.5  # gentle pacing for the Yahoo chart endpoint


def fetch_prices(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + quote(symbol, safe="")
    )

    response = requests.get(
        url,
        params={
            "range": "1y",
            "interval": "1d",
        },
        headers={
            "User-Agent": "Mozilla/5.0 CIRA-Development/1.0",
            "Accept": "application/json",
        },
        timeout=20,
        stream=True,
    )

    try:
        response.raise_for_status()
        # iter_content decodes HTTP compression. Never buffer an unbounded body
        # via response.content/json(), nor hold a chunk list plus a joined copy.
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if len(body) + len(chunk) > MAX_CHART_RESPONSE_BYTES:
                raise ValueError('Market response byte limit exceeded')
            body.extend(chunk)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            # Preserve response.json()'s request-error retry behavior.
            raise requests.exceptions.JSONDecodeError(exc.msg, exc.doc, exc.pos) from exc
        except (UnicodeDecodeError, RecursionError) as exc:
            raise ValueError('Invalid market JSON structure or encoding') from exc
        return normalize_yahoo_chart(symbol, payload)
    finally:
        response.close()


RETRY_WAITS_SECONDS = (3, 8)


def fetch_with_retry(symbol):
    """Yahoo occasionally refuses a valid symbol (HTTP 400/429/5xx); retry before excluding it."""
    last_error = None
    for attempt, wait in enumerate((0,) + RETRY_WAITS_SECONDS, start=1):
        if wait:
            print(f"Retrying {symbol} in {wait}s (attempt {attempt}): {last_error}")
            __import__("time").sleep(wait)
        try:
            return fetch_prices(symbol)
        except requests.RequestException as exc:
            last_error = exc
    raise last_error


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failures = []

    for symbol in SYMBOLS:
        __import__("time").sleep(PRICE_REQUEST_PAUSE_SECONDS)
        print(f"\nFetching {symbol}...")

        try:
            document = fetch_with_retry(symbol)
            prices = document['records']

            if not prices:
                raise RuntimeError("No valid price records")

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
            __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["exclude"](symbol, "market-prices", exc)
            print(f"FAILED: {symbol}: {exc}")

    if failures:
        print("\nFailed symbols:", ", ".join(failures))
    if failures and len(failures) == len(SYMBOLS):
        return 1

    print("\nCIRA MARKET INGESTION SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
