import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "portfolio-engine" / "company_intelligence.py"

spec = importlib.util.spec_from_file_location(
    "company_intelligence", PATH
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestCompanyIntelligence(unittest.TestCase):

    def setUp(self):
        self.financial = {
            "ticker": "MSFT",
            "company": "Microsoft",
            "period_end": "2026-06-30",
            "currency": "USD",
            "metrics_usd": {
                "revenue": 100,
                "net_income": 20,
                "free_cash_flow": 15,
            },
            "provenance": {},
        }
        self.prices = {
            "symbol": "MSFT",
            "currency": "USD",
            "price_type": "unadjusted",
            "records": [
                {"date": "2026-11-05", "close": 100},
                {"date": "2026-11-06", "close": 101},
            ],
        }
        self.market = {
            "symbol": "MSFT",
            "provider": "Yahoo Finance chart endpoint",
            "currency": "USD",
            "price_type": "unadjusted",
            "observations": 2,
            "last_date": "2026-11-06",
            "latest_close": 101,
        }
        self.bcg = {
            "ticker": "MSFT",
            "research_available": True,
            "status": "Research only - verification required",
            "research_score": 74,
            "verified_bcg_class": None,
        }

    def build(self):
        return module.build_company_intelligence(
            "MSFT",
            self.financial,
            self.prices,
            self.market,
            self.bcg,
        )

    def test_success(self):
        self.assertEqual(self.build()["ticker"], "MSFT")

    def test_financial_metrics(self):
        self.assertEqual(
            self.build()["financial"]["metrics_usd"]["revenue"], 100
        )

    def test_market_indicators(self):
        self.assertEqual(
            self.build()["market"]["indicators"]["latest_close"], 101
        )

    def test_bcg_uncertainty(self):
        self.assertFalse(
            self.build()["data_quality"]["independently_verified_bcg"]
        )

    def test_no_recommendation(self):
        self.assertIsNone(
            self.build()["data_quality"]["investment_recommendation"]
        )

    def test_ticker_mismatch(self):
        self.prices["symbol"] = "AAPL"
        with self.assertRaises(ValueError):
            self.build()

    def test_observation_mismatch(self):
        self.market["observations"] = 10
        with self.assertRaises(ValueError):
            self.build()


if __name__ == "__main__":
    unittest.main()

def test_financial_provenance_fx_and_market_quality_survive_combination():
    case = TestCompanyIntelligence()
    case.setUp()
    case.financial.update(cik=123, reported_currency='EUR', reported_metrics={'revenue': 90},
        fx={'source': 'fixed test rates', 'currency': 'EUR', 'rates': {'revenue': {'usd_per_unit': 1.1}}},
        source={'sha256': 'test-source-hash', 'retrieved_at_utc': None})
    case.financial['provenance'] = {'revenue': {'form': '20-F', 'unit': 'EUR',
        'filed': '2026-08-01', 'accession': 'test-accession'}}
    case.market['quality'] = {'volatility_status': 'low confidence: fewer than 60 returns'}
    case.prices['source_metadata'] = {'rejected_observations': 2}
    result = case.build()
    assert result['financial']['reported_metrics']['revenue'] == 90
    assert result['financial']['fx'] == case.financial['fx']
    assert result['financial']['source_metadata']['sha256'] == 'test-source-hash'
    assert result['financial']['filing_dates'] == ['2026-08-01']
    assert result['financial']['metrics_usd']['revenue'] == 100
    assert result['market']['source_metadata']['rejected_observations'] == 2
    assert result['market']['quality'] == case.market['quality']


def test_filing_after_market_date_and_currency_mismatch_disclosed():
    case = TestCompanyIntelligence()
    case.setUp()
    case.financial['provenance'] = {'revenue': {'filed': '2026-11-07'}}
    case.prices['currency'] = case.market['currency'] = 'EUR'
    result = case.build()
    assert result['data_quality']['filings_not_later_than_market'] is False
    assert any('postdates' in w for w in result['data_quality']['warnings'])
    assert any('currencies differ' in w for w in result['data_quality']['warnings'])


def test_adjusted_label_alone_does_not_remove_limitation_warning():
    case = TestCompanyIntelligence()
    case.setUp()
    case.prices['price_type'] = case.market['price_type'] = 'adjusted'
    result = case.build()
    assert any('exclude dividends' in w for w in result['data_quality']['warnings'])
