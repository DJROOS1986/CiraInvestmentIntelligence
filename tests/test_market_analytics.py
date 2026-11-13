"""Unit tests for CIRA market analytics."""

import importlib.util
from pathlib import Path
import unittest

import pytest


ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "market_analytics",
    ROOT / "portfolio-engine" / "market_analytics.py",
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample_document(closes):
    return {
        "symbol": "TEST",
        "currency": "USD",
        "records": [
            {
                "date": f"2026-10-{i + 1:02d}",
                "close": price,
            }
            for i, price in enumerate(closes)
        ],
    }


class MarketAnalyticsTests(unittest.TestCase):

    def test_daily_return(self):
        result = module.analyze_prices(
            sample_document([100, 110])
        )
        self.assertAlmostEqual(
            result["daily_return_pct"], 10.0
        )

    def test_five_day_average(self):
        result = module.analyze_prices(
            sample_document([29, 29.5, 30, 30.5, 31])
        )
        self.assertEqual(result["sma_5"], 30.0)

    def test_twenty_day_average(self):
        result = module.analyze_prices(
            sample_document([8.6 + 0.2 * i for i in range(20)])
        )
        self.assertEqual(result["sma_20"], 10.5)

    def test_insufficient_data_for_sma(self):
        result = module.analyze_prices(
            sample_document([100, 110])
        )
        self.assertIsNone(result["sma_5"])
        self.assertIsNone(result["sma_20"])

    def test_constant_prices_zero_volatility(self):
        result = module.analyze_prices(
            sample_document([100, 100, 100])
        )
        self.assertEqual(
            result["annualized_volatility_pct"], 0.0
        )

    def test_reject_invalid_prices(self):
        with self.assertRaises(ValueError):
            module.analyze_prices(
                sample_document([100, -10])
            )


if __name__ == "__main__":
    unittest.main()

def test_volatility_sample_formula_and_short_history_status():
    import math
    import statistics
    result = module.analyze_prices(sample_document([100, 110, 99, 105]))
    expected = statistics.stdev([0.1, -0.1, 105 / 99 - 1]) * math.sqrt(252) * 100
    assert abs(result['annualized_volatility_pct'] - expected) < 0.0001
    assert result['quality']['return_observations'] == 3
    assert result['quality']['volatility_status'].startswith('low confidence')


@pytest.mark.parametrize('closes', [[100, 102, 51, 52], [100, 102, 103, 104]])
def test_split_withholds_artificial_returns_even_if_close_already_adjusted(closes):
    doc = sample_document(closes)
    doc['corporate_actions'] = {'splits': [{'date': '2026-10-03', 'numerator': 2, 'denominator': 1}]}
    result = module.analyze_prices(doc)
    assert result['period_price_change_pct'] is None and result['annualized_volatility_pct'] is None
    assert result['daily_return_pct'] is None and result['sma_5'] is None
    assert result['latest_close'] == closes[-1]
    assert result['quality']['split_dates'] == ['2026-10-03']


def test_unverified_adjusted_document_cannot_enable_adjusted_returns():
    import pytest
    doc = sample_document([100, 101])
    doc['price_type'] = 'adjusted'
    doc['records'][0]['provider_adjusted_close'] = 50
    with pytest.raises(ValueError, match='methodology'):
        module.analyze_prices(doc)


def test_adjustment_candidates_and_dividends_do_not_change_close_basis():
    doc = sample_document([100, 102, 101])
    for row in doc['records']:
        row['provider_adjusted_close'] = 10
    doc['corporate_actions'] = {'dividends': [{'date': '2026-10-02', 'amount': 1}]}
    result = module.analyze_prices(doc)
    assert result['period_price_change_pct'] == 1
    assert result['return_basis'] == 'unadjusted_close'


def test_long_missing_observation_gap_is_not_a_daily_return():
    doc = sample_document([100, 101, 102])
    doc['records'][-1]['date'] = '2026-10-15'
    result = module.analyze_prices(doc)
    assert result['annualized_volatility_pct'] is None and result['daily_return_pct'] is None
    assert result['period_price_change_pct'] == 2
    assert result['quality']['long_gap_count'] == 1


