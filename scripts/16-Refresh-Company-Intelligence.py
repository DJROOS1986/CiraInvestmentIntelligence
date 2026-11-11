"""CIRA Phase 5: repeatable local company intelligence refresh."""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "company-intelligence"
TICKERS = __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["active_tickers"]()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def build_reports():
    from datetime import datetime, timezone
    from uuid import uuid4
    run_id = uuid4().hex
    generated_at = datetime.now(timezone.utc).isoformat()
    bcg = load_module(
        "cira_bcg_refresh",
        ROOT / "portfolio-engine" / "bcg_integration.py",
    )
    engine = load_module(
        "cira_company_refresh",
        ROOT / "portfolio-engine" / "company_intelligence.py",
    )

    database = bcg.load_bcg_database(
        ROOT / "ingestion" / "bcg-research" / "bcg_research.json"
    )

    reports = {}

    for ticker in TICKERS:
        try:
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

            reports[ticker] = engine.build_company_intelligence(
                ticker, financial, prices, market, assessment, run_id=run_id
            )
            reports[ticker]['generated_at_utc'] = generated_at
        except Exception as exc:  # per-company: exclude and continue
            __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["exclude"](ticker, "company-intelligence", exc)
            continue

    return reports


def main():
    # Build and validate both reports before writing anything.
    reports = build_reports()

    OUTPUT.mkdir(parents=True, exist_ok=True)

    staged = []

    try:
        for ticker, report in reports.items():
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json.tmp",
                prefix=f"{ticker}-",
                dir=OUTPUT,
                delete=False,
            ) as handle:
                json.dump(
                    report,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                handle.write("\n")
                staged.append(
                    (
                        Path(handle.name),
                        OUTPUT / f"{ticker}-company-intelligence.json",
                    )
                )

        # Each individual replacement is atomic on the same filesystem.
        for temporary, destination in staged:
            os.replace(temporary, destination)
            print(f"REFRESHED: {destination}")

    finally:
        for temporary, _ in staged:
            if temporary.exists():
                temporary.unlink()

    print("\nCIRA INTELLIGENCE REFRESH SUCCESS")
    print(
        "Note: individual replacements are atomic; "
        "the two-report batch is not transactional."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CIRA REFRESH FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
