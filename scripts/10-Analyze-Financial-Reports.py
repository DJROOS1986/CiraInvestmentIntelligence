import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "reports" / "financial"
OUTPUT = ROOT / "reports" / "analysis"
OUTPUT.mkdir(parents=True, exist_ok=True)

def divide(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 6)

companies = []

for ticker in tuple(c["ticker"] for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]):
    path = INPUT / f"{ticker}-financial-report.json"
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    m = report["metrics_usd"]

    revenue = m["revenue"]
    income = m["net_income"]
    assets = m["total_assets"]
    liabilities = m["total_liabilities"]
    fcf = m["free_cash_flow"]

    indicators = {
        "net_profit_margin": divide(income, revenue),
        "free_cash_flow_margin": divide(fcf, revenue),
        "return_on_assets": divide(income, assets),
        "liabilities_to_assets": divide(liabilities, assets),
        "net_assets_usd": (
            assets - liabilities
            if assets is not None and liabilities is not None
            else None
        ),
        "free_cash_flow_usd": fcf,
    }

    flags = []
    if income is not None and income < 0:
        flags.append("Negative net income")
    if fcf is not None and fcf < 0:
        flags.append("Negative free cash flow")

    leverage = indicators["liabilities_to_assets"]
    if leverage is not None and leverage > 0.8:
        flags.append("Liabilities exceed 80% of assets")

    companies.append({
        "ticker": ticker,
        "company": report["company"],
        "period_end": report["period_end"],
        "currency": report["currency"],
        "indicators": indicators,
        "risk_flags": flags,
    })

result = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "methodology": (
        "Descriptive ratios derived from SEC financial data. "
        "Risk flags are simple screening thresholds, not "
        "comprehensive risk assessments or investment advice."
    ),
    "companies": companies,
}

json_path = OUTPUT / "company-comparison.json"
json_path.write_text(
    json.dumps(result, indent=2),
    encoding="utf-8"
)

lines = ["CIRA FINANCIAL COMPARISON", "=" * 35, ""]

for company in companies:
    lines.append(
        f"{company['company']} ({company['ticker']})"
    )
    lines.append(f"Fiscal period: {company['period_end']}")

    for name, value in company["indicators"].items():
        if name in (
            "net_profit_margin",
            "free_cash_flow_margin",
            "return_on_assets",
            "liabilities_to_assets",
        ):
            display = (
                f"{value * 100:.2f}%"
                if value is not None else "N/A"
            )
        else:
            display = (
                f"${value:,.0f}"
                if value is not None else "N/A"
            )
        lines.append(f"  {name}: {display}")

    lines.append(
        "  Screening flags: " +
        (", ".join(company["risk_flags"])
         if company["risk_flags"] else "None")
    )
    lines.append("")

text_path = OUTPUT / "company-comparison.txt"
text_path.write_text(
    "\n".join(lines),
    encoding="utf-8"
)

print("FINANCIAL ANALYSIS: SUCCESS")
print(f"JSON: {json_path}")
print(f"Text: {text_path}")
