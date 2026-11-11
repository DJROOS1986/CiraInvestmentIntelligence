#!/usr/bin/env python3
"""Run the CIRA financial pipeline in Azure or locally."""

import importlib.util
import json
import os
import pathlib
import runpy
import sys
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = pathlib.Path(
    os.environ.get(
        "CIRA_CONFIG_PATH",
        str(ROOT / "ingestion" / "config.json"),
    )
)
INGESTION_SCRIPT = ROOT / "ingestion" / "ingest_sec.py"
SOURCE = ROOT / "ingestion" / "output" / "sec" / "companyfacts"
REPORTS = ROOT / "reports"


def load_ingestion():
    spec = importlib.util.spec_from_file_location(
        "cira_ingestion", INGESTION_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upload_file(container, path, blob_name):
    data = path.read_bytes()
    container.upload_blob(
        name=blob_name,
        data=data,
        overwrite=True,
        content_settings=ContentSettings(
            content_type=(
                "application/json"
                if path.suffix == ".json"
                else "text/plain"
            )
        ),
    )
    print(f"UPLOADED: {container.container_name}/{blob_name}")


def run_stage(filename):
    try:
        runpy.run_path(str(ROOT / 'scripts' / filename), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f'Pipeline stage failed: {filename}') from exc


def main():
    ingestion = load_ingestion()
    __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["reset"]()
    if os.getenv("CIRA_SEC_USER_AGENT"):
        cfg = {
            "storage_account": os.environ["CIRA_STORAGE_ACCOUNT"],
            "container": os.environ.get(
                "CIRA_RAW_CONTAINER", "raw-filings"
            ),
            "sec_user_agent": os.environ["CIRA_SEC_USER_AGENT"],
            "companies": [
                *[{"ticker": c["ticker"], "cik": c["cik"]} for c in __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "universe.json").read_text(encoding="utf-8"))["companies"]],
            ],
        }
    else:
        cfg = ingestion.load_config(CONFIG)

    account = os.getenv(
        "CIRA_STORAGE_ACCOUNT", cfg["storage_account"]
    )
    raw_container_name = os.getenv(
        "CIRA_RAW_CONTAINER", cfg["container"]
    )
    reports_container_name = os.getenv(
        "CIRA_REPORTS_CONTAINER", "reports"
    )

    credential = DefaultAzureCredential(
        exclude_interactive_browser_credential=True
    )
    service = BlobServiceClient(
        account_url=f"https://{account}.blob.core.windows.net",
        credential=credential,
    )
    raw_container = service.get_container_client(raw_container_name)
    reports_container = service.get_container_client(
        reports_container_name
    )

    run_stamp = datetime.now(timezone.utc).strftime(
        "%Y/%m/%d/%H%M%S"
    )

    for index, company in enumerate(cfg["companies"]):
        ticker = str(company["ticker"]).upper()
        cik = str(company["cik"]).zfill(10)

        if index:
            import time
            time.sleep(0.25)

        payload = ingestion.fetch_companyfacts(
            cik, cfg["sec_user_agent"]
        )

        import hashlib
        digest = hashlib.sha256(payload).hexdigest()
        relative = pathlib.Path(
            f"{ticker}/CIK{cik}/{run_stamp}-{digest[:12]}.json"
        )
        local_path = SOURCE / relative
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)

        blob_name = "sec/companyfacts/" + relative.as_posix()
        raw_container.upload_blob(
            name=blob_name,
            data=payload,
            overwrite=False,
            metadata={
                "ticker": ticker.lower(),
                "cik": cik,
                "sha256": digest,
                "source": "sec-companyfacts",
            },
            content_settings=ContentSettings(
                content_type="application/json"
            ),
        )
        print(f"INGESTED: {ticker}")

    runpy.run_path(
        str(ROOT / "scripts" / "07-Generate-Financial-Reports.py"),
        run_name="__main__",
    )
    runpy.run_path(
        str(ROOT / "scripts" / "10-Analyze-Financial-Reports.py"),
        run_name="__main__",
    )

    expected = [
        *[REPORTS / "financial" / f"{t}-financial-report.json" for t in __import__("runpy").run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "portfolio-engine" / "run_state.py"))["active_tickers"]()],
        REPORTS / "analysis" / "company-comparison.json",
        REPORTS / "analysis" / "company-comparison.txt",
    ]

    for path in expected:
        if not path.is_file():
            raise FileNotFoundError(
                f"Required report missing: {path}"
            )

        relative = path.relative_to(REPORTS).as_posix()
        upload_file(
            reports_container,
            path,
            f"financial-intelligence/{relative}",
        )

    # Publish a complete immutable research batch only after every stage succeeds.
    # Legacy financial outputs above remain available if the market provider fails.
    for stage in ('13-Ingest-Market-Prices.py', '14-Analyze-Market-Prices.py',
                  '16-Refresh-Company-Intelligence.py'):
        run_stage(stage)
    publisher_spec = importlib.util.spec_from_file_location(
        'cira_publisher', ROOT / 'scripts' / '20-Publish-Versioned-Reports.py')
    publisher = importlib.util.module_from_spec(publisher_spec)
    publisher_spec.loader.exec_module(publisher)
    manifest, manifest_path, payloads = publisher.prepare(ROOT)
    publisher.publish(manifest, manifest_path, payloads, container=reports_container)

    print("CIRA CLOUD PIPELINE: SUCCESS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"CIRA CLOUD PIPELINE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


