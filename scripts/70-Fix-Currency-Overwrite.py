"""Fix: script 52 overwrote the reporting currency with the Yahoo price currency (13 Nov 2026).

  - config/universe.json: ASML -> EUR, XPEV -> CNY (both were recorded as USD by the bug)
  - scripts/52: the price check uses its own variable (price_currency)
  - stage 07: a company whose newest fiscal year is older than ~18 months is excluded as stale
    (it was only checked in verification; in USD mode XPEV would have shown FY2020 as latest)
One-off, idempotent, all-or-nothing. Usage (repo root): python scripts/70-Fix-Currency-Overwrite.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXES = {"ASML": "EUR", "XPEV": "CNY"}

STALE = '''MAX_FINANCIAL_AGE_DAYS = 550  # newest fiscal year older than ~18 months = stale (wrong label or currency)


def _check_fresh(result):
    from datetime import date
    age = (date.today() - date.fromisoformat(result["period_end"])).days
    if age > MAX_FINANCIAL_AGE_DAYS:
        raise ValueError(f"Stale financials: newest fiscal year ends {result['period_end']} ({age} days ago)")


'''


def edit(rel, edits):
    path = ROOT / rel
    text = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    done = []
    for marker, pattern, build, expected in edits:
        if marker in text:
            continue
        hits = list(re.finditer(pattern, text))
        if (expected is None and not hits) or (expected is not None and len(hits) != expected):
            sys.exit(f"{rel}: pattern for {marker!r} matched {len(hits)} times. Nothing written.")
        for m in reversed(hits):
            text = text[:m.start()] + build(m, nl) + text[m.end():]
        done.append(marker)
    return path, text, done


def main():
    changes = []
    changes.append(edit("scripts/52-Verify-Universe-Batch.py", [
        ('price_currency = result_chart', r'(?m)^(?P<i>[ \t]*)currency = result_chart\.get\("meta", \{\}\)\.get\("currency"\)',
         lambda m, nl: f'{m["i"]}price_currency = result_chart.get("meta", {{}}).get("currency")', 1),
        ('closes {price_currency}', r'closes \{currency\}', lambda m, nl: 'closes {price_currency}', 1),
        ('price_currency == "USD"', r'bool\(closes\) and currency == "USD"', lambda m, nl: 'bool(closes) and price_currency == "USD"', 1),
    ]))
    changes.append(edit("scripts/07-Generate-Financial-Reports.py", [
        ("def _check_fresh(result):", r"(?m)^def main\(\):", lambda m, nl: STALE.replace("\n", nl) + m.group(0), 1),
        ("# stale guard", r"(?m)^(?P<i>[ \t]*)result = module\.extract_annual_metrics\(source, \*\*_fx_args\(ticker\)\)[ \t]*(?=\r?\n)",
         lambda m, nl: m.group(0) + nl + m["i"] + "_check_fresh(result)  # stale guard", 1),
    ]))
    upath = ROOT / "config" / "universe.json"
    doc = json.loads(upath.read_text(encoding="utf-8"))
    fixed = []
    for c in doc["companies"]:
        if c["ticker"] in FIXES and c.get("reporting_currency") != FIXES[c["ticker"]]:
            c["reporting_currency"] = FIXES[c["ticker"]]
            fixed.append(f'{c["ticker"]}={FIXES[c["ticker"]]}')
    if set(FIXES) - {c["ticker"] for c in doc["companies"]}:
        sys.exit("universe.json lacks ASML or XPEV. Nothing written.")
    for path, text, done in changes:
        if done:
            path.write_bytes(text.encode("utf-8"))
            print(f"{path.relative_to(ROOT)}: {', '.join(d.strip() for d in done)}")
    if fixed:
        rows = ",\n".join(f"    {json.dumps(c, ensure_ascii=False)}" for c in doc["companies"])
        upath.write_bytes(("{\n" f'  "schema_version": {json.dumps(doc["schema_version"])},\n'
                           f'  "description": {json.dumps(doc["description"], ensure_ascii=False)},\n'
                           '  "companies": [\n' + rows + "\n  ]\n}\n").encode("utf-8"))
        print("universe.json:", " ".join(fixed))
    if not fixed and not any(d for _, _, d in changes):
        print("All fixes already applied.")


if __name__ == "__main__":
    main()
