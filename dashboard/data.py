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
            'batch_id': next(iter(companies.values()))['run_id']}


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
    return {'companies': companies, 'prices': prices, 'source': 'Azure verified batch', 'batch_id': batch, 'excluded': manifest.get('excluded') or {}}


def freshness(report, now=None):
    now = now or datetime.now(timezone.utc)
    generated = datetime.fromisoformat(report['generated_at_utc'].replace('Z', '+00:00'))
    if generated.tzinfo is None:
        raise ValueError('Report timestamp missing timezone')
    age = (now - generated).total_seconds() / 3600
    market_date = datetime.fromisoformat(report['market']['last_date']).date()
    market_age = (now.date() - market_date).days
    if age < 0 or market_age < 0:
        return 'Invalid future timestamp'
    if age > 36 or market_age > 4:
        return 'Stale — refresh required'
    return 'Within freshness window'
