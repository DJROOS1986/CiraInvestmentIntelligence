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
    app.multiselect[0].set_value(['AAPL']).run()
    app.number_input[0].set_value(2.0).run()
    assert not app.exception
    assert app.metric[0].value == '$198.00'
    app.sidebar.radio[0].set_value('Data quality').run()
    assert not app.exception
    assert len(app.dataframe) == 1


def test_portfolio_split_does_not_create_artificial_drawdown():
    doc = prices('AAPL', (100, 51, 52))
    doc['corporate_actions'] = {'splits': [{'date': '2026-11-02', 'numerator': 2, 'denominator': 1}]}
    result = portfolio.analyze_portfolio({'AAPL': 2}, {'AAPL': doc})
    assert result['market_value'] == 104
    assert result['annualized_volatility_pct'] is None
    assert result['maximum_drawdown_pct'] is None
    assert result['period_price_change_pct'] is None


def test_portfolio_rejects_mixed_adjustment_bases():
    a, b = prices('AAPL'), prices('MSFT')
    a['price_type'], b['price_type'] = 'unadjusted', 'adjusted'
    with pytest.raises(ValueError, match='consistent unadjusted'):
        portfolio.analyze_portfolio({'AAPL': 1, 'MSFT': 1}, {'AAPL': a, 'MSFT': b})


def test_portfolio_alignment_and_gap_disclosures():
    a, b = prices('AAPL', (100, 101, 102, 103)), prices('MSFT', (100, 101, 102))
    a['records'][-1]['date'] = b['records'][-1]['date'] = '2026-11-15'
    result = portfolio.analyze_portfolio({'AAPL': 1, 'MSFT': 1}, {'AAPL': a, 'MSFT': b})
    assert result['observations'] == 3
    assert result['annualized_volatility_pct'] is None
    assert any('unmatched dates' in w for w in result['quality_warnings'])


def test_financial_and_retrieval_freshness_are_independent():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    report = {'generated_at_utc': now.isoformat(), 'financial': {'period_end': '2024-01-01'},
              'market': {'last_date': '2026-11-13'}}
    assert data_reader.freshness(report, now).startswith('Stale financial')
    report['financial']['period_end'] = '2026-06-30'
    report['market']['retrieved_at_utc'] = (now - timedelta(days=3)).isoformat()
    assert data_reader.freshness(report, now).startswith('Stale market retrieval')
    report['market']['retrieved_at_utc'] = now.isoformat()
    assert data_reader.freshness(report, now) == 'Within freshness window'
    report['financial']['period_end'] = '2027-01-01'
    assert data_reader.freshness(report, now).startswith('Invalid future financial')


def test_manifest_creation_time_preserved_and_legacy_optional(research_root, monkeypatch):
    monkeypatch.setenv('CIRA_STORAGE_ACCOUNT', 'testaccount')
    manifest, path, payloads = publisher.prepare(research_root)
    container = Container()
    publisher.publish(manifest, path, payloads, container)
    loaded = data_reader.load_azure(container)
    assert loaded['batch_created_at_utc'] == manifest['created_at_utc']
    legacy = data_reader.research_disclosures(loaded['companies']['AAPL'], loaded['prices']['AAPL'])
    assert legacy['Reported currency'] is None
    assert legacy['BCG verification'] == 'Not independently verified'
    assert legacy['Rejected observations'] is None  # unknown is not zero


def test_dashboard_provenance_and_non_usd_price_disclosures(research_root, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.delenv('CIRA_STORAGE_ACCOUNT', raising=False)
    monkeypatch.delenv('CIRA_AI_ENDPOINT', raising=False)
    monkeypatch.setenv('CIRA_PROJECT_ROOT', str(research_root))
    path = research_root / 'reports/company-intelligence/AAPL-company-intelligence.json'
    report = json.loads(path.read_text())
    report['financial'].update(currency='USD', reported_currency='EUR', filing_dates=['2026-08-01'],
        provenance={'revenue': {'tag': 'Revenues', 'form': '20-F', 'filed': '2026-08-01', 'unit': 'EUR', 'scale': 1}},
        fx={'source': 'test ECB fixture', 'rates': {'revenue': {'basis': 'average', 'usd_per_unit': 1.1}}})
    report['market'].update(currency='EUR', return_basis='unadjusted_close', observations=3,
        quality={'volatility_status': 'low confidence: fewer than 60 returns'},
        source_metadata={'rejected_observations': 1})
    report['bcg'] = {'research_available': True, 'classification_origin': 'user-supplied research',
        'provenance': {'source_summary_date': '2026-10-28'},
        'verification_note': 'No independent evidence of an official BCG assessment'}
    path.write_text(json.dumps(report))
    app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=20)
    assert not app.exception
    assert app.metric[3].value == 'EUR 99.00'
    text = '\n'.join(element.value for element in app.markdown)
    assert 'Financial filing dates: 2026-08-01' in text
    assert 'Rejected observations: 1' in text
    assert 'BCG research date: 2026-10-28' in text
    assert 'No independent evidence of an official BCG assessment' in text
    assert any('No total-return claim' in element.value for element in app.caption)
    st.cache_data.clear()


