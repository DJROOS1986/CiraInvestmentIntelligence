"""Build a hand-check checklist: CIRA's numbers vs the companies' own 10-K reports (read-only).

For each company it runs CIRA's own extraction (portfolio-engine/financial_processor.py) on the SEC data,
then writes research/hand-check-<date>.md with, per metric: CIRA's value, the SEC label it came from,
the filing (accession) it came from, a link to that filing, and where to find the line in the 10-K.
Diagnostics: for any missing metric, alternative labels that DO have a value for the same period.
You open the 10-K, compare, and fill in the "10-K value" and "Match" columns.

Usage (repo root, .venv active):
  python scripts/56-Hand-Check-Checklist.py                       # NVDA CDNS AVGO LLY AMZN
  python scripts/56-Hand-Check-Checklist.py --tickers KLAC MSFT
"""
import argparse
import importlib.util
import json
import re
import tempfile
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WHERE = {
    "revenue": "Income statement - total revenue / net sales",
    "net_income": "Income statement - net income",
    "total_assets": "Balance sheet - total assets",
    "total_liabilities": "Balance sheet - total liabilities (or current + non-current)",
    "operating_cash_flow": "Cash flow statement - net cash provided by operating activities",
    "capital_expenditure": "Cash flow statement (investing) - purchases of property and equipment",
    "free_cash_flow": "Not in the 10-K: operating cash flow minus capital expenditure (check both inputs)",
}
SEARCH = {  # alternative labels to show when a metric is missing (diagnostics only)
    "net_income": r"^(NetIncomeLoss|ProfitLoss)",
    "total_liabilities": r"^Liabilities|^StockholdersEquity|^LiabilitiesAndStockholdersEquity$",
    "operating_cash_flow": r"^NetCashProvidedByUsedInOperatingActivities",
    "capital_expenditure": r"^PaymentsToAcquire.*(PropertyPlant|ProductiveAssets|CapitalExpenditure)",
}
NOTES = {
    "LLY": "Open question: CIRA leaves capex empty because Lilly reports only 'Other PP&E'. Compare the diagnostic value with the 10-K's purchases of property and equipment.",
    "AMZN": "Open question: total liabilities not found. Check how Amazon's balance sheet presents liabilities.",
    "CDNS": "Methodology check: total liabilities are DERIVED (current + non-current). Compare with the balance sheet.",
    "AVGO": "Methodology check: net income uses ProfitLoss (includes non-controlling interests). Compare with net income attributable to Broadcom.",
    "NVDA": "Methodology check: capex uses PaymentsToAcquireProductiveAssets. Compare with the cash flow statement.",
}


def money(value):
    return "-" if value is None else f"{value / 1e6:,.1f} m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="*", default=["NVDA", "CDNS", "AVGO", "LLY", "AMZN"])
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("cira_fp", ROOT / "portfolio-engine" / "financial_processor.py")
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    universe = {c["ticker"]: c for c in json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]}
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})

    lines = [f"# CIRA hand-check - {date.today().isoformat()}", "",
             "Compare each CIRA value with the company's own 10-K (link per row). Fill in the last two columns.",
             "Values in USD millions. Small rounding differences (the 10-K often shows millions) are a match.", ""]
    for ticker in [t.upper() for t in args.tickers]:
        company = universe.get(ticker)
        if not company:
            print(f"{ticker}: not in config/universe.json - skipped")
            continue
        cik = company["cik"]
        time.sleep(0.25)
        raw = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=60).content
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            path.write_bytes(raw)
            result = fp.extract_annual_metrics(path)
        facts = json.loads(raw).get("facts", {}).get("us-gaap", {})
        metrics, provenance, period = result["metrics_usd"], result.get("provenance") or {}, result["period_end"]

        lines += [f"## {ticker} - {company.get('sec_name', '')} - fiscal year ending {period}", ""]
        if ticker in NOTES:
            lines += [f"> {NOTES[ticker]}", ""]
        lines += ["| Metric | CIRA value | SEC label | Filed | Filing | Where in the 10-K | 10-K value | Match? |",
                  "|---|---|---|---|---|---|---|---|"]
        for key in ("revenue", "net_income", "total_assets", "total_liabilities", "operating_cash_flow", "capital_expenditure", "free_cash_flow"):
            prov = provenance.get(key) or {}
            accession = prov.get("accession") or ""
            link = (f"[filing](https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/)"
                    if accession else "-")
            lines.append(f"| {key} | {money(metrics.get(key))} | {prov.get('tag', '-') if key != 'free_cash_flow' else 'calculated'} "
                         f"| {prov.get('filed', '-')} | {link} | {WHERE[key]} |  |  |")
        missing = [k for k in SEARCH if metrics.get(k) is None]
        for key in missing:
            pattern = re.compile(SEARCH[key])
            found = []
            for label in sorted(facts):
                if not pattern.search(label):
                    continue
                for item in facts[label].get("units", {}).get("USD", []):
                    if item.get("form") in ("10-K", "10-K/A") and item.get("end") == period:
                        found.append(f"`{label}` = {money(item.get('val'))}")
                        break
            lines += ["", f"Diagnostic for missing **{key}** (labels with a value for {period}): " + (", ".join(found[:8]) or "none")]
        lines.append("")
        print(f"{ticker}: FY {period}  revenue {money(metrics.get('revenue'))}  missing: {', '.join(missing) or '-'}")

    target = ROOT / "research" / f"hand-check-{date.today().isoformat()}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWritten: {target}")


if __name__ == "__main__":
    main()
