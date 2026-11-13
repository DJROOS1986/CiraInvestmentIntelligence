"""Currency conversion: flows at the fiscal-period average rate, balances at the closing rate (fixed test rates)."""
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fp = load("cira_fp_fx", "portfolio-engine/financial_processor.py")
fxmod = load("cira_fx_test", "portfolio-engine/fx.py")
ci = load("cira_ci_fx", "portfolio-engine/company_intelligence.py")


class FixedFx:
    source = "test rates"

    def average(self, ccy, start, end):
        assert (ccy, start, end) == ("EUR", "2025-01-01", "2025-12-31")
        return 1.13

    def closing(self, ccy, on):
        assert (ccy, on) == ("EUR", "2025-12-31")
        return 1.175


def eur_facts():
    d = lambda v: {"EUR": [{"val": v, "start": "2025-01-01", "end": "2025-12-31", "form": "20-F", "fp": "FY", "filed": "2026-02-25", "accn": "a"}]}
    i = lambda v: {"EUR": [{"val": v, "end": "2025-12-31", "form": "20-F", "fp": "FY", "filed": "2026-02-25", "accn": "a"}]}
    return {"RevenueFromContractWithCustomerExcludingAssessedTax": d(1000), "NetIncomeLoss": d(200), "Assets": i(2000),
            "Liabilities": i(800), "NetCashProvidedByUsedInOperatingActivities": d(300), "PaymentsToAcquirePropertyPlantAndEquipment": d(100),
            "Revenues": {"USD": [{"val": 999999, "start": "2025-01-01", "end": "2025-12-31", "form": "20-F", "filed": "2026-02-25", "accn": "x"}]}}


def run(facts, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "facts.json"
        path.write_text(json.dumps({"cik": 1, "entityName": "T", "facts": {"us-gaap": {k: {"units": v} for k, v in facts.items()}}}))
        return fp.extract_annual_metrics(path, **kwargs)


def test_eur_flows_at_average_and_balances_at_closing_rate():
    result = run(eur_facts(), currency="EUR", fx=FixedFx())
    m = result["metrics_usd"]
    assert m["revenue"] == pytest.approx(1130) and m["net_income"] == pytest.approx(226)
    assert m["total_assets"] == pytest.approx(2350) and m["total_liabilities"] == pytest.approx(940)
    assert m["free_cash_flow"] == pytest.approx((300 - 100) * 1.13)
    assert result["reported_currency"] == "EUR" and result["reported_metrics"]["revenue"] == 1000
    assert result["fx"]["rates"]["revenue"] == {"usd_per_unit": 1.13, "basis": "average"}
    assert result["fx"]["rates"]["total_assets"] == {"usd_per_unit": 1.175, "basis": "closing"}


def test_stray_usd_values_ignored_for_eur_reporter():
    assert run(eur_facts(), currency="EUR", fx=FixedFx())["provenance"]["revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_conversion_refused_without_rates():
    with pytest.raises(ValueError, match="Exchange rates required"):
        run(eur_facts(), currency="EUR")


def test_usd_reporter_unchanged():
    facts = {k: {"USD": v["EUR"]} for k, v in eur_facts().items() if "EUR" in v}
    result = run(facts)
    assert result["metrics_usd"]["revenue"] == 1000 and result["fx"] is None and result["reported_currency"] == "USD"


def test_ecb_cross_rate_and_closing():
    data = {"USD": {"2025-12-30": 1.20, "2025-12-31": 1.18}, "CNY": {"2025-12-30": 8.0, "2025-12-31": 8.26}}
    rates = fxmod.EcbRates(fetch=lambda ccy, start, end: {d: v for d, v in data[ccy].items() if start <= d <= end})
    assert rates.average("CNY", "2025-12-30", "2025-12-31") == pytest.approx((1.20 / 8.0 + 1.18 / 8.26) / 2)
    assert rates.closing("CNY", "2025-12-31") == pytest.approx(1.18 / 8.26)
    assert rates.closing("EUR", "2026-01-01") == pytest.approx(1.18)  # last rate on or before the date
    with pytest.raises(ValueError):
        rates.average("CNY", "2024-01-01", "2024-12-31")


def test_conversion_note_in_data_quality():
    financial = {"period_end": "2025-12-31", "metrics_usd": {k: 1 for k in ("revenue", "net_income", "total_assets", "total_liabilities", "operating_cash_flow", "capital_expenditure")},
                 "provenance": {}, "fx": {"source": "ECB", "currency": "EUR", "rates": {"revenue": {"usd_per_unit": 1.13}, "total_assets": {"usd_per_unit": 1.175}}}}
    notes = ci.provenance_warnings(financial)
    assert any("Financials converted from EUR to USD" in n and "1.1300" in n and "1.1750 at 2025-12-31" in n for n in notes)
