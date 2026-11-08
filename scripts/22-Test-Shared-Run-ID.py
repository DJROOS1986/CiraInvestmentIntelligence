"""CIRA shared processing-run ID prototype. Local tests only."""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone


def new_run_id():
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    return f"{timestamp}-{uuid.uuid4().hex[:12]}"


def attach_run_id(reports, run_id):
    if set(reports) != {"AAPL", "MSFT"}:
        raise ValueError("Expected exactly AAPL and MSFT")

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("Missing processing run ID")

    result = {}

    for ticker, report in reports.items():
        if not isinstance(report, dict):
            raise ValueError(f"{ticker}: invalid report")

        if report.get("ticker") != ticker:
            raise ValueError(f"{ticker}: ticker mismatch")

        if "run_id" in report:
            raise ValueError(f"{ticker}: report already has run_id")

        result[ticker] = dict(report)
        result[ticker]["run_id"] = run_id

    return result


def validate_shared_run(reports):
    if set(reports) != {"AAPL", "MSFT"}:
        raise ValueError("Expected exactly AAPL and MSFT")

    run_ids = []

    for ticker in ("AAPL", "MSFT"):
        report = reports[ticker]

        if report.get("ticker") != ticker:
            raise ValueError(f"{ticker}: ticker mismatch")

        run_id = report.get("run_id")

        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(f"{ticker}: missing run_id")

        run_ids.append(run_id)

    if run_ids[0] != run_ids[1]:
        raise ValueError("Mixed processing runs detected")

    return run_ids[0]


def main():
    root = Path(__file__).resolve().parents[1]

    reports = {}

    for ticker in ("AAPL", "MSFT"):
        path = (
            root
            / "reports"
            / "company-intelligence"
            / f"{ticker}-company-intelligence.json"
        )

        reports[ticker] = json.loads(
            path.read_text(encoding="utf-8")
        )

    run_id = new_run_id()

    print("=== SHARED RUN-ID PROTOTYPE ===")

    prepared = attach_run_id(reports, run_id)

    verified = validate_shared_run(prepared)

    assert verified == run_id
    print("PASS: Both companies share one run ID")

    assert all(
        "run_id" not in reports[ticker]
        for ticker in ("AAPL", "MSFT")
    )
    print("PASS: Original in-memory reports unchanged")

    mixed = {
        "AAPL": dict(prepared["AAPL"]),
        "MSFT": dict(prepared["MSFT"]),
    }

    mixed["MSFT"]["run_id"] = new_run_id()

    try:
        validate_shared_run(mixed)
    except ValueError as exc:
        assert "Mixed processing runs" in str(exc)
        print("PASS: Mixed processing runs rejected")
    else:
        raise AssertionError("Mixed processing runs accepted")

    missing = {
        "AAPL": dict(prepared["AAPL"]),
        "MSFT": dict(prepared["MSFT"]),
    }

    del missing["MSFT"]["run_id"]

    try:
        validate_shared_run(missing)
    except ValueError as exc:
        assert "missing run_id" in str(exc)
        print("PASS: Missing run ID rejected")
    else:
        raise AssertionError("Missing run ID accepted")

    print("\n=== SUMMARY ===")
    print("PASSED: 4/4 checks")
    print("Run ID:", run_id)
    print("No reports written.")
    print("No Azure operations.")


if __name__ == "__main__":
    main()
