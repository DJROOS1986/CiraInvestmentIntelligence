"""CIRA Phase 5 cloud integration candidate.

Dry-run only. No network access, Azure uploads, or market fetching.
Validates a fresh isolated build of market analytics and company
intelligence from existing input snapshots.
"""

import argparse
import json
import runpy
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TICKERS = ("AAPL", "MSFT")

INPUTS = (
    "ingestion/bcg-research/bcg_research.json",
    "portfolio-engine/market_analytics.py",
    "portfolio-engine/bcg_integration.py",
    "portfolio-engine/company_intelligence.py",
    "scripts/14-Analyze-Market-Prices.py",
    "scripts/16-Refresh-Company-Intelligence.py",
)

for_ticker = (
    ("financial", "financial-report"),
    ("market-data", "daily-prices"),
)


def prepare_workspace(workspace):
    files = list(INPUTS)

    for ticker in TICKERS:
        for folder, suffix in for_ticker:
            files.append(
                f"reports/{folder}/{ticker}-{suffix}.json"
            )

    for relative in files:
        source = ROOT / relative

        if not source.is_file():
            raise FileNotFoundError(relative)

        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def execute(workspace, script):
    path = workspace / "scripts" / script
    print(f"RUNNING: {script}", flush=True)

    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(
                f"Stage failed: {script} ({exc.code})"
            ) from exc


def verify_report(path, ticker):
    with path.open(encoding="utf-8") as handle:
        report = json.load(handle)

    if report.get("ticker") != ticker:
        raise ValueError(f"Ticker mismatch: {ticker}")

    if report.get("schema_version") != "1.0":
        raise ValueError(f"Invalid schema: {ticker}")

    quality = report.get("data_quality")

    if not isinstance(quality, dict):
        raise ValueError(f"Missing quality metadata: {ticker}")

    if quality.get("independently_verified_bcg") is not False:
        raise ValueError(f"BCG verification error: {ticker}")

    if quality.get("investment_recommendation") is not None:
        raise ValueError(
            f"Unexpected investment recommendation: {ticker}"
        )

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Only supported mode; no cloud operations",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(
        prefix="cira-phase5-cloud-dryrun-"
    ) as directory:
        workspace = Path(directory)
        prepare_workspace(workspace)

        execute(workspace, "14-Analyze-Market-Prices.py")
        execute(workspace, "16-Refresh-Company-Intelligence.py")

        print("\n=== VALIDATED PUBLISHING MANIFEST ===")

        for ticker in TICKERS:
            relative = (
                "company-intelligence/"
                f"{ticker}-company-intelligence.json"
            )
            path = workspace / "reports" / relative
            report = verify_report(path, ticker)

            print(
                f"READY: financial-intelligence/{relative}"
                f" | warnings={len(report['data_quality']['warnings'])}"
            )

        print("\nCIRA PHASE 5 CLOUD DRY-RUN SUCCESS")
        print("No files published to Azure.")
        print("Original reports unchanged.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CIRA PHASE 5 FAILED: {exc}", file=sys.stderr)
        sys.exit(1)