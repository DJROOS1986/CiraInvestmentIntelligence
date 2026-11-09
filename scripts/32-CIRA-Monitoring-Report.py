#!/usr/bin/env python3
"""Read-only CIRA monitoring history summary. No report files written."""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

NAMES = {"26-CIRA-Safe-Promotion.py", "28-CIRA-Recovery-Candidate.py", "29-CIRA-Promotion-Recovery.py", "acceptance_record", "AAPL_report", "MSFT_report", "promotion_journal", "promotion_lock", "recovery_advisory"}
SEVERITY = {"PASS": 0, "WARN": 1, "FAIL": 2}

def validate(data):
    if not isinstance(data, dict) or data.get("phase") != "5.6" or data.get("mode") != "read_only" or data.get("recovery_authorized") is not False:
        raise ValueError("Invalid read-only monitoring snapshot")
    checks = data.get("checks")
    if not isinstance(checks, list) or len(checks) != 9:
        raise ValueError("Snapshot must contain nine checks")
    if any(not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("status"), str) or c["status"] not in SEVERITY or not isinstance(c.get("message"), str) for c in checks):
        raise ValueError("Malformed check")
    if {c["name"] for c in checks} != NAMES:
        raise ValueError("Incorrect check names")
    overall = max((c["status"] for c in checks), key=SEVERITY.__getitem__)
    if data.get("overall_status") != overall:
        raise ValueError("Inconsistent overall status")
    stamp = data.get("timestamp_utc")
    if not isinstance(stamp, str):
        raise ValueError("Invalid timestamp")
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must be UTC")
    if not isinstance(data.get("journal_status"), str):
        raise ValueError("Invalid journal status")
    return data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        # Only read the expected history path relative to the installed script.
        expected = Path(__file__).resolve().parent.parent / "monitoring" / "history"
        if args.history_dir.absolute() != expected.absolute() or not expected.is_dir():
            raise ValueError("History directory must be the existing CIRA history directory")
        for parent in [args.history_dir.absolute(), *args.history_dir.absolute().parents]:
            if parent.is_symlink():
                raise ValueError("Symbolic-link history path prohibited")
        if args.history_dir.absolute() != args.history_dir.resolve(strict=True):
            raise ValueError("Redirected history path prohibited")
        files = sorted(args.history_dir.glob("cira-health-*.json"))
        statuses = Counter()
        latest = None
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise ValueError("Unexpected history entry")
            snapshot = validate(json.loads(path.read_text(encoding="utf-8")))
            statuses[snapshot["overall_status"]] += 1
            if latest is None or snapshot["timestamp_utc"] > latest["timestamp_utc"]:
                latest = snapshot
        result = {"mode": "read_only", "history_count": len(files), "status_counts": {k: statuses[k] for k in ("PASS", "WARN", "FAIL")}, "latest_timestamp_utc": latest["timestamp_utc"] if latest else None, "latest_status": latest["overall_status"] if latest else None}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"report": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
