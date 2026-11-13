"""Tests for CIRA market-data normalization."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location(
    "market_data",
    ROOT / "ingestion" / "market_data.py",
)

market_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(market_data)


class MarketDataTests(unittest.TestCase):

    def test_valid_daily_prices(self):
        records = [{
            "date": "2026-11-06",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1000000,
        }]

        result = market_data.normalize_daily_prices(
            "aapl", records
        )

        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertEqual(result[0]["close"], 105.0)

    def test_invalid_price_range(self):
        records = [{
            "date": "2026-11-06",
            "open": 100,
            "high": 90,
            "low": 95,
            "close": 105,
            "volume": 1000,
        }]

        with self.assertRaises(ValueError):
            market_data.normalize_daily_prices(
                "AAPL", records
            )

    def test_duplicate_dates(self):
        record = {
            "date": "2026-11-06",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1000,
        }

        with self.assertRaises(ValueError):
            market_data.normalize_daily_prices(
                "AAPL", [record, record]
            )

    def test_invalid_volume(self):
        record = {
            "date": "2026-11-06",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": -1,
        }

        with self.assertRaises(ValueError):
            market_data.normalize_daily_prices(
                "AAPL", [record]
            )


if __name__ == "__main__":
    unittest.main()

CHART_AS_OF = __import__('datetime').datetime(2026, 11, 13, tzinfo=__import__('datetime').timezone.utc)


def chart_fixture():
    return {'chart': {'result': [{
        'meta': {'symbol': 'TEST', 'currency': 'EUR', 'exchangeTimezoneName': 'UTC', 'exchangeName': 'TEST'},
        'timestamp': [1767272400, 1767358800, 1767618000],
        'indicators': {'quote': [{'open': [100, 101, 102], 'high': [101, 102, 103],
            'low': [99, 100, 101], 'close': [100, 101, 102], 'volume': [10, 20, 30]}],
            'adjclose': [{'adjclose': [98, 99, 100]}]},
        'events': {'dividends': {'one': {'date': 1767358800, 'amount': 1.0}}},
    }]}}


def test_chart_currency_adjustment_candidates_and_dividends():
    result = market_data.normalize_yahoo_chart('TEST', chart_fixture(), now=CHART_AS_OF)
    assert result['currency'] == 'EUR'
    assert result['records'][0]['close'] == 100
    assert result['records'][0]['provider_adjusted_close'] == 98
    assert result['price_type'] == 'unadjusted' and result['adjustment']['total_return'] is False
    assert result['adjustment']['candidate_complete'] is True
    assert result['corporate_actions']['dividends'][0]['amount'] == 1
    assert result['corporate_actions']['coverage'] == 'unverified'


def test_chart_rejections_and_invalid_adjustment_candidate():
    payload = chart_fixture()
    result = payload['chart']['result'][0]
    result['indicators']['quote'][0]['close'][1] = None
    result['indicators']['adjclose'][0]['adjclose'][1] = None
    result['indicators']['adjclose'][0]['adjclose'][2] = -1
    doc = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert len(doc['records']) == 2
    assert doc['source_metadata']['rejected_observations'] == 1
    assert doc['adjustment']['invalid_candidate_observations'] == 2
    assert doc['adjustment']['candidate_complete'] is False


def test_chart_missing_currency_and_wrong_symbol_rejected():
    payload = chart_fixture()
    payload['chart']['result'][0]['meta'].pop('currency')
    with __import__('pytest').raises(ValueError, match='currency'):
        market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    with __import__('pytest').raises(ValueError, match='symbol'):
        market_data.normalize_yahoo_chart('OTHER', chart_fixture(), now=CHART_AS_OF)


def test_chart_timezone_fallback_is_explicit():
    payload = chart_fixture()
    payload['chart']['result'][0]['meta']['exchangeTimezoneName'] = 'Invalid/Zone'
    result = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert result['source_metadata']['date_basis'] == 'UTC fallback'
    assert any('trading dates use UTC' in w for w in result['quality_warnings'])


def test_chart_exchange_date_uses_timezone_when_available(monkeypatch):
    from datetime import timezone, timedelta
    monkeypatch.setattr(market_data, 'ZoneInfo', lambda _: timezone(timedelta(hours=-5)))
    payload = chart_fixture()
    payload['chart']['result'][0]['timestamp'][0] = 1767229200  # 2026-01-01 01:00 UTC
    doc = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert doc['records'][0]['date'] == '2025-12-31'
    assert doc['source_metadata']['date_basis'] == 'exchange timezone'


def test_intraday_and_future_bars_are_not_published_as_final_closes():
    from datetime import datetime, timezone
    payload = chart_fixture()
    now = datetime(2026, 1, 5, 14, tzinfo=timezone.utc)
    result = payload['chart']['result'][0]
    result['timestamp'] = [int(datetime(2026, 1, d, 13, tzinfo=timezone.utc).timestamp()) for d in (2, 5, 6)]
    result['meta']['currentTradingPeriod'] = {'regular': {
        'end': int(datetime(2026, 1, 5, 21, tzinfo=timezone.utc).timestamp())}}
    doc = market_data.normalize_yahoo_chart('TEST', payload, now=now)
    assert [r['date'] for r in doc['records']] == ['2026-01-02']
    assert doc['source_metadata']['rejection_reasons']['future_or_unconfirmed_session_close'] == 2
    closed = market_data.normalize_yahoo_chart('TEST', payload,
        now=datetime(2026, 1, 5, 22, tzinfo=timezone.utc))
    assert [r['date'] for r in closed['records']] == ['2026-01-02', '2026-01-05']


def test_adjustment_array_length_and_duplicate_dates_fail_safely():
    import pytest
    payload = chart_fixture()
    result = payload['chart']['result'][0]
    result['indicators']['adjclose'][0]['adjclose'].append(101)
    assert not market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)['adjustment']['candidate_complete']
    result['timestamp'][1] = result['timestamp'][0]
    with pytest.raises(ValueError, match='Duplicate'):
        market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)


@__import__('pytest').mark.parametrize('adjustment', [None, [None], [{}],
    [{'adjclose': None}], {'adjclose': []}, [{'adjclose': 'invalid'}], [], False])
def test_malformed_optional_adjustments_preserve_raw_prices(adjustment):
    payload = chart_fixture()
    payload['chart']['result'][0]['indicators']['adjclose'] = adjustment
    result = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert [row['close'] for row in result['records']] == [100, 101, 102]
    assert result['adjustment']['candidate_available'] is False
    assert any('Malformed optional' in w for w in result['quality_warnings'])
    assert all('provider_adjusted_close' not in row for row in result['records'])


@__import__('pytest').mark.parametrize('path,value', [
    (('chart',), None), (('chart', 'result'), None), (('chart', 'result'), [None]),
    (('chart', 'result', 0, 'meta'), None), (('chart', 'result', 0, 'meta', 'symbol'), None),
    (('chart', 'result', 0, 'indicators'), None),
    (('chart', 'result', 0, 'indicators', 'quote'), [None]),
    (('chart', 'result', 0, 'indicators', 'quote', 0, 'close'), 'invalid'),
    (('chart', 'result', 0, 'timestamp'), {}),
])
def test_malformed_required_chart_structures_raise_controlled_error(path, value):
    import pytest
    payload = chart_fixture()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)


def test_missing_required_and_optional_fields_are_distinguished():
    import pytest
    payload = chart_fixture()
    entry = payload['chart']['result'][0]
    entry['indicators'].pop('adjclose')
    assert not market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)['adjustment']['candidate_available']
    entry['indicators']['quote'][0].pop('open')
    with pytest.raises(ValueError, match='required market array'):
        market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)


def test_adjustment_scalar_values_and_rejected_dates_are_reported():
    payload = chart_fixture()
    entry = payload['chart']['result'][0]
    entry['indicators']['adjclose'][0]['adjclose'] = [None, -1, True]
    entry['indicators']['quote'][0]['close'][1] = None
    doc = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert not doc['adjustment']['candidate_available']
    assert any('affected candidates unavailable' in w for w in doc['quality_warnings'])
    assert doc['source_metadata']['rejected_dates'] == ['2026-01-02']


def test_chart_observation_limit_boundaries(monkeypatch):
    import pytest
    assert market_data.MAX_CHART_OBSERVATIONS == 400
    monkeypatch.setattr(market_data, 'MAX_CHART_OBSERVATIONS', 3)
    payload = chart_fixture()
    assert len(market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)['records']) == 3
    payload['chart']['result'][0]['timestamp'].append(1767704400)
    with pytest.raises(ValueError, match='observation limit'):
        market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    payload = chart_fixture()
    payload['chart']['result'][0]['indicators']['quote'][0]['close'].append(103)
    with pytest.raises(ValueError, match='observation limit'):
        market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)


@__import__('pytest').mark.parametrize('span,accepted', [(370, True), (371, False)])
def test_chart_date_span_limit_boundaries(span, accepted):
    from datetime import datetime, timedelta, timezone
    import pytest
    payload = chart_fixture()
    start = datetime(2024, 1, 1, 13, tzinfo=timezone.utc)
    payload['chart']['result'][0]['timestamp'] = [int((start + timedelta(days=d)).timestamp()) for d in (0, 1, span)]
    if not accepted:
        with pytest.raises(ValueError, match='date-span limit'):
            market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
        return
    assert len(market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)['records']) == 3


def test_normal_one_year_chart_fits_all_limits():
    from datetime import datetime, timedelta, timezone
    payload = chart_fixture()
    entry = payload['chart']['result'][0]
    days = [datetime(2025, 1, 1, 13, tzinfo=timezone.utc) + timedelta(days=i) for i in range(365)]
    entry['timestamp'] = [int(day.timestamp()) for day in days if day.weekday() < 5]
    size = len(entry['timestamp'])
    entry['indicators']['quote'] = [{'open': [100] * size, 'high': [101] * size,
        'low': [99] * size, 'close': [100] * size, 'volume': [1000] * size}]
    entry['indicators'].pop('adjclose')
    entry.pop('events')
    doc = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert len(doc['records']) == size and size >= 252
    assert doc['source_metadata']['rejected_observations'] == 0


def test_unrepresentable_adjustment_number_is_unavailable_not_fatal():
    payload = chart_fixture()
    payload['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'] = [10 ** 500, None, True]
    doc = market_data.normalize_yahoo_chart('TEST', payload, now=CHART_AS_OF)
    assert len(doc['records']) == 3
    assert doc['adjustment']['invalid_candidate_observations'] == 3
    assert not doc['adjustment']['candidate_available']
    assert any('affected candidates unavailable' in w for w in doc['quality_warnings'])