def test_invalid_source_dates_are_explicit_and_do_not_crash_dashboard():
    report = {'generated_at_utc': 'not-a-date', 'market': {'last_date': '2026-11-13'}}
    assert data_reader.freshness(report).startswith('Invalid or unavailable')


def test_derived_financial_components_have_visible_filing_references():
    financial = {'provenance': {'total_liabilities': {'tag': 'derived: sum',
        'components': [{'tag': 'LiabilitiesCurrent', 'form': '10-K', 'accession': 'fixture', 'unit': 'USD'}]}}}
    rows = data_reader.financial_provenance_rows(financial)
    assert len(rows) == 2
    assert rows[1]['Definition'] == 'LiabilitiesCurrent' and rows[1]['Accession'] == 'fixture'


def test_dashboard_packaged_portfolio_loads_without_repository_modules(tmp_path):
    import shutil
    destination = tmp_path / 'portfolio-engine'
    destination.mkdir()
    dockerfile = (ROOT / 'Dockerfile.dashboard').read_text()
    for name in ('portfolio_analytics.py', 'market_analytics.py'):
        source = 'portfolio-engine/' + name
        assert f'COPY {source} /app/{source}' in dockerfile
        shutil.copyfile(ROOT / source, destination / name)
    spec = importlib.util.spec_from_file_location('isolated_portfolio', destination / 'portfolio_analytics.py')
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    result = isolated.analyze_portfolio({'AAPL': 1}, {'AAPL': prices('AAPL')})
    assert result['market_value'] == 99
    assert result['quality']['volatility_status'].startswith('low confidence')


def test_dashboard_portfolio_renders_withheld_split_statistics(research_root, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.delenv('CIRA_STORAGE_ACCOUNT', raising=False)
    monkeypatch.delenv('CIRA_AI_ENDPOINT', raising=False)
    monkeypatch.setenv('CIRA_PROJECT_ROOT', str(research_root))
    path = research_root / 'reports/market-data/AAPL-daily-prices.json'
    document = json.loads(path.read_text())
    document['records'][1]['close'] = 50
    document['records'][2]['close'] = 51
    document['corporate_actions'] = {'splits': [{'date': document['records'][1]['date']}]}
    path.write_text(json.dumps(document))
    app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=20)
    app.sidebar.radio[0].set_value('Portfolio lab').run()
    app.multiselect[0].set_value(['AAPL']).run()
    app.number_input[0].set_value(1.0).run()
    assert not app.exception
    assert app.metric[0].value == '$51.00'
    assert app.metric[1].value == app.metric[2].value == 'Unavailable'
    assert any('withheld' in warning.value for warning in app.warning)
    st.cache_data.clear()


@pytest.mark.parametrize('known_split', [False, True])
def test_portfolio_ignores_discontinuities_outside_common_window(known_split):
    from copy import deepcopy
    a = {'symbol': 'AAPL', 'currency': 'USD', 'records': [
        {'date': d, 'close': c} for d, c in [('2026-01-01', 100), ('2026-01-02', 50),
            ('2026-01-03', 51), ('2026-11-10', 100), ('2026-11-11', 101), ('2026-11-12', 102)]]}
    b = {'symbol': 'MSFT', 'currency': 'USD', 'records': [
        {'date': d, 'close': c} for d, c in [('2026-11-10', 100), ('2026-11-11', 101), ('2026-11-12', 102)]]}
    if known_split:
        a['corporate_actions'] = {'splits': [{'date': '2026-01-02'}]}
    documents = {'AAPL': a, 'MSFT': b}
    before = deepcopy(documents)
    result = portfolio.analyze_portfolio({'AAPL': 1, 'MSFT': 1}, documents)
    assert result['first_date'] == '2026-11-10' and result['observations'] == 3
    assert result['annualized_volatility_pct'] is not None
    assert result['maximum_drawdown_pct'] == 0
    assert result['period_price_change_pct'] == pytest.approx(2)
    assert not any('Split event or extreme' in w for w in result['quality_warnings'])
    assert result['quality']['holding_quality']['AAPL']['uncertain_interval_count'] == 0
    assert documents == before


