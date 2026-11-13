"""Descriptive USD buy-and-hold portfolio analytics; no trade execution."""
import math
import statistics
from datetime import date
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('cira_portfolio_market', Path(__file__).with_name('market_analytics.py'))
_market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_market)


def analyze_portfolio(positions, prices, cash=0):
    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('Units and cash must be numbers')
        if not math.isfinite(value) or value < 0:
            raise ValueError('Units and cash must be finite and nonnegative')
        return float(value)
    cash = number(cash)
    holdings = {symbol: number(units) for symbol, units in positions.items()}
    holdings = {symbol: units for symbol, units in holdings.items() if units > 0}
    if not holdings:
        raise ValueError('Enter at least one positive holding')
    histories = {}
    warnings = []
    unsafe = False
    bases = {prices[s].get('price_type', 'unadjusted') for s in holdings}
    if bases != {'unadjusted'}:
        raise ValueError('Portfolio requires a consistent unadjusted basis; adjusted methodology is not validated')
    for symbol in holdings:
        document = prices[symbol]
        if document['symbol'] != symbol or document['currency'] != 'USD':
            raise ValueError('Portfolio requires matching USD price histories')
        rows = document['records']
        history = {}
        for row in rows:
            stamp = date.fromisoformat(row['date']).isoformat()
            if stamp in history:
                raise ValueError('Duplicate portfolio price date')
            close = number(row['close'])
            if close == 0:
                raise ValueError('Prices must be positive')
            history[stamp] = close
        histories[symbol] = history
    common = sorted(set.intersection(*(set(h) for h in histories.values())))
    if len(common) < 3:
        raise ValueError('At least three aligned daily observations are required')
    holding_quality = {}
    for symbol in holdings:
        # Validate each holding within the reported portfolio window, retaining
        # intermediate observations to detect events between aligned dates.
        document = dict(prices[symbol])
        document['records'] = [row for row in prices[symbol]['records']
                               if common[0] <= row['date'] <= common[-1]]
        assessment = _market.analyze_prices(document)
        holding_quality[symbol] = assessment['quality']
        warnings.extend(f'{symbol}: {w}' for w in assessment['quality_warnings'])
        unsafe = unsafe or not assessment['quality']['historical_returns_available']
    values = [cash + sum(holdings[s] * histories[s][day] for s in holdings) for day in common]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    quality, aligned_warnings = _market.series_quality([date.fromisoformat(d) for d in common], values, {})
    quality['holding_quality'] = holding_quality
    warnings.extend(aligned_warnings)
    if any(len(h) != len(common) for h in histories.values()):
        warnings.append('Portfolio history uses only dates shared by every holding; unmatched dates were omitted')
    if unsafe:
        quality['historical_returns_available'] = False
        quality['volatility_available'] = False
        quality['volatility_status'] = 'unavailable: a holding has an unvalidated price discontinuity'
    if any(not q['volatility_available'] for q in holding_quality.values()):
        quality['volatility_available'] = False
        if not unsafe:
            quality['volatility_status'] = 'unavailable: a holding has uncertain trading-session continuity'
    peak, drawdown = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    allocations = {s: holdings[s] * histories[s][common[-1]] / values[-1] * 100 for s in holdings}
    allocations['Cash'] = cash / values[-1] * 100
    return {'currency': 'USD', 'latest_date': common[-1], 'observations': len(common),
            'market_value': values[-1], 'period_price_change_pct': (values[-1] / values[0] - 1) * 100 if quality['historical_returns_available'] else None,
            'annualized_volatility_pct': statistics.stdev(returns) * math.sqrt(252) * 100 if quality['volatility_available'] else None,
            'maximum_drawdown_pct': drawdown * 100 if quality['historical_returns_available'] else None, 'allocations_pct': allocations,
            'first_date': common[0], 'annualization_trading_days': 252, 'return_basis': 'unadjusted_close',
            'quality': quality, 'quality_warnings': list(dict.fromkeys(warnings)),
            'history': [{'date': day, 'value': value} for day, value in zip(common, values)],
            'method': 'Constant units and cash over aligned dates. No dividends, fees, taxes, FX, or cash flows.'}
