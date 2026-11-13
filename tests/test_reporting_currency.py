import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v52 = load("cira_v52", "scripts/52-Verify-Universe-Batch.py")
fp = load("cira_fp_rc", "portfolio-engine/financial_processor.py")


def year(unit, y):
    return {"val": 1, "start": f"{y}-01-01", "end": f"{y}-12-31", "form": "20-F"}


def test_cny_reporter_with_usd_convenience_translation_detected_as_cny():
    doc = {"facts": {"us-gaap": {"Revenues": {"units": {
        "CNY": [year("CNY", y) for y in range(2012, 2026)],
        "USD": [year("USD", 2025)]}}}}}
    assert v52.detect_currency(doc, fp) == "CNY"


def test_usd_reporter_detected_as_usd():
    doc = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [year("USD", y) for y in range(2018, 2026)]}}}}}
    assert v52.detect_currency(doc, fp) == "USD"


def test_universe_currencies_are_known():
    import json
    for c in json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]:
        assert c.get("reporting_currency", "USD") in ("USD", "EUR", "CNY"), c["ticker"]
