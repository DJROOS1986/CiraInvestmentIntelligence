"""CIRA Phase 5: BCG research integration."""

import json
from pathlib import Path


COMPANY_ALIASES = {c["ticker"]: c["bcg_name"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"] if c.get("bcg_name")}

VALID_CLASSES = {
    "Star",
    "Cash Cow",
    "Question Mark",
    "Dog",
}


def load_bcg_database(path):
    """Load and validate the BCG research database."""
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("BCG database must be an object")

    companies = data.get("companies")

    if not isinstance(companies, list):
        raise ValueError("BCG companies must be a list")

    if not all(isinstance(item, dict) for item in companies):
        raise ValueError("Invalid BCG company record")

    return data


def find_company(data, ticker):
    """Match an approved ticker to a BCG company."""
    ticker = ticker.upper().strip()

    company_name = COMPANY_ALIASES.get(ticker)

    if company_name is None:
        return None

    matches = [
        item
        for item in data["companies"]
        if item.get("company", "").casefold()
        == company_name.casefold()
    ]

    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous BCG company match: {company_name}"
        )

    return matches[0] if matches else None


def integrate_bcg(ticker, data):
    """Create a research-only BCG assessment."""
    ticker = ticker.upper().strip()
    record = find_company(data, ticker)

    result = {
        "ticker": ticker,
        "research_available": record is not None,
        "verified_bcg_class": None,
        "investment_recommendation": None,
        "independently_verified": False,
        "classification_origin": "user-supplied research" if record else "unavailable",
        "provenance": {key: data.get(key) for key in (
            'dataset', 'source_file', 'source_sheet', 'source_summary_date', 'imported_on', 'cautions')},
        "verification_note": "No independent evidence of an official BCG assessment",
    }

    if record is None:
        result["status"] = "Research unavailable"
        return result

    rule_class = record.get("rule_based_class")
    evidence = record.get("evidence_status")

    verified = (
        rule_class in VALID_CLASSES
        and evidence == "Classified"
        and isinstance(record.get("relative_share_x"), (int, float))
        and not isinstance(record.get("relative_share_x"), bool)
    )

    result.update({
        "company": record.get("company"),
        "theme": record.get("theme"),
        "research_class": record.get("html_class"),
        "rule_based_class": rule_class,
        "rule_class_origin": "Rule-based classification imported from the user workbook",
        "evidence_status": evidence,
        "market_growth_pct": record.get("market_growth_pct"),
        "market_share_pct": record.get("market_share_pct"),
        "relative_share_x": record.get("relative_share_x"),
        "research_score": record.get("star_score"),
        "quality_tier": record.get("quality_tier"),
        # Legacy field retained for older readers; this is NOT independent verification.
        "verified_bcg_class": rule_class if verified else None,
        "status": (
            "Evidence-classified (source-reported)"
            if verified else "Research only - verification required"
        ),
        "notes": record.get("notes"),
    })

    return result
