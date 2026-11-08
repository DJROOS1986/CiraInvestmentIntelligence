"""CIRA Phase 5.5 safe local promotion.

Default: validation only.
Promotion requires explicit flags.
No Azure operations.

Recovery is conservative: uncertain states require manual review.
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
RELATIVE = pathlib.Path("reports/company-intelligence")
LOCK = ROOT / ".phase55-promotion.lock"
JOURNAL = ROOT / ".phase55-promotion-journal.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_path(base, ticker):
    return base / RELATIVE / f"{ticker}-company-intelligence.json"


def durable_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=".cira-journal-",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate(stage):
    metadata_file = stage / "staging-validation.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

    if metadata.get("status") != "validated_not_promoted":
        raise ValueError("Invalid staging status")

    run_id = metadata.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("Invalid run ID")

    for ticker in TICKERS:
        original = report_path(ROOT, ticker)
        staged = report_path(stage, ticker)

        if not original.is_file() or not staged.is_file():
            raise FileNotFoundError(ticker)

        if sha256(original) != metadata["original_sha256"][ticker]:
            raise ValueError(f"Original hash mismatch: {ticker}")

        if sha256(staged) != metadata["staged_sha256"][ticker]:
            raise ValueError(f"Staged hash mismatch: {ticker}")

        document = json.loads(staged.read_text(encoding="utf-8"))

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
            raise ValueError(f"Invalid BCG flag: {ticker}")

        if quality.get("investment_recommendation") is not None:
            raise ValueError(f"Unexpected recommendation: {ticker}")

    return metadata


def acquire_lock():
    fd = os.open(
        str(LOCK),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())


def promote(stage, metadata):
    if JOURNAL.exists():
        raise RuntimeError(
            "Existing recovery journal. Manual review required."
        )

    acquire_lock()
    backup = None
    prepared = {}
    journal = None

    try:
        # Revalidate after acquiring the lock.
        metadata = validate(stage)

        backup = (
            ROOT / ".phase55-backups"
            / (
                "safe-promotion-"
                + datetime.now(timezone.utc).strftime(
                    "%Y%m%dT%H%M%SZ"
                )
                + "-"
                + uuid4().hex[:8]
            )
        )
        backup.mkdir(parents=True, exist_ok=False)

        for ticker in TICKERS:
            source = report_path(ROOT, ticker)
            destination = report_path(backup, ticker)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

            if sha256(destination) != metadata["original_sha256"][ticker]:
                raise RuntimeError(f"Backup verification failed: {ticker}")

        for ticker in TICKERS:
            destination = report_path(ROOT, ticker)
            staged = report_path(stage, ticker)

            fd, name = tempfile.mkstemp(
                prefix=f".cira-{ticker}-",
                suffix=".tmp",
                dir=destination.parent,
            )
            os.close(fd)
            prepared[ticker] = pathlib.Path(name)
            shutil.copyfile(staged, prepared[ticker])

            if sha256(prepared[ticker]) != metadata["staged_sha256"][ticker]:
                raise RuntimeError(f"Prepared hash mismatch: {ticker}")

        journal = {
            "status": "prepared",
            "run_id": metadata["run_id"],
            "backup": str(backup),
            "original_sha256": metadata["original_sha256"],
            "staged_sha256": metadata["staged_sha256"],
            "replaced": [],
        }
        durable_json(JOURNAL, journal)

        for ticker in TICKERS:
            destination = report_path(ROOT, ticker)

            if sha256(destination) != metadata["original_sha256"][ticker]:
                raise RuntimeError(
                    f"Concurrent modification detected: {ticker}"
                )

            journal["status"] = f"replacing_{ticker}"
            durable_json(JOURNAL, journal)

            os.replace(prepared[ticker], destination)
            journal["replaced"].append(ticker)
            durable_json(JOURNAL, journal)

        for ticker in TICKERS:
            if sha256(report_path(ROOT, ticker)) != (
                metadata["staged_sha256"][ticker]
            ):
                raise RuntimeError(f"Final hash mismatch: {ticker}")

        journal["status"] = "complete"
        durable_json(JOURNAL, journal)

        print("SAFE LOCAL PROMOTION: PASS")
        print("Backup:", backup)
        print("Run ID:", metadata["run_id"])

    except Exception:
        if journal is not None:
            journal["status"] = "recovery_required"
            durable_json(JOURNAL, journal)

        print("PROMOTION FAILED")
        print("Recovery journal:", JOURNAL)
        print("No automatic rollback of uncertain states.")
        raise

    finally:
        for path in prepared.values():
            if path.exists():
                path.unlink()

        # Retain the journal for audit/recovery if created.
        # Do not remove the lock after an interrupted/failed promotion.
        if journal is None or journal.get("status") == "complete":
            if LOCK.exists():
                LOCK.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=pathlib.Path, required=True)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument(
        "--confirm-local-replacement", action="store_true"
    )
    args = parser.parse_args()

    if args.confirm_local_replacement and not args.promote:
        parser.error("Confirmation requires --promote")

    if args.promote and not args.confirm_local_replacement:
        parser.error("Promotion requires explicit confirmation")

    stage = args.stage.resolve()
    metadata = validate(stage)

    print("=== CIRA SAFE PROMOTION ===")
    print("Stage:", stage)
    print("Run ID:", metadata["run_id"])

    if not args.promote:
        print("PREFLIGHT: PASS")
        print("MODE: VALIDATION ONLY")
        print("Reports replaced: NO")
        print("Azure operations: NONE")
        return

    promote(stage, metadata)


if __name__ == "__main__":
    main()