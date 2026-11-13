"""Verify the next batch of US 10-K companies for the CIRA universe (read-only towards CIRA).

Selects the top-N companies by Star Score from config/identifiers.csv (category SEC_10K, not yet in
config/universe.json) and checks, per company:
  1. SEC: latest annual report is a 10-K and the CIK matches the identifier master
  2. Metrics under CIRA's CURRENT rules (portfolio-engine/financial_processor.py: fallback labels and
     the cross-checked liabilities derivation), for the latest revenue fiscal year
  3. Yahoo chart endpoint returns recent prices for the ticker (same endpoint as stage 13)
Writes research/universe-batch-<n>.json with proposed universe entries for companies that pass 1-3
(missing non-revenue metrics are allowed and listed). Nothing in config/ is changed.

Usage (repo root, .venv active):
  python scripts/52-Verify-Universe-Batch.py                 # top 15
  python scripts/52-Verify-Universe-Batch.py --count 20
  python scripts/52-Verify-Universe-Batch.py --tickers GOOGL MU AMAT
"""
import argparse
import csv
import importlib.util
import json
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MAX_FINANCIAL_AGE_DAYS = 550  # latest revenue fiscal year older than ~18 months = stale label (e.g. CPRT 2018)
METHODOLOGY_FALLBACKS = {"ProfitLoss", "PaymentsToAcquireProductiveAssets", "RevenueFromContractWithCustomerIncludingAssessedTax"}  # shown as data-quality notes
NOTE_ROWS = {  # identifier-master notes that belong in the dashboard's data-quality warnings
    "Amazon (AWS)": "AWS is a segment; figures are for all of Amazon",
    "Coherent / Lumentum": "BCG row combines Coherent and Lumentum; this entry is Coherent only",
}