@pytest.mark.parametrize('known_split', [False, True])
def test_portfolio_preserves_discontinuity_checks_inside_common_window(known_split):
    a = {'symbol': 'AAPL', 'currency': 'USD', 'records': [
        {'date': d, 'close': c} for d, c in [('2026-11-10', 100), ('2026-11-11', 50), ('2026-11-12', 51)]]}
    b = {'symbol': 'MSFT', 'currency': 'USD', 'records': [
        {'date': d, 'close': 100} for d in ['2026-11-10', '2026-11-11', '2026-11-12']]}
    if known_split:
        a['corporate_actions'] = {'splits': [{'date': '2026-11-11'}]}
    result = portfolio.analyze_portfolio({'AAPL': 1, 'MSFT': 1}, {'AAPL': a, 'MSFT': b})
    assert result['market_value'] == 151
    assert result['annualized_volatility_pct'] is None and result['maximum_drawdown_pct'] is None
    assert any('Split event or extreme' in w for w in result['quality_warnings'])


def test_portfolio_withholds_uncertain_common_session_volatility():
    a = {'symbol': 'AAPL', 'currency': 'USD', 'records': [
        {'date': d, 'close': 100 + i} for i, d in enumerate(['2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13'])]}
    b = {'symbol': 'MSFT', 'currency': 'USD', 'records': [
        {'date': d, 'close': 100 + i} for i, d in enumerate(['2026-11-10', '2026-11-12', '2026-11-13'])]}
    result = portfolio.analyze_portfolio({'AAPL': 1, 'MSFT': 1}, {'AAPL': a, 'MSFT': b})
    assert result['annualized_volatility_pct'] is None
    assert result['quality']['continuity_status'] == 'uncertain'
    assert result['quality']['holding_quality']['MSFT']['volatility_available'] is False
    assert result['quality']['historical_returns_available'] is True


def test_legacy_filing_summary_matches_metric_and_component_table():
    financial = {'provenance': {
        'revenue': {'filed': '2026-08-01', 'tag': 'Revenues'},
        'net_income': {'filed': '2026-08-01'},
        'total_liabilities': {'components': [{'filed': '2026-08-02'}, {'filed': '2026-07-31'}]},
        'capital_expenditure': None}}
    report = {'financial': financial, 'market': {'last_date': '2026-11-12'}}
    rows = data_reader.financial_provenance_rows(financial)
    expected = ', '.join(sorted({row['Filing date'] for row in rows if row['Filing date']}))
    disclosure = data_reader.research_disclosures(report, {'records': []})
    assert disclosure['Financial filing dates'] == expected == '2026-07-31, 2026-08-01, 2026-08-02'
    financial['filing_dates'] = []  # empty aggregation also falls back
    assert data_reader.research_disclosures(report, {'records': []})['Financial filing dates'] == expected
    financial['provenance'] = {'revenue': {}}
    assert data_reader.research_disclosures(report, {'records': []})['Financial filing dates'] is None


@pytest.mark.parametrize('value,currency,expected', [
    (478_834_000_000, 'USD', '$478.8B'), (132_100_000_000, 'USD', '$132.1B'),
    (136_000_000_000, 'USD', '$136.0B'), (12_345, 'USD', '$12.3K'),
    (1_500_000, 'EUR', 'EUR 1.5M'), (1_200_000_000_000, 'CNY', 'CNY 1.2T'),
    (-132_100_000_000, 'USD', '-$132.1B'), (0, 'USD', '$0.00'),
    (0.25, 'USD', '$0.25'), (999_999, 'USD', '$1.0M'),
    (1e18, 'USD', '$1.0e+18'), (None, 'USD', 'Unavailable'),
    (float('nan'), 'USD', 'Unavailable'), (float('inf'), 'USD', 'Unavailable'),
    (True, 'USD', 'Unavailable'), ('123', 'USD', 'Unavailable'),
    (100, None, 'Currency unavailable 100.00'),
])
def test_compact_money_presentation(value, currency, expected):
    assert data_reader.format_money(value, currency) == expected


