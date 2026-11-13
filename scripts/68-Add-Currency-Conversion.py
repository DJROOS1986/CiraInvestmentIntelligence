"""Currency conversion for non-USD financial statements (one-off, idempotent, all-or-nothing).

financial_processor.py  reads a company's reporting currency and converts to USD with portfolio-engine/fx.py
                        (flows: fiscal-period average rate; balances: closing rate); keeps reported figures + rates
stage 07                passes reporting_currency from config/universe.json (default USD) and an ECB rate provider
company_intelligence    data-quality note with currency, source and rates
scripts/52              detects the reporting currency and proposes it as reporting_currency
Usage (repo root): python scripts/68-Add-Currency-Conversion.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = r"[ \t]*\r?\n"

FP_CONVERT = '''{i}reported, fx_info = None, None
{i}if currency != "USD":
{i}    if fx is None:
{i}        raise ValueError(f"Exchange rates required to convert {{currency}} financials")
{i}    reported, rates = dict(results), {{}}
{i}    for metric, value in list(results.items()):
{i}        if value is None:
{i}            continue
{i}        prov = provenance.get(metric) or {{}}
{i}        if metric in INSTANT:
{i}            rate, basis = fx.closing(currency, period_end), "closing"
{i}        else:
{i}            if not prov.get("start"):
{i}                raise ValueError(f"Missing period start for {{metric}}")
{i}            rate, basis = fx.average(currency, prov["start"], prov.get("period_end") or period_end), "average"
{i}        results[metric] = value * rate
{i}        rates[metric] = {{"usd_per_unit": rate, "basis": basis}}
{i}    fx_info = {{"source": fx.source, "currency": currency, "rates": rates}}

'''

STAGE07_HELPER = '''_FX = None


def _fx_args(ticker):
    """Reporting currency from config/universe.json (default USD) and a shared ECB rate provider."""
    global _FX
    companies = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]
    currency = next((c.get("reporting_currency", "USD") for c in companies if c["ticker"] == ticker), "USD")
    if currency == "USD":
        return {}
    if _FX is None:
        fx_spec = importlib.util.spec_from_file_location("cira_fx", ROOT / "portfolio-engine" / "fx.py")
        fx_module = importlib.util.module_from_spec(fx_spec)
        fx_spec.loader.exec_module(fx_module)
        _FX = fx_module.EcbRates()
    return {"currency": currency, "fx": _FX}


'''

V52_HELPERS = '''def detect_currency(doc, fp):
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


'''

EDITS = [
    ("portfolio-engine/financial_processor.py", "def extract_annual_metrics(companyfacts_path, currency=",
     r"def extract_annual_metrics\(companyfacts_path\):", lambda m, nl: 'def extract_annual_metrics(companyfacts_path, currency="USD", fx=None):', 1),
    ("portfolio-engine/financial_processor.py", "# reporting currency",
     r'\)\.get\("USD", \[\]\)(?=\r?\n[ \t]*\r?\n[ \t]*for item in values:)', lambda m, nl: ').get(currency, [])  # reporting currency', 1),
    ("portfolio-engine/financial_processor.py", "def _instant_value(facts, tag, period_end, currency=",
     r"def _instant_value\(facts, tag, period_end\):", lambda m, nl: 'def _instant_value(facts, tag, period_end, currency="USD"):', 1),
    ("portfolio-engine/financial_processor.py", "# instant currency",
     r'units", \{\}\)\.get\("USD", \[\]\):', lambda m, nl: 'units", {}).get(currency, []):  # instant currency', 1),
    ("portfolio-engine/financial_processor.py", "def derive_total_liabilities(facts, period_end, currency=",
     r"def derive_total_liabilities\(facts, period_end\):", lambda m, nl: 'def derive_total_liabilities(facts, period_end, currency="USD"):', 1),
    ("portfolio-engine/financial_processor.py", '"LiabilitiesCurrent", period_end, currency)',
     r'_instant_value\(facts, (?P<tag>"[A-Za-z]+"|equity_tag), period_end\)',
     lambda m, nl: f'_instant_value(facts, {m["tag"]}, period_end, currency)', None),
    ("portfolio-engine/financial_processor.py", "derive_total_liabilities(facts, period_end, currency)",
     r"derive_total_liabilities\(facts, period_end\)(?!:)", lambda m, nl: "derive_total_liabilities(facts, period_end, currency)", 1),
    ("portfolio-engine/financial_processor.py", "reported, fx_info = None, None",
     r"(?m)^(?P<ind>[ \t]*)ocf = results\[\"operating_cash_flow\"\]",
     lambda m, nl: FP_CONVERT.format(i=m["ind"]).replace("\n", nl) + m.group(0), 1),
    ("portfolio-engine/financial_processor.py", '"reported_currency": currency,',
     r'(?m)^(?P<ind>[ \t]*)"metrics_usd": results,[ \t]*(?=\r?\n)',
     lambda m, nl: (m.group(0) + nl + m["ind"] + '"reported_currency": currency,' + nl + m["ind"] + '"reported_metrics": reported,'
                    + nl + m["ind"] + '"fx": fx_info,'), 1),

    ("scripts/07-Generate-Financial-Reports.py", "def _fx_args(ticker):",
     r"(?m)^def main\(\):", lambda m, nl: STAGE07_HELPER.replace("\n", nl) + m.group(0), 1),
    ("scripts/07-Generate-Financial-Reports.py", "extract_annual_metrics(source, **_fx_args(ticker))",
     r"module\.extract_annual_metrics\(source\)", lambda m, nl: "module.extract_annual_metrics(source, **_fx_args(ticker))", 1),

    ("portfolio-engine/company_intelligence.py", "Financials converted from",
     r"(?m)^(?P<ind>[ \t]*)out = \[\][ \t]*\r?\n(?=[ \t]*for key in \('revenue', 'net_income')",
     lambda m, nl: (m.group(0) + m["ind"] + "fx = financial.get('fx')" + nl + m["ind"] + "if isinstance(fx, dict) and fx.get('rates'):" + nl
                    + m["ind"] + "    rates = fx['rates']" + nl
                    + m["ind"] + "    avg = (rates.get('revenue') or {}).get('usd_per_unit')" + nl
                    + m["ind"] + "    close = (rates.get('total_assets') or {}).get('usd_per_unit')" + nl
                    + m["ind"] + "    parts = ([f'average rate {avg:.4f} for flows'] if avg else []) + ([f\"closing rate {close:.4f} at {financial.get('period_end')}\"] if close else [])" + nl
                    + m["ind"] + "    out.append(f\"Financials converted from {fx.get('currency')} to USD ({fx.get('source')}): \" + ', '.join(parts))" + nl), 1),

    ("scripts/52-Verify-Universe-Batch.py", "def detect_currency(doc, fp):",
     r"(?m)^def main\(\):", lambda m, nl: V52_HELPERS.replace("\n", nl) + m.group(0), 1),
    ("scripts/52-Verify-Universe-Batch.py", "currency = detect_currency(",
     r"(?m)^(?P<ind>[ \t]*)result = fp\.extract_annual_metrics\(path\)[ \t]*(?=\r?\n)",
     lambda m, nl: (f'{m["ind"]}currency = "USD"{nl}{m["ind"]}try:{nl}{m["ind"]}    result = fp.extract_annual_metrics(path){nl}'
                    f'{m["ind"]}except ValueError:{nl}{m["ind"]}    currency = detect_currency(json.loads(facts), fp){nl}'
                    f'{m["ind"]}    if currency in (None, "USD"):{nl}{m["ind"]}        raise{nl}'
                    f'{m["ind"]}    result = fp.extract_annual_metrics(path, currency=currency, fx=load_fx().EcbRates()){nl}'
                    f'{m["ind"]}    out["fallbacks"].append(f"converted from {{currency}}")'), 1),
    ("scripts/52-Verify-Universe-Batch.py", '"reporting_currency": currency,',
     r'"bcg_required": True, "annual_form": out\["form"\]\.split\(\)\[0\],',
     lambda m, nl: '"bcg_required": True, "annual_form": out["form"].split()[0], "reporting_currency": currency,', 1),
]


def main():
    if not (ROOT / "portfolio-engine" / "fx.py").is_file():
        sys.exit("portfolio-engine/fx.py missing - extract CIRA-FX.zip first. Nothing written.")
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
        applied.append(f"{rel}: {marker[:45]} ({len(hits)}x)")
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
