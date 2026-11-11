"""Turn research/identifier-candidates.csv + the reviewed decisions (11 Nov 2026) into config/identifiers.csv.

config/identifiers.csv is the identifier master for every BCG company: which data route it can use
(SEC_10K / SEC_20F / PROVIDER / PARKED), its primary ticker and exchange, CIK where applicable,
whether it is already in config/universe.json, and how certain the identifier is.

Network: one request to SEC's company list (to resolve CIKs for overridden US tickers such as VRTX).
Usage (repo root, .venv active):  python scripts/49-Build-Identifiers.py
"""
import csv
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "research" / "identifier-candidates.csv"
OUT = ROOT / "config" / "identifiers.csv"

# Reviewed decisions. exchange codes follow OpenFIGI (US, JT = Tokyo, TT = Taiwan, HK = Hong Kong).
# "to_verify" = from knowledge / search, not yet confirmed against an official source.
DECISIONS = {
    "Vertex Pharmaceuticals": dict(category="SEC_10K", sec_ticker="VRTX", certainty="verified",
                                   note="Name filter missed SEC title 'INC / MA'; resolved by ticker"),
    "Amazon (AWS)": dict(category="SEC_10K", entity="Amazon.com", certainty="verified",
                         note="AWS is a segment; figures are for all of Amazon"),
    "Coherent / Lumentum": dict(category="SEC_10K", entity="Coherent", certainty="verified",
                                note="Row mapped to Coherent only; Lumentum has its own row"),
    "Delta Electronics (Infra)": dict(category="PROVIDER", entity="Delta Electronics", ticker="2308", exchange="TT",
                                      certainty="to_verify", note="Same company as Delta Electronics (Power)"),
    "Delta Electronics (Power)": dict(category="PROVIDER", entity="Delta Electronics", ticker="2308", exchange="TT",
                                      certainty="to_verify", note="Same company as Delta Electronics (Infra)"),
    "Tencent Cloud": dict(category="PROVIDER", entity="Tencent Holdings", ticker="700", exchange="HK",
                          certainty="to_verify", note="Segment of Tencent Holdings; home listing Hong Kong"),
    "Tencent \u2014 WeChat / Gaming": dict(category="PROVIDER", entity="Tencent Holdings", ticker="700", exchange="HK",
                                          certainty="to_verify", note="Segment of Tencent Holdings; home listing Hong Kong"),
    "X-Energy": dict(category="PARKED", certainty="to_verify",
                     note="SEC lists X-Energy, Inc. (XE) without an annual report yet; verify listing; wait for first 10-K"),
    "Advantest": dict(category="PROVIDER", ticker="6857", exchange="JT", certainty="to_verify",
                      note="Last SEC 20-F in 2015; no longer an SEC filer"),
    "Hoya Corporation": dict(category="PROVIDER", ticker="7741", exchange="JT", certainty="to_verify", note="OpenFIGI no match; from knowledge"),
    "TDK Corporation": dict(category="PROVIDER", ticker="6762", exchange="JT", certainty="to_verify", note="OpenFIGI no match; from knowledge"),
    "Nan Ya PCB": dict(category="PROVIDER", ticker="8046", exchange="TT", certainty="to_verify", note="OpenFIGI no match; from knowledge"),
    "ITEQ Corporation": dict(category="PROVIDER", ticker="6213", exchange="TT", certainty="to_verify", note="OpenFIGI no match; from knowledge"),
}
CATEGORY_MAP = {"SEC 10-K": "SEC_10K", "SEC 20-F/40-F": "SEC_20F",
                "SEC (no annual form)": "PROVIDER", "non-SEC (provider needed)": "PROVIDER"}
FIELDS = ["bcg_name", "entity", "category", "primary_ticker", "exchange", "all_tickers", "sec_cik",
          "annual_form", "in_universe", "certainty", "theme", "star_score", "quality_tier", "figi_candidates", "note"]


def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    universe = {c["ticker"]: c for c in json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]}
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec_list = requests.get("https://www.sec.gov/files/company_tickers.json", timeout=30,
                            headers={"User-Agent": cfg["sec_user_agent"]}).json()
    sec_by_ticker = {r["ticker"].upper(): r for r in sec_list.values()}

    out = []
    for r in rows:
        d = DECISIONS.get(r["bcg_name"], {})
        category = d.get("category") or CATEGORY_MAP.get(r["category"], "")
        tickers = r["sec_tickers"].split()
        row = {
            "bcg_name": r["bcg_name"], "entity": d.get("entity") or r["sec_name"] or r["query"],
            "category": category, "primary_ticker": "", "exchange": "", "all_tickers": r["sec_tickers"],
            "sec_cik": "", "annual_form": r["annual_form"], "in_universe": "no",
            "certainty": d.get("certainty", ""), "theme": r["theme"], "star_score": r["star_score"],
            "quality_tier": r["quality_tier"], "figi_candidates": r["figi_candidates"], "note": d.get("note", ""),
        }
        if category in ("SEC_10K", "SEC_20F"):
            ticker = d.get("sec_ticker") or (tickers[0] if tickers else "")
            sec = sec_by_ticker.get(ticker)
            if not sec:
                sys.exit(f"SEC ticker {ticker!r} for {r['bcg_name']} not found in SEC list. Nothing written.")
            row.update(primary_ticker=ticker, exchange="US", sec_cik=str(sec["cik_str"]).zfill(10),
                       all_tickers=r["sec_tickers"] or ticker, certainty=row["certainty"] or "verified")
            if d.get("sec_ticker"):
                row["entity"] = sec["title"]
                row["annual_form"] = row["annual_form"] or "10-K (resolved by ticker; verify filing date)"
        elif category == "PARKED":
            row.update(primary_ticker=tickers[0] if tickers else "", exchange="US")
        else:
            row.update(primary_ticker=d.get("ticker", ""), exchange=d.get("exchange", ""),
                       certainty=row["certainty"] or "pending_home_listing")
        if row["primary_ticker"] in universe and row["category"] == "SEC_10K":
            row["in_universe"] = "yes"
            if universe[row["primary_ticker"]]["cik"] != row["sec_cik"]:
                sys.exit(f"CIK mismatch for {row['primary_ticker']}: identifiers {row['sec_cik']} vs universe "
                         f"{universe[row['primary_ticker']]['cik']}. Nothing written.")
        out.append(row)

    missing = sorted(set(universe) - {r["primary_ticker"] for r in out if r["in_universe"] == "yes"} - {"AAPL"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)

    print(f"Written: {OUT}  ({len(out)} BCG rows)")
    for cat in ("SEC_10K", "SEC_20F", "PROVIDER", "PARKED"):
        sel = [r for r in out if r["category"] == cat]
        print(f"  {cat:<9} rows {len(sel):>3}   entities {len({r['entity'] for r in sel}):>3}")
    print(f"  already in CIRA universe: {sum(r['in_universe'] == 'yes' for r in out)}")
    print(f"  SEC_10K not yet in universe: {sum(r['category'] == 'SEC_10K' and r['in_universe'] == 'no' for r in out)}")
    if missing:
        print(f"  NOTE universe tickers not found among BCG SEC_10K rows (expected: MSFT if absent from BCG): {missing}")


if __name__ == "__main__":
    main()
