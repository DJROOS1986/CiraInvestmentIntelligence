#!/usr/bin/env python3
"""Fetch SEC Company Facts and archive immutable dated snapshots to Azure Blob Storage."""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def load_config(path):
    config = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for key in ("storage_account", "container", "companies", "sec_user_agent"):
        if not config.get(key):
            raise ValueError(f"Missing configuration: {key}")
    if "@" not in config["sec_user_agent"] or "example.com" in config["sec_user_agent"]:
        raise ValueError("Set sec_user_agent to your actual application name and contact email")
    return config


def fetch_companyfacts(cik, user_agent, attempts=4):
    cik = str(cik).zfill(10)
    if not cik.isdigit() or len(cik) != 10:
        raise ValueError("CIK must be a numeric identifier with at most 10 digits")
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    request = urllib.request.Request(url, headers={
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = response.read()
            doc = json.loads(payload)
            if not isinstance(doc, dict) or "facts" not in doc or "cik" not in doc:
                raise ValueError(f"Unexpected SEC response for CIK {cik}")
            if int(doc["cik"]) != int(cik):
                raise ValueError("SEC CIK mismatch")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            delay = min(2 ** attempt * 5, 30)
            print(f"SEC HTTP {exc.code}; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(min(2 ** attempt * 5, 30))
    raise RuntimeError("Unreachable retry state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="ingestion/config.json")
    parser.add_argument("--dry-run", action="store_true", help="Download locally, do not upload")
    parser.add_argument("--output-dir", default="ingestion/output")
    args = parser.parse_args()
    cfg = load_config(args.config)
    client = None
    if not args.dry_run:
        from azure.identity import AzureCliCredential
        from azure.storage.blob import BlobServiceClient, ContentSettings
        credential = AzureCliCredential()
        client = BlobServiceClient(
            account_url=f"https://{cfg['storage_account']}.blob.core.windows.net",
            credential=credential,
        ).get_container_client(cfg["container"])
    errors = []
    for i, company in enumerate(cfg["companies"]):
        ticker = str(company["ticker"]).upper()
        cik = str(company["cik"]).zfill(10)
        try:
            if i:
                time.sleep(0.25)  # Stay well below SEC's 10 requests/second guidance.
            payload = fetch_companyfacts(cik, cfg["sec_user_agent"])
            digest = hashlib.sha256(payload).hexdigest()
            stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
            blob_name = f"sec/companyfacts/{ticker}/CIK{cik}/{stamp}-{digest[:12]}.json"
            if args.dry_run:
                output = pathlib.Path(args.output_dir) / blob_name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)
                print(f"DRY RUN {ticker}: {output} ({len(payload)} bytes; sha256={digest})")
            else:
                client.upload_blob(
                    name=blob_name,
                    data=payload,
                    overwrite=False,
                    metadata={"ticker": ticker.lower(), "cik": cik, "sha256": digest, "source": "sec-companyfacts"},
                    content_settings=ContentSettings(content_type="application/json"),
                )
                print(f"UPLOADED {ticker}: {cfg['container']}/{blob_name} ({len(payload)} bytes)")
        except Exception as exc:
            errors.append(ticker)
            print(f"ERROR {ticker}: {exc}", file=sys.stderr)
    if errors:
        print(f"Failed companies: {', '.join(errors)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
