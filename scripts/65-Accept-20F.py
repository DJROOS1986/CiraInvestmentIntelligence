"""Accept SEC 20-F annual reports (foreign private issuers reporting US GAAP in USD). One-off, idempotent, all-or-nothing.

Checked 13 Nov 2026 with scripts/64: ARM, CAMT, NVMI and SE report us-gaap revenue in USD on form 20-F.
Companies reporting in other currencies stay out automatically: CIRA reads USD values only.
Usage (repo root): python scripts/65-Accept-20F.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEST = '''

def test_20f_annual_report_accepted():  # foreign private issuers (e.g. Camtek, Nova) file 20-F instead of 10-K
    facts = {}
    for label, entry in BASE.items():
        facts[label] = {"USD": [dict(item, form="20-F") for item in entry["USD"]]}
    result = run(facts)
    assert result["metrics_usd"]["revenue"] == 5_296_759_000
    assert result["metrics_usd"]["capital_expenditure"] == 141_871_000


def test_non_usd_20f_values_ignored():  # e.g. Alibaba reports in CNY: must not be read as USD
    facts = {label: ({"CNY": entry["USD"]} if label.startswith("Revenue") else entry) for label, entry in BASE.items()}
    try:
        run(facts)
    except ValueError as exc:
        assert "revenue" in str(exc).lower()
    else:
        raise AssertionError("CNY revenue must not be accepted")
'''

EDITS = [
    # (file, done-marker, pattern, replacement-builder, expected matches or None for >=1 replace-all)
    ("portfolio-engine/financial_processor.py", '"20-F", "20-F/A"',
     r'\("10-K", "10-K/A"\)', lambda m, nl: '("10-K", "10-K/A", "20-F", "20-F/A")', None),
    ("scripts/52-Verify-Universe-Batch.py", 'r["category"] in ("SEC_10K", "SEC_20F")',
     r'r\["category"\] == "SEC_10K"', lambda m, nl: 'r["category"] in ("SEC_10K", "SEC_20F")', None),
    ("scripts/52-Verify-Universe-Batch.py", 'startswith(("10-K", "20-F"))',
     r'ok_form = out\["form"\]\.startswith\("10-K"\)', lambda m, nl: 'ok_form = out["form"].startswith(("10-K", "20-F"))', 1),
    ("scripts/52-Verify-Universe-Batch.py", '"annual_form": out["form"].split()[0]',
     r'"annual_form": "10-K"', lambda m, nl: '"annual_form": out["form"].split()[0]', 1),
    ("scripts/53-Add-Universe-Batch.py", 'r["category"] in ("SEC_10K", "SEC_20F")',
     r'r\["category"\] == "SEC_10K"', lambda m, nl: 'r["category"] in ("SEC_10K", "SEC_20F")', None),
    ("tests/test_universe.py", 'assertIn(c["annual_form"], ("10-K", "20-F")',
     r'self\.assertEqual\(c\["annual_form"\], "10-K", c\["ticker"\]\)',
     lambda m, nl: 'self.assertIn(c["annual_form"], ("10-K", "20-F"), c["ticker"])', 1),
    ("tests/test_identifiers.py", 'by_ticker = {r["primary_ticker"]: r for r in self.rows if r["category"] in ("SEC_10K", "SEC_20F")}',
     r'by_ticker = \{r\["primary_ticker"\]: r for r in self\.rows if r\["category"\] == "SEC_10K"\}',
     lambda m, nl: 'by_ticker = {r["primary_ticker"]: r for r in self.rows if r["category"] in ("SEC_10K", "SEC_20F")}', 1),
    ("tests/test_financial_fallbacks.py", "test_20f_annual_report_accepted",
     r"\Z", lambda m, nl: TEST.replace("\n", nl), 1),
]


def main():
    texts, problems, applied = {}, [], []
    for rel, marker, pattern, build, expected in EDITS:
        if rel not in texts:
            texts[rel] = (ROOT / rel).read_bytes().decode("utf-8")
        text = texts[rel]
        nl = "\r\n" if "\r\n" in text else "\n"
        if marker in text:
            continue
        hits = list(re.finditer(pattern, text))
        if (expected is None and not hits) or (expected is not None and len(hits) != expected):
            problems.append(f"{rel}: pattern for {marker} matched {len(hits)} times")
            continue
        for m in reversed(hits):
            text = text[:m.start()] + build(m, nl) + text[m.end():]
        texts[rel] = text
        applied.append(f"{rel} ({len(hits)}x)")
    if problems:
        print("NOTHING WRITTEN:")
        for p in problems:
            print("  ", p)
        sys.exit(1)
    for rel, text in texts.items():
        if text != (ROOT / rel).read_bytes().decode("utf-8"):
            (ROOT / rel).write_bytes(text.encode("utf-8"))
    print(f"Applied {len(applied)} edit(s):" if applied else "All edits already applied.")
    for a in applied:
        print("  ", a)


if __name__ == "__main__":
    main()
