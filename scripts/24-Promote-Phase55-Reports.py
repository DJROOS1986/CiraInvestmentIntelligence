"""CIRA Phase 5.5 local report promotion.

Default: validation only.
Promotion requires --promote and --confirm-local-replacement.
No Azure operations.
"""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[1]
TICKERS = ("AAPL", "MSFT")
REPORT_DIR = pathlib.Path("reports/company-intelligence")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_path(base, ticker):
    return base / REPORT_DIR / (
        f"{ticker}-company-intelligence.json"
    )


def validate(stage):
    metadata_path = stage / "staging-validation.json"

    if not metadata_path.is_file():
        raise FileNotFoundError(metadata_path)

    metadata = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )

    if metadata.get("status") != "validated_not_promoted":
        raise ValueError("Staging status is not valid")

    run_id = metadata.get("run_id")

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("Missing staging run ID")

    for ticker in TICKERS:
        original = report_path(ROOT, ticker)
        staged = report_path(stage, ticker)

        if not original.is_file() or not staged.is_file():
            raise FileNotFoundError(
                f"Missing original or staged report: {ticker}"
            )

        expected_original = metadata["original_sha256"][ticker]
        expected_staged = metadata["staged_sha256"][ticker]

        if sha256(original) != expected_original:
            raise ValueError(
                f"Original report changed since staging: {ticker}"
            )

        if sha256(staged) != expected_staged:
            raise ValueError(
                f"Staged report integrity mismatch: {ticker}"
            )

        document = json.loads(
            staged.read_text(encoding="utf-8")
        )

        if document.get("ticker") != ticker:
            raise ValueError(f"Ticker mismatch: {ticker}")

        if document.get("schema_version") != "1.0":
            raise ValueError(f"Schema mismatch: {ticker}")

        if document.get("run_id") != run_id:
            raise ValueError(f"Run ID mismatch: {ticker}")

        quality = document.get("data_quality")

        if not isinstance(quality, dict):
            raise ValueError(f"Missing data quality: {ticker}")

        if quality.get("independently_verified_bcg") is not False:
            raise ValueError(f"Invalid BCG verification: {ticker}")

        if quality.get("investment_recommendation") is not None:
            raise ValueError(f"Unexpected recommendation: {ticker}")

    return metadata


def promote(stage, metadata):
    backup = (
        ROOT / ".phase55-backups"
        / (
            "promotion-"
            + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%SZ"
            )
            + "-"
            + uuid4().hex[:8]
        )
    )

    backup.mkdir(parents=True, exist_ok=False)

    # Preserve originals before attempting replacement.
    for ticker in TICKERS:
        source = report_path(ROOT, ticker)
        destination = report_path(backup, ticker)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

        if sha256(destination) != metadata["original_sha256"][ticker]:
            raise RuntimeError(f"Backup verification failed: {ticker}")

    prepared = {}

    try:
        # Prepare replacement files on the destination filesystem.
        for ticker in TICKERS:
            destination = report_path(ROOT, ticker)
            staged = report_path(stage, ticker)

            fd, temporary = tempfile.mkstemp(
                prefix=f".cira-{ticker}-",
                suffix=".tmp",
                dir=destination.parent,
            )

            os.close(fd)
            temporary = pathlib.Path(temporary)
            prepared[ticker] = temporary

            shutil.copyfile(staged, temporary)

            if sha256(temporary) != metadata["staged_sha256"][ticker]:
                raise RuntimeError(
                    f"Prepared report hash mismatch: {ticker}"
                )

        # Recheck originals immediately before replacement.
        for ticker in TICKERS:
            if sha256(report_path(ROOT, ticker)) != (
                metadata["original_sha256"][ticker]
            ):
                raise RuntimeError(
                    f"Original changed before promotion: {ticker}"
                )

        # Individual replacements are atomic on the same filesystem.
        # The pair is protected by rollback, not one atomic transaction.
        for ticker in TICKERS:
            os.replace(
                prepared[ticker],
                report_path(ROOT, ticker),
            )

        for ticker in TICKERS:
            if sha256(report_path(ROOT, ticker)) != (
                metadata["staged_sha256"][ticker]
            ):
                raise RuntimeError(
                    f"Post-promotion hash mismatch: {ticker}"
                )

        print("LOCAL PROMOTION: PASS")
        print("Backup:", backup)
        print("Run ID:", metadata["run_id"])

    except Exception:
        print("PROMOTION FAILED - ATTEMPTING ROLLBACK")

        rollback_errors = []

        for ticker in TICKERS:
            try:
                original_backup = report_path(backup, ticker)
                destination = report_path(ROOT, ticker)

                if original_backup.is_file():
                    shutil.copy2(original_backup, destination)

                    if sha256(destination) != (
                        metadata["original_sha256"][ticker]
                    ):
                        raise RuntimeError(
                            f"Rollback hash mismatch: {ticker}"
                        )
            except Exception as exc:
                rollback_errors.append(f"{ticker}: {exc}")

        if rollback_errors:
            raise RuntimeError(
                "ROLLBACK INCOMPLETE: "
                + "; ".join(rollback_errors)
                + f". Recovery backup: {backup}"
            )

        print("ROLLBACK: Original reports restored")
        raise

    finally:
        for temporary in prepared.values():
            if temporary.exists():
                temporary.unlink()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--stage",
        type=pathlib.Path,
        required=True,
    )

    parser.add_argument(
        "--promote",
        action="store_true",
    )

    parser.add_argument(
        "--confirm-local-replacement",
        action="store_true",
    )

    args = parser.parse_args()

    if args.confirm_local_replacement and not args.promote:
        parser.error(
            "--confirm-local-replacement requires --promote"
        )

    if args.promote and not args.confirm_local_replacement:
        parser.error(
            "Promotion requires --confirm-local-replacement"
        )

    stage = args.stage.resolve()

    if not stage.is_dir():
        raise FileNotFoundError(stage)

    metadata = validate(stage)

    print("=== CIRA PHASE 5.5 PROMOTION ===")
    print("Staging directory:", stage)
    print("Run ID:", metadata["run_id"])

    for ticker in TICKERS:
        print(f"{ticker}: HASH AND SCHEMA VALIDATION PASS")

    if not args.promote:
        print()
        print("PROMOTION PREFLIGHT: PASS")
        print("MODE: VALIDATION ONLY")
        print("Reports replaced: NO")
        print("Backups created: NO")
        print("Azure operations: NONE")
        return

    promote(stage, metadata)


if __name__ == "__main__":
    main()