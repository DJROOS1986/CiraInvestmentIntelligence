"""Market-data validation and normalization for CIRA."""

from datetime import date
from datetime import datetime, timezone
from collections import Counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import math
from typing import Any, Dict, List

# Per-symbol daily chart limits: generous headroom above ~252 equity sessions
# and a leap year. The byte limit applies to the decoded HTTP body, before JSON.
MAX_CHART_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CHART_OBSERVATIONS = 400
MAX_CHART_SPAN_DAYS = 370


def _chart_object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f'Invalid required market structure: {label}')
    return value


def _chart_array(value, label):
    if not isinstance(value, list):
        raise ValueError(f'Invalid required market array: {label}')
    if len(value) > MAX_CHART_OBSERVATIONS:
        raise ValueError(f'Market observation limit exceeded: {label}')
    return value


def normalize_daily_prices(
    symbol: str,
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate and normalize daily OHLCV records."""

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("A non-empty stock symbol is required")

    if not isinstance(records, list):
        raise TypeError("Records must be a list")

    normalized = []
    seen_dates = set()

    for record in records:
        if not isinstance(record, dict):
            raise TypeError("Each record must be a dictionary")

        trading_date = date.fromisoformat(record["date"])

        if trading_date in seen_dates:
            raise ValueError("Duplicate trading date")

        seen_dates.add(trading_date)

        prices = {}

        for field in ("open", "high", "low", "close"):
            value = record[field]

            if isinstance(value, bool) or not isinstance(
                value, (int, float)
            ):
                raise ValueError(f"Invalid {field}")

            import math

            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid {field}")

            prices[field] = float(value)

        if (
            prices["high"] < prices["low"]
            or prices["high"] < prices["open"]
            or prices["high"] < prices["close"]
            or prices["low"] > prices["open"]
            or prices["low"] > prices["close"]
        ):
            raise ValueError("Inconsistent OHLC prices")

        volume = record["volume"]

        if (
            isinstance(volume, bool)
            or not isinstance(volume, int)
            or volume < 0
        ):
            raise ValueError("Invalid trading volume")

        normalized.append({
            "symbol": symbol.strip().upper(),
            "date": trading_date.isoformat(),
            **prices,
            "volume": volume,
        })

    return sorted(normalized, key=lambda row: row["date"])


def normalize_yahoo_chart(symbol, payload, now=None):
    """Normalize existing chart responses; adjustment methodology remains unverified.

    No forward fill. Rejected rows and adjustment candidates are accounted for.
    Exchange dates use IANA timezone data when installed, otherwise UTC with a warning.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Market retrieval time must include timezone')
    payload = _chart_object(payload, 'response')
    chart = _chart_object(payload.get('chart'), 'chart')
    if chart.get('error'):
        raise ValueError('Market provider returned a chart error')
    results = _chart_array(chart.get('result'), 'result')
    if len(results) != 1:
        raise ValueError('No market chart result')
    result = _chart_object(results[0], 'result entry')
    meta = _chart_object(result.get('meta'), 'meta')
    if not isinstance(meta.get('symbol'), str) or meta['symbol'].upper() != symbol.upper():
        raise ValueError('Market provider symbol mismatch')
    currency = meta.get('currency')
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise ValueError('Market provider currency missing or invalid')
    warnings = []
    exchange_zone = meta.get('exchangeTimezoneName')
    zone, date_basis = timezone.utc, 'UTC fallback'
    if isinstance(exchange_zone, str) and exchange_zone:
        try:
            zone, date_basis = ZoneInfo(exchange_zone), 'exchange timezone'
        except (ZoneInfoNotFoundError, ValueError):
            warnings.append('Exchange timezone unavailable locally; trading dates use UTC')
    else:
        warnings.append('Exchange timezone missing; trading dates use UTC')
    indicators = _chart_object(result.get('indicators'), 'indicators')
    quotes = _chart_array(indicators.get('quote'), 'quote')
    if len(quotes) != 1:
        raise ValueError('No OHLCV data')
    quote = _chart_object(quotes[0], 'OHLCV')
    for key in ('open', 'high', 'low', 'close', 'volume'):
        _chart_array(quote.get(key), key)
    timestamps = _chart_array(result.get('timestamp'), 'timestamp')
    candidates = []
    adjusted = indicators.get('adjclose')
    if 'adjclose' in indicators:
        if (isinstance(adjusted, list) and len(adjusted) == 1
                and isinstance(adjusted[0], dict)
                and isinstance(adjusted[0].get('adjclose'), list)
                and len(adjusted[0]['adjclose']) <= MAX_CHART_OBSERVATIONS):
            candidates = adjusted[0]['adjclose']
        else:
            warnings.append('Malformed optional adjusted-close data; candidates unavailable')
    valid_adjusted = []
    for value in candidates:
        try:
            valid = (not isinstance(value, bool) and isinstance(value, (float, int))
                     and math.isfinite(value) and value > 0)
        except OverflowError:
            valid = False
        valid_adjusted.append(valid)
    invalid_adjusted = (sum(not valid for valid in valid_adjusted)
                        + max(0, len(timestamps) - len(candidates))) if candidates else 0
    if candidates and (invalid_adjusted or len(candidates) != len(timestamps)):
        warnings.append('Invalid or incomplete adjusted-close observations; affected candidates unavailable')
    records, rejected, rejected_dates = [], Counter(), []
    first_day = last_day = None
    for index, timestamp in enumerate(timestamps):
        try:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError('Invalid timestamp')
            trading_day = datetime.fromtimestamp(timestamp, zone).date()
        except (ValueError, TypeError, OverflowError, OSError):
            rejected['invalid_timestamp'] += 1
            continue
        first_day = min(first_day or trading_day, trading_day)
        last_day = max(last_day or trading_day, trading_day)
        if (last_day - first_day).days > MAX_CHART_SPAN_DAYS:
            raise ValueError('Market date-span limit exceeded')
        try:
            row = {'date': trading_day.isoformat()}
            row.update({key: quote[key][index] for key in ('open', 'high', 'low', 'close', 'volume')})
            row = normalize_daily_prices(symbol, [row])[0]
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError):
            rejected['invalid_or_missing_ohlcv_or_timestamp'] += 1
            rejected_dates.append(trading_day.isoformat())
            continue
        # A daily bar dated today may still be intraday. Without a validated
        # session calendar, only retain same-day bars after the provider's
        # reported regular-session end. Never infer a close from the schedule.
        if date.fromisoformat(row['date']) >= now.astimezone(zone).date():
            periods = meta.get('currentTradingPeriod')
            regular = periods.get('regular') if isinstance(periods, dict) else None
            regular_end = regular.get('end') if isinstance(regular, dict) else None
            try:
                end_day = datetime.fromtimestamp(regular_end, zone).date()
            except (ValueError, TypeError, OverflowError, OSError):
                end_day = None
            if (date.fromisoformat(row['date']) > now.astimezone(zone).date()
                    or isinstance(regular_end, bool) or not isinstance(regular_end, (int, float))
                    or not math.isfinite(regular_end) or now.timestamp() < regular_end
                    or end_day != trading_day):
                rejected['future_or_unconfirmed_session_close'] += 1
                rejected_dates.append(trading_day.isoformat())
                continue
        if candidates:
            if index < len(candidates) and valid_adjusted[index]:
                row['provider_adjusted_close'] = float(candidates[index])
        records.append(row)
    if len({row['date'] for row in records}) != len(records):
        raise ValueError('Duplicate trading date')
    records.sort(key=lambda row: row['date'])
    events = result.get('events')
    if events is not None and not isinstance(events, dict):
        raise ValueError('Invalid corporate-action events')
    events = events or {}
    for kind in ('splits', 'dividends'):
        if kind in events and not isinstance(events[kind], dict):
            raise ValueError('Invalid corporate-action events')
        if len(events.get(kind, {})) > MAX_CHART_OBSERVATIONS:
            raise ValueError('Market corporate-action limit exceeded')
        if any(not isinstance(event, dict) for event in events.get(kind, {}).values()):
            raise ValueError('Invalid corporate-action event entry')
    if rejected:
        warnings.append(f'{sum(rejected.values())} market observations rejected; no values filled')
    if len(records) < 252:
        warnings.append('Fewer than 252 valid price observations; one trading year is not established')
    warnings.append('Corporate-action completeness and provider close adjustment methodology are unverified')
    return {
        'symbol': symbol, 'provider': 'Yahoo Finance chart endpoint (prototype)',
        'retrieved_at_utc': now.astimezone(timezone.utc).isoformat(),
        'currency': currency.upper(), 'price_type': 'unadjusted', 'records': records,
        'source_metadata': {
            'exchange_timezone': exchange_zone, 'exchange': meta.get('exchangeName'),
            'date_basis': date_basis, 'timestamp_unit': 'seconds since Unix epoch',
            'requested_range': '1y', 'interval': '1d', 'received_observations': len(timestamps),
            'rejected_observations': sum(rejected.values()), 'rejection_reasons': dict(rejected),
            'rejected_dates': sorted(set(rejected_dates)),
            'unmatched_ohlcv_values': {key: max(0, len(quote.get(key) or []) - len(timestamps))
                                      for key in ('open', 'high', 'low', 'close', 'volume')},
        },
        'adjustment': {
            'status': 'unverified; provider adjusted close is not used in calculations',
            'candidate_available': any(valid_adjusted), 'invalid_candidate_observations': invalid_adjusted,
            'candidate_complete': bool(records) and len(candidates) == len(timestamps) and invalid_adjusted == 0,
            'total_return': False,
        },
        'corporate_actions': {'splits': list(events.get('splits', {}).values()),
                              'dividends': list(events.get('dividends', {}).values()),
                              'coverage': 'unverified'},
        'quality_warnings': warnings,
    }
