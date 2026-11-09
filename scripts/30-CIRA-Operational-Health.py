import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

EXPECTED = {
    "26-CIRA-Safe-Promotion.py":
        "2AE1A7F4E9E8E6B1FAEE5A266D33EE1ECA05D4ECDA5B10AB5965487F7F3EC342",
    "28-CIRA-Recovery-Candidate.py":
        "B61FCC0867DD6B5A4D88B493829E31D28D21E380CDDCB0BA2D79ED3DA7336295",
    "29-CIRA-Promotion-Recovery.py":
        "B40535EBCAE04B40E10B84329339E79836D67C7064DB200CDB1A44723A8034B0",
}

RECORD_HASH = (
    "64E20C3E15510EB9EFD4EEB17441B9ABFE8BFEEBD68B626BB4580A2031DD8182"
)

SEVERITY = {"PASS": 0, "WARN": 1, "FAIL": 2}

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def check(name, status, message):
    return {"name": name, "status": status, "message": message}

def evaluate(root):
    results = []

    for filename, expected in EXPECTED.items():
        path = root / "scripts" / filename
        try:
            valid = digest(path) == expected
            status = "PASS" if valid else "FAIL"
            message = "Hash verified" if valid else "Hash mismatch"
        except OSError:
            status, message = "FAIL", "Missing or unreadable source"
        results.append(check(filename, status, message))

    record = root / "docs" / "acceptance" / (
        "CIRA-Phase-5.5-Final-Acceptance.md"
    )
    try:
        valid = digest(record) == RECORD_HASH
        status = "PASS" if valid else "FAIL"
        message = "Hash verified" if valid else "Hash mismatch"
    except OSError:
        status, message = "FAIL", "Missing or unreadable record"
    results.append(check("acceptance_record", status, message))

    for ticker in ("AAPL", "MSFT"):
        path = root / "reports" / "company-intelligence" / (
            f"{ticker}-company-intelligence.json"
        )
        present = path.is_file()
        results.append(check(
            f"{ticker}_report",
            "PASS" if present else "FAIL",
            "Present" if present else "Missing"
        ))

    journal = root / ".phase55-promotion-journal.json"
    journal_status = "absent"
    journal_present = journal.exists()

    if journal_present:
        try:
            data = json.loads(journal.read_text(encoding="utf-8"))
            journal_status = data.get("status", "unknown")
            if not isinstance(journal_status, str):
                journal_status = "unknown"
        except (OSError, ValueError, UnicodeError):
            journal_status = "unreadable"

    results.append(check(
        "promotion_journal",
        "WARN" if journal_present else "PASS",
        f"Journal: {journal_status}; manual review required"
        if journal_present else "No journal present"
    ))

    lock_present = (root / ".phase55-promotion.lock").exists()
    results.append(check(
        "promotion_lock",
        "WARN" if lock_present else "PASS",
        "Lock present; manual review required"
        if lock_present else "No lock present"
    ))

    review = journal_present or lock_present
    results.append(check(
        "recovery_advisory",
        "WARN" if review else "PASS",
        "Manual review required; recovery not authorized"
        if review else "No recovery indicators detected"
    ))

    overall = max(
        (item["status"] for item in results),
        key=lambda status: SEVERITY[status]
    )

    return {
        "phase": "5.6",
        "mode": "read_only",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "journal_status": journal_status,
        "recovery_authorized": False,
        "checks": results
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    print(json.dumps(evaluate(root), indent=2))

if __name__ == "__main__":
    main()