"""Fourth revenue label: RevenueFromContractWithCustomerIncludingAssessedTax (one-off, idempotent, all-or-nothing).

Copart (CPRT) and CrowdStrike (CRWD) report annual revenue only under this label (checked 12 Nov 2026 with
scripts/60: CPRT FY2026-07-31 4,666.2 m; CRWD FY2026-01-31 4,812.0 m). Lowest priority, so companies that
report the usual 'excluding assessed tax' label are unaffected. Shown as a data-quality note.
Usage (repo root): python scripts/61-Add-Revenue-Fallback.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "RevenueFromContractWithCustomerIncludingAssessedTax"
NOTE = "Revenue uses RevenueFromContractWithCustomerIncludingAssessedTax (may include sales taxes collected from customers)"

TEST = '''

def test_revenue_fallback_including_assessed_tax():  # Copart FY2026: only this label after 2018
    facts = {k: v for k, v in BASE.items() if k != "RevenueFromContractWithCustomerExcludingAssessedTax"}
    facts["Revenues"] = {"USD": [{"val": 1_805_700_000, "start": "2017-08-01", "end": "2018-07-31",
                                  "form": "10-K", "fp": "FY", "filed": "2018-10-01", "accn": "old"}]}
    facts["RevenueFromContractWithCustomerIncludingAssessedTax"] = duration(4_666_200_000)
    result = run(facts)
    assert result["period_end"] == END
    assert result["metrics_usd"]["revenue"] == 4_666_200_000
    assert result["provenance"]["revenue"]["tag"] == "RevenueFromContractWithCustomerIncludingAssessedTax"


def test_excluding_tax_label_still_preferred():
    facts = {**BASE, "RevenueFromContractWithCustomerIncludingAssessedTax": duration(9_999)}
    result = run(facts)
    assert result["provenance"]["revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
'''

EDITS = [
    ("portfolio-engine/financial_processor.py", f'"{LABEL}"',
     r'(?m)^(?P<ind>[ \t]*)"SalesRevenueNet",[ \t]*(?=\r?\n)',
     lambda m, nl: f'{m.group(0)}{nl}{m["ind"]}"{LABEL}",'),
    ("portfolio-engine/company_intelligence.py", f"'{LABEL}'",
     r"(?m)^(?P<ind>[ \t]*)'PaymentsToAcquireProductiveAssets': '[^'\r\n]*',[ \t]*(?=\r?\n)",
     lambda m, nl: f"{m.group(0)}{nl}{m['ind']}'{LABEL}': '{NOTE}',"),
    ("scripts/52-Verify-Universe-Batch.py", f'"{LABEL}"',
     r'METHODOLOGY_FALLBACKS = \{"ProfitLoss", "PaymentsToAcquireProductiveAssets"\}',
     lambda m, nl: f'METHODOLOGY_FALLBACKS = {{"ProfitLoss", "PaymentsToAcquireProductiveAssets", "{LABEL}"}}'),
    ("tests/test_financial_fallbacks.py", "test_revenue_fallback_including_assessed_tax",
     r"\Z", lambda m, nl: TEST.replace("\n", nl)),
]


def main():
    texts, problems, applied = {}, [], []
    for rel, marker, pattern, build in EDITS:
        if rel not in texts:
            texts[rel] = (ROOT / rel).read_bytes().decode("utf-8")
        text = texts[rel]
        nl = "\r\n" if "\r\n" in text else "\n"
        if marker in text:
            continue
        hits = list(re.finditer(pattern, text))
        if len(hits) != 1:
            problems.append(f"{rel}: pattern for {marker} matched {len(hits)} times")
            continue
        texts[rel] = text[:hits[0].start()] + build(hits[0], nl) + text[hits[0].end():]
        applied.append(rel)
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
