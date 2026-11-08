import json
from datetime import date
from pathlib import Path

TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities"
    ],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment"
    ],
}

INSTANT = {"total_assets", "total_liabilities"}


def extract_annual_metrics(companyfacts_path):
    with Path(companyfacts_path).open(
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    facts = data.get("facts", {}).get("us-gaap", {})

    def candidates(metric):
        for tag in TAGS[metric]:
            values = facts.get(tag, {}).get(
                "units", {}
            ).get("USD", [])

            for item in values:
                if item.get("form") not in ("10-K", "10-K/A"):
                    continue
                if item.get("val") is None:
                    continue
                if not item.get("end") or not item.get("filed"):
                    continue

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
            provenance[metric] = {
                "tag": tag,
                "filed": selected["filed"],
                "period_end": selected["end"],
                "start": selected.get("start"),
                "accession": selected.get("accn"),
            }
        else:
            results[metric] = None
            provenance[metric] = None

    ocf = results["operating_cash_flow"]
    capex = results["capital_expenditure"]

    results["free_cash_flow"] = (
        ocf - capex
        if ocf is not None and capex is not None
        else None
    )

    return {
        "company": data.get("entityName"),
        "cik": data.get("cik"),
        "period_end": period_end,
        "currency": "USD",
        "metrics_usd": results,
        "provenance": provenance,
    }
