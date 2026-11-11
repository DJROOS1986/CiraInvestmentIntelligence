"""Build an identifier master for every company in the BCG research data (read-only towards CIRA).

For each company in ingestion/bcg-research/bcg_research.json:
  1. SEC: match the cleaned name against SEC's company list (www.sec.gov/files/company_tickers.json).
     On a unique match: CIK, all tickers for that CIK (share classes kept separate), latest annual form.
  2. Otherwise: OpenFIGI free-text search (common stock only), top candidates with ticker and exchange.
  3. Rows that are segments, duplicates, combined or private are flagged SPECIAL for a human decision.

Output: research/identifier-candidates.csv (open in Excel). Nothing else is written.

Rate limits: SEC paced at 4 req/s with your SEC user agent (ingestion/config.json).
OpenFIGI: paced conservatively; set environment variable OPENFIGI_API_KEY (free key from openfigi.com)
for faster runs. On HTTP 429 the script waits and retries.

Usage (repo root, .venv active):  python scripts/48-Build-Identifier-Master.py
"""
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "identifier-candidates.csv"

# Rows needing a human decision (as far as known on 11 Nov 2026; verify).
SPECIAL = {
    "Amazon (AWS)": ("segment", "AWS is a segment; listed parent is Amazon.com (AMZN)", "Amazon.com"),
    "Tencent Cloud": ("segment", "Segment of Tencent Holdings (listed in Hong Kong)", "Tencent Holdings"),
    "Tencent \u2014 WeChat / Gaming": ("segment", "Segment of Tencent Holdings (listed in Hong Kong)", "Tencent Holdings"),
    "Delta Electronics (Infra)": ("duplicate", "Same listed company as Delta Electronics (Power)", "Delta Electronics"),
    "Delta Electronics (Power)": ("duplicate", "Same listed company as Delta Electronics (Infra)", "Delta Electronics"),
    "Coherent / Lumentum": ("combined", "Two separate listed companies in one row; Lumentum also has its own row", "Coherent"),
    "X-Energy": ("private", "Believed private (not listed) - verify", None),
}
# Search names for rows whose BCG name is an abbreviation or carries a descriptor.
QUERY_ALIASES = {
    "TSMC": "Taiwan Semiconductor Manufacturing",
    "Broadcom (custom AI ASIC design)": "Broadcom",
    "GE Vernova (SMR/BWRX-300)": "GE Vernova",
    "Eternal (Zomato)": "Eternal",
    "Nu Holdings (Nubank)": "Nu Holdings",
    "Fair Isaac (FICO)": "Fair Isaac",
    "SMIC": "Semiconductor Manufacturing International",
    "CATL": "Contemporary Amperex Technology",
    "HKEX": "Hong Kong Exchanges and Clearing",
    "AIA Group": "AIA Group",
    "LVMH": "LVMH Moet Hennessy Louis Vuitton",
    "AT&S": "AT&S Austria Technologie",
    "ASMPT": "ASMPT",
}
SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "holdings",
            "holding", "group", "nv", "sa", "ag", "se", "the", "llc", "lp", "class", "a", "b", "de", "del"}


def normalise(name):
    name = name.lower().replace("\u2014", " ")
    name = re.sub(r"/\s*[a-z]{2,3}\b/?", " ", name)     # SEC state suffixes: /DE, /NEW, / MA, /DE/
    name = re.sub(r"\(.*?\)", " ", name)
    name = name.replace("&", " and ").replace(".", " ")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    words = [w for w in name.split() if w not in SUFFIXES]
    while words and words[-1] == "and":                 # "Eli Lilly & Co" -> "eli lilly"
        words.pop()
    return " ".join(words)


def query_name(company):
    if company in QUERY_ALIASES:
        return QUERY_ALIASES[company]
    if company in SPECIAL and SPECIAL[company][2]:
        return SPECIAL[company][2]
    return re.sub(r"\s*\(.*?\)\s*", " ", company).strip()