def test_price_precision_and_full_report_tooltip():
    assert data_reader.format_money(354.88, 'USD', compact=False) == '$354.88'
    assert data_reader.format_money(99, 'EUR', compact=False) == 'EUR 99.00'
    assert data_reader.format_money(1e18, 'USD', compact=False) == '$1.0e+18'
    assert '478,834,000,000.125' in data_reader.money_help(478_834_000_000.125, 'USD')
    assert 'no estimate' in data_reader.money_help(None, 'USD')


def test_disclosure_grouping_preserves_every_fact_and_legacy_absence():
    report = {'financial': {'period_end': '2026-06-30', 'provenance': {'revenue': {'filed': '2026-08-01'}}},
              'market': {'last_date': '2026-11-12', 'source_metadata': {
                  'rejected_observations': 1, 'rejected_dates': ['2026-11-13'],
                  'rejection_reasons': {'future': 1}}}}
    history = {'records': []}
    groups = data_reader.disclosure_groups(report, history, '2026-11-13T19:51:21Z')
    flat = {label: value for facts in groups.values() for label, value in facts.items()}
    assert flat == data_reader.research_disclosures(report, history, '2026-11-13T19:51:21Z')
    assert sum(map(len, groups.values())) == len(flat)
    assert flat['Financial filing dates'] == '2026-08-01'
    assert flat['Rejected dates'] == '2026-11-13'
    assert flat['Confirmed missing sessions'] is None
    assert flat['Verified holiday sessions'] is None
    assert flat['Reported split events'] is None  # unknown is not zero
    assert flat['Reported dividend events'] is None
    history['corporate_actions'] = {'coverage': 'unverified', 'splits': None}
    absent = data_reader.research_disclosures(report, history)
    assert absent['Reported split events'] is None and absent['Reported dividend events'] is None
    history['corporate_actions'].update(splits=[], dividends=[{'amount': 1}])
    present = data_reader.research_disclosures(report, history)
    assert present['Reported split events'] == 0 and present['Reported dividend events'] == 1


def test_warning_coalescing_retains_unknown_evidence_and_original_report():
    import copy
    warnings = ['Historical price returns may exclude dividends and corporate-action adjustments',
        'Corporate-action completeness and provider close adjustment methodology are unverified',
        'Financial filing postdates the market price; unavailable for point-in-time analysis',
        'BCG classification is not independently verified', 'source-specific warning', 'source-specific warning']
    report = {'data_quality': {'warnings': warnings}}
    original = copy.deepcopy(report)
    displayed = data_reader.active_warnings(report)
    assert len(displayed) == 4
    assert 'dividends' in displayed[0] and 'methodology are unverified' in displayed[0]
    assert displayed[1:] == warnings[2:5]
    assert report == original


@pytest.mark.parametrize('ticker,currency,values,expected', [
    ('AAPL', 'USD', (478_834_000_000, 132_100_000_000, 136_000_000_000),
     ['$478.8B', '$132.1B', '$136.0B']),
    ('ASML', 'EUR', (30_000_000_000, -1_500_000, None),
     ['$30.0B', '-$1.5M', 'Unavailable']),
    ('BABA', 'USD', (0, None, 1e18), ['$0.00', 'Unavailable', '$1.0e+18']),
])
def test_company_cards_and_grouped_legacy_disclosures(research_root, monkeypatch, ticker, currency, values, expected):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.delenv('CIRA_STORAGE_ACCOUNT', raising=False)
    monkeypatch.delenv('CIRA_AI_ENDPOINT', raising=False)
    monkeypatch.setenv('CIRA_PROJECT_ROOT', str(research_root))
    path = research_root / f'reports/company-intelligence/{ticker}-company-intelligence.json'
    report = json.loads(path.read_text())
    report['financial']['metrics_usd'] = dict(zip(['revenue', 'net_income', 'free_cash_flow'], values))
    report['financial']['reported_currency'] = 'EUR' if ticker == 'ASML' else 'USD'
    report['market']['currency'] = currency
    path.write_text(json.dumps(report))
    app = AppTest.from_file(str(ROOT / 'dashboard/app.py')).run(timeout=20)
    app.selectbox[0].select(ticker).run()
    assert not app.exception
    assert [card.value for card in app.metric[:3]] == expected
    assert app.metric[3].value == ('$99.00' if currency == 'USD' else 'EUR 99.00')
    assert all(card.proto.help for card in app.metric)
    text = '\n'.join(element.value for element in app.markdown)
    for title in data_reader.disclosure_groups(report, {}):
        assert title in text
    assert 'Active warnings and unresolved limitations' in text
    assert 'test warning' in text
    assert json.loads(path.read_text()) == report
    st.cache_data.clear()
