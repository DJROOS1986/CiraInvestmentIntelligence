"""Find which us-gaap labels a company uses for annual revenue (read-only, SEC data only).

For each ticker (CIK from config/identifiers.csv): every us-gaap label whose name contains Revenue or
Sales (excluding cost/expense/tax/deferred items) that has full-year 10-K values (330-380 days, USD),
with the newest fiscal year end, its value, how many fiscal years exist, and whether CIRA already
reads that label. Nothing is written.

Usage (repo root, .venv active):  python scripts/60-Discover-Revenue-Labels.py --tickers CPRT CRWD
"""
import argparse
import csv
import importlib.util
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = re.compile(r"Revenue|Sales")
EXCLUDE = re.compile(r"Cost|Expense|IncomeTax|Deferred|Receivable|Unbilled|Remaining|Percentage|Gain|Loss|Proceeds|Allowance|Returns")


def full_year(item):
    try:
        days = (date.fromisoformat(item["end"]) - date.fromisoformat(item["start"])).days
    except (KeyError, TypeError, ValueError):
        return False
    return item.get("form") in ("10-K", "10-K/A") and 330 <= days <= 380 and item.get("val") is not None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", required=True)
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("cira_fp", ROOT / "portfolio-engine" / "financial_processor.py")
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    known = set(fp.TAGS["revenue"])
    ciks = {r["primary_ticker"]: r["sec_cik"] for r in csv.DictReader((ROOT / "config" / "identifiers.csv").open(encoding="utf-8")) if r["sec_cik"]}
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})

    print("CIRA reads revenue from, in order:", ", ".join(fp.TAGS["revenue"]))
    for ticker in [t.upper() for t in args.tickers]:
        cik = ciks.get(ticker)
        if not cik:
            print(f"\n{ticker}: no CIK in config/identifiers.csv")
            continue
        time.sleep(0.25)
        facts = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=60).json().get("facts", {}).get("us-gaap", {})
        rows = []
        for label, body in facts.items():
            if not INCLUDE.search(label) or EXCLUDE.search(label):
                continue
            items = [i for i in body.get("units", {}).get("USD", []) if full_year(i)]
            if not items:
                continue
            newest = max(items, key=lambda i: (i["end"], i.get("filed", "")))
            rows.append((newest["end"], label, newest["val"], len({i["end"] for i in items}), newest.get("filed", "")))
        print(f"\n=== {ticker} (CIK {cik}): revenue-like labels with full-year 10-K values, newest first")
        if not rows:
            print("   none found")
        for end, label, val, years, filed in sorted(rows, reverse=True)[:12]:
            flag = "CIRA reads" if label in known else "          "
            print(f"   {flag}  FY end {end}  {val / 1e6:>12,.1f} m  ({years:>2} yrs, filed {filed})  {label}")


if __name__ == "__main__":
    main()
