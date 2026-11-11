"""Verify pilot-universe candidates at the source (read-only, SEC fair-access friendly).

For each candidate ticker it checks, using SEC's own data:
  1. CIK and registrant name   (www.sec.gov/files/company_tickers.json)
  2. latest annual report form (data.sec.gov/submissions)  -> must be 10-K for stage 1
  3. metric coverage under the us-gaap labels CIRA reads   (data.sec.gov companyfacts)
  4. exact company-name match in ingestion/bcg-research/bcg_research.json

Uses the SEC user agent from ingestion/config.json (local, untracked). ~3 requests per company,
paced at <= 5 requests/second. Writes nothing.

Usage (repo root, .venv active):  python scripts/45-Verify-Universe-Candidates.py
"""
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]

# ticker -> exact company name in the BCG workbook (Matrix sheet / bcg_research.json)
CANDIDATES = {
    "KLAC": "KLA Corporation",
    "ISRG": "Intuitive Surgical",
    "LRCX": "Lam Research",
    "AVGO": "Broadcom (custom AI ASIC design)",
    "NVDA": "Nvidia",
    "VEEV": "Veeva Systems",
    "NOW": "ServiceNow",
    "SNPS": "Synopsys",
    "CDNS": "Cadence Design Systems",
    "LLY": "Eli Lilly",
}

# Mirrors portfolio-engine/financial_processor.py (first label found wins there).
METRICS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}

cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
session = requests.Session()
session.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})


def get_json(url):
    time.sleep(0.25)
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def latest_fy_end(facts, labels):
    best = None
    for label in labels:
        for unit_values in facts.get(label, {}).get("units", {}).values():
            for item in unit_values:
                if item.get("form") == "10-K" and item.get("fp") == "FY":
                    end = item.get("end")
                    if end and (best is None or end > best[1]):
                        best = (label, end)
    return best


bcg = json.loads((ROOT / "ingestion" / "bcg-research" / "bcg_research.json").read_text(encoding="utf-8"))
bcg_names = {c.get("company") for c in bcg["companies"]}

tickers = get_json("https://www.sec.gov/files/company_tickers.json")
by_ticker = {row["ticker"].upper(): row for row in tickers.values()}

rows = []
for ticker, bcg_name in CANDIDATES.items():
    row = {"ticker": ticker, "bcg_match": bcg_name in bcg_names}
    sec = by_ticker.get(ticker)
    if not sec:
        row.update(verdict="NOT IN SEC TICKER LIST")
        rows.append(row)
        continue
    cik = str(sec["cik_str"]).zfill(10)
    row.update(cik=cik, sec_name=sec["title"])
    subs = get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = subs.get("filings", {}).get("recent", {})
    annual = [(f, d) for f, d in zip(recent.get("form", []), recent.get("filingDate", [])) if f in ("10-K", "20-F", "40-F")]
    row["annual_form"] = f"{annual[0][0]} {annual[0][1]}" if annual else "none"
    facts = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").get("facts", {}).get("us-gaap", {})
    coverage = {}
    for metric, labels in METRICS.items():
        found = latest_fy_end(facts, labels)
        coverage[metric] = found[1] if found else "MISSING"
    row["coverage"] = coverage
    missing = [m for m, v in coverage.items() if v == "MISSING"]
    ok_form = annual and annual[0][0] == "10-K"
    row["verdict"] = "READY" if ok_form and not missing and row["bcg_match"] else (
        "CHECK: " + ", ".join(filter(None, [
            None if ok_form else "not a 10-K filer",
            ("missing " + "/".join(missing)) if missing else None,
            None if row["bcg_match"] else "BCG name not found",
        ])))
    rows.append(row)

print(f"{'Ticker':<6} {'CIK':<11} {'Annual form':<16} {'BCG':<4} Verdict / SEC name")
for r in rows:
    print(f"{r['ticker']:<6} {r.get('cik', '-'):<11} {r.get('annual_form', '-'):<16} {'yes' if r['bcg_match'] else 'NO':<4} {r['verdict']}  |  {r.get('sec_name', '')}")
print("\nLatest fiscal-year end found per metric (10-K, FY):")
for r in rows:
    if "coverage" in r:
        print(f"  {r['ticker']:<6} " + "  ".join(f"{k}={v}" for k, v in r["coverage"].items()))