def main():
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})
    figi = requests.Session()
    key = os.environ.get("OPENFIGI_API_KEY", "").strip()
    figi.headers.update({"Content-Type": "application/json", **({"X-OPENFIGI-APIKEY": key} if key else {})})
    figi_pause = 0.6 if key else 2.5

    bcg = json.loads((ROOT / "ingestion" / "bcg-research" / "bcg_research.json").read_text(encoding="utf-8"))
    companies = bcg["companies"]

    tickers = sec.get("https://www.sec.gov/files/company_tickers.json", timeout=30).json()
    by_name = {}
    for row in tickers.values():
        by_name.setdefault(normalise(row["title"]), {}).setdefault(str(row["cik_str"]).zfill(10), {
            "title": row["title"], "tickers": []})["tickers"].append(row["ticker"].upper())

    def annual_form(cik):
        time.sleep(0.25)
        recent = sec.get(f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=30).json().get("filings", {}).get("recent", {})
        for form, date in zip(recent.get("form", []), recent.get("filingDate", [])):
            if form in ("10-K", "20-F", "40-F"):
                return f"{form} {date}"
        return "none"

    def figi_search(query):
        body = {"query": query, "marketSecDes": "Equity", "securityType2": "Common Stock"}
        for attempt in range(6):
            time.sleep(figi_pause)
            response = figi.post("https://api.openfigi.com/v3/search", json=body, timeout=30)
            if response.status_code == 429:
                wait = 60 if attempt < 5 else 0
                print(f"   OpenFIGI rate limit - waiting {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json().get("data", [])
        return []

    rows = []
    for index, company in enumerate(companies, 1):
        name = company.get("company", "")
        query = query_name(name)
        row = {"bcg_name": name, "theme": company.get("theme"), "star_score": company.get("star_score"),
               "quality_tier": company.get("quality_tier"), "query": query, "category": "", "status": "",
               "sec_cik": "", "sec_tickers": "", "sec_name": "", "annual_form": "", "figi_candidates": "", "note": ""}
        if name in SPECIAL:
            row["status"], row["note"] = "SPECIAL:" + SPECIAL[name][0], SPECIAL[name][1]
        matches = by_name.get(normalise(query), {})
        if len(matches) == 1:
            cik, info = next(iter(matches.items()))
            form = annual_form(cik)
            row.update(sec_cik=cik, sec_tickers=" ".join(info["tickers"]), sec_name=info["title"], annual_form=form,
                       category="SEC 10-K" if form.startswith("10-K") else ("SEC 20-F/40-F" if form != "none" else "SEC (no annual form)"))
            row["status"] = row["status"] or "MATCHED_SEC"
        elif len(matches) > 1:
            row["status"] = row["status"] or "AMBIGUOUS_SEC"
            row["note"] = (row["note"] + " | " if row["note"] else "") + "Several SEC registrants: " + \
                "; ".join(f"{c} {i['title']} ({' '.join(i['tickers'])})" for c, i in matches.items())
        if not row["sec_cik"] and SPECIAL.get(name, ("", "", "x"))[2] is not None:
            found = figi_search(query)
            seen, candidates = set(), []
            for item in found:
                label = f"{item.get('ticker')}@{item.get('exchCode')} {item.get('name')} [{item.get('compositeFIGI') or item.get('figi')}]"
                if label not in seen:
                    seen.add(label)
                    candidates.append(label)
                if len(candidates) == 5:
                    break
            row["figi_candidates"] = " | ".join(candidates)
            row["category"] = row["category"] or "non-SEC (provider needed)"
            row["status"] = row["status"] or ("CANDIDATES" if candidates else "NO_MATCH")
        rows.append(row)
        print(f"{index:>3}/{len(companies)} {row['status']:<16} {name}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWritten: {OUT}")
    for label in ("SEC 10-K", "SEC 20-F/40-F", "non-SEC (provider needed)"):
        print(f"  {label:<26} {sum(1 for r in rows if r['category'] == label)}")
    for status in sorted({r['status'] for r in rows}):
        print(f"  status {status:<20} {sum(1 for r in rows if r['status'] == status)}")


if __name__ == "__main__":
    sys.exit(main())
