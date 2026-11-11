"""Discover which us-gaap labels each pilot company uses for CIRA's metrics (read-only).

For each company:
  - reference period = latest 10-K fiscal-year end of revenue (CIRA's own rule)
  - for each metric: is there a value for EXACTLY that period under CIRA's current labels?
  - if not: list alternative labels (keyword search in the company's own facts) that DO have a
    10-K value for that period, with the value, so labels can be chosen on evidence.

Usage (repo root, .venv active):  python scripts/46-Discover-Metric-Labels.py
"""
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
COMPANIES = {
    "KLAC": "0000319201", "ISRG": "0001035267", "LRCX": "0000707549", "AVGO": "0001730168",
    "NVDA": "0001045810", "VEEV": "0001393052", "NOW": "0001373715", "SNPS": "0000883241",
    "CDNS": "0000813672", "LLY": "0000059478",
}
CURRENT = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
# Keyword patterns used only to SEARCH for alternatives (nothing is assumed to exist).
SEARCH = {
    "net_income": r"^(NetIncomeLoss|ProfitLoss)",
    "total_assets": r"^Assets$",
    "total_liabilities": r"^Liabilities|^StockholdersEquity|^LiabilitiesAndStockholdersEquity$",
    "operating_cash_flow": r"^NetCashProvidedByUsedInOperatingActivities",
    "capital_expenditure": r"^PaymentsToAcquire.*(PropertyPlant|ProductiveAssets|CapitalExpenditure)",
}
INSTANT = {"total_assets", "total_liabilities"}

cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
session = requests.Session()
session.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})


def fy_values(facts, label, period_end):
    """10-K full-year (or instant) USD values of a label ending at period_end."""
    out = []
    for unit, items in facts.get(label, {}).get("units", {}).items():
        if unit != "USD":
            continue
        for item in items:
            if item.get("form") == "10-K" and item.get("end") == period_end and item.get("fp") == "FY":
                out.append(item.get("val"))
    return out


for ticker, cik in COMPANIES.items():
    time.sleep(0.25)
    facts = session.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=30).json()
    facts = facts.get("facts", {}).get("us-gaap", {})
    ends = [i["end"] for lbl in CURRENT["revenue"] for u in facts.get(lbl, {}).get("units", {}).values()
            for i in u if i.get("form") == "10-K" and i.get("fp") == "FY" and i.get("end")]
    if not ends:
        print(f"\n{ticker}: no 10-K revenue found")
        continue
    period = max(ends)
    print(f"\n=== {ticker}  reference period (revenue FY end): {period}")
    for metric, labels in CURRENT.items():
        hit = next(((lbl, v[0]) for lbl in labels if (v := fy_values(facts, lbl, period))), None)
        if hit:
            print(f"  OK       {metric:<20} {hit[0]} = {hit[1]:,}")
            continue
        print(f"  MISSING  {metric:<20} (no value for {period} under CIRA's labels)")
        pattern = re.compile(SEARCH.get(metric, "^$"))
        alternatives = [(lbl, v[0]) for lbl in sorted(facts) if pattern.search(lbl) and (v := fy_values(facts, lbl, period))]
        for lbl, val in alternatives[:8]:
            print(f"           candidate: {lbl} = {val:,}")
        if not alternatives:
            print("           no candidate label with a value for this period")
