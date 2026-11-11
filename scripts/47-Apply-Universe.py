"""Wire config/universe.json into CIRA (one-off, idempotent, all-or-nothing).

Every edit must match exactly once (or be already applied); otherwise NOTHING is written.
Usage (repo root): python scripts/47-Apply-Universe.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPR = ('tuple(c["ticker"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve()'
        '.parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"])')
COMPANIES = ('__import__("json").loads((__import__("pathlib").Path(__file__).resolve()'
             '.parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]')

FP_HELPERS = '''DERIVED_TOLERANCE = 0.001
EQUITY_TAGS = (
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquity",
)


def _instant_value(facts, tag, period_end):
    """Latest-filed 10-K balance-sheet value of a tag at period_end, or None."""
    best = None
    for item in facts.get(tag, {}).get("units", {}).get("USD", []):
        if item.get("form") not in ("10-K", "10-K/A") or item.get("val") is None:
            continue
        if item.get("end") != period_end or item.get("start") is not None or not item.get("filed"):
            continue
        if best is None or (item["filed"], item.get("accn", "")) > (best["filed"], best.get("accn", "")):
            best = item
    return best


def derive_total_liabilities(facts, period_end):
    """Current + non-current liabilities, accepted only if it equals total liabilities and equity minus equity."""
    current = _instant_value(facts, "LiabilitiesCurrent", period_end)
    noncurrent = _instant_value(facts, "LiabilitiesNoncurrent", period_end)
    total = _instant_value(facts, "LiabilitiesAndStockholdersEquity", period_end)
    if not (current and noncurrent and total):
        return None
    summed = current["val"] + noncurrent["val"]
    if summed <= 0:
        return None
    for equity_tag in EQUITY_TAGS:
        equity = _instant_value(facts, equity_tag, period_end)
        if equity and abs(summed - (total["val"] - equity["val"])) <= DERIVED_TOLERANCE * summed:
            return summed, {
                "tag": "derived: LiabilitiesCurrent + LiabilitiesNoncurrent",
                "cross_check": f"LiabilitiesAndStockholdersEquity - {equity_tag}",
                "filed": current["filed"],
                "period_end": period_end,
                "start": None,
                "accession": current.get("accn"),
            }
    return None


'''

FP_DERIVE_BLOCK = '''{ind}if results["total_liabilities"] is None:
{ind}    derived = derive_total_liabilities(facts, period_end)
{ind}    if derived is not None:
{ind}        results["total_liabilities"], provenance["total_liabilities"] = derived

'''

CI_HELPERS = '''FALLBACK_TAG_WARNINGS = {
    'ProfitLoss': 'Net income uses ProfitLoss (includes non-controlling interests) because NetIncomeLoss is not reported',
    'PaymentsToAcquireProductiveAssets': 'Capital expenditure uses PaymentsToAcquireProductiveAssets (may include some intangible assets)',
}


def universe_companies():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'config' / 'universe.json'
    return json.loads(path.read_text(encoding='utf-8'))['companies']


def universe_tickers():
    return {c['ticker'] for c in universe_companies()}


def universe_notes(ticker):
    return next((list(c.get('notes', [])) for c in universe_companies() if c['ticker'] == ticker), [])


def provenance_warnings(financial):
    provenance = financial.get('provenance')
    if not isinstance(provenance, dict):
        return []
    metrics = financial.get('metrics_usd') or {}
    out = []
    for key in ('revenue', 'net_income', 'total_assets', 'total_liabilities', 'operating_cash_flow', 'capital_expenditure'):
        label = key.replace('_', ' ').capitalize()
        if metrics.get(key) is None:
            out.append(f'{label} not reported under supported SEC labels')
            continue
        tag = str((provenance.get(key) or {}).get('tag', ''))
        if tag.startswith('derived:'):
            out.append(f'{label} derived ({tag[len("derived:"):].strip()}), cross-checked against the balance sheet')
        elif tag in FALLBACK_TAG_WARNINGS:
            out.append(FALLBACK_TAG_WARNINGS[tag])
    return out


'''

ALIASES = ('COMPANY_ALIASES = {c["ticker"]: c["bcg_name"] for c in ' + COMPANIES + ' if c.get("bcg_name")}')
PORTFOLIO_COLUMNS = '[col for row in [st.columns(4) for _ in range((len(TICKERS) + 3) // 4)] for col in row]'

# (file, done-marker, regex, replacement-builder)
EDITS = [
    ("portfolio-engine/financial_processor.py", '"ProfitLoss"',
     r'"net_income": \["NetIncomeLoss"\],', lambda m, nl: '"net_income": ["NetIncomeLoss", "ProfitLoss"],'),
    ("portfolio-engine/financial_processor.py", '"PaymentsToAcquireProductiveAssets"',
     r'(?m)^(?P<ind>[ \t]*)"PaymentsToAcquirePropertyPlantAndEquipment"[ \t]*(?=\r?\n)',
     lambda m, nl: f'{m["ind"]}"PaymentsToAcquirePropertyPlantAndEquipment",{nl}{m["ind"]}"PaymentsToAcquireProductiveAssets"'),
    ("portfolio-engine/financial_processor.py", "def derive_total_liabilities",
     r'(?m)^def extract_annual_metrics\(', lambda m, nl: FP_HELPERS.replace("\n", nl) + m.group(0)),
    ("portfolio-engine/financial_processor.py", "derived = derive_total_liabilities",
     r'(?m)^(?P<ind>[ \t]*)ocf = results\["operating_cash_flow"\]',
     lambda m, nl: FP_DERIVE_BLOCK.format(ind=m["ind"]).replace("\n", nl) + m.group(0)),

    ("portfolio-engine/company_intelligence.py", "def universe_tickers",
     r'(?m)^def build_company_intelligence\(', lambda m, nl: CI_HELPERS.replace("\n", nl) + m.group(0)),
    ("portfolio-engine/company_intelligence.py", "not in universe_tickers()",
     r"if ticker not in \{'AAPL', 'MSFT'\}:", lambda m, nl: "if ticker not in universe_tickers():"),
    ("portfolio-engine/company_intelligence.py", "universe_notes(ticker))",
     r"(?m)^(?P<ind>[ \t]*)if ticker == 'MSFT':[ \t]*\r?\n[ \t]*warnings\.append\('Microsoft BCG growth figure[^\r\n]*\)",
     lambda m, nl: f"{m['ind']}warnings.extend(universe_notes(ticker)){nl}{m['ind']}warnings.extend(provenance_warnings(financial))"),

    ("portfolio-engine/bcg_integration.py", "universe.json",
     r'(?s)COMPANY_ALIASES = \{[^{}]*\}', lambda m, nl: ALIASES),

    ("dashboard/data.py", "universe.json",
     r"TICKERS = \('AAPL', 'MSFT'\)", lambda m, nl: "TICKERS = " + EXPR),
    ("dashboard/data.py", "report_count') != len(TICKERS)",
     r"manifest\.get\('report_count'\) != 2", lambda m, nl: "manifest.get('report_count') != len(TICKERS)"),
    ("dashboard/app.py", "COMPANIES')",
     r"st\.caption\('RESEARCH WORKSPACE / AAPL[^'\r\n]*'\)", lambda m, nl: "st.caption(f'RESEARCH WORKSPACE / {len(TICKERS)} COMPANIES')"),
    ("dashboard/app.py", "st.columns(4) for _",
     r"zip\(TICKERS, st\.columns\(2\)\)", lambda m, nl: f"zip(TICKERS, {PORTFOLIO_COLUMNS})"),

    ("scripts/07-Generate-Financial-Reports.py", "universe.json", r'\("AAPL", "MSFT"\)', lambda m, nl: EXPR),
    ("scripts/10-Analyze-Financial-Reports.py", "universe.json", r'\("AAPL", "MSFT"\)', lambda m, nl: EXPR),
    ("scripts/13-Ingest-Market-Prices.py", "universe.json", r'SYMBOLS = \["AAPL", "MSFT"\]', lambda m, nl: "SYMBOLS = list(" + EXPR + ")"),
    ("scripts/14-Analyze-Market-Prices.py", "universe.json", r'\("AAPL", "MSFT"\)', lambda m, nl: EXPR),
    ("scripts/15-Build-Company-Intelligence.py", "universe.json", r'\("AAPL", "MSFT"\)', lambda m, nl: EXPR),
    ("scripts/16-Refresh-Company-Intelligence.py", "universe.json", r'TICKERS = \("AAPL", "MSFT"\)', lambda m, nl: "TICKERS = " + EXPR),
    ("scripts/20-Publish-Versioned-Reports.py", "universe.json", r'TICKERS = \("AAPL", "MSFT"\)', lambda m, nl: "TICKERS = " + EXPR),
    ("scripts/12-Run-Cloud-Pipeline.py", 'c["cik"]} for c in',
     r'\{"ticker": "AAPL", "cik": "0000320193"\},[ \t]*\r?\n[ \t]*\{"ticker": "MSFT", "cik": "0000789019"\},',
     lambda m, nl: '*[{"ticker": c["ticker"], "cik": c["cik"]} for c in ' + COMPANIES + '],'),
    ("scripts/12-Run-Cloud-Pipeline.py", '-financial-report.json" for t in',
     r'REPORTS / "financial" / "AAPL-financial-report\.json",[ \t]*\r?\n[ \t]*REPORTS / "financial" / "MSFT-financial-report\.json",',
     lambda m, nl: '*[REPORTS / "financial" / f"{t}-financial-report.json" for t in ' + EXPR + '],'),

    ("Dockerfile.phase5", "config/universe.json",
     r'(?m)^COPY portfolio-engine/ /app/portfolio-engine/[ \t]*(?=\r?\n)',
     lambda m, nl: m.group(0) + nl + "COPY config/universe.json /app/config/universe.json"),
    ("Dockerfile.dashboard", "config/universe.json",
     r'(?m)^COPY dashboard/ /app/dashboard/[ \t]*(?=\r?\n)',
     lambda m, nl: m.group(0) + nl + "COPY config/universe.json /app/config/universe.json"),
]


def main():
    if not (ROOT / "config" / "universe.json").is_file():
        sys.exit("config/universe.json missing - extract CIRA-Universe.zip first. Nothing written.")
    texts, problems, applied = {}, [], []
    for rel, marker, pattern, build in EDITS:
        path = ROOT / rel
        if rel not in texts:
            texts[rel] = path.read_bytes().decode("utf-8")
        text = texts[rel]
        nl = "\r\n" if "\r\n" in text else "\n"
        if marker in text:
            continue
        hits = list(re.finditer(pattern, text))
        if len(hits) != 1:
            problems.append(f"{rel}: pattern for '{marker}' matched {len(hits)} times")
            continue
        m = hits[0]
        texts[rel] = text[:m.start()] + build(m, nl) + text[m.end():]
        applied.append(f"{rel}: {marker}")
    if problems:
        print("NOTHING WRITTEN. Unmatched edits:")
        for p in problems:
            print("  ", p)
        sys.exit(1)
    for rel, text in texts.items():
        original = (ROOT / rel).read_bytes().decode("utf-8")
        if text != original:
            (ROOT / rel).write_bytes(text.encode("utf-8"))
    print(f"Applied {len(applied)} edit(s):" if applied else "All edits already applied.")
    for a in applied:
        print("  ", a)


if __name__ == "__main__":
    main()
