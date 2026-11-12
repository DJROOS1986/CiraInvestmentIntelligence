import importlib.util
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def stage13(monkeypatch, tmp_path):
    monkeypatch.setenv("CIRA_RUN_STATE", str(tmp_path / "run-exclusions.json"))
    monkeypatch.syspath_prepend(str(ROOT / "ingestion"))
    spec = importlib.util.spec_from_file_location("cira_stage13", ROOT / "scripts" / "13-Ingest-Market-Prices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    waits = []
    monkeypatch.setattr(time, "sleep", waits.append)
    module.waits = waits
    return module


def refusing(times, result):
    calls = {"n": 0}

    def fetch(symbol):
        calls["n"] += 1
        if calls["n"] <= times:
            raise requests.HTTPError("400 Client Error: Bad Request")
        return result
    fetch.calls = calls
    return fetch


def test_success_after_two_refusals(stage13, monkeypatch):
    fetch = refusing(2, [{"date": "2026-11-12", "close": 1.0}])
    monkeypatch.setattr(stage13, "fetch_prices", fetch)
    assert stage13.fetch_with_retry("CDNS") == [{"date": "2026-11-12", "close": 1.0}]
    assert fetch.calls["n"] == 3
    assert stage13.waits == [3, 8]


def test_gives_up_after_three_attempts(stage13, monkeypatch):
    fetch = refusing(5, [])
    monkeypatch.setattr(stage13, "fetch_prices", fetch)
    with pytest.raises(requests.HTTPError):
        stage13.fetch_with_retry("TER")
    assert fetch.calls["n"] == 3


def test_no_retry_for_missing_data(stage13, monkeypatch):
    calls = {"n": 0}

    def fetch(symbol):
        calls["n"] += 1
        raise RuntimeError("No market data")
    monkeypatch.setattr(stage13, "fetch_prices", fetch)
    with pytest.raises(RuntimeError):
        stage13.fetch_with_retry("ZZZ")
    assert calls["n"] == 1 and stage13.waits == []
