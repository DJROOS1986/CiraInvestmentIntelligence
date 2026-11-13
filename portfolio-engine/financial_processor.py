import json
from datetime import date
import hashlib
import math
import re
from pathlib import Path

TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities"
    ],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets"
    ],
}

INSTANT = {"total_assets", "total_liabilities"}


DERIVED_TOLERANCE = 0.001
EQUITY_TAGS = (
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquity",
)


def fact_reference(item, tag, currency, cik=None):
    """Describe an SEC fact without changing its reported value or scale."""
    accession = item.get('accn')
    filing_url = None
    if str(cik).isdigit() and re.fullmatch(r'\d{10}-\d{2}-\d{6}', str(accession)):
        filing_url = (f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/'
                      f'{accession.replace("-", "")}/')
    return {'tag': tag, 'namespace': 'us-gaap', 'form': item.get('form'),
            'filed': item.get('filed'), 'period_end': item.get('end'),
            'start': item.get('start'), 'accession': accession,
            'filing_url': filing_url, 'unit': currency, 'scale': 1,
            'reported_value': item.get('val'),
            'period_type': 'duration' if item.get('start') else 'instant'}


def _instant_value(facts, tag, period_end, currency="USD"):
    """Latest-filed 10-K balance-sheet value of a tag at period_end, or None."""
    best = None
    for item in facts.get(tag, {}).get("units", {}).get(currency, []):  # instant currency
        if item.get("form") not in ("10-K", "10-K/A", "20-F", "20-F/A") or item.get("val") is None:
            continue
        if item.get("end") != period_end or item.get("start") is not None or not item.get("filed"):
            continue
        if isinstance(item['val'], bool) or not isinstance(item['val'], (int, float)) or not math.isfinite(item['val']):
            raise ValueError(f'Invalid reported financial value: {tag}')
        if best is None or (item["filed"], item.get("accn", "")) > (best["filed"], best.get("accn", "")):
            best = item
    return best


def derive_total_liabilities(facts, period_end, currency="USD", cik=None):
    """Current + non-current liabilities, accepted only if it equals total liabilities and equity minus equity."""
    current = _instant_value(facts, "LiabilitiesCurrent", period_end, currency)
    noncurrent = _instant_value(facts, "LiabilitiesNoncurrent", period_end, currency)
    total = _instant_value(facts, "LiabilitiesAndStockholdersEquity", period_end, currency)
    if not (current and noncurrent and total):
        return None
    summed = current["val"] + noncurrent["val"]
    if summed <= 0:
        return None
    for equity_tag in EQUITY_TAGS:
        equity = _instant_value(facts, equity_tag, period_end, currency)
        if equity and abs(summed - (total["val"] - equity["val"])) <= DERIVED_TOLERANCE * summed:
            return summed, {
                "tag": "derived: LiabilitiesCurrent + LiabilitiesNoncurrent",
                "cross_check": f"LiabilitiesAndStockholdersEquity - {equity_tag}",
                "filed": current["filed"],
                "period_end": period_end,
                "start": None,
                "accession": current.get("accn"),
                "unit": currency,
                "scale": 1,
                "components": [fact_reference(item, tag, currency, cik) for tag, item in (
                    ('LiabilitiesCurrent', current), ('LiabilitiesNoncurrent', noncurrent),
                    ('LiabilitiesAndStockholdersEquity', total), (equity_tag, equity))],
            }
    return None


