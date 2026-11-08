"""CIRA versioned report publisher.

Default: local dry-run, no network operations.
Live mode: requires --publish and --confirm-live-publish.
Not yet approved for unattended production use.
"""

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


TICKERS = ("AAPL", "MSFT")
PREFIX = "financial-intelligence/batches"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(source):
    batch_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )

    entries = []
    payloads = {}

    for ticker in TICKERS:
        path = (
            source / "reports" / "company-intelligence"
            / f"{ticker}-company-intelligence.json"
        )

        data = path.read_bytes()
        report = json.loads(data)

        if report.get("ticker") != ticker:
            raise ValueError(f"Ticker mismatch: {ticker}")

        if report.get("schema_version") != "1.0":
            raise ValueError(f"Schema mismatch: {ticker}")

        quality = report.get("data_quality")
        if not isinstance(quality, dict):
            raise ValueError(f"Missing data quality: {ticker}")

        if quality.get("independently_verified_bcg") is not False:
            raise ValueError(f"Invalid BCG flag: {ticker}")

        if quality.get("investment_recommendation") is not None:
            raise ValueError(f"Recommendation detected: {ticker}")

        blob = (
            f"{PREFIX}/{batch_id}/company-intelligence/"
            f"{ticker}-company-intelligence.json"
        )

        entries.append({
            "ticker": ticker,
            "blob_path": blob,
            "sha256": digest(data),
            "size_bytes": len(data),
        })

        payloads[blob] = data

    manifest = {
        "schema_version": "1.0",
        "batch_id": batch_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "report_count": len(entries),
        "reports": entries,
    }

    manifest_path = f"{PREFIX}/{batch_id}/manifest.json"

    return manifest, manifest_path, payloads


def upload_and_verify(container, blob_name, data):
    from azure.storage.blob import ContentSettings
    client = container.get_blob_client(blob_name)

    client.upload_blob(
        data,
        overwrite=False,
        content_settings=ContentSettings(
            content_type="application/json"
        ),
    )

    downloaded = client.download_blob().readall()

    if digest(downloaded) != digest(data):
        raise RuntimeError(
            f"Uploaded blob integrity mismatch: {blob_name}"
        )

    if len(downloaded) != len(data):
        raise RuntimeError(
            f"Uploaded blob size mismatch: {blob_name}"
        )


def publish(manifest, manifest_path, payloads):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import (
        BlobServiceClient,
        ContentSettings,
    )

    account = os.environ.get("CIRA_STORAGE_ACCOUNT")
    container_name = os.environ.get(
        "CIRA_REPORTS_CONTAINER", "reports"
    )

    if not account:
        raise ValueError("CIRA_STORAGE_ACCOUNT is required")

    credential = DefaultAzureCredential()

    try:
        service = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=credential,
        )

        container = service.get_container_client(container_name)

        for blob_name, data in payloads.items():
            upload_and_verify(container, blob_name, data)
            print(f"VERIFIED: {blob_name}")

        manifest_data = json.dumps(
            manifest, indent=2
        ).encode("utf-8")

        upload_and_verify(
            container, manifest_path, manifest_data
        )

        print(f"COMMITTED: {manifest_path}")

    finally:
        credential.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root", required=True, type=Path
    )
    parser.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--confirm-live-publish", action="store_true"
    )

    args = parser.parse_args()

    if args.confirm_live_publish and not args.publish:
        parser.error("--confirm-live-publish requires --publish")

    if args.publish and not args.confirm_live_publish:
        parser.error(
            "Live publishing requires --confirm-live-publish"
        )

    manifest, manifest_path, payloads = prepare(
        args.source_root.resolve()
    )

    print("=== CIRA VERSIONED PUBLISHER ===")
    print("Batch:", manifest["batch_id"])

    for entry in manifest["reports"]:
        print(
            f"READY: {entry['ticker']} "
            f"SHA256={entry['sha256']} "
            f"SIZE={entry['size_bytes']}"
        )

    print("Manifest:", manifest_path)

    if not args.publish:
        print("DRY-RUN SUCCESS")
        print("No Azure connection or upload performed.")
        return

    publish(manifest, manifest_path, payloads)
    print("VERSIONED BATCH PUBLISHED SUCCESSFULLY")


if __name__ == "__main__":
    main()