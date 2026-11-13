"""CIRA historical market analytics."""

import math
import statistics
from datetime import date, datetime, timezone


def series_quality(dates, closes, document):
    """Conservative diagnostics, without inventing an exchange holiday calendar.

    60 returns is a disclosure threshold, not a statistical guarantee. A gap
    containing unobserved weekdays is uncertain, not proof of missing sessions:
    no existing integration supplies a verified holiday calendar. Weekend-only
    closures are supported for the current equity universe; holidays are not inferred.
    Large moves flag possible discontinuities; they do not establish a split.
    """
    warnings = list(document.get('quality_warnings') or [])
    gaps = sum((b - a).days > 4 for a, b in zip(dates, dates[1:]))
    # At most six iterations per interval, even for malformed very long spans.
    missing_weekdays = []
    for a, b in zip(dates, dates[1:]):
        weeks, remainder = divmod(max(0, (b - a).days - 1), 7)
        missing_weekdays.append(weeks * 5 + sum(
            (a.weekday() + offset + 1) % 7 < 5 for offset in range(remainder)))
    absent_weekdays = sum(missing_weekdays)
    uncertain = sum(count > 0 for count in missing_weekdays)
    move_dates = [dates[i].isoformat() for i in range(1, len(closes))
                  if abs(closes[i] / closes[i - 1] - 1) >= 0.5]
    moves = len(move_dates)
    splits = []
    for event in (document.get('corporate_actions') or {}).get('splits', []):
        stamp = event.get('date')
        try:
            day = (datetime.fromtimestamp(stamp, timezone.utc).date()
                   if isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                   else date.fromisoformat(stamp))
        except (ValueError, TypeError, OverflowError, OSError):
            raise ValueError('Invalid split event date')
        if dates[0] < day <= dates[-1]:
            splits.append(day.isoformat())
    unsafe = bool(moves or splits)
    if unsafe:
        warnings.append('Split event or extreme price move: historical return and risk estimates withheld pending adjustment validation')
    if gaps:
        warnings.append('Long gaps between observations; session continuity cannot be established')
    if absent_weekdays:
        warnings.append(f'{absent_weekdays} weekdays without observations; may include exchange holidays or missing sessions; daily volatility withheld, no forward fill')
    count = len(closes) - 1
    status = 'descriptive estimate'
    if count < 60:
        status = 'low confidence: fewer than 60 returns'
        warnings.append('Short price history: fewer than 60 observed returns')
    elif count < 252:
        status = 'limited history: fewer than 252 returns'
        warnings.append('Less than one trading year of returns')
    if unsafe or uncertain or count < 2:
        status = 'unavailable: discontinuity, uncertain trading-session continuity, or insufficient returns'
    return {'return_observations': count, 'calendar_span_days': (dates[-1] - dates[0]).days,
            'long_gap_count': gaps, 'extreme_move_count': moves, 'split_dates': splits,
            'extreme_move_dates': move_dates,
            'unobserved_weekdays': absent_weekdays,
            'uncertain_interval_count': uncertain,
            'confirmed_daily_return_observations': count - uncertain,
            'latest_interval_consecutive': bool(missing_weekdays) and missing_weekdays[-1] == 0,
            'continuity_status': 'uncertain' if uncertain else 'consecutive observations or weekend-only closures',
            'historical_returns_available': not unsafe, 'volatility_status': status,
            'volatility_available': not unsafe and not uncertain and count >= 2,
            'calendar_note': 'Observed dates only; exchange holidays and missing sessions are not independently verified'}, warnings


def analyze_prices(document):
    if document.get('price_type') not in (None, 'unadjusted'):
        raise ValueError('Adjusted price methodology has not been validated; cannot calculate adjusted returns')
    records = document["records"]

    if not isinstance(records, list) or len(records) < 2:
        raise ValueError("At least two daily records are required")

    records = sorted(records, key=lambda row: row["date"])

    dates = [date.fromisoformat(row["date"]) for row in records]

    if len(set(dates)) != len(dates):
        raise ValueError("Duplicate trading dates")

    if any(isinstance(row['close'], bool) or not isinstance(row['close'], (int, float)) for row in records):
        raise ValueError('Closing prices must be numeric')
    closes = [float(row["close"]) for row in records]

    if any(not math.isfinite(x) or x <= 0 for x in closes):
        raise ValueError("Closing prices must be finite and positive")

    returns = [
        (closes[i] / closes[i - 1]) - 1
        for i in range(1, len(closes))
    ]
    quality, warnings = series_quality(dates, closes, document)

    def sma(window):
        if len(closes) < window:
            return None
        start = dates[-window].isoformat()
        affected = quality['split_dates'] + quality['extreme_move_dates']
        if any(start < day <= dates[-1].isoformat() for day in affected):
            return None
        return round(statistics.mean(closes[-window:]), 4)

    volatility = None

    if quality['volatility_available']:
        volatility = (
            statistics.stdev(returns) * math.sqrt(252) * 100
        )
    averages = {window: sma(window) for window in (5, 20)}
    quality['moving_average_status'] = {
        str(window): ('available' if averages[window] is not None else
                      'unavailable: insufficient observations or a discontinuity inside this window')
        for window in averages}

    return {
        "symbol": document["symbol"],
        "provider": document.get("provider"),
        "currency": document.get("currency"),
        "price_type": document.get("price_type"),
        "first_date": records[0]["date"],
        "last_date": records[-1]["date"],
        "observations": len(closes),
        "latest_close": closes[-1],
        "daily_return_pct": (round(returns[-1] * 100, 4)
                             if quality['historical_returns_available'] and quality['latest_interval_consecutive'] else None),
        "period_price_change_pct": round(
            ((closes[-1] / closes[0]) - 1) * 100, 4
        ) if quality['historical_returns_available'] else None,
        "sma_5": averages[5],
        "sma_20": averages[20],
        "annualized_volatility_pct": (
            round(volatility, 4)
            if volatility is not None
            else None
        ),
        "annualization_trading_days": 252,
        "return_basis": "unadjusted_close",
        "quality": quality,
        "quality_warnings": warnings,
        "note": (
            "Historical descriptive analytics only. "
            "Unadjusted prices exclude dividend adjustments "
            "and may be affected by corporate actions."
        ),
    }
