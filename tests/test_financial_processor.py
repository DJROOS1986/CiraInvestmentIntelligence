import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = ROOT / "portfolio-engine" / "financial_processor.py"

spec = importlib.util.spec_from_file_location(
    "financial_processor", PROCESSOR
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_fact(value, end, start=None, filed="2026-11-03"):
    fact = {
        "val": value,
        "end": end,
        "filed": filed,
        "form": "10-K",
        "fp": "FY",
        "fy": 2026,
    }
    if start is not None:
        fact["start"] = start
    return fact


def test_annual_metrics_and_free_cash_flow(tmp_path):
    end = "2026-09-26"
    start = "2025-09-28"

    values = {
        "RevenueFromContractWithCustomerExcludingAssessedTax":
            make_fact(478834, end, start),
        "NetIncomeLoss": make_fact(132175, end, start),
        "Assets": make_fact(404548, end),
        "Liabilities": make_fact(292455, end),
        "NetCashProvidedByUsedInOperatingActivities":
            make_fact(145097, end, start),
        "PaymentsToAcquirePropertyPlantAndEquipment":
            make_fact(9041, end, start),
    }

    payload = {
        "entityName": "Test Company",
        "cik": 123456,
        "facts": {
            "us-gaap": {
                tag: {"units": {"USD": [fact]}}
                for tag, fact in values.items()
            }
        },
    }

    path = tmp_path / "companyfacts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = module.extract_annual_metrics(path)
    metrics = result["metrics_usd"]

    assert result["period_end"] == end
    assert metrics["revenue"] == 478834
    assert metrics["net_income"] == 132175
    assert metrics["total_assets"] == 404548
    assert metrics["total_liabilities"] == 292455
    assert metrics["operating_cash_flow"] == 145097
    assert metrics["capital_expenditure"] == 9041
    assert metrics["free_cash_flow"] == 136056


def test_missing_capex_returns_null_fcf(tmp_path):
    end = "2026-09-26"
    start = "2025-09-28"

    payload = {
        "entityName": "Test Company",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [make_fact(1000, end, start)]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [make_fact(500, end, start)]
                    }
                },
            }
        },
    }

    path = tmp_path / "missing_capex.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = module.extract_annual_metrics(path)

    assert result["metrics_usd"]["capital_expenditure"] is None
    assert result["metrics_usd"]["free_cash_flow"] is None


def test_missing_revenue_raises_error(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"facts": {"us-gaap": {}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="annual revenue"):
        module.extract_annual_metrics(path)


def test_comparative_year_selection(tmp_path):
    current = make_fact(
        2000, "2026-09-26", "2025-09-28"
    )
    previous = make_fact(
        1000, "2025-09-27", "2024-09-29"
    )

    payload = {
        "entityName": "Comparative Test Company",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [previous, current]
                    }
                }
            }
        },
    }

    path = tmp_path / "comparatives.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = module.extract_annual_metrics(path)

    assert result["period_end"] == "2026-09-26"
    assert result["metrics_usd"]["revenue"] == 2000


def test_latest_filing_selected(tmp_path):
    original = make_fact(
        1000, "2026-09-26", "2025-09-28",
        filed="2026-10-30"
    )
    restated = make_fact(
        1100, "2026-09-26", "2025-09-28",
        filed="2026-11-03"
    )

    payload = {
        "entityName": "Restatement Test Company",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [original, restated]
                    }
                }
            }
        },
    }

    path = tmp_path / "restated.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = module.extract_annual_metrics(path)

    assert result["metrics_usd"]["revenue"] == 1100
    assert result["provenance"]["revenue"]["filed"] == "2026-11-03"


@pytest.mark.parametrize('form', ['10-K', '10-K/A', '20-F', '20-F/A'])
def test_filing_metadata_units_and_source_hash(tmp_path, form):
    import hashlib
    fact = dict(make_fact(1234567, '2025-12-31', '2025-01-01', '2026-02-01'),
                form=form, accn='0000123456-26-000001')
    doc = {'cik': 123456, 'facts': {'us-gaap': {'Revenues': {'units': {'USD': [fact, dict(fact)]}}}}}
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps(doc))
    result = module.extract_annual_metrics(path)
    p = result['provenance']['revenue']
    assert p['form'] == form and p['unit'] == 'USD' and p['scale'] == 1
    assert p['filed'] == '2026-02-01' and p['period_type'] == 'duration'
    assert p['filing_url'] == 'https://www.sec.gov/Archives/edgar/data/123456/000012345626000001/'
    assert result['metrics_usd']['revenue'] == 1234567  # no implicit millions scaling or duplicate sum
    assert result['source']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['provenance']['free_cash_flow']['available'] is False


def test_conflicting_duplicate_financial_facts_rejected(tmp_path):
    a = make_fact(100, '2025-12-31', '2025-01-01')
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps({'facts': {'us-gaap': {'Revenues': {'units': {'USD': [a, dict(a, val=200)]}}}}}))
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        module.extract_annual_metrics(path)


def test_inconsistent_flow_periods_disclosed_without_changing_values(tmp_path):
    revenue = make_fact(100, '2025-12-31', '2025-01-01')
    income = make_fact(20, '2025-12-31', '2024-12-20')
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps({'facts': {'us-gaap': {
        'Revenues': {'units': {'USD': [revenue]}}, 'NetIncomeLoss': {'units': {'USD': [income]}}}}}))
    result = module.extract_annual_metrics(path)
    assert result['metrics_usd']['net_income'] == 20
    assert any('start dates differ' in w for w in result['quality_warnings'])


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), '100'])
def test_invalid_financial_values_rejected(tmp_path, value):
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps({'facts': {'us-gaap': {'Revenues': {'units': {'USD': [
        make_fact(value, '2025-12-31', '2025-01-01')]}}}}}))
    with pytest.raises(ValueError, match='Invalid reported financial'):
        module.extract_annual_metrics(path)
