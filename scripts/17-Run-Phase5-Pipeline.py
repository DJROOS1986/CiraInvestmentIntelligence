"""CIRA Phase 5 local pipeline candidate.

Runs market analytics and combined intelligence in an isolated
workspace. No SEC requests, market requests or Azure uploads.
"""

import argparse
import json
import runpy
import shutil
import sys
import tempfile
from pathlib import Path


REQUIRED_INPUTS = (
    "reports/financial/AAPL-financial-report.json",
    "reports/financial/MSFT-financial-report.json",
    "reports/market-data/AAPL-daily-prices.json",
    "reports/market-data/MSFT-daily-prices.json",
    "ingestion/bcg-research/bcg_research.json",
)

REQUIRED_CODE = (
    "portfolio-engine/market_analytics.py",
    "portfolio-engine/bcg_integration.py",
    "portfolio-engine/company_intelligence.py",
    "scripts/14-Analyze-Market-Prices.py",
    "scripts/16-Refresh-Company-Intelligence.py",
)


def copy_inputs(source, workspace):
    for relative in REQUIRED_INPUTS + REQUIRED_CODE:
        original = source / relative

        if not original.is_file():
            raise FileNotFoundError(
                f"Required pipeline input missing: {relative}"
            )

        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)


def run_stage(workspace, script):
    path = workspace / "scripts" / script
    print(f"\n=== RUNNING {script} ===", flush=True)

    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(
                f"Pipeline stage failed: {script} ({exc.code})"
            ) from exc


def validate_outputs(workspace):
    for ticker in ("AAPL", "MSFT"):
        path = (
            workspace / "reports" / "company-intelligence"
            / f"{ticker}-company-intelligence.json"
        )

        with path.open(encoding="utf-8") as handle:
            report = json.load(handle)

        if report.get("ticker") != ticker:
            raise ValueError(f"Ticker mismatch: {ticker}")

        if report.get("schema_version") != "1.0":
            raise ValueError(f"Schema mismatch: {ticker}")

        quality = report.get("data_quality", {})

        if quality.get("independently_verified_bcg") is not False:
            raise ValueError(
                f"Invalid BCG verification flag: {ticker}"
            )

        if quality.get("investment_recommendation") is not None:
            raise ValueError(
                f"Unexpected investment recommendation: {ticker}"
            )

        print(
            f"VALIDATED: {ticker}, "
            f"warnings={len(quality.get('warnings', []))}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        required=True,
        type=Path,
    )
    args = parser.parse_args()

    source = args.source_root.resolve()

    with tempfile.TemporaryDirectory(
        prefix="cira-phase5-pipeline-"
    ) as directory:
        workspace = Path(directory)

        print("Creating isolated pipeline workspace...")
        copy_inputs(source, workspace)

        run_stage(
            workspace,
            "14-Analyze-Market-Prices.py",
        )
        run_stage(
            workspace,
            "16-Refresh-Company-Intelligence.py",
        )

        validate_outputs(workspace)

        print("\nCIRA PHASE 5 LOCAL PIPELINE SUCCESS")
        print("No Azure operations performed.")
        print("Original reports unchanged.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PIPELINE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)