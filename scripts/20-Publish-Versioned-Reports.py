"""CIRA versioned report publisher.

Default: local dry-run, no network operations.
Live mode: requires --publish and --confirm-live-publish.
Cloud pipeline publishes validated immutable batches with a final latest pointer.
"""

import argparse
import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


TICKERS = __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["active_tickers"]()
PREFIX = "financial-intelligence/batches"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(source):
    batch_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )

    excluded = __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["check_threshold"]()
    TICKERS = __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["active_tickers"]()
    entries = []
    payloads = {}
    run_ids = set()

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

        run_id = report.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(f"Missing or invalid run_id: {ticker}")
        run_ids.add(run_id)

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

    if len(run_ids) != 1:
        raise ValueError("Mixed processing run IDs detected")

    manifest = {
        "run_id": next(iter(run_ids)),
        "schema_version": "1.0",
        "batch_id": batch_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "report_count": len(entries),
        "reports": entries,
        "excluded": excluded,
    }

    artifacts = []
    documents = {}
    for folder, suffix in (('financial', 'financial-report'),
                           ('market-data', 'daily-prices'),
                           ('market-analysis', 'market-analysis')):
        for ticker in TICKERS:
            path = source / 'reports' / folder / f'{ticker}-{suffix}.json'
            if not path.is_file():
                raise FileNotFoundError(f'Missing batch artifact: {path}')
            data = path.read_bytes()
            document = json.loads(data)
            if document.get('ticker', document.get('symbol')) != ticker:
                raise ValueError(f'Artifact ticker mismatch: {path.name}')
            relative = path.relative_to(source / 'reports').as_posix()
            documents[relative] = document
            blob = f'{PREFIX}/{batch_id}/{relative}'
            payloads[blob] = data
            artifacts.append({'path': relative, 'blob_path': blob,
                              'sha256': digest(data), 'size_bytes': len(data)})
    manifest['artifacts'] = artifacts
    now = datetime.now(timezone.utc)
    for entry in entries:
        ticker = entry['ticker']
        report = json.loads(payloads[entry['blob_path']])
        generated = datetime.fromisoformat(report['generated_at_utc'].replace('Z', '+00:00'))
        if generated.tzinfo is None or not 0 <= (now - generated).total_seconds() <= 36 * 3600:
            raise ValueError(f'Stale or invalid company report: {ticker}')
        prices = documents[f'market-data/{ticker}-daily-prices.json']
        dates = [date.fromisoformat(row['date']) for row in prices['records']]
        if len(dates) < 2 or dates != sorted(set(dates)):
            raise ValueError(f'Invalid price history dates: {ticker}')
        if not 0 <= (now.date() - dates[-1]).days <= 4:
            raise ValueError(f'Stale market observations: {ticker}')
        if report['market']['last_date'] != dates[-1].isoformat():
            raise ValueError(f'Mixed market snapshots: {ticker}')
        retrieved = datetime.fromisoformat(prices['retrieved_at_utc'].replace('Z', '+00:00'))
        if retrieved.tzinfo is None or not 0 <= (now - retrieved).total_seconds() <= 36 * 3600:
            raise ValueError(f'Stale market retrieval: {ticker}')

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


def publish(manifest, manifest_path, payloads, container=None):
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

    credential = None

    try:
        if container is None:
            credential = DefaultAzureCredential()
            service = BlobServiceClient(
                account_url=f"https://{account}.blob.core.windows.net",
                credential=credential,
            )
            container = service.get_container_client(container_name)

        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceNotFoundError
        pointer = container.get_blob_client('financial-intelligence/latest.json')
        etag = None
        try:
            current = pointer.download_blob()
            etag = current.properties.etag
            previous = json.loads(current.readall())
            if previous['created_at_utc'] >= manifest['created_at_utc']:
                raise ValueError('A newer batch is already current')
        except ResourceNotFoundError:
            pass

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

        pointer_data = json.dumps({
            'schema_version': '1.0', 'batch_id': manifest['batch_id'],
            'created_at_utc': manifest['created_at_utc'],
            'manifest_path': manifest_path, 'manifest_sha256': digest(manifest_data),
        }).encode('utf-8')
        options = {'overwrite': False}
        if etag:
            options = {'overwrite': True, 'etag': etag,
                       'match_condition': MatchConditions.IfNotModified}
        pointer.upload_blob(pointer_data, content_settings=ContentSettings(
            content_type='application/json'), **options)
        print('CURRENT: financial-intelligence/latest.json')

    finally:
        if credential is not None:
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