def test_year_history_counts_actual_observations():
    from datetime import date, timedelta
    doc = {'symbol': 'TEST', 'price_type': 'unadjusted', 'records': []}
    day = date(2025, 1, 1)
    while len(doc['records']) < 253:
        if day.weekday() < 5:
            doc['records'].append({'date': day.isoformat(), 'close': 100 + len(doc['records']) / 10})
        day += timedelta(days=1)
    result = module.analyze_prices(doc)
    assert result['quality']['return_observations'] == 252
    assert result['quality']['volatility_status'] == 'descriptive estimate'
    assert result['sma_20'] is not None


@pytest.mark.parametrize('dates', [
    ['2026-10-05', '2026-10-06', '2026-10-08'],  # unobserved Wednesday
    ['2026-11-24', '2026-11-25', '2026-11-27'],  # possible holiday; no verified calendar
])
def test_uncertain_weekday_gap_withholds_daily_and_volatility(dates):
    doc = sample_document([100, 101, 110])
    for row, stamp in zip(doc['records'], dates):
        row['date'] = stamp
    result = module.analyze_prices(doc)
    assert result['daily_return_pct'] is None
    assert result['annualized_volatility_pct'] is None
    assert result['period_price_change_pct'] == 10
    assert result['quality']['continuity_status'] == 'uncertain'
    assert result['quality']['uncertain_interval_count'] == 1
    assert any('holidays or missing sessions' in w for w in result['quality_warnings'])


def test_normal_weekend_gap_preserves_daily_volatility_formula():
    import statistics
    import math
    doc = sample_document([100, 102, 101])
    for row, stamp in zip(doc['records'], ['2026-10-08', '2026-10-09', '2026-10-12']):
        row['date'] = stamp
    result = module.analyze_prices(doc)
    assert result['daily_return_pct'] == round((101 / 102 - 1) * 100, 4)
    assert result['annualized_volatility_pct'] == round(statistics.stdev([0.02, 101 / 102 - 1]) * math.sqrt(252) * 100, 4)
    assert result['quality']['uncertain_interval_count'] == 0
    assert result['quality']['volatility_status'].startswith('low confidence')


def test_earlier_gap_withholds_volatility_but_not_latest_consecutive_return():
    doc = sample_document([100, 110, 111])
    for row, stamp in zip(doc['records'], ['2026-10-05', '2026-10-07', '2026-10-08']):
        row['date'] = stamp
    result = module.analyze_prices(doc)
    assert result['annualized_volatility_pct'] is None
    assert result['daily_return_pct'] == round((111 / 110 - 1) * 100, 4)
    assert result['quality']['return_observations'] == 2


def test_two_observations_keep_return_but_withhold_volatility():
    result = module.analyze_prices(sample_document([100, 101]))
    assert result['daily_return_pct'] == 1
    assert result['annualized_volatility_pct'] is None
    assert result['quality']['volatility_available'] is False


@pytest.mark.parametrize('known_split', [False, True])
@pytest.mark.parametrize('event_day,expected_5,expected_20', [(6, 50, 50), (10, 50, None), (24, None, None)])
def test_moving_averages_only_suppress_windows_crossing_discontinuity(known_split, event_day, expected_5, expected_20):
    doc = sample_document([100 if day < event_day else 50 for day in range(1, 26)])
    if known_split:
        doc['corporate_actions'] = {'splits': [{'date': f'2026-10-{event_day:02d}'}]}
    result = module.analyze_prices(doc)
    assert result['sma_5'] == expected_5
    assert result['sma_20'] == expected_20
    assert result['period_price_change_pct'] is None
    assert result['quality']['moving_average_status']['5'].startswith('available' if expected_5 else 'unavailable')


def test_suspicious_upward_move_also_withholds_crossing_average():
    result = module.analyze_prices(sample_document([50, 50, 100, 100, 100]))
    assert result['sma_5'] is None
    assert result['quality']['extreme_move_dates'] == ['2026-10-03']
