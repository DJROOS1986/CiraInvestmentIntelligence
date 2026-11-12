"""Stage 2, step A: is EODHD's fundamentals data accurate? (free, no registration, read-only)

Uses EODHD's public "demo" key, which works for a few US test tickers only (AAPL.US, MSFT.US).
For each, it compares EODHD's latest yearly figures with CIRA's own SEC extraction
(portfolio-engine/financial_processor.py) for the SAME fiscal year end, and prints the differences.
If a field name is not found, it lists the field names EODHD actually returned, so nothing is guessed silently.
Nothing is written.

Usage (repo root, .venv active):  python scripts/62-Compare-EODHD-Demo.py
"""
import importlib.util
import json
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEMO = {"AAPL": ("AAPL.US", "0000320193"), "MSFT": ("MSFT.US", "0000789019")}
# CIRA metric -> (EODHD statement, candidate field names in order). Names to be confirmed by this run.
FIELDS = {
    "revenue": ("Income_Statement", ["totalRevenue"]),
    "net_income": ("Income_Statement", ["netIncome", "netIncomeApplicableToCommonShares"]),
    "total_assets": ("Balance_Sheet", ["totalAssets"]),
    "total_liabilities": ("Balance_Sheet", ["totalLiab", "totalLiabilities"]),
    "operating_cash_flow": ("Cash_Flow", ["totalCashFromOperatingActivities"]),
    "capital_expenditure": ("Cash_Flow", ["capitalExpenditures"]),
}


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main():
    spec = importlib.util.spec_from_file_location("cira_fp", ROOT / "portfolio-engine" / "financial_processor.py")
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})

    for ticker, (code, cik) in DEMO.items():
        time.sleep(0.5)
        raw = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=60).content
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            path.write_bytes(raw)
            cira = fp.extract_annual_metrics(path)
        period = cira["period_end"]

        eod = requests.get(f"https://eodhd.com/api/v1.1/fundamentals/{code}", params={"api_token": "demo", "fmt": "json"}, timeout=60)
        print(f"\n=== {ticker}: CIRA (SEC) fiscal year end {period} | EODHD HTTP {eod.status_code}")
        if eod.status_code != 200:
            print("   EODHD did not return data:", eod.text[:200])
            continue
        data = eod.json()
        financials = data.get("Financials") or {}
        print(f"   EODHD statements: {', '.join(financials) or 'none'}")
        for metric, (statement, names) in FIELDS.items():
            yearly = ((financials.get(statement) or {}).get("yearly")) or {}
            row = yearly.get(period)
            if row is None:  # 52/53-week fiscal years: EODHD dates them to the month-end
                from datetime import date
                near = [d for d in yearly if abs((date.fromisoformat(d) - date.fromisoformat(period)).days) <= 10]
                if len(near) == 1:
                    row = yearly[near[0]]
                    if metric == "revenue":
                        print(f"   (EODHD dates this fiscal year {near[0]}; matched to SEC {period} within 10 days)")
            if row is None:
                print(f"   {metric:<20} EODHD has no yearly row dated {period}. Dates available: {', '.join(sorted(yearly)[-4:])}")
                continue
            name = next((n for n in names if n in row), None)
            ours = cira["metrics_usd"].get(metric)
            if name is None:
                hints = [k for k in row if any(w in k.lower() for w in metric.split("_")[:1] + ["revenue", "income", "liab", "cash", "capital"])]
                print(f"   {metric:<20} field not found; EODHD fields that look related: {', '.join(hints[:10])}")
                continue
            theirs = number(row.get(name))
            if ours is None or theirs is None:
                print(f"   {metric:<20} CIRA {ours}  EODHD {theirs} ({name})")
                continue
            diff = abs(abs(theirs) - abs(ours)) / abs(ours) * 100 if ours else 0.0
            sign = " (EODHD reports it negative)" if theirs < 0 < ours else ""
            verdict = "MATCH" if diff < 0.5 else ("CLOSE" if diff < 2 else "DIFFERENT")
            print(f"   {metric:<20} CIRA {ours / 1e6:>12,.1f} m  EODHD {theirs / 1e6:>12,.1f} m  ({name}) {diff:5.2f}%  {verdict}{sign}")


if __name__ == "__main__":
    main()
