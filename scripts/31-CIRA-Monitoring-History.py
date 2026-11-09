import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

CHECK_NAMES = {
    "26-CIRA-Safe-Promotion.py",
    "28-CIRA-Recovery-Candidate.py",
    "29-CIRA-Promotion-Recovery.py",
    "acceptance_record",
    "AAPL_report",
    "MSFT_report",
    "promotion_journal",
    "promotion_lock",
    "recovery_advisory",
}

SEVERITY = {"PASS": 0, "WARN": 1, "FAIL": 2}

REQUIRED = {
    "phase", "mode", "timestamp_utc",
    "overall_status", "journal_status",
    "recovery_authorized", "checks",
}

def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Snapshot must be a JSON object")

    if not REQUIRED.issubset(data):
        raise ValueError("Missing required snapshot fields")

    if data["phase"] != "5.6":
        raise ValueError("Unsupported monitoring phase")

    if data["mode"] != "read_only":
        raise ValueError("Monitoring must be read_only")

    if data["recovery_authorized"] is not False:
        raise ValueError("Recovery authorization is prohibited")

    if not isinstance(data["journal_status"], str):
        raise ValueError("Invalid journal status")

    if not isinstance(data["timestamp_utc"], str):
        raise ValueError("Invalid timestamp type")

    try:
        timestamp = datetime.fromisoformat(
            data["timestamp_utc"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Invalid ISO timestamp") from exc

    if timestamp.tzinfo is None:
        raise ValueError("Timestamp must include UTC timezone")

    if timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must be UTC")

    checks = data["checks"]

    if not isinstance(checks, list) or len(checks) != 9:
        raise ValueError("Exactly nine checks required")

    names = []

    for item in checks:
        if not isinstance(item, dict):
            raise ValueError("Invalid check object")

        if not {"name", "status", "message"}.issubset(item):
            raise ValueError("Incomplete check object")

        if not isinstance(item["name"], str):
            raise ValueError("Invalid check name")

        if not isinstance(item["status"], str) or item["status"] not in SEVERITY:
            raise ValueError("Invalid check status")

        if not isinstance(item["message"], str):
            raise ValueError("Invalid check message")

        names.append(item["name"])

    if len(set(names)) != 9 or set(names) != CHECK_NAMES:
        raise ValueError("Missing, duplicate, or unknown check names")

    actual = max(
        (item["status"] for item in checks),
        key=lambda status: SEVERITY[status],
    )

    if data["overall_status"] != actual:
        raise ValueError("Overall status does not match checks")

    return data

def main():
    parser = argparse.ArgumentParser(
        description="CIRA monitoring history validator"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--history-dir", type=Path)

    args = parser.parse_args()

    if args.save and args.history_dir is None:
        parser.error("--save requires --history-dir")

    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        validated = validate(data)

        result = {
            "validation": "PASS",
            "overall_status": validated["overall_status"],
            "check_count": len(validated["checks"]),
            "saved": False,
        }

        if args.save:
            directory = args.history_dir

            expected_directory = (
                Path(__file__).resolve().parent.parent
                / "monitoring"
                / "history"
            )

            if directory.absolute() != expected_directory.absolute():
                raise ValueError("History directory is outside the permitted CIRA destination")

            if not directory.is_dir():
                raise ValueError("History directory must already exist")

            # Reject symbolic links and junctions in the directory path.
            current = directory.absolute()
            while True:
                if current.is_symlink():
                    raise ValueError("History directory path contains a symbolic link")
                if current.parent == current:
                    break
                current = current.parent

            # The supplied path must resolve without redirection.
            if directory.absolute() != directory.resolve(strict=True):
                raise ValueError("History directory path redirection is prohibited")

            timestamp = datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%S%fZ"
            )
            filename = f"cira-health-{timestamp}-{uuid4().hex}.json"
            destination = directory / filename

            payload = json.dumps(
                validated, indent=2, sort_keys=True
            ).encode("utf-8")

            created = False
            try:
                with destination.open("xb") as output:
                    created = True
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
            except OSError:
                if created:
                    try:
                        destination.unlink()
                    except OSError:
                        pass
                raise

            result["saved"] = True
            result["history_file"] = str(destination)

        print(json.dumps(result, indent=2))
        return 0

    except (OSError, ValueError, TypeError) as exc:
        print(
            json.dumps({
                "validation": "FAIL",
                "error": str(exc),
                "saved": False,
            }),
            file=sys.stdout,
        )
        return 1

if __name__ == "__main__":
    sys.exit(main())