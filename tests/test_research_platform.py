import hashlib
import importlib.util
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


portfolio = module('portfolio_test', 'portfolio-engine/portfolio_analytics.py')
data_reader = module('dashboard_data_test', 'dashboard/data.py')
publisher = module('publisher_test', 'scripts/20-Publish-Versioned-Reports.py')


def prices(symbol, closes=(100, 110, 99)):
    return {'symbol': symbol, 'currency': 'USD', 'records': [
        {'date': f'2026-11-{i + 1:02}', 'close': close} for i, close in enumerate(closes)]}


def test_portfolio_buy_and_hold_cash_and_drawdown():
    result = portfolio.analyze_portfolio({'AAPL': 2}, {'AAPL': prices('AAPL')}, 100)
    assert result['market_value'] == 298
    assert result['maximum_drawdown_pct'] == pytest.approx((298 / 320 - 1) * 100)
    assert sum(result['allocations_pct'].values()) == pytest.approx(100)
    assert result['annualized_volatility_pct'] > 0


@pytest.mark.parametrize('units', [-1, float('nan'), True, '3'])
def test_invalid_holdings_rejected(units):
    with pytest.raises(ValueError):
        portfolio.analyze_portfolio({'AAPL': units}, {'AAPL': prices('AAPL')})


def test_portfolio_currency_and_duplicate_dates_rejected():
    doc = prices('AAPL')
    doc['currency'] = 'EUR'
    with pytest.raises(ValueError, match='USD'):
        portfolio.analyze_portfolio({'AAPL': 1}, {'AAPL': doc})
    doc['currency'] = 'USD'
    doc['records'][1]['date'] = doc['records'][0]['date']
    with pytest.raises(ValueError, match='Duplicate'):
        portfolio.analyze_portfolio({'AAPL': 1}, {'AAPL': doc})


class Container:
    def __init__(self):
        self.blobs = {}
        self.fail_path = None

    def get_blob_client(self, name):
        container = self
        class Blob:
            def download_blob(self):
                if name not in container.blobs:
                    raise ResourceNotFoundError('not found')
                return SimpleNamespace(readall=lambda: container.blobs[name], properties=SimpleNamespace(etag='etag'))

            def upload_blob(self, payload, **kwargs):
                if name == container.fail_path:
                    raise RuntimeError('injected upload failure')
                if not kwargs.get('overwrite') and name in container.blobs:
                    raise RuntimeError('immutable blob exists')
                container.blobs[name] = payload
        return Blob()

    def download_blob(self, name):
        return self.get_blob_client(name).download_blob()


@pytest.fixture
def research_root(tmp_path, monkeypatch):
    monkeypatch.setenv('CIRA_RUN_STATE', str(tmp_path / 'run-exclusions.json'))
    now = datetime.now(timezone.utc)
    for ticker in data_reader.TICKERS:
        history = prices(ticker)
        history['retrieved_at_utc'] = now.isoformat()
        for index, row in enumerate(history['records']):
            row['date'] = (now.date() - timedelta(days=2-index)).isoformat()
        docs = {
            f'company-intelligence/{ticker}-company-intelligence.json': {
                'schema_version': '1.0', 'ticker': ticker, 'run_id': 'shared-run', 'company': ticker,
                'generated_at_utc': now.isoformat(),
                'financial': {'period_end': '2026-06-30', 'source': 'SEC', 'metrics_usd': {'revenue': 1e9}},
                'market': {'last_date': now.date().isoformat(), 'provider': 'test', 'indicators': {'latest_close': 99}},
                'data_quality': {'independently_verified_bcg': False, 'investment_recommendation': None, 'warnings': ['test warning']}},
            f'market-data/{ticker}-daily-prices.json': history,
            f'market-analysis/{ticker}-market-analysis.json': {'symbol': ticker},
            f'financial/{ticker}-financial-report.json': {'ticker': ticker},
        }
        for relative, doc in docs.items():
            path = tmp_path / 'reports' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc), encoding='utf-8')
    return tmp_path


def test_publish_read_and_tamper_detection(research_root, monkeypatch):
    monkeypatch.setenv('CIRA_STORAGE_ACCOUNT', 'testaccount')
    manifest, path, payloads = publisher.prepare(research_root)
    container = Container()
    publisher.publish(manifest, path, payloads, container)
    loaded = data_reader.load_azure(container)
    assert set(loaded['companies']) == set(data_reader.TICKERS)
    assert len(loaded['prices']['AAPL']['records']) == 3
    company_path = manifest['reports'][0]['blob_path']
    container.blobs[company_path] = b'{}'
    with pytest.raises(ValueError, match='integrity'):
        data_reader.load_azure(container)


def test_failed_batch_does_not_replace_latest(research_root, monkeypatch):
    monkeypatch.setenv('CIRA_STORAGE_ACCOUNT', 'testaccount')
    container = Container()
    first = publisher.prepare(research_root)
    publisher.publish(*first, container=container)
    previous = container.blobs['financial-intelligence/latest.json']
    second = publisher.prepare(research_root)
    container.fail_path = second[1]
    with pytest.raises(RuntimeError, match='injected'):
        publisher.publish(*second, container=container)
    assert container.blobs['financial-intelligence/latest.json'] == previous
    assert data_reader.load_azure(container)['batch_id'] == first[0]['batch_id']


def test_stale_market_data_blocked_before_publication(research_root):
    path = research_root / 'reports/market-data/AAPL-daily-prices.json'
    doc = json.loads(path.read_text())
    for row in doc['records']:
        row['date'] = (datetime.fromisoformat(row['date']) - timedelta(days=10)).date().isoformat()
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='Stale market'):
        publisher.prepare(research_root)


def test_mixed_local_run_rejected(research_root):
    path = research_root / 'reports/company-intelligence/AAPL-company-intelligence.json'
    report = json.loads(path.read_text())
    report['run_id'] = 'different'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='Mixed'):
        data_reader.load_local(research_root)


def test_dashboard_views(research_root, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('CIRA_STORAGE_ACCOUNT', raising=False)
    monkeypatch.setenv('CIRA_PROJECT_ROOT', str(research_root))
    app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=20)
    assert not app.exception
    assert app.title[0].value == 'Company research'
    app.sidebar.radio[0].set_value('Portfolio lab').run()
    app.number_input[0].set_value(2.0).run()
    assert not app.exception
    assert app.metric[0].value == '$198.00'
    app.sidebar.radio[0].set_value('Data quality').run()
    assert not app.exception
    assert len(app.dataframe) == 1
