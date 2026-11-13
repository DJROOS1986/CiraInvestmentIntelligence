"""Reporting currency = the currency with the most full years of revenue (no USD convenience translations).

13 Nov 2026: BABA, TCOM, HSAI, YMM (and XPEV) report in CNY but their SEC data also holds a few USD
"convenience translation" values; script 52 used those because it tried USD first. Now:
  - scripts/52 always detects the dominant currency and uses only that currency
  - config/universe.json: BABA, TCOM, HSAI, YMM get reporting_currency CNY
  - verification: their figures re-extracted in CNY and converted with ECB rates (printed)
One-off, idempotent. Usage (repo root, .venv active): python scripts/69-Fix-Reporting-Currency.py
"""
import importlib.util
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CNY_COMPANIES = ["BABA", "TCOM", "HSAI", "YMM"]

DETECT = '''def detect_currency(doc, fp):
    """Reporting currency: the unit with the most full-year 10-K/20-F revenue years (ties: newest data).
    Ignores USD convenience translations that some foreign filers add for a single year."""
    facts = doc.get("facts", {}).get("us-gaap", {})
    years, newest = {}, {}
    for label in fp.TAGS["revenue"]:
        for unit, items in facts.get(label, {}).get("units", {}).items():
            for item in items:
                if item.get("form") in ("10-K", "10-K/A", "20-F", "20-F/A") and item.get("end") and item.get("start"):
                    years.setdefault(unit, set()).add(item["end"])
                    newest[unit] = max(newest.get(unit, ""), item["end"])
    if not years:
        return None
    return max(years, key=lambda u: (len(years[u]), newest[u]))


'''
USE = '''{i}currency = detect_currency(json.loads(facts), fp) or "USD"
{i}if currency == "USD":
{i}    result = fp.extract_annual_metrics(path)
{i}else:
{i}    result = fp.extract_annual_metrics(path, currency=currency, fx=load_fx().EcbRates())
{i}    out["fallbacks"].append(f"converted from {{currency}}")'''


def patch_52():
    path = ROOT / "scripts" / "52-Verify-Universe-Batch.py"
    text = path.read_bytes().decode("utf-8")
    if "most full-year 10-K/20-F revenue years" in text:
        return "52: already patched"
    nl = "\r\n" if "\r\n" in text else "\n"
    a = list(re.finditer(r"(?ms)^def detect_currency\(doc, fp\):.*?(?=^def load_fx\(\):)", text))
    b = list(re.finditer(r"(?m)^(?P<i>[ \t]*)currency = \"USD\"[ \t]*\r?\n[ \t]*try:[ \t]*\r?\n[ \t]*result = fp\.extract_annual_metrics\(path\)[ \t]*\r?\n"
                         r"[ \t]*except ValueError:[ \t]*\r?\n[ \t]*currency = detect_currency\(json\.loads\(facts\), fp\)[ \t]*\r?\n"
                         r"[ \t]*if currency in \(None, \"USD\"\):[ \t]*\r?\n[ \t]*raise[ \t]*\r?\n"
                         r"[ \t]*result = fp\.extract_annual_metrics\(path, currency=currency, fx=load_fx\(\)\.EcbRates\(\)\)[ \t]*\r?\n"
                         r"[ \t]*out\[\"fallbacks\"\]\.append\(f\"converted from \{currency\}\"\)", text))
    if len(a) != 1 or len(b) != 1:
        sys.exit(f"52: patterns matched {len(a)}/{len(b)} (expected 1/1). Nothing written.")
    text = text[:b[0].start()] + USE.format(i=b[0]["i"]).replace("\n", nl) + text[b[0].end():]
    a = list(re.finditer(r"(?ms)^def detect_currency\(doc, fp\):.*?(?=^def load_fx\(\):)", text))
    text = text[:a[0].start()] + DETECT.replace("\n", nl) + text[a[0].end():]
    path.write_bytes(text.encode("utf-8"))
    return "52: dominant-currency detection, no USD-first"


def render_universe(doc):
    rows = ",\n".join(f"    {json.dumps(c, ensure_ascii=False)}" for c in doc["companies"])
    return ("{\n" f'  "schema_version": {json.dumps(doc["schema_version"])},\n'
            f'  "description": {json.dumps(doc["description"], ensure_ascii=False)},\n'
            '  "companies": [\n' + rows + "\n  ]\n}\n")


def patch_universe():
    path = ROOT / "config" / "universe.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    changed = []
    for c in doc["companies"]:
        if c["ticker"] in CNY_COMPANIES and c.get("reporting_currency") != "CNY":
            c["reporting_currency"] = "CNY"
            changed.append(c["ticker"])
    missing = set(CNY_COMPANIES) - {c["ticker"] for c in doc["companies"]}
    if missing:
        sys.exit(f"universe.json lacks {sorted(missing)}. Nothing written.")
    if changed:
        path.write_bytes(render_universe(doc).encode("utf-8"))
    return f"universe: reporting_currency CNY set for {' '.join(changed) or '(already set)'}"


def verify():
    load = lambda name, rel: (lambda s: (s.loader.exec_module(m := importlib.util.module_from_spec(s)), m)[1])(
        importlib.util.spec_from_file_location(name, ROOT / rel))
    fp, fx = load("cira_fp", "portfolio-engine/financial_processor.py"), load("cira_fx", "portfolio-engine/fx.py")
    rates = fx.EcbRates()
    cfg = json.loads((ROOT / "ingestion" / "config.json").read_text(encoding="utf-8"))
    ciks = {c["ticker"]: c["cik"] for c in json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]}
    sec = requests.Session()
    sec.headers.update({"User-Agent": cfg["sec_user_agent"], "Accept-Encoding": "gzip, deflate"})
    print("\nVerification in CNY (ECB-converted to USD):")
    for t in CNY_COMPANIES:
        time.sleep(0.25)
        raw = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{ciks[t]}.json", timeout=60).content
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.json"
            p.write_bytes(raw)
            r = fp.extract_annual_metrics(p, currency="CNY", fx=rates)
        m, rep = r["metrics_usd"], r["reported_metrics"]
        missing = [k for k in ("net_income", "total_assets", "total_liabilities", "operating_cash_flow", "capital_expenditure") if m.get(k) is None]
        avg = r["fx"]["rates"]["revenue"]["usd_per_unit"]
        print(f"   {t:<5} FY {r['period_end']}  revenue {rep['revenue'] / 1e6:>12,.1f} m CNY -> {m['revenue'] / 1e6:>10,.1f} m USD"
              f" (avg {avg:.5f})  missing: {', '.join(missing) or '-'}")


if __name__ == "__main__":
    print(patch_52())
    print(patch_universe())
    verify()
