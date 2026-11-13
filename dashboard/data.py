"""Read local snapshots or integrity-checked immutable Azure research batches."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

TICKERS = tuple(c["ticker"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"])


def read_json(data):
    return json.loads(data.decode('utf-8-sig'))


def validate_companies(companies, tickers=TICKERS):
    run_ids = set()
    for ticker in tickers:
        report = companies[ticker]
        if report.get('ticker') != ticker or report.get('schema_version') != '1.0':
            raise ValueError('Unexpected company report schema')
        quality = report.get('data_quality', {})
        if quality.get('independently_verified_bcg') is not False or quality.get('investment_recommendation') is not None:
            raise ValueError('Unexpected research safety metadata')
        if not isinstance(report.get('run_id'), str) or not report['run_id'].strip():
            raise ValueError('Missing report run ID')
        run_ids.add(report['run_id'])
    if len(run_ids) != 1:
        raise ValueError('Mixed report runs; complete batch required')


def load_local(root):
    reports = Path(root) / 'reports'
    companies = {t: read_json((reports / 'company-intelligence' / f'{t}-company-intelligence.json').read_bytes()) for t in TICKERS}
    prices = {t: read_json((reports / 'market-data' / f'{t}-daily-prices.json').read_bytes()) for t in TICKERS}
    validate_companies(companies)
    return {'companies': companies, 'prices': prices, 'source': 'Local snapshots',
            'batch_id': next(iter(companies.values()))['run_id'], 'batch_created_at_utc': None}


def load_azure(container):
    pointer = read_json(container.download_blob('financial-intelligence/latest.json').readall())
    batch = pointer['batch_id']
    if not isinstance(batch, str) or not batch or any(c not in '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-' for c in batch):
        raise ValueError('Invalid batch identifier')
    prefix = f'financial-intelligence/batches/{batch}/'
    if pointer['manifest_path'] != prefix + 'manifest.json':
        raise ValueError('Unexpected manifest destination')
    manifest_data = container.download_blob(pointer['manifest_path']).readall()
    if hashlib.sha256(manifest_data).hexdigest() != pointer['manifest_sha256']:
        raise ValueError('Manifest integrity mismatch')
    manifest = read_json(manifest_data)
    if manifest.get('status') != 'complete' or manifest.get('batch_id') != batch or manifest.get('report_count') != len(manifest.get('reports', [])):
        raise ValueError('Incomplete batch')
    companies, prices = {}, {}
    entries = manifest.get('reports', []) + manifest.get('artifacts', [])
    present = [entry.get('ticker') for entry in manifest.get('reports', [])]
    if not present or len(set(present)) != len(present) or not set(present) <= set(TICKERS):
        raise ValueError('Unexpected batch company list')
    expected = {prefix + f'company-intelligence/{t}-company-intelligence.json': (companies, t) for t in present}
    expected.update({prefix + f'market-data/{t}-daily-prices.json': (prices, t) for t in present})
    seen = set()
    for entry in entries:
        path = entry['blob_path']
        if path not in expected:
            continue
        if path in seen:
            raise ValueError('Duplicate batch artifact')
        seen.add(path)
        payload = container.download_blob(path).readall()
        if len(payload) != entry['size_bytes'] or hashlib.sha256(payload).hexdigest() != entry['sha256']:
            raise ValueError('Report integrity mismatch')
        target, ticker = expected[path]
        target[ticker] = read_json(payload)
    if seen != set(expected):
        raise ValueError('Batch missing company reports or price histories')
    validate_companies(companies, present)
    if any(r['run_id'] != manifest['run_id'] for r in companies.values()):
        raise ValueError('Report run differs from manifest')
    return {'companies': companies, 'prices': prices, 'source': 'Azure verified batch',
            'batch_id': batch, 'batch_created_at_utc': manifest.get('created_at_utc'),
            'excluded': manifest.get('excluded') or {}}


def freshness(report, now=None):
    try:
        return _freshness(report, now)
    except (KeyError, ValueError, TypeError, AttributeError):
        return 'Invalid or unavailable source dates — review required'


def _freshness(report, now=None):
    now = now or datetime.now(timezone.utc)
    generated = datetime.fromisoformat(report['generated_at_utc'].replace('Z', '+00:00'))
    if generated.tzinfo is None:
        raise ValueError('Report timestamp missing timezone')
    age = (now - generated).total_seconds() / 3600
    market_date = datetime.fromisoformat(report['market']['last_date']).date()
    market_age = (now.date() - market_date).days
    financial_period = report.get('financial', {}).get('period_end')
    if financial_period:
        financial_age = (now.date() - datetime.fromisoformat(financial_period).date()).days
        if financial_age < 0:
            return 'Invalid future financial period'
        if financial_age > 550:
            return 'Stale financial period — refresh required'
    retrieved = report.get('market', {}).get('retrieved_at_utc')
    if retrieved:
        stamp = datetime.fromisoformat(retrieved.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return 'Invalid market retrieval timestamp'
        retrieval_age = (now - stamp).total_seconds() / 3600
        if retrieval_age < 0:
            return 'Invalid future timestamp'
        if retrieval_age > 36:
            return 'Stale market retrieval — refresh required'
    if age < 0 or market_age < 0:
        return 'Invalid future timestamp'
    if age > 36 or market_age > 4:
        return 'Stale — refresh required'
    return 'Within freshness window'


def financial_provenance_rows(financial):
    rows = []
    for key, provenance in (financial.get('provenance') or {}).items():
        p = provenance or {}
        for label, item in [(key.replace('_', ' '), p)] + [
                (key.replace('_', ' ') + ' component', c) for c in p.get('components', [])]:
            rows.append({
                'Metric': label, 'Definition': item.get('tag') or item.get('method') or 'Unavailable',
                'Filing type': item.get('form'), 'Accession': item.get('accession'),
                'Filing date': item.get('filed'), 'Period start': item.get('start'),
                'Period end': item.get('period_end'), 'Reported unit': item.get('unit'),
                'Scale': item.get('scale'), 'Filing URL': item.get('filing_url'),
                'Reported value': item.get('reported_value'),
            })
    return rows


def research_disclosures(report, prices, batch_created_at_utc=None):
    """Display facts only; absent metadata in legacy batches stays unavailable."""
    financial, market = report['financial'], report['market']
    metadata = market.get('source_metadata') or prices.get('source_metadata') or {}
    bcg = report.get('bcg') or {}
    bcg_source = bcg.get('provenance') or {}
    source = financial.get('source_metadata') or {}
    adjustment = market.get('adjustment') or prices.get('adjustment') or {}
    quality = market.get('quality') or {}
    filing_dates = financial.get('filing_dates') or sorted({
        row['Filing date'] for row in financial_provenance_rows(financial)
        if row.get('Filing date')})
    return {
        'Financial source': financial.get('source'),
        'Financial period end': financial.get('period_end'),
        'Financial filing dates': ', '.join(filing_dates) or None,
        'Reported currency': financial.get('reported_currency'),
        'Financial display currency': financial.get('currency'),
        'SEC source identifier': source.get('sha256'),
        'SEC snapshot written UTC': source.get('snapshot_written_at_utc'),
        'SEC retrieval timestamp': source.get('retrieved_at_utc'),
        'Financial selection': source.get('selection_method'),
        'Market source': market.get('provider'),
        'Market price date': market.get('last_date'),
        'Market currency': market.get('currency') or prices.get('currency'),
        'Market retrieval UTC': market.get('retrieved_at_utc') or prices.get('retrieved_at_utc'),
        'Price calculation basis': market.get('return_basis') or 'Legacy close; adjustment basis unverified',
        'Adjustment validation': adjustment.get('status') or 'Unavailable; no validated total-return claim',
        'Historical window': f"{market.get('first_date') or 'Unavailable'} to {market.get('last_date') or 'Unavailable'}",
        'Price observations': market.get('observations', len(prices.get('records') or [])),
        'Return observations': quality.get('return_observations'),
        'Rejected observations': metadata.get('rejected_observations'),
        'Exchange timezone': metadata.get('exchange_timezone'),
        'Trading date basis': metadata.get('date_basis'),
        'Volatility status': quality.get('volatility_status') or 'Legacy estimate; reliability not assessed',
        'Annualization convention': market.get('annualization_trading_days'),
        'Research batch created UTC': batch_created_at_utc,
        'Company report generated UTC': report.get('generated_at_utc'),
        'BCG classification origin': bcg.get('classification_origin') or 'Unavailable; not independently verified',
        'BCG source file': bcg_source.get('source_file'),
        'BCG research date': bcg_source.get('source_summary_date'),
        'BCG verification': bcg.get('verification_note') or 'Not independently verified',
    }
