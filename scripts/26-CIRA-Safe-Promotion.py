"""CIRA safe local report promotion.

Default mode: read-only validation.
No Azure imports, authentication, uploads, or deployments.
"""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
TICKERS = ("AAPL", "MSFT")
REPORTS = pathlib.Path("reports/company-intelligence")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_path(root, ticker):
    return root / REPORTS / f"{ticker}-company-intelligence.json"


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".cira-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate(root, stage):
    metadata_path = stage / "staging-validation.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    if metadata.get("status") != "validated_not_promoted":
        raise ValueError("Invalid staging status")

    run_id = metadata.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("Missing run ID")

    for ticker in TICKERS:
        original = report_path(root, ticker)
        staged = report_path(stage, ticker)

        if not original.is_file() or not staged.is_file():
            raise FileNotFoundError(ticker)

        if digest(original) != metadata["original_sha256"][ticker]:
            raise ValueError(f"Original changed: {ticker}")

        if digest(staged) != metadata["staged_sha256"][ticker]:
            raise ValueError(f"Staged report changed: {ticker}")

        report = json.loads(staged.read_text(encoding="utf-8"))
        if report.get("ticker") != ticker:
            raise ValueError(f"Ticker mismatch: {ticker}")
        if report.get("schema_version") != "1.0":
            raise ValueError(f"Schema mismatch: {ticker}")
        if report.get("run_id") != run_id:
            raise ValueError(f"Run ID mismatch: {ticker}")

        quality = report.get("data_quality")
        if not isinstance(quality, dict):
            raise ValueError(f"Missing quality metadata: {ticker}")
        if quality.get("independently_verified_bcg") is not False:
            raise ValueError(f"Invalid BCG flag: {ticker}")
        if quality.get("investment_recommendation") is not None:
            raise ValueError(f"Unexpected recommendation: {ticker}")

    return metadata


class PromotionLock:
    def __init__(self, root):
        self.path = root / ".phase55-promotion.lock"
        self.owned = False

    def __enter__(self):
        fd = os.open(
            self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        self.owned = True
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.owned:
            self.path.unlink(missing_ok=True)


def promote(root, stage):
    with PromotionLock(root):
        journal_path = root / ".phase55-promotion-journal.json"

        if journal_path.exists():
            raise RuntimeError(
                "Existing recovery journal. Manual review required."
            )

        metadata = validate(root, stage)

        backup = (
            root / ".phase55-backups"
            / ("promotion-" + uuid.uuid4().hex)
        )
        backup.mkdir(parents=True, exist_ok=False)

        for ticker in TICKERS:
            source = report_path(root, ticker)
            target = report_path(backup, ticker)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

            if digest(target) != metadata["original_sha256"][ticker]:
                raise RuntimeError(f"Backup failed: {ticker}")

        journal = {
            "status": "prepared",
            "run_id": metadata["run_id"],
            "backup": str(backup),
            "original_sha256": metadata["original_sha256"],
            "staged_sha256": metadata["staged_sha256"],
            "replaced": [],
        }
        write_json_atomic(journal_path, journal)

        prepared = {}

        try:
            for ticker in TICKERS:
                destination = report_path(root, ticker)
                fd, name = tempfile.mkstemp(
                    prefix=f".cira-{ticker}-",
                    dir=destination.parent,
                )
                os.close(fd)
                prepared[ticker] = pathlib.Path(name)
                shutil.copyfile(
                    report_path(stage, ticker), prepared[ticker]
                )

                if digest(prepared[ticker]) != (
                    metadata["staged_sha256"][ticker]
                ):
                    raise RuntimeError(f"Prepared hash failed: {ticker}")

            for ticker in TICKERS:
                destination = report_path(root, ticker)

                if digest(destination) != (
                    metadata["original_sha256"][ticker]
                ):
                    raise RuntimeError(
                        f"Concurrent modification detected: {ticker}"
                    )

                journal["status"] = f"replacing_{ticker}"
                write_json_atomic(journal_path, journal)

                os.replace(prepared[ticker], destination)
                journal["replaced"].append(ticker)
                write_json_atomic(journal_path, journal)

            for ticker in TICKERS:
                if digest(report_path(root, ticker)) != (
                    metadata["staged_sha256"][ticker]
                ):
                    raise RuntimeError(
                        f"Final hash failed: {ticker}"
                    )

            journal["status"] = "complete"
            write_json_atomic(journal_path, journal)

            print("PROMOTION: PASS")
            print("Backup:", backup)
            print("Run ID:", metadata["run_id"])

        except Exception:
            journal["status"] = "recovery_required"
            write_json_atomic(journal_path, journal)
            raise

        finally:
            for path in prepared.values():
                if path.exists():
                    path.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, type=pathlib.Path)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument(
        "--confirm-local-replacement", action="store_true"
    )
    args = parser.parse_args()

    if args.confirm_local_replacement and not args.promote:
        parser.error("Confirmation requires --promote")

    if args.promote and not args.confirm_local_replacement:
        parser.error("Explicit confirmation required")

    root = ROOT.resolve()
    stage = args.stage.resolve()

    if not args.promote:
        metadata = validate(root, stage)
        print("VALIDATION: PASS")
        print("Run ID:", metadata["run_id"])
        print("Reports replaced: NO")
        print("Azure operations: NONE")
        return

    promote(root, stage)


if __name__ == "__main__":
    main()