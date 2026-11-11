"""Per-company publishing (one-off, idempotent, all-or-nothing).

A company that fails a stage is excluded (logged as CIRA COMPANY FAILED) and the rest still publishes;
more than 10% excluded fails the whole run. SEC ingestion stays fail-closed on purpose.
The alert rule for CIRA COMPANY FAILED follows separately (needs monitoring_alerts.tf resource names).
Every edit must match exactly once (or be already applied); otherwise NOTHING is written.
Usage (repo root): python scripts/50-Apply-Per-Company.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_EXPR = ('tuple(c["ticker"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve()'
                 '.parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"])')
RS = ('__import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1]'
      ' / "portfolio-engine" / "run_state.py"))')
ACTIVE = RS + '["active_tickers"]()'


def wrap_try(match, nl, stage, ticker_var, extra_indent="    "):
    """Indent the matched block into try/except that excludes the company and continues."""
    ind = match["ind"]
    body = match.group(0)
    lines = body.split(nl) if nl in body else body.split("\n")
    indented = [(extra_indent + line) if line.strip() else line for line in lines]
    return (f"{ind}try:{nl}" + nl.join(indented) + nl +
            f"{ind}except Exception as exc:  # per-company: exclude and continue{nl}"
            f"{ind}    {RS}[\"exclude\"]({ticker_var}, \"{stage}\", exc){nl}"
            f"{ind}    continue")



# (file, done-marker, regex or None for plain replace-all, replacement-builder, expected count or None)
EDITS = [
    # universe -> active companies in every downstream stage (SEC ingestion keeps the full universe)
    *[(f, "run_state.py", None, (UNIVERSE_EXPR, ACTIVE), None) for f in (
        "scripts/07-Generate-Financial-Reports.py", "scripts/10-Analyze-Financial-Reports.py",
        "scripts/13-Ingest-Market-Prices.py", "scripts/14-Analyze-Market-Prices.py",
        "scripts/16-Refresh-Company-Intelligence.py", "scripts/20-Publish-Versioned-Reports.py",
        "scripts/12-Run-Cloud-Pipeline.py")],

    ("scripts/12-Run-Cloud-Pipeline.py", '["reset"]()',
     r'(?m)^def main\(\):[ \t]*\r?\n(?P<ind>[ \t]+)ingestion = load_ingestion\(\)',
     lambda m, nl: m.group(0) + nl + m["ind"] + RS + '["reset"]()', 1),

    ("scripts/07-Generate-Financial-Reports.py", '"financial-report", "No SEC Company Facts found"',
     r'(?m)^(?P<ind>[ \t]*)if not files:[ \t]*\r?\n[ \t]*raise FileNotFoundError\([ \t]*\r?\n[ \t]*f"No SEC Company Facts found for \{ticker\}"[ \t]*\r?\n[ \t]*\)',
     lambda m, nl: f'{m["ind"]}if not files:{nl}{m["ind"]}    {RS}["exclude"](ticker, "financial-report", "No SEC Company Facts found"){nl}{m["ind"]}    continue', 1),
    ("scripts/07-Generate-Financial-Reports.py", '"financial-report", exc',
     r'(?m)^(?P<ind>[ \t]*)result = module\.extract_annual_metrics\(source\)',
     lambda m, nl: wrap_try(m, nl, "financial-report", "ticker"), 1),

    ("scripts/13-Ingest-Market-Prices.py", '"market-prices", exc',
     r'(?m)^(?P<ind>[ \t]*)failures\.append\(symbol\)[ \t]*(?=\r?\n)',
     lambda m, nl: m.group(0) + nl + m["ind"] + RS + '["exclude"](symbol, "market-prices", exc)', 1),
    ("scripts/13-Ingest-Market-Prices.py", "len(failures) == len(SYMBOLS)",
     r'(?m)^(?P<ind>[ \t]*)if failures:[ \t]*\r?\n(?P<ind2>[ \t]*)print\("\\nFailed symbols:", ", "\.join\(failures\)\)[ \t]*\r?\n[ \t]*return 1',
     lambda m, nl: f'{m["ind"]}if failures:{nl}{m["ind2"]}print("\\nFailed symbols:", ", ".join(failures)){nl}'
                   f'{m["ind"]}if failures and len(failures) == len(SYMBOLS):{nl}{m["ind2"]}return 1', 1),

    ("scripts/14-Analyze-Market-Prices.py", '"market-analysis", exc',
     r'(?ms)^(?P<ind>[ \t]*)path = source / f"\{symbol\}-daily-prices\.json".*?results\[symbol\] = module\.analyze_prices\(document\)',
     lambda m, nl: wrap_try(m, nl, "market-analysis", "symbol"), 1),

    ("scripts/16-Refresh-Company-Intelligence.py", '"company-intelligence", exc',
     r"(?ms)^(?P<ind>[ \t]*)financial = read_json\(.*?reports\[ticker\]\['generated_at_utc'\] = generated_at",
     lambda m, nl: wrap_try(m, nl, "company-intelligence", "ticker"), 1),

    ("scripts/20-Publish-Versioned-Reports.py", '["check_threshold"]()',
     r'(?m)^(?P<ind>[ \t]*)entries = \[\][ \t]*(?=\r?\n)',
     lambda m, nl: (m["ind"] + "excluded = " + RS + '["check_threshold"]()' + nl + m["ind"] + "TICKERS = " + ACTIVE + nl + m.group(0)), 1),
    ("scripts/20-Publish-Versioned-Reports.py", '"excluded": excluded',
     r'(?m)^(?P<ind>[ \t]*)"reports": entries,[ \t]*(?=\r?\n)',
     lambda m, nl: m.group(0) + nl + m["ind"] + '"excluded": excluded,', 1),

    ("dashboard/data.py", "def validate_companies(companies, tickers=TICKERS)",
     r"def validate_companies\(companies\):\r?\n(?P<rest>[ \t]*run_ids = set\(\)\r?\n[ \t]*)for ticker in TICKERS:",
     lambda m, nl: "def validate_companies(companies, tickers=TICKERS):" + nl + m["rest"] + "for ticker in tickers:", 1),
    ("dashboard/data.py", "Unexpected batch company list",
     r"(?m)^(?P<ind>[ \t]*)expected = \{prefix \+ f'company-intelligence/\{t\}-company-intelligence\.json': \(companies, t\) for t in TICKERS\}[ \t]*\r?\n[ \t]*expected\.update\(\{prefix \+ f'market-data/\{t\}-daily-prices\.json': \(prices, t\) for t in TICKERS\}\)",
     lambda m, nl: (f"{m['ind']}present = [entry.get('ticker') for entry in manifest.get('reports', [])]{nl}"
                    f"{m['ind']}if not present or len(set(present)) != len(present) or not set(present) <= set(TICKERS):{nl}"
                    f"{m['ind']}    raise ValueError('Unexpected batch company list'){nl}"
                    f"{m['ind']}expected = {{prefix + f'company-intelligence/{{t}}-company-intelligence.json': (companies, t) for t in present}}{nl}"
                    f"{m['ind']}expected.update({{prefix + f'market-data/{{t}}-daily-prices.json': (prices, t) for t in present}})"), 1),
    ("dashboard/data.py", "report_count') != len(manifest.get('reports', []))",
     r"manifest\.get\('report_count'\) != len\(TICKERS\)",
     lambda m, nl: "manifest.get('report_count') != len(manifest.get('reports', []))", 1),
    ("dashboard/data.py", "validate_companies(companies, present)",
     r"(?m)^(?P<ind>[ \t]*)validate_companies\(companies\)(?=[ \t]*\r?\n[ \t]*if any\(r\['run_id'\] != manifest\['run_id'\])",
     lambda m, nl: m["ind"] + "validate_companies(companies, present)", 1),
    ("dashboard/data.py", "'excluded': manifest.get('excluded') or {}",
     r"'source': 'Azure verified batch', 'batch_id': batch\}",
     lambda m, nl: "'source': 'Azure verified batch', 'batch_id': batch, 'excluded': manifest.get('excluded') or {}}", 1),

    ("dashboard/app.py", "st.selectbox('Company', list(data['companies']))",
     r"st\.selectbox\('Company', TICKERS\)", lambda m, nl: "st.selectbox('Company', list(data['companies']))", 1),
    ("dashboard/app.py", "zip(list(data['companies'])",
     r"zip\(TICKERS, \[col for row in \[st\.columns\(4\) for _ in range\(\(len\(TICKERS\) \+ 3\) // 4\)\] for col in row\]\)",
     lambda m, nl: "zip(list(data['companies']), [col for row in [st.columns(4) for _ in range((len(data['companies']) + 3) // 4)] for col in row])", 1),
    ("dashboard/app.py", "Not in this batch",
     r"(?m)^(?P<ind>[ \t]*)st\.caption\(f\"\{data\['source'\]\}[^\r\n]*\)[ \t]*(?=\r?\n)",
     lambda m, nl: (m.group(0) + nl + m["ind"] + "if data.get('excluded'):" + nl + m["ind"] +
                    "    st.warning('Not in this batch: ' + '; '.join(f\"{t} ({v.get('stage')}: {v.get('reason')})\" for t, v in data['excluded'].items()))"), 1),
]


def main():
    if not (ROOT / "portfolio-engine" / "run_state.py").is_file():
        sys.exit("portfolio-engine/run_state.py missing - extract CIRA-PerCompany.zip first. Nothing written.")
    texts, problems, applied = {}, [], []
    for rel, marker, pattern, build, expected in EDITS:
        if rel not in texts:
            texts[rel] = (ROOT / rel).read_bytes().decode("utf-8")
        text = texts[rel]
        nl = "\r\n" if "\r\n" in text else "\n"
        if marker in text and pattern is not None:
            continue
        if pattern is None:
            old, new = build
            count = text.count(old)
            if count == 0:
                if new in text:
                    continue
                problems.append(f"{rel}: universe expression not found")
                continue
            texts[rel] = text.replace(old, new)
            applied.append(f"{rel}: active companies ({count}x)")
            continue
        hits = list(re.finditer(pattern, text))
        if len(hits) != expected:
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
        if text != (ROOT / rel).read_bytes().decode("utf-8"):
            (ROOT / rel).write_bytes(text.encode("utf-8"))
    print(f"Applied {len(applied)} edit(s):" if applied else "All edits already applied.")
    for a in applied:
        print("  ", a)


if __name__ == "__main__":
    main()