def load_processor():
    spec = importlib.util.spec_from_file_location("cira_fp", ROOT / "portfolio-engine" / "financial_processor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detect_currency(doc, fp):
    """Reporting currency of annual revenue when it is not USD (latest full-year 10-K/20-F value)."""
    facts = doc.get("facts", {}).get("us-gaap", {})
    best = None
    for label in fp.TAGS["revenue"]:
        for unit, items in facts.get(label, {}).get("units", {}).items():
            for item in items:
                if item.get("form") in ("10-K", "10-K/A", "20-F", "20-F/A") and item.get("end") and item.get("start"):
                    if best is None or item["end"] > best[0]:
                        best = (item["end"], unit)
    return best[1] if best else None


def load_fx():
    spec = importlib.util.spec_from_file_location("cira_fx", ROOT / "portfolio-engine" / "fx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--tickers", nargs="*")
    args = parser.parse_args()

    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})
    universe = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))
    in_universe = {c["ticker"] for c in universe["companies"]}
    rows = list(csv.DictReader((ROOT / "config" / "identifiers.csv").open(encoding="utf-8")))

    def score(r):
        try:
            return float(r["star_score"])
        except (TypeError, ValueError):
            return -1.0

    pool = [r for r in rows if r["category"] in ("SEC_10K", "SEC_20F") and r["primary_ticker"] not in in_universe]
    if args.tickers:
        wanted = [t.upper() for t in args.tickers]
        chosen = [r for t in wanted for r in pool if r["primary_ticker"] == t]
        missing = set(wanted) - {r["primary_ticker"] for r in chosen}
        if missing:
            print("Not SEC_10K candidates (or already in universe):", ", ".join(sorted(missing)))
    else:
        chosen = sorted(pool, key=score, reverse=True)[:args.count]

    fp = load_processor()
    results, proposals = [], []
    for r in chosen:
        ticker, cik = r["primary_ticker"], r["sec_cik"]
        out = {"ticker": ticker, "bcg_name": r["bcg_name"], "star": r["star_score"], "form": "", "period": "",
               "missing": [], "fallbacks": [], "price": "", "verdict": ""}
        try:
            time.sleep(0.25)
            subs = sec.get(f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=30).json()
            recent = subs.get("filings", {}).get("recent", {})
            annual = [(f, d) for f, d in zip(recent.get("form", []), recent.get("filingDate", [])) if f in ("10-K", "20-F", "40-F")]
            out["form"] = f"{annual[0][0]} {annual[0][1]}" if annual else "none"
            if int(subs.get("cik", 0)) != int(cik):
                raise ValueError("SEC CIK mismatch")

            time.sleep(0.25)
            facts = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=60).content
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "facts.json"
                path.write_bytes(facts)
                currency = "USD"
                try:
                    result = fp.extract_annual_metrics(path)
                except ValueError:
                    currency = detect_currency(json.loads(facts), fp)
                    if currency in (None, "USD"):
                        raise
                    result = fp.extract_annual_metrics(path, currency=currency, fx=load_fx().EcbRates())
                    out["fallbacks"].append(f"converted from {currency}")
            out["period"] = result["period_end"]
            metrics, provenance = result["metrics_usd"], result.get("provenance") or {}
            out["missing"] = [k for k in ("net_income", "total_assets", "total_liabilities", "operating_cash_flow", "capital_expenditure")
                              if metrics.get(k) is None]
            for key, prov in provenance.items():
                tag = (prov or {}).get("tag", "")
                if tag.startswith("derived:") or tag in METHODOLOGY_FALLBACKS:
                    out["fallbacks"].append(f"{key}={tag}")

            time.sleep(0.5)
            chart = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", timeout=20,
                                 params={"range": "5d", "interval": "1d"},
                                 headers={"User-Agent": "Mozilla/5.0 CIRA-Development/1.0", "Accept": "application/json"}).json()
            result_chart = (chart.get("chart", {}).get("result") or [{}])[0]
            closes = [c for c in (result_chart.get("indicators", {}).get("quote") or [{}])[0].get("close", []) if c is not None]
            currency = result_chart.get("meta", {}).get("currency")
            out["price"] = f"{len(closes)} closes {currency}" if closes else "NO PRICES"

            ok_form = out["form"].startswith(("10-K", "20-F"))
            from datetime import date
            stale = (date.today() - date.fromisoformat(out["period"])).days > MAX_FINANCIAL_AGE_DAYS
            ok_price = bool(closes) and currency == "USD"
            out["verdict"] = ("NOT READY (stale financials)" if stale else
                              "READY" if ok_form and ok_price and not out["missing"] else
                              "READY (gaps)" if ok_form and ok_price else "NOT READY")
            if out["verdict"].startswith("READY"):
                notes = [NOTE_ROWS[r["bcg_name"]]] if r["bcg_name"] in NOTE_ROWS else []
                proposals.append({"ticker": ticker, "cik": cik, "sec_name": r["entity"], "bcg_name": r["bcg_name"],
                                  "bcg_required": True, "annual_form": out["form"].split()[0], "reporting_currency": currency, "notes": notes})
        except Exception as exc:  # one company never stops the batch check
            out["verdict"] = f"ERROR: {type(exc).__name__}: {exc}"[:120]
        results.append(out)
        print(f"{ticker:<6} {out['verdict']:<28} {out['form']:<16} FY {out['period']:<10} price {out['price']:<14} "
              f"missing {','.join(out['missing']) or '-'}  fallbacks {','.join(out['fallbacks']) or '-'}")

    existing = sorted((ROOT / "research").glob("universe-batch-*.json"))
    target = ROOT / "research" / f"universe-batch-{len(existing) + 1}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"proposed_companies": proposals, "checks": results}, indent=2), encoding="utf-8")
    print(f"\nChecked {len(results)}; proposed {len(proposals)} (READY incl. gaps). Written: {target}")
    print("Nothing in config/ was changed.")


if __name__ == "__main__":
    main()