def extract_annual_metrics(companyfacts_path, currency="USD", fx=None):
    with Path(companyfacts_path).open(
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    facts = data.get("facts", {}).get("us-gaap", {})

    def candidates(metric):
        for tag in TAGS[metric]:
            values = facts.get(tag, {}).get(
                "units", {}
            ).get(currency, [])  # reporting currency

            for item in values:
                if item.get("form") not in ("10-K", "10-K/A", "20-F", "20-F/A"):
                    continue
                if item.get("val") is None:
                    continue
                if not item.get("end") or not item.get("filed"):
                    continue
                if isinstance(item['val'], bool) or not isinstance(item['val'], (int, float)) or not math.isfinite(item['val']):
                    raise ValueError(f'Invalid reported financial value: {tag}')

                if metric in INSTANT:
                    if item.get("start") is not None:
                        continue
                else:
                    if not item.get("start"):
                        continue
                    try:
                        days = (
                            date.fromisoformat(item["end"])
                            - date.fromisoformat(item["start"])
                        ).days
                    except ValueError:
                        continue
                    if not 330 <= days <= 380:
                        continue

                yield tag, item

    # Use the latest full-year revenue period as the
    # common reporting date for all financial metrics.
    revenue = list(candidates("revenue"))
    if not revenue:
        raise ValueError("No annual revenue period found")

    period_end = max(item["end"] for _, item in revenue)

    results = {}
    provenance = {}

    for metric in TAGS:
        options = [
            (tag, item)
            for tag, item in candidates(metric)
            if item["end"] == period_end
        ]

        # Prefer configured tag order, then latest filing.
        if options:
            seen = {}
            for tag, item in options:
                identity = (tag, item.get('accn'), item['filed'], item.get('start'), item['end'])
                if identity in seen and seen[identity] != item['val']:
                    raise ValueError(f'Conflicting duplicate SEC facts: {metric}')
                seen[identity] = item['val']
            options.sort(
                key=lambda pair: (
                    -TAGS[metric].index(pair[0]),
                    pair[1]["filed"],
                    pair[1].get("accn", ""),
                ),
                reverse=True,
            )
            tag, selected = options[0]
            results[metric] = selected["val"]
            provenance[metric] = fact_reference(selected, tag, currency, data.get('cik'))
        else:
            results[metric] = None
            provenance[metric] = None

    if results["total_liabilities"] is None:
        derived = derive_total_liabilities(facts, period_end, currency, data.get('cik'))
        if derived is not None:
            results["total_liabilities"], provenance["total_liabilities"] = derived

    reported, fx_info = None, None
    if currency != "USD":
        if fx is None:
            raise ValueError(f"Exchange rates required to convert {currency} financials")
        reported, rates = dict(results), {}
        for metric, value in list(results.items()):
            if value is None:
                continue
            prov = provenance.get(metric) or {}
            if metric in INSTANT:
                rate, basis = fx.closing(currency, period_end), "closing"
            else:
                if not prov.get("start"):
                    raise ValueError(f"Missing period start for {metric}")
                rate, basis = fx.average(currency, prov["start"], prov.get("period_end") or period_end), "average"
            results[metric] = value * rate
            rates[metric] = {"usd_per_unit": rate, "basis": basis}
        fx_info = {"source": fx.source, "currency": currency, "rates": rates}

    ocf = results["operating_cash_flow"]
    capex = results["capital_expenditure"]

    results["free_cash_flow"] = (
        ocf - capex
        if ocf is not None and capex is not None
        else None
    )

    provenance['free_cash_flow'] = {
        'method': 'operating_cash_flow - capital_expenditure (after existing USD conversion)',
        'inputs': ['operating_cash_flow', 'capital_expenditure'], 'unit': 'USD',
        'scale': 1, 'period_end': period_end,
        'available': results['free_cash_flow'] is not None,
    }
    warnings = []
    starts = {p.get('start') for p in provenance.values() if p and p.get('start')}
    if len(starts) > 1:
        warnings.append('Financial flow start dates differ; inspect metric periods before comparison')
    for metric, p in provenance.items():
        components = (p or {}).get('components', [])
        if len({(c.get('filed'), c.get('accession')) for c in components}) > 1:
            warnings.append(f'{metric}: derived components come from different filings')
    for metric, value in results.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value)):
            raise ValueError(f'Invalid reported financial value: {metric}')

    return {
        "company": data.get("entityName"),
        "cik": data.get("cik"),
        "period_end": period_end,
        "currency": "USD",
        "metrics_usd": results,
        "reported_currency": currency,
        "reported_metrics": reported,
        "fx": fx_info,
        "provenance": provenance,
        "source": {
            "provider": "SEC Company Facts", "cik": data.get('cik'),
            "sha256": hashlib.sha256(Path(companyfacts_path).read_bytes()).hexdigest(),
            "selection_method": "Latest annual period; preferred tag then latest filing. Not point-in-time history.",
        },
        "quality_warnings": warnings,
    }
