"""Descriptive USD buy-and-hold portfolio analytics; no trade execution."""
import math
import statistics
from datetime import date


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
    values = [cash + sum(holdings[s] * histories[s][day] for s in holdings) for day in common]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    peak, drawdown = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    allocations = {s: holdings[s] * histories[s][common[-1]] / values[-1] * 100 for s in holdings}
    allocations['Cash'] = cash / values[-1] * 100
    return {'currency': 'USD', 'latest_date': common[-1], 'observations': len(common),
            'market_value': values[-1], 'period_price_change_pct': (values[-1] / values[0] - 1) * 100,
            'annualized_volatility_pct': statistics.stdev(returns) * math.sqrt(252) * 100,
            'maximum_drawdown_pct': drawdown * 100, 'allocations_pct': allocations,
            'history': [{'date': day, 'value': value} for day, value in zip(common, values)],
            'method': 'Constant units and cash over aligned dates. No dividends, fees, taxes, FX, or cash flows.'}
