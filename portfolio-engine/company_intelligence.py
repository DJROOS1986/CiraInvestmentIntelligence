"""CIRA Phase 5: combined company intelligence."""
import math
from datetime import datetime, timezone

def require_object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object')
    return value

def require_ticker(value, expected, label):
    if not isinstance(value, str) or value.upper() != expected:
        raise ValueError(f'{label} ticker does not match {expected}')

def optional_number(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be numeric or null')
    if not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return value

FALLBACK_TAG_WARNINGS = {
    'ProfitLoss': 'Net income uses ProfitLoss (includes non-controlling interests) because NetIncomeLoss is not reported',
    'PaymentsToAcquireProductiveAssets': 'Capital expenditure uses PaymentsToAcquireProductiveAssets (may include some intangible assets)',
    'RevenueFromContractWithCustomerIncludingAssessedTax': 'Revenue uses RevenueFromContractWithCustomerIncludingAssessedTax (may include sales taxes collected from customers)',
}


def universe_companies():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'config' / 'universe.json'
    return json.loads(path.read_text(encoding='utf-8'))['companies']


def universe_tickers():
    return {c['ticker'] for c in universe_companies()}


def universe_notes(ticker):
    return next((list(c.get('notes', [])) for c in universe_companies() if c['ticker'] == ticker), [])


def provenance_warnings(financial):
    provenance = financial.get('provenance')
    if not isinstance(provenance, dict):
        return []
    metrics = financial.get('metrics_usd') or {}
    out = []
    fx = financial.get('fx')
    if isinstance(fx, dict) and fx.get('rates'):
        rates = fx['rates']
        avg = (rates.get('revenue') or {}).get('usd_per_unit')
        close = (rates.get('total_assets') or {}).get('usd_per_unit')
        parts = ([f'average rate {avg:.4f} for flows'] if avg else []) + ([f"closing rate {close:.4f} at {financial.get('period_end')}"] if close else [])
        out.append(f"Financials converted from {fx.get('currency')} to USD ({fx.get('source')}): " + ', '.join(parts))
    for key in ('revenue', 'net_income', 'total_assets', 'total_liabilities', 'operating_cash_flow', 'capital_expenditure'):
        label = key.replace('_', ' ').capitalize()
        if metrics.get(key) is None:
            out.append(f'{label} not reported under supported SEC labels')
            continue
        tag = str((provenance.get(key) or {}).get('tag', ''))
        if tag.startswith('derived:'):
            out.append(f'{label} derived ({tag[len("derived:"):].strip()}), cross-checked against the balance sheet')
        elif tag in FALLBACK_TAG_WARNINGS:
            out.append(FALLBACK_TAG_WARNINGS[tag])
    return out


def build_company_intelligence(ticker, financial, prices, market, bcg_assessment, run_id=None):
    if run_id is not None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('Invalid processing run ID')
    ticker = ticker.upper().strip()
    if ticker not in universe_tickers():
        raise ValueError('Ticker not approved for initial integration')
    for (label, value) in (('financial', financial), ('prices', prices), ('market', market), ('bcg', bcg_assessment)):
        require_object(value, label)
    require_ticker(financial.get('ticker'), ticker, 'Financial')
    require_ticker(prices.get('symbol'), ticker, 'Price')
    require_ticker(market.get('symbol'), ticker, 'Market')
    require_ticker(bcg_assessment.get('ticker'), ticker, 'BCG')
    metrics = require_object(financial.get('metrics_usd'), 'Financial metrics')
    records = prices.get('records')
    if not isinstance(records, list) or not records:
        raise ValueError('Historical prices must contain records')
    if not all((isinstance(item, dict) for item in records)):
        raise ValueError('Invalid historical price record')
    observations = market.get('observations')
    if isinstance(observations, bool) or not isinstance(observations, int) or observations != len(records):
        raise ValueError('Market observation count mismatch')
    price_currency = prices.get('currency')
    market_currency = market.get('currency')
    price_type = prices.get('price_type')
    if not price_currency or price_currency != market_currency:
        raise ValueError('Market currency mismatch')
    if not price_type or price_type != market.get('price_type'):
        raise ValueError('Market price type mismatch')
    last_date = max((str(item.get('date', '')) for item in records))
    if last_date != market.get('last_date'):
        raise ValueError('Market last date mismatch')
    warnings = []
    if not bcg_assessment.get('research_available'):
        warnings.append('BCG research unavailable for this ticker')
    elif bcg_assessment.get('verified_bcg_class') is None:
        warnings.append('BCG classification is not independently verified')
    else:
        warnings.append('BCG classification is source-reported, not independently verified')
    warnings.extend(universe_notes(ticker))
    warnings.extend(provenance_warnings(financial))
    if price_type != 'adjusted':
        warnings.append('Historical price returns may exclude dividends and corporate-action adjustments')
    warnings.append('Financial reporting periods and market dates are not synchronized')
    financial_values = {key: optional_number(metrics.get(key), key) for key in ('revenue', 'net_income', 'total_assets', 'total_liabilities', 'operating_cash_flow', 'capital_expenditure', 'free_cash_flow')}
    market_values = {key: optional_number(market.get(key), key) for key in ('latest_close', 'daily_return_pct', 'period_price_change_pct', 'sma_5', 'sma_20', 'annualized_volatility_pct')}
    return {'schema_version': '1.0', 'ticker': ticker, 'company': financial.get('company'), 'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'financial': {'source': 'SEC financial report', 'period_end': financial.get('period_end'), 'currency': financial.get('currency'), 'metrics_usd': financial_values, 'provenance': financial.get('provenance'), 'report_generated_at_utc': financial.get('generated_at_utc')}, 'market': {'provider': market.get('provider'), 'retrieved_at_utc': prices.get('retrieved_at_utc'), 'currency': market_currency, 'price_type': price_type, 'first_date': market.get('first_date'), 'last_date': market.get('last_date'), 'observations': observations, 'indicators': market_values, 'return_basis': market.get('return_basis')}, 'bcg': dict(bcg_assessment), 'data_quality': {'warnings': warnings, 'independently_verified_bcg': False, 'investment_recommendation': None}, **({'run_id': run_id} if run_id is not None else {})}
