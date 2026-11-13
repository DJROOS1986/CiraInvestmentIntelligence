"""Classify the SEC 20-F filers in config/identifiers.csv (read-only, free SEC data).

For each company: which taxonomy its SEC data uses (us-gaap and/or ifrs-full), in which currency it reports
annual revenue, the latest full-year revenue (20-F or 10-K, 330-380 days) and how many years exist.
The verdict says how much work CIRA needs:
  READY-USD-GAAP   us-gaap revenue in USD    -> CIRA only needs to accept the 20-F form
  GAAP-OTHER-CCY   us-gaap, non-USD currency -> needs currency handling
  IFRS             ifrs-full only            -> needs an IFRS label map (and often currency handling)
Nothing is written.  Usage (repo root, .venv active):  python scripts/64-Classify-20F-Filers.py
"""
import csv
import json
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REVENUE = {
    "us-gaap": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "ifrs-full": ["Revenue", "RevenueFromContractsWithCustomers"],
}
FORMS = ("20-F", "20-F/A", "10-K", "10-K/A", "40-F")


def latest_revenue(facts, taxonomy):
    best = None
    for label in REVENUE[taxonomy]:
        for unit, items in facts.get(taxonomy, {}).get(label, {}).get("units", {}).items():
            years = set()
            for i in items:
                try:
                    days = (date.fromisoformat(i["end"]) - date.fromisoformat(i["start"])).days
                except (KeyError, TypeError, ValueError):
                    continue
                if i.get("form") in FORMS and 330 <= days <= 380 and i.get("val") is not None:
                    years.add(i["end"])
                    if best is None or i["end"] > best["end"]:
                        best = {"end": i["end"], "val": i["val"], "unit": unit, "label": label, "form": i["form"]}
            if best and best["label"] == label and best["unit"] == unit:
                best["years"] = len(years)
    return best


def main():
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})
    rows = [r for r in csv.DictReader((ROOT / "config" / "identifiers.csv").open(encoding="utf-8")) if r["category"] == "SEC_20F"]
    print(f"{len(rows)} SEC 20-F filers\n")
    print(f"{'Ticker':<6} {'Verdict':<15} {'Taxonomies':<20} {'Revenue (latest FY)':<34} {'Label / form'}")
    for r in rows:
        time.sleep(0.25)
        try:
            facts = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{r['sec_cik']}.json", timeout=60).json().get("facts", {})
        except (requests.RequestException, ValueError) as exc:
            print(f"{r['primary_ticker']:<6} ERROR {type(exc).__name__}")
            continue
        taxonomies = ",".join(t for t in ("us-gaap", "ifrs-full") if t in facts) or "-"
        gaap, ifrs = latest_revenue(facts, "us-gaap"), latest_revenue(facts, "ifrs-full")
        pick = max([x for x in (gaap, ifrs) if x], key=lambda x: x["end"], default=None)
        if pick is None:
            verdict, revenue, label = "NO REVENUE", "-", "-"
        else:
            verdict = ("READY-USD-GAAP" if pick is gaap and pick["unit"] == "USD" else
                       "GAAP-OTHER-CCY" if pick is gaap else "IFRS")
            revenue = f"{pick['end']}  {pick['val'] / 1e6:>14,.1f} m {pick['unit']}"
            label = f"{pick['label']} / {pick['form']} ({pick.get('years', '?')} yrs)"
        print(f"{r['primary_ticker']:<6} {verdict:<15} {taxonomies:<20} {revenue:<34} {label}")


if __name__ == "__main__":
    main()
