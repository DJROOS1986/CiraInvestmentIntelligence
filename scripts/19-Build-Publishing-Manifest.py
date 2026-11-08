"""Build a local CIRA publishing manifest. No Azure operations."""

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


TICKERS = ("AAPL", "MSFT")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(source, batch_id):
    reports = []
    run_ids = set()

    for ticker in TICKERS:
        relative = (
            Path("reports")
            / "company-intelligence"
            / f"{ticker}-company-intelligence.json"
        )

        path = source / relative

        if not path.is_file():
            raise FileNotFoundError(path)

        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)

        if document.get("ticker") != ticker:
            raise ValueError(f"Ticker mismatch: {ticker}")

        if document.get("schema_version") != "1.0":
            raise ValueError(f"Schema mismatch: {ticker}")

        quality = document.get("data_quality")

        if not isinstance(quality, dict):
            raise ValueError(f"Missing quality metadata: {ticker}")

        if quality.get("independently_verified_bcg") is not False:
            raise ValueError(f"BCG verification flag invalid: {ticker}")

        if quality.get("investment_recommendation") is not None:
            raise ValueError(
                f"Unexpected investment recommendation: {ticker}"
            )

        run_id = document.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(f"Missing or invalid run_id: {ticker}")
        run_ids.add(run_id)

        blob_path = (
            f"financial-intelligence/batches/{batch_id}/"
            f"company-intelligence/"
            f"{ticker}-company-intelligence.json"
        )

        reports.append({
            "ticker": ticker,
            "blob_path": blob_path,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        })

    if len(run_ids) != 1:
        raise ValueError("Mixed processing run IDs detected")

    return {
        "run_id": next(iter(run_ids)),
        "schema_version": "1.0",
        "batch_id": batch_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "prepared_not_published",
        "report_count": len(reports),
        "reports": reports,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_root.resolve()

    batch_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )

    manifest = build_manifest(source, batch_id)

    print(json.dumps(manifest, indent=2))
    print("\nLOCAL MANIFEST VALIDATION SUCCESS")
    print("No Azure uploads performed.")


if __name__ == "__main__":
    main()