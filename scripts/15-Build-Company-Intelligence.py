"""Generate CIRA combined company intelligence reports."""

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main():
    bcg = load_module(
        "cira_bcg",
        ROOT / "portfolio-engine" / "bcg_integration.py",
    )
    engine = load_module(
        "cira_company_intelligence",
        ROOT / "portfolio-engine" / "company_intelligence.py",
    )

    database = bcg.load_bcg_database(
        ROOT / "ingestion" / "bcg-research" / "bcg_research.json"
    )

    output = ROOT / "reports" / "company-intelligence"
    pending = []

    for ticker in ("AAPL", "MSFT"):
        destination = output / f"{ticker}-company-intelligence.json"

        if destination.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing report: {destination}"
            )

        financial = read_json(
            ROOT / "reports" / "financial"
            / f"{ticker}-financial-report.json"
        )
        prices = read_json(
            ROOT / "reports" / "market-data"
            / f"{ticker}-daily-prices.json"
        )
        market = read_json(
            ROOT / "reports" / "market-analysis"
            / f"{ticker}-market-analysis.json"
        )

        assessment = bcg.integrate_bcg(ticker, database)

        report = engine.build_company_intelligence(
            ticker, financial, prices, market, assessment
        )

        pending.append((destination, report))

    output.mkdir(parents=True, exist_ok=True)

    created = []

    try:
        for destination, report in pending:
            with destination.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
                handle.write("\n")

            created.append(destination)

    except Exception:
        for destination in created:
            destination.unlink()
        raise

    for destination, report in pending:
        print(f"\nTicker: {report['ticker']}")
        print(f"Company: {report['company']}")
        print(
            "BCG status:",
            report["bcg"]["status"],
        )
        print(
            "BCG score:",
            report["bcg"].get("research_score"),
        )
        print(
            "Latest market date:",
            report["market"]["last_date"],
        )
        print(
            "Warnings:",
            len(report["data_quality"]["warnings"]),
        )
        print("Saved:", destination)

    print("\nCIRA COMBINED INTELLIGENCE SUCCESS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)