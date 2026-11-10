"""Read-only check: does CIRA capture prices before the US market close?

1. Flags every batch that was created BEFORE the official US close (16:00 New York time)
   on its own latest market date. Such a "close" is most likely an intraday price.
2. Compares the close of the same ticker + trading date across ALL published batches.
   If an evening batch and the next morning batch disagree for the same date, the evening
   value was not the final close.

Changes nothing: it only lists and downloads blobs.

Usage (repo root, .venv active, signed in with `az login`):
    python scripts/30-Check-Price-Consistency.py
    python scripts/30-Check-Price-Consistency.py --account stciradeva2pjnb --container reports

Exit codes: 0 = consistent, 1 = intraday risk or differences found, 2 = data not in expected shape.
Limitation: US early-close days (e.g. day after Thanksgiving) are not modelled.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient

PREFIX = "financial-intelligence/batches/"


def nth_sunday(year, month, n):
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + timedelta(weeks=n - 1)


def us_close_utc(day):
    """16:00 New York time on `day`, expressed in UTC (US DST: 2nd Sunday March - 1st Sunday Nov)."""
    in_dst = nth_sunday(day.year, 3, 2) <= day < nth_sunday(day.year, 11, 1)
    offset_hours = 4 if in_dst else 5
    return datetime(day.year, day.month, day.day, 16 + offset_hours, tzinfo=timezone.utc)


def batch_time(batch_id):
    try:
        return datetime.strptime(batch_id.split("-")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def find_records(doc):
    if isinstance(doc, list) and doc and isinstance(doc[0], dict) and {"date", "close"} <= doc[0].keys():
        return doc
    if not isinstance(doc, dict):
        return None
    if isinstance(doc.get("records"), list):
        return doc["records"]
    for value in doc.values():
        found = find_records(value)
        if found:
            return found
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account", default="stciradeva2pjnb")
    parser.add_argument("--container", default="reports")
    args = parser.parse_args()

    container = ContainerClient(
        account_url=f"https://{args.account}.blob.core.windows.net",
        container_name=args.container,
        credential=DefaultAzureCredential(),
    )

    by_batch = defaultdict(list)
    for blob in container.list_blobs(name_starts_with=PREFIX):
        parts = blob.name[len(PREFIX):].split("/")
        if len(parts) > 1:
            by_batch[parts[0]].append(blob.name)
    if not by_batch:
        print(f"No batches found under {PREFIX}")
        return 2

    price_blobs = {b: [n for n in names if "/market-data/" in n and n.endswith(".json")] for b, names in by_batch.items()}
    if not any(price_blobs.values()):
        latest = sorted(by_batch)[-1]
        print(f"No */market-data/*.json blobs found. Files in latest batch {latest}:")
        for name in sorted(by_batch[latest]):
            print(f"   {name}")
        return 2

    closes = defaultdict(dict)   # (ticker, date) -> {batch_id: close}
    last_dates = {}              # (batch_id, ticker) -> latest market date in that batch
    for batch, names in sorted(price_blobs.items()):
        for name in names:
            doc = json.loads(container.download_blob(name).readall())
            records = find_records(doc)
            if not records or not all(isinstance(r, dict) and "date" in r and "close" in r for r in records):
                keys = list(doc)[:15] if isinstance(doc, dict) else type(doc).__name__
                print(f"Unexpected structure in {name}. Top-level keys: {keys}")
                return 2
            ticker = (doc.get("ticker") if isinstance(doc, dict) else None) or name.rsplit("/", 1)[-1].split("-")[0].split(".")[0]
            for record in records:
                closes[(ticker, str(record["date"])[:10])][batch] = float(record["close"])
            last_dates[(batch, ticker)] = max(str(r["date"])[:10] for r in records)

    print(f"Batches inspected: {len(price_blobs)}   Price files: {sum(len(v) for v in price_blobs.values())}")

    print("\n1) Batches created before the US close on their latest market date")
    risky = 0
    for (batch, ticker), last in sorted(last_dates.items()):
        created = batch_time(batch)
        if created is None:
            continue
        close_at = us_close_utc(date.fromisoformat(last))
        if created < close_at:
            risky += 1
            print(f"   {batch}  {ticker}: market date {last}, batch {created:%Y-%m-%d %H:%M} UTC "
                  f"< US close {close_at:%H:%M} UTC  -> probably INTRADAY")
    if risky == 0:
        print("   none")

    print("\n2) Same ticker and date, different close across batches")
    diffs = 0
    for (ticker, day), per_batch in sorted(closes.items()):
        if len({round(v, 6) for v in per_batch.values()}) < 2:
            continue
        diffs += 1
        print(f"   {ticker} {day}:")
        for batch, value in sorted(per_batch.items()):
            print(f"      {batch}  {value:.4f}")
    if diffs == 0:
        print("   none")

    print("\nVerdict:", "ATTENTION - see above" if risky or diffs else "OK - no intraday captures or differences found")
    return 1 if (risky or diffs) else 0


if __name__ == "__main__":
    sys.exit(main())
