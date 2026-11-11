"""Generate local CIRA historical market analytics reports."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "market_analytics",
    ROOT / "portfolio-engine" / "market_analytics.py",
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    source = ROOT / "reports" / "market-data"
    output = ROOT / "reports" / "market-analysis"

    symbols = tuple(c["ticker"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"])
    results = {}

    # Analyze all inputs before writing any output.
    for symbol in symbols:
        path = source / f"{symbol}-daily-prices.json"

        document = json.loads(path.read_text(encoding="utf-8"))

        if document.get("symbol") != symbol:
            raise ValueError(f"Unexpected symbol in {path}")

        results[symbol] = module.analyze_prices(document)

    output.mkdir(parents=True, exist_ok=True)

    for symbol, report in results.items():
        destination = output / f"{symbol}-market-analysis.json"

        destination.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        print(f"\n=== {symbol} ===")
        print(f"Latest date: {report['last_date']}")
        print(f"Latest close: {report['latest_close']:.2f}")
        print(f"Daily return: {report['daily_return_pct']:.2f}%")
        print(f"5-day SMA: {report['sma_5']}")
        print(f"20-day SMA: {report['sma_20']}")
        print(
            "Annualized historical volatility: "
            f"{report['annualized_volatility_pct']}%"
        )
        print(f"Saved: {destination}")

    print("\nCIRA MARKET ANALYTICS SUCCESS")


if __name__ == "__main__":
    main()