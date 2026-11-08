import argparse
import json
from datetime import datetime, date, timezone
from pathlib import Path


def parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing or invalid UTC timestamp")

    result = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if result.tzinfo is None:
        raise ValueError("Timestamp must include timezone")

    return result.astimezone(timezone.utc)


def load(path):
    if not path.is_file():
        raise FileNotFoundError(path)

    return json.loads(path.read_text(encoding="utf-8"))


def validate(root, now):
    errors = []
    warnings = []
    market_dates = []
    intelligence_times = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    for ticker in ("AAPL", "MSFT"):
        financial = load(
            root / "reports/financial"
            / f"{ticker}-financial-report.json"
        )

        market = load(
            root / "reports/market-data"
            / f"{ticker}-daily-prices.json"
        )

        analysis = load(
            root / "reports/market-analysis"
            / f"{ticker}-market-analysis.json"
        )

        intelligence = load(
            root / "reports/company-intelligence"
            / f"{ticker}-company-intelligence.json"
        )

        check(financial.get("ticker") == ticker,
              f"{ticker}: financial ticker mismatch")
        check(market.get("symbol") == ticker,
              f"{ticker}: market symbol mismatch")
        check(analysis.get("symbol") == ticker,
              f"{ticker}: analysis symbol mismatch")
        check(intelligence.get("ticker") == ticker,
              f"{ticker}: intelligence ticker mismatch")

        financial_time = parse_timestamp(
            financial.get("generated_at_utc")
        )

        market_time = parse_timestamp(
            market.get("retrieved_at_utc")
        )

        intelligence_time = parse_timestamp(
            intelligence.get("generated_at_utc")
        )

        market_date = date.fromisoformat(
            analysis["last_date"]
        )

        financial_period = date.fromisoformat(
            financial["period_end"]
        )

        records = market.get("records", [])

        check(bool(records), f"{ticker}: no market records")

        if records:
            check(
                records[-1].get("date") == analysis["last_date"],
                f"{ticker}: market/analysis date mismatch"
            )

        check(
            intelligence.get("market", {}).get("last_date")
            == analysis["last_date"],
            f"{ticker}: intelligence market date mismatch"
        )

        check(
            intelligence.get("financial", {}).get("period_end")
            == financial["period_end"],
            f"{ticker}: intelligence financial period mismatch"
        )

        check(
            intelligence.get("financial", {}).get(
                "report_generated_at_utc"
            ) == financial.get("generated_at_utc"),
            f"{ticker}: financial source timestamp mismatch"
        )

        check(
            intelligence_time >= financial_time,
            f"{ticker}: intelligence predates financial report"
        )

        check(
            intelligence_time >= market_time,
            f"{ticker}: intelligence predates market retrieval"
        )

        market_age = (now.date() - market_date).days
        financial_age = (
            now - financial_time
        ).total_seconds() / 86400

        period_age = (
            now.date() - financial_period
        ).days

        check(
            0 <= market_age <= 4,
            f"{ticker}: market observation age {market_age} days"
        )

        check(
            0 <= financial_age <= 7,
            f"{ticker}: financial report age "
            f"{financial_age:.1f} days"
        )

        check(
            financial_time <= now
            and market_time <= now
            and intelligence_time <= now,
            f"{ticker}: future source or report timestamp"
        )

        if period_age > 180:
            warnings.append(
                f"{ticker}: financial period is "
                f"{period_age} days old"
            )

        if market.get("price_type") == "unadjusted":
            warnings.append(
                f"{ticker}: market prices are unadjusted"
            )

        if "prototype" in market.get(
            "provider", ""
        ).lower():
            warnings.append(
                f"{ticker}: prototype market provider"
            )

        market_dates.append(market_date)
        intelligence_times.append(intelligence_time)

        print(
            f"{ticker}: market={market_date} "
            f"market_age={market_age}d "
            f"financial_period={financial_period} "
            f"financial_report_age={financial_age:.1f}d"
        )

    check(
        len(set(market_dates)) == 1,
        "AAPL/MSFT market observation dates differ"
    )

    check(
        len(set(intelligence_times)) == 1,
        "AAPL/MSFT intelligence generation times differ"
    )

    return errors, warnings


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source-root",
        required=True
    )

    parser.add_argument(
        "--as-of",
        help="Optional UTC ISO timestamp for deterministic testing"
    )

    args = parser.parse_args()

    now = (
        parse_timestamp(args.as_of)
        if args.as_of
        else datetime.now(timezone.utc)
    )

    print("=== CIRA DATA FRESHNESS VALIDATOR ===")
    print("Validation time:", now.isoformat())

    try:
        errors, warnings = validate(
            Path(args.source_root), now
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        FileNotFoundError,
        json.JSONDecodeError,
    ) as exc:
        print("VALIDATION FAILED:", exc)
        return 1

    for warning in warnings:
        print("WARNING:", warning)

    for error in errors:
        print("ERROR:", error)

    if errors:
        print("FRESHNESS VALIDATION FAILED")
        return 1

    print("FRESHNESS VALIDATION PASSED")
    print("Warnings:", len(warnings))
    print("No files modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
